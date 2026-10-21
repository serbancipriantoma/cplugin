# cplugin

A Claude Code plugin for task-gated, multi-agent work on a codebase:

- **Two-level project memory.** `MIND_MAP.md` holds the big ideas and is loaded into
  context at every session start, after `/clear` and after every compaction.
  `mindmap/<module>.md` files hold the details and are read on demand.
- **Tasks.** Every code change goes through a `task.md` worked gate by gate, tests
  first: write the tests from the criteria, see them fail (Red), implement until they
  pass (Green). Hooks block code edits without an active task, checking several gates
  at once, and ending a turn with open gates.
- **Strict agent roles.** The main agent coordinates and never writes code or tests.
  For each step it starts `cplugin:tester` to write the tests from the criteria, then
  `cplugin:worker` to write the code. Hooks let each role write only what it owns, and
  files changed through Bash by the wrong role are caught and recorded in the task.
- **A live board.** Run `.claude/bin/board --watch` in a second terminal to see the active
  task, its current gate, and what the main agent, the worker and the tester are doing.
  `/cplugin:board` prints it once in the chat.
- **Judges from other providers.** `tasks plan-review` and `tasks impl-review` have Codex
  and Antigravity (or a read-only Claude when neither is installed) review the plan and
  the code. They never see the conversation, run read-only, and a tamper check voids any
  review during which the project changed. Their findings are quoted into the task for
  the main agent to triage.

The `tasks` CLI (`.claude/bin/tasks` in a project): `new`, `work`, `status`, `list`,
`pause`, `stop`, `done`, `config show|check`.

The design, its decisions and the milestone plan are in [SPEC.md](SPEC.md).

## Requirements

Python 3.11+ (stdlib only), git, macOS or Linux.

## Install

```bash
claude plugin marketplace add serbancipriantoma/cplugin
claude plugin install cplugin@cplugin-marketplace
```

Or, to try a local checkout without installing it:

```bash
claude --plugin-dir /path/to/cplugin
```

Then, in the project you want to manage (once):

```
/cplugin:init       set up .cplugin/, MIND_MAP.md, the CLAUDE.md block and .claude/bin/tasks
/cplugin:mindmap    build or refresh the project memory
```

After that there is nothing to start by hand: whenever Claude Code opens in the project, the
memory and the active task load on their own, and a short banner shows the agents' models and
which judge CLIs are installed. Say "start" (or `/cplugin:start`) for the full picture: where
everything is loaded from, the open tasks, what needs attention.

## Development

```bash
cd tests && python3 -m unittest
claude plugin validate .
```
