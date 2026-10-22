---
name: start
description: Start working in a foreman project - show which Claude models the agents use, which judge CLIs (Codex, Antigravity) are installed and where, whether judges can be sandboxed, the project memory and the open tasks, then ask the user what to work on. Use when the user says "start" (or similar) in a foreman project.
---

# foreman start

1. Run this and show its output to the user exactly as printed, inside a code block:

   ```bash
   python3 -I "${CLAUDE_PLUGIN_ROOT}/bin/tasks.py" start
   ```

   If it says this is not a foreman project, offer `/foreman:init` and stop.

2. Under it, one line for each thing that needs attention, with how to fix it:
   - a judge marked ✗ not installed (install its CLI, or remove the seat from
     `.foreman/config.toml`); when none is installed, reviews fall back to a read-only Claude;
   - judges without an OS sandbox;
   - `MIND_MAP.md` missing, still the template, or over budget (`/foreman:mindmap`);
   - `tests.command` not set.

   Say nothing about the parts that are fine.

3. Ask the user what they want to work on. Do not pick or start a task yourself. If a task is
   active, offer to continue it from its next gate.
