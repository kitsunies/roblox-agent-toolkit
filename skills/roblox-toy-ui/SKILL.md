---
name: roblox-toy-ui
description: >-
  Use when building, restyling or reviewing Roblox ScreenGui, HUD, menu, shop, inventory, reward or button UI in a chunky toy look (bevel lip, gradient face, tinted outlines, extruded text, springy tweens), including phone safe areas and touch targets. Not for web UI.
---

# Roblox toy UI

A token system for UI that looks like a moulded plastic toy: every button has thickness, every label has ink, every panel opens with a spring. Luau recipes live in [recipes.md](recipes.md).

## When to use

- Making or fixing any ScreenGui, BillboardGui stat pill, HUD bar, menu, shop, workshop or reward screen in Roblox.
- A screen looks flat, generic or "obby default" and needs the toy finish.
- Checking a screen for phones: safe areas, touch target sizes, text that survives the smallest scale.

Not for: web UI (use impeccable), world geometry (roblox-build-craft), hit and camera motion (roblox-game-feel).

## The look, as tokens

1. **Buttons have thickness.** Three layers: a dark rim (button background), a darker *lip* gradient peeking 4 px below the face (6 px when the button is 80 px or taller), and a bright vertical gradient *face* on top. Add one or two hard-edged diagonal glass streaks (a UIGradient on a white frame whose transparency jumps in a thin band) and a 2 px light line along the face bottom. Vary the streak bands per button so nothing looks cloned.
2. **Outlines are tinted, never black.** Every label and frame stroke uses a very dark shade of the surface it sits on (dark green on a green button, navy on blue). Pure black only for floating tooltips.
3. **Text is extruded.** Important labels exist twice: a copy in the outline colour 2 px lower, then the white label on top. Both carry a UIStroke (2 to 4 px, Contextual, Round joins). Stroke plus drop copy together, not one or the other.
4. **Icons are stickers.** Tilted -8 to -12 degrees, outlined, allowed to overflow the frame corner (a window icon hangs off the top-left).
5. **Colour has one meaning each.** Green = confirm or soft currency. Red = destroy, scrap, locked. Blue = primary navigation. Yellow = reward, claim, super. Purple = premium or crate. Grey = done or disabled. Never reuse a colour for a second meaning on the same screen.
6. **Pixel offsets plus one UIScale.** Size and position chrome in offset pixels against one reference resolution; scale is for anchors and fills only. Each root gets exactly one UIScale = clamp(min(vx/refX, vy/refY), min, max). Thin bevels stay crisp because nothing rounds independently.
7. **Corners are small.** 0 to 6 px on buttons, slots and panels; only pills and badges are fully round.
8. **Motion is springy.** Press to 0.92 in 0.05 s (Quad Out), release in 0.12 s Back Out, hover 1.04 to 1.06. Windows open 0.86 to 1 in 0.32 s Back Out and close to 0.88 in 0.16 s Quad In. Opening is slow and bouncy, closing is fast.
9. **Every interaction has a sound** (hover tick, click, open, close, success, refusal) with its own volume and pitch.

In an existing game, map these onto its own palette module, fonts and button kit; keep the existing controllers' ownership of camera, blur and CoreGui. Borrow recipes, not controllers.

## Phones first

- **Safe area.** Leave `ScreenGui.ScreenInsets` at `CoreUISafeInsets` for anything tappable so it clears the Roblox menu and chat buttons in the top-left. Read `GuiService.TopbarInset` (a Rect) and listen to its change signal if a bar must share the top row. Full-bleed backdrops may use `None`.
- **44 px targets after scaling.** The rule applies to the on-screen size, not the offset you typed. Smallest scale x offset size must be at least 44. At an 844x390 phone against a 1050x620 reference the scale is 0.63, so a tappable thing needs about 70 px of offset. A 55 px close button lands at 35 px: too small. An alternative that works well: scale by clamp(viewport.Y / 844, 1, 2.2), so phones sit at 1 (offset = on-screen px), and reflow narrow screens instead of shrinking them.
- **Text floor.** Body text at least 12 px on screen at the smallest scale; use `TextScaled` only with a `UITextSizeConstraint`.
- Check in Studio device emulation at the smallest supported phone, landscape, plus a tablet and desktop.

## Workflow

1. Name the screen's one job and its primary action. The primary action is the biggest button, never a different style.
2. Build from the recipes (button, extruded label, panel, fit scale, safe area). Build once in edit mode or once per session; never rebuild every spawn.
3. Wire springs and sounds; cancel a running tween before starting another on the same property.
4. Capture in Studio at phone, tablet and desktop sizes (roblox-studio-bridge), then run the checklist below with the capture open.

## Critique checklist

Run with the capture open. For the why behind each item, cite the matching law in laws-of-ux or principle in 12-principles-of-animation; do not restate them here.

- [ ] One obvious primary action; secondary actions visibly smaller (laws-of-ux: Von Restorff, Hick).
- [ ] Every tappable target is 44 px or more on screen at the smallest scale, and the ones used most sit closest to the thumbs (laws-of-ux: Fitts).
- [ ] Related controls share a panel or spacing group (laws-of-ux: proximity, common region).
- [ ] Layout matches what Roblox players expect from similar games (laws-of-ux: Jakob).
- [ ] Colour meanings hold across the whole screen; no red confirm, no green delete.
- [ ] Every label has a tinted stroke; key labels are extruded; no pure black outlines.
- [ ] Buttons show rim, lip and face; streaks differ between neighbours.
- [ ] Press, release, open and close use the timings above and overshoot once, then settle (12-principles: anticipation, follow through, timing).
- [ ] Motion stays under about 0.3 s except celebration moments (12-principles: timing, exaggeration).
- [ ] Nothing interactive under the Roblox top-left buttons; nothing clipped at the smallest viewport.
- [ ] The reward or result moment is the peak of the flow (laws-of-ux: peak-end).

Sources: tokens and timings adapted in our own words from Stud UI Clean Roblox by TemporaryLooker22 (MIT, pinned 7ae67f3; licence and third-party notices kept at the source, no icon ids or code copied). Fit, touch-target and clipping checks credited to SyphoDev-yt/roblox-ai-skills roblox-ui (custom licence; idea only, no text copied). Phone sizing finding from our own UI review. Critique items draw on the Laws of UX and the 12 principles of animation.
