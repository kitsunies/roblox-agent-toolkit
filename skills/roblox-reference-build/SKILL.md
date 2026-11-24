---
name: roblox-reference-build
description: >-
  Use when building a Roblox scene, arena, machine, prop or screen to look like something: start from a reference image, never from imagination, then block out, capture in Studio, compare side by side and revise. Covers what to measure (proportions, camera, palette, horizon), where evidence goes, and when a mesh is really needed instead of parts and CSG.
---

# Roblox reference build

Taste comes from the reference, not from the agent. Every visual build starts with an image, ends with a capture placed beside it, and loops until the differences are named and closed. Measuring sheets and the evidence layout are in [measure.md](measure.md).

## When to use

- A new arena theme, machine, weapon, prop or screen with a look to hit.
- "Make it look like X", "match this screenshot", "it looks off but I cannot say why".
- Deciding whether something needs an uploaded mesh.

Not for: the geometry mechanics (roblox-build-craft), UI tokens (roblox-toy-ui), effect timing (roblox-vfx-phasing).

## The loop

1. **Reference.** Get one to three images that show the target from the gameplay camera. No reference, no build: ask for one or find one, and record where it came from. Use references for proportion, palette and composition; never copy another game's art, UI or branding.
2. **Measure.** Read numbers off the reference before touching Studio (see below). Write them down in the evidence note.
3. **Block out.** Big shapes only, in flat colour, at the measured proportions. No studs, trim or effects yet.
4. **Capture.** `screen_capture` from the same camera as the reference: same yaw, pitch, FOV and aspect (roblox-studio-bridge, roblox-camera-feel).
5. **Compare side by side.** Put the capture and the reference next to each other at the same height. List every difference as a sentence with a number: "hull is 20 percent too long", "horizon at 70 percent, target 50".
6. **Revise.** Fix the biggest difference first, recapture, compare again. Add detail (studs, face, trim, effects) only after the block-out matches.
7. **Stop** when the remaining differences are deliberate, and a human has looked at the pair. A build is accepted by a person, not by a passing script.

## What to measure

- **Proportions**: length to height to width of each main shape, wheel diameter against hull height, weapon length against hull length. Ratios, not studs.
- **Camera**: yaw, pitch and FOV that reproduce the reference's perspective; how much of the frame width the subjects fill; where the contact point sits.
- **Palette**: three to six colours sampled from the reference, mapped onto the project palette (its palette module), plus the outline and shadow tones.
- **Horizon and backdrop**: horizon height as a percent of frame height, number of backdrop layers, sky gradient end colours.
- **Silhouette**: is it readable as a black shape? Count the distinct parts that show in silhouette.
- **Density**: how much detail per area on the hull versus the weapon versus the wheels; keep them matched.

## Mesh or parts?

Parts and CSG first. Reach for a mesh only when the shape cannot be read at gameplay distance without it.

| Parts and CSG handle | A mesh is actually needed |
|----------------------|---------------------------|
| Wedge and slab hulls, chamfers (CornerWedge, wedges) | Soft-bevel rounded hulls |
| Ring wheels with cut hubs (subtract) | Fluted drill cones, smooth lance cones |
| Octagon saw (intersect two rotated blocks) | Rounded tread lugs |
| Stacked-cylinder drill or lance stand-ins | Outlines with interior edges |
| Outline via one Highlight | Bone-driven stretch (springs, lasers) |

If the project has no mesh pipeline: when the right column comes up, build the best parts stand-in, record the gap in the evidence note, and raise it with the user rather than importing an asset.

## Evidence

- Captures and the reference pair go in an evidence folder per slice outside the game repo (a notes folder or wiki), never in the game repo.
- Each folder has a README ledger: one line per capture with what it proves, the commit or build tag, and the measured numbers.
- Name files after what they show (`w3-hammer-side-v2.png`), not timestamps.

Sources: "build from a reference image, never from imagination" credited to SyphoDev-yt/roblox-ai-skills roblox-map (custom licence; idea only, no text copied). Measure list, mesh table and evidence layout from our own reference analysis and visual research notes.
