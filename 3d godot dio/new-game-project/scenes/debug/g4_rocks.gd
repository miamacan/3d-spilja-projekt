extends SceneTree
# G4 faza: gradi kamen za bacanje i njegovu prašinu, i briše privremeni
# sustav bacanja iz G3 faze.

const CANDIDATE := "res://scenes/_main_g4_candidate.tscn"
const MAIN := "res://scenes/main.tscn"
const ROCK_SCENE := "res://scenes/rock/Rock.tscn"
const DUST_SCENE := "res://scenes/fx/Dust.tscn"
const ROCK_GD := "res://scenes/rock/rock.gd"
const DUST_GD := "res://scenes/fx/dust.gd"
const MAT_PEBBLE := "res://scenes/rock/M_RockPebble.tres"
const MAT_VIEWMODEL := "res://scenes/rock/M_RockViewmodel.tres"

const TEX_BC := "res://assets/env/cave_env_T_Limestone_BC.png"
const TEX_ORM := "res://assets/env/cave_env_T_Limestone_ORM.png"

const ROCK_RADIUS := 0.058

var _msgs: Array = []


func _initialize() -> void:
	_build_materials()
	_build_meshes()
	_build_dust()
	_build_rock()

	var packed: PackedScene = ResourceLoader.load(MAIN, "PackedScene", ResourceLoader.CACHE_MODE_IGNORE)
	if packed == null:
		push_error("G4: could not load %s" % MAIN)
		quit(2); return
	var root := packed.instantiate(PackedScene.GEN_EDIT_STATE_MAIN)
	if root == null or root.name != "Main":
		push_error("G4: root is not Main")
		quit(3); return

	var old := root.get_node_or_null("RockThrower")
	if old != null:
		root.remove_child(old)
		old.free()
		_say("RockThrower: provisional G3 node removed")
	else:
		_say("RockThrower: not present, nothing to remove")

	var ps := PackedScene.new()
	var perr := ps.pack(root)
	if perr != OK:
		push_error("G4: pack failed %d" % perr)
		quit(4); return
	var serr := ResourceSaver.save(ps, CANDIDATE)
	_say("pack OK -> %s %s" % [CANDIDATE, "OK" if serr == OK else "ERR %d" % serr])

	print("=== G4 rocks ===")
	for m in _msgs:
		print("  " + str(m))
	quit(0 if serr == OK else 5)


func _say(s: String) -> void:
	_msgs.append(s)


func _build_materials() -> void:
	var bc: Texture2D = ResourceLoader.load(TEX_BC)
	var orm: Texture2D = ResourceLoader.load(TEX_ORM)
	if bc == null or orm == null:
		_say("!! limestone textures missing (%s / %s)" % [TEX_BC, TEX_ORM])

	var m := StandardMaterial3D.new()
	m.albedo_texture = bc
	m.albedo_color = Color(1, 1, 1)
	m.roughness = 1.0
	m.roughness_texture = orm
	m.roughness_texture_channel = BaseMaterial3D.TEXTURE_CHANNEL_GREEN
	m.ao_enabled = true
	m.ao_texture = orm
	m.ao_texture_channel = BaseMaterial3D.TEXTURE_CHANNEL_RED
	m.metallic = 0.0
	m.uv1_triplanar = true
	m.uv1_scale = Vector3(3.0, 3.0, 3.0)
	_save(m, MAT_PEBBLE, "M_RockPebble")

	var v := m.duplicate() as StandardMaterial3D
	v.emission_enabled = true
	v.emission = Color(0.62, 0.60, 0.55)
	v.emission_energy_multiplier = 0.05
	v.emission_texture = bc
	_save(v, MAT_VIEWMODEL, "M_RockViewmodel")


func _build_meshes() -> void:
	var t := (1.0 + sqrt(5.0)) / 2.0
	var v: Array[Vector3] = [
		Vector3(-1, t, 0), Vector3(1, t, 0), Vector3(-1, -t, 0), Vector3(1, -t, 0),
		Vector3(0, -1, t), Vector3(0, 1, t), Vector3(0, -1, -t), Vector3(0, 1, -t),
		Vector3(t, 0, -1), Vector3(t, 0, 1), Vector3(-t, 0, -1), Vector3(-t, 0, 1),
	]
	for i in v.size():
		v[i] = v[i].normalized()
	var faces := [
		[0, 11, 5], [0, 5, 1], [0, 1, 7], [0, 7, 10], [0, 10, 11],
		[1, 5, 9], [5, 11, 4], [11, 10, 2], [10, 7, 6], [7, 1, 8],
		[3, 9, 4], [3, 4, 2], [3, 2, 6], [3, 6, 8], [3, 8, 9],
		[4, 9, 5], [2, 4, 11], [6, 2, 10], [8, 6, 7], [9, 8, 1],
	]

	var variants := [
		{"seed": 1.7, "amp": 0.20, "squash": Vector3(1.00, 0.80, 0.92)},
		{"seed": 4.3, "amp": 0.26, "squash": Vector3(0.92, 0.88, 1.00)},
		{"seed": 8.9, "amp": 0.16, "squash": Vector3(1.00, 0.72, 0.86)},
	]

	for n in range(variants.size()):
		var cfg = variants[n]
		var st := SurfaceTool.new()
		st.begin(Mesh.PRIMITIVE_TRIANGLES)
		var tris := 0
		for f in faces:
			var a: Vector3 = v[f[0]]
			var b: Vector3 = v[f[1]]
			var c: Vector3 = v[f[2]]
			var ab := ((a + b) * 0.5).normalized()
			var bc := ((b + c) * 0.5).normalized()
			var ca := ((c + a) * 0.5).normalized()
			for tri in [[a, ab, ca], [ab, b, bc], [ca, bc, c], [ab, bc, ca]]:
				for d in tri:
					st.add_vertex(_shape(d, cfg["seed"], cfg["amp"], cfg["squash"]))
				tris += 1
		st.generate_normals()
		var mesh := st.commit()
		var path := "res://scenes/rock/rock_mesh_%d.res" % (n + 1)
		_save(mesh, path, "rock_mesh_%d (%d tris)" % [n + 1, tris])


func _shape(d: Vector3, seed: float, amp: float, squash: Vector3) -> Vector3:
	var s := seed
	var n := 0.0
	n += sin(d.x * 3.1 + s) * cos(d.y * 2.7 - s) * 0.5
	n += sin(d.y * 5.3 - s * 1.3) * cos(d.z * 4.1 + s) * 0.3
	n += sin(d.z * 8.7 + s * 0.7) * cos(d.x * 7.3 - s) * 0.2
	return d * (ROCK_RADIUS * (1.0 + n * amp)) * squash


func _build_dust() -> void:
	var root := Node3D.new()
	root.name = "Dust"
	var sc: Script = ResourceLoader.load(DUST_GD)
	if sc == null:
		push_error("G4: %s missing" % DUST_GD)
		return
	root.set_script(sc)

	var pm := ParticleProcessMaterial.new()
	pm.emission_shape = ParticleProcessMaterial.EMISSION_SHAPE_SPHERE
	pm.emission_sphere_radius = 0.04
	pm.direction = Vector3(0, 1, 0)
	pm.spread = 62.0
	pm.initial_velocity_min = 0.35
	pm.initial_velocity_max = 1.15
	pm.gravity = Vector3(0, -1.6, 0)
	pm.damping_min = 0.8
	pm.damping_max = 1.8
	pm.scale_min = 0.5
	pm.scale_max = 1.3
	var grad := Gradient.new()
	grad.set_color(0, Color(0.58, 0.55, 0.49, 0.55))
	grad.set_color(1, Color(0.58, 0.55, 0.49, 0.0))
	var gt := GradientTexture1D.new()
	gt.gradient = grad
	pm.color_ramp = gt

	var dm := SphereMesh.new()
	dm.radius = 0.018
	dm.height = 0.036
	dm.radial_segments = 5
	dm.rings = 3
	var dmat := StandardMaterial3D.new()
	dmat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	dmat.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	dmat.vertex_color_use_as_albedo = true
	dmat.albedo_color = Color(0.58, 0.55, 0.49, 1.0)
	dm.material = dmat

	var p := GPUParticles3D.new()
	p.name = "Particles"
	p.amount = 10
	p.lifetime = 0.7
	p.one_shot = true
	p.explosiveness = 0.9
	p.randomness = 0.4
	p.process_material = pm
	p.draw_pass_1 = dm
	p.emitting = false
	root.add_child(p)
	p.owner = root

	_save_scene(root, DUST_SCENE, "Dust")
	_verify(DUST_SCENE, ["Particles", "dust.gd"])


func _build_rock() -> void:
	var rb := RigidBody3D.new()
	rb.name = "Rock"
	rb.mass = 0.3
	rb.contact_monitor = true
	rb.max_contacts_reported = 4
	rb.collision_layer = 4
	rb.collision_mask = 1 | 4
	rb.continuous_cd = true
	rb.add_to_group("rock", true)

	var phys := PhysicsMaterial.new()
	phys.bounce = 0.32
	phys.friction = 0.7
	rb.physics_material_override = phys

	var sc: Script = ResourceLoader.load(ROCK_GD)
	if sc == null:
		push_error("G4: %s missing" % ROCK_GD)
		return
	rb.set_script(sc)

	var shape := SphereShape3D.new()
	shape.radius = 0.06
	var col := CollisionShape3D.new()
	col.name = "Col"
	col.shape = shape
	rb.add_child(col)
	col.owner = rb

	var mi := MeshInstance3D.new()
	mi.name = "Mesh"
	mi.mesh = ResourceLoader.load("res://scenes/rock/rock_mesh_1.res")
	mi.material_override = ResourceLoader.load(MAT_PEBBLE)
	mi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_ON
	rb.add_child(mi)
	mi.owner = rb

	var au := AudioStreamPlayer3D.new()
	au.name = "Audio"
	au.unit_size = 4.0
	au.max_distance = 40.0
	au.stream = ResourceLoader.load("res://audio/stone_click_1.wav")
	rb.add_child(au)
	au.owner = rb

	_save_scene(rb, ROCK_SCENE, "Rock")
	_verify(ROCK_SCENE, ["Col", "Mesh", "Audio", "rock.gd", "groups", "rock",
						 "contact_monitor", "PhysicsMaterial"])


func _save(res: Resource, path: String, label: String) -> void:
	var d := path.get_base_dir()
	if not DirAccess.dir_exists_absolute(d):
		DirAccess.make_dir_recursive_absolute(d)
	var e := ResourceSaver.save(res, path)
	_say("%s -> %s %s" % [label, path, "OK" if e == OK else "ERR %d" % e])
	if e == OK:
		res.take_over_path(path)


func _save_scene(root: Node, path: String, label: String) -> void:
	var ps := PackedScene.new()
	var e := ps.pack(root)
	if e != OK:
		push_error("G4: pack %s failed %d" % [label, e])
		return
	var d := path.get_base_dir()
	if not DirAccess.dir_exists_absolute(d):
		DirAccess.make_dir_recursive_absolute(d)
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
		push_error("G4: %s missing %s" % [path, str(missing)])
		_say("!! %s missing %s" % [path, str(missing)])
