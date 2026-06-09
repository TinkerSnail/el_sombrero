# El Sombrero, custom ride notes

This is a custom OpenRCT2 flat ride based on the Enterprise. It spins flat like
the real El Sombrero at Six Flags does, with the usual start, stop, and speed up,
instead of tilting all the way up to vertical. And it has a big painted sombrero
in the middle of the wheel.

These notes cover what we changed, why, and how, so it's easy to come back and
tweak later.

## The short version

There are four custom things going on, and they all live in `build_parkobj.py`.

| # | What it does | How |
|---|------|------|
| 1 | Spins flat, no tilt to vertical | Swap the steep tilt frames for a capped tilt band |
| 2 | Stays smooth at any speed | Use the real 12 frame tilt band length so the rotation never jumps |
| 3 | Riders don't poke through the sombrero | Hide just the back of the ring of seated riders, picked by screen position |
| 4 | Concrete pad with a moving shadow | Stamp a flat concrete lip under every wheel frame, and paint a shadow on it that moves with the spin |

The first three just remap which source PNG each sprite uses, so the art files,
`manifest.json`, and `object.json` never change on disk. The fourth one adds a
little art file in `_padart/`. Anything here is easy to undo by editing
`build_parkobj.py` and rebuilding.

## How the build works

`build_parkobj.py` does this.

1. Reads `manifest.json`, which is 247 sprite entries, each with a source PNG and
   an x and y offset.
2. Remaps some of those entries to point at different frames. This is where all
   the custom stuff happens.
3. Converts every PNG to the RCT2 game palette with `to_palette_png`, using the
   matching `_base_sprites/` frame so the wheel and car pixels keep their
   recolorable indices while the painted hat stays put.
4. Runs `openrct2 sprite build` to make `images.dat`.
5. Zips `object.json` and `images.dat` into `el_sombrero.parkobj` and copies it
   into `~/Library/Application Support/OpenRCT2/object`.

Run it with `python3 build_parkobj.py`.

## The frame layout

Figuring out the frame layout is what made all of this possible.

| Frames | What they are |
|--------|------|
| 0 to 2 | Preview, metadata, and a tiny transparent placeholder (frame 1) |
| 3 to 30 | Flat wheel, used when the ride is stopped or slow |
| 31 to 198 | 14 tilt bands, 12 rotation frames each (more below) |
| 199 to 246 | Seated riders, drawn on top of the wheel for each filled seat |

### The tilt bands

The wheel's tilt, from flat to almost vertical, is stored as 14 bands. Each band
has 12 rotation frames, and they sit on a grid starting at frame 31. So band b
(0 through 13) is frames `31 + b*12` through `31 + b*12 + 11`.

A couple of things to know.

- Tilt is the slow loop and rotation is the fast loop. Inside one band the tilt
  stays the same and the 12 frames are 12 steps of rotation.
- You can see it in the sprite widths. The wheel ellipse gets narrower as it
  tilts, and the width stays flat for exactly 12 frames before it steps, at
  frames 31, 43, 55, 67, and so on.
- Because of that, the matching rotation step in any two bands is always 12
  frames apart, which is the whole trick behind the smooth spin fix.

The game still works out the tilt and rotation on its own and asks for a frame
number. All we do is change what art that frame number points at.

## Custom things 1 and 2, flat spin that stays smooth

The stock Enterprise tilts its wheel up toward vertical as it spins, but the real
El Sombrero stays flat. The tilt is baked into the game and no `object.json`
setting turns it off. What we can do is make every steep tilt frame draw a
flatter one, so the wheel never looks like it tilts past the amount we pick.

There was a fun bug along the way. The first try assumed tilt bands were 32 frames
and remapped with `% 32`. But the bands are really 12 frames, so at full speed,
when the game sits in the top band and cycles its 12 frames, the `% 32` math reset
the rotation every 12th frame. The spin stuttered and looked like it was running
backwards. The fix was to use the real 12 frame length, so each steep frame maps
to the same rotation step in the capped band and the spin stays in phase.

Here's the code.

```python
BAND_ORIGIN = 31
BAND_LEN    = 12
CAP_BAND    = 2          # frames 55 to 66, the gentle fan out we settled on
cap_start   = BAND_ORIGIN + CAP_BAND * BAND_LEN   # = 55
for i in range(cap_start + BAND_LEN, 199):        # remap bands above CAP_BAND
    phase = (i - BAND_ORIGIN) % BAND_LEN
    manifest[i] = dict(manifest[cap_start + phase])
```

The tilt ramps up to band `CAP_BAND` as the ride speeds up, then holds there, and
the 12 rotation frames keep cycling cleanly at any speed.

### Tuning the tilt

`CAP_BAND` is the only knob.

| `CAP_BAND` | Frames at max tilt | Look |
|------------|------|------|
| 0 | 31 to 42 | Almost flat, barely any fan out |
| 1 | 43 to 54 | Slight tilt |
| 2 (current) | 55 to 66 | Gentle fan out |
| 3 and up | 67 to 78 and beyond | More and more tilt, toward stock |

One heads up. At very high speed the wheel can look like it spins backwards.
That's just a strobe effect from 12 rotation steps going fast, like a wagon wheel
in a movie. It isn't the phase bug and you can't fix it by remapping.

## Custom thing 3, hide only the riders that clip the sombrero

Seated riders are drawn as little sprites for each seat, frames 199 to 246,
painted after the wheel. The riders on the back of the wheel land high on the
screen, right over the tall cone, so they show up in front of the hat with their
heads floating on it.

The obvious fixes don't work.

- `drawOrder` (we tried 0, 6, 7, 14, 15) only changes how ride pieces layer
  against each other, not against riders. No help.
- RCT2 has no per pixel or per sprite flag for this.
- The plugin API doesn't expose a guest's seat, the camera angle, or any way to
  hide one guest, so a script can't pick them out either.
- Hiding every rider works, but then all the seats look empty.

The thing that does work. Each rider frame has a fixed spot on the screen baked
into it, its y offset. The game picks which frame a seat uses from
`spin + CurrentRotation*4 + seatRotation`, so whichever seat is at the back always
gets a back frame, on its own, for every camera angle and all through the spin. So
we hide just the back frames, the ones up near the cone, and:

- the far riders never clip the hat because they simply aren't drawn,
- the near riders still show,
- the far cars have their backs to you anyway, so nothing looks missing,
- and it's right from all 4 camera angles without ever knowing a seat number.

Here's the code.

```python
BACK_ARC_Y_CUTOFF = 0    # hide rider frames at or above this screen y (near the cone)
for i in range(199, 247):
    if manifest[i]["y"] < BACK_ARC_Y_CUTOFF:
        manifest[i] = dict(manifest[1])   # tiny transparent placeholder, so it's hidden
    # otherwise it's a front rider, clear of the cone, so leave it alone
```

With the cutoff at 0 this hides 21 back frames and keeps 27 front ones.

- Hidden: 202 to 208, 218 to 224, 234 to 240
- Kept: 199 to 201, 209 to 217, 225 to 233, 241 to 246

### Tuning the riders

`BACK_ARC_Y_CUTOFF` is the knob. Lower it (say to -5) if a side car still nicks
the brim of the cone. Raise it (say to 5) if too many riders vanish.

## Custom thing 4, a concrete pad with a moving shadow

The goal was to sit the ride on a light concrete pad instead of bare dirt.

The catch is that a pad baked into the wheel sprite only shows up if it stays
inside the ride's own footprint tiles. A big ground circle spills onto the
neighboring tiles, and their ground gets painted after the ride and covers it.
The wheel itself is fine because it's up in the air, but anything at ground level
that spills out gets hidden. So the pad has to hug the wheel. It's really just the
front lip of a pad that you can see, not a whole plaza.

The art started as a hand painted lip, then got boiled down to one world
positioned template. `_padart/world_pad.png` holds the lip's shape and
`_padart/world_pad.json` holds where it sits in world coordinates. Only the shape
gets used. It's filled with flat concrete when the build runs.

The build does this in `stamp_world_pad`, on wheel frames 3 to 198, after the
palette step so the cars keep their recoloring.

1. Fill the lip shape with flat concrete (`PAD_BASE_RGB`) at its fixed world spot
   (`world_origin - frame_offset`), so it stays put while the wheel spins.
2. Paint the ride's shadow onto the lip by taking this frame's wheel shape,
   shifting it by `SHADOW_SHIFT`, and darkening the lip there with
   `RIDE_SHADOW_RGB`. Because the wheel shape rotates frame to frame, the shadow
   sweeps across the pad.
3. Lay the wheel and cars back on top so they cover the lip wherever they overlap.

So the concrete stays still, because it's the ground, while the shadow moves,
because the ride above it moves. And none of this touches the car pixels, so the
cars still recolor.

### Tuning

- `SHADOW_SHIFT = (-3, 6)` sets the shadow's direction and length, down and to
  the left. A bigger y shows more lit concrete past the shadow, so the movement
  reads better.
- `RIDE_SHADOW_RGB` and `PAD_BASE_RGB` set how dark the shadow is and how light
  the concrete is.
- `USE_WORLD_PAD = False` turns the pad off completely.

The template in `_padart/` was made once by pulling the hand painted lip out of a
handful of frames and merging them in world coordinates. The merged `world_pad.png`
is checked in, so normal rebuilds just reuse it.

## Quick check after building

Run `python3 build_parkobj.py`, reload in OpenRCT2 (close and reopen the park, or
remove and replace the ride), and look for these.

1. Tilt. The wheel ramps to the gentle fan out and holds. It never flips to
   vertical.
2. Smooth spin. Speed it up to full and back down. The spin stays steady, no
   stutter.
3. Riders loading. The front cars show riders, the back shows none, and nothing
   clips the cone.
4. Camera angles. Rotate through all 4. The back riders stay hidden in every
   view. This is the important one.
5. Riders spinning. Riders show on the front and vanish behind the cone as they
   go around, which looks like proper occlusion.

## The files

| File | What it is | Did we change it |
|------|------|------|
| `build_parkobj.py` | The build script, where all the custom stuff lives | yes |
| `manifest.json` | The source PNG and offset for each frame | no |
| `object.json` | The ride definition, like ride type, seats, and colors | no |
| `sprites/` | The source art for the wheel, hat, and riders | no |
| `_base_sprites/` | The original Enterprise frames, used as a palette reference | no |
| `_padart/` | The concrete pad shape | yes, added |
| `el_sombrero.parkobj` | The packed ride that gets installed | generated |

Everything here is a build time sprite swap, so undoing any of it is just editing
the matching block in `build_parkobj.py` and rebuilding.
