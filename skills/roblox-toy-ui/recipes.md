# Toy UI recipes (Luau)

Client-side snippets. Adapt names to the project; verify every screen in Studio.

## Contents
1. Helpers: stroke, gradient, corner
2. Extruded label
3. Glass streak gradient
4. Toy button (rim, lip, face, streak)
5. Fit scale and the 44 px check
6. Safe area against the top-left buttons
7. Press spring and window open/close
8. Colour themes

## 1. Helpers

```luau
local function stroke(parent: Instance, color: Color3, thickness: number, mode: Enum.ApplyStrokeMode?)
	local s = Instance.new("UIStroke")
	s.Color = color
	s.Thickness = thickness
	s.ApplyStrokeMode = mode or Enum.ApplyStrokeMode.Contextual
	s.LineJoinMode = Enum.LineJoinMode.Round
	s.Parent = parent
	return s
end

local function gradient(parent: Instance, color: ColorSequence, rotation: number?)
	local g = Instance.new("UIGradient")
	g.Color = color
	g.Rotation = rotation or 90 -- 90 = top to bottom
	g.Parent = parent
	return g
end

local function corner(parent: Instance, px: number)
	local c = Instance.new("UICorner")
	c.CornerRadius = UDim.new(0, px)
	c.Parent = parent
end

local function plate(parent: Instance, size: UDim2, position: UDim2, z: number): Frame
	local f = Instance.new("Frame")
	f.Size, f.Position, f.ZIndex = size, position, z
	f.BackgroundColor3 = Color3.new(1, 1, 1) -- white so the UIGradient shows its true colours
	f.BorderSizePixel = 0
	f.Parent = parent
	return f
end
```

## 2. Extruded label

```luau
local FONT = Font.fromEnum(Enum.Font.FredokaOne)

local function extrudedLabel(parent: Instance, text: string, textSize: number, ink: Color3, z: number)
	local function layer(name: string, color: Color3, dy: number, zi: number)
		local l = Instance.new("TextLabel")
		l.Name = name
		l.BackgroundTransparency = 1
		l.Size = UDim2.fromScale(1, 1)
		l.Position = UDim2.fromOffset(0, dy)
		l.FontFace = FONT
		l.Text = text
		l.TextSize = textSize
		l.TextColor3 = color
		l.ZIndex = zi
		l.Parent = parent
		stroke(l, ink, textSize >= 40 and 4 or 3)
		return l
	end
	layer("Shadow", ink, 1, z) -- the drop copy, 2 px below the label
	return layer("Label", Color3.new(1, 1, 1), -1, z + 1)
end
```

## 3. Glass streak

A transparency gradient that is fully transparent except for one thin band. Keypoints must have increasing times and a sequence holds at most 20 points, so keep to four bands or fewer.

```luau
local function streakGradient(frame: Frame, from: number, to: number, alpha: number, rotation: number)
	local e = 0.001
	local g = Instance.new("UIGradient")
	g.Rotation = rotation
	g.Transparency = NumberSequence.new({
		NumberSequenceKeypoint.new(0, 1),
		NumberSequenceKeypoint.new(from, 1),
		NumberSequenceKeypoint.new(from + e, alpha),
		NumberSequenceKeypoint.new(to, alpha),
		NumberSequenceKeypoint.new(to + e, 1),
		NumberSequenceKeypoint.new(1, 1),
	})
	g.Parent = frame
end
```

## 4. Toy button

`theme` is `{ face: ColorSequence, lip: ColorSequence, rim: Color3, ink: Color3 }` (section 8).

```luau
local function toyButton(parent: Instance, theme, size: Vector2, text: string): (ImageButton, UIScale)
	local h = size.Y
	local lip = if h >= 80 then 6 else 4

	local button = Instance.new("ImageButton")
	button.Size = UDim2.fromOffset(size.X, h)
	button.AnchorPoint = Vector2.new(0.5, 0.5) -- scale springs from the centre
	button.BackgroundColor3 = theme.rim
	button.AutoButtonColor = false
	button.Parent = parent
	corner(button, 6)

	-- Lip: twice its visible height, half hidden under the face.
	local lipFrame = plate(button, UDim2.new(1, -4, 0, lip * 2), UDim2.new(0, 2, 1, -(lip * 2 + 2)), 1)
	gradient(lipFrame, theme.lip)
	corner(lipFrame, 4)

	local face = plate(button, UDim2.new(1, -4, 1, -(lip + 4)), UDim2.fromOffset(2, 2), 2)
	face.ClipsDescendants = true
	gradient(face, theme.face)
	corner(face, 4)

	local glow = plate(face, UDim2.new(1, 0, 0, 2), UDim2.new(0, 0, 1, -2), 4)
	glow.BackgroundTransparency = 0.6

	local streak = plate(face, UDim2.fromScale(1, 1), UDim2.new(), 3)
	streakGradient(streak, 0.42, 0.5, 0.8, 60) -- section 3; vary per button

	extrudedLabel(face, text, math.floor(h * 0.5), theme.ink, 5) -- section 2

	local scale = Instance.new("UIScale")
	scale.Parent = button
	return button, scale
end
```

## 5. Fit scale and the 44 px check

```luau
local REF = Vector2.new(1050, 620)
local MIN_SCALE, MAX_SCALE = 0.52, 1.18
local MIN_TARGET = 44

local function fitScale(viewport: Vector2): number
	return math.clamp(math.min(viewport.X / REF.X, viewport.Y / REF.Y), MIN_SCALE, MAX_SCALE)
end

-- One UIScale per root, rebound when the viewport changes.
local function bindFit(root: GuiObject): UIScale
	local camera = workspace.CurrentCamera
	local s = Instance.new("UIScale")
	s.Parent = root
	local function apply() s.Scale = fitScale(camera.ViewportSize) end
	camera:GetPropertyChangedSignal("ViewportSize"):Connect(apply)
	apply()
	return s
end

-- Run against the smallest supported viewport, e.g. Vector2.new(844, 390).
local function auditTargets(root: Instance, viewport: Vector2): { string }
	local k, small = fitScale(viewport), {}
	for _, d in root:GetDescendants() do
		if d:IsA("GuiButton") then
			local onScreen = math.min(d.Size.X.Offset, d.Size.Y.Offset) * k
			if onScreen < MIN_TARGET then
				table.insert(small, string.format("%s %.0f px", d:GetFullName(), onScreen))
			end
		end
	end
	return small
end
```

The audit reads offsets, so it matches the offset-only rule. A button sized by scale needs its `AbsoluteSize` read in Studio at the emulated device instead.

## 6. Safe area

```luau
local GuiService = game:GetService("GuiService")

local gui = Instance.new("ScreenGui")
gui.ResetOnSpawn = false
gui.ScreenInsets = Enum.ScreenInsets.CoreUISafeInsets -- clears the Roblox top-left buttons
gui.ZIndexBehavior = Enum.ZIndexBehavior.Sibling

-- A bar that shares the top row starts where the free topbar area starts.
local function placeTopBar(bar: GuiObject)
	local inset = GuiService.TopbarInset
	bar.Position = UDim2.fromOffset(inset.Min.X, inset.Min.Y)
	bar.Size = UDim2.fromOffset(inset.Width, inset.Height)
end
local function bindTopBar(bar: GuiObject)
	placeTopBar(bar)
	GuiService:GetPropertyChangedSignal("TopbarInset"):Connect(function() placeTopBar(bar) end)
end
```

## 7. Springs

```luau
local TweenService = game:GetService("TweenService")
local PRESS = TweenInfo.new(0.05, Enum.EasingStyle.Quad, Enum.EasingDirection.Out)
local RELEASE = TweenInfo.new(0.12, Enum.EasingStyle.Back, Enum.EasingDirection.Out)
local OPEN = TweenInfo.new(0.32, Enum.EasingStyle.Back, Enum.EasingDirection.Out)
local CLOSE = TweenInfo.new(0.16, Enum.EasingStyle.Quad, Enum.EasingDirection.In)

local function bindPress(button: GuiButton, scale: UIScale, hover: number?)
	local current: Tween?
	local function to(value: number, info: TweenInfo)
		if current then current:Cancel() end
		local tween = TweenService:Create(scale, info, { Scale = value })
		current = tween
		tween:Play()
	end
	local pressed = false
	button.InputBegan:Connect(function(input)
		local t = input.UserInputType
		if t == Enum.UserInputType.MouseButton1 or t == Enum.UserInputType.Touch then
			pressed = true
			to(0.92, PRESS)
		elseif t == Enum.UserInputType.MouseMovement and not pressed then
			to(hover or 1.05, PRESS)
		end
	end)
	button.InputEnded:Connect(function(input)
		local t = input.UserInputType
		if t == Enum.UserInputType.MouseButton1 or t == Enum.UserInputType.Touch
			or t == Enum.UserInputType.MouseMovement then
			pressed = false
			to(1, RELEASE)
		end
	end)
end

-- Window: the fit scale and the animation factor multiply into the root's single UIScale.
local function windowMotion(root: GuiObject, fit: () -> number)
	local scale = root:FindFirstChildOfClass("UIScale")
	if not scale then
		scale = Instance.new("UIScale")
		scale.Parent = root
	end
	local factor = Instance.new("NumberValue")
	factor.Value = 1
	factor.Changed:Connect(function(v) scale.Scale = fit() * v end)

	local function open()
		root.Visible = true
		factor.Value = 0.86
		TweenService:Create(factor, OPEN, { Value = 1 }):Play()
	end
	local function close()
		local t = TweenService:Create(factor, CLOSE, { Value = 0.88 })
		t.Completed:Once(function(state)
			if state == Enum.PlaybackState.Completed then root.Visible = false end
		end)
		t:Play()
	end
	return open, close
end
```

## 8. Colour themes

Build each theme from one base colour so the palette stays in one place. `shade(c, k)` darkens toward black; the ink is the base at about 12 percent brightness, which keeps the hue.

```luau
local function shade(c: Color3, k: number): Color3
	local h, s, v = c:ToHSV()
	return Color3.fromHSV(h, math.min(1, s * 1.1), v * k)
end

local function theme(base: Color3)
	local h, s, v = base:ToHSV()
	local top = Color3.fromHSV(h, s * 0.55, math.min(1, v * 1.15))
	return {
		face = ColorSequence.new(top, base),
		lip = ColorSequence.new(shade(base, 0.55), shade(base, 0.38)),
		rim = shade(base, 0.2),
		ink = shade(base, 0.12),
	}
end

-- Meanings: confirm/currency green, destroy red, navigation blue, reward yellow, premium purple, done grey.
local THEMES = {
	confirm = theme(Color3.fromRGB(88, 214, 52)),
	destroy = theme(Color3.fromRGB(236, 40, 64)),
	nav = theme(Color3.fromRGB(46, 156, 250)),
	reward = theme(Color3.fromRGB(255, 204, 54)),
	premium = theme(Color3.fromRGB(160, 70, 240)),
	done = theme(Color3.fromRGB(176, 186, 200)),
}
```
