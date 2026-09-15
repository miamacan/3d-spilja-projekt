# G5 - generira atlas listova (alfa maska) i sličicu čestice prašine.
# Pokreće se unutar Blendera. Sprema slike izravno u Godot projekt.

import os, zlib, struct
import numpy as np

PROJ = r"C:\Users\Lovro\Desktop\3d godot dio\new-game-project"
TEX = os.path.join(PROJ, "assets", "textures")


def write_png_rgba(path, arr_u8):
    # ručno zapisuje PNG (RGBA) iz numpy polja, isto kao u b5_textures.py
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
    # generira jedan list: oblik (širina se sužava prema vrhu, s blagim
    # valovitim rubom) + boja (tamnije na sredini/žili, svjetlije na rubu)
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float64)
    u = (xx + 0.5) / size * 2.0 - 1.0
    v = (yy + 0.5) / size * 2.0 - 1.0

    # pozicija duž lista, 0 = dno, 1 = vrh
    t = np.clip((v + length) / (2.0 * length), 0.0, 1.0)
    # profil širine: širi pri dnu, sužava se prema vrhu
    prof = np.sin(np.pi * np.clip(t, 0.0, 1.0) ** 0.75) ** (1.0 / tip)
    margin = 1.0 + lobe_amp * np.sin(t * lobes * np.pi + rng.uniform(0, 6.28))
    half = width * prof * margin

    d = np.abs(u) - half
    # alfa maska - oblik lista, s malo mekim rubom
    alpha = np.clip(-d * (size * 0.22), 0.0, 1.0)
    alpha[t <= 0.001] = 0.0
    alpha[t >= 0.999] = 0.0

    # boja: tamnije pri dnu i na žili, svjetlije prema rubu
    base = np.array([0.13, 0.30, 0.10])
    edge = np.array([0.30, 0.52, 0.18])
    k = np.clip(np.abs(u) / np.maximum(half, 1e-6), 0.0, 1.0)
    col = base[None, None, :] + (edge - base)[None, None, :] * k[:, :, None] ** 1.4
    # središnja žila
    rib = np.exp(-((u / 0.022) ** 2))
    col *= (1.0 - 0.35 * rib)[:, :, None]
    # bočne žile
    veins = np.exp(-((np.abs(u) * 6.0 - (t * 9.0 % 1.0)) ** 2) * 12.0) * (alpha > 0)
    col *= (1.0 - 0.12 * veins)[:, :, None]
    # mala nasumična varijacija boje da dva lista ne budu identična
    col *= rng.uniform(0.88, 1.12)

    out = np.zeros((size, size, 4))
    out[:, :, :3] = np.clip(col, 0.0, 1.0)
    out[:, :, 3] = alpha
    return out


def make_atlas(path, cell=256):
    # spaja dva različita lista u jednu sliku (atlas), jedan lijevo, jedan desno
    a = leaf_cell(cell, seed=3, length=0.86, width=0.40, tip=1.7, lobes=7, lobe_amp=0.05)
    b = leaf_cell(cell, seed=11, length=0.80, width=0.50, tip=2.3, lobes=5, lobe_amp=0.09)
    img = np.concatenate([a, b], axis=1)
    u8 = np.clip(img * 255.0 + 0.5, 0, 255).astype(np.uint8)
    n = write_png_rgba(path, u8)
    cov_a = float((a[:, :, 3] > 0.5).mean())
    cov_b = float((b[:, :, 3] > 0.5).mean())
    return {"bytes": n, "size": list(u8.shape[:2][::-1]),
            "coverage_a": round(cov_a, 3), "coverage_b": round(cov_b, 3)}


def make_mote(path, size=64):
    # mala okrugla, mekana točka - čestica prašine u svjetlosnom snopu
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

    # provjera: list koji je premalo/previše prekriven alfa maskom nije dobar list
    for k in ("coverage_a", "coverage_b"):
        c = out["T_LeafAtlas.png"][k]
        assert 0.12 < c < 0.55, "leaf %s coverage %.3f is out of range" % (k, c)
    assert out["T_Mote.png"]["alpha_corner"] == 0, "mote sprite is not round"
    return out


RESULT = main()
