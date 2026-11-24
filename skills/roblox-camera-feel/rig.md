# Fight camera rig (Luau)

One LocalScript-owned module. Subjects are BaseParts (machine roots). Verify in Studio at phone and desktop aspects.

```luau
local RunService = game:GetService("RunService")

local Rig = {
	yaw = math.rad(30), -- off the fight axis
	pitch = math.rad(15), -- looking down
	fov = 60, -- vertical
	fill = 0.78, -- subjects span this share of frame width
	deadzone = Vector3.new(1.5, 1, 1.5), -- studs, half extents
	lead = 0.3, -- look-ahead seconds
	leadRate = 4, -- how fast the look-ahead itself eases
	rate = 8, -- follow smoothing; 6 floaty, 10 snappy
	minDist = 14,
	maxDist = 60,
	floorY = 0,
	floorMargin = 2,
	bounds = nil :: { min: Vector3, max: Vector3 }?, -- built backdrop extent at subject depth
	axis = Vector3.new(1, 0, 0), -- fight axis, player toward -axis
}

local focus: Vector3?
local dist: number?
local leadOffset = Vector3.zero

local function alpha(k: number, dt: number): number
	return 1 - math.exp(-k * dt) -- same convergence at any frame rate
end

local function viewDir(): Vector3
	-- Camera looks along this direction: perpendicular to the axis, turned by yaw, tipped down by pitch.
	local side = Vector3.yAxis:Cross(Rig.axis).Unit -- horizontal, perpendicular to the fight axis
	local flat = (CFrame.fromAxisAngle(Vector3.yAxis, Rig.yaw) * side)
	return (flat * math.cos(Rig.pitch) - Vector3.yAxis * math.sin(Rig.pitch)).Unit
end

local function goalDistance(a: BasePart, b: BasePart, camera: Camera, look: Vector3): number
	local right = look:Cross(Vector3.yAxis).Unit
	local span = math.abs((b.Position - a.Position):Dot(right)) + (a.Size.Magnitude + b.Size.Magnitude) * 0.5
	local aspect = camera.ViewportSize.X / math.max(camera.ViewportSize.Y, 1)
	local halfH = math.atan(math.tan(math.rad(Rig.fov) / 2) * aspect)
	return math.clamp((span / 2) / (Rig.fill * math.tan(halfH)), Rig.minDist, Rig.maxDist)
end

local function deadzoned(current: Vector3, target: Vector3): Vector3
	local d = target - current
	local function over(v: number, half: number) return math.sign(v) * math.max(math.abs(v) - half, 0) end
	return current + Vector3.new(over(d.X, Rig.deadzone.X), over(d.Y, Rig.deadzone.Y), over(d.Z, Rig.deadzone.Z))
end

function Rig.cut()
	focus, dist, leadOffset = nil, nil, Vector3.zero -- next frame snaps to its goals
end

function Rig.start(a: BasePart, b: BasePart)
	local camera = workspace.CurrentCamera
	camera.CameraType = Enum.CameraType.Scriptable
	camera.FieldOfView = Rig.fov
	Rig.cut()
	RunService:BindToRenderStep("FightCamera", Enum.RenderPriority.Camera.Value, function(dt)
		if not (a.Parent and b.Parent) then return end
		local look = viewDir()
		local mid = (a.Position + b.Position) / 2
		local vel = (a.AssemblyLinearVelocity + b.AssemblyLinearVelocity) / 2
		leadOffset = leadOffset:Lerp(Vector3.new(vel.X, 0, vel.Z) * Rig.lead, alpha(Rig.leadRate, dt))

		local goalFocus = deadzoned(focus or mid, mid) + leadOffset
		local goalDist = goalDistance(a, b, camera, look)
		if focus and dist then
			local s = alpha(Rig.rate, dt)
			focus = focus:Lerp(goalFocus, s)
			dist = dist + (goalDist - dist) * s
		else
			focus, dist = goalFocus, goalDist -- hard cut
		end

		local f, d = focus :: Vector3, dist :: number
		if Rig.bounds then -- clamp the view, not the centre
			local aspect = camera.ViewportSize.X / math.max(camera.ViewportSize.Y, 1)
			local halfW = d * math.tan(math.rad(Rig.fov) / 2) * aspect
			local lo, hi = Rig.bounds.min, Rig.bounds.max
			local x = if hi.X - lo.X < halfW * 2 then (lo.X + hi.X) / 2 else math.clamp(f.X, lo.X + halfW, hi.X - halfW)
			f = Vector3.new(x, f.Y, f.Z)
		end
		local pos = f - look * d
		pos = Vector3.new(pos.X, math.max(pos.Y, Rig.floorY + Rig.floorMargin), pos.Z)
		camera.CFrame = CFrame.lookAt(pos, f)
	end)
end

function Rig.stop(humanoid: Humanoid?)
	RunService:UnbindFromRenderStep("FightCamera")
	local camera = workspace.CurrentCamera
	camera.CameraType = Enum.CameraType.Custom
	if humanoid then camera.CameraSubject = humanoid end
end

return Rig
```

Notes:
- The bounds clamp assumes the fight axis is world X; rotate into axis space first for other layouts.
- The shake from roblox-game-feel binds at `Camera.Value + 1` and multiplies an offset onto `camera.CFrame` after this rig writes it.
- Yaw sign decides which side the player stands on; flip it rather than mirroring the arena.
- Headless check (Lune, no Roblox types needed): run `alpha` against a point moving 20 studs/s for 2 s at dt 1/30 and 1/144 and assert the trailing distances stay within 15 percent of each other (k = 8 gives 2.18 and 2.43 studs; a fixed lerp of 0.1 gives 5.99 and 1.25).
