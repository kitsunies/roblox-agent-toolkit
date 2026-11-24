# Effect recipes (Luau)

Client presentation code. Verify every effect in Studio; Lune cannot render.

## Contents
1. Emitter pool
2. A phrased hit
3. Trail safety
4. Debris with a cap
5. Sound pool with cooldowns

## 1. Emitter pool

One anchored, invisible pool part; one attachment per effect kind, emitters built once.

```luau
local pool = Instance.new("Part")
pool.Name = "FxPool"
pool.Anchored, pool.CanCollide, pool.CanQuery, pool.CanTouch = true, false, false, false
pool.Transparency = 1
pool.Size = Vector3.one
pool.Parent = workspace

local function burstEmitter(name: string, props: { [string]: any }): (Attachment, ParticleEmitter)
	local a = Instance.new("Attachment")
	a.Name = name
	a.Parent = pool
	local e = Instance.new("ParticleEmitter")
	e.Rate = 0
	e.Enabled = false
	for k, v in props do
		(e :: any)[k] = v
	end
	e.Parent = a
	return a, e
end

local sparkAt, sparks = burstEmitter("Sparks", {
	Color = ColorSequence.new(Color3.fromRGB(255, 236, 120), Color3.fromRGB(255, 170, 40)),
	LightEmission = 1,
	Lifetime = NumberRange.new(0.12, 0.3),
	Speed = NumberRange.new(18, 34),
	SpreadAngle = Vector2.new(35, 35),
	Drag = 6,
	Acceleration = Vector3.new(0, -30, 0),
	Size = NumberSequence.new({ NumberSequenceKeypoint.new(0, 0.35), NumberSequenceKeypoint.new(1, 0) }),
	Squash = NumberSequence.new(-1.5), -- stretched streaks along travel
	Orientation = Enum.ParticleOrientation.VelocityParallel,
})
```

Emitters on an attachment emit along the attachment's +Y (`EmissionDirection` Top), so aim the attachment at the hit normal.

## 2. A phrased hit

Contact silhouette, then peak, then fade, each on its own frames.

```luau
local ringAt, ring = burstEmitter("Ring", {
	LightEmission = 1, Lifetime = NumberRange.new(0.08), Speed = NumberRange.new(0),
	Size = NumberSequence.new({ NumberSequenceKeypoint.new(0, 0.5), NumberSequenceKeypoint.new(1, 3) }),
	Transparency = NumberSequence.new({ NumberSequenceKeypoint.new(0, 0), NumberSequenceKeypoint.new(1, 1) }),
	LockedToPart = true,
})
local emberAt, embers = burstEmitter("Embers", {
	Color = ColorSequence.new(Color3.fromRGB(255, 150, 40)), LightEmission = 0.6,
	Lifetime = NumberRange.new(0.3, 0.6), Speed = NumberRange.new(3, 6), Drag = 3,
	Size = NumberSequence.new(0.12),
})

local function hit(point: Vector3, normal: Vector3, impact: number)
	local aim = CFrame.lookAt(point, point + normal) * CFrame.Angles(-math.pi / 2, 0, 0) -- +Y along normal
	for _, a in { ringAt, sparkAt, emberAt } do
		a.WorldCFrame = aim
	end
	ring:Emit(1) -- contact: one bold shape, frame 0
	sparks:Emit(math.floor(8 + 24 * impact)) -- peak
	task.delay(0.05, function() embers:Emit(math.floor(3 + 6 * impact)) end) -- fade starts after the peak
end
```

Pooled attachments share one position, so two hits on the same frame both draw at the last point. If simultaneous hits are common, keep two or three attachments per kind and rotate through them.

## 3. Trail safety

```luau
local function moveWithoutSmear(trail: Trail, model: Model, to: CFrame)
	trail.Enabled = false
	model:PivotTo(to)
	trail:Clear()
	task.defer(function() trail.Enabled = true end)
end
```

## 4. Debris with a cap

```luau
local MAX_CHUNKS = 36
local chunks: { BasePart } = {}

local function chunk(at: CFrame, color: Color3, velocity: Vector3)
	if #chunks >= MAX_CHUNKS then
		local oldest = table.remove(chunks, 1)
		if oldest then oldest:Destroy() end
	end
	local p = Instance.new("Part")
	p.Size = Vector3.new(0.5, 0.5, 0.5)
	p.CFrame = at
	p.Color = color
	p.Material = Enum.Material.SmoothPlastic
	p.TopSurface = Enum.SurfaceType.Studs
	p.CanQuery, p.CanTouch = false, false
	p.CollisionGroup = "Debris" -- collides with the floor, not with machines
	p.AssemblyLinearVelocity = velocity
	p.Parent = workspace
	table.insert(chunks, p)
	task.delay(2.5, function()
		local i = table.find(chunks, p)
		if i then
			table.remove(chunks, i)
			p:Destroy()
		end
	end)
end
```

Register the `Debris` collision group once (PhysicsService) and make it non-colliding with machine groups.

## 5. Sound pool with cooldowns

```luau
type Voice = { sounds: { Sound }, next: number, last: number, gap: number }
local voices: { [string]: Voice } = {}

local function register(name: string, id: string, volume: number, parent: Instance, count: number?, gap: number?)
	local v: Voice = { sounds = {}, next = 1, last = -math.huge, gap = gap or 0.06 }
	for i = 1, count or 3 do
		local s = Instance.new("Sound")
		s.Name = name .. i
		s.SoundId = id
		s.Volume = volume
		s.Parent = parent
		table.insert(v.sounds, s)
	end
	voices[name] = v
end

local function play(name: string, at: Attachment?)
	local v = voices[name]
	if not v or os.clock() - v.last < v.gap then return end -- cooldown
	v.last = os.clock()
	local s = v.sounds[v.next]
	v.next = v.next % #v.sounds + 1 -- round robin caps the voice count
	if at then s.Parent = at end
	s.PlaybackSpeed = 1 + (math.random() - 0.5) * 0.1
	s.TimePosition = 0
	s:Play()
end

-- A weapon's set: register("drill_contact", id, 0.6, workspace.FxPool, 3, 0.07)
```
