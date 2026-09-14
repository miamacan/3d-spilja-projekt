extends SceneTree
##
## G3 — builds Splash.tscn, Rock.tscn and Water.tscn, and wires them into
## main.tscn.
##
## Runs HEADLESS, no editor:
##   Godot --headless --path <project> --script res://scenes/debug/g3_water.gd
##
## Writes scenes/_main_g3_candidate.tscn; the caller verifies it and moves it
## over scenes/main.tscn. Same discipline as g2_lighting.gd and for the same
## reason -- see HANDOFF_GODOT.md §5.
##
## Idempotent: every scene is rebuilt from scratch, and the main.tscn wiring is
## looked up by name and replaced.
##

const MAIN := "res://scenes/main.tscn"
const CANDIDATE := "res://scenes/_main_g3_candidate.tscn"
const WATER_SCENE := "res://scenes/water/Water.tscn"
const SPLASH_SCENE := "res://scenes/fx/Splash.tscn"
const ROCK_SCENE := "res://scenes/rock/Rock.tscn"

const WATER_GD := "res://scenes/water/water.gd"
const SPLASH_GD := "res://scenes/fx/splash.gd"
const THROWER_GD := "res://scenes/rock/rock_thrower.gd"
const RING_SHADER := "res://shaders/splash_ring.gdshader"
const PLOP := "res://audio/plop.wav"

# Fallbacks, measured in cave.blend, Blender (x,y,z) -> Godot (x,z,-y).
const FB_POOL_POS := Vector3(2.5, -2.2818, -1.25)
const FB_POOL_HALF := Vector3(15.5, 2.4818, 13.25)
# Shell bbox in Godot space, for the reflection probe.
const SHELL_MIN := Vector3(-12.838, -4.79, -15.617)
const SHELL_MAX := Vector3(17.827, 30.625, 21.0)

var _msgs: Array = []


func _initialize() -> void:
	_say("--- building sub-scenes")
	_build_splash()
	# Rock.tscn is built by G4 (scenes/debug/g4_rocks.gd) and NOT here any more.
	# G3 shipped a provisional sphere; re-running this after G4 would silently
	# revert the real rock. Only check it exists.
	if ResourceLoader.exists(ROCK_SCENE):
		_say("Rock: %s exists, owned by G4, left alone" % ROCK_SCENE)
	else:
		_say("!! %s missing -- run g4_rocks.gd" % ROCK_SCENE)

	var packed: PackedScene = ResourceLoader.load(MAIN, "PackedScene", ResourceLoader.CACHE_MODE_IGNORE)
	if packed == null:
		push_error("G3: could not load %s" % MAIN)
		quit(2); return
	var root := packed.instantiate(PackedScene.GEN_EDIT_STATE_MAIN)
	if root == null or root.name != "Main":
		push_error("G3: root is not Main")
		quit(3); return

	var pool := _pool_box(root)
	_build_water(pool["pos"], pool["half"])

	_say("--- wiring main.tscn")
	_wire_water(root)
	_wire_thrower(root)

	var ps := PackedScene.new()
	var perr := ps.pack(root)
	if perr != OK:
		push_error("G3: pack failed %d" % perr)
		quit(4); return
	var serr := ResourceSaver.save(ps, CANDIDATE)
	_say("pack OK, saved %s -> %s" % [CANDIDATE, "OK" if serr == OK else "ERR %d" % serr])

	if serr == OK:
		var f := FileAccess.open(CANDIDATE, FileAccess.READ)
		if f:
			var body := f.get_as_text()
			f.close()
			for tok in ["Water.tscn", "RockThrower", "cave_env.glb", "Player.tscn",
						"HeroCam", "LightmapGI"]:
				if not (tok in body):
					push_error("G3: '%s' missing from the packed scene" % tok)
					_say("!! packed scene is missing '%s'" % tok)

	print("=== G3 water ===")
	for m in _msgs:
		print("  " + str(m))
	quit(0 if serr == OK else 5)


func _say(s: String) -> void:
	_msgs.append(s)


func _gxform(n: Node3D) -> Transform3D:
	var t := Transform3D()
	var cur: Node = n
	while cur != null and cur is Node3D:
		t = (cur as Node3D).transform * t
		cur = cur.get_parent()
	return t


func _find(n: Node, nm: String) -> Node:
	if String(n.name) == nm:
		return n
	for c in n.get_children():
		var r := _find(c, nm)
		if r != null:
			return r
	return null


## The Area3D box, from MARK_Pool_Volume, with its TOP moved to Y = 0 per the
## brief. The marker itself spans y -4.76..+0.20 in Godot space, i.e. it is the
## water body and its top pokes 0.2 m above the surface -- left as-is the area
## would trigger before the rock touched the water.
func _pool_box(root: Node) -> Dictionary:
	var pos := FB_POOL_POS
	var half := FB_POOL_HALF
	var envnode := root.get_node_or_null("Env")
	if envnode != null:
		var m := _find(envnode, "MARK_Pool_Volume") as Node3D
		if m != null:
			var t := _gxform(m)
			pos = t.origin
			var s := t.basis.get_scale()
			half = Vector3(absf(s.x), absf(s.y), absf(s.z))
			_say("pool: MARK_Pool_Volume at %v half %v" % [pos, half])
		else:
			_say("pool: marker not found, using fallback")
	var size := half * 2.0
	# top at y = 0
	var centre := Vector3(pos.x, -half.y, pos.z)
	return {"pos": centre, "half": half, "size": size}


# -----------------------------------------------------------------------------
# Splash.tscn
# -----------------------------------------------------------------------------

func _build_splash() -> void:
	var root := Node3D.new()
	root.name = "Splash"
	var sc: Script = ResourceLoader.load(SPLASH_GD)
	if sc == null:
		push_error("G3: %s missing" % SPLASH_GD)
		return
	root.set_script(sc)

	# --- droplets
	var pm := ParticleProcessMaterial.new()
	pm.emission_shape = ParticleProcessMaterial.EMISSION_SHAPE_SPHERE
	pm.emission_sphere_radius = 0.09
	pm.direction = Vector3(0, 1, 0)
	pm.spread = 38.0
	pm.initial_velocity_min = 1.8
	pm.initial_velocity_max = 3.6
	pm.gravity = Vector3(0, -9.8, 0)
	pm.scale_min = 0.6
	pm.scale_max = 1.4
	pm.damping_min = 0.2
	pm.damping_max = 0.8
	pm.color = Color(0.72, 0.88, 0.85, 1.0)

	var dm := SphereMesh.new()
	dm.radius = 0.022
	dm.height = 0.044
	dm.radial_segments = 6
	dm.rings = 3
	var dmat := StandardMaterial3D.new()
	# Unshaded: the pool sits in the darkest part of the chamber, and lit
	# droplets that small are simply invisible there.
	dmat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	dmat.albedo_color = Color(0.72, 0.88, 0.85)
	dmat.vertex_color_use_as_albedo = true
	dm.material = dmat

	var drops := GPUParticles3D.new()
	drops.name = "Droplets"
	drops.amount = 24
	drops.lifetime = 0.8
	drops.one_shot = true
	drops.explosiveness = 1.0
	drops.randomness = 0.35
	drops.process_material = pm
	drops.draw_pass_1 = dm
	drops.emitting = false          # splash.gd fires it
	root.add_child(drops)
	drops.owner = root

	# --- ring
	var qm := QuadMesh.new()
	qm.size = Vector2(3.0, 3.0)     # splash.gd resizes to the real diameter
	var ring := MeshInstance3D.new()
	ring.name = "Ring"
	ring.mesh = qm
	# QuadMesh lies in XY facing +Z; -90 deg about X turns its normal to +Y so
	# it lies flat on the water. Lifted 3 cm: the water plane writes depth, and
	# a coplanar quad z-fights with it.
	ring.transform = Transform3D(Basis(Vector3(1, 0, 0), -PI * 0.5), Vector3(0, 0.03, 0))
	var rsh: Shader = ResourceLoader.load(RING_SHADER)
	if rsh != null:
		var rmat := ShaderMaterial.new()
		rmat.shader = rsh
		ring.material_override = rmat
	else:
		push_error("G3: %s missing" % RING_SHADER)
	ring.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	root.add_child(ring)
	ring.owner = root

	# --- audio
	var au := AudioStreamPlayer3D.new()
	au.name = "Audio"
	var st: AudioStream = ResourceLoader.load(PLOP)
	if st != null:
		au.stream = st
	else:
		_say("!! %s missing, splash will be silent" % PLOP)
	au.unit_size = 6.0
	au.max_distance = 45.0
	au.autoplay = false
	root.add_child(au)
	au.owner = root

	_save_scene(root, SPLASH_SCENE, "Splash")
	_verify_scene(SPLASH_SCENE, ["Droplets", "Ring", "Audio", "splash.gd"])


# -----------------------------------------------------------------------------
# Rock.tscn
# -----------------------------------------------------------------------------

# -----------------------------------------------------------------------------
# Water.tscn
# -----------------------------------------------------------------------------

func _build_water(centre: Vector3, half: Vector3) -> void:
	var root := Node3D.new()
	root.name = "Water"
	var sc: Script = ResourceLoader.load(WATER_GD)
	if sc == null:
		push_error("G3: %s missing" % WATER_GD)
		return
	root.set_script(sc)

	# --- trigger volume
	var area := Area3D.new()
	area.name = "Volume"
	area.collision_layer = 0        # nothing needs to detect the water itself
	area.collision_mask = 4         # rocks
	area.monitoring = true
	area.monitorable = false
	area.transform = Transform3D(Basis(), centre)
	root.add_child(area)
	area.owner = root
	var box := BoxShape3D.new()
	box.size = half * 2.0
	var cs := CollisionShape3D.new()
	cs.name = "Shape"
	cs.shape = box
	# Order matters: the parent must already be in root's tree before `owner`
	# can be set to root, or Godot rejects it with "Owner must be an ancestor in
	# the tree" -- and the node is then simply not saved, leaving an Area3D with
	# no shape that silently detects nothing.
	area.add_child(cs)
	cs.owner = root

	# --- reflection probe
	var probe := ReflectionProbe.new()
	probe.name = "Probe"
	var pmin := SHELL_MIN
	var pmax := SHELL_MAX
	var pcentre := (pmin + pmax) * 0.5
	probe.transform = Transform3D(Basis(), pcentre)
	probe.size = (pmax - pmin) * 1.02
	probe.update_mode = ReflectionProbe.UPDATE_ONCE
	# Capture from just above the water rather than from the middle of a 35 m
	# box, so what the pool reflects is the chamber as seen from the surface.
	probe.origin_offset = Vector3(0.0, 1.5 - pcentre.y, 0.0)
	# interior = true keeps the bright PhysicalSky OUT of the reflection. This
	# is the G2 lesson repeated: the placeholder pool went pale because a smooth
	# surface at a grazing angle mirrors the sky. The pool must reflect the cave.
	probe.interior = true
	probe.intensity = 1.0
	probe.max_distance = 0.0
	# A probe's box is its AREA OF EFFECT, not its capture extent -- it always
	# captures the whole surroundings. Left unmasked, a box "covering the
	# chamber" therefore re-lights every rock face in the cave with the captured
	# cubemap, which turned the entire chamber bright and green (the cubemap
	# contains the green-blue FOG_PoolMurk and the vegetation).
	# reflection_mask restricts it to visual layer 2, which water.gd puts the
	# pool surface on and nothing else uses. cull_mask stays wide so the capture
	# still sees the whole chamber, which is the point.
	probe.reflection_mask = 2
	# and no ambient contribution at all; the lightmap owns that
	probe.ambient_mode = ReflectionProbe.AMBIENT_DISABLED
	root.add_child(probe)
	probe.owner = root

	var holder := Node3D.new()
	holder.name = "Splashes"
	root.add_child(holder)
	holder.owner = root

	_save_scene(root, WATER_SCENE, "Water")
	_say("water: volume %v at %v, probe %v" % [half * 2.0, centre, probe.size])
	_verify_scene(WATER_SCENE, ["Volume", "Shape", "Probe", "Splashes", "water.gd"])


# -----------------------------------------------------------------------------
# main.tscn wiring
# -----------------------------------------------------------------------------

func _wire_water(root: Node) -> void:
	var old := root.get_node_or_null("Water")
	if old != null:
		root.remove_child(old)
		old.free()
		_say("Water: old placeholder node removed")
	var ps: PackedScene = ResourceLoader.load(WATER_SCENE, "PackedScene", ResourceLoader.CACHE_MODE_IGNORE)
	if ps == null:
		push_error("G3: %s did not save" % WATER_SCENE)
		return
	var w := ps.instantiate()
	w.name = "Water"
	root.add_child(w)
	w.owner = root
	# Keep it in the same place in the child order it had before, for no reason
	# other than that main.tscn stays readable.
	root.move_child(w, mini(4, root.get_child_count() - 1))
	_say("Water: Water.tscn instanced")


func _wire_thrower(root: Node) -> void:
	var t := root.get_node_or_null("RockThrower")
	if t == null:
		t = Node3D.new()
		t.name = "RockThrower"
		root.add_child(t)
		t.owner = root
	var sc: Script = ResourceLoader.load(THROWER_GD)
	if sc == null:
		push_error("G3: %s missing" % THROWER_GD)
		return
	t.set_script(sc)
	_say("RockThrower: added (PROVISIONAL -- see rock_thrower.gd header)")


func _save_scene(root: Node, path: String, label: String) -> void:
	var ps := PackedScene.new()
	var e := ps.pack(root)
	if e != OK:
		push_error("G3: pack %s failed %d" % [label, e])
		return
	var d := path.get_base_dir()
	if not DirAccess.dir_exists_absolute(d):
		DirAccess.make_dir_recursive_absolute(d)
	var s := ResourceSaver.save(ps, path)
	_say("%s -> %s %s" % [label, path, "OK" if s == OK else "ERR %d" % s])


## Read a just-written scene back off disk and check the names that must be in
## it are there. An unowned child is dropped by pack() WITHOUT an error at save
## time -- the Area3D lost its CollisionShape3D exactly this way and would have
## shipped detecting nothing.
func _verify_scene(path: String, tokens: Array) -> void:
	var f := FileAccess.open(path, FileAccess.READ)
	if f == null:
		_say("!! could not read back %s" % path)
		return
	var body := f.get_as_text()
	f.close()
	var missing: Array = []
	for t in tokens:
		if not (String(t) in body):
			missing.append(t)
	if missing.is_empty():
		_say("   verified %s (%d bytes)" % [path, body.length()])
	else:
		push_error("G3: %s is missing %s" % [path, str(missing)])
		_say("!! %s is missing %s" % [path, str(missing)])
