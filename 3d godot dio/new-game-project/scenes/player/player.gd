extends CharacterBody3D

## First-person walker for the limestone cave blockout (G1).
##
## Capsule 1.8 m / r 0.4, eye at 1.65 m, 75 deg FOV.
## Yaw on the body, pitch on Head. Spawns at MARK_PlayerSpawn inside the
## imported cave_env.glb and takes its facing from the marker's -Z.
##
## The route auditor (scenes/debug/route_audit.gd) drives this same body by
## setting `auto_control` and `auto_wish_dir`, so the audit measures the real
## capsule against the real colliders, not a raycast approximation.

const SETTING_SENSITIVITY := "player/mouse_sensitivity"
const SETTING_INVERT_Y := "player/invert_y"

@export_group("Movement")
## Metres per second on flat ground.
@export var walk_speed := 4.0
@export var sprint_speed := 6.5
## Higher = snappier. Units are m/s per second.
@export var ground_accel := 14.0
@export var ground_decel := 18.0
@export var air_accel := 3.0
@export var jump_enabled := true
## Apex height in metres. Converted to an impulse against project gravity.
@export var jump_height := 0.9

@export_group("Look")
## Radians of rotation per pixel of mouse movement. Overridden at runtime by
## the project setting `player/mouse_sensitivity` when that exists.
@export var mouse_sensitivity := 0.0022
@export_range(1.0, 89.0, 0.5) var pitch_limit_deg := 89.0
@export var invert_y := false

@export_group("Head bob")
@export var bob_enabled := true
## Vertical travel of the eye, in metres. The brief asks for 2 cm.
@export var bob_amplitude := 0.02
## Bob cycles per metre walked. One cycle = two footfalls.
@export var bob_cycles_per_metre := 0.55

@export_group("Spawn")
@export var spawn_marker := "MARK_PlayerSpawn"
## Lift above the marker so the capsule never starts embedded in the floor.
@export var spawn_lift := 0.1
@export var use_marker_facing := true
## Used only when the marker cannot be found. Blender (-3, -29, 5.517).
@export var fallback_spawn := Vector3(-3.0, 5.6, 29.0)

@export_group("Throwing")
## G4. Charge by holding `throw`, release to throw. Hold time is clamped into
## [charge_min, charge_max] and mapped onto [speed_min, speed_max], so a quick
## tap still throws -- it just throws softly.
@export var throw_enabled := true
@export var rock_scene_path := "res://scenes/rock/Rock.tscn"
@export var charge_min := 0.3
@export var charge_max := 1.2
@export var speed_min := 6.0
@export var speed_max := 16.0
@export var throw_cooldown := 0.4
@export var spawn_ahead := 0.6
@export var max_live_rocks := 30
@export var rock_ttl := 20.0

@export_group("Viewmodel")
@export var viewmodel_enabled := true
@export var viewmodel_mesh_path := "res://scenes/rock/rock_mesh_1.res"
@export var viewmodel_material_path := "res://scenes/rock/M_RockViewmodel.tres"
## Camera-local. Bottom-right, close enough to read, far enough not to clip the
## near plane at 0.05.
@export var viewmodel_rest := Vector3(0.30, -0.24, -0.62)
@export var viewmodel_scale := 0.85

@export_group("Debug")
@export var hud_visible := true

# --- scripted control, used by the route auditor -----------------------------
var auto_control := false
var auto_wish_dir := Vector3.ZERO  # world space, horizontal, normalised
var auto_sprint := false

var _pitch := 0.0
var _charging := false
var _charge := 0.0
var _cooldown := 0.0
var _rocks: Array[Node] = []
var _rock_scene: PackedScene
var _viewmodel: MeshInstance3D
var _vm_lift := 0.0
var _vm_spin := 0.0
var _bob_phase := 0.0
var _bob_weight := 0.0
var _head_rest_y := 1.65
var _spawn_found := false

@onready var head: Node3D = $Head
@onready var camera: Camera3D = $Head/Camera3D
@onready var _hud: CanvasLayer = $HUD
@onready var _stats: Label = $HUD/Stats


func _ready() -> void:
	if ProjectSettings.has_setting(SETTING_SENSITIVITY):
		mouse_sensitivity = float(ProjectSettings.get_setting(SETTING_SENSITIVITY))
	if ProjectSettings.has_setting(SETTING_INVERT_Y):
		invert_y = bool(ProjectSettings.get_setting(SETTING_INVERT_Y))

	_head_rest_y = head.position.y
	_hud.visible = hud_visible
	Input.mouse_mode = Input.MOUSE_MODE_CAPTURED
	if throw_enabled:
		_rock_scene = ResourceLoader.load(rock_scene_path)
		if _rock_scene == null:
			push_warning("Player: %s missing, throwing disabled" % rock_scene_path)
		if not _has("throw"):
			push_warning("Player: no 'throw' action in the input map")
		_build_viewmodel()
	teleport_to_spawn.call_deferred()


# -----------------------------------------------------------------------------
# Spawn
# -----------------------------------------------------------------------------

func find_spawn_marker() -> Node3D:
	var root: Node = get_tree().current_scene
	if root == null:
		root = get_tree().root
	# owned = false: the markers come in as children of the .glb instance and
	# are not owned by the current scene's root.
	return root.find_child(spawn_marker, true, false) as Node3D


func teleport_to_spawn() -> void:
	var m := find_spawn_marker()
	var p := fallback_spawn
	if m != null:
		_spawn_found = true
		p = m.global_position
		if use_marker_facing:
			var f := -m.global_transform.basis.z
			f.y = 0.0
			if f.length_squared() > 0.000001:
				f = f.normalized()
				rotation.y = atan2(-f.x, -f.z)
	else:
		push_warning("Player: '%s' not found in the scene; using fallback_spawn." % spawn_marker)
	teleport_to(p + Vector3(0.0, spawn_lift, 0.0))


func teleport_to(world_pos: Vector3) -> void:
	global_position = world_pos
	velocity = Vector3.ZERO
	_bob_weight = 0.0
	head.position.y = _head_rest_y


# -----------------------------------------------------------------------------
# Input
# -----------------------------------------------------------------------------

func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventMouseMotion and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
		var mm := event as InputEventMouseMotion
		rotate_y(-mm.relative.x * mouse_sensitivity)
		var dy := mm.relative.y * mouse_sensitivity
		if invert_y:
			dy = -dy
		var lim := deg_to_rad(pitch_limit_deg)
		_pitch = clampf(_pitch - dy, -lim, lim)
		head.rotation.x = _pitch
		return

	if event is InputEventKey and event.pressed and not event.is_echo():
		var k := event as InputEventKey
		if k.keycode == KEY_F3:
			hud_visible = not hud_visible
			_hud.visible = hud_visible
			return

	if event is InputEventMouseButton and event.pressed \
			and Input.mouse_mode != Input.MOUSE_MODE_CAPTURED:
		Input.mouse_mode = Input.MOUSE_MODE_CAPTURED
		return

	if throw_enabled and not auto_control and _has("throw") \
			and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
		if event.is_action_pressed("throw"):
			_begin_charge()
			return
		if event.is_action_released("throw"):
			_release_charge()
			return

	if _has("pause") and event.is_action_pressed("pause"):
		Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
	elif event.is_action_pressed("ui_cancel"):
		Input.mouse_mode = Input.MOUSE_MODE_VISIBLE


static func _has(action: StringName) -> bool:
	return InputMap.has_action(action)


func _wish_dir() -> Vector3:
	if auto_control:
		var d := auto_wish_dir
		d.y = 0.0
		return d.normalized() if d.length_squared() > 0.000001 else Vector3.ZERO

	if not (_has("move_left") and _has("move_right") and _has("move_forward") and _has("move_back")):
		return Vector3.ZERO
	var iv := Input.get_vector("move_left", "move_right", "move_forward", "move_back")
	if iv.length_squared() < 0.000001:
		return Vector3.ZERO
	var b := global_transform.basis
	var dir := (b.x * iv.x) + (b.z * iv.y)
	dir.y = 0.0
	return dir.normalized() if dir.length_squared() > 0.000001 else Vector3.ZERO


# -----------------------------------------------------------------------------
# Movement
# -----------------------------------------------------------------------------

func _physics_process(delta: float) -> void:
	var g := get_gravity()
	if not is_on_floor():
		velocity += g * delta

	if jump_enabled and not auto_control and is_on_floor() \
			and _has("jump") and Input.is_action_just_pressed("jump"):
		velocity.y = sqrt(2.0 * absf(g.y) * jump_height)

	var wish := _wish_dir()
	var sprinting := auto_sprint if auto_control \
			else (_has("sprint") and Input.is_action_pressed("sprint"))
	var target := wish * (sprint_speed if sprinting else walk_speed)

	var hv := Vector3(velocity.x, 0.0, velocity.z)
	var rate := air_accel
	if is_on_floor():
		rate = ground_accel if wish.length_squared() > 0.0 else ground_decel
	hv = hv.move_toward(Vector3(target.x, 0.0, target.z), rate * delta)
	velocity.x = hv.x
	velocity.z = hv.z

	move_and_slide()
	_update_bob(delta)
	_update_throw(delta)
	_update_hud()


func _update_bob(delta: float) -> void:
	var hs := Vector2(velocity.x, velocity.z).length()
	var moving := bob_enabled and is_on_floor() and hs > 0.2
	_bob_weight = move_toward(_bob_weight, 1.0 if moving else 0.0, delta * 5.0)
	if moving:
		_bob_phase += hs * delta * bob_cycles_per_metre * TAU
	head.position.y = _head_rest_y + sin(_bob_phase) * bob_amplitude * _bob_weight


# -----------------------------------------------------------------------------
# HUD
# -----------------------------------------------------------------------------

func _update_hud() -> void:
	if not _hud.visible:
		return
	var p := global_position
	var slope := rad_to_deg(get_floor_angle()) if is_on_floor() else -1.0
	_stats.text = "pos   %6.2f  %6.2f  %6.2f\nspeed %5.2f m/s   vy %6.2f\nfloor %s   slope %s\nfps   %d%s" % [
		p.x, p.y, p.z,
		Vector2(velocity.x, velocity.z).length(), velocity.y,
		"yes" if is_on_floor() else "NO ",
		("%.1f deg" % slope) if slope >= 0.0 else "-",
		Engine.get_frames_per_second(),
		"" if _spawn_found else "   [spawn marker NOT found]",
	]
	if throw_enabled:
		_stats.text += "\nrocks  %d/%d   charge %.2f s -> %.1f m/s%s" % [
			_rocks.size(), max_live_rocks, _charge, _charge_speed(),
			"   [cooldown]" if _cooldown > 0.0 else "",
		]


# -----------------------------------------------------------------------------
# Throwing (G4)
# -----------------------------------------------------------------------------

func _begin_charge() -> void:
	if _cooldown > 0.0 or _rock_scene == null:
		return
	_charging = true
	_charge = 0.0


func _release_charge() -> void:
	if not _charging:
		return
	_charging = false
	var speed := _charge_speed()
	_charge = 0.0
	_cooldown = throw_cooldown
	_spawn_rock(speed)


## Hold time -> launch speed. Clamped at both ends: under charge_min a tap still
## throws at speed_min rather than dribbling out at zero, and over charge_max
## holding longer gains nothing.
func _charge_speed() -> float:
	var t := clampf(_charge, charge_min, charge_max)
	var f := (t - charge_min) / maxf(charge_max - charge_min, 0.001)
	return lerpf(speed_min, speed_max, f)


func get_charge_ratio() -> float:
	return clampf(_charge / maxf(charge_max, 0.001), 0.0, 1.0)


func live_rock_count() -> int:
	return _rocks.size()


func _update_throw(delta: float) -> void:
	if _cooldown > 0.0:
		_cooldown = maxf(0.0, _cooldown - delta)
	if _charging:
		_charge = minf(_charge + delta, charge_max)
	_update_viewmodel(delta)


func _spawn_rock(speed: float) -> void:
	if _rock_scene == null:
		return
	var host: Node = get_tree().current_scene
	if host == null:
		host = get_parent()
	var rb := _rock_scene.instantiate() as RigidBody3D
	if rb == null:
		return
	host.add_child(rb)
	var fwd := -camera.global_transform.basis.z
	rb.global_position = camera.global_position + fwd * spawn_ahead
	# impulse = mass * delta-v, so this lands the rock at exactly `speed`
	rb.apply_central_impulse(fwd * speed * rb.mass)
	rb.angular_velocity = Vector3(
		randf_range(-9.0, 9.0), randf_range(-9.0, 9.0), randf_range(-9.0, 9.0))
	rb.set("lifetime", rock_ttl)
	_rocks.append(rb)
	_prune_rocks()


## Keeps the live count bounded. water.gd frees rocks that sink and rock.gd
## frees itself after rock_ttl, but a rock wedged in a crevice would otherwise
## sit there until then -- and the cap is what keeps spamming cheap.
func _prune_rocks() -> void:
	var keep: Array[Node] = []
	for r in _rocks:
		if is_instance_valid(r):
			keep.append(r)
	_rocks = keep
	while _rocks.size() > max_live_rocks:
		var old: Node = _rocks.pop_front()
		if is_instance_valid(old):
			old.queue_free()


# -----------------------------------------------------------------------------
# Viewmodel
# -----------------------------------------------------------------------------

func _build_viewmodel() -> void:
	if not viewmodel_enabled or camera == null:
		return
	var m: Mesh = ResourceLoader.load(viewmodel_mesh_path)
	if m == null:
		push_warning("Player: viewmodel mesh %s missing" % viewmodel_mesh_path)
		return
	_viewmodel = MeshInstance3D.new()
	_viewmodel.name = "Viewmodel"
	_viewmodel.mesh = m
	_viewmodel.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	var mat: Material = ResourceLoader.load(viewmodel_material_path)
	if mat != null:
		_viewmodel.material_override = mat
	camera.add_child(_viewmodel)
	_viewmodel.position = viewmodel_rest
	_viewmodel.scale = Vector3.ONE * viewmodel_scale
	_viewmodel.rotation = Vector3(0.0, 0.0, 0.0)


func _update_viewmodel(delta: float) -> void:
	if _viewmodel == null:
		return
	# "disappears on release": hidden for the cooldown, back when ready again.
	_viewmodel.visible = _cooldown <= 0.0
	var target := get_charge_ratio() if _charging else 0.0
	_vm_lift = move_toward(_vm_lift, target, delta * 5.0)
	_viewmodel.position = viewmodel_rest + Vector3(-0.025, 0.06, 0.035) * _vm_lift
	_vm_spin += delta * 0.7
	_viewmodel.rotation = Vector3(-0.55 * _vm_lift, _vm_spin, 0.15 * _vm_lift)
