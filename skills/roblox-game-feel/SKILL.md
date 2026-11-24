---
name: roblox-game-feel
description: >-
  Use when Roblox hits, impacts, knockouts or weapon contacts feel weak, floaty, laggy or not punchy: trauma-squared camera shake, hit-stop that coalesces overlapping hits, squash and stretch, knockback on the struck body, impact frames, and where feedback must fire in a client-owned physics fight. Luau.
---

# Roblox game feel

Feedback sells an impact: several short, exaggerated responses fired together on one event. Juice never changes the outcome; it moves the camera, holds a pose or plays an effect, and the simulation stays honest. Luau for every pattern is in [patterns.md](patterns.md).

## When to use

- A hit, KO, landing or weapon contact works but reads weak, floaty or late.
- Adding or tuning shake, hit-stop, squash, knockback, impact frames or their tiers.
- Feedback that arrives after the hit, or hits that feel like lag.

Not for: follow, framing and smoothing (roblox-camera-feel, which owns the camera this skill nudges), particle and sound design (roblox-vfx-phasing), UI motion (roblox-toy-ui).

## Fire feedback where the physics lives

The lesson that cost this project a week: **feedback fires from the simulation that owns the physics, in the same step as the contact.**

- A machine whose network owner is the client senses its own contact, plays sound, sparks, hit-stop and kick in that step, then reports the contact to the server for pricing.
- Waiting for the server to see the contact and send an event back adds the replication delay twice. In Studio a drill overlap took 284 ms to feel this way (the server saw the overlap 250 ms late); a replicated event batch alone arrives about 100 ms late. Players read that as lag, not as a hit.
- The server stays authoritative for damage, rewards and cheat checks: it vets each report (rate, finite, bounds, reach) and lands any contact the client fails to report within a short window, so a client cannot dodge hits by staying silent.
- Server-owned bodies and spectators get the replicated version; that is acceptable because they never felt the contact first-hand.

## The five patterns

1. **Shake from trauma squared.** Events add trauma (clamped 0 to 1); it decays linearly per real second; offset = max offset x trauma^2 x smooth noise. Light hits barely move, heavy hits punch, and shake always ends. Write it as an offset on top of the camera's follow, after the follow runs.
2. **Hit-stop that coalesces.** Hold both machines' poses for 0.03 to 0.12 s. A second hit during a stop extends the one deadline (take the later end); it never starts a second stop or restores early. Gate how often stops may happen (heavy hits every 0.2 s at most, light ticks about once a second) so grinders never stutter-lock.
3. **Knockback on the struck body only.** Apply the impulse to the struck assembly's root, scaled by its mass, on the side that owns it. During a hit-stop, fold the kick into the held velocity so the thaw releases it; a kick applied after the thaw reads as a second, late jolt.
4. **Squash and stretch on visual parts.** Squash along the hit normal and stretch across it, keeping volume roughly constant, then spring back with Back Out in about 0.18 s. Only on visual-only art (CanCollide false, Massless); resizing physics parts changes mass and collisions.
5. **Impact frame.** One or two frames where the struck machine's Highlight fill goes solid white (or the screen inverts behind a frame) at the moment of contact, then snaps back. Keep large flashes to three per second or fewer and offer a reduce-flashing toggle.

## Tiers

Scale every channel by one impact weight per weapon (0 to 1), not by the damage roll, so a slow cannon sells hard and a fast grinder ticks lightly.

| Tier | Trauma | Hit-stop | Kick (studs/s) | Extra |
|------|--------|----------|----------------|-------|
| tick (grinder, chip) | 0.1 to 0.2 | none or about 1 per second | 0 to 4 | sparks, tick sound |
| hit | 0.3 to 0.5 | 0.04 to 0.06 s | 6 to 10 | impact frame |
| heavy (cannon, hammer, KO) | 0.7 to 1.0 | 0.08 to 0.12 s | 12 to 16 | impact frame, zoom punch |

## Workflow

1. Find the discrete event (contact, KO). Add a signal if none exists; never poll for "did a hit happen".
2. Give the weapon an impact weight and route every channel through one `feedback(weight, point, normal)` call.
3. Fire it on the owner, in the physics step that saw the contact.
4. Check headless where possible (Lune or a spec): two hits 30 ms apart leave one stop that ends at the later deadline; trauma reaches 0 within 1 / decay seconds; squash ends at exactly rest size.
5. Check in Studio with an `os.clock()` log on the owning client: sound, sparks, freeze and kick land in the same frame as the contact, and the kick is released at the thaw. Then ask a human whether the hit reads.
6. Ship toggles: shake strength 0 to 100 percent, reduce flashing.

## Gotchas

- Shaking the machine instead of the camera desyncs collisions; shake the camera only.
- `math.random()` per frame buzzes; use `math.noise` or summed sines over time.
- Roblox has no global time scale. Hit-stop is a held pose plus paused animations (`AnimationTrack:AdjustSpeed(0)`), not slowed time; shake, UI and sound keep running in real time.
- Anchoring a client-owned part to freeze it drops network ownership; hold the pose with `PivotTo` and zero velocity each step instead.
- Re-triggerable tweens fight each other: cancel the previous tween on the same property first.
- Juice on every routine action hides the real hits; footsteps and idle ticks get the lowest tier or nothing.

Sources: shake, hit-stop and squash patterns adapted in our own words and ported to Luau from gamedev-skills/awesome-gamedev-agent-skills game-feel (Apache-2.0, Copyright 2026 Abhishek Barali and contributors, commit c6ca6c4; changes: Roblox port, owner-side firing, coalescing deadline, mass-scaled kick). Trauma shake after Squirrel Eiserloh, GDC 2016. Netcode lesson and numbers from our own playtests.
