extends RigidBody3D
##
## G4 — a thrown stone.
##
## Owns its own impact response (stone click + dust puff) and its own lifetime.
## The player only throws it; everything after release is here, so the same
## scene behaves identically however it gets into the world -- thrown, dropped
## by a test harness, or knocked loose by another rock.
##
## Water is NOT handled here: scenes/water/water.gd detects entry through its
## Area3D and takes over damping, sinking and freeing.
##

const DUST_SCENE := "res://scenes/fx/Dust.tscn"
const CLICKS: Array[String] = [
	"res://audio/stone_click_1.wav",
	"res://audio/stone_click_2.wav",
	"res://audio/stone_click_3.wav",
]
const MESHES: Array[String] = [
	"res://scenes/rock/rock_mesh_1.res",
	"res://scenes/rock/rock_mesh_2.res",
	"res://scenes/rock/rock_mesh_3.res",
]

@export var lifetime := 20.0
## Below this the impact is a nudge, not a knock. Without it a rock settling on
## a slope clicks every physics frame as it micro-bounces.
@export var min_click_speed := 1.6
## Minimum seconds between this rock's own clicks. A bounce can report several
## contacts in consecutive frames.
@export var click_cooldown := 0.09
@export var min_dust_speed := 3.5
@export var max_dust_puffs := 3
## No clicking off the pool bed once submerged -- water.gd owns that.
@export var water_level := 0.0

var _age := 0.0
var _since_click := 99.0
var _puffs := 0
## Speed as of the last physics step. body_entered fires after the solver has
## already killed the velocity, so reading linear_velocity inside it reports a
## near-stationary rock and every impact comes out silent.
var _prev_speed := 0.0

@onready var _audio: AudioStreamPlayer3D = get_node_or_null("Audio")
@onready var _mesh: MeshInstance3D = get_node_or_null("Mesh")


func _ready() -> void:
	if not is_in_group("rock"):
		add_to_group("rock")
	_pick_variant()
	body_entered.connect(_on_body_entered)


## One scene, three shapes. Rocks that are all identical read as manufactured.
func _pick_variant() -> void:
	if _mesh == null:
		return
	var idx := randi() % MESHES.size()
	var m: Mesh = ResourceLoader.load(MESHES[idx])
	if m != null:
		_mesh.mesh = m
	# a little extra scale variety on top of the three shapes
	var s := randf_range(0.85, 1.2)
	_mesh.scale = Vector3(s, s, s)
	rotation = Vector3(randf() * TAU, randf() * TAU, randf() * TAU)


func _integrate_forces(state: PhysicsDirectBodyState3D) -> void:
	_prev_speed = state.linear_velocity.length()


func _physics_process(delta: float) -> void:
	_age += delta
	_since_click += delta
	if _age >= lifetime:
		queue_free()


func _on_body_entered(_body: Node) -> void:
	if _since_click < click_cooldown:
		return
	if global_position.y < water_level:
		return
	var v := _prev_speed
	if v < min_click_speed:
		return
	_since_click = 0.0
	_click(v)
	if v >= min_dust_speed and _puffs < max_dust_puffs:
		_puffs += 1
		_dust(v)


func _click(speed: float) -> void:
	if _audio == null:
		return
	var st: AudioStream = ResourceLoader.load(CLICKS[randi() % CLICKS.size()])
	if st == null:
		return
	_audio.stream = st
	# Harder hits are louder and a touch brighter. The pitch spread also stops
	# a run of bounces sounding like one sample retriggered.
	var f := clampf(speed / 12.0, 0.0, 1.0)
	_audio.volume_db = linear_to_db(clampf(0.25 + f * 0.75, 0.05, 1.0))
	_audio.pitch_scale = randf_range(0.88, 1.14) * (0.95 + f * 0.2)
	_audio.play()


func _dust(speed: float) -> void:
	var ps: PackedScene = ResourceLoader.load(DUST_SCENE)
	if ps == null:
		return
	var d := ps.instantiate()
	# Parent to the rock's PARENT, not the rock: the puff should stay where the
	# impact happened while the rock bounces away from it.
	var host := get_parent()
	if host == null:
		return
	host.add_child(d)
	if d is Node3D:
		(d as Node3D).global_position = global_position
	if d.has_method("configure"):
		d.call("configure", clampf(speed / 10.0, 0.3, 1.5))
