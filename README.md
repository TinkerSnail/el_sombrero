# El Sombrero 🌮

A custom [OpenRCT2](https://openrct2.org) flat ride: a spinning wheel crowned
with a giant rotating sombrero. It's built on the game's **Enterprise** ride type
but reworked to behave like the real *El Sombrero* ride at Six Flags: it spins
flat (with the usual start / stop / acceleration) instead of tilting up to
vertical.

![El Sombrero spinning in-game](media/demo.gif)

> ▶️ Full-quality clip: [`media/demo.mp4`](media/demo.mp4)

## Install

1. Download **`el_sombrero.parkobj`** from this repo (or from the
   [Releases](../../releases) page).
2. Drop it into your OpenRCT2 `object` folder:
   - **macOS:** `~/Library/Application Support/OpenRCT2/object`
   - **Windows:** `%USERPROFILE%\Documents\OpenRCT2\object`
   - **Linux:** `~/.config/OpenRCT2/object`
3. Launch OpenRCT2. El Sombrero appears in the ride list under **Thrill Rides**.

## Features

- **Flat spin**: holds a gentle fan-out tilt instead of flipping to vertical
  like the stock Enterprise.
- **Smooth rotation** at every spin speed (no jitter or stutter).
- **Custom painted sombrero** crowning the wheel.
- **Concrete pad** under the ride, with a shadow that sweeps as it spins.
- Riders are drawn correctly without clipping through the hat.

![El Sombrero spinning on its concrete pad](media/screenshot.png)

## Building from source

The ride is packed from source PNGs by a Python script:

```bash
python3 build_parkobj.py
```

This palette-converts the sprites, packs `images.dat`, and zips it with
`object.json` into `el_sombrero.parkobj` (also installing it to your local
OpenRCT2 object folder).

Requires Python 3 with `Pillow` and `numpy`, plus an OpenRCT2 install (the script
calls its `sprite build` command).

## How it works

All of the custom behavior (flat spin, smooth rotation, rider occlusion) is
implemented as build-time **sprite remaps** in `build_parkobj.py` — the source
art, `manifest.json`, and `object.json` are never edited destructively. The full
technical write-up, including the Enterprise frame layout and the tuning knobs,
is in [`CUSTOMIZATIONS.md`](CUSTOMIZATIONS.md).

## Credits

Created by **TinkerSnail**. The wheel and car artwork is derived from
RollerCoaster Tycoon 2's original Enterprise ride; the painted sombrero is
original work. You need RollerCoaster Tycoon 2 game assets (via OpenRCT2) to play.
