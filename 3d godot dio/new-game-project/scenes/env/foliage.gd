@tool
extends Node3D
# G5 - stavlja shader mahovine na kamen i pravi materijal lišća na vegetaciju.
#
# Postavlja se skriptom (isti razlog kao water.gd) - jer bi override
# materijala inače "otpao" pri spremanju scene, pa se svaki put ponovno
# postavlja kad se scena pokrene/otvori.
#
# @tool je ovdje da i editor vidi ovo, jer to treba lightmap baku da
# "vidi" mahovinu, ne golu stijenu.

const MOSS_SHADER := "res://shaders/rock_moss.gdshader"
const MOSS_BC := "res://assets/textures/T_Moss_BC.png"
const MOSS_N := "res://assets/textures/T_Moss_N.png"
const MOSS_ORM := "res://assets/textures/T_Moss_ORM.png"
const LEAF_ATLAS := "res://assets/textures/T_LeafAtlas.png"

# materijali iz .glb datoteke na koje treba "narasti" mahovina
const ROCK_MATERIALS: Array[String] = [
	"M_Limestone_Shell", "M_Limestone_Outcrop", "M_Limestone_Boulder",
	"M_Limestone_Ground", "M_Limestone_Tunnel",
]
const LEAF_MATERIALS: Array[String] = ["M_VineLeaf"]

@export_group("Moss")
@export var moss_enabled := true
@export var moss_tile := 0.5:
	set(v):
		moss_tile = v
		_push()
@export_range(0.0, 4.0) var mask_gain := 1.0:
	set(v):
		mask_gain = v
		_push()
@export_range(0.0, 1.0) var mask_threshold := 0.22:
	set(v):
		mask_threshold = v
		_push()
@export_range(0.001, 0.5) var edge_softness := 0.08:
	set(v):
		edge_softness = v
		_push()
@export var edge_noise_scale := 1.8:
	set(v):
		edge_noise_scale = v
		_push()
@export_range(0.0, 1.0) var edge_noise_amount := 0.30:
	set(v):
		edge_noise_amount = v
		_push()
@export_range(0.0, 1.0) var moss_roughness := 0.9:
	set(v):
		moss_roughness = v
		_push()
@export var moss_tint := Color(1, 1, 1):
	set(v):
		moss_tint = v
		_push()
# jednobojna magenta = mahovina, crno = golo - za provjeru maske bez
# potrebe da se gleda osvijetljeni render
@export var debug_mask := false:
	set(v):
		debug_mask = v
		_push()

@export_group("Leaves")
@export var leaves_enabled := true
@export_range(0.0, 1.0) var alpha_scissor := 0.5
@export var leaf_backlight := Color(0.26, 0.32, 0.18)

var _moss_mats: Dictionary = {}     # naziv izvornog materijala -> ShaderMaterial
var _leaf_mat: StandardMaterial3D
var _applied := {"rock": 0, "leaf": 0, "skipped": 0}


func _ready() -> void:
	apply()


func get_report() -> Dictionary:
	return _applied.duplicate()


func apply() -> void:
	_moss_mats.clear()
	_leaf_mat = null
	_applied = {"rock": 0, "leaf": 0, "skipped": 0}
	var envnode := get_parent().get_node_or_null("Env") if get_parent() else null
	if envnode == null:
		push_warning("foliage: no sibling Env node")
		return
	_walk(envnode)


func _walk(n: Node) -> void:
	if n is MeshInstance3D:
		_do_mesh(n as MeshInstance3D)
	for c in n.get_children():
		_walk(c)


# čita IZVORNI materijal, ne trenutno postavljeni - jer bi drugi put
# ovaj kod inače čitao svoj vlastiti rezultat, umjesto originalnih tekstura
func _source_material(mi: MeshInstance3D) -> StandardMaterial3D:
	if mi.mesh != null and mi.mesh.get_surface_count() > 0:
		var m := mi.mesh.surface_get_material(0)
		if m is StandardMaterial3D:
			return m as StandardMaterial3D
	var o := mi.get_surface_override_material(0)
	if o is StandardMaterial3D:
		return o as StandardMaterial3D
	return null


func _do_mesh(mi: MeshInstance3D) -> void:
	var src := _source_material(mi)
	if src == null:
		return
	var nm := String(src.resource_name)
	if moss_enabled and nm in ROCK_MATERIALS:
		var mat := _moss_material(nm, src)
		if mat != null:
			mi.material_override = mat
			_applied["rock"] += 1
		return
	if leaves_enabled and nm in LEAF_MATERIALS:
		mi.material_override = _leaf_material()
		_applied["leaf"] += 1
		return
	_applied["skipped"] += 1


func _moss_material(key: String, src: StandardMaterial3D) -> ShaderMaterial:
	if _moss_mats.has(key):
		return _moss_mats[key]
	var sh: Shader = ResourceLoader.load(MOSS_SHADER)
	if sh == null:
		push_error("foliage: %s missing" % MOSS_SHADER)
		return null
	var m := ShaderMaterial.new()
	m.shader = sh
	# stijena koristi teksture koje je glTF uvoz već spojio, po materijalu -
	# tako svaki mesh čuva svoju vlastitu zapečenu T_Macro_* mapu
	m.set_shader_parameter("rock_albedo", src.albedo_texture)
	m.set_shader_parameter("rock_normal", src.normal_texture)
	m.set_shader_parameter("rock_orm", src.roughness_texture)
	m.set_shader_parameter("moss_albedo", ResourceLoader.load(MOSS_BC))
	m.set_shader_parameter("moss_normal", ResourceLoader.load(MOSS_N))
	m.set_shader_parameter("moss_orm", ResourceLoader.load(MOSS_ORM))
	_moss_mats[key] = m
	_push_one(m)
	return m


func _leaf_material() -> StandardMaterial3D:
	if _leaf_mat != null:
		return _leaf_mat
	var m := StandardMaterial3D.new()
	var tex: Texture2D = ResourceLoader.load(LEAF_ATLAS)
	if tex == null:
		push_warning("foliage: %s missing, leaves stay flat" % LEAF_ATLAS)
	m.albedo_texture = tex
	m.albedo_color = Color(1, 1, 1)
	# alfa izrezivanje (scissor), ne postupno miješanje - kartice lišća se
	# jako preklapaju, pa bi miješanje svaki frame krivo sortiralo dubinu
	m.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA_SCISSOR
	m.alpha_scissor_threshold = alpha_scissor
	m.cull_mode = BaseMaterial3D.CULL_DISABLED
	m.backlight_enabled = true
	m.backlight = leaf_backlight
	m.roughness = 0.85
	m.metallic = 0.0
	_leaf_mat = m
	return m


func _push() -> void:
	for k in _moss_mats:
		_push_one(_moss_mats[k])


func _push_one(m: ShaderMaterial) -> void:
	if m == null:
		return
	m.set_shader_parameter("moss_tile", moss_tile)
	m.set_shader_parameter("mask_gain", mask_gain)
	m.set_shader_parameter("mask_threshold", mask_threshold)
	m.set_shader_parameter("edge_softness", edge_softness)
	m.set_shader_parameter("edge_noise_scale", edge_noise_scale)
	m.set_shader_parameter("edge_noise_amount", edge_noise_amount)
	m.set_shader_parameter("moss_roughness", moss_roughness)
	m.set_shader_parameter("moss_tint", moss_tint)
	m.set_shader_parameter("debug_mask", 1.0 if debug_mask else 0.0)
