---
name: init
description: Set up or upgrade the current project for the cplugin workflow (config, MIND_MAP.md, CLAUDE.md block, .claude/bin launchers).
argument-hint: "[project name]"
disable-model-invocation: true
---

# cplugin init

Set up this project for the cplugin workflow. Safe to re-run: it only adds what
is missing, refreshes the cplugin block in CLAUDE.md and the launchers, and never
overwrites `.cplugin/config.toml` or `MIND_MAP.md`.

Project name: $ARGUMENTS (when empty, the directory name is used)

1. Run the setup script, adding `--name "<project name>"` when a name was given:

   ```bash
   python3 -I "${CLAUDE_PLUGIN_ROOT}/bin/tasks.py" init
   ```

   If it exits with an error, show it to the user and stop.

2. Summarize the report for the user: what was created, updated, left unchanged.

3. If the report warns that this is not a git repository, explain why cplugin needs
   git and ask the user whether to run `git init`. Do not run it without a yes.
   Explain any other WARNING line.

4. If `MIND_MAP.md` was just created, it is still the empty template. Offer to build
   it now with `/cplugin:mindmap`.

5. Tell the user the project memory loads automatically at the next session start,
   after `/clear`, and after every compaction.
