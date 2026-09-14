extends SceneTree
##
## G5 — builds the dust-mote and drip emitters and wires the foliage script,
## the motes and the drips into main.tscn.
##
##   Godot --headless --path <project> --script res://scenes/debug/g5_env.gd
##
## Writes scenes/_main_g5_candidate.tscn; the caller verifies and promotes.
##
## The moss and leaf MATERIALS are not built here -- scenes/env/foliage.gd
## applies those at runtime, because they land on meshes inside the instanced
## cave_env.glb where pack() will not keep an override (HANDOFF_GODOT.md §4).
##

const CANDIDATE := "res://scenes/_main_g5_candidate.tscn"
const MAIN := "res://scenes/main.tscn"
const MOTES_SCENE := "res://scenes/fx/Motes.tscn"
const DRIP_SCENE := "res://scenes/fx/Drip.tscn"
const FOLIAGE_GD := "res://scenes/env/foliage.gd"
const DRIPS_GD := "res://scenes/fx/drips.gd"
const MOTE_TEX := "res://assets/textures/T_Mote.png"

# MARK_Skylight, measured: origin and the direction light travels.
const SUN_POS := Vector3(-2.53, 30.3688, -7.68)
const SUN_DIR := Vector3(0.4198, -0.8896, 0.1799)

var _msgs: Array = []


func _initialize() -> void:
	_build_motes()
	_build_drip()

	var packed: PackedScene = ResourceLoader.load(MAIN, "PackedScene", ResourceLoader.CACHE_MODE_IGNORE)
	if packed == null:
		push_error("G5: could not load %s" % MAIN)
		quit(2); return
	var root := packed.instantiate(PackedScene.GEN_EDIT_STATE_MAIN)
	if root == null or root.name != "Main":
		push_error("G5: root is not Main")
		quit(3); return

	_wire(root)

	var ps := PackedScene.new()
	var perr := ps.pack(root)
	if perr != OK:
		push_error("G5: pack failed %d" % perr)
		quit(4); return
	var serr := ResourceSaver.save(ps, CANDIDATE)
	_say("pack OK -> %s %s" % [CANDIDATE, "OK" if serr == OK else "ERR %d" % serr])
	if serr == OK:
		_verify(CANDIDATE, ["Foliage", "foliage.gd", "Motes", "Drips", "drips.gd",
							"cave_env.glb", "Player.tscn", "Water.tscn"])

	print("=== G5 env ===")
	for m in _msgs:
		print("  " + str(m))
	quit(0 if serr == OK else 5)


func _say(s: String) -> void:
	_msgs.append(s)


## Orthonormal basis whose -Z points along `dir`, as in g2_lighting.gd.
func _basis_facing(dir: Vector3) -> Basis:
	var z := (-dir).normalized()
	var up := Vector3.UP
	if absf(z.dot(up)) > 0.999:
		up = Vector3.FORWARD
	var x := up.cross(z).normalized()
	var y := z.cross(x).normalized()
	return Basis(x, y, z)


# -----------------------------------------------------------------------------
# Motes.tscn
# -----------------------------------------------------------------------------

func _build_motes() -> void:
	# The emitter box is ROTATED onto the light direction rather than being an
	# axis-aligned block over the chamber. An axis-aligned box big enough to
	# contain the shaft also contains most of the room, and additive motes are
	# visible wherever they are -- they are not actually gated by the fog, the
	# brief's reasoning notwithstanding. Confining them to a 6 x 6 x 34 m column
	# along the ray is what makes them read as "dust in the beam".
	var to_y := 2.0
	var t := (SUN_POS.y - to_y) / SUN_DIR.y * -1.0        # distance along the ray
	var far := SUN_POS + SUN_DIR * t
	var mid := (SUN_POS + far) * 0.5

	var p := GPUParticles3D.new()
	p.name = "Motes"
	p.transform = Transform3D(_basis_facing(SUN_DIR), mid)
	p.amount = 300
	p.lifetime = 16.0
	p.one_shot = false
	p.explosiveness = 0.0
	p.randomness = 1.0
	# Without preprocess the beam is empty for the first 16 seconds and then
	# fills -- which is exactly the window a screenshot lands in.
	p.preprocess = 16.0
	p.fixed_fps = 20            # dust does not need 60 Hz simulation
	p.draw_order = GPUParticles3D.DRAW_ORDER_VIEW_DEPTH
	p.visibility_aabb = AABB(Vector3(-12, -12, -24), Vector3(24, 24, 48))

	var pm := ParticleProcessMaterial.new()
	pm.emission_shape = ParticleProcessMaterial.EMISSION_SHAPE_BOX
	pm.emission_box_extents = Vector3(3.0, 3.0, 17.0)     # half-extents, local
	pm.direction = Vector3(0, 1, 0)
	pm.spread = 180.0
	pm.initial_velocity_min = 0.02
	pm.initial_velocity_max = 0.10
	pm.gravity = Vector3(0, -0.035, 0)                    # barely sinking
	pm.scale_min = 0.5
	pm.scale_max = 1.6
	pm.color = Color(1.0, 0.97, 0.90, 1.0)

	var qm := QuadMesh.new()
	qm.size = Vector2(0.035, 0.035)
	var mat := StandardMaterial3D.new()
	mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	mat.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	mat.blend_mode = BaseMaterial3D.BLEND_MODE_ADD
	mat.billboard_mode = BaseMaterial3D.BILLBOARD_ENABLED
	mat.billboard_keep_scale = true
	mat.vertex_color_use_as_albedo = true
	mat.albedo_color = Color(1.0, 0.97, 0.90, 0.5)
	var tex: Texture2D = ResourceLoader.load(MOTE_TEX)
	if tex != null:
		mat.albedo_texture = tex
	else:
		_say("!! %s missing, motes will be hard squares" % MOTE_TEX)
	mat.disable_receive_shadows = true
	qm.material = mat
	p.draw_pass_1 = qm

	p.process_material = pm
	_save_scene(p, MOTES_SCENE, "Motes")
	_verify(MOTES_SCENE, ["GPUParticles3D", "ParticleProcessMaterial", "QuadMesh"])
	_say("motes: 300 in a 6x6x34 m column along the ray, centred %v" % mid)


# -----------------------------------------------------------------------------
# Drip.tscn
# -----------------------------------------------------------------------------

func _build_drip() -> void:
	var p := GPUParticles3D.new()
	p.name = "Drip"
	p.amount = 5
	p.lifetime = 1.8
	p.one_shot = false
	p.explosiveness = 0.0
	p.randomness = 0.9
	p.preprocess = 1.0
	# Stretches each quad along its velocity, which is what turns a dot into a
	# falling streak without needing an animated sprite.
	p.transform_align = GPUParticles3D.TRANSFORM_ALIGN_Y_TO_VELOCITY
	p.visibility_aabb = AABB(Vector3(-1, -14, -1), Vector3(2, 16, 2))

	var pm := ParticleProcessMaterial.new()
	pm.emission_shape = ParticleProcessMaterial.EMISSION_SHAPE_POINT
	pm.direction = Vector3(0, -1, 0)
	pm.spread = 3.0
	pm.initial_velocity_min = 0.4
	pm.initial_velocity_max = 0.9
	pm.gravity = Vector3(0, -9.8, 0)
	pm.scale_min = 0.7
	pm.scale_max = 1.3
	pm.color = Color(0.78, 0.90, 0.92, 1.0)

	var qm := QuadMesh.new()
	qm.size = Vector2(0.012, 0.16)
	var mat := StandardMaterial3D.new()
	mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	mat.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	mat.blend_mode = BaseMaterial3D.BLEND_MODE_ADD
	mat.vertex_color_use_as_albedo = true
	mat.albedo_color = Color(0.78, 0.90, 0.92, 0.75)
	mat.disable_receive_shadows = true
	qm.material = mat
	p.draw_pass_1 = qm
	p.process_material = pm

	_save_scene(p, DRIP_SCENE, "Drip")
	_verify(DRIP_SCENE, ["GPUParticles3D", "ParticleProcessMaterial"])


# -----------------------------------------------------------------------------
# main.tscn
# -----------------------------------------------------------------------------

func _wire(root: Node) -> void:
	# --- Foliage
	var f := root.get_node_or_null("Foliage")
	if f == null:
		f = Node3D.new()
		f.name = "Foliage"
		root.add_child(f)
		f.owner = root
		_say("Foliage: node created")
	var fs: Script = ResourceLoader.load(FOLIAGE_GD)
	if fs == null:
		push_error("G5: %s missing" % FOLIAGE_GD)
	else:
		f.set_script(fs)
		_say("Foliage: scripted with foliage.gd")

	# --- FX/Motes
	var fx := root.get_node_or_null("FX")
	if fx == null:
		fx = Node3D.new()
		fx.name = "FX"
		root.add_child(fx)
		fx.owner = root
	var old := fx.get_node_or_null("Motes")
	if old != null:
		fx.remove_child(old)
		old.free()
	var mps: PackedScene = ResourceLoader.load(MOTES_SCENE, "PackedScene", ResourceLoader.CACHE_MODE_IGNORE)
	if mps != null:
		var mn := mps.instantiate()
		mn.name = "Motes"
		fx.add_child(mn)
		mn.owner = root
		_say("FX/Motes: instanced")
	else:
		_say("!! %s did not save" % MOTES_SCENE)

	# --- FX/Drips
	var d := fx.get_node_or_null("Drips")
	if d == null:
		d = Node3D.new()
		d.name = "Drips"
		fx.add_child(d)
		d.owner = root
	var ds: Script = ResourceLoader.load(DRIPS_GD)
	if ds == null:
		push_error("G5: %s missing" % DRIPS_GD)
	else:
		d.set_script(ds)
		_say("FX/Drips: scripted with drips.gd")


# -----------------------------------------------------------------------------
# helpers
# -----------------------------------------------------------------------------

func _save_scene(root: Node, path: String, label: String) -> void:
	var ps := PackedScene.new()
	var e := ps.pack(root)
	if e != OK:
		push_error("G5: pack %s failed %d" % [label, e])
		return
	var dir := path.get_base_dir()
	if not DirAccess.dir_exists_absolute(dir):
		DirAccess.make_dir_recursive_absolute(dir)
	var s := ResourceSaver.save(ps, path)
	_say("%s -> %s %s" % [label, path, "OK" if s == OK else "ERR %d" % s])


func _verify(path: String, tokens: Array) -> void:
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
		push_error("G5: %s missing %s" % [path, str(missing)])
		_say("!! %s missing %s" % [path, str(missing)])
