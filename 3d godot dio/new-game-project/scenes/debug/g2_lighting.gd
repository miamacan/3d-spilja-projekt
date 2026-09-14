extends SceneTree
##
## G2 — lighting and atmosphere.
##
## Runs HEADLESS, no editor:
##   Godot --headless --path <project> --script res://scenes/debug/g2_lighting.gd
## It writes scenes/_main_g2_candidate.tscn; the caller verifies that and then
## moves it over scenes/main.tscn.
##
## Idempotent: every node it owns is looked up by name, created if missing and
## overwritten if present, so re-running is safe. It never touches Env, Water,
## Player or Audio, and only adds a child to FX.
##
## Notes worth keeping:
##  - Every enum is a NAMED constant, never an integer. A hand-written .tscn
##    enum int is the easiest thing to get silently wrong here, and a wrong
##    tonemap or environment-mode value looks exactly like a lighting bug.
##  - The Environment is saved as an EXTERNAL .tres so exposure / fog density /
##    glow can be retuned by editing that one file.
##    *** Re-running this script REBUILDS that file from the constants below,
##        so tune in ONE place: either here and re-run, or there and don't. ***
##  - Transforms come from the MARK_* empties inside cave_env.glb when they are
##    present, and fall back to values measured in cave.blend otherwise. The
##    script prints which of the two it used.
##

const ENV_PATH := "res://assets/env/cave_environment.tres"
const SCENE_PATH := "res://scenes/main.tscn"
const CANDIDATE_PATH := "res://scenes/_main_g2_candidate.tscn"

# --- fallbacks, measured in cave.blend and converted Z-up -> Y-up -------------
# Blender (x, y, z)  ->  Godot (x, z, -y)
const FALLBACK_SUN_DIR   := Vector3(0.4198, -0.8896, 0.1799)   # MARK_Skylight -Z
const FALLBACK_SUN_POS   := Vector3(-2.53, 30.3688, -7.68)     # MARK_Skylight origin
const FALLBACK_HERO_POS  := Vector3(0.0, 7.2, 14.0)            # MARK_HeroView origin
const FALLBACK_HERO_DIR  := Vector3(0.0, -0.1011, -0.9949)     # MARK_HeroView -Z
const FALLBACK_POOL_POS  := Vector3(2.5, -2.2818, -1.25)       # MARK_Pool_Volume origin
const FALLBACK_POOL_SIZE := Vector3(31.0, 5.0, 26.5)           # full extents

var _msgs: Array = []


func _initialize() -> void:
	_msgs = []
	var packed: PackedScene = ResourceLoader.load(SCENE_PATH, "PackedScene", ResourceLoader.CACHE_MODE_IGNORE)
	if packed == null:
		push_error("G2: could not load %s" % SCENE_PATH)
		quit(2); return
	# GEN_EDIT_STATE_MAIN is what keeps Env as an INSTANCE of cave_env.glb.
	# Without it, pack() bakes all 22 MB of the glb into main.tscn.
	var root := packed.instantiate(PackedScene.GEN_EDIT_STATE_MAIN)
	if root == null or root.name != "Main":
		push_error("G2: root is '%s', expected 'Main'." % (root.name if root else "<null>"))
		quit(3); return

	var markers := _collect_markers(root)

	var env := _build_environment()
	_apply_environment(root, env)
	_apply_skylight(root, markers)
	_apply_pool_fog(root, markers)
	_apply_fills(root)
	_apply_water_placeholder(root)
	_apply_lightmap(root)
	_apply_hero_cam(root, markers)
	_quiet_route_audit(root)

	# Write to a CANDIDATE path. Blender-side checks it (size, and that the glb
	# is still an ext_resource rather than baked in) before it replaces
	# main.tscn. Overwriting a good scene with a 22 MB baked one is not the kind
	# of mistake worth risking for one saved step.
	var ps := PackedScene.new()
	var perr := ps.pack(root)
	if perr != OK:
		push_error("G2: pack failed err %d" % perr)
		quit(4); return
	var serr := ResourceSaver.save(ps, CANDIDATE_PATH)
	# Read the file back. "The script said it applied it" is not evidence that
	# it is in the scene; this is the check that would have caught the water
	# material being dropped.
	if serr == OK:
		var f := FileAccess.open(CANDIDATE_PATH, FileAccess.READ)
		if f:
			var body := f.get_as_text()
			f.close()
			for token in ["HeroCam", "FOG_PoolMurk", "FILL_Recess", "LightmapGI",
						  "water_placeholder.gd", "cave_environment.tres"]:
				if not (token in body):
					push_error("G2: '%s' MISSING from the packed scene" % token)
					_say("!! packed scene is missing '%s'" % token)
	_say("pack -> %s, save %s -> %s" % [
		"OK" if perr == OK else "ERR", CANDIDATE_PATH,
		"OK" if serr == OK else "ERR %d" % serr])

	print("=== G2 lighting ===")
	for m in _msgs:
		print("  " + str(m))
	quit(0 if serr == OK else 5)


func _say(s: String) -> void:
	_msgs.append(s)


# -----------------------------------------------------------------------------
# markers
# -----------------------------------------------------------------------------

func _collect_markers(root: Node) -> Dictionary:
	var found := {}
	var envnode := root.get_node_or_null("Env")
	if envnode != null:
		_walk_markers(envnode, found)
	if found.is_empty():
		_say("markers: NONE found under Env -- using measured fallbacks")
	else:
		var names := found.keys()
		names.sort()
		_say("markers: found %d under Env -> %s" % [found.size(), ", ".join(PackedStringArray(names))])
	return found


func _walk_markers(n: Node, out: Dictionary) -> void:
	if n is Node3D and String(n.name).begins_with("MARK_"):
		out[String(n.name)] = n
	for c in n.get_children():
		_walk_markers(c, out)


## "The way things travel" for a MARK_ empty.
##
## In Blender that is the empty's -Z. It does NOT arrive as -Z in Godot. The
## glTF +Y-up conversion is a change of basis (B' = C B C-inverse, with
## C: x,y,z -> x,z,-y), so the node's LOCAL AXIS LABELS are permuted too:
## Blender local +Z lands on Godot local +Y. The direction is therefore -basis.y.
##
## Verified against the real glb, not derived and hoped for:
##   MARK_Skylight  basis.y = (-0.4198, 0.8896, -0.1799) -> -y matches the
##                  (0.4198, -0.8896, 0.1799) measured in cave.blend
##   MARK_HeroView  basis.y = ( 0.0000, 0.1011,  0.9949) -> -y matches
##                  (0, -0.1011, -0.9949)
## Reading -basis.z instead gives a sun 90 deg out that points UP, and a hero
## camera pitched +84.2 deg -- the Blender X euler showing through verbatim.
func _marker_dir(markers: Dictionary, key: String, fallback: Vector3) -> Vector3:
	if markers.has(key):
		var m: Node3D = markers[key]
		var d := (-_gxform(m).basis.y).normalized()
		# The fallback is the same vector measured independently in Blender. If
		# the two disagree the convention has moved, and shipping a silently
		# wrong sun angle is worse than a loud complaint.
		var off := rad_to_deg(acos(clampf(d.dot(fallback.normalized()), -1.0, 1.0)))
		if off > 5.0:
			push_error("G2: %s marker dir %v is %.1f deg off the measured %v" % [key, d, off, fallback])
			_say("!! %s: marker dir %v disagrees with cave.blend by %.1f deg" % [key, d, off])
		return d
	_say("%s: not in glb, fallback dir %v" % [key, fallback])
	return fallback.normalized()


func _marker_pos(markers: Dictionary, key: String, fallback: Vector3) -> Vector3:
	if markers.has(key):
		var m: Node3D = markers[key]
		return _gxform(m).origin
	_say("%s: not in glb, fallback pos %v" % [key, fallback])
	return fallback



## `global_transform` errors and returns identity on a node that is not inside
## the SceneTree, which is exactly the case here: the scene is instantiated,
## mutated and re-packed without ever being added to the tree. Both of these
## walk the parent chain instead. This cost one full run -- every marker read
## came back as the origin and the sun pointed straight down.
func _gxform(n: Node3D) -> Transform3D:
	var t := Transform3D()
	var cur: Node = n
	while cur != null and cur is Node3D:
		t = (cur as Node3D).transform * t
		cur = cur.get_parent()
	return t


func _set_world(n: Node3D, xf: Transform3D) -> void:
	var p := n.get_parent()
	var pg := Transform3D()
	if p != null and p is Node3D:
		pg = _gxform(p as Node3D)
	n.transform = pg.affine_inverse() * xf


## Orthonormal basis whose -Z points along `dir`. Shared by the sun and the hero
## camera, which both use the "-Z is forward" convention.
func _basis_facing(dir: Vector3) -> Basis:
	var z := (-dir).normalized()
	var up := Vector3.UP
	if absf(z.dot(up)) > 0.999:
		up = Vector3.FORWARD
	var x := up.cross(z).normalized()
	var y := z.cross(x).normalized()
	return Basis(x, y, z)


# -----------------------------------------------------------------------------
# environment
# -----------------------------------------------------------------------------

func _build_environment() -> Environment:
	var env := Environment.new()

	# --- sky: real daylight outside, so the skylight hole and the tunnel mouth
	#     read as openings rather than as flat grey holes.
	var sky_mat := PhysicalSkyMaterial.new()
	sky_mat.turbidity = 4.0
	sky_mat.ground_color = Color(0.22, 0.24, 0.20)
	sky_mat.energy_multiplier = 1.0
	var sky := Sky.new()
	sky.sky_material = sky_mat
	sky.process_mode = Sky.PROCESS_MODE_REALTIME
	sky.radiance_size = Sky.RADIANCE_SIZE_128
	env.sky = sky
	env.background_mode = Environment.BG_SKY
	env.background_energy_multiplier = 1.0

	# --- ambient: deliberately low, the lightmap bake carries the bounce.
	env.ambient_light_source = Environment.AMBIENT_SOURCE_SKY
	env.ambient_light_sky_contribution = 0.15
	env.ambient_light_energy = 1.0
	env.reflected_light_source = Environment.REFLECTION_SOURCE_SKY

	# --- tonemap
	env.tonemap_mode = Environment.TONE_MAPPER_AGX
	env.tonemap_exposure = 2.6
	env.tonemap_white = 6.0

	# --- screen-space
	env.ssao_enabled = true
	env.ssao_radius = 1.0
	env.ssao_intensity = 2.0
	env.ssil_enabled = true
	env.ssr_enabled = false          # the water does its own reflections

	# --- glow: only the shafts and the openings should bloom
	env.glow_enabled = true
	env.glow_intensity = 0.6
	env.glow_bloom = 0.0
	env.glow_hdr_threshold = 1.6
	env.glow_hdr_scale = 2.0
	env.glow_blend_mode = Environment.GLOW_BLEND_MODE_SOFTLIGHT

	# --- volumetric fog: anisotropy high so the shafts read as directional
	env.volumetric_fog_enabled = true
	env.volumetric_fog_density = 0.015
	env.volumetric_fog_albedo = Color(0.78, 0.82, 0.86)
	env.volumetric_fog_emission = Color(0, 0, 0)
	env.volumetric_fog_emission_energy = 0.0
	env.volumetric_fog_anisotropy = 0.7
	env.volumetric_fog_length = 64.0
	env.volumetric_fog_detail_spread = 2.0
	env.volumetric_fog_gi_inject = 1.0
	env.volumetric_fog_ambient_inject = 0.0
	env.volumetric_fog_temporal_reprojection_enabled = true

	# --- adjustments
	env.adjustment_enabled = true
	env.adjustment_brightness = 1.0
	env.adjustment_contrast = 1.05
	env.adjustment_saturation = 0.95

	var err := ResourceSaver.save(env, ENV_PATH)
	if err != OK:
		push_error("G2: could not save %s (err %d)" % [ENV_PATH, err])
		_say("environment: SAVE FAILED err %d" % err)
	else:
		env.take_over_path(ENV_PATH)
		_say("environment: wrote %s (AgX, vol fog 0.03/aniso 0.7, SSAO+SSIL, glow soft)" % ENV_PATH)
	return env


func _apply_environment(root: Node, env: Environment) -> void:
	var we := root.get_node_or_null("WorldEnvironment") as WorldEnvironment
	if we == null:
		we = WorldEnvironment.new()
		we.name = "WorldEnvironment"
		root.add_child(we)
		we.owner = root
		_say("WorldEnvironment: created")
	we.environment = env

	# Exposure is tuned at the hero view, so it lives on a CameraAttributes the
	# whole world shares rather than on one camera.
	var ca := we.camera_attributes as CameraAttributesPractical
	if ca == null:
		ca = CameraAttributesPractical.new()
		we.camera_attributes = ca
	ca.auto_exposure_enabled = false
	ca.exposure_multiplier = 1.0
	_say("WorldEnvironment: environment assigned, auto-exposure OFF")


# -----------------------------------------------------------------------------
# key light
# -----------------------------------------------------------------------------

func _apply_skylight(root: Node, markers: Dictionary) -> void:
	var sun := root.get_node_or_null("Skylight") as DirectionalLight3D
	if sun == null:
		sun = DirectionalLight3D.new()
		sun.name = "Skylight"
		root.add_child(sun)
		sun.owner = root
		_say("Skylight: created")

	var dir := _marker_dir(markers, "MARK_Skylight", FALLBACK_SUN_DIR)
	var pos := _marker_pos(markers, "MARK_Skylight", FALLBACK_SUN_POS)
	_set_world(sun, Transform3D(_basis_facing(dir), pos))

	sun.light_color = Color(1.0, 0.957, 0.886)     # warm white
	sun.light_energy = 4.0
	sun.light_indirect_energy = 1.0
	sun.light_volumetric_fog_energy = 3.5
	sun.light_specular = 0.5

	sun.shadow_enabled = true
	sun.shadow_bias = 0.04
	sun.shadow_normal_bias = 1.5
	sun.directional_shadow_mode = DirectionalLight3D.SHADOW_PARALLEL_4_SPLITS
	sun.directional_shadow_blend_splits = true
	sun.directional_shadow_max_distance = 80.0
	sun.directional_shadow_split_1 = 0.08
	sun.directional_shadow_split_2 = 0.22
	sun.directional_shadow_split_3 = 0.52

	if pos.length() < 0.01 or absf(dir.y) < 0.01:
		push_error("G2: MARK_Skylight read as pos %v dir %v -- transform read failed" % [pos, dir])
		_say("!! Skylight transform read looks WRONG (pos %v dir %v)" % [pos, dir])
	var elev := rad_to_deg(asin(clampf(-dir.y, -1.0, 1.0)))
	_say("Skylight: dir %v, %.1f deg above horizontal, energy %.1f, fog energy %.1f"
		% [dir, elev, sun.light_energy, sun.light_volumetric_fog_energy])


# -----------------------------------------------------------------------------
# pool murk
# -----------------------------------------------------------------------------

func _apply_pool_fog(root: Node, markers: Dictionary) -> void:
	var holder := root.get_node_or_null("FX")
	if holder == null:
		holder = Node3D.new()
		holder.name = "FX"
		root.add_child(holder)
		holder.owner = root
		_say("FX: created")

	var fog := holder.get_node_or_null("FOG_PoolMurk") as FogVolume
	if fog == null:
		fog = FogVolume.new()
		fog.name = "FOG_PoolMurk"
		holder.add_child(fog)
		fog.owner = root
		_say("FOG_PoolMurk: created under FX")

	# MARK_Pool_Volume is the WATER BODY: in Blender it spans z -4.76 to +0.20,
	# i.e. it is entirely below the surface. The murk the brief asks for is the
	# air above the pool, so the box keeps the marker's footprint and is
	# re-seated to span y 0..5. Deliberate, and flagged rather than hidden.
	var foot := _marker_pos(markers, "MARK_Pool_Volume", FALLBACK_POOL_POS)
	var size := FALLBACK_POOL_SIZE
	if markers.has("MARK_Pool_Volume"):
		var m: Node3D = markers["MARK_Pool_Volume"]
		var s := _gxform(m).basis.get_scale()
		size = Vector3(absf(s.x) * 2.0, 5.0, absf(s.z) * 2.0)
	size.y = 5.0
	var fog_pos := Vector3(foot.x, 2.5, foot.z)
	_set_world(fog, Transform3D(Basis(), fog_pos))
	fog.shape = RenderingServer.FOG_VOLUME_SHAPE_BOX
	fog.size = size

	var mat := fog.material as FogMaterial
	if mat == null:
		mat = FogMaterial.new()
		fog.material = mat
	mat.density = 0.06                      # x2 the world density
	mat.albedo = Color(0.45, 0.68, 0.66)    # green-blue murk
	mat.emission = Color(0, 0, 0)
	mat.height_falloff = 0.35
	mat.edge_fade = 0.25
	_say("FOG_PoolMurk: box %v at %v, density %.3f, albedo green-blue"
		% [size, fog_pos, mat.density])


# -----------------------------------------------------------------------------
# fills
# -----------------------------------------------------------------------------

func _apply_fills(root: Node) -> void:
	var holder := root.get_node_or_null("Fills")
	if holder == null:
		holder = Node3D.new()
		holder.name = "Fills"
		root.add_child(holder)
		holder.owner = root
		_say("Fills: created")

	# Placed in the two places the reference is darkest: the recess off to the
	# right, and the water side of the outcrop.
	var spec := [
		{"name": "FILL_Recess",      "pos": Vector3(9.0, 2.0, -4.0),  "range": 16.0},
		{"name": "FILL_PoolBack",    "pos": Vector3(3.0, 2.5, -8.0),  "range": 18.0},
		{"name": "FILL_OutcropBack", "pos": Vector3(-4.0, 3.0, 3.0),  "range": 12.0},
	]

	for s in spec:
		var l := holder.get_node_or_null(String(s["name"])) as OmniLight3D
		if l == null:
			l = OmniLight3D.new()
			l.name = String(s["name"])
			holder.add_child(l)
			l.owner = root
		_set_world(l, Transform3D(Basis(), s["pos"]))
		l.light_color = Color(0.60, 0.78, 0.86)   # cool
		l.light_energy = 0.3
		l.light_volumetric_fog_energy = 1.0
		l.light_specular = 0.0
		l.shadow_enabled = false
		l.omni_range = float(s["range"])
		l.omni_attenuation = 1.6
		l.light_bake_mode = Light3D.BAKE_STATIC
	_say("Fills: 3 omni at energy 0.3, cool, shadows off, bake STATIC")


# -----------------------------------------------------------------------------
# GI
# -----------------------------------------------------------------------------

func _apply_lightmap(root: Node) -> void:
	var lm := root.get_node_or_null("LightmapGI") as LightmapGI
	if lm == null:
		lm = LightmapGI.new()
		lm.name = "LightmapGI"
		root.add_child(lm)
		lm.owner = root
		_say("LightmapGI: created")
	lm.quality = LightmapGI.BAKE_QUALITY_MEDIUM
	lm.bounces = 3
	lm.bounce_indirect_energy = 1.0
	lm.use_denoiser = true
	lm.directional = true
	lm.generate_probes_subdiv = LightmapGI.GENERATE_PROBES_SUBDIV_8
	lm.environment_mode = LightmapGI.ENVIRONMENT_MODE_CUSTOM_COLOR
	lm.environment_custom_color = Color(0.03, 0.045, 0.055)
	lm.environment_custom_energy = 1.0
	_say("LightmapGI: medium, 3 bounces, probes subdiv 8, dark custom env. NOT BAKED YET.")


# -----------------------------------------------------------------------------
# hero check camera
# -----------------------------------------------------------------------------

func _apply_hero_cam(root: Node, markers: Dictionary) -> void:
	var cam := root.get_node_or_null("HeroCam") as Camera3D
	if cam == null:
		cam = Camera3D.new()
		cam.name = "HeroCam"
		root.add_child(cam)
		cam.owner = root
		_say("HeroCam: created")

	var pos := _marker_pos(markers, "MARK_HeroView", FALLBACK_HERO_POS)
	var dir := _marker_dir(markers, "MARK_HeroView", FALLBACK_HERO_DIR)
	_set_world(cam, Transform3D(_basis_facing(dir), pos))
	cam.fov = 75.0
	cam.near = 0.05
	cam.far = 400.0
	cam.current = false
	cam.keep_aspect = Camera3D.KEEP_HEIGHT

	var sp := "res://scenes/debug/hero_cam.gd"
	if ResourceLoader.exists(sp):
		cam.set_script(ResourceLoader.load(sp))
		cam.set("player_cam_path", NodePath("../Player/Player/Head/Camera3D"))
		_say("HeroCam: pos %v, fov 75, pitch %.1f deg, press H in game to toggle"
			% [pos, rad_to_deg(asin(clampf(dir.y, -1.0, 1.0)))])
	else:
		_say("HeroCam: pos %v -- hero_cam.gd MISSING, no toggle" % pos)


# -----------------------------------------------------------------------------
# misc
# -----------------------------------------------------------------------------

func _quiet_route_audit(root: Node) -> void:
	var ra := root.get_node_or_null("RouteAudit")
	if ra != null and ra.get("run_on_start") == true:
		ra.set("run_on_start", false)
		_say("RouteAudit: run_on_start -> false (it hijacks the player during lighting work)")


# -----------------------------------------------------------------------------
# water placeholder
# -----------------------------------------------------------------------------

func _apply_water_placeholder(root: Node) -> void:
	# The dark water material is applied by a @tool script on the Water node,
	# NOT written into this scene. See scenes/water/water_placeholder.gd for why:
	# overriding a property on a node inside the instanced glb makes pack()
	# serialise the whole mesh inline (105 KB of vertex arrays) and forks the
	# water away from cave_env.glb.
	var w := root.get_node_or_null("Water")
	if w == null:
		_say("water: no Water node, placeholder skipped")
		return
	# Once G3 has run, Water is an instance of Water.tscn carrying the real
	# shader. Re-running G2 must not overwrite that with the placeholder.
	if w.scene_file_path != "":
		_say("water: Water is an instance of %s, leaving it alone" % w.scene_file_path)
		return
	var sp := "res://scenes/water/water_placeholder.gd"
	if not ResourceLoader.exists(sp):
		_say("!! water: %s missing, pool will render as default WHITE and poison the bake" % sp)
		push_error("G2: %s missing" % sp)
		return
	w.set_script(ResourceLoader.load(sp))
	_say("water: Water node scripted with water_placeholder.gd (dark, rough 0.55)")


func _find_desc(n: Node, nm: String) -> Node:
	if String(n.name) == nm:
		return n
	for c in n.get_children():
		var r := _find_desc(c, nm)
		if r != null:
			return r
	return null
