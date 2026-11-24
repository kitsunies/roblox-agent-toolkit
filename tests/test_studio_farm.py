"""Studio farm config, state and scripts, without touching Studio: python3 -m unittest discover -s tests"""

import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import farm_probe  # noqa: E402
import studio_farm  # noqa: E402

ROJO = shutil.which("rojo") or shutil.which(str(Path.home() / ".rokit/bin/rojo"))


class StudioFarmTests(unittest.TestCase):
    def test_moments_are_ascending_and_capped(self):
        self.assertEqual(farm_probe.parse_moments("0.05, 0.3,1"), [0.05, 0.3, 1.0])
        for bad in ("", "0.3,0.1", "0.1,0.1", "-1", ",".join(str(n) for n in range(9))):
            with self.assertRaises(ValueError):
                farm_probe.parse_moments(bad)

    def test_expect_polls_until_the_attribute_matches(self):
        name, pattern = farm_probe.parse_expect("FlowProbe=^PASS")
        self.assertEqual(name, "FlowProbe")
        self.assertTrue(pattern.search("PASS run1 PASS | run2 PASS") and not pattern.search("run1 PASS"))
        with self.assertRaises(ValueError):
            farm_probe.parse_expect("no-equals")

        class Bridge:
            def __init__(self, values):
                self.values = list(values)

            def tool(self, *_, **__):
                return f"EXPECT {self.values.pop(0)}"

        with mock.patch.object(farm_probe.time, "sleep"):
            self.assertIsNone(farm_probe.expect_attribute(Bridge(["nil", "run1 PASS", "PASS all"]), "s", "FlowProbe=^PASS", 60))
            error = farm_probe.expect_attribute(Bridge(["running", "FAIL run1 FAIL"]), "s", "FlowProbe=^PASS", 60)
        self.assertIn("FAIL run1 FAIL", error)

    def test_expect_runs_the_probe_check_phase_before_each_read(self):
        calls = []

        class Bridge:
            def tool(self, *_, code, **__):
                calls.append(code)
                return "checked" if code == "CHECK" else "EXPECT " + ("PASS" if calls.count("CHECK") >= 2 else "waiting")

        with mock.patch.object(farm_probe.time, "sleep"):
            self.assertIsNone(farm_probe.expect_attribute(Bridge(), "s", "ShopProbe=^PASS", 60, "CHECK"))
        self.assertEqual(calls[0::2], ["CHECK", "CHECK"])  # the check phase runs before every attribute read

    def test_close_refuses_instances_the_farm_did_not_open(self):
        state = {"instances": {"c2-ab12cd": {"id": "farm"}}}
        self.assertEqual(studio_farm.resolve("farm", state), "c2-ab12cd")
        with self.assertRaises(RuntimeError):
            studio_farm.resolve("main", state)

    def test_cap_dialog_is_told_from_a_loaded_window(self):
        self.assertTrue(studio_farm.held_by_cap("[]"))
        self.assertTrue(studio_farm.held_by_cap("[Roblox Studio]"))
        self.assertFalse(studio_farm.held_by_cap(r"[D:\farm\x.rbxl - Roblox Studio]"))
        self.assertFalse(studio_farm.held_by_cap("GONE"))

    def test_capacity_gate_queues_until_room(self):
        samples = iter([(5, 9000), (4, 3000), (6, 9000), (4, 4096)])
        now, logs = [0.0], []

        def sleep(seconds):
            now[0] += seconds

        room = studio_farm.wait_for_room("t", sample=lambda: next(samples), max_studios=5, min_free_mb=4096,
                                         queue=900, sleep=sleep, clock=lambda: now[0], log=logs.append)
        self.assertEqual(room, (4, 4096))
        self.assertEqual(now[0], 30)
        self.assertEqual(len(logs), 1)  # one line per minute queued

    def test_capacity_gate_gives_up_after_the_queue(self):
        now, logs = [0.0], []

        def sleep(seconds):
            now[0] += seconds

        with self.assertRaises(TimeoutError):
            studio_farm.wait_for_room("t", sample=lambda: (9, 5600), queue=900, sleep=sleep, clock=lambda: now[0],
                                      log=logs.append)
        self.assertEqual(now[0], 900)
        self.assertEqual(len(logs), 15)

    def test_open_launches_without_focus_and_parks_windows(self):
        config = studio_farm.load_config(os.devnull)
        guard = studio_farm.guard_script("c2-ab12cd", config)
        self.assertIn("$tag = 'c2-ab12cd'", guard)
        self.assertIn('$dir = "$env:LOCALAPPDATA\\Temp\\studio-farm"', guard)
        self.assertNotRegex(guard, r"@[A-Z]+@")  # every placeholder filled
        self.assertIn("), 7, $false)", guard)  # WScript.Shell Run: SW_SHOWMINNOACTIVE, no wait
        self.assertNotIn("Start-Process", guard)
        self.assertIn("[FarmWindows]::Park($ids, 1180, 800)", guard)
        self.assertIn("Invoke-Interactive 'c2-ab12cd.open'", studio_farm.PS_OPEN.format(tag="c2-ab12cd"))
        self.assertIn("Remove-Interactive '{tag}.open'", studio_farm.PS_CLOSE)  # close ends the guard task too
        self.assertIn("conhost.exe' `\n    -Argument \"--headless", studio_farm.PS_PRELUDE)  # no console window

    def test_config_loads_example_and_rejects_typos(self):
        config = studio_farm.load_config(ROOT / "farm.example.toml")
        self.assertEqual(config.host, "studio-host")
        self.assertEqual(config.studio_mcp[0], "ssh")
        self.assertEqual(config.window, [1180, 800])
        self.assertEqual(studio_farm.load_config(os.devnull).max_studios, 8)  # empty file: defaults
        with tempfile.NamedTemporaryFile("w", suffix=".toml") as bad:
            bad.write('hots = "x"\n')
            bad.flush()
            with self.assertRaises(ValueError):
                studio_farm.load_config(bad.name)

    @unittest.skipUnless(ROJO, "rojo not installed")
    def test_build_bakes_the_tag(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "src").mkdir()
            (project / "src/Hello.luau").write_text("return 1\n")
            (project / "default.project.json").write_text(json.dumps({"name": "fixture", "tree": {
                "$className": "DataModel", "ReplicatedStorage": {"$className": "ReplicatedStorage",
                                                                 "Shared": {"$path": "src"}}}}))
            shutil.copy(ROOT / "rokit.toml", project)
            with mock.patch.dict(os.environ, {"PATH": f"{Path(ROJO).parent}:{os.environ['PATH']}"}), \
                    mock.patch.object(studio_farm, "config", lambda: studio_farm.load_config(os.devnull)):
                place = studio_farm.build_place(project, "unit-tag", tmp)
            self.assertIn(b"unit-tag", place.read_bytes())


if __name__ == "__main__":
    unittest.main()
