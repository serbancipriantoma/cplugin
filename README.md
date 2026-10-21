# cplugin

A Claude Code plugin for task-gated, multi-agent work on a codebase:

- **Two-level project memory.** `MIND_MAP.md` holds the big ideas and is loaded into
  context at every session start, after `/clear` and after every compaction.
  `mindmap/<module>.md` files hold the details and are read on demand.
- **Tasks** (coming next): every code change goes through a `task.md` worked gate by gate.
- **Strict agent roles** (planned): a coordinating main agent, a worker that writes code,
  a tester that writes tests from the requirement, and judges from other providers.

The design is in [SPEC.md](SPEC.md) (Romanian).

## Requirements

Python 3.11+ (stdlib only), git, macOS or Linux.

## Try it locally

```bash
claude --plugin-dir /path/to/cplugin
```

Then, in the project you want to manage:

```
/cplugin:init       set up .cplugin/, MIND_MAP.md, the CLAUDE.md block and .claude/bin/tasks
/cplugin:mindmap    build or refresh the project memory
```

To install it permanently from this folder:

```bash
claude plugin marketplace add /path/to/cplugin
claude plugin install cplugin@cplugin-marketplace
```

## Development

```bash
cd tests && python3 -m unittest
claude plugin validate .
```
