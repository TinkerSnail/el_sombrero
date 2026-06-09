# El Sombrero — Custom Ride Modifications

A custom OpenRCT2 flat ride built on the **Enterprise** ride type, reworked to
behave like the real *El Sombrero* ride at Six Flags: it spins flat (with the
usual start/stop/acceleration) instead of tilting up to vertical, and it wears a
tall painted sombrero in the center of the wheel.

This document records the custom behaviors we built on top of the stock
Enterprise, *why* each was needed, and *how* each works — so the build can be
understood and tuned later.

---

## TL;DR — what's customized

| # | Behavior | Where | One-line how |
|---|----------|-------|--------------|
| 1 | **Flat spin (no tilt to vertical)** | `build_parkobj.py` tilt-cap block | Substitute high-tilt wheel sprites with a capped tilt band |
| 2 | **Smooth spin at all speeds** | same block | Use the *true* 12-frame tilt-band period so rotation phase is preserved |
| 3 | **No riders clipping the sombrero** | `build_parkobj.py` overlay block | Blank only the back-arc seated-rider overlays (by screen position) |
| 4 | **Concrete pad + moving shadow** | `build_parkobj.py` `stamp_world_pad` | Stamp a flat concrete lip under every wheel frame, world-static, with a per-frame ride shadow projected onto it |

Customizations 1–3 are implemented purely in the **build script** by remapping
which source PNG each sprite slot uses; `manifest.json`, `object.json`, and the
source art in `sprites/` are **never modified on disk**. Customization 4 adds a
small piece of source art in `_padart/`. Every change is reversible by editing
`build_parkobj.py` and rebuilding.

---

## Background: how this object is built

`build_parkobj.py` packs the ride:

1. Reads `manifest.json` (247 sprite entries → source PNG + x/y offset per frame).
2. Optionally **remaps** some entries to different source frames (this is where
   all our customization lives).
3. Palette-converts each PNG to the RCT2 game palette (`to_palette_png`), using
   the matching `_base_sprites/` frame as a reference so original wheel/car
   pixels keep their recolorable indices while the painted hat stays fixed.
4. Calls `openrct2 sprite build` to produce `images.dat`.
5. Zips `object.json` + `images.dat` into `el_sombrero.parkobj` and installs it
   to `~/Library/Application Support/OpenRCT2/object`.

Run it with:

```bash
python3 build_parkobj.py
```

---

## Sprite frame layout (the key reference)

Understanding the frame layout is what made the customizations possible.

| Frame range | Contents |
|-------------|----------|
| `000–002` | Preview / metadata / 1×1 transparent placeholder (`001`) |
| `003–030` | **Flat region** — wheel horizontal (used when stopped / slow) |
| `031–198` | **14 tilt bands of 12 rotation frames each** (see below) |
| `199–246` | **Seated-rider overlays** — drawn on top of the wheel per occupied seat |

### The tilt bands (frames 031–198)

The wheel's tilt (horizontal → near-vertical) is stored as **14 bands**, each
containing **12 rotation frames**, on a grid starting at frame **31**:

```
band b (0..13)  =  frames  31 + b*12  ..  31 + b*12 + 11
```

- **Tilt is the outer loop, rotation the inner loop**: within a band the tilt is
  constant and the 12 consecutive frames are 12 consecutive rotation steps.
- Verified empirically: sprite *width* (the wheel ellipse narrowing as it tilts)
  holds constant for exactly 12 frames, then steps — at frames 31, 43, 55, 67, …
- This is why corresponding rotation steps in different bands are exactly **12
  frames apart** — the fact that makes the phase-preserving remap work.

The OpenRCT2 sim still computes tilt/rotation the stock way and asks for a frame
index; we only change *which art* those indices point to.

---

## Customization 1 & 2 — Flat spin, smooth at all speeds

**Problem.** The stock Enterprise tilts its wheel up toward vertical as it spins.
The real El Sombrero only spins flat. The tilt is **hardcoded in the sim** and
can't be disabled by any `object.json` property — but we *can* make every
high-tilt frame draw a low-tilt sprite, so the wheel never *appears* to tilt past
a chosen amount.

**Subtlety (the jitter bug).** A first version assumed 32-frame tilt stages and
remapped with `% 32`. Because the bands are actually **12** frames, at full speed
(when the sim parks in the top tilt band and cycles its 12 frames) the `% 32`
math reset the rotation phase every 12th frame — making the spin visibly
**jitter / appear to stutter or run backwards**. The fix was to use the true
12-frame period so each high-tilt frame maps to the **same rotation step** in the
capped band, preserving phase exactly.

**Implementation** (`build_parkobj.py`):

```python
BAND_ORIGIN = 31
BAND_LEN    = 12
CAP_BAND    = 2          # frames 55..66 — the gentle fan-out tilt we settled on
cap_start   = BAND_ORIGIN + CAP_BAND * BAND_LEN   # = 55
for i in range(cap_start + BAND_LEN, 199):        # remap bands above CAP_BAND
    phase = (i - BAND_ORIGIN) % BAND_LEN
    manifest[i] = dict(manifest[cap_start + phase])
```

Result: tilt ramps up naturally to band `CAP_BAND` as the ride accelerates, then
holds there; the 12 rotation frames cycle cleanly (no backward jump) at any spin
speed.

### Tuning the tilt

`CAP_BAND` is the single knob:

| `CAP_BAND` | Frames shown at max | Look |
|-----------|---------------------|------|
| `0` | 31–42 | Almost flat, very slight fan-out |
| `1` | 43–54 | Slight tilt |
| `2` *(current)* | 55–66 | Gentle/moderate fan-out |
| `3`+ | 67–78 … | Progressively more tilt (toward stock) |

> **Note — strobe effect:** at very high spin speed the wheel may *appear* to
> rotate backwards. That's a true aliasing/wagon-wheel effect of 12 discrete
> rotation steps spinning fast, **not** the phase bug — it isn't fixable by
> remapping.

---

## Customization 3 — Hide only the riders that clip the sombrero

**Problem.** Seated riders are drawn as per-seat **overlay sprites** (frames
199–246) painted *after* the wheel. Riders on the **back arc** of the wheel land
high on screen, right over the tall sombrero cone, so they render *in front of*
the hat — heads/bodies floating on the cone.

**Why the obvious fixes don't work:**
- `drawOrder` (tried 0, 6, 7, 14, 15) only affects vehicle-vs-vehicle layering,
  not rider occlusion. No effect.
- Per-pixel / per-sprite occlusion flags don't exist in the RCT2 format.
- The plugin API exposes neither a guest's seat index, the camera rotation, nor
  any per-guest hide flag — so a script can't selectively hide riders either.
- Hiding **all** riders works (blank all of 199–246) but leaves every seat
  looking empty.

**The unlock.** Each overlay frame has a **fixed baked screen position** (its
`manifest` y-offset). The engine assigns a frame to each seat via
`spin + CurrentRotation*4 + seatRotation`, so **whichever seat is currently at
the back always gets a back-position frame** — automatically, for every camera
rotation and throughout the spin. Therefore we can hide *only the back-arc
frames* (those with a negative/high screen y, up by the cone) and:

- far-side riders never clip the hat (they're simply not drawn),
- near-side riders stay visible,
- the back of those far cars faces the camera anyway, so nothing looks missing,
- it's correct under **all 4 camera rotations** without knowing any seat index.

**Implementation** (`build_parkobj.py`):

```python
BACK_ARC_Y_CUTOFF = 0    # blank overlays sitting at/above this screen y (near cone)
for i in range(199, 247):
    if manifest[i]["y"] < BACK_ARC_Y_CUTOFF:
        manifest[i] = dict(manifest[1])   # 1×1 transparent placeholder → hidden
    # else: front/near arc, clear of the cone — keep the original rider overlay
```

With the cutoff at `0`, this hides 21 back-arc frames and keeps 27 front frames:

- **Hidden:** 202–208, 218–224, 234–240
- **Kept:** 199–201, 209–217, 225–233, 241–246

### Tuning the rider hiding

`BACK_ARC_Y_CUTOFF` is the knob: **lower** it (e.g. `-5`) if a side car still
nicks the cone's brim; **raise** it (e.g. `+5`) if too many riders disappear.

---

## Customization 4 — Concrete pad with a moving shadow

**Goal.** Sit the ride on a light concrete pad instead of bare dirt.

**The hard constraint.** A pad baked into the wheel sprite only renders if it
stays **within the ride's own footprint tiles**. A large ground ellipse spills
onto neighboring tiles, whose ground is painted *after* the ride sprite and
covers it (the elevated wheel escapes this; a ground-level pad does not). So the
pad has to hug the wheel — it's the **visible front lip** of a pad, not a full
plaza.

**The art.** The lip shape was hand-painted, then reduced to a single
world-positioned template: `_padart/world_pad.png` (the lip's alpha shape) plus
`_padart/world_pad.json` (its origin in world/offset coordinates). Only the
*shape* is used — it's filled with flat concrete at build time.

**The build** (`stamp_world_pad`, applied to wheel frames 3–198): after palette
conversion (so the cars keep their remap/recolour indices), for each frame it

1. fills the lip shape with flat concrete (`PAD_BASE_RGB`), placed at its fixed
   world position (`world_origin − frame_offset`), so it's **static** as the
   wheel spins;
2. casts the **ride's shadow** onto the lip by projecting *this frame's* wheel
   silhouette by `SHADOW_SHIFT` and darkening the lip there (`RIDE_SHADOW_RGB`) —
   because the silhouette rotates frame to frame, the shadow **sweeps**;
3. lays the wheel/cars back on top so they occlude the lip where they overlap.

This keeps the concrete static (it's the ground) while the shadow is dynamic (the
ride above it moves) — and never touches the car pixels, so no recolour is lost.

### Tuning

- `SHADOW_SHIFT = (-3, 6)` — shadow direction/length (down-left). Bigger `y`
  exposes more lit concrete beyond the shadow, making the motion more visible.
- `RIDE_SHADOW_RGB` / `PAD_BASE_RGB` — shadow darkness / concrete shade.
- `USE_WORLD_PAD = False` disables the pad entirely.

> The pad template in `_padart/` is regenerated from hand-painted frames by a
> one-off extraction (union of the painted frames in world coordinates); the
> committed `world_pad.png` is the result, so normal rebuilds just reuse it.

## Verification checklist

After `python3 build_parkobj.py`, reload in OpenRCT2 (close/reopen the park, or
remove + re-place the ride) and confirm:

1. **Tilt:** wheel ramps to the gentle fan-out and holds — never flips to
   vertical.
2. **Smooth spin:** through full acceleration → top speed → deceleration, the
   spin is steady with no periodic jitter.
3. **Riders, loading:** near/front cars show riders; back arc shows none and
   nothing clips the cone.
4. **Camera rotation:** rotate through all 4 angles — "no rider behind the cone"
   holds in every view (the key robustness check).
5. **Riders, spinning:** riders appear on the front arc and disappear behind the
   cone as they orbit (reads as correct occlusion).

---

## Files

| File | Role | Modified by us? |
|------|------|-----------------|
| `build_parkobj.py` | Build script — **all customization lives here** | ✅ yes |
| `manifest.json` | Per-frame source PNG + offset | ❌ no |
| `object.json` | Ride definition (`type: enterprise`, seats, colors…) | ❌ no |
| `sprites/` | Source art (wheel, hat, riders, peeps) | ❌ no |
| `_base_sprites/` | Original ENTERP frames (palette reference) | ❌ no |
| `el_sombrero.parkobj` | Build output (installed to OpenRCT2) | (generated) |

All three customizations are sprite **remaps** applied at build time, so reverting
any of them is just editing the corresponding block in `build_parkobj.py` and
rebuilding.
