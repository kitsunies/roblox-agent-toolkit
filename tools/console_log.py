"""Console gate for a farm play session: read LogService:GetLogHistory() from the Server and Client DataModels, keep
Errors and Warnings, and tag each line with its source: `game` when it names a script of the place
(ServerScriptService, ReplicatedStorage, ReplicatedFirst, StarterPlayer, StarterGui, Players.<x>.Player*), else core,
plugin, studio or other. Any Error from a game script fails the run; warnings and other sources are INFO.
`accept` (console_accept in farm.toml) lists regexes for known noise, matched against "<side> <message>".
`report(bridge, studio_id)` prints the block and returns the failures.
"""
import json
import re

# Each DataModel keeps its own history; execute_luau runs there in its own VM, which still sees LogService.
LUAU = """
local HttpService = game:GetService("HttpService")
local out = {}
local history = game:GetService("LogService"):GetLogHistory()
for index, entry in history do
	if entry.messageType == Enum.MessageType.MessageError or entry.messageType == Enum.MessageType.MessageWarning then
		local message = entry.message
		-- An engine error ("Body is not a valid member of Frame") names no script; its "Stack Begin" ... "Stack End"
		-- Info lines that follow do, so they join the message (else such an error would read INFO).
		local nextEntry = history[index + 1]
		if nextEntry and nextEntry.message == "Stack Begin" then
			for at = index + 2, math.min(index + 12, #history) do
				local line = history[at].message
				if line == "Stack End" then
					break
				end
				message ..= " | " .. line
			end
		end
		table.insert(out, { error = entry.messageType == Enum.MessageType.MessageError, message = message })
	end
end
return "LOGS " .. HttpService:JSONEncode(out)
"""

GAME = re.compile(r"\b(ServerScriptService|ServerStorage|ReplicatedStorage|ReplicatedFirst|StarterPlayer|StarterGui"
                  r"|Players\.[^.\s]+\.(PlayerScripts|PlayerGui|Backpack)|Workspace)\.[\w.]+(:\d+|', Line \d+)")
CORE = re.compile(r"\b(CoreGui|CorePackages|RobloxGui|CoreScript|RobloxPlayerScripts)\b")
PLUGIN = re.compile(r"\b(Plugin|plugin|cloud_\d+|user_[\w.]+\.rbxmx?|builtin_)", re.I)
STUDIO = re.compile(r"(Studio|DataStore|HTTP 4\d\d|Roblox API services|asset|Asset|rbxassetid|Failed to load)")

def source(message):
    if GAME.search(message):
        return "game"
    for name, pattern in (("core", CORE), ("plugin", PLUGIN), ("studio", STUDIO)):
        if pattern.search(message):
            return name
    return "other"


def read(bridge, studio_id, sides=("Server", "Client")):
    """[{side, error, message, source}] for every Error and Warning line in each DataModel's history."""
    lines = []
    for side in sides:
        try:
            text = bridge.tool("execute_luau", studio_id=studio_id, datamodel_type=side, code=LUAU)
        except Exception as error:  # a stopped play has no Server or Client DataModel: say so, never pass silently
            lines.append({"side": side, "error": True, "message": f"console read failed: {error}", "source": "tool"})
            continue
        m = re.search(r"LOGS (\[.*\]|\{\})", text, re.S)
        if not m:
            lines.append({"side": side, "error": True, "message": f"console read: {text.strip()[:200]}", "source": "tool"})
            continue
        for entry in json.loads(m.group(1)) or []:
            message = entry.get("message", "")
            lines.append({"side": side, "error": bool(entry.get("error")), "message": message, "source": source(message)})
    return lines


def accepted(line, accept=()):
    text = f"{line['side']} {line['message']}"
    return next((f"matches {pattern!r}" for pattern in accept if re.search(pattern, text)), None)


def judge(lines, accept=()):
    """(text block, failures): an Error from a game script (or a failed read) fails unless accepted."""
    errors, warnings, failures = [], [], []
    seen = set()
    for line in lines:
        key = (line["side"], line["error"], line["message"])
        if key in seen:
            continue
        seen.add(key)
        reason = accepted(line, accept)
        row = f"  {line['side']:6} {line['source']:6} {line['message'][:300]}" + (f"  (ACCEPTED: {reason})" if reason else "")
        (errors if line["error"] else warnings).append(row)
        if line["error"] and line["source"] in ("game", "tool") and not reason:
            failures.append(f"console: {line['side']} {line['message'][:200]}")
    text = [f"console: {len(errors)} errors, {len(warnings)} warnings ({len(failures)} failing)"]
    if errors:
        text += ["Errors:"] + errors
    if warnings:
        text += ["Warnings (INFO):"] + warnings
    return "\n".join(text), failures


def report(bridge, studio_id, sides=("Server", "Client"), accept=()):
    text, failures = judge(read(bridge, studio_id, sides), accept)
    print(text, flush=True)
    return failures

