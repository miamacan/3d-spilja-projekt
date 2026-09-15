extends SceneTree
# Snima jednu "hero" sliku scene iz referentne kamere kao PNG, uz dugo
# zagrijavanje da se volumetrijska magla stigne stabilizirati.

var _out: String = "user://hero_shot.png"
var _warmup: int = 120
var _frames: int = 0
var _done: bool = false
var _fired: bool = false
var _overrides: Dictionary = {}
var _root_node: Node
var _deltas: PackedFloat64Array = PackedFloat64Array()


func _initialize() -> void:
	_parse_args()

	var packed: PackedScene = load("res://scenes/main.tscn")
	if packed == null:
		push_error("hero_shot: could not load res://scenes/main.tscn")
		quit(2)
		return
	_root_node = packed.instantiate()
	root.add_child(_root_node)

	for n in ["Player", "RouteAudit"]:
		var d := _root_node.get_node_or_null(n)
		if d:
			d.free()

	_apply_overrides()

	var cam := _root_node.get_node_or_null("HeroCam") as Camera3D
	if cam == null:
		push_error("hero_shot: no HeroCam in main.tscn -- run g2_lighting.gd first")
		quit(3)
		return
	if cam.get_script() != null:
		cam.set_script(null)
	cam.current = true

	DisplayServer.window_set_vsync_mode(DisplayServer.VSYNC_DISABLED)

	print("hero_shot: out=%s warmup=%d overrides=%s" % [_out, _warmup, str(_overrides)])
	print("hero_shot: cam pos %v  fov %.1f" % [cam.global_position, cam.fov])


func _parse_args() -> void:
	var a := OS.get_cmdline_user_args()
	var i := 0
	while i < a.size():
		var k := String(a[i])
		var v := String(a[i + 1]) if i + 1 < a.size() else ""
		match k:
			"--out":          _out = v; i += 2
			"--warmup":       _warmup = int(v); i += 2
			"--exposure":     _overrides["exposure"] = float(v); i += 2
			"--fog-density":  _overrides["fog_density"] = float(v); i += 2
			"--fog-aniso":    _overrides["fog_aniso"] = float(v); i += 2
			"--sun-energy":   _overrides["sun_energy"] = float(v); i += 2
			"--sun-fog":      _overrides["sun_fog"] = float(v); i += 2
			"--glow-threshold": _overrides["glow_threshold"] = float(v); i += 2
			"--ambient":      _overrides["ambient"] = float(v); i += 2
			"--no-fog":       _overrides["fog_off"] = true; i += 1
			"--hide-water":   _overrides["hide_water"] = true; i += 1
			"--no-glow":      _overrides["glow_off"] = true; i += 1
			_:                i += 1


func _apply_overrides() -> void:
	if _overrides.is_empty():
		return
	var we := _root_node.get_node_or_null("WorldEnvironment") as WorldEnvironment
	if we and we.environment:
		var e: Environment = we.environment.duplicate(true)
		we.environment = e
		if _overrides.has("exposure"):       e.tonemap_exposure = _overrides["exposure"]
		if _overrides.has("fog_density"):    e.volumetric_fog_density = _overrides["fog_density"]
		if _overrides.has("fog_aniso"):      e.volumetric_fog_anisotropy = _overrides["fog_aniso"]
		if _overrides.has("glow_threshold"): e.glow_hdr_threshold = _overrides["glow_threshold"]
		if _overrides.has("ambient"):        e.ambient_light_sky_contribution = _overrides["ambient"]
		if _overrides.has("fog_off"):        e.volumetric_fog_enabled = false
		if _overrides.has("glow_off"):       e.glow_enabled = false
	if _overrides.has("hide_water"):
		var surf := _find(_root_node, "WATER_Pool_Surface")
		if surf is GeometryInstance3D:
			(surf as GeometryInstance3D).visible = false
			print("hero_shot: water surface hidden")
		else:
			print("hero_shot: WATER_Pool_Surface not found to hide")
	var sun := _root_node.get_node_or_null("Skylight") as DirectionalLight3D
	if sun:
		if _overrides.has("sun_energy"): sun.light_energy = _overrides["sun_energy"]
		if _overrides.has("sun_fog"):    sun.light_volumetric_fog_energy = _overrides["sun_fog"]


func _process(_delta: float) -> bool:
	if _done:
		return true
	_frames += 1
	if _frames > _warmup / 2:
		_deltas.append(_delta)
	if _frames >= _warmup and not _fired:
		_fired = true
		_capture()
	return false


func _capture() -> void:
	await RenderingServer.frame_post_draw
	var tex := root.get_texture()
	if tex == null:
		push_error("hero_shot: no viewport texture")
		_done = true
		return
	var img: Image = tex.get_image()
	var dir := _out.get_base_dir()
	if dir != "" and not dir.begins_with("user:") and not dir.begins_with("res:"):
		DirAccess.make_dir_recursive_absolute(dir)
	var err := img.save_png(_out)
	if err == OK:
		print("hero_shot: WROTE %s  %dx%d  after %d frames" % [_out, img.get_width(), img.get_height(), _frames])
	else:
		push_error("hero_shot: save_png failed err %d for %s" % [err, _out])
	_report_frame_time()
	_done = true


func _report_frame_time() -> void:
	if _deltas.is_empty():
		return
	var ms: Array[float] = []
	for d in _deltas:
		ms.append(float(d) * 1000.0)
	ms.sort()
	var total := 0.0
	for v in ms:
		total += v
	var mean := total / float(ms.size())
	var p95 := ms[int(floor(float(ms.size() - 1) * 0.95))]
	print("hero_shot: FRAMETIME n=%d mean=%.2fms p95=%.2fms max=%.2fms -> %s" % [
		ms.size(), mean, p95, ms[ms.size() - 1],
		"PASS under 16ms" if p95 < 16.0 else "OVER 16ms"])


func _find(n: Node, nm: String) -> Node:
	if String(n.name) == nm:
		return n
	for c in n.get_children():
		var r := _find(c, nm)
		if r != null:
			return r
	return null
