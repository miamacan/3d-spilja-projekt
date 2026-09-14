"""
B4 — vegetation and the Col moss mask.

RUNS INSIDE BLENDER (needs bpy). Unlike gen_cave.py, which runs in the cloud
container because it needs scipy/skimage, everything here is Blender-side:
curves, mesh building, raycasts against the shell, and the vertex-colour pass.

Run it on a file that already has B3's state. It is idempotent: it deletes and
rebuilds VINE_*, ROOT_*, the ferns numbered 9 and up, and the Col attribute on
every rock mesh, then re-seats MARK_Drip_01..05.

    exec(open(r"C:\\Users\\Mia\\Desktop\\3-dpr\\blender\\tools\\b4_vegetation.py").read())

WHY THE VINES HANG WHERE THEY DO — this is the one thing not to "fix" blindly.
The brief says "ceiling points near the skylight". The dome around the skylight
is at Z 27-28, and the hero frame's top edge is only ~3.5 m above eye level at
that distance: a vine hung from the true ceiling is entirely ABOVE the frame
and invisible. The reference's strands are visible because they hang from the
overhanging upper wall at Z 11-17.5, where the chamber radius shrinks with
height so the rock leans inward and a strand hangs free of it. That band was
found by probing, not guessed, and the lengths are then SOLVED so each tip
lands in the reference's measured band (tips v 0.23-0.40).
"""
import bpy, bmesh, math, numpy as np
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view

scene = bpy.context.scene
vl = bpy.context.view_layer
VEG = bpy.data.collections["30_VEGETATION"]
shell = bpy.data.objects["CAVE_Shell_Main"]
ledge = bpy.data.objects["LEDGE_Outcrop"]
cam = bpy.data.objects["CAM_Hero"]

AX, AY = 0.5, 1.0        # chamber axis, locked
SKY_AZ = 114.4           # azimuth of MARK_Skylight from that axis
BAND_Z = (11.0, 17.5)    # the overhang band that projects into the hero frame


# ---------------------------------------------------------------- helpers
def activate(ob):
    for o in bpy.context.selected_objects:
        o.select_set(False)
    vl.objects.active = ob
    ob.select_set(True)


def vof(p):
    """frame position from the TOP, 0..1"""
    return 1.0 - world_to_camera_view(scene, cam, Vector(p)).y


def uof(p):
    return world_to_camera_view(scene, cam, Vector(p)).x


_DIRS = [Vector(d) for d in ((0, 0, 1), (0, 0, -1), (1, 0, 0),
                             (-1, 0, 0), (0, 1, 0), (0, -1, 0))]


def in_void(p):
    """The shell is a ONE-SIDED surface with normals facing the void, so from
    open air a ray hits a FRONT face: dot(normal, direction) < 0. Vote over six
    axes -- a single noise-tilted face was enough to fail a single-ray test and
    it silently threw away 8 of 14 vines."""
    v = Vector(p)
    votes = seen = 0
    for d in _DIRS:
        ok, loc, nrm, idx = shell.ray_cast(v, d, distance=60.0)
        if not ok:
            continue
        seen += 1
        if nrm.dot(d) < 0.0:
            votes += 1
    return (votes * 2 >= seen) if seen else False


def sstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _hash01(ix, iy, iz, seed):
    h = (ix.astype(np.int64) * 73856093) ^ (iy.astype(np.int64) * 19349663) \
        ^ (iz.astype(np.int64) * 83492791) ^ np.int64(seed * 2654435761)
    h = (h ^ (h >> 13)) * np.int64(1274126177)
    h = h ^ (h >> 16)
    return (h & np.int64(0xFFFFFF)).astype(np.float64) / float(0xFFFFFF)


def vnoise(p, freq, seed):
    """vectorised 3D value noise -- a per-vertex python loop over 70k verts
    with mathutils.noise was the slow part; this is pure numpy"""
    q = p * freq
    i = np.floor(q)
    f = q - i
    w = f * f * (3.0 - 2.0 * f)
    ix, iy, iz = (i[:, 0].astype(np.int64), i[:, 1].astype(np.int64),
                  i[:, 2].astype(np.int64))
    c = {(a, b, d): _hash01(ix + a, iy + b, iz + d, seed)
         for a in (0, 1) for b in (0, 1) for d in (0, 1)}
    x00 = c[(0, 0, 0)] * (1 - w[:, 0]) + c[(1, 0, 0)] * w[:, 0]
    x10 = c[(0, 1, 0)] * (1 - w[:, 0]) + c[(1, 1, 0)] * w[:, 0]
    x01 = c[(0, 0, 1)] * (1 - w[:, 0]) + c[(1, 0, 1)] * w[:, 0]
    x11 = c[(0, 1, 1)] * (1 - w[:, 0]) + c[(1, 1, 1)] * w[:, 0]
    y0 = x00 * (1 - w[:, 1]) + x10 * w[:, 1]
    y1 = x01 * (1 - w[:, 1]) + x11 * w[:, 1]
    return (y0 * (1 - w[:, 2]) + y1 * w[:, 2]) * 2.0 - 1.0


def placeholder_material(name, rgba, alpha_clip=False):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF")
    if b:
        b.inputs["Base Color"].default_value = rgba
        if "Roughness" in b.inputs:
            b.inputs["Roughness"].default_value = 0.75
    if alpha_clip:
        for attr in ("blend_method", "shadow_method"):
            if hasattr(m, attr):
                try:
                    setattr(m, attr, 'CLIP')
                except Exception:
                    pass
    return m


# ================================================================== VINES
def find_anchor(az_deg, rad_pref):
    """An upward ray onto the overhanging dome. Requires nz < -0.25: an
    upward-facing hit means the ray started buried and came out on top of a
    rock shelf, and a vine hung from there passes straight down through it."""
    order = sorted(np.arange(10.15, 12.75, 0.13), key=lambda r: abs(r - rad_pref))
    for rad in order:
        for jit in (0.0, -2.0, 2.0, -4.0, 4.0):
            a = math.radians(az_deg + jit)
            x = AX + rad * math.cos(a)
            y = AY + rad * math.sin(a)
            ok, loc, nrm, idx = shell.ray_cast(Vector((x, y, 10.0)),
                                               Vector((0, 0, 1)), distance=25.0)
            if not ok or nrm.z >= -0.25:
                continue
            if not (BAND_Z[0] <= loc.z <= BAND_Z[1]):
                continue
            if not in_void((loc.x, loc.y, loc.z - 0.4)):
                continue
            return loc.copy(), nrm.copy(), float(rad), az_deg + jit
    return None, None, None, None


def vine_path(a, length, seed, step_in, n=180):
    """steps inward off the rock over the first 18% then hangs with a slight
    catenary bow and one or two kinks. The inward step matters: bowing alone
    swung strands back into the wall."""
    r = np.random.default_rng(seed)
    t = np.linspace(0, 1, n)
    inw = Vector((AX - a.x, AY - a.y, 0.0))
    inw = inw.normalized() if inw.length > 1e-6 else Vector((0, 1, 0))
    tg = Vector((-inw.y, inw.x, 0.0))
    s = np.clip(t / 0.18, 0, 1)
    s = s * s * (3 - 2 * s)
    amp = 0.10 + 0.14 * r.random()
    side = (r.random() - 0.5) * 0.5
    bow = np.sin(np.pi * t) * amp
    kink = np.zeros_like(t)
    kd = []
    for _ in range(int(r.integers(1, 3))):
        t0 = 0.20 + 0.60 * r.random()
        w = 0.05 + 0.05 * r.random()
        kink = kink + np.exp(-((t - t0) ** 2) / (2 * w * w)) * (0.07 + 0.14 * r.random())
        kd.append(Vector((r.random() - 0.5, r.random() - 0.5, 0.0)).normalized())
    pts = []
    for i, ti in enumerate(t):
        p = Vector((a.x, a.y, a.z - length * ti))
        p += inw * (step_in * s[i] + bow[i]) + tg * (bow[i] * side)
        if kd:
            p += kd[i % len(kd)] * kink[i]
        pts.append(p)
    return pts


def buried_frac(pts, skip=6):
    sm = pts[::skip]
    return sum(0 if in_void(p) else 1 for p in sm) / len(sm)


def ledge_clearance(pts, skip=5):
    d = 1e9
    for p in pts[::skip]:
        ok, loc, nrm, idx = ledge.closest_point_on_mesh(p)
        if ok:
            d = min(d, (Vector(p) - loc).length)
    return d


def solve_length(a, target_v):
    """length in 2..8 m whose tip lands nearest target_v in the hero frame"""
    best = (1e9, 4.0)
    for L in np.arange(2.0, 8.01, 0.1):
        e = abs(vof(Vector((a.x, a.y, a.z - L))) - target_v)
        if e < best[0]:
            best = (e, float(L))
    return best[1]


# Clumped, NOT evenly spaced: evenly spaced strands at one radius read as a
# fence. Three clusters plus strays, dense in the middle per the brief.
VINE_OFFS = [-6, -3, 0, 4, 7,  -20, -17, -13,  14, 18,  -36, -30,  26, 34]
VINE_RADP = [10.3, 11.6, 12.4, 10.9, 11.9, 10.4, 12.1, 11.2,
             10.6, 12.3, 11.4, 10.2, 12.0, 10.8]


def vine_target_v(off):
    mid = 1.0 - min(abs(off) / 40.0, 1.0)
    return 0.245 + 0.155 * (mid ** 0.7)     # reference: tips v 0.23..0.40


def build_vines(M_leaf):
    for o in list(VEG.objects):
        if o.name.startswith("VINE_"):
            bpy.data.objects.remove(o, do_unlink=True)
    rng = np.random.default_rng(9182)
    rep = {}
    for i, (off, rp) in enumerate(zip(VINE_OFFS, VINE_RADP), 1):
        a, nrm, rad, azu = find_anchor(SKY_AZ + off, rp)
        if a is None:
            rep["VINE_%02d" % i] = {"error": "no anchor"}
            continue
        L = solve_length(a, vine_target_v(off))
        bev = 0.030 + 0.030 * rng.random()      # spec 0.03-0.06
        seed = 7000 + i * 53
        chosen = None
        for step_in in (0.45, 0.70, 0.95, 1.25, 1.60):
            pts = vine_path(a, L, seed, step_in)
            bf = buried_frac(pts)
            if chosen is None or bf < chosen[1]:
                chosen = (pts, bf, step_in)
            if bf <= 0.10:
                break
        pts, bf, step_in = chosen

        st = max(2, int(len(pts) / max(4, round(L / 0.4))))
        ctrl = pts[::st]
        if (len(pts) - 1) % st:
            ctrl.append(pts[-1])
        cu = bpy.data.curves.new("VINE_%02d" % i, 'CURVE')
        cu.dimensions = '3D'
        cu.bevel_depth = bev
        cu.bevel_resolution = 0      # 4-sided: it is a 3-6 cm strand
        cu.resolution_u = 3
        sp = cu.splines.new('BEZIER')
        sp.bezier_points.add(len(ctrl) - 1)
        for bp, p in zip(sp.bezier_points, ctrl):
            bp.co = p
            bp.handle_left_type = bp.handle_right_type = 'AUTO'
        stem = bpy.data.objects.new("VINE_%02d" % i, cu)
        VEG.objects.link(stem)
        activate(stem)
        bpy.ops.object.convert(target='MESH')
        stem = bpy.data.objects["VINE_%02d" % i]

        # leaf cards. Built directly rather than with geometry nodes realised
        # to mesh: the end state is the same realised mesh, and this is
        # deterministic and scriptable. Two leaf variants share one atlas --
        # even k takes u 0..0.5, odd k takes u 0.5..1.
        r = np.random.default_rng(seed + 9001)
        nleaf = int(round(L * 70))
        bm = bmesh.new()
        uvl = bm.loops.layers.uv.new("UVMap")
        for k in range(nleaf):
            ti = 0.04 + 0.95 * (k + r.random()) / nleaf
            j = min(len(pts) - 2, int(ti * (len(pts) - 1)))
            base = pts[j]
            tg = (pts[j + 1] - pts[j]).normalized()
            ref = Vector((r.random() - 0.5, r.random() - 0.5, r.random() - 0.5)).normalized()
            ua = tg.cross(ref)
            if ua.length < 1e-5:
                ua = Vector((1, 0, 0))
            ua.normalize()
            va = tg.cross(ua).normalized()
            size = 0.075 + 0.105 * r.random()
            droop = 0.45 + 0.5 * r.random()
            out = (ua * (1.0 - droop) + Vector((0, 0, -1)) * droop).normalized()
            ctr = base + out * (size * 0.55) + tg * ((r.random() - 0.5) * 0.03)
            e1 = out * size
            e2 = va * (size * (0.5 + 0.35 * r.random()))
            vs = [bm.verts.new(q) for q in
                  (ctr - e1 * 0.35 - e2, ctr + e1 * 0.65 - e2,
                   ctr + e1 * 0.65 + e2, ctr - e1 * 0.35 + e2)]
            fc = bm.faces.new(vs)
            u0 = 0.0 if (k % 2 == 0) else 0.5
            for li, (uu, vv) in zip(fc.loops, ((0, 0), (1, 0), (1, 1), (0, 1))):
                li[uvl].uv = (u0 + uu * 0.5, vv)
        lm = bpy.data.meshes.new("l%d" % i)
        bm.to_mesh(lm)
        bm.free()
        lv = bpy.data.objects.new("l%d" % i, lm)
        VEG.objects.link(lv)
        activate(stem)
        lv.select_set(True)
        bpy.ops.object.join()
        ob = bpy.data.objects["VINE_%02d" % i]
        ob.data.name = ob.name
        ob.data.materials.clear()
        ob.data.materials.append(M_leaf)
        ob.color = (0.13, 0.30, 0.09, 1)
        ob.data.calc_loop_triangles()
        rep["VINE_%02d" % i] = {
            "az": round(azu, 1), "rad": round(rad, 2), "len_m": round(L, 2),
            "bevel_m": round(bev, 3), "tris": len(ob.data.loop_triangles),
            "u": round(uof(a), 3), "tip_v": round(vof(pts[-1]), 3),
            "buried_frac": round(bf, 3),
            "outcrop_clearance_m": round(ledge_clearance(pts), 2)}
    return rep


# ================================================================== ROOTS
def make_root(name, pts, bev, res_u=3, bev_res=1):
    cu = bpy.data.curves.new(name, 'CURVE')
    cu.dimensions = '3D'
    cu.bevel_depth = bev
    cu.bevel_resolution = bev_res
    cu.resolution_u = res_u
    sp = cu.splines.new('BEZIER')
    sp.bezier_points.add(len(pts) - 1)
    for bp, p in zip(sp.bezier_points, pts):
        bp.co = p
        bp.handle_left_type = bp.handle_right_type = 'AUTO'
    ob = bpy.data.objects.new(name, cu)
    VEG.objects.link(ob)
    activate(ob)
    bpy.ops.object.convert(target='MESH')
    ob = bpy.data.objects[name]
    ob.data.name = name
    ob.data.calc_loop_triangles()
    return ob


def build_roots(M_bark):
    for o in list(VEG.objects):
        if o.name.startswith("ROOT_"):
            bpy.data.objects.remove(o, do_unlink=True)
    cd = cam.data
    hf = math.tan(cd.angle_x / 2.0)
    vf = math.tan(cd.angle_y / 2.0)
    R = cam.matrix_world.to_3x3()
    O = cam.matrix_world.translation

    def wall_at(u, v):
        d = (R @ Vector(((u - 0.5) * 2 * hf, (0.5 - v) * 2 * vf, -1.0))).normalized()
        ok, loc, nrm, idx = shell.ray_cast(O, d, distance=200.0)
        return (loc.copy(), nrm.copy()) if ok else (None, None)

    rep = {}
    # ROOT_01..03: thick roots pushing through the upper right wall
    for i, (az0, z0, length, bev) in enumerate(
            [(26.0, 13.4, 3.4, 0.26), (38.0, 12.9, 2.8, 0.19), (17.0, 11.6, 3.9, 0.22)], 1):
        pts = []
        for k in range(9):
            f = k / 8.0
            az = az0 + (f - 0.5) * 15.0
            z = z0 + (f - 0.5) * length * 0.75 + 0.35 * math.sin(f * 4.0)
            a = math.radians(az)
            ok, loc, nrm, idx = shell.ray_cast(
                Vector((AX, AY, z)), Vector((math.cos(a), math.sin(a), 0.0)), distance=40.0)
            if ok:
                pts.append(loc + nrm * (bev * 0.55 + 0.05 * math.sin(f * 7.0)))
        if len(pts) < 4:
            rep["ROOT_%02d" % i] = {"error": "wall not found"}
            continue
        ob = make_root("ROOT_%02d" % i, pts, bev)
        ob.data.materials.clear(); ob.data.materials.append(M_bark)
        ob.color = (0.17, 0.12, 0.08, 1)
        rep["ROOT_%02d" % i] = {"tris": len(ob.data.loop_triangles), "bevel_m": bev,
                                "v_range": [round(min(vof(p) for p in pts), 3),
                                            round(max(vof(p) for p in pts), 3)]}

    # ROOT_04: the thin line crossing the top of the hero frame. Sampled by
    # casting camera rays along a target v and taking the wall hit, so it lands
    # on rock AND projects where the reference's line runs. Seating it proud of
    # the rock moves it toward the camera, which LIFTS it in frame -- so aim
    # lower than the band you want.
    best = None
    for aim in (0.105, 0.125, 0.145, 0.165):
        track = []
        for u in np.linspace(0.93, 0.12, 16):
            vv = aim + 0.030 * math.sin((u - 0.12) * 3.4)
            loc, nrm = wall_at(float(u), float(vv))
            if loc is None:
                continue
            track.append(loc + nrm * 0.16)
        if len(track) < 5:
            continue
        vr = [vof(p) for p in track]
        score = abs(float(np.mean(vr)) - 0.065) + (0.5 if min(vr) < 0.012 else 0.0)
        if best is None or score < best[0]:
            best = (score, aim, track, vr)
    if best:
        _, aim, track, vr = best
        ob = make_root("ROOT_04", track, 0.155)
        ob.data.materials.clear(); ob.data.materials.append(M_bark)
        ob.color = (0.17, 0.12, 0.08, 1)
        rep["ROOT_04"] = {"tris": len(ob.data.loop_triangles), "bevel_m": 0.155,
                          "aim_v": aim,
                          "v_range": [round(min(vr), 3), round(max(vr), 3)],
                          "spans_frame_width": round(max(uof(p) for p in track)
                                                     - min(uof(p) for p in track), 3)}
    return rep


# ============================================================== Col MASK
def openness(ob):
    """Per-vertex openness via Dirty Vertex Colors: bright = convex/open, dark
    = concave crevice. Normalised, so the sRGB curve on BYTE_COLOR only
    reshapes it monotonically and does not matter."""
    me = ob.data
    tmp = me.color_attributes.new(name="_tmp_ao", type='BYTE_COLOR', domain='CORNER')
    me.color_attributes.active_color = tmp
    activate(ob)
    bpy.ops.paint.vertex_color_dirt(blur_strength=1.0, blur_iterations=2,
                                    clean_angle=3.14159, dirt_angle=0.0,
                                    dirt_only=False, normalize=True)
    nl = len(me.loops)
    buf = np.empty(nl * 4, dtype=np.float32)
    tmp.data.foreach_get("color", buf)
    buf = buf.reshape(-1, 4)[:, 0]
    li = np.empty(nl, dtype=np.int32)
    me.loops.foreach_get("vertex_index", li)
    acc = np.zeros(len(me.vertices)); cnt = np.zeros(len(me.vertices))
    np.add.at(acc, li, buf); np.add.at(cnt, li, 1.0)
    op = np.where(cnt > 0, acc / np.maximum(cnt, 1), 0.5)
    me.color_attributes.remove(tmp)
    lo, hi = np.percentile(op, 2), np.percentile(op, 98)
    return np.clip((op - lo) / max(hi - lo, 1e-6), 0.0, 1.0)


def write_col():
    """R = up x noise x crevice, biased strong on the outcrop and left wall,
    faint on the right wall and ceiling, ZERO in the wet band.

    Two interpretations were fixed deliberately:
      * (1 - AO). The brief says moss "sits in crevices", so occlusion BOOSTS
        the mask. AO is read as openness, making (1-AO) the occlusion amount.
      * "zero within 0.5 m of Z = 0" is implemented as zero everywhere below
        Z 0.55 and ramping to full by 1.35, so submerged rock is bare too.
    """
    plan = [("CAVE_Shell_Main", "shell", 1.00),
            ("LEDGE_Outcrop", "outcrop", 1.40),
            ("ENT_Tunnel", "mouth", 0.95),
            ("ENT_Ground", "ground", 1.05)] + \
           [(o.name, "boulder", 1.05) for o in bpy.data.collections["20_ROCKS"].objects
            if o.name.startswith("ROCK_")]
    rep = {}
    for name, kind, obias in plan:
        ob = bpy.data.objects.get(name)
        if ob is None or ob.type != 'MESH':
            continue
        me = ob.data
        for a in list(me.color_attributes):
            if a.name in ("Col", "_tmp_ao"):
                me.color_attributes.remove(a)
        n = len(me.vertices)
        co = np.empty(n * 3, dtype=np.float32); me.vertices.foreach_get("co", co)
        nr = np.empty(n * 3, dtype=np.float32); me.vertices.foreach_get("normal", nr)
        co = co.reshape(-1, 3).astype(np.float64)
        nr = nr.reshape(-1, 3).astype(np.float64)
        M = np.array(ob.matrix_world)              # boulders carry placements
        wco = co @ M[:3, :3].T + M[:3, 3]
        wnr = nr @ np.linalg.inv(M[:3, :3]).T.T
        wnr = wnr / np.maximum(np.linalg.norm(wnr, axis=1, keepdims=True), 1e-9)
        op = openness(ob)
        nz, z, x = wnr[:, 2], wco[:, 2], wco[:, 0]

        up = np.clip(nz, 0, 1) ** 0.80 + 0.16 * np.clip(-nz, 0, 1) ** 2
        fbm = (0.60 * vnoise(wco, 0.55, 11) + 0.30 * vnoise(wco, 1.60, 22)
               + 0.10 * vnoise(wco, 4.20, 33))
        n01 = np.clip(fbm * 0.65 + 0.5, 0, 1)
        crev = 0.45 + 0.55 * (1.0 - op)
        wet = sstep(0.55, 1.35, z)
        high = 1.0 - 0.65 * sstep(14.0, 23.0, z)
        if kind == "shell":
            side = 1.15 - 0.87 * sstep(-2.0, 3.0, x)   # right wall ~0.28 of left
        elif kind == "ground":
            side = np.ones_like(x); wet = np.ones_like(z)   # forest floor
        else:
            side = np.ones_like(x)

        mask = up * n01 * crev * wet * high * side * obias
        mask = np.clip(np.clip((mask - 0.03) / 0.40, 0, 1) ** 0.90, 0, 1)

        col = me.color_attributes.new(name="Col", type='FLOAT_COLOR', domain='POINT')
        d = np.zeros((n, 4), dtype=np.float32)
        d[:, 0] = mask.astype(np.float32)
        d[:, 3] = 1.0
        col.data.foreach_set("color", d.reshape(-1))
        me.color_attributes.active_color = col
        me.update()

        def zone(m):
            return round(float(mask[m].mean()), 3) if m.any() else None
        rep[name] = {"mean": round(float(mask.mean()), 3),
                     "wet_band": zone(np.abs(z) < 0.5),
                     "left_wall": zone((x < -4) & (z > 2) & (z < 12)),
                     "right_wall": zone((x > 4) & (z > 2) & (z < 12)),
                     "ceiling": zone(z > 20),
                     "upface_above_water": zone((nz > 0.7) & (z > 1.5))}
    return rep


# ================================================================== FERNS
def build_ferns():
    """Only the left foreground and around the tunnel mouth, per the brief.
    Reject hits on LEDGE_Outcrop: downward rays over the left foreground land
    on the hero rock, and the reference has moss there, not ferns."""
    for o in list(VEG.objects):
        if o.name.startswith("FERN_") and int(o.name.split("_")[-1]) > 8:
            bpy.data.objects.remove(o, do_unlink=True)
    src = {1: bpy.data.objects["FERN_01_01"], 2: bpy.data.objects["FERN_02_01"]}

    def surface(x, y, z_from, shell_only):
        hits = []
        for o in (shell, ledge):
            ok, loc, nrm, idx = o.ray_cast(Vector((x, y, z_from)),
                                           Vector((0, 0, -1)), distance=40.0)
            if ok and nrm.z > 0.0:
                hits.append((loc.z, loc.copy(), nrm.copy(), o.name))
        if not hits:
            return None
        hits.sort(key=lambda h: -h[0])
        if shell_only and hits[0][3] != "CAVE_Shell_Main":
            return None
        return hits[0]

    rng = np.random.default_rng(3141)
    picked = []
    LEFT = []
    for t in np.linspace(0.10, 0.80, 10):          # along the talus ramp
        rx = -0.6 + t * (-6.2); ry = -11.4 + t * 7.4
        LEFT += [(rx - 0.9, ry - 0.3), (rx + 0.7, ry + 0.4)]
    for yy in (-9.5, -8.0, -6.5, -5.0, -3.5):      # left wall foot
        LEFT += [(-7.4, yy), (-8.4, yy)]
    MOUTH = [(x, y) for y in (-12.2, -13.4, -14.6, -15.8, -17.0, -18.2)
                    for x in (-1.5, -0.6, 0.7, 1.5)]

    for zone, cand, zfrom, max_slope, zmin, zmax, cap in (
            ("left", LEFT, 7.5, 55, 1.45, 6.0, 8),
            ("mouth", MOUTH, 9.0, 40, 4.8, 99.0, 6)):
        for cx, cy in cand:
            if sum(1 for p in picked if p[0] == zone) >= cap:
                break
            jx = cx + (rng.random() - 0.5) * 0.6
            jy = cy + (rng.random() - 0.5) * 0.6
            g = surface(jx, jy, zfrom, True)
            if g is None:
                continue
            gz, loc, nrm, on = g
            slope = math.degrees(math.acos(min(1.0, max(-1.0, nrm.z))))
            if slope > max_slope or gz < zmin or gz > zmax:
                continue
            if any((Vector(p[1]) - loc).length < 1.0 for p in picked):
                continue
            picked.append((zone, [loc.x, loc.y, loc.z], nrm.copy(), round(gz, 2),
                           round(slope, 1)))

    out = []
    for i, (zone, loc, nrm, gz, slope) in enumerate(picked):
        k = 1 if i % 2 == 0 else 2
        idx = 9 + sum(1 for o in out if o["kind"] == k)
        nm = "FERN_%02d_%02d" % (k, idx)
        nob = bpy.data.objects.new(nm, src[k].data)      # shares mesh data
        VEG.objects.link(nob)
        nob.location = Vector(loc) + nrm * 0.02
        nob.rotation_euler = (0.0, 0.0, rng.random() * math.tau)
        s = 0.8 + 0.5 * rng.random()
        nob.scale = (s, s, s)
        nob.color = (0.17, 0.38, 0.12, 1)
        out.append({"name": nm, "kind": k, "zone": zone,
                    "loc": [round(v, 2) for v in loc], "slope_deg": slope})
    return out


# ================================================================== DRIPS
def reseat_drips():
    """MARK_Drip_01..05 belong at vine tips over water. Until B4 there were no
    vines and they sat at a guessed Z 19."""
    water = bpy.data.objects["WATER_Pool_Surface"]
    tips = []
    for i in range(1, 15):
        v = bpy.data.objects.get("VINE_%02d" % i)
        if not v:
            continue
        n = len(v.data.vertices)
        a = np.empty(n * 3, dtype=np.float32)
        v.data.vertices.foreach_get("co", a)
        a = a.reshape(-1, 3)
        low = a[np.argmin(a[:, 2])]
        p = Vector((float(low[0]), float(low[1]), float(low[2])))
        ok, loc, nrm, idx = water.ray_cast(Vector((p.x, p.y, p.z - 0.05)),
                                           Vector((0, 0, -1)), distance=60.0)
        if ok:
            tips.append((i, p))
    tips.sort(key=lambda t: -t[1].z)
    out = []
    for k, (vi, p) in enumerate(tips[:5], 1):
        e = bpy.data.objects.get("MARK_Drip_%02d" % k)
        if not e:
            continue
        e.location = (p.x, p.y, p.z - 0.06)
        e.rotation_euler = (0.0, 0.0, 0.0)      # -Z already points the way a drop falls
        out.append({"marker": e.name, "vine": "VINE_%02d" % vi,
                    "loc": [round(p.x, 2), round(p.y, 2), round(p.z - 0.06, 2)]})
    return out, len(tips)


# =================================================================== MAIN
if __name__ == "__main__" or True:
    M_leaf = placeholder_material("M_VineLeaf", (0.16, 0.34, 0.10, 1.0), alpha_clip=True)
    M_bark = placeholder_material("M_RootBark", (0.13, 0.10, 0.07, 1.0))
    vines = build_vines(M_leaf)
    roots = build_roots(M_bark)
    col = write_col()
    ferns = build_ferns()
    drips, n_over_water = reseat_drips()

    veg = [o for o in VEG.objects if o.type == 'MESH']
    for o in veg:
        o.data.calc_loop_triangles()
    print("=== B4 ===")
    ok = {k: v for k, v in vines.items() if "tris" in v}
    print("vines        %d, %d tris, lengths %.1f-%.1f m, tips v %.3f-%.3f"
          % (len(ok), sum(v["tris"] for v in ok.values()),
             min(v["len_m"] for v in ok.values()), max(v["len_m"] for v in ok.values()),
             min(v["tip_v"] for v in ok.values()), max(v["tip_v"] for v in ok.values())))
    print("             min outcrop clearance %.2f m"
          % min(v["outcrop_clearance_m"] for v in ok.values()))
    print("roots        %s" % {k: v.get("tris") for k, v in roots.items()})
    print("ferns        %d (%d left, %d mouth)"
          % (len(ferns), sum(1 for f in ferns if f["zone"] == "left"),
             sum(1 for f in ferns if f["zone"] == "mouth")))
    print("drips        %d re-seated, %d vine tips over water" % (len(drips), n_over_water))
    print("shell Col    %s" % col.get("CAVE_Shell_Main"))
    print("veg tris     %d / 50000" % sum(len(o.data.loop_triangles) for o in veg))
