extends SceneTree
##
## G5 acceptance test.
##
##   Godot --path <project> --rendering-driver d3d12 --resolution 1600x900 \
##         --script res://scenes/debug/g5_probe.gd -- --out-dir C:/some/dir
##
## The done-when is three claims; this checks each one so it cannot be taken on
## faith from a pretty screenshot:
##
##   "moss sits where Blender's mask says"  -- counts how many rock materials
##       got the shader, confirms each carries its OWN baked ORM (not a shared
##       one), and renders the mask flat via debug_mask so coverage can be
##       measured off the image rather than inferred from a lit render.
##   "vines aren't hard-edged"              -- confirms the leaf material is
##       alpha-scissor, cull-disabled, backlit, and carries the atlas.
##   "the god rays have motes"              -- confirms the emitter, its count,
##       and screenshots the hero view.
##

var _out_dir := "user://"
var _t := 0.0
var _phase := 0
var _phase_t := 0.0
var _busy := false
var _done := false
var _main: Node
var _foliage: Node
var _log := {}
var _frames: Array = []
var _cam: Camera3D


func _initialize() -> void:
	var a := OS.get_cmdline_user_args()
	for i in range(a.size() - 1):
		if String(a[i]) == "--out-dir":
			_out_dir = String(a[i + 1])

	var packed: PackedScene = load("res://scenes/main.tscn")
	_main = packed.instantiate()
	root.add_child(_main)
	current_scene = _main
	for n in ["Player", "RouteAudit"]:
		var d := _main.get_node_or_null(n)
		if d:
			d.free()
	DisplayServer.window_set_vsync_mode(DisplayServer.VSYNC_DISABLED)

	_cam = _main.get_node_or_null("HeroCam") as Camera3D
	if _cam != null:
		if _cam.get_script() != null:
			_cam.set_script(null)
		_cam.current = true
	_foliage = _main.get_node_or_null("Foliage")
	print("g5_probe: started")


func _process(delta: float) -> bool:
	if _done:
		return true
	_t += delta
	_phase_t += delta
	if _phase_t > 1.0:
		_frames.append(delta * 1000.0)
	if _busy:
		return false
	match _phase:
		0: _p0_inspect()
		1: _p1_hero()
		2: _p2_mask()
		3: _p3_closeup()
		4:
			_report()
			return true
	if _t > 60.0:
		_log["timeout"] = true
		_report()
		return true
	return false


func _next() -> void:
	_phase += 1
	_phase_t = 0.0


# --- 0: what actually got applied ---------------------------------------------

func _p0_inspect() -> void:
	if _phase_t < 2.5:
		return

	if _foliage != null and _foliage.has_method("get_report"):
		_log["foliage_applied"] = _foliage.call("get_report")

	# every rock mesh: did it get a ShaderMaterial, and does it carry its OWN
	# baked macro map? A shared ORM would mean the per-mesh bakes were lost.
	var rocks := {}
	var leaves := 0
	var leaf_ok := {}
	_scan(_main, rocks, leaf_ok)
	_log["rock_materials"] = rocks
	_log["leaf_material"] = leaf_ok

	var fx := _main.get_node_or_null("FX")
	var motes := fx.get_node_or_null("Motes") if fx else null
	if motes is GPUParticles3D:
		var m := motes as GPUParticles3D
		_log["motes"] = {"amount": m.amount, "lifetime": m.lifetime,
			"preprocess": m.preprocess, "emitting": m.emitting,
			"pos": str(m.global_position).replace(" ", "")}
		var pm := m.process_material as ParticleProcessMaterial
		if pm != null:
			_log["motes"]["box_extents"] = str(pm.emission_box_extents).replace(" ", "")
	var drips := fx.get_node_or_null("Drips") if fx else null
	if drips != null and drips.has_method("marker_count"):
		_log["drip_markers"] = drips.call("marker_count")
	_next()


func _scan(n: Node, rocks: Dictionary, leaf_ok: Dictionary) -> void:
	if n is MeshInstance3D:
		var mi := n as MeshInstance3D
		var ov := mi.material_override
		var nm := String(mi.name)
		if ov is ShaderMaterial:
			var sm := ov as ShaderMaterial
			var orm = sm.get_shader_parameter("rock_orm")
			var moss = sm.get_shader_parameter("moss_albedo")
			rocks[nm] = {
				"orm": orm.resource_path.get_file() if orm else "<none>",
				"moss": moss != null,
				"threshold": sm.get_shader_parameter("mask_threshold"),
			}
		elif ov is StandardMaterial3D and (nm.begins_with("VINE_") or nm.begins_with("FERN_")
				or nm.ends_with("_Canopy")):
			var lm := ov as StandardMaterial3D
			if leaf_ok.is_empty():
				leaf_ok["transparency"] = lm.transparency
				leaf_ok["is_alpha_scissor"] = lm.transparency == BaseMaterial3D.TRANSPARENCY_ALPHA_SCISSOR
				leaf_ok["scissor_threshold"] = lm.alpha_scissor_threshold
				leaf_ok["cull_disabled"] = lm.cull_mode == BaseMaterial3D.CULL_DISABLED
				leaf_ok["backlight_on"] = lm.backlight_enabled
				leaf_ok["backlight"] = str(lm.backlight).replace(" ", "")
				leaf_ok["atlas"] = lm.albedo_texture.resource_path.get_file() if lm.albedo_texture else "<none>"
			leaf_ok["count"] = int(leaf_ok.get("count", 0)) + 1
	for c in n.get_children():
		_scan(c, rocks, leaf_ok)


# --- 1-3: shots ----------------------------------------------------------------

func _p1_hero() -> void:
	if _phase_t < 2.5:
		return
	_shoot("a_hero")
	_next()


func _p2_mask() -> void:
	if _phase_t < 0.1:
		return
	if _foliage != null:
		_foliage.set("debug_mask", true)
	if _phase_t < 0.6:
		return
	_shoot("b_mask")
	if _foliage != null:
		_foliage.set("debug_mask", false)
	_next()


func _p3_closeup() -> void:
	if _cam == null:
		_next(); return
	if _phase_t < 0.1:
		# Looking down at the outcrop crest, which carries the strongest mask in
		# the scene, from open air above and in front of it.
		_cam.look_at_from_position(Vector3(-2.4, 8.6, 10.2), Vector3(-2.2, 5.4, 4.6), Vector3.UP)
		_cam.fov = 50.0
		return
	if _phase_t < 1.2:
		return
	_shoot("c_outcrop")
	_next()


func _shoot(nm: String) -> void:
	_busy = true
	_capture(nm)


func _capture(nm: String) -> void:
	await RenderingServer.frame_post_draw
	var img: Image = root.get_texture().get_image()
	DirAccess.make_dir_recursive_absolute(_out_dir)
	var e := img.save_png(_out_dir.path_join("_g5_probe_%s.png" % nm))
	print("g5_probe: shot %s (%s)" % [nm, "OK" if e == OK else "ERR %d" % e])
	_busy = false


func _report() -> void:
	_done = true
	if _frames.size() > 10:
		var s := _frames.duplicate()
		s.sort()
		var tot := 0.0
		for f in s:
			tot += f
		_log["frame_mean_ms"] = snappedf(tot / float(s.size()), 0.01)
		_log["frame_p95_ms"] = snappedf(s[int(floor(float(s.size() - 1) * 0.95))], 0.01)
	print("G5_PROBE_JSON:" + JSON.stringify(_log))
	quit()
