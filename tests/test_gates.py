import unittest

import helpers  # noqa: F401  (puts the plugin on sys.path)

from cplugin import gates

TASK = """# 001 — feature — x

> - [ ] quoted, not a gate

## 1. Design
- [x] Read the detail files: combat.md §Damage
- [ ] The request in my own words:

## 3. Work Plan
<!--
- [ ] example inside a comment
-->
<!-- - [ ] one-line comment -->
### Step 1: damage
```
- [ ] inside a fence
```
  - [ ] Tests (tester): damage range
* [X] Red: 3 failing
"""


class GatesTest(unittest.TestCase):
    def test_parse_skips_comments_fences_and_quotes(self):
        parsed = gates.parse(TASK)
        self.assertEqual([(g.checked, g.text) for g in parsed], [
            (True, "Read the detail files: combat.md §Damage"),
            (False, "The request in my own words:"),
            (False, "Tests (tester): damage range"),
            (True, "Red: 3 failing"),
        ])
        self.assertEqual(parsed[2].section, "3. Work Plan › Step 1: damage")
        self.assertEqual(parsed[2].line, 18)

    def test_first_open_and_progress(self):
        parsed = gates.parse(TASK)
        self.assertEqual(gates.first_open(parsed).text, "The request in my own words:")
        self.assertEqual(gates.progress(parsed), (2, 4))
        self.assertIsNone(gates.first_open([g for g in parsed if g.checked]))

    def test_checked_count(self):
        self.assertEqual(gates.checked_count("- [x] a\n- [ ] b\n  * [X] c"), 2)

    def test_bare_checks(self):
        old = "- [ ] Red: tests fail\n- [ ] Green:\n- [x] Done already"
        new = "- [x] Red: tests fail\n- [x] Green: 4 passing\n- [x] Done already"
        self.assertEqual(gates.bare_checks(old, new), ["Red: tests fail"])
