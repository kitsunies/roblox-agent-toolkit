-- Splice exported roots into a rojo-built place: lune run splice.luau <in.rbxl> <out.rbxl> <Service.Path=root.rbxm>...
-- Each model replaces the instance at its path (same name), so rojo syncback sees the farm Studio's version.
local fs = require("@lune/fs")
local process = require("@lune/process")
local roblox = require("@lune/roblox")

local args = process.args
local game = roblox.deserializePlace(fs.readFile(args[1]))
for i = 3, #args do
	local path, file = string.match(args[i], "^([^=]+)=(.+)$")
	assert(path, "expected Path=file.rbxm, got " .. args[i])
	local names = string.split(path, ".")
	local parent = game:GetService(names[1])
	for n = 2, #names - 1 do
		parent = assert(parent:FindFirstChild(names[n]), path .. ": missing " .. names[n])
	end
	local roots = roblox.deserializeModel(fs.readFile(file))
	assert(#roots == 1 and roots[1].Name == names[#names], file .. ": expected one root named " .. names[#names])
	local old = parent:FindFirstChild(names[#names])
	if old then
		old:Destroy()
	end
	roots[1].Parent = parent
end
fs.writeFile(args[2], roblox.serializePlace(game))
