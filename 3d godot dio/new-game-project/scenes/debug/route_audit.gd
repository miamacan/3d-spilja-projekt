extends Node3D
# G1 test prohodnosti - vodi igrača kroz niz točaka pravom fizikom i
# bilježi gdje zapinje, propada, ili ne može preći. Tipka F4 pokreće
# test ponovno.

@export var run_on_start := true
@export var player_path: NodePath = ^"../Player/Player"
@export var env_path: NodePath = ^"../Env"

@export_group("Thresholds")
@export var arrive_radius := 1.0
@export var leg_timeout := 35.0
@export var stuck_window := 1.2
@export var stuck_progress := 0.15
@export var float_window := 0.6
@export var fall_below_y := -8.0
@export var headroom_min := 1.9
@export var step_report := 0.30
@export var slope_spec_deg := 40.0

@export_group("Output")
@export var report_name := "route_audit.txt"

const ROUTES := {
	"A  spawn -> tunnel -> cave mouth -> outcrop crest": [
		Vector3(-3.00, 5.52, 29.00),
		Vector3(-2.60, 5.49, 25.50),
		Vector3(-1.20, 5.48, 23.20),
		Vector3(-0.20, 5.48, 22.00),
		Vector3( 0.00, 5.50, 21.00),
		Vector3( 0.00, 5.55, 18.50),
		Vector3( 0.00, 5.55, 14.00),
		Vector3(-0.50, 5.41, 11.00),
		Vector3(-1.50, 5.39,  8.00),
		Vector3(-2.20, 5.60,  5.00),
	],
	"B  crest -> west ramp -> talus -> beach": [
		Vector3(-2.20, 5.60,  5.00),
		Vector3(-1.50, 5.39,  8.00),
		Vector3(-2.25, 5.10, 11.00),
		Vector3(-3.00, 4.70, 11.00),
		Vector3(-4.50, 4.10, 11.00),
		Vector3(-5.25, 3.80, 11.00),
		Vector3(-5.25, 3.50,  8.50),
		Vector3(-4.80, 3.30,  8.00),
		Vector3(-5.25, 1.20,  5.80),
		Vector3(-6.00, 0.30,  3.50),
		Vector3(-7.20, 0.30,  2.60),
		Vector3(-5.20, 0.30,  1.60),
	],
	"C  beach -> back up the talus -> crest (the climb)": [
		Vector3(-6.00, 0.30,  3.50),
		Vector3(-5.25, 1.20,  5.80),
		Vector3(-4.80, 3.30,  8.00),
		Vector3(-5.25, 3.50,  8.50),
		Vector3(-5.25, 3.80, 11.00),
		Vector3(-4.50, 4.10, 11.00),
		Vector3(-3.00, 4.70, 11.00),
		Vector3(-2.25, 5.10, 11.00),
		Vector3(-1.50, 5.39,  8.00),
		Vector3(-2.20, 5.60,  5.00),
	],
	"D  loop the clearing -> back to the mouth": [
		Vector3(-3.00, 5.52, 29.00),
		Vector3(-7.00, 5.50, 30.00),
		Vector3(-7.00, 5.50, 24.00),
		Vector3( 3.00, 5.50, 24.00),
		Vector3( 4.00, 5.50, 31.00),
		Vector3(-3.00, 5.52, 29.00),
		Vector3( 0.00, 5.50, 21.00),
	],
}

var _player: CharacterBody3D
var _env: Node3D
var _label: Label

var _running := false
var _route_keys: Array = []
var _route_i := 0
var _wp_i := 0
var _points: Array[Vector3] = []

var _leg_t := 0.0
var _win_t := 0.0
var _win_dist := 0.0
var _air_t := 0.0
var _prev_pos := Vector3.ZERO
var _last_grounded := Vector3.ZERO
var _leg_max_slope := 0.0
var _leg_max_step := 0.0
var _leg_min_head := 99.0
var _leg_flags := {}
var _lines: Array[String] = []
var _issue_count := 0


func _ready() -> void:
	_player = get_node_or_null(player_path) as CharacterBody3D
	_env = get_node_or_null(env_path) as Node3D
	_label = Label.new()
	var layer := CanvasLayer.new()
	layer.layer = 2
	add_child(layer)
	layer.add_child(_label)
	_label.set_anchors_preset(Control.PRESET_BOTTOM_LEFT)
	_label.offset_left = 14.0
	_label.offset_top = -120.0
	_label.offset_bottom = -10.0
	_label.offset_right = 900.0
	_label.add_theme_color_override("font_outline_color", Color(0, 0, 0, 0.85))
	_label.add_theme_constant_override("outline_size", 6)
	_label.text = ""

	if _player == null:
		push_error("RouteAudit: player not found at %s" % player_path)
		return
	if run_on_start:
		start.call_deferred()


func _to_world(p: Vector3) -> Vector3:
	return _env.global_transform * p if _env != null else p


func start() -> void:
	if _player == null:
		return
	_route_keys = ROUTES.keys()
	_route_keys.sort()
	_route_i = 0
	_lines.clear()
	_issue_count = 0
	_lines.append("G1 route audit  -  %s" % Time.get_datetime_string_from_system())
	_lines.append("capsule h 1.8 r 0.4, floor_max_angle %.0f deg, floor_snap %.2f, gravity %.2f" % [
		rad_to_deg(_player.floor_max_angle), _player.floor_snap_length,
		absf(_player.get_gravity().y)])
	if _env != null and not _env.transform.is_equal_approx(Transform3D.IDENTITY):
		_lines.append("NOTE: Env is not at the origin (%s). Waypoints were offset to match." % _env.position)
	_lines.append("")
	_running = true
	_begin_route()


func stop(reason: String = "aborted") -> void:
	if not _running:
		return
	_running = false
	_player.auto_control = false
	_player.auto_wish_dir = Vector3.ZERO
	_lines.append("")
	_lines.append("audit %s. %d issue(s)." % [reason, _issue_count])
	_write_report()
	_label.text = "ROUTE AUDIT %s - %d issue(s). Report: res://%s" % [
		reason, _issue_count, report_name]


func _begin_route() -> void:
	if _route_i >= _route_keys.size():
		stop("finished")
		return
	var key: String = _route_keys[_route_i]
	_points.clear()
	for p in ROUTES[key]:
		_points.append(_to_world(p as Vector3))
	_lines.append("=== ROUTE %s" % key)
	_wp_i = 0
	_player.auto_control = true
	_player.auto_sprint = false
	_player.teleport_to(_points[0] + Vector3(0.0, 0.3, 0.0))
	_wp_i = 1
	_begin_leg()


func _begin_leg() -> void:
	_leg_t = 0.0
	_win_t = 0.0
	_air_t = 0.0
	_leg_max_slope = 0.0
	_leg_max_step = 0.0
	_leg_min_head = 99.0
	_leg_flags = {}
	_prev_pos = _player.global_position
	_last_grounded = _player.global_position
	_win_dist = _horiz(_player.global_position, _points[_wp_i])


func _horiz(a: Vector3, b: Vector3) -> float:
	return Vector2(a.x - b.x, a.z - b.z).length()


func _issue(kind: String, detail: String) -> void:
	if _leg_flags.has(kind):
		return
	_leg_flags[kind] = true
	_issue_count += 1
	_lines.append("  !! %-12s leg %d->%d  %s" % [kind, _wp_i - 1, _wp_i, detail])


func _fmt(p: Vector3) -> String:
	return "at (%.2f, %.2f, %.2f)" % [p.x, p.y, p.z]


func _colliders() -> String:
	var names: Array[String] = []
	for i in _player.get_slide_collision_count():
		var c := _player.get_slide_collision(i)
		var o := c.get_collider()
		if o == null:
			continue
		var label := String(o.name)
		var par := (o as Node).get_parent()
		if par != null and label.begins_with("StaticBody"):
			label = "%s/%s" % [par.name, label]
		if not names.has(label):
			names.append(label)
	return ", ".join(names) if not names.is_empty() else "nothing"


func _headroom() -> float:
	var space := _player.get_world_3d().direct_space_state
	var from := _player.global_position + Vector3(0.0, 0.45, 0.0)
	var q := PhysicsRayQueryParameters3D.create(from, from + Vector3(0.0, 4.0, 0.0))
	q.exclude = [_player.get_rid()]
	var hit := space.intersect_ray(q)
	return (hit.position.y - _player.global_position.y) if hit else 99.0


func _input(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and not event.is_echo():
		var k := event as InputEventKey
		if k.keycode == KEY_F4:
			if _running:
				stop("aborted (F4)")
			else:
				start()
	if _running and event.is_pressed():
		for a in ["move_forward", "move_back", "move_left", "move_right"]:
			if InputMap.has_action(a) and event.is_action_pressed(a):
				stop("aborted (you took over)")
				return


func _physics_process(delta: float) -> void:
	if not _running or _player == null or _wp_i >= _points.size():
		return

	var pos := _player.global_position
	var target := _points[_wp_i]
	_leg_t += delta
	_win_t += delta

	if pos.y < fall_below_y:
		_issue("FELL-THROUGH", "left the level below y=%.1f, last ground %s" % [
			fall_below_y, _fmt(_last_grounded)])
		_player.teleport_to(_last_grounded + Vector3(0.0, 0.3, 0.0))
		_next_waypoint()
		return

	if _player.is_on_floor():
		_air_t = 0.0
		_last_grounded = pos
		_leg_max_slope = maxf(_leg_max_slope, rad_to_deg(_player.get_floor_angle()))
		var dy := pos.y - _prev_pos.y
		if dy > step_report:
			_leg_max_step = maxf(_leg_max_step, dy)
			_issue("STEP", "climbed %.2f m in one tick %s (%s)" % [dy, _fmt(pos), _colliders()])
	else:
		_air_t += delta
		if _air_t > float_window and absf(_player.velocity.y) < 0.6:
			_issue("FLOATING", "airborne %.1f s with vy %.2f %s" % [_air_t, _player.velocity.y, _fmt(pos)])

	var head := _headroom()
	_leg_min_head = minf(_leg_min_head, head)
	if head < headroom_min:
		_issue("LOW-CEILING", "%.2f m of headroom %s" % [head, _fmt(pos)])

	var to := target - pos
	to.y = 0.0
	var d := to.length()
	if d < arrive_radius:
		var dy_err := pos.y - target.y
		if absf(dy_err) > 1.0:
			_lines.append("  ~  wp %d reached %.2f m %s than authored (%s)" % [
				_wp_i, absf(dy_err), "higher" if dy_err > 0.0 else "lower", _fmt(pos)])
		_next_waypoint()
		return

	_player.auto_wish_dir = to / d

	if _win_t >= stuck_window:
		if (_win_dist - d) < stuck_progress:
			_issue("STUCK", "%.2f m of progress in %.1f s, %.1f m short of wp %d %s, touching %s" % [
				_win_dist - d, _win_t, d, _wp_i, _fmt(pos), _colliders()])
		_win_t = 0.0
		_win_dist = d

	if _leg_t > leg_timeout:
		_issue("UNREACHABLE", "gave up after %.0f s, %.1f m short of wp %d %s" % [
			_leg_t, d, _wp_i, _fmt(pos)])
		_next_waypoint()
		return

	_prev_pos = pos
	_label.text = "ROUTE AUDIT  %s\nwaypoint %d/%d   %.1f m to go   %.0f s   issues %d\nF4 abort  -  or press W/A/S/D to take over" % [
		_route_keys[_route_i], _wp_i, _points.size() - 1, d, _leg_t, _issue_count]


func _next_waypoint() -> void:
	if _leg_max_slope > slope_spec_deg:
		_issue("OVER-SPEC", "floor reached %.1f deg, brief caps walkable slope at %.0f" % [
			_leg_max_slope, slope_spec_deg])
	_lines.append("  ok wp %d  %.1fs  max slope %.1f deg  max step %.2f m  min headroom %s" % [
		_wp_i, _leg_t, _leg_max_slope, _leg_max_step,
		("%.2f m" % _leg_min_head) if _leg_min_head < 90.0 else "open sky"])
	_wp_i += 1
	if _wp_i >= _points.size():
		_lines.append("")
		_route_i += 1
		_begin_route()
		return
	_begin_leg()


func _write_report() -> void:
	var text := "\n".join(_lines)
	var f := FileAccess.open("user://" + report_name, FileAccess.WRITE)
	if f != null:
		f.store_string(text)
		f.close()
	if OS.has_feature("editor"):
		var g := FileAccess.open("res://" + report_name, FileAccess.WRITE)
		if g != null:
			g.store_string(text)
			g.close()
	print("\n" + text + "\n")
