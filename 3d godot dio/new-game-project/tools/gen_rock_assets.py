"""
G4 — generate the stone-on-stone impact sounds.

Runs INSIDE Blender (Blender's Python is the shell on this machine). numpy only.
Writes into the GODOT project:

    audio/stone_click_1.wav
    audio/stone_click_2.wav
    audio/stone_click_3.wav

Three variants, not one. A thrown rock bounces several times in quick
succession, and one sample retriggered reads as a machine gun -- rock.gd picks a
variant at random per impact and also jitters pitch.

Idempotent: re-running overwrites the same three files.

What a stone click actually is: two hard, dense, INHARMONIC bodies striking.
So the recipe is a very short broadband transient for the strike itself, plus a
few damped partials at deliberately non-integer ratios for the "stoniness". Use
harmonic partials instead and it rings like a bell or a woodblock; make the
decay longer than ~80 ms and it turns into a clack of plastic.
"""

import os, wave
import numpy as np

PROJ = r"C:\Users\Lovro\Desktop\3d godot dio\new-game-project"
AUD = os.path.join(PROJ, "audio")


def write_wav(path, sig, sr=44100):
    sig = np.asarray(sig, dtype=np.float64)
    peak = float(np.max(np.abs(sig)))
    if peak > 0.0:
        sig = sig / peak * 0.9
    n = len(sig)
    fade = max(1, int(sr * 0.004))
    sig[-fade:] *= np.linspace(1.0, 0.0, fade)
    pcm = (sig * 32767.0).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return n / sr


def one_pole_highpass(x, sr, fc):
    a = np.exp(-2.0 * np.pi * fc / sr)
    y = np.empty_like(x)
    prev_x = 0.0
    prev_y = 0.0
    for i in range(len(x)):
        y[i] = a * (prev_y + x[i] - prev_x)
        prev_x = x[i]
        prev_y = y[i]
    return y


def stone_click(seed, partials, decays, strike_ms, sr=44100, dur=0.14):
    rng = np.random.default_rng(seed)
    n = int(sr * dur)
    t = np.arange(n) / sr

    # the strike: broadband, very short, high-passed so it reads as a click
    noise = rng.normal(0.0, 1.0, n)
    noise = one_pole_highpass(noise, sr, 900.0)
    noise *= np.exp(-t / (strike_ms / 1000.0))

    # the body: inharmonic damped partials
    body = np.zeros(n)
    for f, d, amp in zip(partials, decays, [1.0, 0.62, 0.38, 0.22]):
        body += amp * np.sin(2.0 * np.pi * f * t) * np.exp(-t / d)

    sig = 0.75 * noise + 0.55 * body
    return sig


def main():
    os.makedirs(AUD, exist_ok=True)
    out = {}
    # deliberately non-integer frequency ratios -- see the module docstring
    specs = [
        (11, [1630.0, 2780.0, 4390.0, 6110.0], [0.030, 0.022, 0.014, 0.009], 4.5),
        (29, [1980.0, 3310.0, 5020.0, 7240.0], [0.026, 0.018, 0.012, 0.008], 3.8),
        (47, [1340.0, 2410.0, 3870.0, 5530.0], [0.038, 0.027, 0.017, 0.010], 5.5),
    ]
    for i, (seed, partials, decays, strike_ms) in enumerate(specs, start=1):
        sig = stone_click(seed, partials, decays, strike_ms)
        p = os.path.join(AUD, "stone_click_%d.wav" % i)
        secs = write_wav(p, sig)
        # a click that is not actually short is the failure mode worth catching:
        # measure where 90% of the energy has decayed
        e = np.cumsum(sig ** 2)
        e /= e[-1]
        t90 = float(np.searchsorted(e, 0.9)) / 44100.0
        out["stone_click_%d.wav" % i] = {
            "seconds": round(secs, 3),
            "bytes": os.path.getsize(p),
            "t90_ms": round(t90 * 1000.0, 1),
        }
        assert t90 < 0.060, "stone_click_%d rings for %.0f ms, too long" % (i, t90 * 1000)
    return out


RESULT = main()
