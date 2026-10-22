import unittest
from pathlib import Path

import helpers  # noqa: F401  (puts the plugin on sys.path)

from foreman import config, globs, roles

CFG = config.DEFAULTS


class GlobsTest(unittest.TestCase):
    def test_double_star(self):
        self.assertTrue(globs.matches("src/a/b.ts", ["src/**"]))
        self.assertTrue(globs.matches("test_x.py", ["**/test_*.py"]))
        self.assertTrue(globs.matches("pkg/sub/test_x.py", ["**/test_*.py"]))
        self.assertTrue(globs.matches("src/x.test.ts", ["**/*.test.*"]))
        self.assertTrue(globs.matches("anything/at/all.ts", ["**"]))
        self.assertFalse(globs.matches("srcx/a.ts", ["src/**"]))

    def test_single_star_stays_in_one_directory(self):
        self.assertTrue(globs.matches("src/a.ts", ["src/*"]))
        self.assertFalse(globs.matches("src/a/b.ts", ["src/*"]))
        self.assertFalse(globs.matches("a/test_x.py", ["test_*.py"]))


class RolesTest(unittest.TestCase):
    def test_role_of(self):
        self.assertEqual(roles.role_of({}), roles.MAIN)
        self.assertEqual(roles.role_of({"agent_type": "foreman:worker"}), roles.WORKER)
        self.assertEqual(roles.role_of({"agent_type": "foreman:tester"}), roles.TESTER)
        self.assertEqual(roles.role_of({"agent_type": "general-purpose"}), roles.OTHER)
        self.assertEqual(roles.role_of({"agent_type": "other-plugin:worker"}), roles.OTHER)

    def test_owner(self):
        nowhere = Path("/nonexistent")
        self.assertEqual(roles.owner("MIND_MAP.md", nowhere, CFG), roles.MAIN)
        self.assertEqual(roles.owner("mindmap/projects.md", nowhere, CFG), roles.MAIN)
        self.assertIsNone(roles.owner("README.md", nowhere, CFG))
        self.assertIsNone(roles.owner("assets/levels.json", nowhere, CFG))
        self.assertEqual(roles.owner("src/game.ts", nowhere, CFG), roles.WORKER)
        self.assertEqual(roles.owner("vite.config.ts", nowhere, CFG), roles.WORKER)
        self.assertEqual(roles.owner("tests/game.test.ts", nowhere, CFG), roles.TESTER)
        self.assertEqual(roles.owner("src/game.test.ts", nowhere, CFG), roles.TESTER)  # tests win
        self.assertEqual(roles.owner("src/__tests__/grid.tsx", nowhere, CFG), roles.TESTER)

    def test_nothing_in_the_locker_is_code(self):
        x = Path("/x")
        for rel in ("locker/report.html", "locker/drafts/hero.tsx", "locker/notes.py"):
            self.assertIsNone(roles.owner(rel, x, CFG), rel)
            for role in (roles.MAIN, roles.WORKER, roles.TESTER, roles.OTHER):
                self.assertIsNone(roles.write_violation(role, rel, x, CFG), (role, rel))
        self.assertEqual(roles.owner("lockers/a.ts", x, CFG), roles.WORKER)  # only the folder itself
        renamed = {**CFG, "locker": {"dir": "crate"}}
        self.assertIsNone(roles.owner("crate/a.ts", x, renamed))
        self.assertEqual(roles.owner("locker/a.ts", x, renamed), roles.WORKER)

    def test_locker_dir_must_be_one_plain_folder_name(self):
        for name in ("locker", "crate", "my_box-2", "box.v2"):
            self.assertEqual(config.locker_dir({"locker": {"dir": name}}), name)
        for name in ("", ".locker", "../up", "a/b", "mindmap", 3, None):
            self.assertIsNone(config.locker_dir({"locker": {"dir": name}}), name)
        self.assertIn(("ERROR", "locker.dir must be one folder name: letters, digits, _ . -, "
                                "not starting with a dot, not mindmap"),
                      config.check({**CFG, "locker": {"dir": "a/b"}}))

    def test_narrowed_worker_paths_leave_code_unassigned(self):
        cfg = {**CFG, "roles": {**CFG["roles"], "worker": {"paths": ["src/**"]}}}
        self.assertEqual(roles.owner("vite.config.ts", Path("/x"), cfg), roles.UNASSIGNED)
        reason = roles.write_violation(roles.WORKER, "vite.config.ts", Path("/x"), cfg)
        self.assertIn("matches neither", reason)

    def test_violations_name_the_owner(self):
        x = Path("/x")
        self.assertIsNone(roles.write_violation(roles.WORKER, "src/a.ts", x, CFG))
        self.assertIsNone(roles.write_violation(roles.TESTER, "tests/a.test.ts", x, CFG))
        self.assertIsNone(roles.write_violation(roles.MAIN, "MIND_MAP.md", x, CFG))
        self.assertIsNone(roles.write_violation(roles.WORKER, "README.md", x, CFG))
        self.assertIn("foreman:worker", roles.write_violation(roles.MAIN, "src/a.ts", x, CFG))
        self.assertIn("foreman:tester", roles.write_violation(roles.MAIN, "tests/a.test.ts", x, CFG))
        self.assertIn("may not change tests", roles.write_violation(roles.WORKER, "tests/a.test.ts", x, CFG))
        self.assertIn("may not change production code", roles.write_violation(roles.TESTER, "src/a.ts", x, CFG))
        self.assertIn("belongs to the main agent", roles.write_violation(roles.TESTER, "MIND_MAP.md", x, CFG))
        self.assertIn("only foreman:worker writes code", roles.write_violation(roles.OTHER, "src/a.ts", x, CFG))
