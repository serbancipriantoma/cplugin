# {{num}} — {{type}} — {{slug}}

> **Gate discipline.** One gate at a time: do the work, check the box, and append
> the outcome on the same line (`- [x] Red: 4 failing, all "damage not defined"`).
> Never check several gates in one edit and never replace a gate's text. When the
> plan changes, edit or add unchecked gates. Only the main agent checks gates.
> Lines inside comments, code blocks and quotes are not gates.

## Status
pending

## Request
{{request}}

## Context
{{context}}

## 1. Design
- [ ] Read the affected sections of the detail files listed in Context:
- [ ] The request in my own words:
- [ ] Done means (verifiable criteria):
- [ ] In scope:
- [ ] Out of scope:
- [ ] Wrote the Work Plan: one group per step, each with criteria, interface and how it is verified

## 2. Plan Review
- [ ] Run `.claude/bin/tasks plan-review {{n}}` and wait for it to finish
- [ ] Triage: every finding → accepted / parked / rejected, with the reason

## 3. Work Plan
<!--
Write one group per step, in this shape. Steps that cannot be tested
automatically (graphics, animation, feel) use the manual shape.

{{step_shape}}
-->

## 4. Implementation Review
- [ ] Run `.claude/bin/tasks impl-review {{n}}` and wait for it to finish
- [ ] Triage: every finding → accepted / parked / rejected, with the reason

## 5. Final Review
- [ ] All tests pass (command + count)
- [ ] No debug leftovers (temporary logs, commented-out code, focused or skipped tests)
- [ ] Updated the owning sections of the detail files in place; MIND_MAP.md only if the big ideas changed

## Parked
(what came up and is out of scope, with enough context for a future task)
