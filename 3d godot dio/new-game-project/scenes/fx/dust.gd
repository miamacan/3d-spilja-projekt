extends Node3D
##
## G4 — a tiny dust puff where a stone struck stone. One-shot, frees itself.
##

@export var extra_life := 0.25

var _t := 0.0
var _life := 1.0

@onready var _p: GPUParticles3D = get_node_or_null("Particles")


func configure(scale_factor: float) -> void:
	set_meta("puff_scale", clampf(scale_factor, 0.2, 2.0))


func _ready() -> void:
	var s := 1.0
	if has_meta("puff_scale"):
		s = float(get_meta("puff_scale"))
	if _p != null:
		_p.amount = maxi(4, int(round(10.0 * s)))
		var pm := _p.process_material as ParticleProcessMaterial
		if pm != null:
			pm = pm.duplicate() as ParticleProcessMaterial
			pm.initial_velocity_min *= s
			pm.initial_velocity_max *= s
			_p.process_material = pm
		_p.emitting = true
		_life = _p.lifetime + extra_life
	else:
		_life = extra_life


func _process(delta: float) -> void:
	_t += delta
	if _t >= _life:
		queue_free()
