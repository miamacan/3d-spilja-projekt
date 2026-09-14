@tool
extends Node3D
##
## G3 — the pool: surface material, ripple bookkeeping, and what happens when a
## rock hits it.
##
## Replaces water_placeholder.gd, which existed only to stop the pool rendering
## as Godot's default WHITE (see HANDOFF_GODOT.md §4). The reason this is a
## script on a scene node rather than a material saved into main.tscn is
## unchanged and still important: WATER_Pool_Surface lives inside the instanced
## cave_env.glb, and PackedScene.pack() only records an override there if the
## node's owner is re-pointed at the outer scene -- which makes it serialise the
## whole mesh inline, 105 KB of vertex arrays, forked away from the glb.
##
## @tool so the editor shows the water too, which is what lets the lightmap bake
## see it. All gameplay is guarded behind Engine.is_editor_hint().
##

const MAX_RIPPLES := 16
const SHADER_PATH := "res://shaders/water.gdshader"
const NORMAL_A := "res://assets/textures/T_WaterNormal_A.png"
const NORMAL_B := "res://assets/textures/T_WaterNormal_B.png"
const SPLASH_SCENE := "res://scenes/fx/Splash.tscn"
const SURFACE_NAME := "WATER_Pool_Surface"
## Visual layers for the pool surface: bit 1 (normal rendering) + bit 2, which
## exists only so Water.tscn's ReflectionProbe can target the water and nothing
## else via its reflection_mask. Without that the probe re-lights every rock in
## the chamber with its captured cubemap.
const SURFACE_VISUAL_LAYERS := 1 | 2

@export var rock_group: StringName = &"rock"
## Below this impact speed a rock gets no splash and no sound -- a rock that
## rolls gently off the beach should not sound like one thrown from the crest.
@export var min_impact_speed := 0.8
@export_group("Sinking")
@export var sink_linear_damp := 6.0
@export var sink_angular_damp := 4.0
@export var sink_gravity_scale := 0.4
@export var rock_lifetime := 3.0

var _mat: ShaderMaterial
var _surface: MeshInstance3D
var _ripples := PackedVector4Array()
var _slot := 0
var _live := 0
## Our own clock, handed to the shader every frame. See the comment on
## `time_now` in water.gdshader for why this is not TIME.
var _clock := 0.0


func _ready() -> void:
	_ripples.resize(MAX_RIPPLES)
	for i in MAX_RIPPLES:
		_ripples[i] = Vector4.ZERO
	_bind_surface()
	if Engine.is_editor_hint():
		return
	var vol := get_node_or_null("Volume") as Area3D
	if vol == null:
		push_warning("water: no Volume Area3D child, rocks will not be detected")
	else:
		vol.body_entered.connect(_on_body_entered)


func _process(delta: float) -> void:
	_clock += delta
	if _mat != null:
		_mat.set_shader_parameter("time_now", _clock)


# -----------------------------------------------------------------------------
# surface
# -----------------------------------------------------------------------------

func _bind_surface() -> void:
	var p := get_parent()
	if p == null:
		return
	var envnode := p.get_node_or_null("Env")
	if envnode == null:
		push_warning("water: no sibling Env node; surface not bound")
		return
	_surface = _find(envnode, SURFACE_NAME) as MeshInstance3D
	if _surface == null:
		push_warning("water: %s not found under Env" % SURFACE_NAME)
		return

	var sh: Shader = ResourceLoader.load(SHADER_PATH)
	if sh == null:
		push_error("water: could not load %s" % SHADER_PATH)
		return

	_mat = ShaderMaterial.new()
	_mat.shader = sh
	var na: Texture2D = ResourceLoader.load(NORMAL_A)
	var nb: Texture2D = ResourceLoader.load(NORMAL_B)
	if na == null or nb == null:
		push_warning("water: normal maps missing -- run tools/gen_water_assets.py")
	_mat.set_shader_parameter("normal_a", na)
	_mat.set_shader_parameter("normal_b", nb)
	_mat.set_shader_parameter("ripples", _ripples)
	_mat.set_shader_parameter("ripple_count", 0)
	_surface.layers = SURFACE_VISUAL_LAYERS
	_surface.material_override = _mat


func _find(n: Node, nm: String) -> Node:
	if String(n.name) == nm:
		return n
	for c in n.get_children():
		var r := _find(c, nm)
		if r != null:
			return r
	return null


# -----------------------------------------------------------------------------
# ripples
# -----------------------------------------------------------------------------

## Push an expanding ring at a world position. The array is a ring buffer: once
## all 16 slots are live the oldest is overwritten, which is what the brief
## asks for and also means a player spamming rocks degrades gracefully instead
## of dropping new ripples on the floor.
func add_ripple(world_pos: Vector3) -> void:
	if _mat == null:
		return
	_ripples[_slot] = Vector4(world_pos.x, world_pos.y, world_pos.z, _clock)
	_slot = (_slot + 1) % MAX_RIPPLES
	_live = mini(_live + 1, MAX_RIPPLES)
	_mat.set_shader_parameter("ripples", _ripples)
	_mat.set_shader_parameter("ripple_count", _live)


# -----------------------------------------------------------------------------
# impacts
# -----------------------------------------------------------------------------

func _on_body_entered(body: Node3D) -> void:
	if not body.is_in_group(rock_group):
		return

	var speed := 0.0
	if body is RigidBody3D:
		speed = (body as RigidBody3D).linear_velocity.length()

	# Put the impact ON the surface, not wherever the body happened to be when
	# the area fired. The Area3D triggers as soon as the collision shapes touch,
	# so a fast rock is already some way under by then.
	var hit := body.global_position
	hit.y = global_position.y

	if speed >= min_impact_speed:
		add_ripple(hit)
		_spawn_splash(hit, speed)

	if body is RigidBody3D:
		var rb := body as RigidBody3D
		rb.linear_damp = sink_linear_damp
		rb.angular_damp = sink_angular_damp
		rb.gravity_scale = sink_gravity_scale
		# Free it rather than leaving physics bodies accumulating on the pool
		# bed for the rest of the session.
		# Capture the instance ID, not the node. The player's live-rock cap can
		# free this rock before the timer fires, and a lambda holding the freed
		# object itself errors with "Lambda capture at index 0 was freed".
		var rid := rb.get_instance_id()
		var t := get_tree().create_timer(rock_lifetime)
		t.timeout.connect(func():
			var o := instance_from_id(rid)
			if o != null and is_instance_valid(o):
				(o as Node).queue_free())


func _spawn_splash(at: Vector3, speed: float) -> void:
	var ps: PackedScene = ResourceLoader.load(SPLASH_SCENE)
	if ps == null:
		push_warning("water: %s missing, no splash" % SPLASH_SCENE)
		return
	var s := ps.instantiate()
	var holder := get_node_or_null("Splashes")
	if holder == null:
		holder = self
	holder.add_child(s)
	if s is Node3D:
		(s as Node3D).global_position = at
	if s.has_method("configure"):
		s.call("configure", speed)
