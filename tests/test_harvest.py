"""Offline check of harvest's apply step on a small fixture project. A lune edit stands in for the farm Studio work
(adds a module and a model, rewrites Rock); meanwhile the project moves on (Rock and Burst edited by someone else).
Apply must write exactly the two new files, report Rock as a conflict, keep both project edits and leave
default.project.json alone. Needs rojo 7.5+ and lune (skipped without them)."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import harvest  # noqa: E402

TOOLS = os.pathsep.join([str(Path.home() / ".rokit/bin"), os.environ["PATH"]])
HAVE_TOOLS = all(shutil.which(tool, path=TOOLS) for tool in ("rojo", "lune"))

PROJECT = {"name": "fixture", "tree": {
    "$className": "DataModel",
    "ReplicatedStorage": {"$className": "ReplicatedStorage", "Shared": {"$path": "src/shared"}},
    "StarterPlayer": {"$className": "StarterPlayer", "StarterPlayerScripts": {
        "$className": "StarterPlayerScripts", "Client": {"$path": "src/client"}}}}}

EDIT = """local fs = require("@lune/fs")
local roblox = require("@lune/roblox")
local game = roblox.deserializePlace(fs.readFile("base.rbxl"))
local client = game:GetService("StarterPlayer").StarterPlayerScripts.Client
local shared = game:GetService("ReplicatedStorage").Shared
local module = roblox.Instance.new("ModuleScript")
module.Name, module.Source, module.Parent = "FarmProbe", "return 1\\n", client
client.Rock.Source = "return 'farm'\\n"
local model = roblox.Instance.new("Model")
model.Name = "FarmModel"
roblox.Instance.new("Part").Parent = model
model.Parent = shared
fs.writeFile("client.rbxm", roblox.serializeModel({ client }))
fs.writeFile("shared.rbxm", roblox.serializeModel({ shared }))
"""


@unittest.skipUnless(HAVE_TOOLS, "rojo and lune not installed")
class HarvestTests(unittest.TestCase):
    def test_apply_writes_only_the_farm_changes(self):
        os.environ["PATH"] = TOOLS
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            work = tmp / "project"
            for name in ("shared/Util", "client/Rock", "client/Burst"):
                (work / "src" / f"{name}.luau").parent.mkdir(parents=True, exist_ok=True)
                (work / "src" / f"{name}.luau").write_text(f"return '{name}'\n")
            (work / "default.project.json").write_text(json.dumps(PROJECT, indent=2))
            shutil.copy(ROOT / "rokit.toml", tmp)  # Rokit shims resolve tools from the working directory up
            subprocess.run(["rojo", "build", "default.project.json", "-o", str(tmp / "base.rbxl")], cwd=work,
                           check=True, capture_output=True)
            (tmp / "edit.luau").write_text(EDIT)
            subprocess.run(["lune", "run", "edit.luau"], cwd=tmp, check=True)
            for name in ("Rock", "Burst"):  # someone else's edits after the farm run started
                with (work / f"src/client/{name}.luau").open("a") as file:
                    file.write("-- moved on\n")
            before = harvest.files(work, ["src/shared", "src/client"])
            project = (work / "default.project.json").read_bytes()
            self.assertEqual(harvest.mapped_roots(work / "default.project.json"),
                             ["ReplicatedStorage.Shared", "StarterPlayer.StarterPlayerScripts.Client"])
            applied, conflicts = harvest.apply(work, tmp / "base.rbxl", {
                "StarterPlayer.StarterPlayerScripts.Client": tmp / "client.rbxm",
                "ReplicatedStorage.Shared": tmp / "shared.rbxm"})
            after = harvest.files(work, ["src/shared", "src/client"])
            self.assertEqual(applied, ["src/client/FarmProbe.luau", "src/shared/FarmModel.rbxm"])
            self.assertEqual(conflicts, ["src/client/Rock.luau"])
            self.assertEqual(sorted(set(after) - set(before)), applied)
            self.assertEqual([name for name in before if after[name] != before[name]], [])  # nothing else touched
            self.assertEqual(after["src/client/FarmProbe.luau"], b"return 1\n")
            self.assertEqual((work / "default.project.json").read_bytes(), project)


if __name__ == "__main__":
    unittest.main()
