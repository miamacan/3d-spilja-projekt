extends Node3D
# G5 - kapanje vode s krajeva loza.
#
# Na svaki MARK_Drip_* marker stavlja tanki efekt kapi koja pada, i s
# nasumičnim tajmerom (po markeru) pušta val u jezero točno ispod te kapi.
#
# Markeri su u Blenderu postavljeni na stvarne krajeve loza, i svih 14
# vrhova provjereno je da se nalazi iznad vode, pa val uvijek završi
# u jezeru, ne na kamenu.

const DRIP_SCENE := "res://scenes/fx/Drip.tscn"

@export var enabled := true
@export var marker_prefix := "MARK_Drip_"
@export var water_level := 0.0
@export var interval_min := 1.4
@export var interval_max := 4.2
# valovi idu u isti "ring buffer" od 16 mjesta kao i valovi od kamenja -
# ako je ovo previsoko, kapanje bi samo istisnulo valove od bačenog kamena
@export var max_ripples_per_second := 1.5

var _markers: Array[Node3D] = []
var _timers: Array[float] = []
var _water: Node
var _since_ripple := 0.0


func _ready() -> void:
	if not enabled:
		return
	var p := get_parent()
	while p != null and p.get_node_or_null("Env") == null:
		p = p.get_parent()
	if p == null:
		push_warning("drips: could not find a node with an Env child")
		return
	_water = p.get_node_or_null("Water")
	_collect(p.get_node("Env"))

	var ps: PackedScene = ResourceLoader.load(DRIP_SCENE)
	for m in _markers:
		_timers.append(randf_range(interval_min, interval_max))
		if ps != null:
			var d := ps.instantiate()
			add_child(d)
			if d is Node3D:
				(d as Node3D).global_position = m.global_position
	print("drips: %d markers, %s" % [_markers.size(),
		"emitters placed" if ps != null else "no Drip.tscn, ripples only"])


func _collect(n: Node) -> void:
	if n is Node3D and String(n.name).begins_with(marker_prefix):
		_markers.append(n as Node3D)
	for c in n.get_children():
		_collect(c)


func _process(delta: float) -> void:
	if _markers.is_empty():
		return
	_since_ripple += delta
	for i in _markers.size():
		_timers[i] -= delta
		if _timers[i] > 0.0:
			continue
		_timers[i] = randf_range(interval_min, interval_max)
		if _since_ripple < 1.0 / maxf(max_ripples_per_second, 0.01):
			continue
		_since_ripple = 0.0
		_ripple_under(_markers[i])


func _ripple_under(m: Node3D) -> void:
	if _water == null or not _water.has_method("add_ripple"):
		return
	var p := m.global_position
	_water.call("add_ripple", Vector3(p.x, water_level, p.z))


func marker_count() -> int:
	return _markers.size()
