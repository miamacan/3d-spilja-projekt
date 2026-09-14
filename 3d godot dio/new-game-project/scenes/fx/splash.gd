extends Node3D
##
## G3 — one-shot impact splash: droplets, an expanding ring, and a plop.
##
## Spawned by water.gd at the impact point, already on the water plane. Frees
## itself once the longest of its three parts has finished.
##

@export var duration := 0.6            ## ring life, brief asks for 0.6 s
@export var max_radius := 1.5          ## metres, at the reference impact speed
@export var reference_speed := 8.0     ## impact speed the defaults are tuned for

var _t := 0.0
var _life := 1.2
var _ring_mat: ShaderMaterial

@onready var _ring: MeshInstance3D = get_node_or_null("Ring")
@onready var _drops: GPUParticles3D = get_node_or_null("Droplets")
@onready var _audio: AudioStreamPlayer3D = get_node_or_null("Audio")


## Called by water.gd immediately after add_child, so this runs BEFORE _ready
## is guaranteed to have run on some paths -- everything it sets is read in
## _ready rather than applied directly.
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
			# Build the quad at the FINAL diameter; the shader draws the ring
			# travelling outward inside it. See splash_ring.gdshader.
			qm = qm.duplicate() as QuadMesh
			qm.size = Vector2(max_radius * 2.0, max_radius * 2.0)
			_ring.mesh = qm
		_ring_mat = _ring.material_override as ShaderMaterial
		if _ring_mat == null and _ring.mesh != null:
			_ring_mat = _ring.mesh.surface_get_material(0) as ShaderMaterial
		if _ring_mat != null:
			_ring_mat = _ring_mat.duplicate() as ShaderMaterial   # per-instance progress
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
		# Pitch scaled by impact speed, per the brief. Inverted deliberately: a
		# harder impact makes a BIGGER cavity, which resonates LOWER. Scaling
		# pitch up with speed is the intuitive choice and sounds like a cartoon.
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
