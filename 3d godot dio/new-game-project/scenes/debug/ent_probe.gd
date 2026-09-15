extends SceneTree
# Snima nekoliko referentnih kadrova ulaza u špilju iz raznih kutova,
# za usporedbu s pravom fotografijom.

var _out := "user://"
var _tag := "x"
var _i := 0
var _pt := 0.0
var _applied := -1
var _busy := false
var _done := false
var _main: Node
var _cam: Camera3D

const SHOTS := [
	{"name": "mouth", "from": Vector3(-0.4, 7.4, 16.0), "at": Vector3(-0.4, 7.4, 22.0), "fov": 65.0},
	{"name": "close", "from": Vector3(-0.4, 7.4, 19.5), "at": Vector3(-0.4, 7.4, 22.0), "fov": 75.0},
	{"name": "obliq", "from": Vector3(3.2, 8.6, 17.5), "at": Vector3(-0.6, 7.2, 21.2), "fov": 60.0},
	{"name": "outside", "from": Vector3(-0.4, 7.4, 26.0), "at": Vector3(-0.4, 7.4, 20.0), "fov": 65.0},
]


func _initialize() -> void:
	var a := OS.get_cmdline_user_args()
	for i in range(a.size() - 1):
		if String(a[i]) == "--out-dir":
			_out = String(a[i + 1])
		if String(a[i]) == "--tag":
			_tag = String(a[i + 1])
	_main = (load("res://scenes/main.tscn") as PackedScene).instantiate()
	root.add_child(_main)
	current_scene = _main
	for n in ["Player", "RouteAudit"]:
		var d := _main.get_node_or_null(n)
		if d:
			d.free()
	DisplayServer.window_set_vsync_mode(DisplayServer.VSYNC_DISABLED)
	_cam = _main.get_node_or_null("HeroCam") as Camera3D
	if _cam != null:
		if _cam.get_script() != null:
			_cam.set_script(null)
		_cam.current = true


func _process(delta: float) -> bool:
	if _done:
		return true
	_pt += delta
	if _busy:
		return false
	if _cam == null or _i >= SHOTS.size():
		print("ent_probe: done")
		_done = true
		quit()
		return true
	var s: Dictionary = SHOTS[_i]
	if _applied != _i:
		_cam.look_at_from_position(s["from"], s["at"], Vector3.UP)
		_cam.fov = s["fov"]
		_applied = _i
		_pt = 0.0
		print("ent_probe: camera -> %s at %v" % [s["name"], _cam.global_position])
		return false
	var wait := 3.0 if _i == 0 else 1.0
	if _pt < wait:
		return false
	_busy = true
	_shoot(String(s["name"]))
	return false


func _shoot(nm: String) -> void:
	await RenderingServer.frame_post_draw
	await RenderingServer.frame_post_draw
	var img: Image = root.get_texture().get_image()
	DirAccess.make_dir_recursive_absolute(_out)
	img.save_png(_out.path_join("_ent_%s_%s.png" % [_tag, nm]))
	print("ent_probe: shot %s/%s" % [_tag, nm])
	_i += 1
	_pt = 0.0
	_busy = false
