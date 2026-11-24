# roblox-agent-toolkit

Tools and skills for AI agents that drive Roblox Studio. This repo holds the logic and the know-how only. Studio is
reached through two existing MCP servers, called only through their tool APIs:

- the official Roblox Studio MCP server (`list_roblox_studios`, `execute_luau`, `screen_capture`, `start_stop_play`, ...)
- [Chrrxs robloxstudio-mcp](https://www.npmjs.com/package/@chrrxs/robloxstudio-mcp) 3.5.0 (`export_rbxm` for harvest; multiplayer tests, runtime logs and the profiler in the skills)

Contents:

| Path | What |
| --- | --- |
| `tools/studio_farm.py` | The Studio farm: throwaway Studio instances on a Windows host over SSH (open, probe, capture, close) |
| `tools/farm_probe.py`, `tools/console_log.py`, `tools/probes/ui-audit.luau` | The probe job, its console gate and the UI audit |
| `tools/harvest.py`, `tools/splice.luau` | Bring work done in a farm Studio back into a Rojo project |
| `tools/measure.py` | Judge captured effect frames (tone), particle and beam textures, and reference clips |
| `luau/FxClock.luau` | Drop-in effect clock that lets `probe --moments` hold an effect at exact times |
| `skills/` | Ten agent skills for building, feel, VFX, UI, design and Studio operation |
| `hooks/studio-mcp-guard.py` | Optional PreToolUse hook that guards Studio MCP calls |

## Prerequisites

- A Windows host with Roblox Studio, OpenSSH server and key auth, and a logged-in desktop session (farm Studios run
  on that desktop, parked off screen).
- The official Studio MCP server, startable as a stdio command (`studio_mcp` in the config).
- Chrrxs robloxstudio-mcp 3.5.0 and its Studio plugin on the host (harvest only). The plugin talks to the bridge on
  port 58741, and only one plugin can hold port 58741 per Studio: do not install another plugin that uses it.
- On the machine running the tools: Python 3.11+, `ssh` and `scp`; Pillow 10.1+ for `probe` and `measure`
  (ffmpeg optional, for `measure clip` on a video);
  [Rojo](https://rojo.space) 7.5+ for `probe --project` and harvest, plus [Lune](https://lune-org.github.io/lune/)
  for harvest (`rokit.toml` pins both). `reap` reads `/proc`, so it needs Linux.

## Config

```sh
cp farm.example.toml farm.toml   # then set host and studio_mcp
```

The tools read `farm.toml` from the working directory, or the file named by `STUDIO_FARM_CONFIG`. Every setting is
described in `farm.example.toml`; unknown keys are an error. `farm.toml` is git-ignored.

## Commands

Run from your game's project directory (paths below assume the toolkit sits at `../roblox-agent-toolkit`).

```sh
T=../roblox-agent-toolkit/tools

# Open a built place in a new farm Studio, then close it (only instances the farm opened can be closed).
python3 $T/studio_farm.py open --place build/Game.rbxl --tag smoke-1
python3 $T/studio_farm.py close smoke-1

# Every Studio on the host, farm ones annotated; close farm Studios whose owner process has exited.
python3 $T/studio_farm.py list
python3 $T/studio_farm.py reap

# Build the Rojo project, play it, run a server probe, click a button, capture two sizes, close.
python3 $T/studio_farm.py probe --project . --script probes/shop.luau --click "Shop" --size 844x390 --size 1920x1080

# Wait for a client attribute verdict set by your probe (FAIL... or a timeout fails the run).
python3 $T/studio_farm.py probe --project . --script probes/quest.luau --expect "QuestProbe=^PASS"

# Effect moments: hold the newest FxClock effect at each time and capture it, plus a labelled sheet.
python3 $T/studio_farm.py probe --project . --script probes/explosion.luau --moments 0.05,0.2,0.5 --hide-gui --size 1280x720

# UI audit of the screen after the clicks, at phone and desktop sizes; fail on any finding.
python3 $T/studio_farm.py probe --project . --click "Inventory" --size 844x390 --size 1920x1080 --audit --fail-on-findings

# Harvest: open a farm Studio on the project, edit it through MCP, then apply only what changed.
python3 $T/harvest.py open --tag fx-pass
python3 $T/harvest.py apply --tag fx-pass

```

Probe scripts are plain Luau run with `execute_luau`; each starts with `local CONFIG = { tag = ..., phase = "run" }`
(see `tools/farm_probe.py` for the `frame` and `expect` phases). Captures land in `build/probes` as PNG plus a JSON
sidecar. For `--moments`, copy `luau/FxClock.luau` into your game and step effects through it.

## Measure

`tools/measure.py` judges effect captures, textures and reference clips. It prints JSON and exits 0 when clean, 1 when
it raises a flag, 2 on a usage error. Thresholds are named constants at the top of the file: those from
`skills/roblox-vfx-phasing/references/measured.md` say so, the rest give their reason.

```sh
# Captured moments: washed out (pale share over 40%), blown out (clipped white) or flat. --base is the same view
# without the effect, so only the pixels the effect changed are measured.
python3 $T/measure.py tone build/probes/explosion-1280x720-m*.png --base build/probes/empty-1280x720.png

# Textures: power-of-two and 1024 cap, real alpha or black-background additive, plus per kind: line brightness,
# tile seams, ring evenness, flipbook grid (2x2, 4x4, 8x8; found from clean cell borders) and wasted frames.
python3 $T/measure.py texture --kind flipbook assets/fx/fireball-4x4.png

# A reference clip (video through ffmpeg, skipped without it; or a frame directory with --fps): onset, flash,
# time to half and to gone after the flash, colours at each beat, tone at the flash and any second ignition.
python3 $T/measure.py clip refs/explosion.mp4
```

## Skills

Copy the folders under `skills/` into your agent's skills directory: `.claude/skills/` for Claude Code, or
`.agents/skills/` for harnesses that read that path. Each skill loads by its description.

| Skill | Use |
| --- | --- |
| roblox-studio-bridge | Operating Studio through MCP safely, playtests, captures, the farm and harvest |
| roblox-build-craft | Building from Parts, wedges and CSG with a toy look |
| roblox-reference-build | Building to match a reference image |
| roblox-camera-feel | Scripted fight and showcase cameras |
| roblox-game-feel | Hits, shake, hit-stop, knockback |
| roblox-vfx-phasing | Effects in warning, contact, peak and fade; measured VFX figures |
| roblox-toy-ui | Chunky toy-style ScreenGui, phone safe areas, touch targets |
| roblox-game-design | Core loop, FTUE, economy, retention |
| roblox-player-psychology | Rewards, streaks, pricing, odds, dark-pattern audit |
| roblox-publish-checklist | Release gates before publishing |

The optional hook: add `python3 /path/to/hooks/studio-mcp-guard.py` as a PreToolUse command hook. It refuses
`.Source =` writes through code tools and asks before uploads, Open Cloud calls, `save_place` outside a farm
instance and unknown Studio tools. Set `STUDIO_FARM_STATES` (colon-separated globs) if your farm state files are not
at `build/studio-farm/state.json` under the working directory.

## Tests

```sh
python3 -m unittest discover -s tests
```

None of them touch Studio; the harvest and build tests skip without Rojo and Lune.

## Credits

- `roblox-game-design`, `roblox-player-psychology` and `roblox-publish-checklist` come from
  [TabooHarmony/roblox-brain](https://github.com/TabooHarmony/roblox-brain) (MIT); each keeps its `LICENSE` and
  `SOURCE`. Skill names they mention that are not in this repo live there.
- Other skills credit their sources in a closing "Sources" line (roblox-brain under MIT, awesome-gamedev-agent-skills
  under Apache-2.0, and ideas only from other projects).
- The figures in `roblox-vfx-phasing/references/measured.md` restate numbers from the
  [Roqer](https://github.com/S4US/Roqer) project's VFX study (AGPL-3.0). No Roqer code or text is included.

## License

MIT. See `LICENSE`.
