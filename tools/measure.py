#!/usr/bin/env python3
"""Measure captured Roblox VFX frames, particle and beam textures, and reference clips. Pillow only; ffmpeg optional.

  measure.py tone <png...> [--base effect-free.png]    washed-out, blown-out or flat frames
  measure.py texture <png...> [--kind sprite|line|tile|ring|flipbook] [--grid 2|4|8]
  measure.py clip <video-or-frame-dir> [--fps 30]      timing and colour of a reference effect

Prints JSON. Exit 0 when clean, 1 when any flag is raised, 2 on usage errors. Constants marked "sheet" come from
skills/roblox-vfx-phasing/references/measured.md; the rest are our own choices, each with its reason."""

import argparse
import json
import math
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import tempfile

from PIL import Image, ImageChops, ImageStat

# tone
PALE_VALUE = 191        # HSV value 75% and up: bright enough to read as pale on screen
PALE_SATURATION = 64    # HSV saturation 25% and under: the colour has drifted toward white
WASHED_OUT = 0.40       # sheet: a pale pixel share over about 40% reads washed out (studied videos 2 to 21%)
CLIPPED = 250           # every channel at 250 or more is clipped white
BLOWN_OUT = 0.15        # own: a white-hot core is 1 or 2 small front layers; more clipped area than this erases shape
FLAT = 48               # own: under 48 of 255 luma separation (spread, or contrast against base) does not read
SPREAD_TAIL = 0.01      # own: without a base, spread is the 1st to 99th percentile, so an effect on 1% of the frame counts
CHANGED = 24            # own: a luma change from the base frame above this is effect; below is noise and compression

# texture
MAX_SIDE = 1024         # sheet: Roblox caps a texture side at 1024
INK_MIN = 10            # own: coverage (brightest channel times alpha) under 4% is invisible in game
FULL = 230              # own: coverage of 90% and up counts as full brightness (brightest channel, so pure hues count)
BLACK_BORDER = 16       # own: an opaque texture with most of its border under this value is a black-background additive
LINE_FULL_MAX = 0.26    # sheet: line strokes are about 13% near full and far above reads cheap; we flag at twice that
SEAM_MAX = 0.04         # sheet: tiles keep opposite edges within about 4%
RING_SECTORS = 72       # own: 5 degree sectors resolve a broken stroke without counting antialiasing
RING_EVEN_BRIGHT = 0.15  # sheet: brightness spread under 15% ...
RING_EVEN_WIDTH = 0.25   # sheet: ... with width spread under 25% reads as clip art
GRIDS = (8, 4, 2)       # sheet: Roblox built-in flipbook layouts, tried finest first
BLEED_MAX = 0.01        # own: more than 1% of a cell border inked means frames bleed into each other when sampled
WASTED = 0.12           # sheet: a frame whose outline changes less than about 12% from the last is wasted

# clip
CLIP_WIDTH = 160        # own: timing and colour need no detail; small frames keep a long clip fast
ONSET = 0.10            # own: brightening under 10% of the peak is not yet (or no longer) the effect
MIN_FLASH = 2.0         # own: a mean luma rise under 2 of 255 is noise, not a flash
REIGNITE = 0.20         # own: after the flash, a rise of 20% of the peak is a second ignition, smaller is flicker
KINDS = ("sprite", "line", "tile", "ring", "flipbook")


def mask_of(image, test):
    return image.point(lambda v: 255 if test(v) else 0)


def count(binary, region=None):
    return binary.histogram(mask=region)[255]


def percentile(hist, q):
    target, run = q * sum(hist), 0
    for value, n in enumerate(hist):
        run += n
        if run >= target:
            return value
    return 255


def tone(rgb, base=None):
    """Pale and clipped shares over the pixels that differ from base (or the whole frame), and its luma separation:
    mean difference from base over those pixels (contrast), or without base the SPREAD_TAIL percentile spread."""
    luma = rgb.convert("L")
    region = diff = None
    if base is not None:
        diff = ImageChops.difference(luma, base.convert("L").resize(luma.size))
        region = mask_of(diff, lambda v: v > CHANGED)
    total = count(region) if region else rgb.width * rgb.height
    out = {"region": round(total / (rgb.width * rgb.height), 4), "flags": []}
    if not total:
        return out
    _, s, v = rgb.convert("HSV").split()
    pale = ImageChops.multiply(mask_of(v, lambda x: x >= PALE_VALUE), mask_of(s, lambda x: x <= PALE_SATURATION))
    r, g, b = (mask_of(c, lambda x: x >= CLIPPED) for c in rgb.split())
    clipped = ImageChops.multiply(ImageChops.multiply(r, g), b)
    out.update(pale=round(count(pale, region) / total, 4), clipped=round(count(clipped, region) / total, 4))
    if diff:
        out["contrast"] = round(ImageStat.Stat(diff, region).mean[0], 1)
    else:
        hist = luma.histogram()
        out["spread"] = percentile(hist, 1 - SPREAD_TAIL) - percentile(hist, SPREAD_TAIL)
    out["flags"] = [name for name, hit in (("washed_out", out["pale"] > WASHED_OUT),
                                           ("blown_out", out["clipped"] > BLOWN_OUT),
                                           ("flat", out.get("contrast", out.get("spread")) < FLAT)) if hit]
    return out


def spread(values):
    mean = statistics.fmean(values)
    return statistics.pstdev(values) / mean if mean else 0.0


def ring(ink):
    """Brightness and width spread round a ring centred in the texture, as coefficients of variation over sectors."""
    small = ink.resize((256, 256))
    px, peak = small.load(), small.getextrema()[1]
    bright, width = [], []
    for k in range(RING_SECTORS):
        a = 2 * math.pi * k / RING_SECTORS
        ray = [px[int(128 + r * math.cos(a)), int(128 + r * math.sin(a))] for r in range(128)]
        bright.append(max(ray))
        width.append(sum(v >= peak / 2 for v in ray))
    return round(spread(bright), 3), round(spread(width), 3)


def clean(binary, n):
    """True when the n x n grid lines (a 2 px band each) carry almost no ink."""
    w, h = binary.size
    inked = area = 0
    for k in range(1, n):
        for box in ((k * w // n - 1, 0, k * w // n + 1, h), (0, k * h // n - 1, w, k * h // n + 1)):
            band = binary.crop(box)
            inked, area = inked + count(band), area + band.width * band.height
    return inked <= BLEED_MAX * area


def flipbook(binary, grid):
    """Grid (given or found), cells used, trailing blanks, wasted frames and where the largest drawing falls."""
    out = {"grid": grid or next((n for n in GRIDS if clean(binary, n)), None), "flags": []}
    if grid and not clean(binary, grid):
        out["flags"].append("cell_bleed")
    n = out["grid"]
    if not n:
        out["flags"].append("no_grid")
        return out
    w, h = binary.width // n, binary.height // n
    cells = [binary.crop((c * w, r * h, c * w + w, r * h + h)) for r in range(n) for c in range(n)]
    areas = [count(c) for c in cells]
    wasted = []
    for i in range(1, len(cells)):
        union = count(ImageChops.lighter(cells[i - 1], cells[i]))
        if areas[i - 1] and areas[i] and count(ImageChops.difference(cells[i - 1], cells[i])) < WASTED * union:
            wasted.append(i)
    used = [i for i, a in enumerate(areas) if a]
    out.update(cells=len(cells), used=len(used), trailing_blank=len(cells) - 1 - used[-1] if used else len(cells),
               largest_at=round(areas.index(max(areas)) / (len(cells) - 1), 2), wasted=wasted)
    if wasted:
        out["flags"].append("wasted_frames")
    return out


def texture(path, kind="sprite", grid=None):
    im = Image.open(path)
    rgba = im.convert("RGBA")
    w, h = rgba.size
    r, g, b, alpha = rgba.split()
    value = ImageChops.lighter(ImageChops.lighter(r, g), b)
    ink = ImageChops.multiply(value, alpha)
    edges = [value.crop(box).histogram() for box in ((0, 0, w, 1), (0, h - 1, w, h), (0, 0, 1, h), (w - 1, 0, w, h))]
    black = sum(sum(e[:BLACK_BORDER]) for e in edges) / sum(sum(e) for e in edges)
    has_alpha = alpha.getextrema()[0] < 255
    hist = ink.histogram()
    stroke = sum(hist[INK_MIN:])
    out = {"file": str(path), "size": [w, h], "kind": kind,
           "alpha": "real" if has_alpha else "black-additive" if black > 0.5 else "opaque",
           "full_share": round(sum(hist[FULL:]) / stroke, 4) if stroke else 0.0, "flags": []}
    flags = out["flags"]
    if w & (w - 1) or h & (h - 1):
        flags.append("not_power_of_two")
    if max(w, h) > MAX_SIDE:
        flags.append("over_1024")
    if kind != "tile" and out["alpha"] == "opaque":
        flags.append("opaque_card")  # no alpha and no black background: draws as a visible square
    if kind == "line" and out["full_share"] > LINE_FULL_MAX:
        flags.append("line_too_full")
    if kind == "tile":
        rgb = rgba.convert("RGB")
        def seam(a, b):
            return round(statistics.fmean(ImageStat.Stat(ImageChops.difference(rgb.crop(a), rgb.crop(b))).mean) / 255, 4)
        out["seam"] = [seam((0, 0, 1, h), (w - 1, 0, w, h)), seam((0, 0, w, 1), (0, h - 1, w, h))]
        if max(out["seam"]) > SEAM_MAX:
            flags.append("seam")
        if has_alpha:
            flags.append("tile_not_opaque")  # sheet: tiles are opaque
    if kind == "ring":
        out["bright_spread"], out["width_spread"] = ring(ink)
        if out["bright_spread"] < RING_EVEN_BRIGHT and out["width_spread"] < RING_EVEN_WIDTH:
            flags.append("clip_art_ring")
    if kind == "flipbook":
        if w != h:
            flags.append("not_square")
        book = flipbook(mask_of(ink, lambda v: v >= INK_MIN), grid)
        flags += book.pop("flags")
        out["flipbook"] = book
    return out


def hexcolour(rgb, region):
    if not count(region):
        return None
    return "#" + "".join(f"{round(c):02x}" for c in ImageStat.Stat(rgb, region).mean)


def clip(src, fps):
    """Brightness timing (seconds; the first frame must come before the effect) and colours at each beat."""
    src = Path(src)
    with tempfile.TemporaryDirectory() as tmp:
        if src.is_dir():
            files = sorted(p for p in src.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg"))
        elif not src.is_file():
            raise FileNotFoundError(f"no such clip: {src}")
        elif not shutil.which("ffmpeg"):
            return {"clip": str(src), "skipped": "ffmpeg not installed", "flags": []}
        else:
            subprocess.run(["ffmpeg", "-v", "error", "-i", str(src), "-vf", f"fps={fps},scale={CLIP_WIDTH}:-2",
                            f"{tmp}/%05d.png"], check=True, capture_output=True)
            files = sorted(Path(tmp).glob("*.png"))
        if len(files) < 2:
            raise ValueError(f"{src}: need at least 2 frames, found {len(files)}")
        frames = []
        for f in files:
            im = Image.open(f).convert("RGB")
            frames.append(im.resize((CLIP_WIDTH, max(1, im.height * CLIP_WIDTH // im.width))))
    lumas = [f.convert("L") for f in frames]
    means = [ImageStat.Stat(l).mean[0] for l in lumas]
    energy = [max(0.0, m - means[0]) for m in means]
    peak = max(energy)
    out = {"clip": str(src), "frames": len(frames), "fps": fps, "flags": []}
    if peak < MIN_FLASH:
        out["flash_s"] = None
        return out
    at = lambda i: round(i / fps, 3)
    p = energy.index(peak)
    live = [i for i, e in enumerate(energy) if e >= ONSET * peak]
    half = next((i for i in range(p, len(energy)) if energy[i] < peak / 2), None)
    low, reignite = peak, False
    for e in energy[p:]:
        low = min(low, e)
        reignite = reignite or e - low > REIGNITE * peak
    beats = {"onset": live[0], "flash": p, "half": half, "end": live[-1]}
    out.update(onset_s=at(live[0]), flash_s=at(p), to_half_s=None if half is None else at(half - p),
               to_gone_s=at(live[-1] - p), colours={
                   k: None if i is None else hexcolour(frames[i], mask_of(ImageChops.difference(lumas[i], lumas[0]),
                                                                          lambda v: v > CHANGED))
                   for k, i in beats.items()},
               tone_at_flash=tone(frames[p], frames[0]))
    out["flags"] = (["second_ignition"] if reignite else []) + out["tone_at_flash"]["flags"]
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(prog="measure.py", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    t = sub.add_parser("tone", help="washed-out, blown-out or flat captured frames")
    t.add_argument("png", nargs="+")
    t.add_argument("--base", help="the same view without the effect: measure only the pixels the effect changed")
    x = sub.add_parser("texture", help="facts a particle or beam texture should satisfy")
    x.add_argument("png", nargs="+")
    x.add_argument("--kind", choices=KINDS, default="sprite")
    x.add_argument("--grid", type=int, choices=GRIDS, help="flipbook layout; found from clean cell borders if omitted")
    c = sub.add_parser("clip", help="timing and colour facts from a reference video or frame directory")
    c.add_argument("src")
    c.add_argument("--fps", type=float, default=30.0, help="frame rate of a frame directory, or sampling rate of a video")
    args = parser.parse_args(argv)
    try:
        if args.command == "tone":
            base = Image.open(args.base).convert("RGB") if args.base else None
            result = {"results": [{"file": f, **tone(Image.open(f).convert("RGB"), base)} for f in args.png]}
            flagged = any(r["flags"] for r in result["results"])
        elif args.command == "texture":
            kind = "flipbook" if args.grid else args.kind
            result = {"results": [texture(f, kind, args.grid) for f in args.png]}
            flagged = any(r["flags"] for r in result["results"])
        else:
            if args.fps <= 0:
                parser.error("--fps must be positive")
            result = clip(args.src, args.fps)
            flagged = bool(result["flags"])
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"measure.py: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 1 if flagged else 0


if __name__ == "__main__":
    sys.exit(main())
