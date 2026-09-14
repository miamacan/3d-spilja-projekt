"""
B3 cave generator. B1 blockout + B2 three-tier detail + the B3 entrance kit.

Signed-distance fields, meshed with marching cubes, written as binary PLY:

  CAVE_Shell_Main   chamber void + throat + talus ramp + beach, normals inward
  LEDGE_Outcrop     the hero rock, solid, normals outward
  ENT_Tunnel        rock bank at the cave mouth, bore continued out of the
                    shell, solid, normals outward
  ENT_Ground        clearing floor, 20 x 20 m displaced grid (not marched)
  ROCK_01..06       boulder kit, solid, each centred on its own origin

Spec targets (world is Z-up, metres, water surface Z = 0):
  chamber          26 m across, 32 m tall (bed -3.6 -> dome apex 28.4)
  skylight         4 x 6 m opening, offset +5 m toward the far wall
  right recess     8 m wide, floor below the waterline
  pool floor       dished bowl, 2.0 m deep at the wall to 3.6 m at the axis
  outcrop          9.3 m long, 5 m at the base, top Z 5.50, 2 m flat crest
  entrance throat  8 m long, 3.5 m wide, 4 m high, S-bend
  talus + beach    ~29 deg ramp from the mouth down to a pad at Z 0.35
  CAM_Hero         (0, -14, 7.2) pitched 5.8 deg down -- fixed, do not move
"""
import numpy as np
from scipy import ndimage
from skimage import measure
import os

OUT = "/mnt/user-data/outputs"
os.makedirs(OUT, exist_ok=True)

# chamber axis, in XY. Placed so the near wall sits just ahead of CAM_Hero.
AX, AY = 0.5, 1.0
BED_AXIS, BED_WALL = -3.6, -2.0          # dished pool floor
FLOOR = 5.50                              # tunnel floor / outcrop crest


def sstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def smin(a, b, k):
    h = np.clip(0.5 + 0.5 * (b - a) / k, 0.0, 1.0)
    return b * (1.0 - h) + a * h - k * h * (1.0 - h)


def smax(a, b, k):
    return -smin(-a, -b, k)


def prof(z, pts):
    zs = np.array([p[0] for p in pts], dtype=np.float32)
    rs = np.array([p[1] for p in pts], dtype=np.float32)
    return np.interp(z, zs, rs).astype(np.float32)


_cc = {}


def noise3(shape, cell_m, seed, vox):
    """band-limited noise, ~unit variance, feature size in METRES"""
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
    """anisotropic band-limited noise -- cells_m is (x, y, z) feature size in
    metres, so stretching z gives the vertical fluting real limestone has."""
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
    ax, ay, az = a
    dx, dy, dz = b[0] - ax, b[1] - ay, b[2] - az
    ll = dx * dx + dy * dy + dz * dz
    t = np.clip(((px - ax) * dx + (py - ay) * dy + (pz - az) * dz) / ll, 0.0, 1.0)
    return np.sqrt((px - ax - t * dx) ** 2 + (py - ay - t * dy) ** 2
                   + (pz - az - t * dz) ** 2)


def polyline_xy(gx, gy, pts, samples=220):
    """For each XY cell: distance to the polyline in XY, the parameter t of the
    nearest sample, and the polyline's interpolated Z there."""
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
    """close the domain except the named faces, then march"""
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


# =========================================================================
# 1.  CAVE_Shell_Main
# =========================================================================
VOX = float(os.environ.get("VOX", 0.285))
# Residual displacement amplitude at the skylight rim, as a fraction of full.
# B1 used 0.08 (1 - 0.92). Mia's B2 asks for ~0.3 so the rim is rounded
# rather than shredded; the opening is measured after marching to confirm
# the extra amplitude has not blown the 4 x 6 m target.
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

# --- chamber: 26 m across, dished floor, domed top --------------------
CHAMBER = [(-5.0, 7.0), (-4.0, 8.5), (-2.0, 10.5), (0.0, 11.8), (2.0, 12.6),
           (5.0, 13.0), (8.0, 13.0), (11.0, 12.7), (14.0, 12.0), (17.0, 11.0),
           (20.0, 9.6), (23.0, 7.8), (25.5, 5.6), (27.0, 3.6), (28.0, 1.6),
           (28.4, 0.2),
           # negative radius above the apex forces the dome shut. Without this
           # the noise pass reopens the tapering needle and punches a second
           # unintended skylight through the ceiling at the chamber axis.
           (29.0, -2.0), (31.0, -3.0)]
rho = np.sqrt((X - AX) ** 2 + (Y - AY) ** 2)
d = rho - prof(Z, CHAMBER)
# dished pool floor: 3.6 m deep on the axis easing to 2.0 m at the wall
bed = BED_AXIS + (BED_WALL - BED_AXIS) * np.clip(rho / 13.0, 0.0, 1.0) ** 2
d = smax(d, bed - Z, 1.1)
del bed

# --- entrance throat: 3.5 x 4 m flat-floored box on an S-bend ---------
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

# --- shadowed recess leading off right, 8 m wide, floor under water ---
# raised so the dark mouth sits where the reference puts its mid-right shadow
# mass, while the floor stays under the waterline so the pool runs into it
# Projection check: the reference's big shadow mass sits at 42-70% across the
# hero frame. At (7, 2) the recess mouth landed at 79% -- too far right. Moved
# to (5, 6) it lands at ~66% and runs off into the far-right corner. It cannot
# be water: water can never appear above 71% of this frame, so that mass in
# the reference has to be a shadowed recess.
d = smin(d, capsule(X, Y, Z, (5.0, 6.0, 1.5), (13.0, 12.0, 1.0)) - 4.0, 1.8)

# --- skylight: 4 x 6 m elliptical shaft, offset +5 m toward the far wall
scx = -2.0 - 0.10 * (Z - 24.0)
scy = 6.0 + 0.24 * (Z - 24.0)
d_sky = np.sqrt(((X - scx) / 1.0) ** 2 + ((Y - scy) / 1.5) ** 2) - 2.0
d = smin(d, smax(d_sky, 24.0 - Z, 0.8), 1.9)
del scx, scy, d_sky

# --- foreground buttresses: rock pushed into the void left and right ---
# undercut profiles: thin at the waterline so there is floor to walk on,
# bulging at eye level so both frame edges read dark
# strongly undercut: almost nothing below Z 3 so the talus ramp has a lane
# to pass through, bulging hard at eye level so the frame edge still reads dark
LEFT = [(-5.0, 0.6), (0.0, 0.9), (2.0, 1.4), (4.0, 2.8), (6.0, 4.2),
        # carried higher than before: the frame top sits only ~3.5 m above eye
        # level at this distance, so the dark top-left mass in the reference
        # has to come from rock at Z 9-14, not from the ceiling proper
        (9.0, 4.3), (12.0, 4.2), (16.0, 3.0), (19.0, 1.5), (22.0, 0.4),
        (31.0, 0.1)]
d_bl = np.sqrt(((X + 9.2) / 1.0) ** 2 + ((Y + 8.4) / 1.45) ** 2) - prof(Z, LEFT)
d = smax(d, -d_bl, 1.4)
del d_bl

# pulled back and slimmed: at R 4.0 from x 8.8 it filled a fifth of the hero
# frame, where the reference only has a narrow dark strip on the right
RIGHT = [(-5.0, 1.0), (0.0, 2.0), (3.0, 2.8), (7.0, 3.5), (12.0, 3.0),
         (16.0, 1.8), (19.0, 0.5), (31.0, 0.1)]
d_br = np.sqrt(((X - 9.4) / 1.0) ** 2 + ((Y + 7.0) / 1.30) ** 2) - prof(Z, RIGHT)
d = smax(d, -d_br, 1.3)
del d_br

# --- talus ramp + shingle beach, added as rock on the camera-left -----
# ~29 deg all the way down, threaded between the outcrop and the left
# buttress, widening into a beach pad at Z 0.35
# Starts ON the outcrop crest, not beside it: the first attempt began inside
# the throat box next to the outcrop's flank and there was no continuous
# surface to step onto -- the walk test found an 85 deg segment there.
# Curves back into the chamber as it drops. The previous line ran straight
# out to x -8 around y -8, which is outside the chamber wall at water level:
# the ramp was buried in solid rock with no void above it to stand in, and
# the walk test found 10 samples with no floor at all.
# A near-level lead-in across the outcrop crest first: descending straight
# off the crest put a 0.4 m drop in the first step (45 deg).
RAMP = [(-0.6, -11.40, 5.50), (-1.8, -11.25, 5.35), (-3.0, -11.00, 4.70),
        (-4.4, -10.30, 3.75), (-5.7, -9.20, 2.80), (-6.5, -7.60, 1.85),
        (-6.9, -5.80, 0.95), (-6.8, -4.00, 0.35)]
dh_r, t_r, z_r, _ = polyline_xy(gx, gy, RAMP)
dh_r = dh_r[:, :, None]; t_r = t_r[:, :, None]; z_r = z_r[:, :, None]
W_r = 1.30 + 1.70 * sstep(0.82, 1.0, t_r)          # widens into the beach pad
surf = np.where(t_r > 0.95, np.float32(0.35), z_r)  # flat pad at the foot
d_ramp = smax(dh_r - W_r, Z - surf, 0.45)
d = smax(d, -d_ramp, 0.5)
del t_r, z_r, W_r

# --- B2 displacement: three tiers, per Mia's B2 spec -------------------
# Tier 1 large forms  ~12 m  / 1.5 m   -> bulges and hollows
# Tier 2 stratification ~3 m / 0.4 m   -> stretched 4:1 horizontally
# Tier 3 grain        ~0.9 m / 0.08 m  -> see note at the grain tier
# Displacement mask. This is the generator's equivalent of Mia's vertex
# group: zero on the walkable surfaces, ramping up off them, held down
# near the skylight rim. Built as a field rather than painted weights.
amp = ((0.35 + 0.65 * sstep(-13.0, -7.0, Y))
       * (1.0 - SKY_MASK * sstep(22.0, 27.0, Z)))   # skylight rim stays rounded
# Quieten the noise in a corridor around the talus ramp. At full amplitude
# the lump octaves grew a 1.5 m rock boss straight across it and the walk
# test lost the floor for 2 m. Only the corridor is affected, so the left
# wall keeps its lumps where the hero frame sees them.
# Deepened from 0.80 to 0.90 for B2: the large-forms tier is 1.5 m where the
# old lump octave was 0.9 m, so 20% residual would have put a 0.30 m boss on
# the ramp. 10% keeps the absolute residual where B1 had it.
amp = amp * (1.0 - 0.80
             * (1.0 - sstep(1.7, 3.4, dh_r))
             * (1.0 - sstep(3.0, 5.5, np.abs(Z - surf))))
# Same corridor around the tunnel floor -- this is Mia's "weight ~0 on the
# walkable floor and tunnel floor" mask. B1 never had one: it relied on the
# re-assert below, which turned out not to be enough at B2 amplitudes.
amp = amp * (1.0 - 0.80
             * (1.0 - sstep(2.0, 3.8, dh_t[:, :, None]))
             * (1.0 - sstep(2.6, 4.6, np.abs(Z - FLOOR))))

# Mia's B2 strengths are Displace-modifier numbers, where "strength 1.5 m"
# means +/-0.75 m about the midlevel. Measured that way B1's stack already
# met most of them: its 0.90 unit-variance octave is +/-2.2 m at 2.5 sigma,
# well past tier 1, and its sine bands already exceed the 0.4 m tier. The
# first B2 attempt REPLACED that stack with the three tiers and the walls
# came back smoother than B1 -- the 1.25 m and 0.70 m octaves are what made
# them read as rock. So B2 adds to B1 rather than replacing it.

# --- tier 1: large forms. The octave B1 genuinely lacked: its biggest was
# 7.5 m, so the chamber had no bulges and hollows above that scale.
large = 0.55 * noise3(shape, 12.0, 26, VOX)

# --- B1's lump stack, unchanged. This is the crunch. -------------------
lumps = (0.90 * noise3(shape, 7.5, 21, VOX)
         + 0.40 * noise3(shape, 3.0, 22, VOX)
         + 0.22 * noise3(shape, 1.25, 23, VOX)
         + 0.09 * noise3(shape, 0.70, 24, VOX))

# --- tier 2: stratification, now with the 4:1 horizontal stretch -------
# B1's sine bands are kept -- they are what actually reads as limestone --
# but the bed planes are no longer dead level. bedwob tilts and waves them,
# and an anisotropic field at (12, 12, 3) m adds bedding that is 4x wider
# than it is tall, which is the stretch Mia asked for.
bedwob = noise3a(shape, (18.0, 18.0, 7.0), 13, VOX)
strat = (0.20 * np.sin((Z + 0.55 * bedwob) * 3.10
                       + 0.50 * noise3(shape, 6.5, 11, VOX))
         + 0.11 * np.sin((Z + 0.35 * bedwob) * 7.30 + 1.30)
         + 0.05 * np.sin((Z + 0.20 * bedwob) * 15.0 + 2.70)
         + 0.16 * noise3a(shape, (12.0, 12.0, 3.0), 14, VOX))
del bedwob
# differential erosion: soft beds cut back, hard beds stand proud
strat *= 0.30 + 0.95 * np.clip(noise3(shape, 9.0, 12, VOX) * 0.5 + 0.5, 0, 1)

# --- tier 3: grain -----------------------------------------------------
# Mia's spec says 0.5 m. At VOX 0.285 that is under two voxels, below what
# marching cubes can resolve -- asking for it here buys aliasing and
# triangles, not detail. 0.70 m in the lump stack above is the finest
# honest tier at this voxel size. Real 0.5 m grain is a B6 normal-map job,
# which is where the brief already puts the near-rock faceting fix.

# --- vertical fluting (kept from B1) -----------------------------------
# runnels about 2 m across and 9 m tall. The walls were reading as pure
# horizontal corduroy against a reference that has strong vertical
# water-worn grooves, especially on the right.
flutes = (0.30 * noise3a(shape, (2.2, 2.2, 9.0), 41, VOX)
          + 0.14 * noise3a(shape, (1.0, 1.0, 4.0), 42, VOX))

d += amp * (large + lumps + strat + flutes)
del amp, large, lumps, strat, flutes

# The noise pass erodes walkable surfaces -- it opened a hole straight
# through the beach on the first run. Re-assert the throat void and the ramp
# rock afterwards so the route is guaranteed passable. Cost: the tunnel and
# the ramp read smoother than the rest of the rock until B6 puts detail back
# in with normal maps.
# sharp blends here on purpose: at k=1.5 the re-assert let the throat floor
# wander +/-0.4 m and the walk test hit 52 deg inside the tunnel
d = smin(d, d_tun, 0.35)
# Guarantee the tunnel floor exists. smin can only ever open the throat, it
# can never put rock back, so when the large-forms tier eroded the ground
# out from under the corridor the re-assert above could not restore it --
# the route check lost the floor on 22 of 32 samples. This slab is solid
# rock under the corridor and smax cannot remove it. Tapered over the last
# 1.2 m so it does not leave a step where the throat meets the chamber.
slab = np.maximum(dh_t[:, :, None] - (HW + 0.45), Z - FLOOR)
slab_on = sstep(0.0, 0.14, t_t[:, :, None])
d = smax(d, -slab - 10.0 * (1.0 - slab_on), 0.30)
d = smax(d, -d_ramp, 0.25)
del slab, slab_on, t_t, dh_t
# guaranteed headroom over the ramp: it threads under the left buttress and
# the walk test measured 1.69 m clearance, under the 1.8 m capsule
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
    """Walk the route in XY. At each sample find the floor (highest solid->air
    crossing below z_hi) and the ceiling above it, straight off the field.
    This is the same thing the Blender raycast walk test measures, run here so
    a bad noise tune is caught before anything is transferred."""
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
        idx = np.where(air[:-1] & ~air[1:])[0]          # air above, solid below
        below = np.where(~air)[0]
        if not air.any() or not below.any():
            floors.append(np.nan); heads.append(np.nan); lost += 1; continue
        # highest solid cell that has air directly above it
        cand = [i for i in below if i + 1 < len(col) and air[i + 1]]
        if not cand:
            floors.append(np.nan); heads.append(np.nan); lost += 1; continue
        fi = cand[-1] if len(idx) == 0 else cand[0]
        for i in cand:                                   # lowest floor with 1.8 m over it
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

# Skylight opening, measured on the field rather than eyeballed: the open
# cells on the top slice of the domain, before march() seals the faces.
sky = d[:, :, -1] < 0.0
if sky.any():
    # Count separate openings. A single bbox over all open cells is exactly
    # what hid the second unintended skylight in B1 and inflated the
    # measurement to 5.6 x 10.1 m -- so label each component and report it.
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

# =========================================================================
# 2.  LEDGE_Outcrop
# =========================================================================
# B3: 0.168 -> 0.126. The outcrop is 3 m from CAM_Hero, so it carries the
# scene's finest honest detail. At 0.126 the 0.40 m octaves and the 0.52 m
# bedding sine are 3-4 voxels and resolve cleanly; at 0.168 they aliased.
# Marching at 0.126 overshoots the 40k budget (~69k), so the mesh is
# collapse-decimated back to <=40k in Blender. Marching fine and decimating
# beats marching coarse: collapse takes triangles out of the flat areas
# first, so the detail survives and the flanks stop being over-tessellated.
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

# The stage has to be the clear high point with the ridge sitting lower
# behind it, otherwise the near part of the ridge bulks out the silhouette
# and the whole thing reads as a dome instead of the reference's pinnacle.
z_top = 5.22 + 0.45 * sstep(0.50, 1.00, tn) - 0.05 * np.sin(tn * 7.0)

# --- B3: the standing spot at MARK_ThrowSpot --------------------------
# "One comfortable standing spot" -- a genuinely flat pad, not just a low
# spot in the noise. Inside r 0.50 the cap is held dead level and every
# noise term is switched off; it fades out by r 1.05, which is about the
# cap's half-width, so the pad does not widen the silhouette.
PAD_XY = (-2.2, -5.0)                      # = MARK_ThrowSpot in XY
# Held at exactly B2's measured stage top so the hero composition does not
# move this phase (B2 read 34.3% across / 58.6% down on this point).
PAD_Z = 5.609
r_pad = np.sqrt((g2x - PAD_XY[0]) ** 2 + (g2y - PAD_XY[1]) ** 2)
pad = (1.0 - sstep(0.50, 1.05, r_pad))[:, :, None]
quiet = 1.0 - 0.94 * pad                   # noise mask, ~0 on the pad

# --- B3: a few 10 cm bumps on the near-flat top -----------------------
# Read as 10 cm TALL, which is what stops the cap being a mirror-flat
# plane at 3 m from the camera. 10 cm WIDE is not buildable here: it is
# under a voxel at 0.126, the same argument as the 0.5 m grain tier on the
# shell. These are added to the cap height rather than as blobs in the
# field, so the height is exactly what is asked for. All five sit clear of
# the pad so they never intrude on the standing spot.
BUMPS = [(-2.75, -3.95, 0.30, 0.10), (-1.95, -6.15, 0.26, 0.09),
         (-2.60, -6.30, 0.22, 0.11), (-1.55, -7.35, 0.32, 0.10),
         (-1.15, -8.60, 0.28, 0.08)]
bump = np.zeros(n2[:2], np.float32)
for bx, by, br, bh in BUMPS:
    bump += bh * np.exp(-(((g2x - bx) ** 2 + (g2y - by) ** 2) / (br * br)))
z_top = z_top + bump[:, :, None] * (1.0 - pad)
z_top = z_top * (1.0 - pad) + PAD_Z * pad

W = 0.90                                  # ~1.8 m cap, ~2.0 m once noised
drop = np.maximum(z_top - Z2, 0.0)
# narrow cap, flaring fast for the first 1.6 m, then near-vertical down to
# 5 m across at the waterline and a steeper plunge below it
width = (W + 0.62 * np.minimum(drop, 1.6)
         + 0.20 * np.clip(drop - 1.6, 0.0, 3.6)
         + 0.14 * np.maximum(drop - 5.2, 0.0))

# --- B3: rounded overhangs at the waterline ---------------------------
# Keyed off absolute Z, not off drop, because the overhang has to sit at
# the water surface and z_top varies along the ridge. A bulge centred
# 0.85 m above the water and a pinch 0.55 m below it give a lip that
# leans about 0.9 m out over the water across 1.4 m of height -- roughly
# 33 deg off vertical, which reads as an undercut from 3 m away. Lobed
# round the rock by a vertically-stretched noise so it is not a donut.
ovar = 0.50 + 0.50 * np.clip(
    noise3a(n2, (3.2, 3.2, 11.0), 38, VOX2) * 0.55 + 0.5, 0.0, 1.0)
width = width + ovar * (0.55 * np.exp(-((Z2 - 0.85) / 1.05) ** 2)
                        - 0.42 * np.exp(-((Z2 + 0.55) / 0.70) ** 2))
del ovar

d_r = smax(dh - width, Z2 - z_top, 0.50)
d_r = smax(d_r, Y2 + 3.90, 0.60)           # far tip, just past the stage
d_r = smax(d_r, -13.20 - Y2, 0.60)         # back end, overlapping the throat
flank = sstep(0.80, 2.10, dh)          # 0 on the spine, 1 out on the sides
del dh, tn, z_top, W, drop, width

# Near the crest the noise has to stay quiet: at 0.20 amplitude with strong
# sub-metre octaves it was throwing 0.5 m bumps into the walk route and the
# slope check hit 52 deg. Amplitude and the two fine octaves are both cut.
# B3: `quiet` switches all three noise groups off on the standing pad.
# Existing octaves are untouched -- the B2 lesson was that re-tuning them
# makes the rock read smoother, so density is added as new octaves only.
#
# B3 also re-aims the suppression. B2 keyed it to HEIGHT alone, which
# quieted the upper FLANKS as well as the ridge -- and the upper flanks are
# most of what CAM_Hero sees of this rock from 3 m away, so the hero rock
# came back smoother than the walls behind it. The reason for the
# suppression was the walk route, and the walk route is the ridge line, so
# key it to distance from the spine instead: quiet on the high ridge, full
# strength on the flanks at the same height.
# Two masks, split by octave size, and the split is the point. Giving the
# 4.2 m octave the flank boost as well grew a second lobe out of the rock's
# right shoulder, and the silhouette stopped being the pinnacle that the
# locked decisions call for -- so the big forms keep B2's height-only mask
# exactly, and only the sub-metre octaves get the flank boost. That buys
# surface that reads as rock at 3 m without moving the outline the hero
# composition depends on.
amp2 = (0.10 + 0.68 * sstep(6.0, 1.0, Z2)) * quiet            # B2, unchanged
fine2 = (0.12 + 0.66 * np.maximum(sstep(6.0, 1.0, Z2), flank)) * quiet
d_r += amp2 * (0.52 * noise3(n2, 4.2, 31, VOX2)
               + 0.24 * noise3(n2, 1.75, 32, VOX2))
d_r += fine2 * (0.08 * noise3(n2, 0.72, 33, VOX2)
                + 0.03 * noise3(n2, 0.42, 34, VOX2)
                + 0.030 * noise3(n2, 0.40, 39, VOX2))  # B3, 3.2 voxels

# B2: carry the same bedding through the hero rock. It is the nearest rock
# to the camera, so if it stays smooth while the walls get banded it reads
# as a different material. At VOX2 0.165 the 0.5 m grain Mia asked for IS
# resolvable here, unlike on the shell.
bw2 = noise3a(n2, (9.0, 9.0, 4.0), 35, VOX2)
beds2 = (0.58 * noise3a(n2, (8.0, 8.0, 2.0), 36, VOX2)
         + 0.30 * np.sin((Z2 + 0.70 * bw2) * 2.55)
         + 0.14 * np.sin((Z2 + 0.45 * bw2) * 5.90 + 1.30)
         # B3: a fourth bed at 0.52 m wavelength, 4.1 voxels at VOX2 0.126.
         # This is the tier the shell cannot have and the hero rock can.
         + 0.07 * np.sin((Z2 + 0.30 * bw2) * 12.00 + 0.60))
del bw2
# own mask, not amp2: full strength on the flanks, cut hard near the crest
# so the 2 m stage stays flat and the walk route keeps its slope margin.
# same flank rule as amp2: the bedding is the main thing that makes this
# read as the same limestone as the walls, and B2 was masking it out of the
# exact band the hero camera looks at.
bmask = (0.12 + 0.88 * np.maximum(sstep(5.40, 3.20, Z2), flank)) * quiet
gmask = (0.20 + 0.80 * np.maximum(sstep(5.40, 3.20, Z2), flank)) * quiet
d_r += 0.34 * beds2 * bmask
d_r += 0.05 * noise3(n2, 0.50, 37, VOX2) * gmask
d_r += 0.028 * noise3(n2, 0.40, 43, VOX2) * gmask       # B3 grain
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

# --- B3 checks: the standing pad and the waterline overhang -------------
rp = np.sqrt((v2[:, 0] - PAD_XY[0]) ** 2 + (v2[:, 1] - PAD_XY[1]) ** 2)
top = (rp < 0.45) & (v2[:, 2] > 5.0)
if top.any():
    zs = v2[top, 2]
    print(f"  standing pad r<0.45: {top.sum()} verts, Z {zs.min():.3f}"
          f"..{zs.max():.3f}, spread {np.ptp(zs) * 1000:.0f} mm")
# widest radius from the ridge in three bands: below water, at the lip,
# and above it. lip > below = the rock leans out over the water.
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

# =========================================================================
# 3.  ENT_Tunnel  --  the rock bank at the cave mouth
# =========================================================================
# The shell's domain stops dead at y = -21 with an open rim, so from the
# clearing the throat was a tube ending in mid-air. This is the rock the
# tunnel is bored through: a bank rising out of the clearing floor with the
# THROAT polyline carried straight on out of the shell.
#
# The join: this field's +y domain face sits at exactly y = -21.0, the same
# plane the shell's open rim sits on, and the bore here uses the same
# rounded-box cross-section (HW/HH/CR about FLOOR) as the shell's d_tun. All
# displacement is faded to zero over the last 1.2 m, so at the seam both
# meshes are the bare analytic tube and agree to well under a voxel. They do
# not share vertices -- different voxel sizes -- so expect a hairline seam,
# not a step.
VOX3 = float(os.environ.get("VOX3", 0.17))
# The bank has to be as wide as the hole it is covering. The shell's y0
# domain face is open across the whole chamber, so any sight line from the
# clearing that crosses y = -21 inside the chamber's footprint lands on the
# far wall -- the cave interior, seen from outside, floating in the open.
# A 12 m bank left that leaking on both flanks. This one spans ~26 m and the
# leak check at the bottom of this section is what says whether it is enough.
o3 = (-14.45, -25.25, 4.80)
h3 = ( 14.45, -21.00, 16.53)
n3 = tuple(int(round((h3[i] - o3[i]) / VOX3)) + 1 for i in range(3))
print("tunnel grid", n3, "=", round(np.prod(n3) / 1e6, 2), "M voxels")

X3 = (o3[0] + np.arange(n3[0], dtype=np.float32) * VOX3)[:, None, None]
Y3 = (o3[1] + np.arange(n3[1], dtype=np.float32) * VOX3)[None, :, None]
Z3 = (o3[2] + np.arange(n3[2], dtype=np.float32) * VOX3)[None, None, :]
g3x = (o3[0] + np.arange(n3[0], dtype=np.float32) * VOX3)[:, None] + np.zeros(n3[:2], np.float32)
g3y = (o3[1] + np.arange(n3[1], dtype=np.float32) * VOX3)[None, :] + np.zeros(n3[:2], np.float32)

# BORE starts on the shell's last throat segment so the centreline and its
# direction match across y = -21, then bends gently toward MARK_PlayerSpawn.
BORE = [(0.90, -18.60, 0.0), (-0.50, -21.00, 0.0), (-1.15, -22.45, 0.0),
        (-1.60, -23.90, 0.0), (-1.95, -25.30, 0.0)]
dh_b, _, _, _ = polyline_xy(g3x, g3y, BORE)
dh_b = dh_b[:, :, None]

# The bore flares toward daylight. A cave mouth is not the same size as the
# corridor behind it, and holding HW/HH constant is what made the first
# version read as a machined doorway. Zero flare at y = -21 so the join with
# the shell's throat is still the identical cross-section.
fl = sstep(-21.80, -24.30, Y3)
HWf = HW + 1.15 * fl
HHf = HH + 0.60 * fl
CRf = CR + 0.50 * fl
q3x = dh_b - (HWf - CRf)
q3z = np.abs(Z3 - (FLOOR + HHf)) - (HHf - CRf)
d_bore = (np.sqrt(np.maximum(q3x, 0.0) ** 2 + np.maximum(q3z, 0.0) ** 2)
          + np.minimum(np.maximum(q3x, q3z), 0.0) - CRf)
del q3x, q3z

# Break up the bore itself. The first version added all its noise to the
# bank and then carved the bore with smax afterwards, so every surface the
# bore defined -- the whole tunnel interior and the mouth -- came out as the
# bare analytic rounded box. Displacing d_bore before the carve is what
# makes the portal an irregular arch. Faded to zero at the shell seam, and
# held off the bottom 0.30 m so the tunnel floor stays flat and walkable.
bore_amp = sstep(-21.00, -22.40, Y3) * sstep(0.30, 1.70, Z3 - FLOOR)
d_bore += bore_amp * (0.72 * noise3(n3, 2.40, 58, VOX3)
                      + 0.38 * noise3(n3, 1.10, 59, VOX3)
                      + 0.16 * noise3(n3, 0.60, 60, VOX3))
del bore_amp, fl

# At that amplitude the noise is free to pinch the tunnel shut, so
# guarantee a corridor: 2.2 m wide, 2.4 m over the floor, always open.
# smax against a negated SDF opens; it can never close.
corr = np.maximum(np.maximum(dh_b - 1.10, (FLOOR + 0.02) - Z3),
                  Z3 - (FLOOR + 2.40))
d_bore = np.minimum(d_bore, corr)

# The bank as a height field, tapered to nothing at the sides and at the
# outer edge so the domain walls never cut through solid rock. Everything
# under about 5.5 is buried by ENT_Ground, so the foot meets the clearing on
# a natural intersection line rather than a visible flat cut.
hh3 = 6.20 * sstep(-24.60, -21.30, Y3) + 2.40 * sstep(-23.00, -21.00, Y3)
lat = 1.0 - sstep(6.50, 13.00, np.abs(X3))       # full height over ~13 m,
ytap = sstep(-24.90, -23.60, Y3)                 # gone by ~26 m
Hs = 4.60 + (0.70 + hh3) * (lat * ytap)
del hh3, ytap
# (Z - H) is not a distance -- on the 60-odd degree front face its gradient
# is ~2.5, so metre-sized noise would only bite 0.4 m into the rock there,
# which is the face the player actually sees. Normalise by the gradient so
# the displacement is isotropic.
Hs2 = np.ascontiguousarray(Hs[:, :, 0])
gxs, gys = np.gradient(Hs2, VOX3, VOX3)
gmag = np.sqrt(gxs ** 2 + gys ** 2 + 1.0).astype(np.float32)[:, :, None]
d_b = (Z3 - Hs) / gmag
del Hs, Hs2, gxs, gys, gmag

# same limestone recipe as B2, faded out at the seam and at the edges
seam = sstep(-21.00, -22.20, Y3) * lat
d_b += seam * (0.70 * noise3(n3, 5.0, 51, VOX3)
               + 0.42 * noise3(n3, 2.2, 52, VOX3)
               + 0.22 * noise3(n3, 1.0, 53, VOX3)
               + 0.10 * noise3(n3, 0.55, 54, VOX3))
bw3 = noise3a(n3, (14.0, 14.0, 6.0), 55, VOX3)
d_b += seam * 0.46 * (0.55 * noise3a(n3, (10.0, 10.0, 2.5), 56, VOX3)
                      + 0.28 * np.sin((Z3 + 0.60 * bw3) * 3.10)
                      + 0.13 * np.sin((Z3 + 0.40 * bw3) * 7.30 + 1.30))
d_b += seam * 0.28 * noise3a(n3, (2.0, 2.0, 7.0), 57, VOX3)   # fluting
del bw3, seam

# carve the bore. Sharp blend: this is a walkable floor and the same
# lesson as the shell's re-assert applies -- a soft blend lets it wander.
d_b = smax(d_b, -d_bore, 0.28)

# Guarantee rock over the bore. The bank noise now runs at nearly twice the
# amplitude it did, and smax cannot put rock back, so without this the lump
# octaves are free to open a skylight straight through the roof of the
# tunnel -- the same failure the shell's negative-radius line exists to
# prevent at the dome apex.
#
# This hugs the bore rather than being a flat slab over it. The first
# version smax-ed in a 7 m wide, 1.8 m thick box above the crown, which did
# stop the blowout but ironed the rock flat over the whole mouth -- the one
# place the player looks at from two metres. Here the guaranteed rock is a
# 1 m skin following the (already noised) bore, and it is switched off
# outside the portal, because at the portal rim the rock thickness goes to
# zero by definition and a guarantee there would wall the opening up.
guard = sstep(-22.95, -22.15, Y3)          # 0 outside the mouth, 1 inside
skin = np.maximum(np.maximum(-d_bore, d_bore - 1.00),
                  (FLOOR + HHf) - Z3)
d_b = smin(d_b, skin + 12.0 * (1.0 - guard), 0.45)
del guard, skin, corr

# --- checks -------------------------------------------------------------
def at3(px, py, pz):
    return float(d_b[int(round((px - o3[0]) / VOX3)),
                     int(round((py - o3[1]) / VOX3)),
                     int(round((pz - o3[2]) / VOX3))])
mouth = d_bore[:, -1, :] < 0.0
print(f"  bore open cells on the y=-21 seam: {int(mouth.sum())}"
      f"  (0 would mean the tunnel is walled off)")
# thinnest rock over the bore, walked along the centreline
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

# =========================================================================
# 4.  ENT_Ground  --  20 x 20 m displaced clearing floor
# =========================================================================
# A grid, not a marched field: it is a floor, it needs clean quads and a
# predictable triangle count, and marching cubes would spend most of its
# budget on the underside. Near edge sits exactly on y = -21 so it meets
# the shell where the throat floor comes through.
GRES = 0.40
GC = (-1.50, -31.00)
gn = int(round(20.0 / GRES)) + 1
gxv = GC[0] - 10.0 + np.arange(gn, dtype=np.float32) * GRES
gyv = GC[1] - 10.0 + np.arange(gn, dtype=np.float32) * GRES
GX = gxv[:, None] + np.zeros((gn, gn), np.float32)
GY = gyv[None, :] + np.zeros((gn, gn), np.float32)

def n2d(cell_m, seed):
    return noise3((gn, gn, 3), cell_m, seed, GRES)[:, :, 1]

GBASE = 5.50                       # = FLOOR, so the tunnel floor runs on out
h = (0.32 * n2d(9.0, 71) + 0.17 * n2d(3.6, 72) + 0.075 * n2d(1.5, 73))

# Keep the walk out of the cave flat. Same idea as the shell's displacement
# mask, and the same reason: at full amplitude the noise puts a step in the
# doorway. The route runs from the throat out past MARK_PlayerSpawn.
WALK = [(-0.50, -21.00), (-1.30, -23.20), (-2.10, -25.60), (-2.80, -28.00),
        (-3.00, -30.50), (-3.20, -33.00)]
dh_w, _, _, _ = polyline_xy(GX, GY, WALK)
h *= 0.10 + 0.90 * sstep(1.70, 3.60, dh_w)

# A low rim so the clearing reads as a place rather than a plane. Held off
# the cave end entirely: a rim berm poking up through the tunnel floor is
# exactly the B1 defect that cost a session, and it is not repeated here.
r_c = np.sqrt((GX - GC[0]) ** 2 + (GY - GC[1]) ** 2)
h += 1.05 * sstep(6.50, 10.20, r_c) * sstep(-23.00, -25.50, GY)

# Dead flat under the bore itself so the tunnel floor and the clearing are
# the same surface at the doorway. Faded, not switched: a binary mask here
# puts a cliff edge across the clearing where it cuts off.
flat = ((1.0 - sstep(2.40, 4.20, dh_w))
        * (1.0 - sstep(-24.60, -26.20, GY)))
h *= 1.0 - flat
# The bank's field bottoms out at Z 4.80 and gets a flat cap there, so the
# clearing must not dip below that anywhere the bank's foot could reach or
# the underside shows.
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

# =========================================================================
# 5.  ROCK_01..06  --  boulder kit
# =========================================================================
# Each boulder is generated at the origin with its flat base on Z = 0, so
# placement is just "put it on the ground". Voxel size scales with the
# rock, which keeps every one of them in the 1.5-4k band regardless of
# size. Same octave ratios as the outcrop, plus a bedding sine at a FIXED
# 0.55 m wavelength -- the bands are a property of the limestone, not of
# how big the lump of it is, so they must not scale with the boulder.
# R is the base radius, so the longest axis lands near 2*R*max(ax) plus
# about 0.55 R of noise. Sized so every boulder stays inside the 0.5-3 m
# band. The voxel divisor falls with the rock: a 0.5 m stone does not need
# a 3 m stone's triangle count, and this is what keeps the kit in the
# 1.5-4k band per rock and under the 20k budget in total.
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
    # the finest octave is floored at 3.5 voxels -- below that marching
    # cubes returns aliasing, not detail, which is the same reason the
    # shell's 0.5 m grain tier does not exist
    d_k += R * (0.125 * noise3(sh, R * 0.95, sd, v_r)
                + 0.070 * noise3(sh, R * 0.48, sd + 100, v_r)
                + 0.034 * noise3(sh, max(R * 0.30, v_r * 3.5), sd + 200, v_r))
    d_k += 0.045 * np.sin(ZR * (2.0 * np.pi / 0.55) + sd) * (
        0.35 + 0.65 * np.clip(noise3(sh, R * 1.3, sd + 300, v_r) * 0.5 + 0.5, 0, 1))
    # flatten the base so it sits instead of balancing
    d_k = smax(d_k, -(ZR + aa[2] * 0.70), R * 0.22)
    vk, fk, nk = march(d_k, o_r, v_r)
    nk = -nk
    fk = fk[:, ::-1].copy()
    vk[:, 2] -= vk[:, 2].min()                     # base on Z = 0
    size = (vk.max(0) - vk.min(0))
    print(f"{nm}: {len(vk)} verts {len(fk)} tris   "
          f"{size[0]:.2f} x {size[1]:.2f} x {size[2]:.2f} m")
    write_ply(f"{OUT}/{nm}.ply", vk, fk, nk)
    del d_k, vk, fk, nk, XR, YR, ZR

print("done")
