#!/usr/bin/env python3
"""Harvest: bring work done in a farm Studio back into a Rojo project, applying only what changed there.

  harvest.py open [--project DIR] [--tag T]   build the project's place, keep a copy as the base, open farm Studio T
  harvest.py apply [--project DIR] --tag T    export the Rojo-mapped roots from farm Studio T (Chrrxs export_rbxm),
                                              apply the diff to the project

Work in the farm Studio through MCP between the two (Edit DataModel only). Close it with
`studio_farm.py close T`. Needs rojo 7.5+ (syncback) and lune on PATH, and chrrxs_mcp in farm.toml.
"""
import argparse
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
import time

import studio_farm
from studio_farm import Bridge

SPLICE = Path(__file__).resolve().parent / "splice.luau"
CONFLICT = 4  # exit code: a changed file also moved in the project since open; left alone


def mapped_roots(project):
    """Dotted DataModel paths of every $path node in a Rojo project, e.g. ReplicatedStorage.Shared."""
    roots = []

    def walk(node, path):
        if "$path" in node and path:
            roots.append(".".join(path))
            return
        for name, child in node.items():
            if not name.startswith("$") and isinstance(child, dict):
                walk(child, path + [name])

    walk(json.loads(Path(project).read_text())["tree"], [])
    return roots


NOISE = {"SerializedOverrides", "ExplorerIconContent"}  # Studio-only properties every exported instance carries


def files(root, dirs):
    return {str(p.relative_to(root)): p.read_bytes() for d in dirs for p in sorted((root / d).rglob("*")) if p.is_file()}


def noise(rel, data, before):
    """A .meta.json syncback writes only for Studio's own bookkeeping properties."""
    if before is not None or not rel.endswith(".meta.json"):
        return False
    meta = json.loads(data)
    return set(meta) <= {"properties"} and set(meta.get("properties", {})) <= NOISE


def apply(project_dir, base, models, project_file="default.project.json"):
    """Apply to project_dir only what `models` ({dotted path: rbxm}) change against `base`, the place the farm opened.
    Tools run from project_dir, since Rokit shims find rokit.toml from the working directory up and a temporary
    directory has none. Both sides go through rojo syncback in temporary copies, so syncback's own rewrites (every file touched, the
    project file reordered, Studio bookkeeping .meta.json) cancel out. A changed file that also moved in project_dir
    since `base` is a conflict: reported, left alone. Returns (applied, conflicts)."""
    project_dir = Path(project_dir)
    project = json.loads((project_dir / project_file).read_text())
    dirs = sorted({node["$path"] for node in _path_nodes(project["tree"])})
    sides = {}
    with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as tmp:
        spliced = Path(tmp) / "spliced.rbxl"
        subprocess.run(["lune", "run", str(SPLICE), str(base), str(spliced),
                        *(f"{path}={file}" for path, file in models.items())], cwd=project_dir, check=True)
        for side, place in (("before", base), ("after", spliced)):
            copy = Path(tmp) / side
            copy.mkdir()
            shutil.copy(project_dir / project_file, copy)
            for d in dirs:
                shutil.copytree(project_dir / d, copy / d)
            subprocess.run(["rojo", "syncback", str(copy / project_file), "--input", str(place), "-y"],
                           cwd=project_dir, check=True, capture_output=True)
            sides[side] = files(copy, dirs)
    before, after = sides["before"], sides["after"]
    applied, conflicts = [], []
    for rel in sorted(set(before) | set(after)):
        old, new = before.get(rel), after.get(rel)
        if old == new or (new is not None and noise(rel, new, old)):
            continue
        target = project_dir / rel
        current = target.read_bytes() if target.exists() else None
        if current != old:
            conflicts.append(rel)
            continue
        if new is None:
            target.unlink()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(new)
        applied.append(rel)
    return applied, conflicts


def _path_nodes(node):
    if "$path" in node:
        yield node
    for name, child in node.items():
        if not name.startswith("$") and isinstance(child, dict):
            yield from _path_nodes(child)


def run_dir(tag):
    return Path(studio_farm.config().state_dir).resolve().parent / "harvest" / tag


def open_(args):
    tag = args.tag or f"harvest-{secrets.token_hex(3)}"
    out = run_dir(tag)
    out.mkdir(parents=True, exist_ok=True)
    # Built with the tag baked in (FarmTag), so the export and this base agree on every farm attribute.
    built = studio_farm.build_place(args.project, tag, out)
    shutil.copy(built, out / "place.rbxl")  # apply diffs the farm Studio's export against exactly this
    studio = studio_farm.open_instance(out / "place.rbxl", tag, args.owner)
    studio.bridge.close()
    print(json.dumps({"id": studio.id, "tag": tag, "pid": studio.pid, "base": str(out / "place.rbxl")}))
    print(f"edit farm Studio {tag} (studio_id {studio.id}); never click its Rojo connect prompt; then: "
          f"harvest.py apply --project {args.project} --tag {tag}")


def chrrxs_instance(bridge, tag, wait=60):
    """Chrrxs's instance id for farm Studio `tag`, matched by its placeName "<tag>.rbxl" (the plugin joins the
    bridge a few seconds after the session starts it)."""
    for _ in range(wait // 2):
        listed = json.loads(bridge.tool("get_connected_instances"))["instances"]
        hits = [i for i in listed if i.get("placeName") == f"{tag}.rbxl"]
        if len(hits) == 1:
            return hits[0]["id"]
        time.sleep(2)
    raise RuntimeError(f"Chrrxs lists no single edit instance for {tag}: {listed}")


def export(tag, roots, out):
    """Each mapped root as <dotted path>.rbxm in out, exported by Chrrxs export_rbxm from farm Studio `tag`. The
    Chrrxs plugin in every farm Studio joins the bridge this call starts on the host (127.0.0.1:58741 there, one
    holder per Studio); export_rbxm writes on the host, so the files come back by scp."""
    remote = studio_farm.powershell(f'$h = "$dir\\harvest-{tag}"; New-Item -ItemType Directory -Force $h | Out-Null; $h')
    bridge = Bridge(studio_farm.required("chrrxs_mcp"))
    try:
        bridge.initialize("harvest", "2025-06-18")
        instance = chrrxs_instance(bridge, tag)
        for path in roots:
            reply = bridge.tool("export_rbxm", instance_paths=[f"game.{path}"], output_path=f"{remote}\\{path}.rbxm",
                                target="edit", instance_id=instance)
            if '"error"' in reply:
                raise RuntimeError(f"export_rbxm {path}: {reply[:300]}")
            print(f"exported {path}", flush=True)
    finally:
        bridge.close()
    try:
        for path in roots:
            subprocess.run(["scp", "-q", "-o", "BatchMode=yes",
                            f"{studio_farm.required('host')}:{remote.replace(chr(92), '/')}/{path}.rbxm",
                            str(out)], check=True, timeout=120)
    finally:
        studio_farm.powershell(f'Remove-Item -Recurse -Force "{remote}" -ErrorAction SilentlyContinue')


def apply_(args):
    project_file = studio_farm.config().rojo_project
    base = run_dir(args.tag) / "place.rbxl"
    if not base.exists():
        raise RuntimeError(f"{base} missing: apply needs the base `open` kept")
    out = base.parent / "export"
    out.mkdir(parents=True, exist_ok=True)
    roots = mapped_roots(args.project / project_file)
    export(args.tag, roots, out)
    applied, conflicts = apply(args.project, base, {path: out / f"{path}.rbxm" for path in roots}, project_file)
    print("applied:", *applied or ["nothing"], sep="\n  ")
    if conflicts:
        print("CONFLICT (changed in the project since open, left alone; port by hand):", *conflicts, sep="\n  ")
    print(subprocess.run(["git", "diff", "--stat", "--", *applied], cwd=args.project, capture_output=True,
                         text=True).stdout)
    return CONFLICT if conflicts else 0


def main():
    os.environ["PATH"] = f"{Path.home()}/.rokit/bin:" + os.environ["PATH"]
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    opener = commands.add_parser("open")
    opener.add_argument("--tag", help="default harvest-<random>")
    opener.add_argument("--owner", type=int, help="local PID whose exit lets reap close it; default the caller")
    applier = commands.add_parser("apply")
    applier.add_argument("--tag", required=True)
    for command in (opener, applier):
        command.add_argument("--project", type=Path, default=Path("."), help="Rojo project directory (default .)")
    args = parser.parse_args()
    args.project = args.project.resolve()
    return {"open": open_, "apply": apply_}[args.command](args) or 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, KeyError, RuntimeError, ValueError, TimeoutError, EOFError, subprocess.SubprocessError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(1)
