extends SceneTree
# G5 dijagnostika: renderira isti kadar na tri načina (bez mahovine, s
# mahovinom, i s prikazanom maskom) da se vidi točno odakle dolazi
# razlika u svjetlini.

var _out := "user://"
var _t := 0.0
var _ph := 0
var _pt := 0.0
var _busy := false
var _done := false
var _main: Node
var _cam: Camera3D
var _rocks: Array[MeshInstance3D] = []
var _saved: Array = []
var _log := {}


func _initialize() -> void:
	var a := OS.get_cmdline_user_args()
	for i in range(a.size() - 1):
		if String(a[i]) == "--out-dir":
			_out = String(a[i + 1])
	_main = (load("res://scenes/main.tscn") as PackedScene).instantiate()
	root.add_child(_main)
	current_scene = _main
	for n in ["Player", "RouteAudit"]:
		var d := _main.get_node_or_null(n)
		if d: d.free()
	DisplayServer.window_set_vsync_mode(DisplayServer.VSYNC_DISABLED)
	_cam = _main.get_node_or_null("HeroCam") as Camera3D
	if _cam:
		if _cam.get_script() != null: _cam.set_script(null)
		_cam.current = true


func _collect() -> void:
	_rocks.clear(); _saved.clear()
	_walk(_main)
	var names := ["rock_albedo", "rock_normal", "rock_orm",
				  "moss_albedo", "moss_normal", "moss_orm"]
	for mi in _rocks:
		var sm := mi.material_override as ShaderMaterial
		if sm == null: continue
		if String(mi.name) != "CAVE_Shell_Main": continue
		var d := {}
		for n in names:
			var v = sm.get_shader_parameter(n)
			d[n] = (v.resource_path.get_file() if v != null else "<NULL -> samples WHITE>")
		d["debug_mask"] = sm.get_shader_parameter("debug_mask")
		d["mask_threshold"] = sm.get_shader_parameter("mask_threshold")
		_log["shell_params"] = d
	_log["rock_count"] = _rocks.size()


func _walk(n: Node) -> void:
	if n is MeshInstance3D:
		var mi := n as MeshInstance3D
		if mi.material_override is ShaderMaterial and String(mi.name) != "WATER_Pool_Surface":
			_rocks.append(mi)
	for c in n.get_children():
		_walk(c)


func _process(delta: float) -> bool:
	if _done: return true
	_t += delta; _pt += delta
	if _busy: return false
	match _ph:
		0:
			if _pt < 2.5: return false
			_collect()
			for mi in _rocks:
				_saved.append(mi.material_override)
				mi.material_override = null
			_next()
		1:
			if _pt < 0.8: return false
			_shoot("a_plain"); _next()
		2:
			for i in _rocks.size():
				_rocks[i].material_override = _saved[i]
			if _pt < 0.8: return false
			_shoot("b_moss"); _next()
		3:
			for mi in _rocks:
				var sm := mi.material_override as ShaderMaterial
				if sm: sm.set_shader_parameter("debug_mask", 1.0)
			if _pt < 0.8: return false
			_shoot("c_debug"); _next()
		4:
			print("G5_DIAG_JSON:" + JSON.stringify(_log))
			_done = true
			quit()
			return true
	if _t > 40.0:
		print("G5_DIAG_JSON:" + JSON.stringify(_log)); _done = true; quit(); return true
	return false


func _next() -> void:
	_ph += 1; _pt = 0.0


func _shoot(nm: String) -> void:
	_busy = true
	_cap(nm)


func _cap(nm: String) -> void:
	await RenderingServer.frame_post_draw
	var img: Image = root.get_texture().get_image()
	DirAccess.make_dir_recursive_absolute(_out)
	img.save_png(_out.path_join("_g5_diag_%s.png" % nm))
	print("g5_diag: %s" % nm)
	_busy = false
