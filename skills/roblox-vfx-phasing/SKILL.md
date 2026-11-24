---
name: roblox-vfx-phasing
description: >-
  Use when designing, adding or tuning Roblox hit effects, sparks, debris, trails, beams, smoke, explosions or weapon sounds: phrasing an effect into warning, contact, peak and fade, ParticleEmitter, Beam and Trail lifecycle and pooling, phone budgets, and per-weapon sound sets with cooldowns. Also when an effect is invisible, mushy, laggy or never cleans up.
---

# Roblox VFX phrasing

An effect is a short sentence with four beats. Get the shape readable first, then add texture. Pooling, lifecycle and sound code is in [effects.md](effects.md); measured starting numbers (layers, brightness, timing, smoke, textures, flipbooks) are in [references/measured.md](references/measured.md).

## When to use

- A weapon, hit, KO, super or pickup needs an effect or sound, or an existing one reads as mush.
- Effects pile up, never clean up, or drop frames on phones.
- Choosing where smoke, glow or screen effects belong.

Not for: camera shake and hit-stop (roblox-game-feel), UI motion (roblox-toy-ui).

## The four beats

1. **Warning** (optional, 0.1 to 0.5 s): a telegraph that differs from the hit in shape or colour: a charge glow, a wind-up trail, a ground marker. Only when the player can or should react.
2. **Contact** (1 to 2 frames): one bold silhouette at the exact contact point: a flash, a ring, a star burst, a bright sprite. This frame carries the read.
3. **Peak** (2 to 6 frames): the brightest, biggest moment: spark burst, debris, the sound's transient.
4. **Fade** (0.2 to 0.6 s): quieter decay: embers, falling chunks, a short wisp. Stagger layer endings so nothing pops off on one frame.

**Silhouette before particles.** Turn sound and post-processing off and look: at gameplay distance, against both a dark and a bright background, can you see where and which way the hit went? If not, more particles will not fix it; a stronger contact shape will.

**Judge frame by frame.** Slow emitters with `ParticleEmitter.TimeScale` (0.1) and step captures, or record and scrub. Each beat must be distinct on its own frames.

## Layers, one job each

- Sparks: yellow, additive (`LightEmission` 1), fast, short, drag-heavy; at the contact point along the hit normal.
- Debris: team-colour studded cubes (real parts, no outline), a few per hit, more on KO; capped.
- Speed lines and wisps: white Beam or ParticleEmitter, motion only.
- Trail on swinging heads: white, short `Lifetime`, tapered `WidthScale`; the thin tail trails the motion.
- Sparkles: four-point stars on chrome, sparing.
- **Smoke only where it means something**: cannon fire, booster trail, crate landing, the KO wreck. Smoke on every hit hides the next contact.

## Lifecycle

- Burst emitters: `Rate = 0`, `Enabled = false`, fire with `:Emit(n)`. Continuous emitters: toggle `Enabled`; emitted particles finish their lifetime after disable.
- **Pool, do not clone per hit.** Build each emitter once on an attachment in a pool part; move the attachment's `WorldPosition` and `Emit`. Cloning and destroying per hit allocates and leaks when an owner dies mid-effect.
- Beams and Trails need two attachments on stable parts with an owner who removes them. A teleported attachment stretches a trail across the map: disable the trail, move, `Clear()`, re-enable.
- Temporary parts and lights: one owner, one lifetime (`Debris:AddItem` or a delayed destroy), cancel on round end.
- Effects are presentation: they fire where the physics is owned (roblox-game-feel) and never decide damage.

## Phone budgets (start points; measure on the smallest phone)

| Item | Start budget |
|------|--------------|
| Sparks per normal hit | 8 to 16 particles |
| Sparks per heavy hit | 20 to 40 |
| Debris chunks alive | 36 total, oldest removed first |
| Live particles on screen | under about 300 |
| Active Beams and Trails | under 10 |
| Dynamic lights from effects | 0 to 2, short-lived |
| Smoke emitters active | 0 to 2 |

Record the frame time beside each budget you settle on.

## Sound

- **Per weapon, a sound set**: swing or charge, contact, heavy contact, and a tail for KO. Contact sounds have a sharp transient that lines up with the contact frame.
- **Cooldowns per sound**: a minimum interval (about 0.05 to 0.08 s) and a voice cap (3 or 4) so a grinder does not stack into noise. Vary `PlaybackSpeed` by plus or minus 5 percent per play.
- **Spatial** sounds parented to an attachment at the contact point for 3D; UI sounds in SoundService.
- Sounds fire in the same step as the visual contact. A late sound makes a sharp hit feel weak.
- Check asset permissions: a sound that is not shared with the experience plays silence.

## Workflow

1. Write the four beats for the event in one line each, with durations.
2. Build the contact silhouette; capture it; confirm the read.
3. Add peak and fade layers one at a time, each with one job.
4. Pool emitters and sounds; add cooldowns.
5. Capture at gameplay distance on phone and desktop, scrub frame by frame, then count particles and frame time against the budget. With this toolkit: step the effect's clock through `luau/FxClock.luau` and capture exact beats with `tools/studio_farm.py probe --moments t1,t2,... --hide-gui`, then compare the frames against [references/measured.md](references/measured.md).

Sources: "warning, contact, peak, fade" and "silhouette before particles" restated in our own words from tabooharmony/roblox-brain roblox-animation-vfx (MIT, commit ceee4aa). "Judge effects frame by frame in readable phases" is an idea credited to SyphoDev-yt/roblox-ai-skills roblox-vfx (custom licence; idea only, no text copied). Layer list, smoke rule and debris cap from our own reference analysis and shipped game code.
