"""
G5 — generate the leaf alpha atlas and the dust-mote sprite.

Runs INSIDE Blender. numpy only. Writes into the GODOT project:

    assets/textures/T_LeafAtlas.png   512x256 RGBA, TWO leaf cells
    assets/textures/T_Mote.png        64x64 RGBA, soft radial dot

Idempotent.

THE ATLAS LAYOUT IS NOT FREE. b4_vegetation.py laid the vine leaf cards out for
a two-variant atlas already -- "even cards take u 0-0.5, odd take u 0.5-1" --
so this must be two cells side by side, each self-contained. Each cell holds a
COMPLETE leaf, which also means anything that happens to sample the full 0-1
range (the ferns and tree canopies share M_VineLeaf and their UVs were not laid
out by that script) gets two leaves rather than one broken one.

Alpha is what the whole thing is for: the vines currently render as solid green
scales because M_VineLeaf has no texture at all, which the Blender handoff calls
the most visible unfinished thing in the hero view.
"""

import os, zlib, struct
import numpy as np

PROJ = r"C:\Users\Lovro\Desktop\3d godot dio\new-game-project"
TEX = os.path.join(PROJ, "assets", "textures")


def write_png_rgba(path, arr_u8):
    """arr_u8: (h, w, 4) uint8, row 0 = BOTTOM. Flipped on the way out, same as
    gen_water_assets.py -- PNG row 0 is the top, UV v=0 is the bottom."""
    a = np.flipud(arr_u8)
    h, w, c = a.shape
    assert c == 4
    raw = b"".join(b"\x00" + a[y].tobytes() for y in range(h))

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 6))
           + chunk(b"IEND", b""))
    open(path, "wb").write(png)
    return len(png)


def leaf_cell(size, seed, length=0.86, width=0.40, tip=1.7, lobes=7, lobe_amp=0.05):
    """One leaf, centred, pointing +v. Returns (h, w, 4) float 0..1.

    Shape: a superellipse-ish blade whose half-width tapers to a point, with a
    low-frequency wobble on the margin so the silhouette is not a perfect
    almond, plus a midrib and side veins in the colour channels.
    """
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float64)
    u = (xx + 0.5) / size * 2.0 - 1.0          # -1..1 across
    v = (yy + 0.5) / size * 2.0 - 1.0          # -1..1 up

    # normalised position along the blade, 0 at base, 1 at tip
    t = np.clip((v + length) / (2.0 * length), 0.0, 1.0)
    # half-width profile: fat near the base third, tapering to a point
    prof = np.sin(np.pi * np.clip(t, 0.0, 1.0) ** 0.75) ** (1.0 / tip)
    margin = 1.0 + lobe_amp * np.sin(t * lobes * np.pi + rng.uniform(0, 6.28))
    half = width * prof * margin

    d = np.abs(u) - half
    # a couple of pixels of soft edge, then alpha-scissor does the rest
    alpha = np.clip(-d * (size * 0.22), 0.0, 1.0)
    alpha[t <= 0.001] = 0.0
    alpha[t >= 0.999] = 0.0

    # colour: darker at the base and along the midrib, lighter toward the margin
    base = np.array([0.13, 0.30, 0.10])
    edge = np.array([0.30, 0.52, 0.18])
    k = np.clip(np.abs(u) / np.maximum(half, 1e-6), 0.0, 1.0)
    col = base[None, None, :] + (edge - base)[None, None, :] * k[:, :, None] ** 1.4
    # midrib
    rib = np.exp(-((u / 0.022) ** 2))
    col *= (1.0 - 0.35 * rib)[:, :, None]
    # side veins, angled off the midrib
    veins = np.exp(-((np.abs(u) * 6.0 - (t * 9.0 % 1.0)) ** 2) * 12.0) * (alpha > 0)
    col *= (1.0 - 0.12 * veins)[:, :, None]
    # slight per-leaf value shift so the two cells are not twins
    col *= rng.uniform(0.88, 1.12)

    out = np.zeros((size, size, 4))
    out[:, :, :3] = np.clip(col, 0.0, 1.0)
    out[:, :, 3] = alpha
    return out


def make_atlas(path, cell=256):
    a = leaf_cell(cell, seed=3, length=0.86, width=0.40, tip=1.7, lobes=7, lobe_amp=0.05)
    b = leaf_cell(cell, seed=11, length=0.80, width=0.50, tip=2.3, lobes=5, lobe_amp=0.09)
    img = np.concatenate([a, b], axis=1)          # u 0-0.5 = a, 0.5-1 = b
    u8 = np.clip(img * 255.0 + 0.5, 0, 255).astype(np.uint8)
    n = write_png_rgba(path, u8)
    cov_a = float((a[:, :, 3] > 0.5).mean())
    cov_b = float((b[:, :, 3] > 0.5).mean())
    return {"bytes": n, "size": list(u8.shape[:2][::-1]),
            "coverage_a": round(cov_a, 3), "coverage_b": round(cov_b, 3)}


def make_mote(path, size=64):
    """A soft round dot. Without this the motes are hard squares -- at 2 cm and
    20 m away that reads as sparkling debris rather than dust."""
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float64)
    u = (xx + 0.5) / size * 2.0 - 1.0
    v = (yy + 0.5) / size * 2.0 - 1.0
    r = np.sqrt(u * u + v * v)
    a = np.clip(1.0 - r, 0.0, 1.0) ** 2.2
    out = np.zeros((size, size, 4))
    out[:, :, :3] = 1.0
    out[:, :, 3] = a
    u8 = np.clip(out * 255.0 + 0.5, 0, 255).astype(np.uint8)
    return {"bytes": write_png_rgba(path, u8),
            "alpha_mean": round(float(a.mean()), 4),
            "alpha_corner": int(u8[0, 0, 3])}


def main():
    os.makedirs(TEX, exist_ok=True)
    out = {}
    out["T_LeafAtlas.png"] = make_atlas(os.path.join(TEX, "T_LeafAtlas.png"))
    out["T_Mote.png"] = make_mote(os.path.join(TEX, "T_Mote.png"))
    # a leaf that fills its cell is not a leaf, and one that fills nothing is a
    # hole -- both would pass silently and only show up in a render
    for k in ("coverage_a", "coverage_b"):
        c = out["T_LeafAtlas.png"][k]
        assert 0.12 < c < 0.55, "leaf %s coverage %.3f is out of range" % (k, c)
    assert out["T_Mote.png"]["alpha_corner"] == 0, "mote sprite is not round"
    return out


RESULT = main()
