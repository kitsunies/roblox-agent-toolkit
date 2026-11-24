# Build craft recipes (Luau)

Edit-mode or server snippets. Each MCP `execute_luau` call is stateless: re-find the model at the top of every call.

## Contents
1. Part helper with explicit properties
2. Anchor offsets and grid snap
3. Safe CSG
4. Cylinder and wedge orientation
5. Studs and 3-tone plates
6. Silhouette Highlight
7. Validation script

## 1. Part helper

```luau
local function part(parent: Instance, name: string, size: Vector3, cf: CFrame, color: Color3, props: { [string]: any }?): Part
	local p = Instance.new("Part")
	p.Name = name
	p.Size = size
	p.CFrame = cf
	p.Color = color
	p.Material = Enum.Material.SmoothPlastic
	p.Anchored = true -- defaults to false
	p.CanCollide = true
	p.CastShadow = true
	p.TopSurface = Enum.SurfaceType.Smooth
	p.BottomSurface = Enum.SurfaceType.Smooth
	if props then
		for k, v in props do
			(p :: any)[k] = v
		end
	end
	p.Parent = parent
	return p
end

-- Visual-only art welded to a physics body.
local ART = { CanCollide = false, CanQuery = false, CanTouch = false, Massless = true, Anchored = false }
```

## 2. Anchors and snapping

```luau
local function snap(v: number, step: number?): number
	local s = step or 0.25
	return math.round(v / s) * s
end

local D = { -- named dimensions, all on the grid
	HullLength = 6, HullHeight = 2, HullWidth = 3.5,
	WheelRadius = 1.25, WheelWidth = 0.75, WheelInset = 0.5,
}

local model = Instance.new("Model")
model.Name = "Machine"
local hull = part(model, "Hull", Vector3.new(D.HullWidth, D.HullHeight, D.HullLength), CFrame.new(), Color3.fromRGB(46, 156, 250))
model.PrimaryPart = hull
local ox = D.HullWidth / 2 - D.WheelInset
local oz = snap(D.HullLength * 0.3)
-- every sub-part from the anchor, never from world coordinates
local wheelCF = hull.CFrame * CFrame.new(ox, -D.HullHeight / 2, oz)
model:PivotTo(CFrame.new(0, 10, 0)) -- move the finished model last
```

## 3. Safe CSG

```luau
local EPS = 0.05

-- A cutter that fully passes through `thickness` along its local Z.
local function cutter(size: Vector3, cf: CFrame, thickness: number): Part
	return part(workspace, "Cutter", Vector3.new(size.X, size.Y, thickness + EPS * 2), cf, Color3.new(1, 0, 0))
end

local function subtract(base: BasePart, cutters: { BasePart }): PartOperation?
	local ok, out = pcall(function()
		return base:SubtractAsync(cutters)
	end)
	if not (ok and typeof(out) == "Instance" and out:IsA("PartOperation")) then
		warn("CSG failed on", base:GetFullName(), out)
		for _, c in cutters do c:Destroy() end
		return nil -- base untouched
	end
	local result = out :: PartOperation
	result.CFrame = base.CFrame
	result.UsePartColor = true
	result.Color = base.Color
	result.Material = base.Material
	result.Anchored = base.Anchored
	result.CollisionFidelity = Enum.CollisionFidelity.Box -- decorative
	result.Name = base.Name
	result.Parent = base.Parent
	base:Destroy()
	for _, c in cutters do c:Destroy() end
	return result
end
```

`UnionAsync` and `IntersectAsync` follow the same shape. Do the operation near the origin, then move the result.

## 4. Orientation

```luau
-- Cylinder: length on X. Upright pillar:
local pillar = part(model, "Pillar", Vector3.new(4, 1, 1), CFrame.new(0, 2, 0) * CFrame.Angles(0, 0, math.rad(90)), Color3.fromRGB(122, 140, 160))
pillar.Shape = Enum.PartType.Cylinder
-- Wheel: axle along X already, so a wheel on a machine facing -Z needs no rotation.

-- WedgePart: thin edge toward -Z (forward on a -Z machine) by default, full height at +Z.
--   tip up      CFrame.Angles(math.rad(90), 0, 0)
--   tip down    CFrame.Angles(math.rad(-90), 0, 0)
--   tip toward +Z  CFrame.Angles(0, math.rad(180), 0)
```

Check orientation with a capture, not by reasoning: a backwards wedge is the most common error.

## 5. Studs and 3-tone plates

```luau
local function lighten(c: Color3, k: number): Color3
	return c:Lerp(Color3.new(1, 1, 1), k)
end
local function darken(c: Color3, k: number): Color3
	return c:Lerp(Color3.new(0, 0, 0), k)
end

local FACES = { "Top", "Bottom", "Front", "Back", "Left", "Right" }
local function studded(p: BasePart)
	for _, face in FACES do
		(p :: any)[face .. "Surface"] = Enum.SurfaceType.Studs
	end
end

-- Three tones from one base: lit top, mid sides, dark under/shade.
local function tones(base: Color3)
	return { lit = lighten(base, 0.18), mid = base, shade = darken(base, 0.3) }
end
```

Surface studs render on Block, WedgePart, Cylinder and Ball faces of 0.5 stud and up, but only with `Material = Plastic` (never SmoothPlastic), and no public stud Texture asset loads, so switch studded parts to Plastic instead of texturing.

## 6. Silhouette Highlight

```luau
local function outline(model: Model): Highlight
	local h = model:FindFirstChildOfClass("Highlight") or Instance.new("Highlight")
	h.Adornee = model
	h.OutlineColor = Color3.fromRGB(12, 14, 20)
	h.OutlineTransparency = 0
	h.FillTransparency = 1
	h.DepthMode = Enum.HighlightDepthMode.Occluded
	h.Parent = model
	return h
end
```

## 7. Validation script

Paste into one `execute_luau` call; set `ROOT` to the model's path. Prints errors (must fix), warnings (justify) and the part count for the budget.

```luau
local ROOT = workspace:FindFirstChild("Machine")
assert(ROOT, "root not found")
local DEFAULT = Color3.fromRGB(163, 162, 165)
local errors, warnings, parts, unions, highlights = {}, {}, 0, 0, 0
local function onGrid(v: number) return math.abs(v / 0.125 - math.round(v / 0.125)) < 1e-3 end

for _, d in ROOT:GetDescendants() do
	if d:IsA("Highlight") then highlights += 1 end
	if not d:IsA("BasePart") then continue end
	parts += 1
	if d:IsA("UnionOperation") then unions += 1 end
	local name = d:GetFullName()
	local art = not d.CanCollide
	if not d.Anchored and not art and #d:GetJoints() == 0 then
		table.insert(errors, name .. ": unanchored and unwelded")
	end
	if d.Color == DEFAULT and d.Material == Enum.Material.Plastic then
		table.insert(errors, name .. ": default grey Plastic")
	end
	if art and not d.Massless then
		table.insert(warnings, name .. ": non-colliding art is not Massless")
	end
	if d.Position.Y - d.Size.Y / 2 < -0.5 then
		table.insert(warnings, name .. ": below the floor")
	end
	if not (onGrid(d.Size.X) and onGrid(d.Size.Y) and onGrid(d.Size.Z)) then
		table.insert(warnings, name .. string.format(": off-grid size %s", tostring(d.Size)))
	end
	if d.Material == Enum.Material.Metal and d.Name:lower():find("hull") then
		table.insert(warnings, name .. ": chrome on a hull")
	end
end
if highlights > 1 then table.insert(warnings, highlights .. " Highlights; one per machine") end

for _, e in errors do print("[ERROR] " .. e) end
for _, w in warnings do print("[WARN] " .. w) end
print(string.format("parts=%d unions=%d highlights=%d errors=%d warnings=%d",
	parts, unions, highlights, #errors, #warnings))
```
