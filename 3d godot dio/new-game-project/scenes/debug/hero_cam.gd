extends Camera3D
##
## Hero-view check camera. Press H in game to jump between the player's eyes and
## MARK_HeroView, so the composition can be compared against
## reference/cave_ref_hero.png without moving the player.
##
## Also prints the frame time while the hero view is active, because the G2
## done-when includes "frame time stays under 16 ms" and this is the view that
## costs the most.
##

@export var player_cam_path: NodePath = ^"../Player/Player/Head/Camera3D"
@export var toggle_keycode: Key = KEY_H
@export var show_stats: bool = true

var _label: Label
var _accum: float = 0.0
var _frames: int = 0


func _ready() -> void:
	if show_stats:
		var cl := CanvasLayer.new()
		cl.layer = 10
		add_child(cl)
		_label = Label.new()
		_label.position = Vector2(14, 110)
		_label.add_theme_color_override("font_color", Color(1, 1, 1))
		_label.add_theme_color_override("font_outline_color", Color(0, 0, 0, 0.85))
		_label.add_theme_constant_override("outline_size", 6)
		cl.add_child(_label)
		_label.visible = false


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and not event.echo and event.keycode == toggle_keycode:
		if current:
			var c := get_node_or_null(player_cam_path)
			if c is Camera3D:
				(c as Camera3D).current = true
			else:
				push_warning("hero_cam: player camera not found at %s" % player_cam_path)
		else:
			current = true
		if _label:
			_label.visible = current
		get_viewport().set_input_as_handled()


func _process(delta: float) -> void:
	if _label == null or not current:
		return
	_accum += delta
	_frames += 1
	if _accum >= 0.5:
		var ms := (_accum / float(_frames)) * 1000.0
		_label.text = "HERO VIEW  %.2f ms  (%.0f fps)   pos %v   fov %.0f" % [
			ms, 1000.0 / maxf(ms, 0.0001), global_position, fov
		]
		_accum = 0.0
		_frames = 0
