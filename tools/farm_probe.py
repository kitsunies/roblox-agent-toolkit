#!/usr/bin/env python3
"""The farm's probe job (`studio_farm.py probe`): build or take a place, play it in a farm instance, run the probe
scripts, poll --expect, capture each --size (filmstrips with --frames, held effect moments with --moments, a UI audit
with --audit) and close.

Probe scripts are plain Luau run through execute_luau. Each gets a header first:
  local CONFIG = { tag = "<farm tag>", phase = "run" }
A client probe is called again with CONFIG.phase "frame" (steer the camera for CONFIG.frameSeconds while the capture
runs) and, when its source mentions CONFIG.phase == "expect", with phase "expect" before each --expect read."""

import base64
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import secrets
import tempfile
import threading
import time

import console_log
from studio_farm import (HIDE_GUI_LUAU, PROBES, SIZE_LUAU, StudioFarm, build_place, click, config, connect, git_head,
                         play, safe_name, studios)

AUDIT = PROBES / "ui-audit.luau"


def probe(args):
    """Build, open, play, run the probe scripts, capture each size, stop and close; returns the written files."""
    from PIL import Image  # screen_capture returns JPEG

    worktree = (args.project or args.place.parent).resolve()
    script = args.script and args.script.resolve(strict=True)
    client = None if args.client == Path("none") else args.client or (
        script and script.with_name(script.stem + "-client.luau"))
    client = client.resolve(strict=True) if client and (args.client or client.exists()) else None
    sizes = [tuple(int(n) for n in size.lower().split("x")) for size in args.size or ["1920x1080"]]
    tag = args.tag or f"{safe_name(worktree)}-probe-{secrets.token_hex(3)}"
    args.out.mkdir(parents=True, exist_ok=True)
    header = f'local CONFIG = {{ tag = "{tag}", phase = "run" }}\n'
    digest = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (script, client) if path}
    written, shooter, expect_error, findings = [], None, None, 0
    with tempfile.TemporaryDirectory() as out, StudioFarm.session(
            build_place(worktree, tag, out) if args.project else args.place, tag) as studio:
        bridge = studio.bridge
        print(f"farm instance {studio.id} pid {studio.pid} tag {tag}", flush=True)
        play(bridge, studio.id, True)
        if getattr(args, "moments", None):  # before anything can start the effect: its clock stops at the first moment
            bridge.tool("execute_luau", studio_id=studio.id, datamodel_type="Client",
                        code=f'workspace:SetAttribute("FarmFxHold", {args.moments[0]}) return "ok"')
        try:
            for side, path in (("Server", script), ("Client", client)):
                if path:
                    result = bridge.tool("execute_luau", studio_id=studio.id, datamodel_type=side,
                                         code=header + path.read_text())
                    print(f"{side}: {result.strip()[:300]}", flush=True)
            time.sleep(args.wait)
            if args.emulate:  # the clicks see the emulated viewport (a key low on the bare farm viewport misses)
                ew, eh = (int(n) for n in args.emulate.lower().split("x"))
                bridge.tool("execute_luau", studio_id=studio.id, datamodel_type="Client", code=SIZE_LUAU.format(w=ew, h=eh))
            for text in args.click or []:
                text, _, wait = text.partition("@")  # "Buy@1.5": this click waits 1.5 s instead of --click-wait
                click(bridge, studio.id, text)
                time.sleep(float(wait) if wait else args.click_wait)
            if args.expect:  # after the clicks: a clicked route is what the verdict judges
                check = None
                if client and 'CONFIG.phase == "expect"' in client.read_text():
                    check = header + 'CONFIG.phase = "expect"\n' + client.read_text()
                expect_error = expect_attribute(bridge, studio.id, args.expect, args.expect_timeout, check)
            if getattr(args, "moments", None):
                written += moments(bridge, studio.id, args, sizes[0], tag, {
                    "studio_id": studio.id, "tag": tag, "project": str(worktree), "commit": git_head(worktree),
                    "scripts": digest})
            for w, h in [] if getattr(args, "moments", None) else sizes:
                viewport = bridge.tool("execute_luau", studio_id=studio.id, datamodel_type="Client",
                                       code=SIZE_LUAU.format(w=w, h=h))
                found = re.search(r"VIEWPORT (\d+)x(\d+)", viewport)
                framing = None
                if args.audit:
                    findings += audit(bridge, studio.id, args.out / f"{args.name or tag}-{w}x{h}-audit.json")
                if args.hide_gui:
                    bridge.tool("execute_luau", studio_id=studio.id, datamodel_type="Client", code=HIDE_GUI_LUAU)
                if client and args.frames == 1:
                    # execute_luau threads end with the call and the game's own camera takes over again right
                    # after, so the client probe steers the camera for a few seconds while a second bridge
                    # connection captures mid-loop.
                    framed = {}
                    def frame():
                        try:
                            framed["text"] = bridge.tool(
                                "execute_luau", studio_id=studio.id, datamodel_type="Client",
                                code=header + 'CONFIG.phase, CONFIG.frameSeconds = "frame", 4\n' + client.read_text())
                        except (RuntimeError, TimeoutError) as error:
                            framed["text"] = f"frame call failed: {error}"

                    framing = threading.Thread(target=frame)
                    framing.start()
                    time.sleep(2)
                    shooter = shooter or connect()
                    studios(shooter)
                film = []
                for index in range(args.frames):
                    if index:
                        time.sleep(args.every)
                        if args.hide_gui and not framing:  # screens the game opened since the last frame
                            bridge.tool("execute_luau", studio_id=studio.id, datamodel_type="Client",
                                        code=HIDE_GUI_LUAU)
                    picture = grab(shooter if framing else bridge, studio.id, f"{tag}-{w}x{h}-{index}")
                    if framing:
                        framing.join()
                        print(f"Client frame: {framed.get('text', '').strip()[:200]}", flush=True)
                    stem = args.out / (f"{args.name or tag}-{w}x{h}" + (f"-f{index:02d}" if args.frames > 1 else ""))
                    with picture:
                        captured, picture = picture.size, picture.convert("RGB")
                        # Phone emulation renders at the window's physical-size scale, so the raw capture size
                        # varies by instance; resample to the emulated viewport so captures compare (the sidecar
                        # keeps both).
                        if found and captured != (int(found[1]), int(found[2])):
                            picture = picture.resize((int(found[1]), int(found[2])), Image.LANCZOS)
                        picture.save(stem.with_suffix(".png"))
                    stem.with_suffix(".json").write_text(json.dumps({
                        "studio_id": studio.id, "tag": tag, "project": str(worktree),
                        "commit": git_head(worktree), "scripts": digest, "requested": f"{w}x{h}",
                        "viewport": found and f"{found[1]}x{found[2]}", "captured": f"{captured[0]}x{captured[1]}",
                        "captured_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                    }, indent=2) + "\n")
                    written += [stem.with_suffix(".png"), stem.with_suffix(".json")]
                    film.append(stem.with_suffix(".png"))
                    print(f"captured {stem.with_suffix('.png')} (viewport {found and found[0][9:]}, raw "
                          f"{captured[0]}x{captured[1]})", flush=True)
                if len(film) > 1:  # a filmstrip: the frames in time order, four across
                    sheet = contact_sheet(film, 4)
                    sheet_path = args.out / f"{args.name or tag}-{w}x{h}-sheet.png"
                    sheet.save(sheet_path)
                    written.append(sheet_path)
                    print(f"sheet {sheet_path}", flush=True)
        finally:
            if shooter:
                shooter.close()
            console = console_log.report(bridge, studio.id, accept=config().console_accept)  # game errors fail too
            play(bridge, studio.id, False)
    if expect_error:
        raise RuntimeError(expect_error)
    if console:
        raise RuntimeError("; ".join(console))
    if findings and args.fail_on_findings:
        raise RuntimeError(f"UI audit: {findings} findings (see the -audit.json files)")
    return written


def audit(bridge, studio_id, path):
    """Run the UI audit probe on the Client DataModel, write its JSON to path, print the counts; returns the total."""
    reply = bridge.tool("execute_luau", studio_id=studio_id, datamodel_type="Client", code=AUDIT.read_text())
    found = re.search(r"AUDIT (\{.*\})", reply, re.S)
    if not found:
        raise RuntimeError(f"UI audit returned no report: {reply.strip()[:300]}")
    report = json.loads(found[1])
    path.write_text(json.dumps(report, indent=2) + "\n")
    counts = report.get("counts", {})
    print(f"audit {path}: " + ", ".join(f"{kind} {count}" for kind, count in counts.items()), flush=True)
    return sum(counts.values())


def grab(bridge, studio_id, capture_id):
    """One screen_capture as a PIL image (screen_capture returns JPEG)."""
    from PIL import Image
    result = bridge.request("tools/call", {"name": "screen_capture",
                                           "arguments": {"studio_id": studio_id, "capture_id": capture_id}})
    image = next((c for c in result.get("content", []) if c.get("type") == "image"), None)
    if result.get("isError") or not image:
        raise RuntimeError(f"screen_capture {capture_id} returned no image: {result}")
    return Image.open(io.BytesIO(base64.b64decode(image["data"])))


MAX_MOMENTS = 8
STALL = 1.5  # seconds an effect's clock may sit still short of its hold before the capture gives up
# The watched effect: the newest FarmFx root when first seen (FxClock), marked so later polls keep to it.
FX_LUAU = """local watched, newest
for _, root in game:GetService("CollectionService"):GetTagged("FarmFx") do
	if root:GetAttribute("FxWatched") then
		watched = root
	end
	if not newest or root:GetAttribute("FxBorn") > newest:GetAttribute("FxBorn") then
		newest = root
	end
end
if {first} and not watched and newest then
	newest:SetAttribute("FxWatched", true)
	watched = newest
end
if not watched then
	return "FX none"
end
return string.format("FX %.4f %s", watched:GetAttribute("FxTime"), watched:GetFullName())"""


def parse_moments(text):
    """'0.05,0.3,0.9' -> ascending seconds, at most MAX_MOMENTS."""
    times = [float(part) for part in text.split(",") if part.strip()]
    if not times or len(times) > MAX_MOMENTS or times != sorted(set(times)) or times[0] < 0:
        raise ValueError(f"--moments takes 1 to {MAX_MOMENTS} ascending seconds, got {text!r}")
    return times


def moments(bridge, studio_id, args, size, tag, sidecar, timeout=None):
    """Capture the watched effect held at each time in args.moments (FarmFxHold set first by probe), then release it.
    Each PNG is exact: FxClock stops the effect's clock at the hold, so call latency never shifts a frame. Stops early
    when the effect ends or its clock stalls STALL seconds short of a hold. Returns the written files."""
    w, h = size
    timeout = timeout or args.expect_timeout
    viewport = bridge.tool("execute_luau", studio_id=studio_id, datamodel_type="Client", code=SIZE_LUAU.format(w=w, h=h))
    found = re.search(r"VIEWPORT (\d+)x(\d+)", viewport)
    written, shots, labels, seen = [], [], [], False
    for index, at in enumerate(args.moments):
        if index:
            bridge.tool("execute_luau", studio_id=studio_id, datamodel_type="Client",
                        code=f'workspace:SetAttribute("FarmFxHold", {at}) return "ok"')
        deadline, last, moved = time.monotonic() + (timeout if not seen else 30), None, time.monotonic()
        while True:
            reply = bridge.tool("execute_luau", studio_id=studio_id, datamodel_type="Client",
                                code=FX_LUAU.replace("{first}", "false" if seen else "true"))
            fx = re.search(r"FX (\S+)(?: (\S+))?", reply)
            if fx and fx[1] != "none":
                seen, now = True, float(fx[1])
                if now >= at - 1e-4:
                    break
                if now != last:
                    last, moved = now, time.monotonic()
                elif time.monotonic() - moved > STALL:
                    raise RuntimeError(f"moment {at}: the effect's clock stalled at {now:.3f} s")
            elif seen:
                print(f"moment {at}: the effect ended first; {len(shots)} of {len(args.moments)} captured", flush=True)
                break
            if time.monotonic() >= deadline:
                raise RuntimeError(f"moment {at}: no FarmFx effect reached it (last reply {reply.strip()[:200]})")
            time.sleep(0.2)
        if not (fx and fx[1] != "none"):
            break
        if args.hide_gui:
            bridge.tool("execute_luau", studio_id=studio_id, datamodel_type="Client", code=HIDE_GUI_LUAU)
        with grab(bridge, studio_id, f"{tag}-m{index}") as picture:
            captured, picture = picture.size, picture.convert("RGB")
            if found and captured != (int(found[1]), int(found[2])):
                picture = picture.resize((int(found[1]), int(found[2])))
            stem = args.out / f"{args.name or tag}-{w}x{h}-m{index}"
            picture.save(stem.with_suffix(".png"))
        stem.with_suffix(".json").write_text(json.dumps({
            **sidecar, "moment": at, "fx_time": float(fx[1]), "effect": fx[2], "requested": f"{w}x{h}",
            "viewport": found and f"{found[1]}x{found[2]}", "captured": f"{captured[0]}x{captured[1]}",
            "captured_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds")}, indent=2) + "\n")
        written += [stem.with_suffix(".png"), stem.with_suffix(".json")]
        shots.append(stem.with_suffix(".png"))
        labels.append(f"t={at:g} s")
        print(f"moment {at} s: {stem.with_suffix('.png')} ({fx[2]} at {float(fx[1]):.3f} s)", flush=True)
    bridge.tool("execute_luau", studio_id=studio_id, datamodel_type="Client",
                code='workspace:SetAttribute("FarmFxHold", nil) return "ok"')
    if not shots:
        raise RuntimeError("--moments captured nothing")
    sheet = args.out / f"{args.name or tag}-{w}x{h}-moments.png"
    contact_sheet(shots, 2, labels).save(sheet)
    print(f"moments sheet {sheet}", flush=True)
    return written + [sheet]


def contact_sheet(paths, columns, labels=None):
    """The frames in reading order, `columns` across, each labelled with its index (or its entry in labels)."""
    from PIL import Image, ImageDraw
    frames = [Image.open(path).convert("RGB") for path in paths]
    w, h = frames[0].size
    rows = (len(frames) + columns - 1) // columns
    sheet = Image.new("RGB", (w * columns, h * rows), "black")
    draw = ImageDraw.Draw(sheet)
    for index, frame in enumerate(frames):
        x, y = (index % columns) * w, (index // columns) * h
        sheet.paste(frame.resize((w, h)), (x, y))
        draw.text((x + 6, y + 4), labels[index] if labels else f"f{index:02d}", fill="yellow", font_size=max(12, h // 24))
    return sheet


EXPECT_LUAU = """local value = game:GetService("Players").LocalPlayer:GetAttribute({name!r})
return "EXPECT " .. tostring(value)"""


def parse_expect(text):
    """'Name=regex' -> (name, compiled regex) for --expect."""
    name, sep, pattern = text.partition("=")
    if not sep or not name:
        raise ValueError(f"--expect takes NAME=REGEX, got {text!r}")
    return name, re.compile(pattern)


def expect_attribute(bridge, studio_id, expect, timeout, check=None):
    """Polls the LocalPlayer attribute until it matches (None), starts with FAIL or times out (the error text).
    The captures still run either way, so a failed probe keeps its frames. `check`: the client probe run with
    CONFIG.phase "expect" before each read (execute_luau threads end with their call, so a probe that judges a
    clicked route sets its attribute from this phase instead of a long-lived thread)."""
    name, pattern = parse_expect(expect)
    deadline, value = time.monotonic() + timeout, None
    while True:
        if check:
            bridge.tool("execute_luau", studio_id=studio_id, datamodel_type="Client", code=check)
        reply = bridge.tool("execute_luau", studio_id=studio_id, datamodel_type="Client",
                            code=EXPECT_LUAU.format(name=name))
        found = re.search(r"EXPECT (.*)", reply, re.S)
        value = found and found.group(1).strip()
        if value and pattern.search(value):
            print(f"expect {name}: {value[:300]}", flush=True)
            return None
        if value and value.startswith("FAIL"):
            return f"expect {name}: {value[:300]}"
        if time.monotonic() >= deadline:
            return f"expect {name}: timed out after {timeout:.0f} s; last {value!r}"[:400]
        time.sleep(2)
