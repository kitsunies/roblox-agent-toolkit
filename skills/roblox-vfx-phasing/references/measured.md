# Measured VFX figures

Starting values for Roblox effects, as a data sheet. Sample: 49 effect files by experienced artists (5,010 ParticleEmitters, about 1,200 textures, their videos) plus a community kit of 1,108 textures. Medians unless marked; a range is the middle of the spread. Tune by eye at gameplay distance; these are not targets.

Source: the measurement method and figures come from the Roqer project's VFX study (S4US/Roqer, AGPL-3.0). Only the facts are used here, in our own structure and wording; no Roqer text or code.

## Layer counts

| Figure | Value |
| --- | --- |
| Layers in one studied slash hit | 40 to 60 |
| Layers in a small orb (one attachment) | 17 |
| EmitCount, median | 1 |
| Emitters with Speed near 0 | about 37% |
| Scatter bursts (sparks, droplets, debris, dots) | 10 to 160 particles |
| Files with glowing meshes beside particles | about 20 of 48 |
| Black layers, all emitters | about 7% |
| Black layers, value-contrast pieces | 10 to 35% |
| Dark backing: ZOffset / size against the colour layer | -1 to -3 / 1.1 to 4.5x |
| Complementary accent | about 1 layer in 10 |

Reading: build from many small, mostly stationary sprites timed against each other; keep big counts for scatter; put a dark layer behind coloured ones for value contrast.

## Orientation

| Orientation | Share | Typical use |
| --- | --- | --- |
| FacingCamera | 40% | puffs, glows, flares, impact stars |
| VelocityPerpendicular | 34% | flat rings, sigils, crescents, ground marks |
| VelocityParallel | 23% | sparks, flame tongues, speed lines, debris |
| FacingCameraWorldUp | 3% | rising columns |

## Brightness and LightEmission

| Layer | Brightness | LightEmission / other |
| --- | --- | --- |
| All layers, median | near 9 (other sample 3 to 10); top quarter over 25 | |
| Hottest layer of a hit (26 impacts) | about 15; 50+ in a third | |
| White-hot core (1 or 2 front layers) | 50 to 150 | shaped (spikes, star, ring); lives 0.03 to 0.1 s |
| Glows, halos | 1 to 6 | LightEmission 1; soft ones about 2/3 transparent |
| Sharp shapes | about 4 | |
| Four-point flares | 5 to 12 | |
| Neon mesh flash | about 78 down to 27 by 7% of life | white to black as the ring grows |

- Saturated layers at LightEmission 0.3 or less: 58%. In daylight, colour lives on solid layers.
- Additive blending can only brighten the backdrop; on a bright sky colour drifts to pastel and then white. Pale pixel share: mostly additive test effect 74 to 85%, studied videos 2 to 21%; over about 40% reads washed out.
- A dark layer on a bright background: LightEmission 0 = solid ink, about 0.55 = faint veil, 1 = invisible.

## Colour over life

- Fire layers (1,391): 87% keep their hue and shift toward red; some open blue or violet for the first 10 to 25% of life.
- Fire body end colour: deeper own hue 73%, grey 24%, black 3%.
- Self-lit darks are not dark: at LightInfluence 0, #3f3f3f at Brightness 5 to 16 shows light grey to white; #2b190c at Brightness 15 to 65 shows glowing brown. At Brightness 1 both are black.
- One-shot sheets in fragments by their dark tail: 82%. So a dark end at LightEmission 0 reads as embers on fragments and as a black blob on a whole puff.

## Explosion and impact timing (seconds from the flash; three studied explosions)

| Beat | Stylized | Realistic |
| --- | --- | --- |
| Flash | 1 to 2 frames: big soft glow, yellow-white core, thin cross flare | floor-lighting white-out |
| Fire body | 0.05 to 0.33: boiling shapes, white core, orange, red rim | to about 0.5, patchy by 0.3 |
| Burn-out | 0.3 to 0.5: charcoal core, glowing rims and cracks | 0.4 to 0.8, dark smoke takes over |
| Smoke peak | 0.33 to 0.6, area at most half the fire's | about 0.8, low and spreading |
| Gone | 0.6 to 1.2, embers slightly later | smoke 2 to 3 more |

Brightness falls monotonically after the flash: no second ignition.

## Fire body layers (152 flipbooks)

| Figure | Value |
| --- | --- |
| Sheet layout | 4x4 on 84, 8x8 (rendered, realistic) on 46 |
| OneShot | 97% |
| Layers per explosion | 1 to 7, median 3 |
| EmitCount per layer | 3 to 28, or a short Rate burst |
| Lifetime | 0.45 to 1 s (hit); 1 to 7 s (slam, nuke) |
| Speed / Drag | median 88 (outliers 190 to 460) / about 3: fast out, then nearly still |
| Size | constant on 45% (growth comes from the frames); eased out on the rest |
| Random Rotation / Size spread | 73% / 60% |
| Brightness | median 5 (2.7 to 15); one hot layer up to 15 to 25 |
| LightEmission | median 0.2 (0 to 0.5) |
| One boiling fireball | three drawn 4x4 sheets, Rate 55 to 90, Speed 225 to 380, Drag 3 to 4, particle life 0.35 to 0.75 s |

## Smoke (320 layers)

| Figure | Value |
| --- | --- |
| LightInfluence 0 / 0.5 or more | 68% / 20% |
| Flipbook (mostly 4x4 OneShot) | 71% |
| Soft or mottled texture | 72% |
| Self-lit solid smoke value | about 0.71 (0.34 to 1.2): mid to light grey |
| Transparency at its most solid | about 0.59 (0.26 to 0.79); under 0.2 on 20% |
| Fades in instead of starting solid | 23% |
| Grey / tinted (warm near fire, or the effect hue) | 63% / 30% |
| Lifetime | about 1.0 s (0.56 to 1.39); 3 to 7 s only for a slam's final cloud |
| Dark smoke | 40 of 320; peak Transparency about 0.5, often 0.8 to 0.92; usually beside light smoke |

## Size and transparency curves

- Size keys with a per-particle envelope of about 1/3 of the peak: 51% of emitters, in 37 of 39 files. Result: no two particles alike.
- Spawn snap: Squash 2 to 0 within the first 2% of life.
- Lingering layer: up to about +20% size across 2 s of fading.
- Held sprite: Transparency 1 to 0 over the first 20% of life, held until 80%, back to 1.

## Textures (1,393)

| Family (told apart by alpha) | Edge | Pixels at full brightness | Where used |
| --- | --- | --- | --- |
| Crisp drawn matter | hard alpha | about 19% | mostly LightEmission 0; 65% of flipbook emitters use crisp or near-crisp sheets |
| Soft light | smooth falloff | about 1% | 83% of LightEmission 1 emitters, 77% of single-image emitters |
| Mixed | | about 29% | |

- Line textures (752): about 13% of a stroke near full, 40% faint. Far above the family's share reads cheap.
- Rings (159): 84% uneven around the circle (thick bright arc thinning away, broken strokes, radial streaks). Spread round the ring: brightness about 32%, width about 51%; about 8% at full brightness. Brightness spread under 15% with width spread under 25% reads as clip art.
- Size: square; 1024 px on 93% of 89 flipbooks and 42% of 122 single images. Roblox caps a side at 1024. Tiles are opaque and seamless (opposite edges within about 4%).
- Community kit smoke: mostly soft or mottled; 11 flat cel puffs (peak Transparency about 0.53).

## Flipbooks

| Figure | Value |
| --- | --- |
| 4x4 share of flipbook emitters | 81% (Grid2x2, Grid8x8 the other built-ins; Custom 7%, beta) |
| Sheet size | 1024x1024 |
| One-shot sheets (463): break apart / shrink and fade / erode whole | 57% / 15% / 6% |
| Largest drawing | about 27% through the sheet |
| Fire sheets ending in blank cells | 55 of 79 |
| Outline change between 4x4 frames | about 44%; 5% static (rings, cracks, glows that only fade) |
| Impact star sheets (18) | peak size about 1/5 in; last drawn cell about 73% through; every frame redrawn |

- Impact star shapes: shards leaving a solid centre that hollows into a ring, or a rotating four-point flare. The flash is its own 1 or 2 frame layer.
- A frame that changes less than about 12% from the last is wasted.
- Some hand-drawn sets keep half the frames under 27% of the cell and scale with particle Size; both approaches work.

## Trails

- Textured: 58 of 66 (streaks, torn or dripping edges, tapered shards, wisps). Untextured ones look like a plain tube.
- Wide soft wisps: Lifetime 0.15 to 0.4, LightEmission 0.55 to 0.75, WidthScale tapering to 0.
- Gap behind the head over the first 15% of length; end fades over 5 to 10%.
