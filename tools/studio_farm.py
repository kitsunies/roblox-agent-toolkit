#!/usr/bin/env python3
"""Studio farm: throwaway Roblox Studio instances on a Windows host over SSH, one per verification job.

Each instance opens a copy of a built place named <tag>.rbxl, is identified by that file in list_roblox_studios,
and is closed by matching that file on the Studio command line, so an instance the farm did not open (your main
Rojo-connected Studio included) can never be closed, played or stopped by it.

Settings come from farm.toml in the working directory (or the file named by STUDIO_FARM_CONFIG); see
farm.example.toml.
"""

import argparse
import base64
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
from functools import cache
import json
import os
from pathlib import Path
import queue as queues
import re
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import tomllib

BOOT_ID = Path("/proc/sys/kernel/random/boot_id")
BOOT = BOOT_ID.read_text().strip() if BOOT_ID.exists() else None  # reap needs Linux /proc to tell an owner is alive
TAG = re.compile(r"^[A-Za-z0-9_-]{1,48}$")
GRACE = 6  # seconds between the close request and the kill; Studio usually waits on a save prompt
PROBES = Path(__file__).resolve().parent / "probes"
OPEN_LOCK = Path("/tmp/studio-farm-open.lock")  # machine-wide: shared by every checkout's farm
NOT_CONNECTED = ("No Roblox Studio instances are connected", "is not connected")

DEFAULTS = {
    "host": None,  # ssh alias of the Windows Studio host (key auth, OpenSSH server)
    "studio_mcp": None,  # argv that starts the official Studio MCP server (stdio), e.g. over ssh to the host
    "chrrxs_mcp": None,  # argv that starts Chrrxs robloxstudio-mcp 3.5.0 on the host (harvest only)
    "remote_dir": r"$env:LOCALAPPDATA\Temp\studio-farm",  # PowerShell string: where places are copied on the host
    "state_dir": "build/studio-farm",  # local, relative to the working directory
    "rojo_project": "default.project.json",
    "max_studios": 8,  # RobloxStudioBeta processes on the host (playtest servers and clients count) after an open
    "min_free_mb": 4096,  # free physical memory an open needs; with less, new Studios never register
    "queue_seconds": 900,  # seconds an open waits for room before failing
    "window": [1180, 800],
    "console_accept": [],  # regexes for console errors that never fail a probe, matched against "<side> <message>"
}


def load_config(path=None):
    """Settings from a TOML file over DEFAULTS. A missing file gives the defaults (commands that need the host or
    an MCP command fail when they reach for it)."""
    path = Path(path or os.environ.get("STUDIO_FARM_CONFIG") or "farm.toml")
    data = tomllib.loads(path.read_text()) if path.exists() else {}
    unknown = set(data) - set(DEFAULTS)
    if unknown:
        raise ValueError(f"{path}: unknown settings {sorted(unknown)}")
    config = SimpleNamespace(**{**DEFAULTS, **data})
    if len(config.window) != 2:
        raise ValueError(f"{path}: window takes [width, height]")
    return config


@cache
def config():
    return load_config()


def required(name):
    value = getattr(config(), name)
    if not value:
        raise ValueError(f"set {name} in farm.toml (see farm.example.toml)")
    return value


def state_file():
    return Path(config().state_dir) / "state.json"


class Bridge:
    """A minimal MCP stdio client: JSON-RPC lines over a child process."""

    def __init__(self, command):
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        text=True, encoding="utf-8", bufsize=1)
        self.messages = queues.Queue()
        self.next_id = 0
        threading.Thread(target=self.read, daemon=True).start()

    def read(self):
        try:
            for line in self.process.stdout:
                self.messages.put(json.loads(line))
        except (ValueError, OSError) as exc:
            self.messages.put(exc)
        finally:
            self.messages.put(EOFError("Studio MCP bridge closed"))

    def send(self, message):
        self.process.stdin.write(json.dumps({"jsonrpc": "2.0", **message}) + "\n")
        self.process.stdin.flush()

    def request(self, method, params):
        self.next_id += 1
        request_id = self.next_id
        self.send({"id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + 45
        while True:
            try:
                message = self.messages.get(timeout=max(0, deadline - time.monotonic()))
            except queues.Empty as exc:
                raise TimeoutError(f"Studio MCP timeout: {method}") from exc
            if isinstance(message, Exception):
                raise message
            if message.get("method") and "id" in message:
                if message["method"] == "ping":
                    self.send({"id": message["id"], "result": {}})
                else:
                    self.send({"id": message["id"], "error": {"code": -32601, "message": "Unsupported client method"}})
            elif message.get("id") == request_id:
                if "error" in message:
                    raise RuntimeError(message["error"])
                return message["result"]

    def initialize(self, name, protocol="2024-11-05"):
        self.request("initialize", {"protocolVersion": protocol, "capabilities": {},
                                    "clientInfo": {"name": name, "version": "1"}})
        self.send({"method": "notifications/initialized"})
        return self

    def tool(self, name, **arguments):
        for attempt in range(20):
            result = self.request("tools/call", {"name": name, "arguments": arguments})
            text = "\n".join(c["text"] for c in result.get("content", []) if c.get("type") == "text")
            # With several Studios open the proxy briefly loses them all; the call never ran, so retrying is safe.
            if not (result.get("isError") and any(m in text for m in NOT_CONNECTED)) or attempt == 19:
                break
            time.sleep(1)
        if result.get("isError"):
            raise RuntimeError(f"{name}: {text}")
        return text

    def close(self):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.process.stdout.close()


# Windows side. A GUI started from the SSH session never reaches the interactive desktop, so launch and the graceful
# close run as a one-shot scheduled task with an Interactive principal. The task runs a .ps1 file: Windows blocks
# -EncodedCommand inside such tasks (0x80070005).
PS_PRELUDE = r"""$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$dir = "@DIR@"
function Invoke-Interactive($name, $body) {
  $ps1 = "$dir\$name.ps1"
  Set-Content $ps1 $body
  $action = New-ScheduledTaskAction -Execute 'conhost.exe' `
    -Argument "--headless powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$ps1`""
  $user = New-ScheduledTaskPrincipal -LogonType Interactive `
    -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name)
  Register-ScheduledTask -TaskName "studio-farm-$name" -Action $action -Principal $user -Force | Out-Null
  Start-ScheduledTask -TaskName "studio-farm-$name"
}
function Remove-Interactive($name) {
  Unregister-ScheduledTask -TaskName "studio-farm-$name" -Confirm:$false -ErrorAction SilentlyContinue
}
function Get-Farm($tag) {
  @(Get-CimInstance Win32_Process -Filter "Name = 'RobloxStudioBeta.exe'" |
    Where-Object { $_.CommandLine -like ('*' + [WildcardPattern]::Escape("$dir\$tag.rbxl") + '*') })
}
"""
PS_CAPACITY = r"""$os = Get-CimInstance Win32_OperatingSystem
'{0} {1}' -f @(Get-Process RobloxStudioBeta -ErrorAction SilentlyContinue).Count, [int]($os.FreePhysicalMemory / 1024)"""
PS_PREPARE = r"""if (Get-Farm '{tag}') {{ throw 'an instance for tag {tag} is already running' }}
New-Item -ItemType Directory -Force $dir | Out-Null
$dir"""
# The interactive launch task stays up as a guard: it starts Studio minimized without activation (WScript.Shell Run,
# SW_SHOWMINNOACTIVE) and, until the instance exits, parks every top-level window of it and of the playtest Studios it
# spawns left of the virtual screen, restored but never activated, at the bottom of the z-order. Parked, not
# minimized: a minimized Studio draws no 3D, so its captures come out blank.
# Big enough for a phone sized game view under Studio's panels (about 980x445; at 720x560 it was 520x265 and
# clipped keys low on the screen, so clicked flows never reached them). Configurable as `window`.
PS_GUARD = r"""$dir = "@DIR@"
$tag = '@TAG@'
Add-Type -TypeDefinition @"
using System; using System.Collections.Generic; using System.Runtime.InteropServices; using System.Text;
public static class FarmWindows {
  public struct Rect { public int Left, Top, Right, Bottom; }
  public struct Placement { public int Length, Flags, ShowCmd, MinX, MinY, MaxX, MaxY; public Rect Normal; }
  delegate bool Each(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] static extern bool EnumWindows(Each f, IntPtr l);
  [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] static extern bool IsIconic(IntPtr h);
  [DllImport("user32.dll")] static extern IntPtr GetWindow(IntPtr h, uint cmd);
  [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr h, int cmd);
  [DllImport("user32.dll")] static extern bool GetWindowRect(IntPtr h, out Rect r);
  [DllImport("user32.dll")] static extern bool SetWindowPlacement(IntPtr h, ref Placement p);
  [DllImport("user32.dll")] static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int cx, int cy, uint f);
  [DllImport("user32.dll")] static extern int GetSystemMetrics(int i);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetClassName(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  public static List<string> Park(uint[] pids, int w, int ht) {
    var ids = new HashSet<uint>(pids); var done = new List<string>();
    int left = GetSystemMetrics(76), x = left - w - 200, y = GetSystemMetrics(77);  // SM_X/YVIRTUALSCREEN
    EnumWindows((h, l) => {
      uint pid; GetWindowThreadProcessId(h, out pid); Rect r;
      // unowned visible windows only: owned dialogs follow their owner
      if (!ids.Contains(pid) || !IsWindowVisible(h) || GetWindow(h, 4) != IntPtr.Zero) return true;
      if (!IsIconic(h) && GetWindowRect(h, out r) && r.Right <= left) return true;  // already parked
      bool active = GetForegroundWindow() == h;
      if (active) ShowWindow(h, 6);  // SW_MINIMIZE hands activation to the next window first
      var p = new Placement(); p.Length = Marshal.SizeOf(p); p.ShowCmd = 4;  // SW_SHOWNOACTIVATE
      p.Normal.Left = x; p.Normal.Top = y; p.Normal.Right = x + w; p.Normal.Bottom = y + ht;
      SetWindowPlacement(h, ref p);  // restores (minimized or maximized) but pulls the rect back on screen
      SetWindowPos(h, (IntPtr)1, x, y, w, ht, 0x10);  // HWND_BOTTOM, SWP_NOACTIVATE; no clamp here
      var c = new StringBuilder(128); var t = new StringBuilder(256); GetClassName(h, c, 128); GetWindowText(h, t, 256);
      done.Add(String.Format("{0:HH:mm:ss.fff} pid={1} hwnd={2} active={3} class={4} title={5}", DateTime.Now, pid, h, active, c, t));
      return true;
    }, IntPtr.Zero);
    return done;
  }
}
"@
[void][FarmWindows]::SetProcessDPIAware()
# newest install: the registry ContentFolder can name a version an auto-update emptied
$exe = Get-ChildItem "$env:LOCALAPPDATA\Roblox\Versions" -Directory | Sort-Object CreationTime -Descending |
  ForEach-Object { Join-Path $_.FullName 'RobloxStudioBeta.exe' } | Where-Object { Test-Path $_ } | Select-Object -First 1
[void](New-Object -ComObject WScript.Shell).Run(('"{0}" "{1}\{2}.rbxl"' -f $exe, $dir, $tag), 7, $false)
$root = $null
for ($i = 0; $i -lt 240 -and -not $root; $i++) {
  Start-Sleep -Milliseconds 250
  $root = Get-CimInstance Win32_Process -Filter "Name = 'RobloxStudioBeta.exe'" |
    Where-Object { $_.CommandLine -like ('*' + [WildcardPattern]::Escape("$dir\$tag.rbxl") + '*') } | Select-Object -First 1 -ExpandProperty ProcessId
}
if (-not $root) { exit 1 }
Set-Content "$dir\$tag.pid.tmp" $root  # renamed whole: PS_OPEN polls the file and would read it half written
Move-Item -Force "$dir\$tag.pid.tmp" "$dir\$tag.pid"
$ids = [uint32[]]@($root)
for ($tick = 0; Get-Process -Id $root -ErrorAction SilentlyContinue; $tick++) {
  if ($tick % 8 -eq 0) {  # playtest servers and clients are descendants of the instance
    $all = @(Get-CimInstance Win32_Process -Filter "Name = 'RobloxStudioBeta.exe'")
    do {
      $n = $ids.Count
      $ids = [uint32[]]@($ids + @($all | Where-Object { $ids -contains $_.ParentProcessId -and $ids -notcontains $_.ProcessId } |
        ForEach-Object { $_.ProcessId }))
    } while ($ids.Count -gt $n)
  }
  $done = [FarmWindows]::Park($ids, @WIDTH@, @HEIGHT@)
  if ($done.Count) { Add-Content "$dir\$tag.guard.log" $done }
  Start-Sleep -Milliseconds 250
}"""
PS_OPEN = r"""$pidFile = "$dir\{tag}.pid"
Remove-Item $pidFile -ErrorAction SilentlyContinue
Invoke-Interactive '{tag}.open' (Get-Content -Raw "$dir\{tag}.open.ps1")
for ($i = 0; $i -lt 240 -and -not (Test-Path $pidFile); $i++) {{ Start-Sleep -Milliseconds 250 }}
if (-not (Test-Path $pidFile)) {{ throw 'the interactive launch task did not start Studio' }}
Get-Content $pidFile"""


def guard_script(tag, config=None):
    """The launch and guard task's .ps1 for tag; copied over with scp, since it outgrows cmd.exe's 8191 characters."""
    config = config or load_config()
    width, height = config.window
    return (PS_GUARD.replace("@TAG@", tag).replace("@DIR@", config.remote_dir)
            .replace("@WIDTH@", str(width)).replace("@HEIGHT@", str(height)))


PS_TITLES = r"""$out = "$dir\{tag}.titles.txt"
$ids = (Get-Farm '{tag}' | ForEach-Object {{ $_.ProcessId }}) -join ','
if (-not $ids) {{ 'GONE'; return }}
Remove-Item $out -ErrorAction SilentlyContinue
try {{
  Invoke-Interactive '{tag}.titles' "Get-Process -Id $ids | ForEach-Object {{ '[' + `$_.MainWindowTitle + ']' }} | Set-Content '$out'"
  for ($i = 0; $i -lt 60 -and -not (Test-Path $out); $i++) {{ Start-Sleep -Milliseconds 250 }}
}} finally {{ Remove-Interactive '{tag}.titles' }}
Get-Content $out"""
PS_CLOSE = r"""$procs = Get-Farm '{tag}'
$result = 'gone'
if ($procs) {{
  $ids = ($procs | ForEach-Object {{ $_.ProcessId }}) -join ','
  try {{
    Invoke-Interactive '{tag}.close' "Get-Process -Id $ids -ErrorAction SilentlyContinue | ForEach-Object {{ [void]`$_.CloseMainWindow() }}"
    for ($i = 0; $i -lt {grace} * 4 -and (Get-Farm '{tag}'); $i++) {{ Start-Sleep -Milliseconds 250 }}
  }} catch {{ }} finally {{ Remove-Interactive '{tag}.close' }}
  $result = 'closed'
  foreach ($p in Get-Farm '{tag}') {{ Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue; $result = 'killed' }}
  for ($i = 0; $i -lt 40 -and (Get-Farm '{tag}'); $i++) {{ Start-Sleep -Milliseconds 250 }}
  if (Get-Farm '{tag}') {{ throw 'Studio for tag {tag} survived the kill' }}
}}
Remove-Interactive '{tag}.open'
Remove-Item "$dir\{tag}.*" -Force -ErrorAction SilentlyContinue
$result"""


def powershell(script, timeout=120):
    prelude = PS_PRELUDE.replace("@DIR@", config().remote_dir)
    encoded = base64.b64encode((prelude + script).encode("utf-16-le")).decode()
    result = subprocess.run(["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", required("host"),
                             f"powershell -NoProfile -NonInteractive -EncodedCommand {encoded}"],
                            capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        errors = re.findall(r'<S S="Error">(.*?)</S>', result.stderr) or [result.stderr]
        raise RuntimeError("Windows: " + "".join(errors).replace("_x000D__x000A_", " ").strip()[:800])
    return result.stdout.strip()


def connect():
    """A Bridge to the official Studio MCP server (studio_mcp in farm.toml)."""
    bridge = Bridge(required("studio_mcp"))
    try:
        bridge.initialize("studio-farm")
    except BaseException:
        bridge.close()
        raise
    return bridge


def studios(bridge, settle=30):
    for _ in range(settle):  # the proxy lists no instances for a moment after connecting
        listed = json.loads(bridge.tool("list_roblox_studios"))["studios"]
        if listed:
            return listed
        time.sleep(1)
    return []


def started(pid):
    try:
        return (Path("/proc") / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()[19]
    except (OSError, IndexError):
        return None


def owner_record(pid):
    try:  # a make target exits at once; the job is the shell that ran make
        if (Path("/proc") / str(pid) / "comm").read_text().strip() == "make":
            pid = int((Path("/proc") / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return {"pid": pid, "start": started(pid), "boot": BOOT}


def alive(owner):
    return bool(owner and owner.get("boot") == BOOT and owner.get("start")
                and started(owner.get("pid")) == owner["start"])


@contextmanager
def locked_state():
    path = state_file()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (path.parent / "lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = json.loads(path.read_text()) if path.exists() else {}
        state.setdefault("instances", {})
        yield state
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, indent=2) + "\n")
        temporary.replace(path)


def tag_of(entry):
    return (entry.get("file") or "").removesuffix(".rbxl")


def build_place(worktree, tag, out_dir, project_file=None):
    """Build a Rojo project's place with Workspace attribute FarmTag = tag baked in; returns the .rbxl path."""
    worktree = Path(worktree).resolve()
    project = json.loads((worktree / (project_file or config().rojo_project)).read_text())

    def absolute(node):
        for key, value in node.items():
            if key == "$path" and isinstance(value, str):
                node[key] = str(worktree / value)
            elif isinstance(value, dict) and not key.startswith("$"):
                absolute(value)

    absolute(project["tree"])
    workspace = project["tree"].setdefault("Workspace", {"$className": "Workspace"})
    workspace.setdefault("$attributes", {})["FarmTag"] = tag
    out_dir = Path(out_dir)
    project_file = out_dir / f"{tag}.project.json"
    project_file.write_text(json.dumps(project))
    place = out_dir / f"{tag}.rbxl"
    rojo = shutil.which("rojo") or str(Path.home() / ".rokit/bin/rojo")
    subprocess.run([rojo, "build", str(project_file), "-o", str(place)], cwd=worktree, check=True,
                   stdout=subprocess.DEVNULL)
    return place


class CapReached(RuntimeError):
    """Roblox refused another Studio window ("You have opened the maximum allowed Studio windows")."""


def held_by_cap(titles):
    # A loaded instance's main window is titled "<place path> - Roblox Studio"; one held by the cap dialog has none.
    return titles != "GONE" and ".rbxl - Roblox Studio" not in titles


def capped(tag):
    return held_by_cap(powershell(PS_TITLES.format(tag=tag)))


def wait_listed(bridge, tag, baseline, deadline):
    launched, suspicious = time.monotonic(), 0
    while True:
        fresh = [s for s in studios(bridge, settle=1) if s["id"] not in baseline and tag_of(s) == tag]
        if len(fresh) == 1:
            studio_id = fresh[0]["id"]
            try:  # also proves the Edit DataModel answers; places built without the tag get it here
                probe = bridge.tool("execute_luau", studio_id=studio_id, datamodel_type="Edit", code=(
                    f'if workspace:GetAttribute("FarmTag") == nil then workspace:SetAttribute("FarmTag", "{tag}") end '
                    'return "FarmTag=" .. tostring(workspace:GetAttribute("FarmTag"))'))
            except RuntimeError:
                probe = ""
            if f"FarmTag={tag}" in probe:
                return studio_id
        elif time.monotonic() - launched > 40:  # a normal load lists well before this
            suspicious = suspicious + 1 if capped(tag) else 0
            if suspicious >= 2:
                raise CapReached(f"Studio window cap reached while opening {tag}")
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Studio for {tag} did not appear in list_roblox_studios")
        time.sleep(5 if suspicious else 2)


def capacity():
    studios, free_mb = powershell(PS_CAPACITY).split()[-2:]
    return int(studios), int(free_mb)


def wait_for_room(tag, sample=capacity, max_studios=8, min_free_mb=4096, queue=900,
                  sleep=time.sleep, clock=time.monotonic, log=print):
    """Block until fewer than max_studios Studios run and min_free_mb is free; one log line per minute queued."""
    # ponytail: no lock across farms, so two opens can pass the gate together; the cap retry absorbs the overshoot
    start = clock()
    last_log = None
    while True:
        studios, free_mb = sample()
        if studios < max_studios and free_mb >= min_free_mb:
            return studios, free_mb
        waited = clock() - start
        if waited >= queue:
            raise TimeoutError(f"no room for {tag} after {queue:.0f} s: {studios} Studios, {free_mb} MB free")
        if last_log is None or waited - last_log >= 60:
            last_log = waited
            log(f"{tag}: queued {waited:.0f} s ({studios}/{max_studios} Studios, {free_mb}/{min_free_mb} MB free)")
        sleep(10)


def open_instance(place, tag=None, owner=None, bridge=None, timeout=600, max_studios=None, min_free_mb=None,
                  queue=None):
    """Open place in a new Studio once the host has room; on Roblox's window cap, retry until timeout."""
    settings = config()
    max_studios = max_studios or settings.max_studios
    min_free_mb = min_free_mb or settings.min_free_mb
    queue = settings.queue_seconds if queue is None else queue
    host = required("host")
    tag = tag or f"{safe_name(Path.cwd())}-{secrets.token_hex(3)}"
    if not TAG.match(tag):
        raise ValueError(f"tag must match {TAG.pattern}: {tag}")
    place = Path(place).resolve(strict=True)
    with locked_state() as state:
        if tag in state["instances"]:
            raise RuntimeError(f"tag {tag} is already open; close it or pick another tag")
        state["instances"][tag] = {"id": None, "pid": None, "owner": owner_record(owner or os.getppid()),
                                   "opened_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                   "place": str(place)}
    own = bridge is None
    launched = False
    try:
        bridge = bridge or connect()
        baseline = {s["id"] for s in studios(bridge)}
        remote = powershell(PS_PREPARE.format(tag=tag)).replace("\\", "/")
        launched = True
        deadline = time.monotonic() + timeout
        # One launch at a time across every farm on this machine, from the capacity check until the instance lists:
        # parallel opens otherwise all pass the gate together and Windows sshd starts dropping connections.
        launch_lock = open(OPEN_LOCK, "a")
        fcntl.flock(launch_lock, fcntl.LOCK_EX)
        while True:
            wait_for_room(tag, max_studios=max_studios, min_free_mb=min_free_mb, queue=queue,
                          log=lambda line: print(line, file=sys.stderr, flush=True))
            deadline = max(deadline, time.monotonic() + 180)  # queued time does not count against loading
            subprocess.run(["scp", "-q", "-o", "BatchMode=yes", str(place), f"{host}:{remote}/{tag}.rbxl"],
                           check=True, timeout=120)
            with tempfile.TemporaryDirectory() as tmp:
                guard = Path(tmp) / f"{tag}.open.ps1"
                guard.write_text(guard_script(tag))
                subprocess.run(["scp", "-q", "-o", "BatchMode=yes", str(guard), f"{host}:{remote}/"], check=True,
                               timeout=60)
            pid = int(powershell(PS_OPEN.format(tag=tag)).split()[-1])
            with locked_state() as state:
                state["instances"][tag]["pid"] = pid
            try:
                studio_id = wait_listed(bridge, tag, baseline, deadline)
                launch_lock.close()
                break
            except CapReached:
                powershell(PS_CLOSE.format(tag=tag, grace=0))  # this attempt only; also clears the dialog
                if time.monotonic() + 30 >= deadline:
                    raise
                print(f"{tag}: Studio window cap reached; retrying in 30 s", file=sys.stderr, flush=True)
                time.sleep(30)
        with locked_state() as state:
            state["instances"][tag]["id"] = studio_id
        return SimpleNamespace(id=studio_id, tag=tag, pid=pid, bridge=bridge)
    except BaseException:
        if "launch_lock" in locals():
            launch_lock.close()
        if launched:
            close_quietly(tag)
        else:
            with locked_state() as state:
                state["instances"].pop(tag, None)
        if own and bridge:
            bridge.close()
        raise


def resolve(key, state):
    if key in state["instances"]:
        return key
    for tag, record in state["instances"].items():
        if record.get("id") == key:
            return tag
    raise RuntimeError(f"{key} was not opened by this farm; refusing to close it")


def close_instance(key):
    with locked_state() as state:
        tag = resolve(key, state)
    result = powershell(PS_CLOSE.format(tag=tag, grace=GRACE)).split()[-1]
    with locked_state() as state:
        state["instances"].pop(tag, None)
    return tag, result


def close_quietly(key):
    """Close with Ctrl-C held off, so an interrupt cannot strand the instance halfway."""
    main = threading.current_thread() is threading.main_thread()
    previous = signal.signal(signal.SIGINT, signal.SIG_IGN) if main else None
    try:
        return close_instance(key)
    finally:
        if main:
            signal.signal(signal.SIGINT, previous)


def reap():
    with locked_state() as state:
        stale = [tag for tag, record in state["instances"].items() if not alive(record.get("owner"))]
    return [close_instance(tag) for tag in stale]


def listing(bridge):
    with locked_state() as state:
        records = dict(state["instances"])
    by_id = {r["id"]: (tag, r) for tag, r in records.items() if r.get("id")}
    rows = []
    for s in studios(bridge):
        tag, record = by_id.pop(s["id"], (None, None))
        rows.append({"id": s["id"], "mode": s.get("mode"), "tag": tag or tag_of(s) or s.get("name"),
                     "owner": record and record["owner"]["pid"], "opened_at": record and record["opened_at"],
                     "pid": record and record["pid"], "preexisting": record is None})
    listed = {r["id"] for r in rows}
    for tag, record in records.items():
        if record.get("id") not in listed:
            rows.append({"id": record.get("id"), "mode": "not listed", "tag": tag, "owner": record["owner"]["pid"],
                         "opened_at": record["opened_at"], "pid": record["pid"], "preexisting": False})
    return rows


# Viewport size through Studio's device emulation, set from the Client DataModel (setters fail in the Server one).
# Landscape sizes use a desktop preset, portrait sizes a phone preset turned Portrait; SetResolutionAsync takes the
# longer side first. No custom devices and no scaling mode: both persist into every Studio on the host.
# Store page shots (--hide-gui): every ScreenGui off on the client, so the capture is the bare game camera.
HIDE_GUI_LUAU = """
for _, gui in game:GetService("Players").LocalPlayer:WaitForChild("PlayerGui"):GetChildren() do
	if gui:IsA("ScreenGui") then
		gui.Enabled = false
	end
end
return "GUI HIDDEN"
"""
SIZE_LUAU = """local svc = game:GetService("StudioDeviceSimulatorService")
local w, h = {w}, {h}
local function preset(form)
	for _, id in svc:GetDeviceListAsync() do
		if svc:GetDeviceInfoAsync(id).DeviceForm == form then
			return id
		end
	end
end
pcall(svc.SetOrientationAsync, svc, Enum.ScreenOrientation.LandscapeLeft)
svc:SetDeviceAsync(preset(if h > w then Enum.DeviceForm.Phone else Enum.DeviceForm.Desktop))
task.wait(0.3)
if h > w then
	svc:SetOrientationAsync(Enum.ScreenOrientation.Portrait)
	task.wait(0.3)
end
svc:SetResolutionAsync(math.max(w, h), math.min(w, h))
task.wait(0.8)
local size = workspace.CurrentCamera.ViewportSize
return "VIEWPORT " .. size.X .. "x" .. size.Y"""


def play(bridge, studio_id, on):
    """Start or stop play and confirm it from get_studio_state; a timed-out toggle is checked, never repeated."""
    try:
        bridge.tool("start_stop_play", studio_id=studio_id, is_start=on)
    except TimeoutError:
        pass
    deadline = time.monotonic() + 45
    while True:
        state = bridge.tool("get_studio_state", studio_id=studio_id)
        if (on and "Server" in state and "Client" in state) or (not on and "Current Studio Mode: Edit" in state):
            return
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Studio did not {'enter' if on else 'leave'} play: {state}")
        time.sleep(0.5)


CLICK_LUAU = """local want = string.lower({text!r})
local byName = string.sub(want, 1, 5) == "name:"
local function shown(gui)
	while gui and gui:IsA("GuiObject") do
		if not gui.Visible then
			return false
		end
		gui = gui.Parent
	end
	return gui == nil or not gui:IsA("ScreenGui") or gui.Enabled
end
for _, button in game:GetService("Players").LocalPlayer.PlayerGui:GetDescendants() do
	if button:IsA("GuiButton") and shown(button) and button.AbsoluteSize.X > 0 then
		local key = string.sub(want, 6)
		local prefix = string.sub(key, -1) == "*" -- "name:Log_Row*": the first key whose name starts so
		local lower = string.lower(button.Name)
		if byName and (lower == key or prefix and string.sub(lower, 1, #key - 1) == string.sub(key, 1, -2)) then
			return "PATH " .. button:GetFullName()
		end
		local texts = {{ if button:IsA("TextButton") then button.Text else "" }}
		for _, label in button:GetDescendants() do
			if label:IsA("TextLabel") then
				table.insert(texts, label.Text)
			end
		end
		for _, text in texts do
			if string.find(string.lower(text), want, 1, true) then
				return "PATH " .. button:GetFullName()
			end
		end
	end
end
return "PATH none"
"""


def click(bridge, studio_id, text):
    """Click the first visible button whose text contains `text` (case-insensitive), through user_mouse_input."""
    deadline = time.monotonic() + 10  # screens slide in; wait for the button
    while True:
        found = bridge.tool("execute_luau", studio_id=studio_id, datamodel_type="Client",
                            code=CLICK_LUAU.format(text=text))
        path = re.search(r"PATH (\S+)", found)
        if path and path[1] != "none":
            break
        if time.monotonic() >= deadline:
            raise RuntimeError(f"no visible button with text {text!r}")
        time.sleep(1)
    # GetFullName gives Players.<name>.PlayerGui...; user_mouse_input wants LocalPlayer.PlayerGui...
    target = "LocalPlayer." + path[1].split(".", 2)[2]
    bridge.tool("user_mouse_input", studio_id=studio_id, datamodel_type="Client", actions=[
        {"action": "moveTo", "instance_path": target}, {"action": "wait", "wait_time_ms": 150},
        {"action": "mouseButtonClick", "mouse_button": "left"}])
    print(f"clicked {text!r} at {target}", flush=True)


def safe_name(worktree):
    """A directory's name trimmed to tag characters (tags allow letters, digits, - and _)."""
    return re.sub(r"[^A-Za-z0-9_-]", "", Path(worktree).name)[:30] or "farm"


def lua(value):
    return "nil" if value is None else json.dumps(value)


def git_head(worktree):
    result = subprocess.run(["git", "-C", str(worktree), "rev-parse", "--short", "HEAD"],
                            capture_output=True, text=True)
    return result.stdout.strip() or None


class StudioFarm:
    open = staticmethod(open_instance)
    close = staticmethod(close_instance)
    reap = staticmethod(reap)

    @staticmethod
    @contextmanager
    def session(place, tag=None, **options):
        """`with StudioFarm.session(place, tag) as studio:` studio.id, .tag, .pid, .bridge; always closed after."""
        main = threading.current_thread() is threading.main_thread()

        def terminate(signum, frame):
            raise SystemExit(128 + signum)

        previous = signal.signal(signal.SIGTERM, terminate) if main else None
        bridge = connect()
        studio = None
        try:
            studio = open_instance(place, tag, os.getpid(), bridge, **options)
            yield studio
        finally:
            try:
                if studio:
                    close_quietly(studio.tag)
            finally:
                bridge.close()
                if main:
                    signal.signal(signal.SIGTERM, previous)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    opener = commands.add_parser("open", help="open a place in a new Studio instance")
    opener.add_argument("--place", required=True)
    opener.add_argument("--tag", help="unique name; default <directory>-<random>")
    opener.add_argument("--owner", type=int, help="local PID whose exit lets reap close it; default the caller")
    opener.add_argument("--max-studios", type=int, help="open only below this many Studios (max_studios)")
    opener.add_argument("--min-free-mb", type=int, help="open only with this much free memory (min_free_mb)")
    opener.add_argument("--wait", type=float, help="seconds to queue for room before failing (queue_seconds)")
    commands.add_parser("close", help="close one farm instance").add_argument("id", help="Studio id or tag")
    commands.add_parser("list", help="every Studio instance, farm ones annotated")
    commands.add_parser("reap", help="close farm instances whose owner process is gone")
    prober = commands.add_parser("probe", help="play a place in a farm instance, run probe scripts, capture each "
                                 "--size as PNG plus a JSON sidecar, close it")
    source = prober.add_mutually_exclusive_group(required=True)
    source.add_argument("--project", type=Path, help="Rojo project directory to build (rojo_project inside it)")
    source.add_argument("--place", type=Path, help="a built .rbxl to open as is")
    prober.add_argument("--script", type=Path, help="Server DataModel probe run once play starts")
    prober.add_argument("--client", type=Path, help="Client DataModel probe; default <script>-client.luau if present, "
                        "'none' for no client probe")
    prober.add_argument("--size", action="append", help="WxH capture size, repeatable; default 1920x1080")
    prober.add_argument("--wait", type=float, default=3, help="seconds between the scripts and the captures")
    prober.add_argument("--out", type=Path, default=Path("build/probes"))
    prober.add_argument("--tag")
    prober.add_argument("--click", action="append", help="after --wait, click the visible button whose text contains "
                        "this (or name:<ButtonName>, or name:<Prefix>* for the first whose name starts so), optional "
                        "@seconds wait; repeatable, in order")
    prober.add_argument("--click-wait", type=float, default=2.5, help="seconds after each --click")
    prober.add_argument("--emulate", help="WxH device emulation set before the clicks (keys low on the bare farm "
                        "viewport fall outside it)")
    prober.add_argument("--name", help="capture file stem; default the tag")
    prober.add_argument("--frames", type=int, default=1, help="captures per size, --every apart, on the game's own "
                        "camera; with more than one, <stem>-fNN.png and a <stem>-sheet.png")
    prober.add_argument("--every", type=float, default=0.5, help="seconds between --frames captures")
    prober.add_argument("--moments", help="t1,t2,...: seconds into the newest FxClock effect (FarmFx tag) to hold and "
                        "capture, up to 8, at the first --size; writes <stem>-<size>-mNN.png and a labelled "
                        "<stem>-<size>-moments.png (luau/FxClock.luau)")
    prober.add_argument("--hide-gui", action="store_true", help="disable every PlayerGui ScreenGui before each "
                        "capture: bare game camera frames (store page shots)")
    prober.add_argument("--audit", action="store_true", help="run probes/ui-audit.luau at each --size and write "
                        "<stem>-<size>-audit.json (small text, truncation, small keys, overlaps, occluded keys)")
    prober.add_argument("--fail-on-findings", action="store_true", help="with --audit: fail when any count is nonzero")
    prober.add_argument("--expect", help="NAME=REGEX: after the clicks, before the captures, poll the client "
                        "LocalPlayer attribute NAME until it matches (a value starting FAIL or the timeout fails)")
    prober.add_argument("--expect-timeout", type=float, default=240, help="seconds --expect waits")
    args = parser.parse_args()
    if args.command == "open":
        studio = open_instance(args.place, args.tag, args.owner, max_studios=args.max_studios,
                               min_free_mb=args.min_free_mb, queue=args.wait)
        studio.bridge.close()
        print(json.dumps({"id": studio.id, "tag": studio.tag, "pid": studio.pid}))
    elif args.command == "close":
        tag, result = close_instance(args.id)
        print(f"{tag}: {result}")
    elif args.command == "probe":
        if any(not re.fullmatch(r"\d+x\d+", size.lower()) for size in args.size or []):
            parser.error("--size takes WxH, e.g. 1920x1080")
        from farm_probe import parse_expect, parse_moments, probe
        if args.moments:
            args.moments = parse_moments(args.moments)
            if args.frames > 1 or len(args.size or []) > 1 or args.audit:
                parser.error("--moments takes one --size and no --frames or --audit")
        if args.expect:
            parse_expect(args.expect)  # a bad NAME=REGEX fails before a Studio opens
        for path in probe(args):
            print(path)
        print("PASS: probe")
    elif args.command == "reap":
        for tag, result in reap():
            print(f"{tag}: {result}")
        print("reap done")
    else:
        bridge = connect()
        try:
            for row in listing(bridge):
                print(json.dumps(row))
        finally:
            bridge.close()


if __name__ == "__main__":
    try:
        main()
    except (OSError, KeyError, ValueError, RuntimeError, TimeoutError, EOFError,
            subprocess.SubprocessError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(1)
