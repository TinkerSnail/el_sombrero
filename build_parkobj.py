import json
import shutil
import struct
import subprocess
import zipfile
from pathlib import Path

from PIL import Image

BASE = Path(__file__).parent
SPRITES = BASE / "sprites"
OUT_PARKOBJ = BASE / "el_sombrero.parkobj"
INSTALL_DIR = Path.home() / "Library/Application Support/OpenRCT2/object"
OPENRCT2 = Path("/Applications/OpenRCT2.app/Contents/MacOS/openrct2")

# RCT2 game palette extracted from rct1.ride.toilets.parkobj — 256 RGB triples
_RCT2_PALETTE_HEX = (
    "000000010101020202030303040404050505060606070707080808090909172323"
    "2333332f43433f53534b63635b73736f83838397979fafafb7c3c3d3dbdbeff3f"
    "3332f003f3b004f4b0b5b5b136b6b1f777b2f878b3b979b4fa7af5fbbbf73cbc"
    "f8bdfe3a3432b07573b0b6f4b177f571f8f63279f7333b38343bf9757cbaf6fd"
    "bc787e7dba3f7efc3471b005f2b00773f008f5307a76f07bf8b0fd7a713f3cb1"
    "bffe72ffff35ffffb8fffffc32300004f00005f07076f0f0f7f1b1b8f2727a33b"
    "3bb34f4fc76767d77f7feb9f9fffbfbf1b3313233f172f4f1f3b5f27476f2b57"
    "7f33638f3b739b4383ab4b93bb53a3cb5fb7db671f371b2f47233b532b4b6337"
    "5b6f436f874f879f5f9fb76fb7cf7fc3db93cfe7a7dff7bf0f3f001353001767"
    "001f7b00278f07379f1747af275bbf3f6fcf578bdf73a3ef8fc3ffb34f2b1363"
    "371b77472b8b573ba76343bb7353cf8363d79773e3ab83efbf97f7cfabffe3c3"
    "0f1337272b573337673f437753538b63639b7777af8b8bbf9f9fcfb7b7dfd3d3"
    "efefefff001b6f0027970733a70f43bb1b53cb2b67df4387e35ba3e777bbef8f"
    "d3f3afe7fbd7f7ff0b2b0f0f371717471f23532b2f633b3b734b4f875f639b77"
    "7baf8b93c7a7afdbc3cff3df3f005f4b0773530f7f5f1f8f6b2b9b7b3fab8753"
    "bb9b67c7ab7fd7bf9be7d7c3f3f3ebff3f00005700007300008f0000ab0000c7"
    "0000e30700ff0700ff4f43ff7b73ffaba3ffdbd74f27006f3300933f00b74700"
    "db4f00ff5300ff6f17ff8b33ffa34fffb76bffcb87ffdba300332f003f37004b"
    "4300574f076b63177f772b938f47a7a363bbbb83cfcfabe7e7cfffff3f001b67"
    "00337b0b3f8f174fa31f5fb7276fdb3b8fef5babf377bbf797cbfbb7dfffd7ef"
    "271300371f07472f0f5b3f1f6b53337b674b8f7f6ba3937fbbab93cfc3abe7db"
    "c3fff3df374b4bffb700ffdb00ffff00278f871b837b07675f005f570f776fc7"
    "ffff9be3e353afaf339b977bcbcb435b5b536b6b637b7b6f332f83372f973f33"
    "ab4333bf4b2fd34f2be75723ff5f1fff7f27ff9b33ffb73fffcf4bffffff"
)
RCT2_PALETTE = bytes.fromhex(_RCT2_PALETTE_HEX)  # 768 bytes: [R,G,B]*256

# RCT2 palette indices reserved for runtime recoloring (primary/secondary/tertiary
# car colors). Pixels landing here get tinted by the chosen ride colour scheme,
# which we want for the original Enterprise cars but NOT for the painted-on hat.
REMAP_INDICES = (
    set(range(243, 255))  # primary
    | set(range(202, 214))  # secondary
    | set(range(46, 58))    # tertiary
)
TRANSPARENT = 0
SAFE_INDICES = sorted(set(range(1, 256)) - REMAP_INDICES)

# Pre-compute (256,3) palette array and (len(SAFE),3) safe-only array for nearest-color lookups
import numpy as np
_palette_arr = np.array(
    [[RCT2_PALETTE[i*3], RCT2_PALETTE[i*3+1], RCT2_PALETTE[i*3+2]] for i in range(256)],
    dtype=np.int32,
)
_safe_arr = _palette_arr[SAFE_INDICES]
_safe_lookup = np.array(SAFE_INDICES, dtype=np.uint8)


def _nearest(palette_arr: np.ndarray, lookup: np.ndarray, rgb: np.ndarray) -> np.ndarray:
    """Vectorised nearest-color: rgb is (N,3) int32; returns (N,) palette indices."""
    # broadcast (N,1,3) - (1,P,3) → (N,P,3); sum sq → (N,P); argmin → (N,)
    diffs = rgb[:, None, :] - palette_arr[None, :, :]
    dists = (diffs * diffs).sum(axis=2)
    return lookup[np.argmin(dists, axis=1)] if lookup is not None else np.argmin(dists, axis=1).astype(np.uint8)


# --- Concrete ground pad ------------------------------------------------------
# Paint a light-grey concrete disc on the ground under the wheel so the ride sits
# on a pad instead of bare dirt. The pad is a screen-space ellipse (a circle in
# isometric view) placed at the ride's FIXED ground-centre in world space, so it
# stays put while the wheel spins/tilts above it. It is baked into every wheel
# frame *after* palette conversion (as a non-remap "safe" grey index) so it never
# recolours and the cars keep their ride-colour-scheme indices.
# NOTE: Disabled — it doesn't render in-game. A ground-level pad baked into the
# flat-ride structure sprite gets painted over by the surrounding tiles' ground
# (the ride is anchored to one tile; neighbouring tiles draw their terrain on top
# of anything at ground level that spills onto them — only the elevated wheel
# survives). The original ENTERP's baked shadow is tiny for the same reason. To
# put a pad under the ride, place path/floor scenery tiles around it in-game.
ADD_CONCRETE_PAD = False
PAD_WORLD = (-4, 34)      # ground-centre in manifest-offset space (x, y)
PAD_RX, PAD_RY = 84, 42   # ellipse radii in px (~2:1 for the iso ground plane)
CONCRETE_RGB = (206, 203, 196)
TEXTURE_GRAIN = 5.0       # fine per-pixel concrete speckle (brightness units)
TEXTURE_MOTTLE = 4.0      # broader mottling amplitude
# Soft shadow of the wheel cast onto the pad (the painted El Sombrero art dropped
# the shadow the original ENTERP sprite had baked in). A smooth penumbra darkens
# the concrete under the wheel, offset toward the lower-left to match RCT2's light.
ADD_PAD_SHADOW = True
SHADOW_RX, SHADOW_RY = 70, 35       # ~ the disc's ground footprint
SHADOW_OFFSET = (-5, 4)             # px offset from PAD_WORLD (lower-left)
SHADOW_RGB = (150, 147, 140)        # darkest grey at the shadow's core
SHADOW_INNER, SHADOW_OUTER = 0.30, 1.12  # penumbra band (wider gap = softer fade)

# Greyscale LUT: brightness 0..255 -> nearest non-remap palette index, keeping the
# concrete's slight warm tint. Lets us paint a smooth textured/shaded gradient.
_tint = (CONCRETE_RGB[1] / CONCRETE_RGB[0], CONCRETE_RGB[2] / CONCRETE_RGB[0])
_lut_v = np.arange(256)
_lut_cols = np.clip(
    np.stack([_lut_v, _lut_v * _tint[0], _lut_v * _tint[1]], axis=1), 0, 255
).astype(np.int32)
_gray_lut = _nearest(_safe_arr, _safe_lookup, _lut_cols)   # (256,) uint8
_CONCRETE_V, _SHADOW_V = CONCRETE_RGB[0], SHADOW_RGB[0]


def _hash01(ix, iy):
    """Deterministic pseudo-random in [0,1) from coords — world-static texture."""
    n = np.sin(ix * 12.9898 + iy * 78.233) * 43758.5453
    return n - np.floor(n)


def add_concrete_pad(palette_path, out_path, ox: int, oy: int):
    """Composite the textured, soft-shadowed ground pad under a palettised sprite.

    The pad's texture and shadow are sampled in WORLD (screen) coordinates so they
    stay locked to the ground as the wheel spins; the original sprite is laid on
    top so the wheel/cars occlude the pad where they overlap. Returns new (ox, oy).
    """
    img = Image.open(palette_path)
    if img.mode != "P":
        img = img.convert("P")
    idx = np.array(img)                        # (h, w) palette indices
    h, w = idx.shape
    cx, cy = PAD_WORLD[0] - ox, PAD_WORLD[1] - oy

    minx, miny = min(0, cx - PAD_RX), min(0, cy - PAD_RY)
    maxx, maxy = max(w, cx + PAD_RX + 1), max(h, cy + PAD_RY + 1)
    W, H = int(maxx - minx), int(maxy - miny)
    sx, sy = int(-minx), int(-miny)
    new_ox, new_oy = ox - sx, oy - sy

    # world (screen) coord of every output pixel → texture/shadow stay world-static
    wx = (new_ox + np.arange(W))[None, :].astype(np.float64)   # (1, W)
    wy = (new_oy + np.arange(H))[:, None].astype(np.float64)   # (H, 1)
    dx, dy = wx - PAD_WORLD[0], wy - PAD_WORLD[1]
    mask = (dx / PAD_RX) ** 2 + (dy / PAD_RY) ** 2 <= 1.0       # (H, W)

    ix = np.broadcast_to(wx, (H, W)); iy = np.broadcast_to(wy, (H, W))
    val = np.full((H, W), float(_CONCRETE_V))
    val += (_hash01(ix, iy) - 0.5) * 2 * TEXTURE_GRAIN                       # grain
    val += (_hash01(np.floor(ix / 5), np.floor(iy / 3)) - 0.5) * 2 * TEXTURE_MOTTLE

    if ADD_PAD_SHADOW:
        sdx, sdy = wx - (PAD_WORLD[0] + SHADOW_OFFSET[0]), wy - (PAD_WORLD[1] + SHADOW_OFFSET[1])
        r = np.sqrt((sdx / SHADOW_RX) ** 2 + (sdy / SHADOW_RY) ** 2)
        t = np.clip((SHADOW_OUTER - r) / (SHADOW_OUTER - SHADOW_INNER), 0.0, 1.0)
        t = t * t * (3 - 2 * t)                # smoothstep penumbra
        val -= (_CONCRETE_V - _SHADOW_V) * t

    pad_idx = _gray_lut[np.clip(val, 0, 255).astype(np.int32)]
    out = np.where(mask, pad_idx, 0).astype(np.uint8)

    # lay the original sprite on top (non-transparent pixels win)
    region = out[sy:sy + h, sx:sx + w]
    op = idx != 0
    region[op] = idx[op]
    out[sy:sy + h, sx:sx + w] = region

    new = Image.new("P", (W, H))
    new.putpalette(list(RCT2_PALETTE))
    new.putdata(out.flatten().tolist())
    new.save(out_path, transparency=0)
    return new_ox, new_oy


# --- Hand-painted concrete lip, propagated world-static -----------------------
# Instead of a generated ellipse (which spilled past the ride footprint and got
# occluded), we use the artist's actual painted concrete lip — proven to render
# because it hugs the wheel. _padart/world_pad.png holds that art in WORLD (screen)
# coordinates (origin in world_pad.json); we stamp it under every wheel frame at
# the right per-frame pixel position, in palette space (after colour conversion,
# so the cars keep their remap/recolour indices). World-static => no flicker.
USE_WORLD_PAD = True
PAD_BASE_RGB = (201, 198, 191)     # flat, evenly-lit concrete
RIDE_SHADOW_RGB = (150, 147, 140)  # the spinning ride's shadow on the concrete
SHADOW_SHIFT = (-3, 6)             # project ride silhouette down-left (light upper-right)
_pad_base_index = int(_nearest(_safe_arr, _safe_lookup, np.array([PAD_BASE_RGB], np.int32))[0])
_ride_shadow_index = int(_nearest(_safe_arr, _safe_lookup, np.array([RIDE_SHADOW_RGB], np.int32))[0])
# Keep only the SHAPE of the artist's painted lip; the static blurry shadow the
# union picked up is dropped and recreated dynamically per frame (see stamp fn).
_wp_path = BASE / "_padart" / "world_pad.png"
if USE_WORLD_PAD and _wp_path.exists():
    _wp_meta = json.loads((BASE / "_padart" / "world_pad.json").read_text())
    _wp_alpha = np.array(Image.open(_wp_path).convert("RGBA"))[:, :, 3] >= 128
    _wp_ox, _wp_oy = _wp_meta["world_origin"]   # world coord of pad pixel (0,0)


def _shift_mask(m, dx, dy):
    """Boolean mask shifted by (dx, dy), clipped to bounds."""
    out = np.zeros_like(m)
    H, W = m.shape
    ys, xs = np.where(m)
    ny, nx = ys + dy, xs + dx
    v = (ny >= 0) & (ny < H) & (nx >= 0) & (nx < W)
    out[ny[v], nx[v]] = True
    return out


def stamp_world_pad(palette_path, out_path, ox: int, oy: int):
    """Flat concrete lip (static) + the ride's shadow cast onto it per frame.

    The lip is filled with even concrete; the shadow is made by projecting THIS
    frame's wheel silhouette down-left onto the lip, so it sweeps as the cars
    spin. Done in palette space, so the cars keep their remap/recolour indices.
    """
    img = Image.open(palette_path)
    if img.mode != "P":
        img = img.convert("P")
    idx = np.array(img)
    h, w = idx.shape
    ph, pw = _wp_alpha.shape
    px0, py0 = _wp_ox - ox, _wp_oy - oy
    minx, miny = min(0, px0), min(0, py0)
    maxx, maxy = max(w, px0 + pw), max(h, py0 + ph)
    W, H = int(maxx - minx), int(maxy - miny)
    sx, sy = int(-minx), int(-miny)
    out = np.zeros((H, W), dtype=np.uint8)

    # flat concrete lip
    pad_mask = np.zeros((H, W), dtype=bool)
    pxs, pys = px0 + sx, py0 + sy
    pad_mask[pys:pys + ph, pxs:pxs + pw] = _wp_alpha
    out[pad_mask] = _pad_base_index

    # ride's moving shadow: project this frame's wheel silhouette onto the lip
    wheel = np.zeros((H, W), dtype=bool)
    wheel[sy:sy + h, sx:sx + w] = idx != 0
    shadow = _shift_mask(wheel, SHADOW_SHIFT[0], SHADOW_SHIFT[1])
    out[pad_mask & shadow] = _ride_shadow_index

    # wheel/cars on top (occlude the lip where they overlap)
    wreg = out[sy:sy + h, sx:sx + w]
    op = idx != 0
    wreg[op] = idx[op]
    out[sy:sy + h, sx:sx + w] = wreg

    new = Image.new("P", (W, H))
    new.putpalette(list(RCT2_PALETTE))
    new.putdata(out.flatten().tolist())
    new.save(out_path, transparency=0)
    return ox - sx, oy - sy


def to_palette_png(src_path: Path, out_path: Path, base_path: Path | None = None) -> None:
    """Convert RGBA PNG to RCT2-palette-indexed PNG.

    If base_path is given (path to the original ENTERP sprite for this frame),
    use it as a reference: pixels matching the base art keep their original palette
    index (preserving remap behavior for the wheel/cars); painted-over or new pixels
    are forced to non-remap "safe" indices so the hat doesn't recolor at runtime.
    Base sprite is assumed bottom-aligned within a current canvas that may be taller.
    """
    img = Image.open(src_path).convert("RGBA")
    w, h = img.size
    arr = np.array(img)
    alpha = arr[:, :, 3]
    rgb = arr[:, :, :3].astype(np.int32)

    opaque = alpha >= 128
    flat_rgb = rgb.reshape(-1, 3)

    # Full-palette nearest for every pixel (what the old build did)
    nearest_any = _nearest(_palette_arr, np.arange(256, dtype=np.uint8), flat_rgb).reshape(h, w)
    # Safe-only nearest for every pixel
    nearest_safe = _nearest(_safe_arr, _safe_lookup, flat_rgb).reshape(h, w)

    if base_path and base_path.exists():
        base = np.array(Image.open(base_path).convert("P"))  # indices
        bh, bw = base.shape
        # Bottom-align: base bottom-left = (h - bh, 0) in current
        y_off = h - bh
        # Build a base-index grid the same size as current, with -1 where base has no pixel
        base_full = -np.ones((h, w), dtype=np.int32)
        x_end = min(bw, w)
        if y_off >= 0 and bh > 0:
            base_full[y_off:y_off + bh, :x_end] = base[:, :x_end]

        # Decision per opaque pixel:
        #   - if base has an opaque pixel at this location AND our nearest_any picks the
        #     same index → user didn't overpaint here, keep the base index (preserves remap)
        #   - otherwise → painted/new pixel; clamp to safe palette
        kept_base = (base_full > 0) & (nearest_any.astype(np.int32) == base_full)
        out = np.where(kept_base, base_full.astype(np.uint8), nearest_safe)
    else:
        # No base reference (e.g. peep sprites 199-246) — use safe palette everywhere
        out = nearest_safe

    out = np.where(opaque, out, TRANSPARENT).astype(np.uint8)

    out_img = Image.new("P", (w, h))
    out_img.putpalette(list(RCT2_PALETTE))
    out_img.putdata(out.flatten().tolist())
    out_img.save(out_path, transparency=0)


manifest = json.loads((BASE / "manifest.json").read_text())
obj = json.loads((BASE / "object.json").read_text())

# Real El Sombrero spins flat — it doesn't tilt to vertical like the Enterprise.
# The Enterprise tilt is hardcoded in the sim, so we cap the *visible* tilt by
# substituting sprites. The wheel sprites are laid out as 14 tilt BANDS of 12
# rotation frames each, on a grid starting at frame 31 (frames 3-30 are the flat
# region). Within a band, tilt is constant and consecutive frames are consecutive
# rotation steps (tilt = outer loop, rotation = inner). So:
#   band b (0..13) = frames 31 + b*12 .. 31 + b*12 + 11
# To cap the visible tilt at CAP_BAND while keeping the spin perfectly smooth, we
# remap every frame in a higher band to the SAME rotation step (same within-band
# offset) of CAP_BAND. Using the true 12-frame period preserves rotation phase
# exactly. (A previous version used %32, which assumed 32-frame bands and reset
# the rotation phase every 12th frame at speed — that caused the spin to jitter.)
BAND_ORIGIN = 31
BAND_LEN = 12
CAP_BAND = 2  # frames 55..66 — the gentle fan-out tilt; raise for more, lower for less
cap_start = BAND_ORIGIN + CAP_BAND * BAND_LEN
for i in range(cap_start + BAND_LEN, 199):
    phase = (i - BAND_ORIGIN) % BAND_LEN
    manifest[i] = dict(manifest[cap_start + phase])

# Frames 199..246 are the seated-rider overlay sprites the Enterprise paints on
# top of the wheel. Because peeps draw after the vehicle sprite, riders on the
# BACK arc of the wheel land high on screen, over the sombrero cone, and clip it.
# Each overlay frame has a FIXED baked screen position (its manifest y-offset),
# and the engine assigns a back-position frame to whichever seat is currently at
# the back (rotation = spin + CurrentRotation*4 + seatRotation) — so blanking just
# the negative-y (back-arc) frames hides exactly the riders behind the cone, for
# every camera rotation and throughout the spin, while front-arc riders still
# render. Back cars show their closed shell anyway, so nothing is lost there.
BACK_ARC_Y_CUTOFF = 0  # blank overlays sitting at/above this screen y (near cone)
for i in range(199, 247):
    if manifest[i]["y"] < BACK_ARC_Y_CUTOFF:
        manifest[i] = dict(manifest[1])  # 1x1 transparent placeholder → hidden
    # else: front/near arc, clear of the cone — keep the original rider overlay

# Build sprite manifest pointing at the right source file per frame
tmp_dir = BASE / "_palette_tmp"
tmp_dir.mkdir(exist_ok=True)

sprite_manifest = []
for i, entry in enumerate(manifest):
    # Honor entry["path"] so the de-tilt remap above (which points tilted-stage
    # slots at flat-rotation source files) actually reads the right artwork.
    src_basename = Path(entry["path"]).stem
    src = SPRITES / f"{src_basename}.png"

    if not src.exists():
        print(f"  WARNING: {src} not found, skipping frame {i:03d}")
        continue

    # Convert RGBA → palette-indexed so sprite build produces flags=0x0000.
    # Pass the base ENTERP sprite (if available) so original wheel/car pixels keep
    # their remap-range indices while painted hat pixels get clamped to safe colors.
    src_img = Image.open(src)
    if src_img.mode == "P":
        palette_src = src
    else:
        palette_src = tmp_dir / f"{i:03d}.png"
        base_ref = BASE / "_base_sprites" / f"{src_basename}.png"
        to_palette_png(src, palette_src, base_ref if base_ref.exists() else None)

    sprite_path, x, y = str(palette_src), entry["x"], entry["y"]

    # Stamp the hand-painted concrete lip under every wheel frame (3..198),
    # world-static so it stays put as the wheel spins/tilts.
    if USE_WORLD_PAD and _wp_path.exists() and 3 <= i <= 198:
        cpath = tmp_dir / f"pad_{i:03d}.png"
        x, y = stamp_world_pad(palette_src, cpath, x, y)
        sprite_path = str(cpath)
    elif ADD_CONCRETE_PAD and 3 <= i <= 198:
        cpath = tmp_dir / f"concrete_{i:03d}.png"
        x, y = add_concrete_pad(palette_src, cpath, x, y)
        sprite_path = str(cpath)

    sprite_manifest.append({"path": sprite_path, "x": x, "y": y})

print(f"  converted {sum(1 for e in sprite_manifest if '_palette_tmp' in e['path'])} sprites to palette mode")

# Use OpenRCT2 CLI to build images.dat (paths must be relative to manifest location)
manifest_path = BASE / "_sprite_manifest.json"
images_dat = BASE / "_images.dat"

# Make paths relative to BASE so openrct2 can resolve them
relative_manifest = [
    {"path": str(Path(e["path"]).relative_to(BASE)), "x": e["x"], "y": e["y"]}
    for e in sprite_manifest
]
manifest_path.write_text(json.dumps(relative_manifest))

try:
    result = subprocess.run(
        [str(OPENRCT2), "sprite", "build", str(images_dat), str(manifest_path)],
        capture_output=True, text=True, cwd=str(BASE)
    )
    if result.returncode != 0:
        print("sprite build failed:", result.stderr)
        raise SystemExit(1)

    # Use string format (matches what built-in objects use)
    obj["images"] = [f"$LGX:images.dat[0..{len(sprite_manifest) - 1}]"]

    # Update sprite bounds to match actual sprite dimensions
    dat_data = images_dat.read_bytes()
    n_sprites = struct.unpack_from("<I", dat_data, 0)[0]
    max_w = max_neg = max_pos = 0
    for i in range(n_sprites):
        # G1Element: offset(uint32), width(int16), height(int16), x(int16), y(int16), flags(uint16), zoom(uint16)
        _, w, h, x, y, _, _ = struct.unpack_from("<IhhhhHH", dat_data, 8 + i * 16)
        if w > max_w: max_w = w
        if -y > max_neg: max_neg = -y
        if y + h > max_pos: max_pos = y + h

    # Only height changed (hat is above wheel) — keep original spriteWidth
    obj["properties"]["cars"]["spriteHeightNegative"] = max(max_neg, 128)
    obj["properties"]["cars"]["spriteHeightPositive"] = max(max_pos, 32)
    print(f"  sprite bounds: heightNeg={max(max_neg,128)}, heightPos={max(max_pos,32)}")

    with zipfile.ZipFile(OUT_PARKOBJ, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("object.json", json.dumps(obj, indent=4))
        zf.write(images_dat, "images.dat")
finally:
    manifest_path.unlink(missing_ok=True)
    images_dat.unlink(missing_ok=True)
    shutil.rmtree(tmp_dir, ignore_errors=True)

INSTALL_DIR.mkdir(parents=True, exist_ok=True)
shutil.copy2(OUT_PARKOBJ, INSTALL_DIR / OUT_PARKOBJ.name)

print(f"Done: {OUT_PARKOBJ.name} ({len(sprite_manifest)} images) → installed to {INSTALL_DIR}")
