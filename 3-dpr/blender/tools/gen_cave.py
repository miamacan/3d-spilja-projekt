# Generator geometrije špilje (blockout + detalji + ulaz). Ne pokreće se u Blenderu,
# nego zasebno (treba scipy/skimage) - rezultat su .ply mreže koje se zatim uvezu u Blender.
# Koristi tehniku "signed distance field" + marching cubes: prostor se opiše
# matematičkom funkcijom (gdje je "unutra" a gdje "vani"), pa se iz nje izvuče mreža.

import numpy as np
from scipy import ndimage
from skimage import measure
import os

OUT = "/mnt/user-data/outputs"
os.makedirs(OUT, exist_ok=True)

# os špilje (XY) i ključne visine
AX, AY = 0.5, 1.0
BED_AXIS, BED_WALL = -3.6, -2.0
FLOOR = 5.50


def sstep(e0, e1, x):
    # glatki prijelaz (smoothstep) između dvije vrijednosti
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def smin(a, b, k):
    # "meki" minimum - spaja dva oblika glatko umjesto oštrim rubom
    h = np.clip(0.5 + 0.5 * (b - a) / k, 0.0, 1.0)
    return b * (1.0 - h) + a * h - k * h * (1.0 - h)


def smax(a, b, k):
    # "meki" maksimum (isto kao smin, samo obrnuto)
    return -smin(-a, -b, k)


def prof(z, pts):
    # linearna interpolacija profila (radijus u ovisnosti o visini)
    zs = np.array([p[0] for p in pts], dtype=np.float32)
    rs = np.array([p[1] for p in pts], dtype=np.float32)
    return np.interp(z, zs, rs).astype(np.float32)


_cc = {}


def noise3(shape, cell_m, seed, vox):
    # 3D šum određene "krupnoće" (cell_m u metrima), za dodavanje neravnina
    cell_vox = cell_m / vox
    rng = np.random.default_rng(seed)
    small = tuple(int(np.ceil(s / cell_vox)) + 4 for s in shape)
    base = rng.standard_normal(small).astype(np.float32)
    key = (shape, cell_vox)
    if key not in _cc:
        _cc[key] = np.array(np.meshgrid(
            *[np.arange(s, dtype=np.float32) / cell_vox + 1.5 for s in shape],
            indexing="ij"))
    out = ndimage.map_coordinates(base, _cc[key], order=3,
                                  mode="nearest").astype(np.float32)
    return out / (out.std() + 1e-6)


def noise3a(shape, cells_m, seed, vox):
    # kao noise3, ali "anizotropni" - različita krupnoća po X/Y/Z (npr. rastegnuto
    # po visini da nastanu vertikalne pruge kakve ima pravi vapnenac)
    cv = [c / vox for c in cells_m]
    rng = np.random.default_rng(seed)
    small = tuple(int(np.ceil(s / c)) + 4 for s, c in zip(shape, cv))
    base = rng.standard_normal(small).astype(np.float32)
    coords = np.array(np.meshgrid(
        *[np.arange(s, dtype=np.float32) / c + 1.5 for s, c in zip(shape, cv)],
        indexing="ij"))
    out = ndimage.map_coordinates(base, coords, order=3,
                                  mode="nearest").astype(np.float32)
    return out / (out.std() + 1e-6)


def capsule(px, py, pz, a, b):
    # udaljenost svake točke od "kapsule" (linija a-b s debljinom) - koristi se za tunele
    ax, ay, az = a
    dx, dy, dz = b[0] - ax, b[1] - ay, b[2] - az
    ll = dx * dx + dy * dy + dz * dz
    t = np.clip(((px - ax) * dx + (py - ay) * dy + (pz - az) * dz) / ll, 0.0, 1.0)
    return np.sqrt((px - ax - t * dx) ** 2 + (py - ay - t * dy) ** 2
                   + (pz - az - t * dz) ** 2)


def polyline_xy(gx, gy, pts, samples=220):
    # za svaku točku na mreži (grid): udaljenost od zadane krivulje (u XY ravnini),
    # plus na kojem mjestu duž krivulje i kolika je tamo visina - koristi se za stazu/tunel
    P = np.asarray(pts, dtype=np.float32)
    key = np.linspace(0.0, 1.0, len(P))
    tt = np.linspace(0.0, 1.0, samples)
    sx = np.interp(tt, key, P[:, 0]).astype(np.float32)
    sy = np.interp(tt, key, P[:, 1]).astype(np.float32)
    sz = (np.interp(tt, key, P[:, 2]).astype(np.float32)
          if P.shape[1] > 2 else np.zeros_like(sx))
    dh = np.full(gx.shape, 1e9, dtype=np.float32)
    tn = np.zeros(gx.shape, dtype=np.float32)
    zl = np.zeros(gx.shape, dtype=np.float32)
    cx = np.zeros(gx.shape, dtype=np.float32)
    for i in range(samples):
        dd = np.sqrt((gx - sx[i]) ** 2 + (gy - sy[i]) ** 2)
        m = dd < dh
        dh = np.where(m, dd, dh)
        tn = np.where(m, np.float32(tt[i]), tn)
        zl = np.where(m, sz[i], zl)
        cx = np.where(m, sx[i], cx)
    return dh, tn, zl, cx


def write_ply(path, verts, faces, normals=None):
    # sprema mrežu (vrhovi + trokuti) u binarni .ply format
    n, m = len(verts), len(faces)
    hdr = ["ply", "format binary_little_endian 1.0",
           "comment cave.blend B2 detail pass",
           f"element vertex {n}",
           "property float x", "property float y", "property float z"]
    if normals is not None:
        hdr += ["property float nx", "property float ny", "property float nz"]
    hdr += [f"element face {m}",
            "property list uchar int vertex_indices", "end_header", ""]
    cols = 6 if normals is not None else 3
    vt = np.empty((n, cols), dtype="<f4")
    vt[:, 0:3] = verts
    if normals is not None:
        vt[:, 3:6] = normals
    ft = np.empty(m, dtype=[("c", "u1"), ("i", "<i4", 3)])
    ft["c"] = 3
    ft["i"] = faces
    with open(path, "wb") as f:
        f.write("\n".join(hdr).encode())
        f.write(vt.tobytes())
        f.write(ft.tobytes())


def march(field, origin, vox, open_faces=()):
    # zatvori rubove 3D polja (osim traženih strana) i izvuče mrežu iz njega
    # (marching cubes - standardni algoritam za pretvaranje polja brojeva u 3D oblik)
    if "x0" not in open_faces: field[0, :, :] = 5.0
    if "x1" not in open_faces: field[-1, :, :] = 5.0
    if "y0" not in open_faces: field[:, 0, :] = 5.0
    if "y1" not in open_faces: field[:, -1, :] = 5.0
    if "z0" not in open_faces: field[:, :, 0] = 5.0
    if "z1" not in open_faces: field[:, :, -1] = 5.0
    v, f, nrm, _ = measure.marching_cubes(field, level=0.0,
                                          spacing=(vox, vox, vox),
                                          gradient_direction="descent")
    return (v.astype(np.float32) + np.array(origin, dtype=np.float32),
            f.astype(np.int32), nrm.astype(np.float32))


VOX = float(os.environ.get("VOX", 0.285))

# ============================================================
# 1. GLAVNA KOMORA ŠPILJE (CAVE_Shell_Main)
# ============================================================
SKY_MASK = 1.0 - float(os.environ.get("SKY_RIM", 0.30))
ox, oy, oz = -13.0, -21.0, -5.0
hx, hy, hz = 18.0, 16.0, 30.5
nx = int(round((hx - ox) / VOX)) + 1
ny = int(round((hy - oy) / VOX)) + 1
nz = int(round((hz - oz) / VOX)) + 1
shape = (nx, ny, nz)
print("shell grid", shape, "=", round(np.prod(shape) / 1e6, 2), "M voxels")

X = (ox + np.arange(nx, dtype=np.float32) * VOX)[:, None, None]
Y = (oy + np.arange(ny, dtype=np.float32) * VOX)[None, :, None]
Z = (oz + np.arange(nz, dtype=np.float32) * VOX)[None, None, :]
gx = (ox + np.arange(nx, dtype=np.float32) * VOX)[:, None] + np.zeros((nx, ny), np.float32)
gy = (oy + np.arange(ny, dtype=np.float32) * VOX)[None, :] + np.zeros((nx, ny), np.float32)


CHAMBER = [(-5.0, 7.0), (-4.0, 8.5), (-2.0, 10.5), (0.0, 11.8), (2.0, 12.6),
           (5.0, 13.0), (8.0, 13.0), (11.0, 12.7), (14.0, 12.0), (17.0, 11.0),
           (20.0, 9.6), (23.0, 7.8), (25.5, 5.6), (27.0, 3.6), (28.0, 1.6),
           (28.4, 0.2),


           (29.0, -2.0), (31.0, -3.0)]
rho = np.sqrt((X - AX) ** 2 + (Y - AY) ** 2)
d = rho - prof(Z, CHAMBER)

bed = BED_AXIS + (BED_WALL - BED_AXIS) * np.clip(rho / 13.0, 0.0, 1.0) ** 2
d = smax(d, bed - Z, 1.1)
del bed


THROAT = [(0.0, -11.6, 0.0), (0.1, -15.0, 0.0), (2.3, -16.8, 0.0),
          (0.9, -18.6, 0.0), (-0.5, -21.0, 0.0)]
dh_t, t_t, _, _ = polyline_xy(gx, gy, THROAT)
HW, HH, CR = 1.75, 2.00, 0.80
qx = dh_t[:, :, None] - (HW - CR)
qz = np.abs(Z - (FLOOR + HH)) - (HH - CR)
d_tun = (np.sqrt(np.maximum(qx, 0.0) ** 2 + np.maximum(qz, 0.0) ** 2)
         + np.minimum(np.maximum(qx, qz), 0.0) - CR)
d = smin(d, d_tun, 1.9)
del qx, qz


d = smin(d, capsule(X, Y, Z, (5.0, 6.0, 1.5), (13.0, 12.0, 1.0)) - 4.0, 1.8)


scx = -2.0 - 0.10 * (Z - 24.0)
scy = 6.0 + 0.24 * (Z - 24.0)
d_sky = np.sqrt(((X - scx) / 1.0) ** 2 + ((Y - scy) / 1.5) ** 2) - 2.0
d = smin(d, smax(d_sky, 24.0 - Z, 0.8), 1.9)
del scx, scy, d_sky


LEFT = [(-5.0, 0.6), (0.0, 0.9), (2.0, 1.4), (4.0, 2.8), (6.0, 4.2),


        (9.0, 4.3), (12.0, 4.2), (16.0, 3.0), (19.0, 1.5), (22.0, 0.4),
        (31.0, 0.1)]
d_bl = np.sqrt(((X + 9.2) / 1.0) ** 2 + ((Y + 8.4) / 1.45) ** 2) - prof(Z, LEFT)
d = smax(d, -d_bl, 1.4)
del d_bl


RIGHT = [(-5.0, 1.0), (0.0, 2.0), (3.0, 2.8), (7.0, 3.5), (12.0, 3.0),
         (16.0, 1.8), (19.0, 0.5), (31.0, 0.1)]
d_br = np.sqrt(((X - 9.4) / 1.0) ** 2 + ((Y + 7.0) / 1.30) ** 2) - prof(Z, RIGHT)
d = smax(d, -d_br, 1.3)
del d_br


RAMP = [(-0.6, -11.40, 5.50), (-1.8, -11.25, 5.35), (-3.0, -11.00, 4.70),
        (-4.4, -10.30, 3.75), (-5.7, -9.20, 2.80), (-6.5, -7.60, 1.85),
        (-6.9, -5.80, 0.95), (-6.8, -4.00, 0.35)]
dh_r, t_r, z_r, _ = polyline_xy(gx, gy, RAMP)
dh_r = dh_r[:, :, None]; t_r = t_r[:, :, None]; z_r = z_r[:, :, None]
W_r = 1.30 + 1.70 * sstep(0.82, 1.0, t_r)
surf = np.where(t_r > 0.95, np.float32(0.35), z_r)
d_ramp = smax(dh_r - W_r, Z - surf, 0.45)
d = smax(d, -d_ramp, 0.5)
del t_r, z_r, W_r


amp = ((0.35 + 0.65 * sstep(-13.0, -7.0, Y))
       * (1.0 - SKY_MASK * sstep(22.0, 27.0, Z)))


amp = amp * (1.0 - 0.80
             * (1.0 - sstep(1.7, 3.4, dh_r))
             * (1.0 - sstep(3.0, 5.5, np.abs(Z - surf))))


amp = amp * (1.0 - 0.80
             * (1.0 - sstep(2.0, 3.8, dh_t[:, :, None]))
             * (1.0 - sstep(2.6, 4.6, np.abs(Z - FLOOR))))


large = 0.55 * noise3(shape, 12.0, 26, VOX)


lumps = (0.90 * noise3(shape, 7.5, 21, VOX)
         + 0.40 * noise3(shape, 3.0, 22, VOX)
         + 0.22 * noise3(shape, 1.25, 23, VOX)
         + 0.09 * noise3(shape, 0.70, 24, VOX))


bedwob = noise3a(shape, (18.0, 18.0, 7.0), 13, VOX)
strat = (0.20 * np.sin((Z + 0.55 * bedwob) * 3.10
                       + 0.50 * noise3(shape, 6.5, 11, VOX))
         + 0.11 * np.sin((Z + 0.35 * bedwob) * 7.30 + 1.30)
         + 0.05 * np.sin((Z + 0.20 * bedwob) * 15.0 + 2.70)
         + 0.16 * noise3a(shape, (12.0, 12.0, 3.0), 14, VOX))
del bedwob

strat *= 0.30 + 0.95 * np.clip(noise3(shape, 9.0, 12, VOX) * 0.5 + 0.5, 0, 1)


flutes = (0.30 * noise3a(shape, (2.2, 2.2, 9.0), 41, VOX)
          + 0.14 * noise3a(shape, (1.0, 1.0, 4.0), 42, VOX))

d += amp * (large + lumps + strat + flutes)
del amp, large, lumps, strat, flutes


d = smin(d, d_tun, 0.35)


slab = np.maximum(dh_t[:, :, None] - (HW + 0.45), Z - FLOOR)
slab_on = sstep(0.0, 0.14, t_t[:, :, None])
d = smax(d, -slab - 10.0 * (1.0 - slab_on), 0.30)
d = smax(d, -d_ramp, 0.25)
del slab, slab_on, t_t, dh_t


d_head = np.maximum(np.maximum(dh_r - 1.15, (surf + 0.15) - Z),
                    Z - (surf + 2.55))
d = smin(d, d_head, 0.35)
del d_tun, d_ramp, dh_r, surf, d_head

def at(px, py, pz):
    return float(d[int(round((px - ox) / VOX)),
                   int(round((py - oy) / VOX)),
                   int(round((pz - oz) / VOX))])

print("  CAM_Hero (0,-14,7.2)      ", round(at(0, -14, 7.2), 2), "(<0 = open air)")
print("  tunnel mid (0.1,-15,7.2)  ", round(at(0.1, -15, 7.2), 2), "(<0)")
print("  beach (-5.6,-4.6,0.7)     ", round(at(-5.6, -4.6, 0.7), 2), "(<0 open above beach)")
print("  under beach (-5.6,-4.6,0.0)", round(at(-5.6, -4.6, 0.0), 2), "(>0 = solid)")


def route_check(name, pts, z_lo, z_hi, step=0.35):
    P = np.asarray(pts, dtype=np.float32)
    seg = np.sqrt(((P[1:, :2] - P[:-1, :2]) ** 2).sum(1))
    total = float(seg.sum())
    n = max(int(total / step), 2)
    key = np.concatenate([[0.0], np.cumsum(seg)]) / total
    tt = np.linspace(0.0, 1.0, n)
    px = np.interp(tt, key, P[:, 0])
    py = np.interp(tt, key, P[:, 1])
    zs = np.arange(z_lo, z_hi, 0.05)
    floors, heads, lost = [], [], 0
    for a, b in zip(px, py):
        col = np.array([at(a, b, z) for z in zs])
        air = col < 0.0
        idx = np.where(air[:-1] & ~air[1:])[0]
        below = np.where(~air)[0]
        if not air.any() or not below.any():
            floors.append(np.nan); heads.append(np.nan); lost += 1; continue

        cand = [i for i in below if i + 1 < len(col) and air[i + 1]]
        if not cand:
            floors.append(np.nan); heads.append(np.nan); lost += 1; continue
        fi = cand[-1] if len(idx) == 0 else cand[0]
        for i in cand:
            top = i + 1
            while top < len(col) and air[top]:
                top += 1
            if (top - i - 1) * 0.05 >= 1.80:
                fi = i
                break
        top = fi + 1
        while top < len(col) and air[top]:
            top += 1
        floors.append(float(zs[fi]))
        heads.append(float((top - fi - 1) * 0.05))
    fl = np.array(floors)
    hd = np.array(heads)
    ok = ~np.isnan(fl)
    d_xy = np.sqrt(np.diff(px) ** 2 + np.diff(py) ** 2)
    both = ok[:-1] & ok[1:]
    slope = np.degrees(np.arctan2(np.abs(np.diff(fl))[both], d_xy[both]))
    print(f"  route {name}: {n} samples, {lost} with no floor"
          f" | floor {np.nanmin(fl):.2f}..{np.nanmax(fl):.2f}"
          f" | max slope {slope.max():.1f} deg ({(slope > 40).sum()} over 40)"
          f" | min headroom {np.nanmin(hd):.2f} m")
    return lost, (slope.max() if slope.size else 0.0), np.nanmin(hd)


route_check("throat", [p[:2] for p in THROAT][::-1], 5.0, 10.5)
route_check("ramp+beach", [p[:2] for p in RAMP], -0.5, 7.5)


sky = d[:, :, -1] < 0.0
if sky.any():


    lab, ncomp = ndimage.label(sky)
    print(f"  skylight: {ncomp} separate opening(s) on the top slice"
          + ("  <-- MORE THAN ONE, the dome has been punched through"
             if ncomp > 1 else ""))
    for c in range(1, ncomp + 1):
        sxi, syi = np.where(lab == c)
        sw = (sxi.max() - sxi.min() + 1) * VOX
        sl = (syi.max() - syi.min() + 1) * VOX
        print(f"    #{c}: {sw:.2f} x {sl:.2f} m at "
              f"({ox + sxi.mean() * VOX:.2f}, {oy + syi.mean() * VOX:.2f})"
              f"  area {len(sxi) * VOX * VOX:.1f} m2   [target 4 x 6]")
else:
    print("  skylight opening: NONE -- the dome closed over, check SKY_RIM")

v, f, nrm = march(d, (ox, oy, oz), VOX, open_faces=("y0", "z1"))
print("shell:", len(v), "verts", len(f), "tris", "  budget 150000")
print("  bbox", v.min(0).round(2), v.max(0).round(2))
write_ply(f"{OUT}/CAVE_Shell_Main.ply", v, f, nrm)
del d, v, f, nrm

# ============================================================
# 2. VELIKA STIJENA / IZBOČINA (LEDGE_Outcrop)
# ============================================================
VOX2 = float(os.environ.get("VOX2", 0.126))
o2 = (-6.0, -14.0, -5.0)
h2 = (4.0, -3.0, 7.0)
n2 = tuple(int(round((h2[i] - o2[i]) / VOX2)) + 1 for i in range(3))
print("outcrop grid", n2, "=", round(np.prod(n2) / 1e6, 2), "M voxels")

X2 = (o2[0] + np.arange(n2[0], dtype=np.float32) * VOX2)[:, None, None]
Y2 = (o2[1] + np.arange(n2[1], dtype=np.float32) * VOX2)[None, :, None]
Z2 = (o2[2] + np.arange(n2[2], dtype=np.float32) * VOX2)[None, None, :]
g2x = (o2[0] + np.arange(n2[0], dtype=np.float32) * VOX2)[:, None] + np.zeros(n2[:2], np.float32)
g2y = (o2[1] + np.arange(n2[1], dtype=np.float32) * VOX2)[None, :] + np.zeros(n2[:2], np.float32)

SPINE = [(0.2, -12.8, 0.0), (-0.5, -10.8, 0.0), (-1.2, -8.8, 0.0),
         (-1.8, -6.8, 0.0), (-2.25, -5.0, 0.0), (-2.5, -3.9, 0.0)]
dh, tn, _, _ = polyline_xy(g2x, g2y, SPINE)
dh = dh[:, :, None]; tn = tn[:, :, None]


z_top = 5.22 + 0.45 * sstep(0.50, 1.00, tn) - 0.05 * np.sin(tn * 7.0)


PAD_XY = (-2.2, -5.0)


PAD_Z = 5.609
r_pad = np.sqrt((g2x - PAD_XY[0]) ** 2 + (g2y - PAD_XY[1]) ** 2)
pad = (1.0 - sstep(0.50, 1.05, r_pad))[:, :, None]
quiet = 1.0 - 0.94 * pad


BUMPS = [(-2.75, -3.95, 0.30, 0.10), (-1.95, -6.15, 0.26, 0.09),
         (-2.60, -6.30, 0.22, 0.11), (-1.55, -7.35, 0.32, 0.10),
         (-1.15, -8.60, 0.28, 0.08)]
bump = np.zeros(n2[:2], np.float32)
for bx, by, br, bh in BUMPS:
    bump += bh * np.exp(-(((g2x - bx) ** 2 + (g2y - by) ** 2) / (br * br)))
z_top = z_top + bump[:, :, None] * (1.0 - pad)
z_top = z_top * (1.0 - pad) + PAD_Z * pad

W = 0.90
drop = np.maximum(z_top - Z2, 0.0)


width = (W + 0.62 * np.minimum(drop, 1.6)
         + 0.20 * np.clip(drop - 1.6, 0.0, 3.6)
         + 0.14 * np.maximum(drop - 5.2, 0.0))


ovar = 0.50 + 0.50 * np.clip(
    noise3a(n2, (3.2, 3.2, 11.0), 38, VOX2) * 0.55 + 0.5, 0.0, 1.0)
width = width + ovar * (0.55 * np.exp(-((Z2 - 0.85) / 1.05) ** 2)
                        - 0.42 * np.exp(-((Z2 + 0.55) / 0.70) ** 2))
del ovar

d_r = smax(dh - width, Z2 - z_top, 0.50)
d_r = smax(d_r, Y2 + 3.90, 0.60)
d_r = smax(d_r, -13.20 - Y2, 0.60)
flank = sstep(0.80, 2.10, dh)
del dh, tn, z_top, W, drop, width


amp2 = (0.10 + 0.68 * sstep(6.0, 1.0, Z2)) * quiet
fine2 = (0.12 + 0.66 * np.maximum(sstep(6.0, 1.0, Z2), flank)) * quiet
d_r += amp2 * (0.52 * noise3(n2, 4.2, 31, VOX2)
               + 0.24 * noise3(n2, 1.75, 32, VOX2))
d_r += fine2 * (0.08 * noise3(n2, 0.72, 33, VOX2)
                + 0.03 * noise3(n2, 0.42, 34, VOX2)
                + 0.030 * noise3(n2, 0.40, 39, VOX2))


bw2 = noise3a(n2, (9.0, 9.0, 4.0), 35, VOX2)
beds2 = (0.58 * noise3a(n2, (8.0, 8.0, 2.0), 36, VOX2)
         + 0.30 * np.sin((Z2 + 0.70 * bw2) * 2.55)
         + 0.14 * np.sin((Z2 + 0.45 * bw2) * 5.90 + 1.30)


         + 0.07 * np.sin((Z2 + 0.30 * bw2) * 12.00 + 0.60))
del bw2


bmask = (0.12 + 0.88 * np.maximum(sstep(5.40, 3.20, Z2), flank)) * quiet
gmask = (0.20 + 0.80 * np.maximum(sstep(5.40, 3.20, Z2), flank)) * quiet
d_r += 0.34 * beds2 * bmask
d_r += 0.05 * noise3(n2, 0.50, 37, VOX2) * gmask
d_r += 0.028 * noise3(n2, 0.40, 43, VOX2) * gmask
del amp2, fine2, beds2, bmask, gmask, quiet, pad, flank

v2, f2, nr2 = march(d_r, o2, VOX2)
nr2 = -nr2
f2 = f2[:, ::-1].copy()
print("outcrop:", len(v2), "verts", len(f2), "tris")
print("  bbox", v2.min(0).round(2), v2.max(0).round(2))
sel = (np.abs(v2[:, 0] + 2.2) < 1.0) & (np.abs(v2[:, 1] + 5.0) < 1.0)
if sel.any():
    print("  stage top Z near (-2.2,-5):", round(float(v2[sel, 2].max()), 3),
          "  [B2 read 5.609 -- hold this, the hero composition keys off it]")


rp = np.sqrt((v2[:, 0] - PAD_XY[0]) ** 2 + (v2[:, 1] - PAD_XY[1]) ** 2)
top = (rp < 0.45) & (v2[:, 2] > 5.0)
if top.any():
    zs = v2[top, 2]
    print(f"  standing pad r<0.45: {top.sum()} verts, Z {zs.min():.3f}"
          f"..{zs.max():.3f}, spread {np.ptp(zs) * 1000:.0f} mm")


sx = np.interp(np.linspace(0, 1, 64), np.linspace(0, 1, len(SPINE)),
               [p[0] for p in SPINE]).astype(np.float32)
sy = np.interp(np.linspace(0, 1, 64), np.linspace(0, 1, len(SPINE)),
               [p[1] for p in SPINE]).astype(np.float32)
rad = np.sqrt((v2[:, None, 0] - sx[None, :]) ** 2
              + (v2[:, None, 1] - sy[None, :]) ** 2).min(1)
for lo, hi, lbl in [(-1.10, -0.50, "below water"), (0.55, 1.15, "at the lip"),
                    (2.20, 2.80, "above     ")]:
    m = (v2[:, 2] > lo) & (v2[:, 2] < hi)
    if m.any():
        print(f"  overhang {lbl} Z {lo:+.2f}..{hi:+.2f}: "
              f"max radius {rad[m].max():.2f} m  mean {rad[m].mean():.2f} m")
write_ply(f"{OUT}/LEDGE_Outcrop.ply", v2, f2, nr2)
del d_r, v2, f2, nr2, X2, Y2, Z2

# ============================================================
# 3. TUNEL / ULAZ U ŠPILJU (ENT_Tunnel)
# ============================================================
VOX3 = float(os.environ.get("VOX3", 0.17))


o3 = (-14.45, -25.25, 4.80)
h3 = ( 14.45, -21.00, 16.53)
n3 = tuple(int(round((h3[i] - o3[i]) / VOX3)) + 1 for i in range(3))
print("tunnel grid", n3, "=", round(np.prod(n3) / 1e6, 2), "M voxels")

X3 = (o3[0] + np.arange(n3[0], dtype=np.float32) * VOX3)[:, None, None]
Y3 = (o3[1] + np.arange(n3[1], dtype=np.float32) * VOX3)[None, :, None]
Z3 = (o3[2] + np.arange(n3[2], dtype=np.float32) * VOX3)[None, None, :]
g3x = (o3[0] + np.arange(n3[0], dtype=np.float32) * VOX3)[:, None] + np.zeros(n3[:2], np.float32)
g3y = (o3[1] + np.arange(n3[1], dtype=np.float32) * VOX3)[None, :] + np.zeros(n3[:2], np.float32)


BORE = [(0.90, -18.60, 0.0), (-0.50, -21.00, 0.0), (-1.15, -22.45, 0.0),
        (-1.60, -23.90, 0.0), (-1.95, -25.30, 0.0)]
dh_b, _, _, _ = polyline_xy(g3x, g3y, BORE)
dh_b = dh_b[:, :, None]


fl = sstep(-21.80, -24.30, Y3)
HWf = HW + 1.15 * fl
HHf = HH + 0.60 * fl
CRf = CR + 0.50 * fl
q3x = dh_b - (HWf - CRf)
q3z = np.abs(Z3 - (FLOOR + HHf)) - (HHf - CRf)
d_bore = (np.sqrt(np.maximum(q3x, 0.0) ** 2 + np.maximum(q3z, 0.0) ** 2)
          + np.minimum(np.maximum(q3x, q3z), 0.0) - CRf)
del q3x, q3z


bore_amp = sstep(-21.00, -22.40, Y3) * sstep(0.30, 1.70, Z3 - FLOOR)
d_bore += bore_amp * (0.72 * noise3(n3, 2.40, 58, VOX3)
                      + 0.38 * noise3(n3, 1.10, 59, VOX3)
                      + 0.16 * noise3(n3, 0.60, 60, VOX3))
del bore_amp, fl


corr = np.maximum(np.maximum(dh_b - 1.10, (FLOOR + 0.02) - Z3),
                  Z3 - (FLOOR + 2.40))
d_bore = np.minimum(d_bore, corr)


hh3 = 6.20 * sstep(-24.60, -21.30, Y3) + 2.40 * sstep(-23.00, -21.00, Y3)
lat = 1.0 - sstep(6.50, 13.00, np.abs(X3))
ytap = sstep(-24.90, -23.60, Y3)
Hs = 4.60 + (0.70 + hh3) * (lat * ytap)
del hh3, ytap


Hs2 = np.ascontiguousarray(Hs[:, :, 0])
gxs, gys = np.gradient(Hs2, VOX3, VOX3)
gmag = np.sqrt(gxs ** 2 + gys ** 2 + 1.0).astype(np.float32)[:, :, None]
d_b = (Z3 - Hs) / gmag
del Hs, Hs2, gxs, gys, gmag


seam = sstep(-21.00, -22.20, Y3) * lat
d_b += seam * (0.70 * noise3(n3, 5.0, 51, VOX3)
               + 0.42 * noise3(n3, 2.2, 52, VOX3)
               + 0.22 * noise3(n3, 1.0, 53, VOX3)
               + 0.10 * noise3(n3, 0.55, 54, VOX3))
bw3 = noise3a(n3, (14.0, 14.0, 6.0), 55, VOX3)
d_b += seam * 0.46 * (0.55 * noise3a(n3, (10.0, 10.0, 2.5), 56, VOX3)
                      + 0.28 * np.sin((Z3 + 0.60 * bw3) * 3.10)
                      + 0.13 * np.sin((Z3 + 0.40 * bw3) * 7.30 + 1.30))
d_b += seam * 0.28 * noise3a(n3, (2.0, 2.0, 7.0), 57, VOX3)
del bw3, seam


d_b = smax(d_b, -d_bore, 0.28)


guard = sstep(-22.95, -22.15, Y3)
skin = np.maximum(np.maximum(-d_bore, d_bore - 1.00),
                  (FLOOR + HHf) - Z3)
d_b = smin(d_b, skin + 12.0 * (1.0 - guard), 0.45)
del guard, skin, corr


def at3(px, py, pz):
    return float(d_b[int(round((px - o3[0]) / VOX3)),
                     int(round((py - o3[1]) / VOX3)),
                     int(round((pz - o3[2]) / VOX3))])
mouth = d_bore[:, -1, :] < 0.0
print(f"  bore open cells on the y=-21 seam: {int(mouth.sum())}"
      f"  (0 would mean the tunnel is walled off)")

thin, thin_at = 99.0, None
for yi in range(1, n3[1] - 1):
    yv = o3[1] + yi * VOX3
    if yv > -21.4 or yv < -24.2: continue
    col = d_b[:, yi, :]
    xi = int(np.argmin(np.abs((o3[0] + np.arange(n3[0]) * VOX3) - (-1.3))))
    air = col[xi] < 0.0
    zs = o3[2] + np.arange(n3[2]) * VOX3
    void = np.where(~air & (zs > FLOOR) & (zs < FLOOR + 7.0))[0]
    solid = np.where(air & (zs > FLOOR + 1.0))[0]
    if len(solid):
        t = (zs[solid].max() - zs[solid].min())
        if t < thin: thin, thin_at = t, round(yv, 2)
print(f"  rock over the bore on the centreline: thinnest {thin:.2f} m at y={thin_at}"
      f"   (<0.5 would mean the roof is about to blow out)")

v3, f3, nr3 = march(d_b, o3, VOX3)
nr3 = -nr3
f3 = f3[:, ::-1].copy()
print("ENT_Tunnel:", len(v3), "verts", len(f3), "tris")
print("  bbox", v3.min(0).round(2), v3.max(0).round(2))
write_ply(f"{OUT}/ENT_Tunnel.ply", v3, f3, nr3)
del d_b, d_bore, v3, f3, nr3, lat, dh_b

# ============================================================
# 4. POD ISPRED ULAZA (ENT_Ground) - ravna mreža, ne marching cubes
# ============================================================
GRES = 0.40
GC = (-1.50, -31.00)
gn = int(round(20.0 / GRES)) + 1
gxv = GC[0] - 10.0 + np.arange(gn, dtype=np.float32) * GRES
gyv = GC[1] - 10.0 + np.arange(gn, dtype=np.float32) * GRES
GX = gxv[:, None] + np.zeros((gn, gn), np.float32)
GY = gyv[None, :] + np.zeros((gn, gn), np.float32)

def n2d(cell_m, seed):
    return noise3((gn, gn, 3), cell_m, seed, GRES)[:, :, 1]

GBASE = 5.50
h = (0.32 * n2d(9.0, 71) + 0.17 * n2d(3.6, 72) + 0.075 * n2d(1.5, 73))


WALK = [(-0.50, -21.00), (-1.30, -23.20), (-2.10, -25.60), (-2.80, -28.00),
        (-3.00, -30.50), (-3.20, -33.00)]
dh_w, _, _, _ = polyline_xy(GX, GY, WALK)
h *= 0.10 + 0.90 * sstep(1.70, 3.60, dh_w)


r_c = np.sqrt((GX - GC[0]) ** 2 + (GY - GC[1]) ** 2)
h += 1.05 * sstep(6.50, 10.20, r_c) * sstep(-23.00, -25.50, GY)


flat = ((1.0 - sstep(2.40, 4.20, dh_w))
        * (1.0 - sstep(-24.60, -26.20, GY)))
h *= 1.0 - flat


h = np.where(GY > -26.0, np.maximum(h, -0.40), h)
gz = GBASE + h
del flat

verts_g = np.stack([GX.ravel(), GY.ravel(), gz.ravel()], 1).astype(np.float32)
idx = np.arange(gn * gn).reshape(gn, gn)
a = idx[:-1, :-1].ravel(); b = idx[1:, :-1].ravel()
c = idx[1:, 1:].ravel();   e = idx[:-1, 1:].ravel()
faces_g = np.concatenate([np.stack([a, b, c], 1), np.stack([a, c, e], 1)]).astype(np.int32)
print("ENT_Ground:", len(verts_g), "verts", len(faces_g), "tris")
print("  bbox", verts_g.min(0).round(2), verts_g.max(0).round(2))
print(f"  Z at the doorway (-0.9,-21.4): "
      f"{gz[np.argmin(np.abs(gxv + 0.9)), np.argmin(np.abs(gyv + 21.4))]:.3f}"
      f"  [tunnel floor is {FLOOR:.2f}]")
write_ply(f"{OUT}/ENT_Ground.ply", verts_g, faces_g)
del verts_g, faces_g, GX, GY, gz, h, dh_w, r_c

# ============================================================
# 5. KAMENJE (ROCK_01..06) - manji odvojeni kamenčići za oko šume/ulaza
# ============================================================
KIT = [("ROCK_01", 1.10, (1.00, 0.80, 0.60), 61, 10.0),
       ("ROCK_02", 0.85, (1.00, 0.95, 0.74), 62, 9.5),
       ("ROCK_03", 0.62, (0.88, 1.00, 0.66), 63, 9.0),
       ("ROCK_04", 0.45, (1.00, 0.78, 0.82), 64, 8.0),
       ("ROCK_05", 0.32, (0.92, 1.00, 0.70), 65, 7.0),
       ("ROCK_06", 0.21, (1.00, 0.86, 0.78), 66, 6.5)]
for nm, R, ax, sd, div in KIT:
    v_r = R / div
    half = R * 1.55
    nr_ = int(round(2 * half / v_r)) + 1
    o_r = (-half, -half, -half)
    XR = (o_r[0] + np.arange(nr_, dtype=np.float32) * v_r)[:, None, None]
    YR = (o_r[1] + np.arange(nr_, dtype=np.float32) * v_r)[None, :, None]
    ZR = (o_r[2] + np.arange(nr_, dtype=np.float32) * v_r)[None, None, :]
    sh = (nr_, nr_, nr_)
    aa = (R * ax[0], R * ax[1], R * ax[2])
    d_k = (np.sqrt((XR / aa[0]) ** 2 + (YR / aa[1]) ** 2 + (ZR / aa[2]) ** 2)
           - 1.0) * min(aa)


    d_k += R * (0.125 * noise3(sh, R * 0.95, sd, v_r)
                + 0.070 * noise3(sh, R * 0.48, sd + 100, v_r)
                + 0.034 * noise3(sh, max(R * 0.30, v_r * 3.5), sd + 200, v_r))
    d_k += 0.045 * np.sin(ZR * (2.0 * np.pi / 0.55) + sd) * (
        0.35 + 0.65 * np.clip(noise3(sh, R * 1.3, sd + 300, v_r) * 0.5 + 0.5, 0, 1))

    d_k = smax(d_k, -(ZR + aa[2] * 0.70), R * 0.22)
    vk, fk, nk = march(d_k, o_r, v_r)
    nk = -nk
    fk = fk[:, ::-1].copy()
    vk[:, 2] -= vk[:, 2].min()
    size = (vk.max(0) - vk.min(0))
    print(f"{nm}: {len(vk)} verts {len(fk)} tris   "
          f"{size[0]:.2f} x {size[1]:.2f} x {size[2]:.2f} m")
    write_ply(f"{OUT}/{nm}.ply", vk, fk, nk)
    del d_k, vk, fk, nk, XR, YR, ZR

print("done")
