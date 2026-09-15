@tool
extends Node3D
# Jezero (G3): materijal površine, širenje valova (ripple), i što se
# dogodi kad kamen udari u vodu.
#
# @tool je ovdje da bi i editor (ne samo pokrenuta igra) vidio vodu - to
# treba da lightmap bake ispravno "vidi" površinu vode. Sve što je vezano
# za samu igru je zaštićeno provjerom Engine.is_editor_hint().

const MAX_RIPPLES := 16
const SHADER_PATH := "res://shaders/water.gdshader"
const NORMAL_A := "res://assets/textures/T_WaterNormal_A.png"
const NORMAL_B := "res://assets/textures/T_WaterNormal_B.png"
const SPLASH_SCENE := "res://scenes/fx/Splash.tscn"
const SURFACE_NAME := "WATER_Pool_Surface"
# vizualni slojevi površine vode: bit 1 = normalno renderiranje, bit 2 = da
# ReflectionProbe hvata samo vodu, ništa drugo u prostoriji
const SURFACE_VISUAL_LAYERS := 1 | 2

@export var rock_group: StringName = &"rock"
# ispod ove brzine udarca nema pljuska ni zvuka
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
# vlastiti "sat" koji se svaki frame šalje shaderu vode
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


# ---------------------------------------------------------------- POVRŠINA -----

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


# ------------------------------------------------------------------ VALOVI -----

# dodaje jedan šireći krug (val) na svjetskoj poziciji. Niz radi kao "ring
# buffer" - kad su svih 16 mjesta puna, najstariji val se prepiše novim.
func add_ripple(world_pos: Vector3) -> void:
	if _mat == null:
		return
	_ripples[_slot] = Vector4(world_pos.x, world_pos.y, world_pos.z, _clock)
	_slot = (_slot + 1) % MAX_RIPPLES
	_live = mini(_live + 1, MAX_RIPPLES)
	_mat.set_shader_parameter("ripples", _ripples)
	_mat.set_shader_parameter("ripple_count", _live)


# ----------------------------------------------------------------- UDARCI -----

func _on_body_entered(body: Node3D) -> void:
	if not body.is_in_group(rock_group):
		return

	var speed := 0.0
	if body is RigidBody3D:
		speed = (body as RigidBody3D).linear_velocity.length()

	# udarac se postavlja NA površinu vode, ne gdje god je tijelo trenutno -
	# brz kamen je već malo ispod površine kad se Area3D okine
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
		# obriši kamen nakon nekog vremena, da se ne gomilaju na dnu jezera.
		# Čuva se ID instance, ne sam čvor - jer igrač može ranije obrisati
		# taj isti kamen (limit broja kamenja), pa bi lambda inače pucala.
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
