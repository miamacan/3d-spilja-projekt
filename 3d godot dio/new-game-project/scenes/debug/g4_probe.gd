extends SceneTree
# G4 test: provjerava da bacanje kamena radi kako treba - nabijanje,
# brzina, odskakivanje, i da sve i dalje radi kad se baci puno kamenja odjednom.

var _out_dir := "user://"
var _t := 0.0
var _main: Node
var _player: Node
var _water: Node
var _log := {}
var _phase := 0
var _phase_t := 0.0
var _busy := false
var _done := false

var _tracked: RigidBody3D
var _samples: Array = []
var _contact_pre := -1.0
var _contact_post := -1.0
var _apex := -999.0
var _spam: Array = []
var _spam_frames: Array = []
var _shot_taken := {}
var _last_delta := 0.016
var _splash_peak := 0
var _water_rock_spawned := false
var _charged_for_shot := false
var _bouncer: RigidBody3D
var _b_prev_vy := 0.0
var _b_pre := -1.0
var _b_post := -1.0


func _initialize() -> void:
	var a := OS.get_cmdline_user_args()
	for i in range(a.size() - 1):
		if String(a[i]) == "--out-dir":
			_out_dir = String(a[i + 1])

	var packed: PackedScene = load("res://scenes/main.tscn")
	_main = packed.instantiate()
	root.add_child(_main)
	current_scene = _main
	var ra := _main.get_node_or_null("RouteAudit")
	if ra:
		ra.free()
	DisplayServer.window_set_vsync_mode(DisplayServer.VSYNC_DISABLED)

	_player = _main.get_node_or_null("Player/Player")
	_water = _main.get_node_or_null("Water")
	_log["player_found"] = _player != null
	_log["water_found"] = _water != null
	_log["gravity"] = ProjectSettings.get_setting("physics/3d/default_gravity", 9.8)
	print("g4_probe: started")


func _process(delta: float) -> bool:
	if _done:
		return true
	_t += delta
	_phase_t += delta
	_last_delta = delta
	if _busy:
		return false

	match _phase:
		0: _p0_settle()
		1: _p1_charge_map()
		2: _p2_throw()
		3: _p3_track()
		4: _p4_bounce()
		5: _p4_spam()
		6: _p5_water()
		7:
			_report()
			return true
	if _t > 45.0:
		_log["timeout"] = true
		_report()
		return true
	return false


func _next() -> void:
	_phase += 1
	_phase_t = 0.0


func _p0_settle() -> void:
	if _phase_t < 2.0:
		return
	if _player != null:
		_player.set("auto_control", true)
		_player.call("teleport_to", Vector3(-2.2, 5.9, 5.0))
		var p: Node3D = _player
		p.rotation.y = atan2(-(3.0 - -2.2), -(-1.0 - 5.0))
		_log["player_pos"] = str((_player as Node3D).global_position)
	_next()


func _p1_charge_map() -> void:
	if _player == null:
		_next(); return
	var rows := {}
	for hold in [0.0, 0.15, 0.3, 0.5, 0.75, 1.0, 1.2, 2.0]:
		_player.set("_charge", hold)
		rows[str(hold)] = snappedf(float(_player.call("_charge_speed")), 0.01)
	_player.set("_charge", 0.0)
	_log["charge_map"] = rows
	_log["charge_ok"] = (absf(float(rows.get("0.3", -1)) - 6.0) < 0.01
		and absf(float(rows.get("1.2", -1)) - 16.0) < 0.01
		and absf(float(rows.get("0.0", -1)) - 6.0) < 0.01
		and absf(float(rows.get("2.0", -1)) - 16.0) < 0.01)
	_next()


func _p2_throw() -> void:
	if _player == null:
		_next(); return
	if not _charged_for_shot:
		_charged_for_shot = true
		_player.call("_begin_charge")
		_player.set("_charge", 1.2)
		return
	if _phase_t < 0.5:
		return
	if not _shot_taken.has("c_charge"):
		_shoot("c_charge")
		return
	_player.set("_charge", 1.2)
	_player.call("_release_charge")
	for c in _main.get_children():
		if c is RigidBody3D and c.is_in_group("rock"):
			_tracked = c
	_log["throw_spawned"] = _tracked != null
	if _tracked != null:
		_log["rock_mass"] = _tracked.mass
		_log["rock_layer"] = _tracked.collision_layer
		_log["rock_mask"] = _tracked.collision_mask
		_log["contact_monitor"] = _tracked.contact_monitor
		_log["max_contacts"] = _tracked.max_contacts_reported
		_log["has_phys_mat"] = _tracked.physics_material_override != null
		if _tracked.physics_material_override:
			_log["bounce"] = _tracked.physics_material_override.bounce
		var mi := _tracked.get_node_or_null("Mesh") as MeshInstance3D
		if mi != null and mi.mesh != null:
			_log["mesh_surfaces"] = mi.mesh.get_surface_count()
			var arr := (mi.mesh as ArrayMesh).surface_get_arrays(0) if mi.mesh is ArrayMesh else []
			if arr.size() > 0 and arr[Mesh.ARRAY_VERTEX] != null:
				_log["mesh_tris"] = arr[Mesh.ARRAY_VERTEX].size() / 3
	_next()


func _p3_track() -> void:
	if _tracked == null or not is_instance_valid(_tracked):
		_log["track"] = "rock gone"
		_next(); return
	var v := _tracked.linear_velocity.length()
	var y := _tracked.global_position.y
	_apex = maxf(_apex, y)
	_samples.append({"t": snappedf(_phase_t, 0.001), "v": snappedf(v, 0.01), "y": snappedf(y, 0.01)})

	if not _log.has("launch_speed") and v > 0.01:
		_log["launch_speed"] = snappedf(v, 0.01)

	if _phase_t > 1.6:
		_log["apex_y"] = snappedf(_apex, 0.01)
		_log["flight_end_y"] = snappedf(_tracked.global_position.y, 0.01)
		_log["samples"] = _samples.slice(0, 4)
		_shoot("a_flight")
		_next()


func _p4_bounce() -> void:
	if _bouncer == null:
		var ps: PackedScene = load("res://scenes/rock/Rock.tscn")
		if ps == null:
			_next(); return
		_bouncer = ps.instantiate() as RigidBody3D
		_main.add_child(_bouncer)
		_bouncer.global_position = Vector3(-2.2, 9.2, 5.0)
		_bouncer.linear_velocity = Vector3(0, -8.0, 0)
		_b_prev_vy = -8.0
		return
	if not is_instance_valid(_bouncer):
		_log["bounce_test"] = "rock freed early"
		_next(); return
	var vy := _bouncer.linear_velocity.y
	var sp := _bouncer.linear_velocity.length()
	if _b_pre < 0.0 and _b_prev_vy < -1.0 and vy > 0.15:
		_b_pre = absf(_b_prev_vy)
		_b_post = sp
	_b_prev_vy = vy
	if _phase_t > 3.0 or _b_pre > 0.0 and _phase_t > 0.6:
		_log["bounce_impact_speed"] = snappedf(_b_pre, 0.01)
		_log["bounce_rebound_speed"] = snappedf(_b_post, 0.01)
		_log["bounce_ratio"] = snappedf(_b_post / maxf(_b_pre, 0.001), 0.01) if _b_pre > 0.0 else 0.0
		_log["bounced"] = _b_pre > 0.0
		_log["bounce_rest_y"] = snappedf(_bouncer.global_position.y, 0.01)
		if is_instance_valid(_bouncer):
			_bouncer.queue_free()
		_next()


func _p4_spam() -> void:
	if _player == null:
		_next(); return
	if _spam.size() < 40 and fmod(_phase_t, 0.05) < 0.03:
		_player.set("_charge", randf_range(0.3, 1.2))
		_player.call("_spawn_rock", float(_player.call("_charge_speed")))
		_spam.append(1)
	if _phase_t > 0.6:
		_spam_frames.append(_last_delta * 1000.0)
	if _phase_t > 1.3:
		_shoot("b_spam")
	if _phase_t > 3.2:
		var live := int(_player.call("live_rock_count"))
		_log["spam_thrown"] = _spam.size()
		_log["spam_live"] = live
		_log["spam_cap_held"] = live <= int(_player.get("max_live_rocks"))
		if _spam_frames.size() > 0:
			var srt := _spam_frames.duplicate()
			srt.sort()
			var tot := 0.0
			for f in srt:
				tot += f
			_log["spam_frame_mean_ms"] = snappedf(tot / float(srt.size()), 0.01)
			_log["spam_frame_p95_ms"] = snappedf(srt[int(floor(float(srt.size() - 1) * 0.95))], 0.01)
			_log["spam_frame_max_ms"] = snappedf(srt[srt.size() - 1], 0.01)
			_log["spam_under_16ms"] = float(_log["spam_frame_p95_ms"]) < 16.0
		_next()


func _p5_water() -> void:
	if _player == null or _water == null:
		_next(); return
	if not _water_rock_spawned:
		_water_rock_spawned = true
		var holder := _water.get_node_or_null("Splashes")
		_log["splashes_before"] = holder.get_child_count() if holder else -1
		var ps: PackedScene = load("res://scenes/rock/Rock.tscn")
		var r := ps.instantiate() as RigidBody3D
		_main.add_child(r)
		r.global_position = Vector3(3.0, 5.0, -1.0)
		r.linear_velocity = Vector3(0, -5.0, 0)
		return
	var h2 := _water.get_node_or_null("Splashes")
	if h2 != null:
		_splash_peak = maxi(_splash_peak, h2.get_child_count())
	if _phase_t > 2.5:
		_log["splash_peak_after_water_throw"] = _splash_peak
		_log["splash_after_water_throw"] = _splash_peak > 0
		var surf := _find(_main, "WATER_Pool_Surface") as MeshInstance3D
		if surf != null and surf.material_override is ShaderMaterial:
			_log["ripple_count_after"] = (surf.material_override as ShaderMaterial).get_shader_parameter("ripple_count")
		_next()


func _shoot(nm: String) -> void:
	if _shot_taken.has(nm):
		return
	_shot_taken[nm] = true
	_busy = true
	_capture(nm)


func _capture(nm: String) -> void:
	await RenderingServer.frame_post_draw
	var img: Image = root.get_texture().get_image()
	DirAccess.make_dir_recursive_absolute(_out_dir)
	var path := _out_dir.path_join("_g4_probe_%s.png" % nm)
	var e := img.save_png(path)
	print("g4_probe: shot %s (%s)" % [nm, "OK" if e == OK else "ERR %d" % e])
	_busy = false


func _find(n: Node, nm: String) -> Node:
	if String(n.name) == nm:
		return n
	for c in n.get_children():
		var r := _find(c, nm)
		if r != null:
			return r
	return null


func _report() -> void:
	_done = true
	print("G4_PROBE_JSON:" + JSON.stringify(_log))
	quit()
