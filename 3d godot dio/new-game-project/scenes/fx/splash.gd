extends Node3D
# G3 - pljusak pri udarcu: kapljice, širći krug (val), i zvuk "plop".
#
# Stvara ga water.gd na mjestu udarca, već na razini vode. Sam se obriše
# kad završi najduži od svoja tri dijela (val, kapljice, zvuk).

@export var duration := 0.6            # trajanje kruga (vala)
@export var max_radius := 1.5          # metri, pri referentnoj brzini udarca
@export var reference_speed := 8.0     # brzina udarca za koju su zadane vrijednosti namještene

var _t := 0.0
var _life := 1.2
var _ring_mat: ShaderMaterial

@onready var _ring: MeshInstance3D = get_node_or_null("Ring")
@onready var _drops: GPUParticles3D = get_node_or_null("Droplets")
@onready var _audio: AudioStreamPlayer3D = get_node_or_null("Audio")


# poziva ga water.gd odmah nakon add_child - postavlja jačinu efekta
# ovisno o brzini udarca, prije nego _ready pročita tu vrijednost
func configure(impact_speed: float) -> void:
	var s := clampf(impact_speed / maxf(reference_speed, 0.001), 0.35, 1.8)
	set_meta("speed_scale", s)


func _ready() -> void:
	var s := 1.0
	if has_meta("speed_scale"):
		s = float(get_meta("speed_scale"))

	max_radius *= s

	if _ring != null:
		var qm := _ring.mesh as QuadMesh
		if qm != null:
			# quad se pravi u KONAČNOJ veličini; shader iznutra crta val
			# koji putuje prema van (vidi splash_ring.gdshader)
			qm = qm.duplicate() as QuadMesh
			qm.size = Vector2(max_radius * 2.0, max_radius * 2.0)
			_ring.mesh = qm
		_ring_mat = _ring.material_override as ShaderMaterial
		if _ring_mat == null and _ring.mesh != null:
			_ring_mat = _ring.mesh.surface_get_material(0) as ShaderMaterial
		if _ring_mat != null:
			_ring_mat = _ring_mat.duplicate() as ShaderMaterial   # zaseban napredak po instanci
			_ring.material_override = _ring_mat
			_ring_mat.set_shader_parameter("progress", 0.0)

	if _drops != null:
		_drops.amount = maxi(6, int(round(24.0 * s)))
		var pm := _drops.process_material as ParticleProcessMaterial
		if pm != null:
			pm = pm.duplicate() as ParticleProcessMaterial
			pm.initial_velocity_min *= s
			pm.initial_velocity_max *= s
			_drops.process_material = pm
		_drops.emitting = true
		_life = maxf(_life, _drops.lifetime + 0.3)

	if _audio != null and _audio.stream != null:
		# visina tona ovisi o brzini udarca, ali OBRNUTO od očekivanog:
		# jači udarac = veća "šupljina" u vodi = niži ton (ne viši, kako
		# bi se prvo pomislilo - viši ton bi zvučao k'o crtani film)
		_audio.pitch_scale = clampf(1.25 - (s - 1.0) * 0.35, 0.7, 1.45)
		_audio.play()
		_life = maxf(_life, _audio.stream.get_length() / _audio.pitch_scale + 0.2)

	_life = maxf(_life, duration + 0.2)


func _process(delta: float) -> void:
	_t += delta
	if _ring_mat != null:
		_ring_mat.set_shader_parameter("progress", clampf(_t / duration, 0.0, 1.0))
	if _t >= _life:
		queue_free()
