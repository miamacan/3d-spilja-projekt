# Peče "macro" teksturu za svaki veći komad geometrije (zid, izbočina...) -
# slojevitost stijene i mrlje od vode, koje obična tiling tekstura ne može
# prikazati jer ovise o svjetskoj Z koordinati (visini), a ne o UV-u.

import bpy, os, time
import numpy as np

SIZE        = 1024
RATIO_SCALE = 1.5
AO_DISTANCE = 3.0
SAMPLES     = 32
MARGIN      = 8


TARGETS = {
    "CAVE_Shell_Main": (0.34, 1.00),
    "ENT_Tunnel":      (0.34, 1.00),
    "ENT_Ground":      (0.34, 1.00),
    "LEDGE_Outcrop":   (0.38, 1.75),
}


def build_macro(nt, strata_f, stain_gain):
    # sagradi privremeni shader-graf koji generira slojevitost i mrlje od vode,
    # na temelju svjetske pozicije (Z os = visina)
    N, L = nt.nodes, nt.links
    geo = N.new("ShaderNodeNewGeometry")
    sxyz = N.new("ShaderNodeSeparateXYZ")
    L.new(geo.outputs["Position"], sxyz.inputs["Vector"])

    def mapping(scale):
        # skalira poziciju prije šuma (kontrolira "gustoću" uzorka)
        m = N.new("ShaderNodeMapping"); m.vector_type = "POINT"
        m.inputs["Scale"].default_value = scale
        L.new(geo.outputs["Position"], m.inputs["Vector"]); return m

    def noise(src, sc, det, rough):
        # 3D šum (fractal noise) za teksturu
        n = N.new("ShaderNodeTexNoise")
        n.noise_dimensions = "3D"; n.noise_type = "FBM"; n.normalize = True
        n.inputs["Scale"].default_value = sc
        n.inputs["Detail"].default_value = det
        n.inputs["Roughness"].default_value = rough
        n.inputs["Lacunarity"].default_value = 2.0
        L.new(src.outputs["Vector"], n.inputs["Vector"]); return n

    def ramp(src, interp, p0, c0, p1, c1):
        # pretvara šum u boju (color ramp - gradijent od boje c0 do c1)
        r = N.new("ShaderNodeValToRGB"); r.color_ramp.interpolation = interp
        e = r.color_ramp.elements
        e[0].position, e[0].color = p0, c0
        e[1].position, e[1].color = p1, c1
        L.new(src.outputs["Fac"], r.inputs["Fac"]); return r

    def maprange(sock, fmin, fmax, tmin, tmax):
        # preslika vrijednost iz jednog raspona u drugi (npr. visinu u jačinu efekta)
        m = N.new("ShaderNodeMapRange"); m.data_type = "FLOAT"
        m.clamp = True; m.interpolation_type = "LINEAR"
        m.inputs[1].default_value = fmin; m.inputs[2].default_value = fmax
        m.inputs[3].default_value = tmin; m.inputs[4].default_value = tmax
        L.new(sock, m.inputs[0]); return m

    # osnovna boja stijene (blaga varijacija)
    cr0 = ramp(noise(mapping((1, 1, 1)), 0.42, 6, 0.55), "LINEAR",
               0.32, (0.105, 0.098, 0.086, 1), 0.68, (0.215, 0.203, 0.18, 1))

    # slojevitost (strata) - šum spljošten po Z osi da izgleda kao vodoravni slojevi
    cr1 = ramp(noise(mapping((1, 1, 15)), 0.85, 8, 0.62), "B_SPLINE",
               0.40, (0, 0, 0, 1), 0.60, (1, 1, 1, 1))
    mixA = N.new("ShaderNodeMixRGB"); mixA.blend_type = "OVERLAY"
    mixA.inputs["Fac"].default_value = strata_f
    L.new(cr0.outputs["Color"], mixA.inputs["Color1"])
    L.new(cr1.outputs["Color"], mixA.inputs["Color2"])

    # mrlje od vode (stains) - izduljene okomito, jače pri dnu (blizu poda)
    cr2 = ramp(noise(mapping((3.2, 3.2, 0.22)), 1.15, 8, 0.7), "LINEAR",
               0.46, (0, 0, 0, 1), 0.74, (1, 1, 1, 1))
    zg = maprange(sxyz.outputs["Z"], 16.0, 0.0, 0.25, 1.0)
    m0 = N.new("ShaderNodeMath"); m0.operation = "MULTIPLY"; m0.use_clamp = True
    L.new(cr2.outputs["Color"], m0.inputs[0]); m0.inputs[1].default_value = stain_gain
    m1 = N.new("ShaderNodeMath"); m1.operation = "MULTIPLY"; m1.use_clamp = True
    L.new(m0.outputs["Value"], m1.inputs[0]); L.new(zg.outputs["Result"], m1.inputs[1])
    mixB = N.new("ShaderNodeMixRGB"); mixB.blend_type = "MIX"
    mixB.inputs["Color2"].default_value = (0.105, 0.092, 0.078, 1)
    L.new(m1.outputs["Value"], mixB.inputs["Fac"])
    L.new(mixA.outputs["Color"], mixB.inputs["Color1"])

    # "mokri pojas" tik iznad vodene linije - niži roughness, tamnija boja
    wet = maprange(sxyz.outputs["Z"], 0.85, 0.6, 0.0, 1.0)
    mixC = N.new("ShaderNodeMixRGB"); mixC.blend_type = "MULTIPLY"
    mixC.inputs["Color2"].default_value = (0.6, 0.6, 0.62, 1)
    L.new(wet.outputs["Result"], mixC.inputs["Fac"])
    L.new(mixB.outputs["Color"], mixC.inputs["Color1"])

    # roughness: suha stijena 0.82, s mrljama 0.62, mokra 0.15
    r0 = maprange(m1.outputs["Value"], 0.0, 1.0, 0.82, 0.62)
    r1 = N.new("ShaderNodeMapRange"); r1.data_type = "FLOAT"; r1.clamp = True
    r1.inputs[1].default_value = 0.0; r1.inputs[2].default_value = 1.0
    r1.inputs[4].default_value = 0.15
    L.new(wet.outputs["Result"], r1.inputs[0])
    L.new(r0.outputs["Result"], r1.inputs[3])
    return {"base": cr0.outputs["Color"],
            "albedo": mixC.outputs["Color"],
            "rough": r1.outputs["Result"]}


def _read(img):
    # čita piksele slike u numpy polje
    a = np.empty(SIZE * SIZE * 4, dtype=np.float32)
    img.pixels.foreach_get(a)
    return a.reshape(SIZE, SIZE, 4)


def bake_one(obj_name, strata_f, stain_gain, texdir):
    # za jedan objekt: privremeno mu zamijeni materijal, ispeci (bake) sve slojeve
    # (boju, AO, roughness), spremi rezultat kao jednu ORM-stil teksturu, i vrati mu stari materijal
    S = bpy.context.scene
    o = bpy.data.objects[obj_name]
    keep_mats = [s.material for s in o.material_slots]

    mat = bpy.data.materials.new("_BAKE_TMP"); mat.use_nodes = True
    nt = mat.node_tree; nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    emi = nt.nodes.new("ShaderNodeEmission"); emi.inputs["Strength"].default_value = 1.0
    nt.links.new(emi.outputs["Emission"], out.inputs["Surface"])
    taps = build_macro(nt, strata_f, stain_gain)
    tgt = nt.nodes.new("ShaderNodeTexImage")
    o.data.materials.clear(); o.data.materials.append(mat)

    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = o; o.select_set(True)

    got, secs = {}, {}
    for key, btype in (("base", "EMIT"), ("albedo", "EMIT"),
                       ("rough", "EMIT"), ("ao", "AO")):
        im = bpy.data.images.new("_bk_" + key, SIZE, SIZE, alpha=True,
                                 float_buffer=True, is_data=True)
        tgt.image = im; nt.nodes.active = tgt
        if btype == "EMIT":
            for l in list(nt.links):
                if l.to_socket == emi.inputs["Color"]:
                    nt.links.remove(l)
            nt.links.new(taps[key], emi.inputs["Color"])
        t = time.time()
        bpy.ops.object.bake(type=btype, uv_layer="UVMap",
                            margin=MARGIN, use_clear=True)
        secs[key] = round(time.time() - t, 2)
        got[key] = _read(im)
        bpy.data.images.remove(im)

    o.data.materials.clear()
    for m in keep_mats:
        o.data.materials.append(m)
    bpy.data.materials.remove(mat)

    # spakiraj rezultat: R = omjer boje (koliko je potamnjeno/mrlja), G = AO, B = roughness
    base, alb = got["base"][..., :3], got["albedo"][..., :3]
    cov = base[..., 0] > 1e-4
    ratio = np.where(base > 1e-5, alb / np.maximum(base, 1e-5), 1.0)
    chroma = float(np.abs(ratio[..., 0] - ratio[..., 2])[cov].max()) if cov.any() else 0.0

    packed = np.ones((SIZE, SIZE, 4), dtype=np.float32)
    packed[..., 0] = np.clip(ratio[..., 0] / RATIO_SCALE, 0.0, 1.0)
    packed[..., 1] = np.clip(got["ao"][..., 0], 0.0, 1.0)
    packed[..., 2] = np.clip(got["rough"][..., 0], 0.0, 1.0)

    packed[..., 0][~cov] = 1.0 / RATIO_SCALE
    packed[..., 1][~cov] = 1.0
    packed[..., 2][~cov] = 0.82

    name = "T_Macro_%s.png" % obj_name
    path = os.path.join(texdir, name)
    oi = bpy.data.images.get(name)
    if oi:
        bpy.data.images.remove(oi)
    oi = bpy.data.images.new(name, SIZE, SIZE, alpha=True,
                             float_buffer=False, is_data=True)
    oi.colorspace_settings.name = "Non-Color"
    oi.pixels.foreach_set(packed.ravel())
    oi.filepath_raw = path; oi.file_format = "PNG"; oi.save()

    def st(a, m):
        v = a[m]
        return {"mean": round(float(v.mean()), 4), "min": round(float(v.min()), 4),
                "max": round(float(v.max()), 4),
                "p99": round(float(np.percentile(v, 99)), 4)}

    return {"object": obj_name, "file": name, "bake_s": secs,
            "coverage_pct": round(100 * float(cov.mean()), 2),
            "ratio": st(ratio[..., 0], cov),
            "ratio_chroma_max": round(chroma, 4),
            "clipped_pct": round(100 * float((ratio[..., 0][cov] > RATIO_SCALE).mean()), 3),
            "ao": st(got["ao"][..., 0], cov),
            "roughness": st(got["rough"][..., 0], cov),
            "mb": round(os.path.getsize(path) / 1048576, 3)}


def run():
    # glavna funkcija: postavi Cycles za pečenje, obradi sve ciljane objekte, vrati postavke natrag
    S = bpy.context.scene
    keep = (S.render.engine, S.cycles.device, S.cycles.samples,
            S.cycles.use_denoising, S.world.light_settings.distance,
            S.render.bake.margin)
    S.render.engine = "CYCLES"
    S.cycles.device = "GPU"; S.cycles.samples = SAMPLES; S.cycles.use_denoising = True
    S.world.light_settings.distance = AO_DISTANCE
    S.render.bake.margin = MARGIN

    texdir = os.path.join(os.path.dirname(os.path.dirname(bpy.data.filepath)), "textures")
    os.makedirs(texdir, exist_ok=True)

    out = []
    try:
        for name, (sf, sg) in TARGETS.items():
            out.append(bake_one(name, sf, sg, texdir))
    finally:
        (S.render.engine, S.cycles.device, S.cycles.samples,
         S.cycles.use_denoising, S.world.light_settings.distance,
         S.render.bake.margin) = keep
        for m in [m for m in bpy.data.materials if m.name.startswith("_BAKE_")]:
            bpy.data.materials.remove(m)
        for i in [i for i in bpy.data.images if i.name.startswith("_bk_")]:
            bpy.data.images.remove(i)
    return out


if __name__ == "__main__" or True:
    B7_RESULT = run()
