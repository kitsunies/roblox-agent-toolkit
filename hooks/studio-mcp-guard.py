#!/usr/bin/env python3
"""Optional Claude Code PreToolUse guard for Roblox Studio MCP tools (official roblox-studio and Chrrxs robloxstudio).

- Refuses `.Source =` writes inside execute_luau / run_code / eval_*_runtime: script source goes through the bridge's
  script edit tools (official multi_edit, Chrrxs set_script_source / edit_script_lines) and is read back.
- Asks before irreversible or outward tools (uploads, Open Cloud, manage_*, feedback), before save_place on a Studio
  that is not a farm instance (ids in the farm state files named by STUDIO_FARM_STATES, colon-separated globs,
  default build/studio-farm/state.json under the working directory) and before any unknown Studio tool.
- Known reads and in-Studio mutations pass silently.
The read / mutation / irreversible split (unknown counts as irreversible) follows the idea of Roqer's tool policy;
the code is original. Self-check: python3 hooks/studio-mcp-guard.py --self-check
"""
import glob
import json
import os
import re
import sys

READ = set("""get_console_output get_roblox_skill get_studio_state inspect_instance list_plugin_actions list_roblox_skills
list_roblox_studios screen_capture script_grep script_read script_search search_asset search_game_tree video_capture
wait_job_finished http_get breakpoints capture_device_matrix capture_micro_profiler capture_screenshot
capture_script_profiler capture_video export_rbxm get_asset_details get_asset_thumbnail get_attributes
get_connected_instances get_device_simulator_state get_instance_properties get_memory_breakdown get_place_info
get_project_structure get_request_status get_roblox_docs get_roblox_skills get_runtime_logs get_scene_analysis
get_script_source get_simulation_state grep_scripts preview_asset search_assets search_objects selection""".split())
MUTATE = set("""execute_luau run_code eval_server_runtime eval_client_runtime multi_edit insert_asset start_stop_play
user_keyboard_input user_mouse_input character_navigation auto_setup_avatar segment_mesh open_plugin create_skill
edit_skill subagent store_image generate_animation generate_avatar generate_material generate_mesh generate_procedural_model
generate_scene generate_texture delete_script_lines edit_script_lines insert_script_lines set_script_source
find_and_replace_in_scripts generate_model import_rbxm set_properties set_device_simulator set_network_profile
simulate_keyboard_input simulate_mouse_input solo_playtest multiplayer_playtest reset_simulation_state""".split())
IRREVERSIBLE = {"upload_asset", "upload_image", "open_cloud_invoke", "submit_feedback"}
CODE_TOOLS = {"execute_luau", "run_code", "eval_server_runtime", "eval_client_runtime"}
SOURCE_WRITE = re.compile(r"""\.Source\s*=(?!=)|\[\s*["']Source["']\s*\]\s*=(?!=)""")
STUDIO_SERVER = re.compile(r"roblox|studio", re.I)
FARM_STATES = tuple(os.environ.get("STUDIO_FARM_STATES", "build/studio-farm/state.json").split(":"))


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def farm_ids(patterns=FARM_STATES):
    ids = set()
    for path in (hit for pattern in patterns for hit in glob.glob(os.path.expanduser(pattern))):
        try:
            ids |= {r.get("id") for r in json.load(open(path))["instances"].values() if r.get("id")}
        except (OSError, ValueError, KeyError, AttributeError):
            pass
    return ids


def decide(tool_name, tool_input, farm=farm_ids):
    """(decision, reason) for one call; decision None lets it through."""
    parts = tool_name.split("__")
    if len(parts) < 3 or parts[0] != "mcp" or not STUDIO_SERVER.search(parts[1]):
        return None, ""
    tool = parts[-1]
    if tool in CODE_TOOLS and any(SOURCE_WRITE.search(text) for text in strings(tool_input)):
        return "deny", (f"{tool} sets a script's .Source: write source with the bridge's script edit tool (official "
                        "multi_edit, Chrrxs set_script_source or edit_script_lines), then read it back")
    if tool in IRREVERSIBLE or tool.startswith("manage_") or tool.startswith("publish"):
        return "ask", f"{tool} is irreversible or leaves Studio (uploads, Open Cloud, experience settings)"
    if tool == "save_place":
        studio = (tool_input or {}).get("studio_id")
        if studio and studio in farm():
            return None, ""
        return "ask", "save_place on a Studio that is not a farm instance writes the user's place"
    if tool in READ or tool in MUTATE:
        return None, ""
    return "ask", f"unknown Studio MCP tool {tool}: not in the guard's risk table"


def self_check():
    official, chrrxs = "mcp__roblox-studio__", "mcp__robloxstudio__"
    farm = lambda: {"farm-1"}  # noqa: E731
    assert decide(official + "execute_luau", {"code": 'script.Source = "x"'}, farm)[0] == "deny"
    assert decide(chrrxs + "eval_client_runtime", {"code": 'm["Source"] = s'}, farm)[0] == "deny"
    assert decide(official + "execute_luau", {"code": 'return m.Source == "" or #m.Source'}, farm)[0] is None
    assert decide(official + "execute_luau", {"code": "return 1"}, farm)[0] is None
    assert decide(chrrxs + "set_script_source", {"source": "x.Source = 1"}, farm)[0] is None
    for tool in ("upload_asset", "open_cloud_invoke", "manage_experience", "manage_instance", "upload_image"):
        assert decide(chrrxs + tool, {}, farm)[0] == "ask", tool
    assert decide(official + "save_place", {"studio_id": "farm-1"}, farm)[0] is None
    assert decide(official + "save_place", {"studio_id": "main"}, farm)[0] == "ask"
    assert decide(official + "brand_new_tool", {}, farm)[0] == "ask"
    assert decide(official + "list_roblox_studios", {}, farm)[0] is None
    assert decide("mcp__figma__use_figma", {"code": "a.Source = 1"}, farm)[0] is None
    assert decide("Bash", {"command": "x.Source = 1"}, farm)[0] is None
    print("PASS: studio-mcp-guard")


def main():
    if sys.argv[1:] == ["--self-check"]:
        self_check()
        return 0
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0
    decision, reason = decide(event.get("tool_name", ""), event.get("tool_input") or {})
    if decision:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": decision,
                                                 "permissionDecisionReason": reason}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
