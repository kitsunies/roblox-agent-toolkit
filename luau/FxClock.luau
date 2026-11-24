--!strict
-- The effect handle convention: an effect that runs on its own clock steps it through FxClock, so the Studio farm can
-- stop it at exact moments (`studio_farm.py probe --moments`). In Studio only: the effect's root is tagged FarmFx and
-- carries FxBorn (os.clock at start) and FxTime (its clock); the clock never passes workspace attribute FarmFxHold
-- (seconds), and while held every ParticleEmitter under the root has TimeScale 0. Live servers get a plain clock.
local FxClock = {}
FxClock.__index = FxClock
FxClock.TAG = "FarmFx"

export type Clock = typeof(setmetatable({} :: { root: Instance, t: number, studio: boolean, held: boolean }, FxClock))

function FxClock.new(root: Instance): Clock
	local studio = game:GetService("RunService"):IsStudio()
	if studio then
		root:SetAttribute("FxBorn", os.clock())
		root:SetAttribute("FxTime", 0)
		game:GetService("CollectionService"):AddTag(root, FxClock.TAG)
	end
	return setmetatable({ root = root, t = 0, studio = studio, held = false }, FxClock)
end

-- Pure: the next clock value; a hold below the current time stops it where it is (never backwards).
function FxClock.advance(t: number, dt: number, hold: number?): number
	return math.min(t + dt, math.max(t, hold or math.huge))
end

-- Advances by dt seconds (a frame's real time) and returns the effect's time.
function FxClock.step(self: Clock, dt: number): number
	if not self.studio then
		self.t += dt
		return self.t
	end
	local hold = game:GetService("RunService"):IsStudio() and workspace:GetAttribute("FarmFxHold")
	local limit = if type(hold) == "number" then hold else nil
	self.t = FxClock.advance(self.t, dt, limit)
	local held = limit ~= nil and self.t >= limit
	if held ~= self.held then
		self.held = held
		for _, item in self.root:GetDescendants() do
			if item:IsA("ParticleEmitter") then
				item.TimeScale = if held then 0 else 1
			end
		end
	end
	self.root:SetAttribute("FxTime", self.t)
	return self.t
end

return FxClock
