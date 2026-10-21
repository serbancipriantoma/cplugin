<!-- cplugin:begin — managed by /cplugin:init; edits inside this block are overwritten -->
## cplugin workflow

This project uses the cplugin workflow.

- **Project memory.** `MIND_MAP.md` holds the big ideas and is loaded at session
  start. Each module has a detail file, `mindmap/<module>.md`, linked from its
  node. Read the detail file before working on a module. After changing
  behaviour, update the owning section of that file in place; change
  `MIND_MAP.md` only when the big ideas change.
- **Build or refresh the map** with `/cplugin:mindmap`.
- **Configuration** lives in `.cplugin/config.toml`.
<!-- cplugin:end -->
