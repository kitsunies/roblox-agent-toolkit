# Game feel patterns (Luau)

Client snippets for a machine the local client owns. Verify every pattern in Studio; Lune cannot run physics.

## Contents
1. Trauma shake
2. Coalescing hit-stop with folded kicks
3. Pause gate per impact weight
4. Knockback
5. Squash and stretch on visual parts
6. Impact frame
7. One feedback call

## 1. Trauma shake

Runs after the camera follow (roblox-camera-feel binds follow at `Camera.Value`; shake binds one priority later) and writes an offset on top.

```luau
local RunService = game:GetService("RunService")

local Shake = { trauma = 0, decay = 1.2, strength = 1, maxOffset = 0.6, maxRoll = math.rad(2.5) }
local t = 0

function Shake.add(amount: number)
	Shake.trauma = math.clamp(Shake.trauma + amount, 0, 1) -- hits add, never reset
end

RunService:BindToRenderStep("TraumaShake", Enum.RenderPriority.Camera.Value + 1, function(dt)
	if Shake.trauma <= 0 then return end
	Shake.trauma = math.max(Shake.trauma - Shake.decay * dt, 0) -- render dt is real time
	t += dt
	local k = Shake.trauma * Shake.trauma * Shake.strength
	local x = math.noise(t * 18, 0.5) * Shake.maxOffset * k
	local y = math.noise(0.5, t * 18) * Shake.maxOffset * k
	local roll = math.noise(t * 12, 7.3) * Shake.maxRoll * k
	local camera = workspace.CurrentCamera
	camera.CFrame *= CFrame.new(x, y, 0) * CFrame.Angles(0, 0, roll)
end)
```

`math.noise` returns about -0.5 to 0.5 for non-integer inputs and 0 at integers; the offsets above keep inputs off the lattice.

## 2. Coalescing hit-stop with folded kicks

Called every physics step for each owned machine (`RunService.PreSimulation` or the fight driver's step). One deadline per fight; a new hit pushes the deadline later and keeps the original pose.

```luau
type Held = { frame: CFrame, linear: Vector3, angular: Vector3, untilAt: number }

local Stop = { untilAt = 0 }
local held: { [Model]: Held } = {}

function Stop.request(seconds: number)
	Stop.untilAt = math.max(Stop.untilAt, os.clock() + seconds) -- extend, never stack
end

-- `kick` is any knockback that arrived this step (studs/s).
local function stepMachine(model: Model, root: BasePart, kick: Vector3)
	local now = os.clock()
	local h = held[model]
	if now < Stop.untilAt then
		if not h then
			h = { frame = root.CFrame, linear = root.AssemblyLinearVelocity,
				angular = root.AssemblyAngularVelocity, untilAt = Stop.untilAt }
			held[model] = h
		end
		h.linear += kick -- the thaw releases it
		model:PivotTo(h.frame)
		root.AssemblyLinearVelocity = Vector3.zero
		root.AssemblyAngularVelocity = Vector3.zero
		return
	end
	if h then -- thaw: restore motion plus every kick that landed during the stop
		root.AssemblyLinearVelocity = h.linear
		root.AssemblyAngularVelocity = h.angular
		held[model] = nil
	elseif kick ~= Vector3.zero then
		root:ApplyImpulse(kick * root.AssemblyMass)
	end
end
```

Also pause playing animation tracks during the stop (`track:AdjustSpeed(0)`, restore the saved speed at the thaw). Server-side anti-cheat must tolerate the hold: a frozen machine that jumps forward by its folded kick is not a teleport.

## 3. Pause gate

Light ticks may pause rarely, heavy hits often, never back to back.

```luau
local STOP_MIN, STOP_MAX = 0.03, 0.12 -- seconds at impact 0 and 1
local GAP_LIGHT, GAP_HEAVY = 1.0, 0.2 -- seconds since the last pause before another may start
local lastPause = -math.huge

local function pauseFor(impact: number): number?
	local gap = GAP_LIGHT + (GAP_HEAVY - GAP_LIGHT) * impact
	if os.clock() - lastPause < gap then return nil end
	lastPause = os.clock()
	return STOP_MIN + (STOP_MAX - STOP_MIN) * impact
end
```

## 4. Knockback

Only the struck machine moves. Direction from the attacker toward the target, flattened, with a little lift.

```luau
local KICK_MAX = 16 -- studs/s at impact 1

local function knockback(target: BasePart, from: Vector3, impact: number): Vector3
	local away = target.Position - from
	away = Vector3.new(away.X, 0, away.Z)
	if away.Magnitude < 1e-3 then return Vector3.zero end
	return (away.Unit + Vector3.new(0, 0.3, 0)) * KICK_MAX * impact -- feed to stepMachine as `kick`
end
```

`ApplyImpulse` only moves the body on the machine that owns it. Calling it from a client that does not own the assembly does nothing useful.

## 5. Squash and stretch

For visual-only parts. Scale along the hit normal down, the other two axes up, so volume stays near 1, then spring back.

```luau
local TweenService = game:GetService("TweenService")
local BACK = TweenInfo.new(0.18, Enum.EasingStyle.Back, Enum.EasingDirection.Out)
local active: { [BasePart]: Tween } = {}

local function squash(part: BasePart, rest: Vector3, localNormal: Vector3, amount: number)
	local n = Vector3.new(math.abs(localNormal.X), math.abs(localNormal.Y), math.abs(localNormal.Z))
	local along = 1 - amount -- e.g. 0.25 -> 0.75 along the normal
	local across = 1 / math.sqrt(along) -- keeps volume roughly constant
	local s = n * along + (Vector3.one - n) * across
	if active[part] then active[part]:Cancel() end
	part.Size = rest * s
	local tween = TweenService:Create(part, BACK, { Size = rest })
	active[part] = tween
	tween.Completed:Once(function() if active[part] == tween then active[part] = nil end end)
	tween:Play()
end
```

`rest` is the part's design size, stored once (an attribute), never read back mid-squash. Changing Size grows the part about its centre; for a hull that should squash against the ground, move the part by half the size change too. For whole models, `Model:ScaleTo(0.92)` then a NumberValue tween back to 1 gives a uniform punch.

## 6. Impact frame

```luau
local function impactFrame(highlight: Highlight)
	local fill, color = highlight.FillTransparency, highlight.FillColor
	highlight.FillColor = Color3.new(1, 1, 1)
	highlight.FillTransparency = 0
	task.delay(1 / 30, function() -- about two frames at 60 fps
		highlight.FillColor = color
		highlight.FillTransparency = fill
	end)
end
```

Reuse the machine's existing silhouette Highlight; a second Highlight per hit adds instances under a global cap.

## 7. One feedback call

```luau
local Effects = require(script.Parent.Effects) -- the project's pooled effects (roblox-vfx-phasing)
local pendingKick: { [BasePart]: Vector3 } = {}

local function feedback(impact: number, point: Vector3, attacker: BasePart, target: BasePart, highlight: Highlight)
	Shake.add(0.1 + 0.8 * impact * impact)
	local pause = pauseFor(impact)
	if pause then Stop.request(pause) end
	if impact >= 0.3 then impactFrame(highlight) end
	pendingKick[target] = (pendingKick[target] or Vector3.zero) + knockback(target, attacker.Position, impact)
	Effects.hit(point, impact) -- roblox-vfx-phasing: sparks and the weapon's sound, same step
end
```

`pendingKick` is drained by `stepMachine` in the same physics step, so freeze, kick, sparks and sound share one frame.
