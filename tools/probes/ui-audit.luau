-- UI audit (studio_farm.py probe --audit runs it at each size in the Client DataModel): every visible TextLabel,
-- TextButton and TextBox on the enabled ScreenGuis, checked for
--   small     rendered text under 12 px (TextSize times the UIScale chain; scaled text from its TextBounds),
--   truncated TextFits false,
--   key       a button under 44 px on either side,
--   occluded  a visible key whose centre (of its clipped box) is covered: the topmost GuiObject there that draws
--             something or takes input (GetGuiObjectsAtPosition, after ZIndex and DisplayOrder) is neither the key
--             nor inside it (a key under another ScreenGui's bar passes the per-layer overlap check); a key
--             behind anything over half the screen (a modal, a full screen view) or scrolled out is not counted,
--   overlap   two visible text elements or keys of the same layer overlapping by more than 8 px both ways: text by
--             its rendered bounds, keys by their box, both clipped by ClipsDescendants ancestors; not one inside the
--             other, not inside the same key, not an extruded copy with the same text. A layer is the nearest
--             ancestor dim or panel over half the screen (a modal covers what is under it on purpose); text-less
--             transparent catch-all buttons (tap catchers, full screen skip keys) are left out.
--   offscreen a visible text or key cut by the screen edge by more than 8 px (fully off screen is left out: views
--             park there; so are the catch-all keys the overlap check leaves out),
--   clipped   a key wholly cut away by a ClipsDescendants ancestor that does not scroll,
--   scroll    a text or key past its ScrollingFrame's canvas by more than 2 px: no scroll position shows it.
-- Extruded text counts once (a copy named Shadow is skipped).
-- Returns one JSON line: { viewport, elements, counts, issues = { { kind, path, text, w, h, value } },
-- texts = { { text, path, key } } } (every visible string, for copy review).
local HttpService = game:GetService("HttpService")
local gui = game:GetService("Players").LocalPlayer:WaitForChild("PlayerGui")
local view = workspace.CurrentCamera.ViewportSize
local MIN_TEXT, MIN_KEY, OVERLAP = 12, 44, 8
-- AbsolutePosition starts below the top bar whatever the ScreenGui's insets: the screen spans -topBar to view.Y - topBar.
local topBar = game:GetService("GuiService"):GetGuiInset().Y

local function shown(item)
	local node = item
	while node and node ~= gui do
		if node:IsA("GuiObject") and not node.Visible then
			return false
		elseif node:IsA("LayerCollector") and not node.Enabled then
			return false
		end
		node = node.Parent
	end
	return true
end

local function scaleOf(item)
	local scale, node = 1, item.Parent
	while node and node ~= gui do
		local uiScale = node:FindFirstChildOfClass("UIScale")
		if uiScale then
			scale *= uiScale.Scale
		end
		node = node.Parent
	end
	return scale
end

local function plain(text)
	return (string.gsub(string.gsub(text, "<[^>]->", ""), "^%s*(.-)%s*$", "%1"))
end

local function path(item)
	return string.gsub(item:GetFullName(), "^.-PlayerGui%.", "")
end

local function onScreen(item)
	local p, s = item.AbsolutePosition, item.AbsoluteSize
	return s.X > 1 and s.Y > 1 and p.X < view.X and p.Y < view.Y and p.X + s.X > 0 and p.Y + s.Y > 0
end

local function keyOf(item)
	local node = item
	while node and node ~= gui do
		if node:IsA("GuiButton") then
			return node
		end
		node = node.Parent
	end
	return nil
end

local AREA = view.X * view.Y

-- The visible rect: the box clipped by every ClipsDescendants ancestor (a scrolled row under the menu bar is cut).
local function clipped(item, x0, y0, x1, y1)
	local node = item.Parent
	while node and node ~= gui do
		if node:IsA("GuiObject") and node.ClipsDescendants then
			local p, s = node.AbsolutePosition, node.AbsoluteSize
			x0, y0, x1, y1 = math.max(x0, p.X), math.max(y0, p.Y), math.min(x1, p.X + s.X), math.min(y1, p.Y + s.Y)
		end
		node = node.Parent
	end
	return x0, y0, x1, y1
end

-- Text by its rendered bounds inside the box (alignment aware; TextBounds is already in screen pixels, UIScale
-- included); keys and the rest by the box.
local function rectOf(item, textual)
	local p, s = item.AbsolutePosition, item.AbsoluteSize
	local x0, y0, x1, y1 = p.X, p.Y, p.X + s.X, p.Y + s.Y
	if textual and not item:IsA("GuiButton") then
		local w, h = math.min(s.X, item.TextBounds.X), math.min(s.Y, item.TextBounds.Y)
		local ax = if item.TextXAlignment == Enum.TextXAlignment.Left
			then 0
			elseif item.TextXAlignment == Enum.TextXAlignment.Right then 1
			else 0.5
		local ay = if item.TextYAlignment == Enum.TextYAlignment.Top
			then 0
			elseif item.TextYAlignment == Enum.TextYAlignment.Bottom then 1
			else 0.5
		x0, y0 = p.X + (s.X - w) * ax, p.Y + (s.Y - h) * ay
		x1, y1 = x0 + w, y0 + h
	end
	return clipped(item, x0, y0, x1, y1)
end

-- The layer: the nearest ancestor (or self) dim or panel over half the screen, else the ScreenGui.
local function layerOf(item, screen)
	local node = item.Parent
	while node and node ~= screen do
		if
			node:IsA("GuiObject")
			and node.BackgroundTransparency < 0.95
			and node.AbsoluteSize.X * node.AbsoluteSize.Y > AREA / 2
		then
			return node
		end
		node = node.Parent
	end
	return screen
end

local issues, rects, texts, keys, elements = {}, {}, {}, {}, 0
local counts = { small = 0, truncated = 0, key = 0, overlap = 0, occluded = 0, offscreen = 0, clipped = 0, scroll = 0 }
local function report(kind, item, value, text)
	counts[kind] += 1
	local s = item.AbsoluteSize
	table.insert(
		issues,
		{ kind = kind, path = path(item), text = text, w = math.floor(s.X), h = math.floor(s.Y), value = value }
	)
end

-- Past the canvas: the pixels of item outside its ScrollingFrame's canvas, which no scroll position reaches.
local function pastCanvas(item)
	local scroller = item:FindFirstAncestorWhichIsA("ScrollingFrame")
	local p, s = item.AbsolutePosition, item.AbsoluteSize
	if not scroller or s.X <= 1 or s.Y <= 1 then
		return 0
	end
	local origin, canvas = scroller.AbsolutePosition - scroller.CanvasPosition, scroller.AbsoluteCanvasSize
	return math.max(origin.X - p.X, origin.Y - p.Y, p.X + s.X - origin.X - canvas.X, p.Y + s.Y - origin.Y - canvas.Y)
end

for _, screen in gui:GetChildren() do
	if screen:IsA("ScreenGui") and screen.Enabled then
		for _, item in screen:GetDescendants() do
			local textual = item:IsA("TextLabel") or item:IsA("TextButton") or item:IsA("TextBox")
			if (textual or item:IsA("GuiButton")) and item.Name ~= "Shadow" and shown(item) then
				local text = if textual then plain(item.Text) else ""
				local key = item:IsA("GuiButton") and item.Active and item.Interactable ~= false
				local visibleText = text ~= "" and item.TextTransparency < 0.95
				local past = if visibleText or key then pastCanvas(item) else 0
				if past > 2 then
					report("scroll", item, `{math.floor(past)} px`, text)
				end
				if (visibleText or key) and onScreen(item) then
					elements += 1
					if visibleText then
						table.insert(texts, { text = text, path = path(item), key = keyOf(item) ~= nil })
						local lines = select(2, string.gsub(text, "\n", "")) + 1
						local height = if item.TextScaled
							then item.TextBounds.Y / lines
							else item.TextSize * scaleOf(item)
						if height < MIN_TEXT then
							report("small", item, math.floor(height * 10) / 10, text)
						end
						if not item.TextFits then
							report("truncated", item, false, text)
						end
					end
					local size = item.AbsoluteSize
					if key and (size.X < MIN_KEY or size.Y < MIN_KEY) and (size.X < view.X * 0.9) then
						report("key", item, `{math.floor(size.X)}x{math.floor(size.Y)}`, text)
					end
					local x0, y0, x1, y1 = rectOf(item, visibleText)
					local catchAll = key and text == "" and item.BackgroundTransparency >= 0.9
						or size.X * size.Y > AREA / 2
					local cut = math.max(-x0, -topBar - y0, x1 - view.X, y1 - view.Y + topBar)
					if cut > OVERLAP and not catchAll then
						report("offscreen", item, `{math.floor(cut)} px`, text)
					end
					if key and not catchAll then
						table.insert(keys, item)
					end
					if not catchAll and x1 > x0 and y1 > y0 then
						table.insert(rects, {
							item = item,
							layer = layerOf(item, screen),
							text = text,
							key = keyOf(item),
							box = { x0, y0, x1, y1 },
						})
					end
				end
			end
		end
	end
end

-- Overlaps within one ScreenGui.
for i = 1, #rects do
	local a = rects[i]
	for j = i + 1, #rects do
		local b = rects[j]
		if a.layer == b.layer and not (a.key and a.key == b.key) and not (a.text ~= "" and a.text == b.text) then
			local ia, ib = a.item, b.item
			if not (ia:IsAncestorOf(ib) or ib:IsAncestorOf(ia)) then
				local ra, rb = a.box, b.box
				local x = math.min(ra[3], rb[3]) - math.max(ra[1], rb[1])
				local y = math.min(ra[4], rb[4]) - math.max(ra[2], rb[2])
				if x > OVERLAP and y > OVERLAP then
					counts.overlap += 1
					table.insert(issues, {
						kind = "overlap",
						path = path(ia),
						other = path(ib),
						text = a.text,
						otherText = b.text,
						value = `{math.floor(x)}x{math.floor(y)}`,
					})
				end
			end
		end
	end
end

-- Occlusion: what the player would tap at each key's centre.
local GuiService = game:GetService("GuiService")
local inset = GuiService:GetGuiInset()
local function draws(object, x, y)
	if object:IsA("GuiButton") and object.Active then
		return true -- takes the tap even when clear
	elseif object.BackgroundTransparency < 0.95 then
		return true
	elseif (object:IsA("ImageLabel") or object:IsA("ImageButton")) and object.Image ~= "" then
		return object.ImageTransparency < 0.95
	elseif object:IsA("ViewportFrame") then
		return true
	elseif object:IsA("TextLabel") or object:IsA("TextButton") then
		if plain(object.Text) == "" or object.TextTransparency >= 0.95 then
			return false
		end
		local x0, y0, x1, y1 = rectOf(object, true)
		return x >= x0 and x <= x1 and y >= y0 and y <= y1
	end
	return false
end
local function under(x, y, key)
	-- GetGuiObjectsAtPosition reads screen pixels; AbsolutePosition under an inset ScreenGui sits below the top bar:
	-- try both frames and keep the one whose list holds the key.
	for _, dy in { 0, inset.Y } do
		local list = gui:GetGuiObjectsAtPosition(x, y + dy)
		if table.find(list, key) then
			local first = nil
			for _, object in list do
				if object == key or key:IsAncestorOf(object) then
					return first
				elseif shown(object) and draws(object, x, y) then
					local size = object.AbsoluteSize
					if size.X * size.Y > AREA / 2 then
						return nil -- behind a modal or a full screen view: covered on purpose
					end
					first = first or object
				end
			end
			return first
		end
	end
	return false -- the key itself is not hit at its centre (fully clipped or behind a sibling layer)
end
for _, key in keys do
	local p, s = key.AbsolutePosition, key.AbsoluteSize
	local x0, y0, x1, y1 = clipped(key, p.X, p.Y, p.X + s.X, p.Y + s.Y)
	local scroller = key:FindFirstAncestorWhichIsA("ScrollingFrame")
	if (x1 - x0 < 4 or y1 - y0 < 4) and scroller and scroller.ClipsDescendants then
		continue -- scrolled out of view
	elseif x1 - x0 < 4 or y1 - y0 < 4 then
		counts.clipped += 1
		table.insert(issues, { kind = "clipped", path = path(key), value = "0x0" })
	else
		local cover = under((x0 + x1) / 2, (y0 + y1) / 2, key)
		if cover ~= nil then
			counts.occluded += 1
			local text = key:IsA("TextButton") and plain(key.Text) or ""
			local caption = key:FindFirstChild("Caption", true)
			text = if text == "" and caption and caption:IsA("TextLabel") then caption.Text else text
			table.insert(issues, {
				kind = "occluded",
				path = path(key),
				text = text,
				other = if cover then path(cover) else "not hit",
				value = `{math.floor(x1 - x0)}x{math.floor(y1 - y0)}`,
			})
		end
	end
end

return "AUDIT "
	.. HttpService:JSONEncode({
		viewport = `{math.floor(view.X)}x{math.floor(view.Y)}`,
		elements = elements,
		counts = counts,
		issues = issues,
		texts = texts,
	})
