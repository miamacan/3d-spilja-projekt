"""
G3 — generate the water surface's normal maps and the impact sound.

Runs INSIDE Blender (Blender's Python is the shell on this machine; device_bash
is down). Needs only numpy, which Blender bundles. Writes into the GODOT
project, not the Blender one:

    assets/textures/T_WaterNormal_A.png   512, tiles at 4 m
    assets/textures/T_WaterNormal_B.png   512, tiles at 4 m, different seed
    audio/plop.wav                        16-bit mono 44.1 kHz, ~0.45 s

Idempotent: re-running overwrites the same three files.

The maps are SYNTHESISED on a periodic lattice, exactly like b5_textures.py:
every octave's indices wrap mod L so the tile is seamless by construction
rather than by fighting a bake for it. Each octave gets a phase offset for the
reason b5_textures.py records — with no offset every octave puts a lattice line
on u=0 and v=0 where the fade curve's derivative is zero, which makes the tile
edge measurably FLATTER than its interior and reports a suspiciously good seam
ratio while looking wrong.

`seam_ratio` = mean step across the wrap / mean step in the interior. 1.0 is
indistinguishable. Printed for both maps; do not trust a value far below 1.
"""

import os, sys, zlib, struct, wave, math
import numpy as np

PROJ = r"C:\Users\Lovro\Desktop\3d godot dio\new-game-project"
TEX = os.path.join(PROJ, "assets", "textures")
AUD = os.path.join(PROJ, "audio")


# ---------------------------------------------------------------- png writing

def write_png(path, arr_u8):
    """arr_u8: (h, w, 3) uint8, row 0 = BOTTOM (v=0), flipped on the way out.

    PNG row 0 is the top while a UV v=0 is the bottom. Getting this wrong
    inverts the green channel of every normal map, which reads as light coming
    from the wrong side and is very hard to spot on water.
    """
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


# ---------------------------------------------------------------- noise

def fade(t):
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


def periodic_value_noise(size, period, rng, phase):
    """Value noise on a lattice of `period` cells across `size` pixels, with
    lattice indices wrapped mod period so the result tiles exactly."""
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
    rng = np.random.default_rng(seed)
    h = np.zeros((size, size), dtype=np.float64)
    amp_total = 0.0
    for k, (period, amp) in enumerate(octaves):
        # a phase offset per octave, an exact number of pixels so the period is
        # still exactly `period` cells and the tile stays seamless
        phase = (k + 1) * 0.37 * period / (k + 2)
        h += periodic_value_noise(size, period, rng, phase) * amp
        amp_total += amp
    h /= amp_total
    h -= h.mean()
    return h


def normal_map_from_height(h, target_slope):
    """Central differences with wraparound, so the normal map tiles too.

    The gradient scale is NOT a free constant. Across a 512 px tile whose
    largest lattice cell is 128 px, the per-pixel height step is ~1/128, so any
    hand-picked strength in the single digits leaves nx/ny near zero and the
    blue channel pinned at 255 -- a normal map that encodes a flat surface and
    looks like the shader is broken. Scale off the measured 99th percentile of
    the gradient instead, so `target_slope` means what it says regardless of
    resolution or lattice period."""
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
    """Mean step across the wrap against the mean step in the interior."""
    f = a.astype(np.float64)
    across = (np.abs(f[0, :, :] - f[-1, :, :]).mean()
              + np.abs(f[:, 0, :] - f[:, -1, :]).mean()) * 0.5
    interior = (np.abs(np.diff(f, axis=0)).mean()
                + np.abs(np.diff(f, axis=1)).mean()) * 0.5
    return float(across / max(interior, 1e-9))


# ---------------------------------------------------------------- plop

def make_plop(path, sr=44100):
    """A water plop is a short pitch-DROPPING sine (the bubble cavity closing
    and expanding) plus a click of broadband noise for the surface break.
    A pitch-rising sweep reads as a cartoon 'boing'; the drop is what makes it
    sound wet."""
    dur = 0.45
    n = int(sr * dur)
    t = np.arange(n) / sr

    # cavity tone: 620 Hz falling to 180 Hz over the first 120 ms
    f0, f1, tau = 620.0, 180.0, 0.11
    inst_f = f1 + (f0 - f1) * np.exp(-t / tau)
    phase = 2.0 * np.pi * np.cumsum(inst_f) / sr
    tone = np.sin(phase) * np.exp(-t / 0.13)

    # surface break: filtered noise, very short
    rng = np.random.default_rng(7)
    noise = rng.normal(0.0, 1.0, n)
    k = 24
    noise = np.convolve(noise, np.ones(k) / k, mode="same")   # crude low-pass
    noise *= np.exp(-t / 0.018) * 0.6

    # a little low thump for body
    thump = np.sin(2.0 * np.pi * 95.0 * t) * np.exp(-t / 0.06) * 0.35

    sig = tone + noise + thump
    sig /= np.max(np.abs(sig)) + 1e-9
    sig *= 0.85
    # 5 ms fade out so the tail cannot click
    fade_n = int(sr * 0.005)
    sig[-fade_n:] *= np.linspace(1.0, 0.0, fade_n)

    pcm = (sig * 32767.0).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return n / sr


# ---------------------------------------------------------------- main

def main():
    os.makedirs(TEX, exist_ok=True)
    os.makedirs(AUD, exist_ok=True)
    out = {}

    SIZE = 512
    # The pool is still, so the detail is broad and low-amplitude: big slow
    # swells plus a little fine chop. Feature sizes are in LATTICE CELLS across
    # a tile that the shader maps to 4 m, so period 8 is a ~0.5 m ripple.
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
            # a normal map that actually encodes slope has mean blue well under
            # 1.0 and real spread in R/G; 1.0 means it is flat
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
