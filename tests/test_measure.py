"""measure.py on synthetic frames, textures and clips: python3 -m unittest tests.test_measure"""

import contextlib
import io
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import measure  # noqa: E402

DARK, ORANGE, PALE, RED = (20, 20, 40), (255, 140, 0), (240, 235, 230), (200, 30, 30)


class MeasureTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)

    def save(self, image, name):
        path = self.dir / name
        image.save(path)
        return str(path)

    def run_measure(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            try:
                code = measure.main([str(a) for a in argv])
            except SystemExit as exit:
                code = exit.code
        return code, json.loads(out.getvalue()) if out.getvalue() else None

    def split(self, left, right, share=0.5, size=(200, 100)):
        image = Image.new("RGB", size, right)
        ImageDraw.Draw(image).rectangle((0, 0, int(size[0] * share) - 1, size[1]), fill=left)
        return image

    def flags(self, *argv):
        code, result = self.run_measure(*argv)
        flags = result["flags"] if "flags" in result else result["results"][0]["flags"]
        self.assertEqual(code, 1 if flags else 0)
        return flags

    # tone

    def test_tone_flags_each_problem_alone_and_stays_quiet_on_a_readable_frame(self):
        self.assertEqual(self.flags("tone", self.save(self.split(PALE, DARK), "pale.png")), ["washed_out"])
        self.assertEqual(self.flags("tone", self.save(self.split((255, 255, 255), RED, 0.2), "blown.png")), ["blown_out"])
        self.assertEqual(self.flags("tone", self.save(Image.new("RGB", (64, 64), (90, 100, 120)), "flat.png")), ["flat"])
        self.assertEqual(self.flags("tone", self.save(self.split(DARK, ORANGE), "ok.png")), [])

    def test_tone_base_scopes_the_measure_to_the_effect(self):
        base = Image.new("RGB", (200, 100), DARK)
        frame = base.copy()
        ImageDraw.Draw(frame).rectangle((0, 0, 39, 49), fill=PALE)  # a pale puff on 10% of the frame
        ImageDraw.Draw(frame).rectangle((100, 0, 119, 49), fill=ORANGE)  # and colour on 5%
        frame_path, base_path = self.save(frame, "puff.png"), self.save(base, "base.png")
        self.assertEqual(self.flags("tone", frame_path), [])
        code, result = self.run_measure("tone", frame_path, "--base", base_path)
        self.assertEqual((code, result["results"][0]["flags"], result["results"][0]["region"]), (1, ["washed_out"], 0.15))
        veil = base.copy()
        ImageDraw.Draw(veil).rectangle((0, 0, 99, 99), fill=(50, 50, 70))  # a faint dark-on-dark veil
        self.assertEqual(self.flags("tone", self.save(veil, "veil.png"), "--base", base_path), ["flat"])

    # texture

    def test_texture_size_rules(self):
        self.assertEqual(self.flags("texture", self.save(Image.new("RGBA", (100, 100)), "odd.png")), ["not_power_of_two"])
        self.assertEqual(self.flags("texture", self.save(Image.new("RGBA", (2048, 16)), "big.png")), ["over_1024"])
        self.assertEqual(self.flags("texture", self.save(Image.new("RGBA", (256, 64)), "fine.png")), [])

    def test_texture_alpha_usage(self):
        dot = Image.radial_gradient("L").point(lambda v: max(0, 255 - 2 * v))  # a glow that fades out before the edge
        soft = Image.new("RGBA", dot.size, (255, 255, 255, 0))
        soft.putalpha(dot)
        additive = Image.merge("RGB", [dot] * 3)
        card = Image.new("RGB", (256, 256), (128, 128, 128))
        card.paste(additive.crop((64, 64, 192, 192)), (64, 64))
        for image, alpha, flags in ((soft, "real", []), (additive, "black-additive", []), (card, "opaque", ["opaque_card"])):
            code, result = self.run_measure("texture", self.save(image, f"{alpha}.png"))
            self.assertEqual((result["results"][0]["alpha"], result["results"][0]["flags"], code), (alpha, flags, int(bool(flags))))

    def test_texture_line_brightness(self):
        bar = Image.new("RGB", (256, 64))
        ImageDraw.Draw(bar).rectangle((0, 16, 255, 47), fill=(255, 255, 255))
        soft = Image.new("RGB", (256, 64))
        for k in range(16):  # a stroke that is only full in its core
            ImageDraw.Draw(soft).line((0, 32, 255, 32), fill=(16 * k + 15,) * 3, width=32 - 2 * k)
        self.assertEqual(self.flags("texture", "--kind", "line", self.save(bar, "bar.png")), ["line_too_full"])
        self.assertEqual(self.flags("texture", "--kind", "line", self.save(soft, "soft.png")), [])

    def test_texture_tile_seams_and_opacity(self):
        def wave(x, y):
            return int(128 + 60 * math.cos(2 * math.pi * x / 64) + 60 * math.cos(2 * math.pi * y / 64))
        tile = Image.new("L", (64, 64))
        tile.putdata([wave(i % 64, i // 64) for i in range(64 * 64)])
        clear = tile.convert("RGBA")
        clear.putalpha(128)
        self.assertEqual(self.flags("texture", "--kind", "tile", self.save(tile.convert("RGB"), "tile.png")), [])
        self.assertEqual(self.flags("texture", "--kind", "tile", self.save(Image.linear_gradient("L"), "ramp.png")), ["seam"])
        self.assertEqual(self.flags("texture", "--kind", "tile", self.save(clear, "clear.png")), ["tile_not_opaque"])

    def test_texture_ring_evenness(self):
        even = Image.new("RGB", (256, 256))
        ImageDraw.Draw(even).ellipse((28, 28, 228, 228), outline=(255, 255, 255), width=12)
        uneven = Image.new("RGB", (256, 256))
        ImageDraw.Draw(uneven).ellipse((28, 28, 228, 228), outline=(120, 120, 120), width=4)
        ImageDraw.Draw(uneven).arc((28, 28, 228, 228), 200, 320, fill=(255, 255, 255), width=30)
        self.assertEqual(self.flags("texture", "--kind", "ring", self.save(even, "even.png")), ["clip_art_ring"])
        self.assertEqual(self.flags("texture", "--kind", "ring", self.save(uneven, "uneven.png")), [])

    def sheet(self, radii, size=256, n=2):
        image, cell = Image.new("RGB", (size, size)), size // n
        for i, r in enumerate(radii):
            cx, cy = (i % n) * cell + cell // 2, (i // n) * cell + cell // 2
            ImageDraw.Draw(image).ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 255, 255))
        return self.save(image, f"sheet-{'-'.join(map(str, radii))}.png")

    def test_texture_flipbook_grid_and_frames(self):
        code, result = self.run_measure("texture", "--kind", "flipbook", self.sheet([10, 25, 40, 0]))
        book = result["results"][0]["flipbook"]
        self.assertEqual((code, book["grid"], book["used"], book["trailing_blank"], book["wasted"]), (0, 2, 3, 1, []))
        self.assertEqual(self.flags("texture", "--kind", "flipbook", self.sheet([40, 40, 41, 20])), ["wasted_frames"])
        whole = Image.new("RGB", (256, 256))
        ImageDraw.Draw(whole).ellipse((8, 8, 248, 248), fill=(255, 255, 255))
        path = self.save(whole, "whole.png")
        self.assertEqual(self.flags("texture", "--kind", "flipbook", path), ["no_grid"])
        self.assertIn("cell_bleed", self.flags("texture", "--grid", "2", path))

    # clip

    def frames(self, levels):
        folder = self.dir / "frames"
        folder.mkdir()
        for i, level in enumerate(levels):
            image = Image.new("RGB", (160, 90), DARK)
            if level:
                ImageDraw.Draw(image).rectangle((40, 20, 40 + level, 70), fill=ORANGE)
            image.save(folder / f"f{i:02d}.png")
        return folder

    def test_clip_timing_colour_and_second_ignition(self):
        code, result = self.run_measure("clip", self.frames([0, 0, 0, 60, 80, 60, 40, 20, 10, 0, 0, 0]))
        self.assertEqual((code, result["flags"]), (0, []))
        self.assertEqual((result["onset_s"], result["flash_s"], result["to_half_s"]), (0.1, round(4 / 30, 3), round(3 / 30, 3)))
        self.assertEqual(result["colours"]["flash"], "#ff8c00")
        shutil.rmtree(self.dir / "frames")
        code, result = self.run_measure("clip", self.frames([0, 0, 80, 40, 10, 60, 10, 0]), "--fps", 10)
        self.assertEqual((code, result["flags"]), (1, ["second_ignition"]))

    def test_clip_video_uses_ffmpeg_or_skips_cleanly(self):
        folder = self.frames([0, 0, 0, 60, 80, 60, 40, 20, 10, 0, 0, 0])
        video = self.dir / "clip.mkv"
        with mock.patch.object(measure.shutil, "which", return_value=None):
            video.write_bytes(b"x")
            self.assertEqual(self.run_measure("clip", video), (0, {"clip": str(video), "skipped": "ffmpeg not installed", "flags": []}))
        if not shutil.which("ffmpeg"):
            self.skipTest("ffmpeg not installed")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", "30", "-pattern_type", "glob", "-i", f"{folder}/*.png",
                        "-c:v", "ffv1", str(video)], check=True)
        code, result = self.run_measure("clip", video)
        self.assertEqual((code, result["frames"], result["flash_s"]), (0, 12, round(4 / 30, 3)))

    def test_usage_errors_exit_2(self):
        self.assertEqual(self.run_measure()[0], 2)
        self.assertEqual(self.run_measure("tone", self.dir / "missing.png")[0], 2)
        self.assertEqual(self.run_measure("clip", self.dir / "missing")[0], 2)
        self.assertEqual(self.run_measure("texture", "--grid", "3", "x.png")[0], 2)


if __name__ == "__main__":
    unittest.main()
