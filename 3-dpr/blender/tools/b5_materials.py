"""b5_materials.py -- rewire the limestone materials to images. Runs INSIDE Blender.

Companion to b5_textures.py. That one makes the maps; this one wires them and
throws the procedural trees away, so it is the DESTRUCTIVE half of the session.
Save cave_B5_procedural.blend before running it -- the 30-node look-dev graphs
are not recoverable from anything else.

WHAT IT DOES

1. Reorders the UV layers so UVTile is index 0 and UVMap index 1, on every mesh
   carrying a limestone material.

   WHY: with one-layer materials the shipped textures sample UVTile, and glTF
   writes a texture's TEXCOORD index from the layer's POSITION in the list, not
   from which one is active_render. Left at index 1 the whole texture set would
   arrive in Godot on UV2 -- the slot Godot fills with generated lightmap UVs on
   import (contract  2). So UVTile has to be index 0.

   This changes a  3 invariant ("UVMap kept active and active_render"). It is
   forced by the one-layer decision, not chosen. UVMap survives intact at index
   1 and stays the ACTIVE (edit) layer; it is still what the deferred per-mesh
   macro dirt map will bake into. The reorder round-trip is verified
   coordinate-by-coordinate, because silently scrambling a 139k-tri unwrap would
   be an expensive thing to discover later.

2. Clears both limestone node trees and rebuilds them from five node types
   only, so the contract's node-type check passes literally:
   {Principled BSDF, Image Texture, Normal Map, Separate Colour, Material Output}

   ORM: R = AO is deliberately LEFT UNCONNECTED. Principled has no AO input, and
   multiplying it into base colour would need a Mix node, which the allowlist
   forbids. Godot's shader reads it off the ORM image. G -> Roughness,
   B -> Metallic.

3. Runs the node-type check across every material that exports (collections
   10-70) and returns the result rather than asserting, so the caller can report
   a measured pass instead of a hoped-for one.

WHAT IT DELIBERATELY DOES NOT DO
The look-dev's stratification bands, water stains and wet band were driven by
world Z and cannot survive into a surface tile (see b5_textures.py's header for
the measurement). They are not reproduced here. The rewired walls carry
limestone SURFACE CHARACTER only; the world-space layers come back as the
deferred per-mesh macro maps, or in Godot's shader.
"""
import os

import bpy

TEX_DIR = "textures"
SETS = {
    "M_Limestone_Shell": "T_Limestone",
    "M_Limestone_Outcrop": "T_Limestone",   # its unique 4K set is deferred
}
EXPORT_COLLECTIONS = ("10_CAVE", "20_ROCKS", "30_VEGETATION",
                      "40_ENTRANCE", "50_WATER", "60_COLLISION", "70_MARKERS")
ALLOWED = {"ShaderNodeBsdfPrincipled", "ShaderNodeTexImage", "ShaderNodeNormalMap",
           "ShaderNodeSeparateColor", "ShaderNodeOutputMaterial"}


def _grab(me, name):
    import numpy as np
    lay = me.uv_layers[name]
    a = np.empty(len(lay.data) * 2, dtype=np.float32)
    lay.data.foreach_get("uv", a)
    return a


def reorder_uvs(ob):
    """UVTile to index 0, UVMap to index 1, verified exact."""
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
    me.uv_layers.active = me.uv_layers["UVMap"]      # stays the edit layer
    return {
        "object": ob.name,
        "order": [l.name for l in me.uv_layers],
        "moved": moved,
        "identical": all(bool(np.array_equal(before[n], after[n])) for n in before),
        "active_render": next(l.name for l in me.uv_layers if l.active_render),
        "active": me.uv_layers.active.name,
    }


def load_image(fn, non_color):
    path = os.path.join(os.path.dirname(os.path.dirname(bpy.data.filepath)), TEX_DIR, fn)
    img = bpy.data.images.get(fn)
    if img is None:
        img = bpy.data.images.load(path, check_existing=True)
        img.name = fn
    img.colorspace_settings.name = "Non-Color" if non_color else "sRGB"
    img.alpha_mode = "NONE"
    try:
        img.filepath = bpy.path.relpath(path)          # keep the repo relative
    except Exception:
        pass
    return img


def rewire(mat, tex_set):
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
    nmap.uv_map = ""            # empty = the mesh's active render layer (UVTile)

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
