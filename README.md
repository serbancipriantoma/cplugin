# cplugin

A Claude Code plugin for task-gated, multi-agent work on a codebase:

- **Two-level project memory.** `MIND_MAP.md` holds the big ideas and is loaded into
  context at every session start, after `/clear` and after every compaction.
  `mindmap/<module>.md` files hold the details and are read on demand.
- **Tasks.** Every code change goes through a `task.md` worked gate by gate, tests
  first: write the tests from the criteria, see them fail (Red), implement until they
  pass (Green). Hooks block code edits without an active task, checking several gates
  at once, and ending a turn with open gates.
- **Strict agent roles** (planned): a coordinating main agent, a worker that writes code,
  a tester that writes tests from the requirement, and judges from other providers.

The `tasks` CLI (`.claude/bin/tasks` in a project): `new`, `work`, `status`, `list`,
`pause`, `stop`, `done`.

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

Then, in the project you want to manage:

```
/cplugin:init       set up .cplugin/, MIND_MAP.md, the CLAUDE.md block and .claude/bin/tasks
/cplugin:mindmap    build or refresh the project memory
```

## Development

```bash
cd tests && python3 -m unittest
claude plugin validate .
```
