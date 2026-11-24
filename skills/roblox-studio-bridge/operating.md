# Operating the Studio bridge

Shapes, not a library. This toolkit's `tools/studio_farm.py` holds a working Python MCP client (`Bridge`) and the farm; reuse them.

## Contents
1. Bootstrap
2. Mutation record and reconcile
3. Long-bracket source push
4. Structured playtest
5. Multiplayer test
6. Capture
7. Studio farm shape

## 1. Bootstrap

```text
list_roblox_studios                         -> pick the ID whose place carries your marker
execute_luau(studio_id, datamodel_type=Edit,
  code='return workspace:GetAttribute("FarmTag")')
get_studio_state(studio_id)                 -> mode and DataModels
```

## 2. Mutation record

Before each mutating call write down: target (studio id plus path), pre-state read, intended post-state, the inverse change. On timeout:

```text
read target
  matches intended  -> applied; do not re-apply
  matches pre-state -> apply once
  neither           -> stop and report
read again to verify
```

## 3. Long-bracket source push

```luau
-- One execute_luau call, Edit DataModel. Pick a level whose closing bracket is not in the source.
local target = game:GetService("ReplicatedStorage").Shared.Combat
local src = [==[
-- module source here
]==]
target.Source = src
return #target.Source
```

Compare the returned length (or a hash computed the same way locally) with the file. Large payloads may hit a bridge limit; if a push fails or truncates, split by module, never by halves of one module.

## 4. Structured playtest

```text
1. Assertion: "Workspace.Fight attribute Outcome == 'Win' within 40 s".
2. start_stop_play(studio_id, is_start=true)
3. poll get_studio_state every 1 s until Server (and Client if needed) exists, deadline 60 s
4. execute_luau(datamodel_type=Server) to read the assertion target; poll with a deadline
5. finally: start_stop_play(studio_id, is_start=false); poll get_studio_state until Edit
6. report: pass/fail, read values, duration, last console lines (`tools/console_log.py` reads `LogService:GetLogHistory()` from Server and Client)
```

Python shape:

```python
bridge.tool("start_stop_play", studio_id=sid, is_start=True)
try:
    wait_for(lambda: "Server" in bridge.tool("get_studio_state", studio_id=sid), timeout=60, every=1.0)
    result = poll_assertion(bridge, sid, timeout=40)
finally:
    bridge.tool("start_stop_play", studio_id=sid, is_start=False)
    wait_for(lambda: "Edit" in bridge.tool("get_studio_state", studio_id=sid), timeout=30, every=1.0)
```

## 5. Multiplayer test

Preferred: Chrrxs `multiplayer_playtest`. Peers come back as a named group (server, client-N), so they are attributable in a shared farm with no polling. Pass `instance_id` on every call.

```python
c("multiplayer_playtest", action="start", numPlayers=2)
try:
    c("eval_server_runtime", code='return workspace:GetAttribute("Token")',
      wait_until='workspace:GetAttribute("Token") ~= nil')
    for t in ("client-1", "client-2"):
        c("eval_client_runtime", target=t, code='return workspace:GetAttribute("Token")',
          wait_until='workspace:GetAttribute("Token") ~= nil')
finally:
    c("multiplayer_playtest", action="end")  # also when start failed: a timed-out start can leave the test running
```

Official route, only when no other worker's test can start. Its peers are anonymous: during a test `list_roblox_studios` shows the server and clients with `name: null`, no file and no mode, so in a shared farm you cannot tell yours from another worker's. Attribute them as "new since I started", confirm each id with a read-only marker check before driving it, and refuse to guess if an unexpected id appears.

```luau
-- Edit DataModel. Returns at once; the test runs in new DataModels.
task.spawn(function()
	game:GetService("StudioTestService"):ExecuteMultiplayerTestAsync(2, { scenario = "trade" })
end)
return "started"
```

Then `list_roblox_studios` again: the server and both clients appear with their own IDs. Drive each with `execute_luau` on its own ID. Finish from the Server DataModel:

```luau
game:GetService("StudioTestService"):EndTest({ passed = true })
```

## 6. Capture

```python
r = bridge.request("tools/call", {"name": "screen_capture",
    "arguments": {"studio_id": sid, "capture_id": "fight-start"}})
for c in r.get("content", []):
    if c.get("type") == "image":
        Path(out, "fight-start.png").write_bytes(base64.b64decode(c["data"]))
```

For a framed still, set the camera in the same session first (Edit DataModel `workspace.CurrentCamera.CFrame`) or pass the tool's optional camera position and look-at arguments. Restore anything you made visible for the shot.

Video (official `video_capture`), Client DataModel, during play:

```python
bridge.tool("video_capture", studio_id=sid, datamodel_type="Client", is_start=True)
time.sleep(4)  # recording length
r = bridge.tool("video_capture", studio_id=sid, datamodel_type="Client", is_start=False)
```

The stop response holds only host file paths to the mp4 (about 1.7 KB); scp the files back from the Studio host. Chrrxs `capture_video` needs FFmpeg 8+ on the host; its screenshot storyboard costs about 110 KB per frame.

## 7. Studio farm shape

What the reference implementation guarantees, so a port keeps the same safety:

- **Identity by tag.** Each job copies the built place to `<tag>.rbxl` and opens that file; the tag is the only key. A probe writes the tag into the place (Workspace `FarmTag` attribute) and reads it back, which also proves the Edit DataModel answers.
- **Only close what you opened.** Close matches the tagged file on the Studio command line; an ID the farm did not record is refused.
- **Atomic lifecycle.** `with StudioFarm.session(place, tag) as studio:` opens, yields `studio.id` and `studio.bridge`, and always closes in `finally`, with Ctrl-C held off during the close so an interrupt cannot strand a window.
- **State under a lock.** One JSON state file guarded by `fcntl`; each record has the owner PID, so `reap` closes instances whose owner died.
- **Graceful then forced.** A close request, a few seconds of grace (Studio may wait on a save prompt), then a kill.
- **Windows specifics.** A GUI started over SSH never reaches the desktop, so launch and close run as one-shot scheduled tasks with an interactive principal, executing a `.ps1` file (encoded commands are blocked in such tasks).

Usage:

```python
from studio_farm import StudioFarm
with StudioFarm.session("build/Game.rbxl", "economy-check") as studio:
    b, sid = studio.bridge, studio.id
    ...  # every call passes studio_id=sid
```
