extends SceneTree
# G3 test: baci kamen u jezero i provjeri je li se pljusak, val i krug
# stvarno dogodili - ne samo vizualno, provjerava se i unutarnje stanje.

var _out_dir := "user://"
var _t := 0.0
var _frames := 0
var _drop_at := 2.0
var _dropped := false
var _impact_t := -1.0
var _shots: Array = []
var _main: Node
var _water: Node
var _rock: RigidBody3D
var _log := {}
var _busy := false
var _finished := false


func _initialize() -> void:
	var a := OS.get_cmdline_user_args()
	for i in range(a.size() - 1):
		if String(a[i]) == "--out-dir":
			_out_dir = String(a[i + 1])

	var packed: PackedScene = load("res://scenes/main.tscn")
	_main = packed.instantiate()
	root.add_child(_main)
	for n in ["Player", "RouteAudit"]:
		var d := _main.get_node_or_null(n)
		if d:
			d.free()

	DisplayServer.window_set_vsync_mode(DisplayServer.VSYNC_DISABLED)

	_water = _main.get_node_or_null("Water")
	_log["water_node"] = _water != null
	_log["volume"] = _water != null and _water.get_node_or_null("Volume") != null
	var vol := _water.get_node_or_null("Volume") if _water else null
	_log["volume_shape"] = vol != null and vol.get_node_or_null("Shape") != null
	_log["probe"] = _water != null and _water.get_node_or_null("Probe") != null

	var cam := Camera3D.new()
	cam.fov = 70.0
	cam.near = 0.05
	cam.far = 300.0
	_main.add_child(cam)
	cam.look_at_from_position(Vector3(-2.2, 7.3, 5.0), Vector3(3.0, 0.0, -1.0), Vector3.UP)
	cam.current = true
	_log["cam_basis_ok"] = not cam.transform.basis.is_equal_approx(Basis())

	_shots = [
		{"name": "a_before", "at": -0.25, "done": false},
		{"name": "b_impact", "at": 0.15, "done": false},
		{"name": "c_spread", "at": 0.50, "done": false},
		{"name": "d_dying", "at": 1.20, "done": false},
	]
	print("g3_probe: started, out_dir=%s" % _out_dir)


func _process(delta: float) -> bool:
	if _finished:
		return true
	_t += delta
	_frames += 1

	if not _dropped and _t >= _drop_at:
		_drop()

	if _impact_t < 0.0 and _dropped:
		_check_impact()

	for s in _shots:
		if s["done"]:
			continue
		var due := -1.0
		if String(s["name"]) == "a_before":
			due = _drop_at + 0.45
		elif _impact_t >= 0.0:
			due = _impact_t + float(s["at"])
		if due >= 0.0 and _t >= due and not _busy:
			s["done"] = true
			_shoot(String(s["name"]))
			break

	var all_done := true
	for s in _shots:
		all_done = all_done and bool(s["done"])
	if all_done and not _busy:
		_report()
		_finished = true
	if _t > 14.0:
		_log["timeout"] = true
		_report()
		_finished = true
	return false


func _drop() -> void:
	_dropped = true
	var ps: PackedScene = load("res://scenes/rock/Rock.tscn")
	if ps == null:
		_log["rock_scene"] = false
		return
	_log["rock_scene"] = true
	_rock = ps.instantiate() as RigidBody3D
	_main.add_child(_rock)
	_rock.global_position = Vector3(3.0, 6.0, -1.0)
	_rock.linear_velocity = Vector3(0.0, -6.0, 0.0)
	_log["rock_in_group"] = _rock.is_in_group("rock")
	_log["rock_layer"] = _rock.collision_layer
	print("g3_probe: rock dropped at t=%.2f" % _t)


func _check_impact() -> void:
	var holder := _water.get_node_or_null("Splashes") if _water else null
	if holder != null and holder.get_child_count() > 0:
		_impact_t = _t
		_log["impact_t"] = snappedf(_t - _drop_at, 0.01)
		_log["splash_spawned"] = true
		print("g3_probe: IMPACT at t=%.2f (%.2f s after drop)" % [_t, _t - _drop_at])


func _shoot(nm: String) -> void:
	_busy = true
	_capture(nm)


func _capture(nm: String) -> void:
	await RenderingServer.frame_post_draw
	var img: Image = root.get_texture().get_image()
	var path := _out_dir.path_join("_g3_probe_%s.png" % nm)
	DirAccess.make_dir_recursive_absolute(_out_dir)
	var e := img.save_png(path)
	print("g3_probe: shot %s -> %s (%s)" % [nm, path, "OK" if e == OK else "ERR %d" % e])
	_snapshot(nm)
	_busy = false


func _snapshot(nm: String) -> void:
	var mat: ShaderMaterial = null
	var surf := _find(_main, "WATER_Pool_Surface") as MeshInstance3D
	if surf != null:
		mat = surf.material_override as ShaderMaterial
	var d := {}
	d["surface_found"] = surf != null
	d["is_shader_material"] = mat != null
	if surf != null:
		d["surface_layers"] = surf.layers
	if mat != null:
		d["ripple_count"] = mat.get_shader_parameter("ripple_count")
		var arr = mat.get_shader_parameter("ripples")
		d["ripple0"] = str(arr[0]) if arr != null and arr.size() > 0 else "-"
		d["time_now"] = snappedf(float(mat.get_shader_parameter("time_now")), 0.01)
	var holder := _water.get_node_or_null("Splashes") if _water else null
	d["splashes_live"] = holder.get_child_count() if holder else -1
	if _rock != null and is_instance_valid(_rock):
		d["rock_y"] = snappedf(_rock.global_position.y, 0.01)
		d["rock_damp"] = _rock.linear_damp
		d["rock_gscale"] = _rock.gravity_scale
	else:
		d["rock"] = "freed"
	_log[nm] = d


func _find(n: Node, nm: String) -> Node:
	if String(n.name) == nm:
		return n
	for c in n.get_children():
		var r := _find(c, nm)
		if r != null:
			return r
	return null


func _report() -> void:
	print("G3_PROBE_JSON:" + JSON.stringify(_log))
	quit()
