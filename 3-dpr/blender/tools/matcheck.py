# Skripta za brzo renderiranje kontrolnih slika materijala (pokreće se unutar Blendera).
# Postavi privremeno svjetlo i kameru, snimi par slika izbliza (stijena, ulaz u tunel...),
# pa sve vrati na staro kad završi.

import bpy, math, os
from mathutils import Vector, Euler

OUT = os.path.join(os.path.dirname(bpy.data.filepath), "_src")
SAMPLES = 256
RES = (1200, 675)
WORLD_STRENGTH = 1.6


def _cam_on_surface(ob, from_pt, to_pt, dist, name, lens=50.0):
    # postavlja kameru ispred površine objekta, okrenutu prema njoj (koristi raycast)
    M = ob.matrix_world
    Mi = M.inverted()
    o = Mi @ Vector(from_pt)
    t = Mi @ Vector(to_pt)
    hit, loc, nrm, _ = ob.ray_cast(o, (t - o).normalized())
    if not hit:
        return None, None
    p = M @ loc
    n = (M.to_3x3() @ nrm).normalized()
    if (o - loc).dot(nrm) < 0:
        n = -n
    cd = bpy.data.cameras.new(name)
    cd.lens = lens
    cam = bpy.data.objects.new(name, cd)
    bpy.context.scene.collection.objects.link(cam)
    cam.location = p + n * dist
    cam.rotation_euler = (p - cam.location).normalized().to_track_quat('-Z', 'Y').to_euler()
    return cam, p


def run():
    # glavna funkcija: sprema trenutne postavke, renderira kontrolne snimke, vraća postavke natrag
    sc = bpy.context.scene
    ee = sc.eevee
    bg = sc.world.node_tree.nodes["Background"].inputs["Strength"]
    save = {
        "engine": sc.render.engine, "cam": sc.camera.name if sc.camera else None,
        "res": (sc.render.resolution_x, sc.render.resolution_y),
        "pct": sc.render.resolution_percentage, "fp": sc.render.filepath,
        "ff": sc.render.image_settings.file_format, "bg": bg.default_value,
        "samples": getattr(ee, "taa_render_samples", None),
    }
    os.makedirs(OUT, exist_ok=True)
    sc.render.engine = 'BLENDER_EEVEE'
    sc.render.resolution_x, sc.render.resolution_y = RES
    sc.render.resolution_percentage = 100
    sc.render.image_settings.file_format = 'PNG'
    bg.default_value = WORLD_STRENGTH
    if hasattr(ee, "taa_render_samples"):
        ee.taa_render_samples = SAMPLES

    made = []

    def light(name, loc, energy, size, rot=(0, 0, 0), color=(1, 1, 1)):
        # dodaje privremeno svjetlo (uklanja se na kraju)
        d = bpy.data.lights.new(name, 'AREA')
        d.energy, d.color, d.size = energy, color, size
        ob = bpy.data.objects.new(name, d)
        ob.location = loc
        ob.rotation_euler = Euler(rot)
        sc.collection.objects.link(ob)
        made.append(ob)

    oc = bpy.data.objects["LEDGE_Outcrop"]
    bb = [oc.matrix_world @ Vector(c) for c in oc.bound_box]
    cx = sum(v.x for v in bb) / 8
    cy = sum(v.y for v in bb) / 8
    zmax = max(v.z for v in bb)

    light("LD_Key", (cx, cy, 26.0), 90000.0, 8.0, color=(1.0, 0.97, 0.9))
    light("LD_Fill", (cx - 12, cy - 10, 12.0), 12000.0, 14.0,
          rot=(math.radians(62), 0, math.radians(-42)), color=(0.75, 0.82, 0.95))

    shots = {}

    def shoot(tag, cam):
        # renderira jednu sliku s te kamere i sprema je na disk
        sc.camera = cam
        sc.render.filepath = os.path.join(OUT, "_mat_" + tag)
        bpy.ops.render.render(write_still=True)
        shots[tag] = sc.render.filepath + ".png"

    shoot("hero", bpy.data.objects["CAM_Hero"])

    # slika izbliza: stijena (outcrop)
    cam, p = _cam_on_surface(oc, (cx - 9.0, cy - 9.0, zmax + 2.0),
                             (cx, cy, zmax - 0.6), 3.0, "LD_OutcropCam")
    if cam:
        made.append(cam)
        shoot("detail", cam)

    # slika izbliza: zid špilje
    sh = bpy.data.objects["CAVE_Shell_Main"]
    cam, p = _cam_on_surface(sh, (cx, cy, 9.0), (cx - 30.0, cy, 9.0), 4.0, "LD_WallCam")
    if cam:
        made.append(cam)
        shoot("wall", cam)

    # slika izbliza: ulaz u tunel
    tun = bpy.data.objects.get("ENT_Tunnel")
    if tun:
        tb = [tun.matrix_world @ Vector(c) for c in tun.bound_box]
        tx = sum(v.x for v in tb) / 8
        ty = sum(v.y for v in tb) / 8
        tz = min(v.z for v in tb) + 2.0
        cam, p = _cam_on_surface(tun, (tx, ty, tz), (tx, ty, tz + 6.0), 3.0, "LD_TunnelCam")
        if cam:
            made.append(cam)
            shoot("tunnel", cam)

    # ukloni sve privremene kamere i svjetla
    for ob in made:
        dat = ob.data
        bpy.data.objects.remove(ob, do_unlink=True)
        if isinstance(dat, bpy.types.Light):
            bpy.data.lights.remove(dat)
        elif isinstance(dat, bpy.types.Camera):
            bpy.data.cameras.remove(dat)

    # vrati originalne postavke rendera
    sc.render.engine = save["engine"]
    if save["cam"]:
        sc.camera = bpy.data.objects[save["cam"]]
    sc.render.resolution_x, sc.render.resolution_y = save["res"]
    sc.render.resolution_percentage = save["pct"]
    sc.render.filepath = save["fp"]
    sc.render.image_settings.file_format = save["ff"]
    bg.default_value = save["bg"]
    if save["samples"] is not None:
        ee.taa_render_samples = save["samples"]
    bpy.ops.wm.save_mainfile()

    leftovers = [o.name for o in bpy.data.objects if o.name.startswith("LD_")]
    return {"shots": shots, "leftovers": leftovers, "engine": sc.render.engine}


if __name__ == "__main__":
    print(run())
