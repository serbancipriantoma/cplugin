# foreman

A Claude Code plugin for task-gated, multi-agent work on a codebase:

- **Two-level project memory.** `MIND_MAP.md` holds the big ideas and is loaded into
  context at every session start, after `/clear` and after every compaction.
  `mindmap/<module>.md` files hold the details and are read on demand.
- **Tasks.** Every code change goes through a `task.md` worked gate by gate, tests
  first: write the tests from the criteria, see them fail (Red), implement until they
  pass (Green). Hooks block code edits without an active task, checking several gates
  at once, and ending a turn with open gates.
- **Strict agent roles.** The main agent coordinates and never writes code or tests.
  For each step it starts `foreman:tester` to write the tests from the criteria, then
  `foreman:worker` to write the code. Hooks let each role write only what it owns, and
  files changed through Bash by the wrong role are caught and recorded in the task.
- **A live board.** Run `.claude/bin/board --watch` in a second terminal to see the active
  task, its current gate, and what the main agent, the worker and the tester are doing.
  `/foreman:board` prints it once in the chat.
- **A status line.** Under the prompt: the model and effort, the context window, the five-hour
  rate limit, the session's weighted tokens (sub-agents included) and its cost; below it, in a
  foreman project, the active task, its gate and the sub-agents working now. `/foreman:init`
  sets it in the project's `.claude/settings.local.json` unless the project already has one.
- **A locker.** `locker/`, which git never sees, is where you hand Claude an image, a mockup
  or a PDF, and where Claude leaves exports for you. What has to ship (the image on a page) is
  copied into the project's own folders; the locker keeps the original.
- **Judges from other providers.** `tasks plan-review` and `tasks impl-review` have Codex
  and Antigravity (or a read-only Claude when neither is installed) review the plan and
  the code. They never see the conversation, run read-only, and a tamper check voids any
  review during which the project changed. Their findings are quoted into the task for
  the main agent to triage.

- **Freehand.** `/foreman:freehand` suspends the rules while you drive; only you can turn it
  on. It ends with `tasks work <N>` or `tasks freehand off`, and what changed meanwhile is
  logged in `.foreman/freehand.md`.
- **Sandbox.** `.claude/bin/sandbox` starts Claude Code without permission prompts inside
  `sandbox-exec` (macOS) or bubblewrap (Linux): it can write only in the project (not
  `.git`) and Claude's own state. Where that containment is not possible, it refuses to start.

The `tasks` CLI (`.claude/bin/tasks` in a project): `start`, `new`, `work`, `status`, `list`,
`pause`, `stop`, `done`, `plan-review`, `impl-review`, `freehand off`, `config show|check`.

The design, its decisions and the milestone plan are in [SPEC.md](SPEC.md).

## Requirements

Python 3.11+ (stdlib only), git, macOS or Linux. On Linux, bubblewrap for the sandbox and the
judges' containment: see [docs/linux.md](docs/linux.md).

## Install

```bash
claude plugin marketplace add serbancipriantoma/foreman
claude plugin install foreman@foreman-marketplace
```

Or, to try a local checkout without installing it:

```bash
claude --plugin-dir /path/to/foreman
```

Then, in the project you want to manage (once):

```
/foreman:init       set up .foreman/, MIND_MAP.md, the CLAUDE.md block and .claude/bin/tasks
/foreman:mindmap    build or refresh the project memory
```

`/foreman:init` ends with the same overview as "start" (below), so you see the agents and judges
right away, without restarting the session.

After that there is nothing to start by hand: whenever Claude Code opens in the project, the
memory and the active task load on their own, and a short banner shows the agents' models and
which judge CLIs are installed. Say "start" (or `/foreman:start`) for the full picture: where
everything is loaded from, the open tasks, what needs attention.

## Development

```bash
cd tests && python3 -m unittest
claude plugin validate .
```
