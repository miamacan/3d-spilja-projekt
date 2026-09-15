extends RigidBody3D
# Bačeni kamen (G4).
# Sam se brine o udarcu (zvuk klika + prašina) i o svom vremenu trajanja.
# Igrač ga samo baci - sve poslije toga (udarac, prašina, brisanje) je ovdje,
# svejedno je li kamen bačen, pušten u testu, ili gurnut drugim kamenom.
#
# Voda se NE rješava ovdje - water.gd (preko svog Area3D) preuzme kamen
# čim uđe u vodu (usporavanje, tonjenje, brisanje).

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
# ispod ove brzine udarac se ignorira (inače kamen "klika" svaki frame dok se smiruje)
@export var min_click_speed := 1.6
# najmanji razmak (u sekundama) između dva klika istog kamena
@export var click_cooldown := 0.09
@export var min_dust_speed := 3.5
@export var max_dust_puffs := 3
# ispod vode se ne klika - to rješava water.gd
@export var water_level := 0.0

var _age := 0.0
var _since_click := 99.0
var _puffs := 0
# brzina iz zadnjeg fizikalnog koraka - u trenutku samog sudara (body_entered)
# brzina je već "ugušena" na skoro nulu, pa se čita malo prije toga
var _prev_speed := 0.0

@onready var _audio: AudioStreamPlayer3D = get_node_or_null("Audio")
@onready var _mesh: MeshInstance3D = get_node_or_null("Mesh")


func _ready() -> void:
	if not is_in_group("rock"):
		add_to_group("rock")
	_pick_variant()
	body_entered.connect(_on_body_entered)


# nasumično odabere jedan od tri oblika kamena, da ne izgledaju svi isto
func _pick_variant() -> void:
	if _mesh == null:
		return
	var idx := randi() % MESHES.size()
	var m: Mesh = ResourceLoader.load(MESHES[idx])
	if m != null:
		_mesh.mesh = m
	# malo nasumične veličine, na vrh već postojeće 3 varijante oblika
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
	# jači udarac = glasniji i malo "svjetliji" zvuk; raspon visine tona
	# sprječava da se više udaraca zaredom čuje kao isti, repetitivni zvuk
	var f := clampf(speed / 12.0, 0.0, 1.0)
	_audio.volume_db = linear_to_db(clampf(0.25 + f * 0.75, 0.05, 1.0))
	_audio.pitch_scale = randf_range(0.88, 1.14) * (0.95 + f * 0.2)
	_audio.play()


func _dust(speed: float) -> void:
	var ps: PackedScene = ResourceLoader.load(DUST_SCENE)
	if ps == null:
		return
	var d := ps.instantiate()
	# prašina se veže na roditelja kamena, ne na sam kamen - da ostane na
	# mjestu udarca dok se kamen dalje kotrlja/odskakuje
	var host := get_parent()
	if host == null:
		return
	host.add_child(d)
	if d is Node3D:
		(d as Node3D).global_position = global_position
	if d.has_method("configure"):
		d.call("configure", clampf(speed / 10.0, 0.3, 1.5))
