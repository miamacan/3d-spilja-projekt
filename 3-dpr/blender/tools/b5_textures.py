# Generira teksture koje se ponavljaju bez šava (tileable): stijena i mahovina.
# Umjesto da se teksture ručno crtaju ili peku iz Blenderovog shadera, ovdje se
# matematički (šumom) generiraju base colour, normal i ORM slika za svaku od njih.

import os
import struct
import zlib

import bpy
import numpy as np

RES = 1024
LIMESTONE_TILE_M = 2.0
MOSS_TILE_M = 0.5
SEED = 20260913


def _fade(t):
    # glatka krivulja za interpolaciju šuma (standardni "ease" oblik)
    return t * t * t * (t * (t * 6 - 15) + 10)


def pnoise(res, L, rng, off=None):
    # "periodični" šum - napravljen tako da mu se rubovi savršeno spajaju,
    # pa se tekstura može ponavljati (tile) bez vidljivog šava
    g = rng.random((L, L))
    if off is None:
        off = (rng.random() * L, rng.random() * L)

    def axis(o):
        t = np.arange(res) * (L / res) + o
        ti = np.floor(t).astype(np.int64)
        return ti % L, (ti + 1) % L, _fade(t - ti)

    iy0, iy1, uy = axis(off[1])
    ix0, ix1, ux = axis(off[0])
    a = g[np.ix_(iy0, ix0)]
    b = g[np.ix_(iy0, ix1)]
    c = g[np.ix_(iy1, ix0)]
    d = g[np.ix_(iy1, ix1)]
    top = a + (b - a) * ux[None, :]
    bot = c + (d - c) * ux[None, :]
    return top + (bot - top) * uy[:, None]


def fbm(res, base_L, octaves, roughness, rng, ridged=False):
    # zbraja više slojeva šuma različite gustoće (fractal noise) - daje prirodniji izgled
    out = np.zeros((res, res))
    amp = 1.0
    tot = 0.0
    L = base_L
    for _ in range(octaves):
        n = pnoise(res, L, rng)
        if ridged:
            n = 1.0 - np.abs(2.0 * n - 1.0)
        out += amp * n
        tot += amp
        amp *= roughness
        L *= 2
    return out / tot


def norm01(a):
    # svede vrijednosti u polju na raspon 0-1
    lo, hi = float(a.min()), float(a.max())
    return (a - lo) / (hi - lo) if hi > lo else np.zeros_like(a)


def gblur(a, sigma_px):
    # zamućenje (blur), koristi se za ambient occlusion i za "toplije" mrlje boje
    fy = np.fft.fftfreq(a.shape[0])[:, None]
    fx = np.fft.fftfreq(a.shape[1])[None, :]
    k = np.exp(-2.0 * (np.pi * sigma_px) ** 2 * (fx * fx + fy * fy))
    return np.real(np.fft.ifft2(np.fft.fft2(a) * k))


def smoothstep(e0, e1, x):
    # glatki prijelaz između dvije vrijednosti (kao maska/prag)
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def height_to_normal(h, amp_m, tile_m):
    # pretvara visinsku kartu (height map) u normal mapu - iz nagiba površine
    # izračuna smjer "lažne" normale koju GPU koristi za osvjetljenje
    px = tile_m / h.shape[0]
    hm = h * amp_m
    gx = (np.roll(hm, -1, axis=1) - np.roll(hm, 1, axis=1)) / (2.0 * px)
    gy = (np.roll(hm, -1, axis=0) - np.roll(hm, 1, axis=0)) / (2.0 * px)
    nx, ny, nz = -gx, -gy, np.ones_like(hm)
    ln = np.sqrt(nx * nx + ny * ny + nz * nz)
    return np.stack([nx / ln, ny / ln, nz / ln], axis=-1) * 0.5 + 0.5


def ao_from_height(h, scales=((3.0, 0.9), (9.0, 0.7), (26.0, 0.5)), floor=0.30):
    # računa ambient occlusion (zatamnjenje u udubinama) iz visinske karte
    occ = np.zeros_like(h)
    for sigma, w in scales:
        occ += w * np.clip(gblur(h, sigma) - h, 0.0, None)
    p = float(np.percentile(occ, 98.0))
    occ = np.clip(occ / p, 0.0, 1.0) if p > 0 else occ
    return np.clip(1.0 - (1.0 - floor) * occ, 0.0, 1.0)


def lin2srgb(x):
    # pretvara linearnu boju u sRGB (format u kojem se boje standardno spremaju)
    x = np.clip(x, 0.0, 1.0)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * np.power(x, 1.0 / 2.4) - 0.055)


def write_png(path, arr, srgb):
    # ručno zapisuje PNG datoteku iz numpy polja (bez vanjskih biblioteka)
    a = lin2srgb(arr) if srgb else np.clip(arr, 0.0, 1.0)
    b8 = np.ascontiguousarray(np.flipud(np.rint(a * 255.0)).astype(np.uint8))
    h, w, _ = b8.shape
    raw = b"".join(b"\x00" + b8[y].tobytes() for y in range(h))

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 6))
    png += chunk(b"IEND", b"")
    with open(path, "wb") as fh:
        fh.write(png)
    return os.path.getsize(path)


def seam_ratio(a):
    # provjerava koliko se vidi šav na rubu teksture kad se ponavlja (1.0 = savršeno nevidljivo)
    a = a if a.ndim == 2 else a.mean(axis=-1)
    interior = 0.5 * (np.abs(np.diff(a, axis=1)).mean() + np.abs(np.diff(a, axis=0)).mean())
    seam = 0.5 * (np.abs(a[:, 0] - a[:, -1]).mean() + np.abs(a[0, :] - a[-1, :]).mean())
    return float(seam / interior) if interior > 0 else float("nan")


def limestone(res=RES):
    # generira teksturu vapnenačke stijene: boju, normal mapu i ORM (AO+roughness)
    rng = np.random.default_rng(SEED)
    meso = fbm(res, 2, 4, 0.55, rng)
    detail = fbm(res, 8, 5, 0.60, rng)
    grain = fbm(res, 32, 3, 0.55, rng)
    cracks = fbm(res, 4, 5, 0.62, rng, ridged=True)
    pits = fbm(res, 48, 2, 0.5, rng)

    crack_mask = smoothstep(0.86, 0.99, norm01(cracks))
    pit_mask = smoothstep(0.80, 0.97, norm01(pits))

    h = (0.50 * norm01(meso) + 0.33 * norm01(detail) + 0.17 * norm01(grain)
         - 0.30 * crack_mask - 0.16 * pit_mask)
    h = norm01(h)


    lo = np.array([0.105, 0.098, 0.086])
    hi = np.array([0.215, 0.203, 0.180])
    t = smoothstep(0.18, 0.86, h)[..., None]
    bc = lo + (hi - lo) * t
    bc *= (1.0 - 0.18 * (1.0 - norm01(detail)))[..., None]
    bc *= (1.0 - 0.42 * crack_mask - 0.28 * pit_mask)[..., None]
    bc *= (0.94 + 0.12 * norm01(gblur(meso, 40.0)))[..., None]

    nrm = height_to_normal(h, 0.100, LIMESTONE_TILE_M)
    ao = ao_from_height(h)
    rough = 0.82 + 0.055 * (1.0 - norm01(detail)) - 0.045 * t[..., 0]
    rough = np.clip(rough + 0.05 * crack_mask, 0.60, 0.95)
    orm = np.stack([ao, rough, np.zeros_like(ao)], axis=-1)
    return dict(BC=(bc, True), N=(nrm, False), ORM=(orm, False)), h


def moss(res=RES):
    # generira teksturu mahovine - isti princip kao stijena, samo zelena i sitnija
    rng = np.random.default_rng(SEED + 77)
    clump = fbm(res, 3, 5, 0.58, rng)
    frond = fbm(res, 20, 4, 0.62, rng)
    fine = fbm(res, 64, 2, 0.5, rng)

    h = norm01(0.58 * norm01(clump) + 0.30 * norm01(frond) + 0.12 * norm01(fine))

    lo = np.array([0.018, 0.055, 0.016])
    hi = np.array([0.130, 0.300, 0.075])
    t = smoothstep(0.10, 0.92, h)[..., None]
    bc = lo + (hi - lo) * t
    warm = norm01(gblur(clump, 22.0))[..., None]
    bc *= np.concatenate([0.92 + 0.26 * warm, np.ones_like(warm), 0.88 + 0.10 * warm], axis=-1)

    nrm = height_to_normal(h, 0.022, MOSS_TILE_M)
    ao = ao_from_height(h, scales=((4.0, 1.0), (12.0, 0.8)), floor=0.18)
    rough = np.clip(0.88 + 0.06 * (1.0 - t[..., 0]), 0.0, 1.0)
    orm = np.stack([ao, rough, np.zeros_like(ao)], axis=-1)
    return dict(BC=(bc, True), N=(nrm, False), ORM=(orm, False)), h


def run(res=RES):
    # generira obje teksture (stijena, mahovina) i sprema sve slike na disk
    root = os.path.dirname(os.path.dirname(bpy.data.filepath))
    out = os.path.join(root, "textures")
    os.makedirs(out, exist_ok=True)
    report = {"dir": out, "res": res, "files": {}, "seams": {}, "stats": {}}

    for name, (maps, h) in (("T_Limestone", limestone(res)), ("T_Moss", moss(res))):
        report["seams"][name + "_height"] = round(seam_ratio(h), 4)
        for suffix, (arr, srgb) in maps.items():
            fn = "%s_%s.png" % (name, suffix)
            path = os.path.join(out, fn)
            size = write_png(path, arr, srgb)
            report["files"][fn] = size
            report["seams"][fn] = round(seam_ratio(arr), 4)
            report["stats"][fn] = [round(float(arr[..., c].mean()), 4) for c in range(3)]

    report["total_bytes"] = sum(report["files"].values())
    return report


if __name__ == "__main__":
    print(run())
