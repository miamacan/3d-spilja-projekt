# Spaja materijale stijene na prave slikovne teksture (base colour, normal, ORM)
# umjesto proceduralnog shadera, jer Godot/glTF ne mogu prenijeti Blenderov
# node-graf - samo gotove slike.

import os

import bpy

TEX_DIR = "textures"
SETS = {
    "M_Limestone_Shell": "T_Limestone",
    "M_Limestone_Outcrop": "T_Limestone",
}
EXPORT_COLLECTIONS = ("10_CAVE", "20_ROCKS", "30_VEGETATION",
                      "40_ENTRANCE", "50_WATER", "60_COLLISION", "70_MARKERS")
ALLOWED = {"ShaderNodeBsdfPrincipled", "ShaderNodeTexImage", "ShaderNodeNormalMap",
           "ShaderNodeSeparateColor", "ShaderNodeOutputMaterial"}


def _grab(me, name):
    # čita sve UV koordinate jednog UV sloja u niz brojeva
    import numpy as np
    lay = me.uv_layers[name]
    a = np.empty(len(lay.data) * 2, dtype=np.float32)
    lay.data.foreach_get("uv", a)
    return a


def reorder_uvs(ob):
    # UVTile mora biti prvi UV sloj (index 0), inače Godot pri uvozu tu teksturu
    # stavi na pogrešan UV slot (koji je rezerviran za lightmape)
    import numpy as np
    me = ob.data
    names = [l.name for l in me.uv_layers]
    if "UVTile" not in names or "UVMap" not in names:
        return {"object": ob.name, "skipped": names}
    before = {n: _grab(me, n) for n in ("UVMap", "UVTile")}
    moved = False
    if names[0] != "UVTile":
        while me.uv_layers:
            me.uv_layers.remove(me.uv_layers[0])
        for n in ("UVTile", "UVMap"):
            lay = me.uv_layers.new(name=n, do_init=False)
            lay.data.foreach_set("uv", before[n])
        moved = True
    after = {n: _grab(me, n) for n in ("UVMap", "UVTile")}
    me.uv_layers["UVTile"].active_render = True
    me.uv_layers.active = me.uv_layers["UVMap"]
    return {
        "object": ob.name,
        "order": [l.name for l in me.uv_layers],
        "moved": moved,
        "identical": all(bool(np.array_equal(before[n], after[n])) for n in before),
        "active_render": next(l.name for l in me.uv_layers if l.active_render),
        "active": me.uv_layers.active.name,
    }


def load_image(fn, non_color):
    # učita teksturu s diska (ili je pronađe ako je već učitana) i postavi joj ispravan
    # prostor boje - "Non-Color" za normal/ORM mape, "sRGB" za obične boje
    path = os.path.join(os.path.dirname(os.path.dirname(bpy.data.filepath)), TEX_DIR, fn)
    img = bpy.data.images.get(fn)
    if img is None:
        img = bpy.data.images.load(path, check_existing=True)
        img.name = fn
    img.colorspace_settings.name = "Non-Color" if non_color else "sRGB"
    img.alpha_mode = "NONE"
    try:
        img.filepath = bpy.path.relpath(path)
    except Exception:
        pass
    return img


def rewire(mat, tex_set):
    # obriše stari shader i sagradi novi, jednostavan: 3 slike (base colour, normal, ORM)
    # spojene ravno na Principled BSDF - to je materijal koji glTF/Godot razumije
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial"); out.location = (520, 0)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled"); bsdf.location = (220, 0)
    bc = nt.nodes.new("ShaderNodeTexImage"); bc.location = (-360, 240)
    nm_t = nt.nodes.new("ShaderNodeTexImage"); nm_t.location = (-360, -40)
    orm_t = nt.nodes.new("ShaderNodeTexImage"); orm_t.location = (-360, -320)
    nmap = nt.nodes.new("ShaderNodeNormalMap"); nmap.location = (-60, -60)
    sep = nt.nodes.new("ShaderNodeSeparateColor"); sep.location = (-60, -320)

    bc.image = load_image(tex_set + "_BC.png", False)
    nm_t.image = load_image(tex_set + "_N.png", True)
    orm_t.image = load_image(tex_set + "_ORM.png", True)
    nmap.uv_map = ""

    L = nt.links.new
    L(bc.outputs["Color"], bsdf.inputs["Base Color"])
    L(nm_t.outputs["Color"], nmap.inputs["Color"])
    L(nmap.outputs["Normal"], bsdf.inputs["Normal"])
    L(orm_t.outputs["Color"], sep.inputs["Color"])
    L(sep.outputs["Green"], bsdf.inputs["Roughness"])
    L(sep.outputs["Blue"], bsdf.inputs["Metallic"])
    L(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return {"material": mat.name, "nodes": len(nt.nodes),
            "types": sorted({n.bl_idname for n in nt.nodes})}


def exported_materials():
    # skupi sve materijale koji se stvarno izvoze (unutar kolekcija 10-70)
    mats, seen = [], set()
    for cname in EXPORT_COLLECTIONS:
        coll = bpy.data.collections.get(cname)
        if not coll:
            continue
        for ob in coll.all_objects:
            for slot in getattr(ob, "material_slots", []):
                m = slot.material
                if m and m.name not in seen:
                    seen.add(m.name); mats.append(m)
    return mats


def node_type_check():
    # provjera: svi materijali smiju koristiti SAMO dopuštene tipove node-ova
    # (jer glTF ne zna izvesti bilo koji drugi shader čvor)
    used, offenders = set(), {}
    for m in exported_materials():
        if not m.node_tree:
            continue
        t = {n.bl_idname for n in m.node_tree.nodes}
        used |= t
        bad = sorted(t - ALLOWED)
        if bad:
            offenders[m.name] = bad
    return {"materials": sorted(m.name for m in exported_materials()),
            "node_types_used": sorted(used),
            "is_subset_of_allowed": not offenders,
            "offenders": offenders}


def run():
    # glavna funkcija: prespoji materijale, poredaj UV slojeve, i provjeri rezultat
    rep = {"uv": [], "materials": []}
    for mat_name, tex_set in SETS.items():
        mat = bpy.data.materials.get(mat_name)
        if mat:
            rep["materials"].append(rewire(mat, tex_set))
    targets = [ob for ob in bpy.data.objects
               if ob.type == "MESH"
               and any(s.material and s.material.name in SETS for s in ob.material_slots)]
    for ob in sorted(targets, key=lambda o: o.name):
        rep["uv"].append(reorder_uvs(ob))
    rep["uv_all_identical"] = all(u.get("identical", True) for u in rep["uv"])
    rep["uv_meshes"] = len(rep["uv"])
    rep["check"] = node_type_check()
    return rep


if __name__ == "__main__":
    print(run())
