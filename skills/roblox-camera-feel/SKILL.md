---
name: roblox-camera-feel
description: >-
  Use when writing or tuning a scripted Roblox camera for fights, arenas or showcases: deadzone, look-ahead, frame-rate-independent smoothing, zoom from subject separation, low three-quarter framing numbers, floor and backdrop clamps, and where shake plugs in. Also when a Roblox camera jitters, swims, whips after a respawn or shows the void.
---

# Roblox camera feel

A fight camera frames two subjects, moves less than they do, and never shows what is not built. Full Luau rig in [rig.md](rig.md).

## When to use

- Building or tuning a Scriptable camera for a fight, duel, arena, turntable or results shot.
- The camera jitters, lags differently on fast and slow devices, whips across the map after a reset, clips the floor or shows the void past the backdrop.
- Choosing framing numbers for a new arena or theme.

Not for: shake amounts and triggers (roblox-game-feel writes the offset this rig exposes), the default player camera (leave Roblox's PlayerModule alone unless the game takes over).

## Framing numbers (low three-quarter)

Measured from reference footage during our own project's camera review; good defaults for any side-on brawler.

| Setting | Value |
|---------|-------|
| Yaw | about 30 degrees off the fight axis, toward the player's side |
| Pitch | about 15 degrees down (10 to 20); never top-down, never a high three-quarter |
| FOV | 60 vertical (55 to 70) |
| Fill | both subjects span 70 to 85 percent of frame width |
| Composition | player left, enemy right, contact point near frame centre |
| Horizon | 45 to 60 percent of frame height, so the backdrop reads |

## The rig, in order, every render frame

1. **Focus target**: midpoint of the subjects (or the contact point when they touch).
2. **Deadzone**: move the focus only by how far the target left a box around it (per axis, about 1 to 2 studs). Kills jitter from small wobbles.
3. **Look-ahead**: add the subjects' mean velocity times a lead time (0.2 to 0.4 s), and ease the lead itself so a direction flip does not whip the view.
4. **Zoom from separation**: distance = (span / 2) / (fill x tan(horizontal half FOV)), where span is the subjects' extent projected onto the camera's right vector plus their widths. Clamp between a minimum (never inside a machine) and a maximum (the backdrop still covers the frame).
5. **Smooth**: blend position and distance with alpha = 1 - exp(-k x dt), k about 6 to 10 (higher is snappier). Never a fixed lerp factor per frame: that is floatier at 30 fps and snappier at 144.
6. **Clamp**: camera height at least floor + margin; clamp the view, not the centre, so the frame edges stay inside the built backdrop. If the arena is narrower than the view on an axis, centre on that axis instead.
7. **Shake last**: game feel writes its offset after the follow, at a later render priority. Shake inside the follow target makes the smoothing fight it.

## Rules

- `Camera.CameraType = Scriptable` while the rig owns it; restore `Custom` and the subject when the fight ends.
- Bind with `RunService:BindToRenderStep` at `Enum.RenderPriority.Camera.Value`; unbind on teardown so two rigs never write the same frame.
- Follow interpolated render positions (`BasePart.Position` read in RenderStepped is already interpolated on the client); reading physics-step snapshots jitters.
- On spawn, teleport or round start, hard-cut: set position and distance to their goals and zero the eased look-ahead. A smoothed camera slingshots otherwise.
- Pitch and yaw are fixed in a fight camera. If a turntable or orbit allows drag, clamp pitch about -80 to +45 degrees.
- Phones are wider: compute horizontal FOV from the live aspect ratio each frame, never from a constant.

## Check

- Headless: step the follow with a target moving 20 studs/s for 2 s at dt 1/30 and 1/144. With k = 8 exponential smoothing trails by 2.18 and 2.43 studs; a fixed lerp of 0.1 trails by 5.99 and 1.25.
- Studio: `screen_capture` at the fight's start, mid-brawl and KO on a phone aspect and a desktop aspect (roblox-studio-bridge). Measure subject fill and horizon height on the capture against the table above.
- Push both machines to each arena edge: no floor clipping, no void.

Sources: deadzone, look-ahead, exponential smoothing and clamp-the-view ideas adapted in our own words and ported to Luau from gamedev-skills/awesome-gamedev-agent-skills camera-systems (Apache-2.0, Copyright 2026 Abhishek Barali and contributors, commit c6ca6c4; changes: Roblox render-step rig, separation zoom, fight framing). Framing numbers from our own reference review.
