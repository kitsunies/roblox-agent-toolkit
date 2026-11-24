---
name: roblox-build-craft
description: >-
  Use when building or editing Roblox geometry from native Parts, WedgeParts, cylinders and CSG (machines, hulls, wheels, props, arenas), by script or through Studio MCP, and when a build has gaps, z-fighting, default grey parts, wrong orientation or too many parts. Includes the toy-look rules (studs, 3-tone shading, one silhouette Highlight) and a validation script. No Blender.
---

# Roblox build craft

Geometry that stays crisp, readable and cheap. Recipes and the validation script are in [craft.md](craft.md).

## When to use

- Scripting or MCP-building any Model from Parts and CSG: machines, weapons, wheels, props, arena pieces.
- Fixing gaps, z-fighting, falling parts, sideways cylinders, backwards wedges or "unfinished grey".
- Reviewing a build for the toy look and part budget.

Not for: deciding what to build or matching a reference (roblox-reference-build), effects (roblox-vfx-phasing), UI (roblox-toy-ui).

## Geometry rules

1. **Snap to the grid.** Every size and offset is a multiple of 0.125, 0.25 or 0.5 studs. Values like 0.33 or 1.17 compound into visible seams.
2. **Name your dimensions.** A table of named sizes at the top (hull length, wheel radius, armour thickness); no magic numbers in the body.
3. **Offset from an anchor.** Place every sub-part as `anchor.CFrame * CFrame.new(offset)`, never at guessed world coordinates. Build at the origin, then `PivotTo` the finished model to its destination.
4. **CSG epsilon.** Cutters overshoot every face they cut through by 0.05 studs on each side, or coplanar faces z-fight and leave paper-thin skins.
5. **CSG is fallible.** Wrap `SubtractAsync`, `UnionAsync` and `IntersectAsync` in `pcall`, check the result is a BasePart, copy CFrame, colour and material back, and destroy the inputs only on success. Keep CSG trees shallow and do it near the origin, where float precision is best. Decorative unions get `CollisionFidelity = Box`.
6. **Set everything explicitly.** Colour and Material on every part (default grey Plastic means unfinished), `Anchored` (defaults to false, so parts fall), `CanCollide`, `CastShadow`, `Massless` for art welded to a physics body.
7. **Know the primitives.** A cylinder's length runs along its X axis (rotate 90 degrees about Z to stand it up). A WedgePart is full height at the back (+Z) and slopes down to its thin edge at the front (-Z) (verified by Studio capture; the common guess of +Z is wrong). Neon glows but lights nothing; add a PointLight if it must. CornerWedgePart exists for chamfered corners.
8. **Art and physics are separate.** Visual parts are `CanCollide false`, `CanQuery false`, `CanTouch false`, `Massless true`, welded to the physics body. Never let new decoration change mass, collision or mount names.

## Player scale (when the build meets an avatar)

Avatar about 5 studs tall; door 4 x 7; ceiling 10 to 14; counter 3.5 to 4; seat 1.5; paths 6 or wider.

## Toy-look rules

1. **One readable primitive per hull**, never a stack of cubes: a wedge (slanted front to tall rear, length about 3x height) or a tall slab with a chamfered back-top corner (height about 1.1x length).
2. **Studs on every coloured face**: `Enum.SurfaceType.Studs` on Block faces, stud tone about 15 percent lighter than the base. Tyres, joints and black weapon parts stay smooth. Where studs do not render (wedge slopes, cylinders, balls), fall back to a tiled stud Texture.
3. **Hard 3-tone shading** from one key light upper-left: lit top, mid side, dark shade. Fake it with face plates in three tones of the base colour; SmoothPlastic or Plastic only on hulls; chrome (Metal, Reflectance 0.5 to 0.7) only on blades and weapon heads.
4. **One silhouette Highlight per machine**: OutlineColor near-black, FillTransparency 1, DepthMode Occluded. One per Model, not per part.
5. **Never pure black.** Tyres are near-black navy; outlines are a dark tint.
6. **Weapons oversized and weapon-first**, leaning back 15 to 25 degrees at rest; detail density on the weapon matches the wheels.
7. **One face detail per chassis** (sensor cube with eyes, grille, bumper) so every machine has character.

## Part budgets

Start here, then measure on the smallest target phone and tighten:

| Thing | Start budget |
|-------|--------------|
| Hero machine (hull, wheels, weapons, face) | 60 to 150 BaseParts |
| Weapon | 6 to 25 parts |
| Wheel | 2 to 6 parts (tyre, hub, studs via surface) |
| Highlights on screen | 2 to 3 (engine cap 255) |
| CSG unions per machine | under 10 |

Count with the validation script, not by eye. A budget is a measured number, not a guess: record the frame time beside it.

## Workflow

1. Write the dimension table and the anchor; decide forward (for example -Z) and the pivot.
2. Big silhouette first, then functional mid shapes (wheels, weapon, face), then restrained trim.
3. Build in bounded batches (20 to 30 parts per MCP call) and read back after each. Wrap each batch in `ChangeHistoryService:TryBeginRecording` / `FinishRecording` (Commit on success, Cancel on error) so a bad batch undoes as one step.
4. Run the validation script. Fix every error; justify every warning.
5. Capture front, side and three-quarter at gameplay distance (roblox-studio-bridge) before adding detail.

Sources: geometry craft adapted and trimmed in our own words from tabooharmony/roblox-brain roblox-building (MIT, commit ceee4aa; we kept spatial rules, CSG, platform quirks, validation and acceptance, dropped asset, terrain and Editable sections). Toy-look rules from our own reference analysis of chunky toy-style Roblox games.
