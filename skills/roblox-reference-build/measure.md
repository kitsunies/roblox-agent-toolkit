# Measuring a reference

## Measurement sheet

Copy into the evidence README and fill before building.

```markdown
## <subject> reference sheet
Reference: <file or URL>, <what it shows>, <licence or "reference only">
Camera: yaw <deg> pitch <deg> FOV <deg> aspect <w:h>; subjects fill <pct> of width; contact at <x pct, y pct>
Horizon: <pct> of frame height; backdrop layers: <n>; sky <hex top> -> <hex horizon>
Palette: base <hex> lit <hex> shade <hex> outline <hex> accent <hex> -> Palette.<names>
Proportions: hull L:H:W <a:b:c>; wheel D / hull H <r>; weapon L / hull L <r>; rear/front wheel <r>
Silhouette parts: <n>; face detail: <what>
Density: hull <low/med/high>, weapon <...>, wheels <...>
Mesh-only features: <list or none> -> stand-in: <how>
```

## Reading numbers off an image

- **Ratios**: measure pixel lengths along the same axis, corrected for perspective by comparing shapes at the same depth. Use a vertical edge near the subject as a ruler.
- **Fill**: subject span in pixels / image width.
- **Horizon**: horizon row / image height, from the top.
- **Pitch from the ground plane**: if parallel lines on the floor converge steeply, pitch is high; a near-flat floor band means 10 to 20 degrees.
- **Palette**: sample flat lit areas, not edges or highlights. `ocr <image> "list the 6 dominant colours as hex"` or the Read tool on the image gives a first pass; confirm with a pixel picker.

## Side-by-side compare

Make one image with the reference left and the capture right, same height:

```bash
# ImageMagick, if installed
magick ref.png capture.png -resize x720 +append compare-v1.png
```

Then write the difference list under the image in the README, biggest first, each with a number. Revisions append; never overwrite an earlier compare, so the history shows the trend.

## Capture settings that make compares fair

- Same aspect as the reference (set the Studio viewport or use device emulation).
- Same lighting preset every time; post effects on unless you are judging silhouette.
- Hide HUD and debug parts for scene compares; show them for screen compares.
- For silhouette checks: set every part's Color to black and Material to SmoothPlastic in a scratch copy, capture, compare shapes only.
