# G3 - generira normal mape za površinu vode i zvuk pljuska.
# Pokreće se unutar Blendera. Sprema teksture i zvuk u Godot projekt.
#
# Teksture su generirane na "periodičnoj" mreži - isti princip kao u
# b5_textures.py, tako da se ponavljaju bez šava po konstrukciji.

import os, sys, zlib, struct, wave, math
import numpy as np

PROJ = r"C:\Users\Lovro\Desktop\3d godot dio\new-game-project"
TEX = os.path.join(PROJ, "assets", "textures")
AUD = os.path.join(PROJ, "audio")


def write_png(path, arr_u8):
    # ručno zapisuje PNG (RGB) iz numpy polja
    a = np.flipud(arr_u8)
    h, w, c = a.shape
    assert c == 3
    raw = b"".join(b"\x00" + a[y].tobytes() for y in range(h))

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 6))
           + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)
    return len(png)


def fade(t):
    # glatka krivulja za interpolaciju šuma
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


def periodic_value_noise(size, period, rng, phase):
    # periodični šum - rubovi se savršeno spajaju, pa tekstura nema šav
    g = rng.random((period, period)).astype(np.float64)

    u = (np.arange(size) / size * period + phase) % period
    i0 = np.floor(u).astype(np.int64) % period
    i1 = (i0 + 1) % period
    tf = fade(u - np.floor(u))

    x0, x1, tx = i0[None, :], i1[None, :], tf[None, :]
    y0, y1, ty = i0[:, None], i1[:, None], tf[:, None]

    n00 = g[y0, x0]; n10 = g[y0, x1]
    n01 = g[y1, x0]; n11 = g[y1, x1]
    a = n00 + (n10 - n00) * tx
    b = n01 + (n11 - n01) * tx
    return a + (b - a) * ty


def height_field(size, seed, octaves):
    # zbraja više slojeva šuma (fractal noise) u jednu visinsku kartu
    rng = np.random.default_rng(seed)
    h = np.zeros((size, size), dtype=np.float64)
    amp_total = 0.0
    for k, (period, amp) in enumerate(octaves):
        # pomak faze po sloju, da rub teksture ne izađe "prelagan" (previše ravan)
        phase = (k + 1) * 0.37 * period / (k + 2)
        h += periodic_value_noise(size, period, rng, phase) * amp
        amp_total += amp
    h /= amp_total
    h -= h.mean()
    return h


def normal_map_from_height(h, target_slope):
    # pretvara visinsku kartu u normal mapu (isti princip kao b5_textures.py)
    dx = (np.roll(h, -1, axis=1) - np.roll(h, 1, axis=1)) * 0.5
    dy = (np.roll(h, -1, axis=0) - np.roll(h, 1, axis=0)) * 0.5
    ref = np.percentile(np.abs(np.concatenate([dx.ravel(), dy.ravel()])), 99.0)
    strength = target_slope / max(ref, 1e-9)
    nx = -dx * strength
    ny = -dy * strength
    nz = np.ones_like(h)
    inv = 1.0 / np.sqrt(nx * nx + ny * ny + nz * nz)
    nx *= inv; ny *= inv; nz *= inv
    rgb = np.stack([nx * 0.5 + 0.5, ny * 0.5 + 0.5, nz * 0.5 + 0.5], axis=-1)
    return np.clip(rgb * 255.0 + 0.5, 0, 255).astype(np.uint8)


def seam_ratio(a):
    # provjerava koliko se vidi šav na rubu teksture kad se ponavlja
    f = a.astype(np.float64)
    across = (np.abs(f[0, :, :] - f[-1, :, :]).mean()
              + np.abs(f[:, 0, :] - f[:, -1, :]).mean()) * 0.5
    interior = (np.abs(np.diff(f, axis=0)).mean()
                + np.abs(np.diff(f, axis=1)).mean()) * 0.5
    return float(across / max(interior, 1e-9))


def make_plop(path, sr=44100):
    # zvuk "plop" - ton koji PADA u visini (kao mjehur koji se zatvara),
    # + kratki šum za sam prasak na površini + tup zvuk za "tijelo"
    dur = 0.45
    n = int(sr * dur)
    t = np.arange(n) / sr

    # ton koji pada s 620 Hz na 180 Hz u prvih 120 ms
    f0, f1, tau = 620.0, 180.0, 0.11
    inst_f = f1 + (f0 - f1) * np.exp(-t / tau)
    phase = 2.0 * np.pi * np.cumsum(inst_f) / sr
    tone = np.sin(phase) * np.exp(-t / 0.13)

    # prasak na površini: filtrirani šum, kratak
    rng = np.random.default_rng(7)
    noise = rng.normal(0.0, 1.0, n)
    k = 24
    noise = np.convolve(noise, np.ones(k) / k, mode="same")
    noise *= np.exp(-t / 0.018) * 0.6

    # mali dubok "tup" za tijelo zvuka
    thump = np.sin(2.0 * np.pi * 95.0 * t) * np.exp(-t / 0.06) * 0.35

    sig = tone + noise + thump
    sig /= np.max(np.abs(sig)) + 1e-9
    sig *= 0.85
    # 5 ms izlazni fade da se zvuk ne "reže" na kraju
    fade_n = int(sr * 0.005)
    sig[-fade_n:] *= np.linspace(1.0, 0.0, fade_n)

    pcm = (sig * 32767.0).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return n / sr


def main():
    os.makedirs(TEX, exist_ok=True)
    os.makedirs(AUD, exist_ok=True)
    out = {}

    SIZE = 512
    # jezero je mirno - veliki, blagi valovi + malo finog detalja
    specs = [
        ("T_WaterNormal_A.png", 1771, [(4, 1.0), (8, 0.5), (16, 0.25), (32, 0.12)], 0.45),
        ("T_WaterNormal_B.png", 9043, [(6, 1.0), (12, 0.45), (24, 0.2), (48, 0.1)], 0.35),
    ]
    for name, seed, octaves, target_slope in specs:
        h = height_field(SIZE, seed, octaves)
        nm = normal_map_from_height(h, target_slope)
        p = os.path.join(TEX, name)
        nbytes = write_png(p, nm)
        out[name] = {
            "bytes": nbytes,
            "seam_ratio": round(seam_ratio(nm), 3),
            "mean_b": round(float(nm[:, :, 2].mean()) / 255.0, 4),
            # provjera da normal mapa stvarno ima nagib, ne da je posve ravna
            "std_r": round(float(nm[:, :, 0].std()) / 255.0, 4),
            "std_g": round(float(nm[:, :, 1].std()) / 255.0, 4),
        }
        assert out[name]["mean_b"] < 0.995, "%s encodes a flat surface" % name
        assert out[name]["std_r"] > 0.02, "%s has no slope in R" % name

    wav = os.path.join(AUD, "plop.wav")
    out["plop.wav"] = {"seconds": round(make_plop(wav), 3),
                       "bytes": os.path.getsize(wav)}
    return out


RESULT = main()
