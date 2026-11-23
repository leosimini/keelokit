"""The routing of a change to the verify steps it needs (verify_tools.py plan). The guards that keep the map
honest: unknown goes up, --all is every step, a plan never shrinks when a file is added, every route names real
steps, and each file the template ships is classified the way it is written down here independently.
Run: python3 -m unittest discover -s tests"""
import runpy
import subprocess
import tomllib
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TOOLS = runpy.run_path(str(REPO / "template/.keelokit/bin/verify_tools.py"), run_name="tools")
ROUTING = tomllib.loads((REPO / "template/.keelokit/verify-routing.toml").read_text())
STEPS = set(TOOLS["STEPS"])


def plan(files, everything=False):
    always = ROUTING.get("always", [])
    routes = [([TOOLS["glob_re"](p) for p in r["paths"]], r["steps"]) for r in ROUTING["route"]]
    return TOOLS["plan_for"](files, (always, routes), everything)


def template_files():
    listed = subprocess.run(["git", "ls-files", "template"], cwd=REPO, capture_output=True, text=True, check=True).stdout.split()
    return [f[len("template/"):].removesuffix(".jinja") for f in listed]


class PlanGuardsTest(unittest.TestCase):
    def test_every_route_names_real_steps(self):
        for r in ROUTING["route"]:
            self.assertTrue(set(r["steps"]) <= STEPS | {"all"}, r)

    def test_all_is_every_step_and_any_plan_is_inside_it(self):
        self.assertEqual(plan(["docs/a.md"], everything=True)[0], ["all"])
        for f in template_files():
            steps, _ = plan([f])
            self.assertTrue(steps == ["all"] or set(steps) <= STEPS, (f, steps))

    def test_a_file_no_route_knows_runs_everything(self):
        steps, unknown = plan(["docs/a.md", "tools/mystery.xyz"])
        self.assertEqual((steps, unknown), (["all"], ["tools/mystery.xyz"]))

    def test_adding_a_file_never_removes_a_step(self):
        files = template_files()
        base = {"docs/guide.md"}
        for f in files[::7]:
            before, _ = plan(sorted(base))
            after, _ = plan(sorted(base | {f}))
            self.assertTrue(after == ["all"] or (before != ["all"] and set(before) <= set(after)), (f, before, after))

    def test_what_each_kind_of_file_must_get_written_independently_of_the_table(self):
        expect = {
            "docs/guide.md": ({"format"}, {"unit", "build", "e2e", "integration", "typecheck", "lint"}),
            "README.md": ({"format"}, {"unit", "build", "e2e"}),
            "backlog/stories/A-1-x.md": ({"format"}, {"unit"}),
            "apps/web/src/i18n/locales/es.json": ({"unit", "lint", "typecheck", "format"}, {"build", "e2e", "integration"}),
        }
        for f, (must, must_not) in expect.items():
            steps, _ = plan([f])
            self.assertNotEqual(steps, ["all"], f)
            self.assertTrue(must <= set(steps), (f, steps))
            self.assertFalse(must_not & set(steps), (f, steps))
        for f in ("apps/api/src/billing/charge.ts", "packages/shared/src/index.ts", "package.json", "pnpm-lock.yaml",
                  ".keelokit/harness/rules.toml", ".github/workflows/ci.yml.jinja", "scripts/verify.sh", ".githooks/pre-push",
                  "apps/web/e2e/home.spec.ts", "tsconfig.base.json"):
            self.assertEqual(plan([f])[0], ["all"], f)

    def test_every_file_the_template_ships_is_classified_or_runs_everything(self):
        """Not a place to add routes, a place to see what is unclassified: a new kind of file is `all` until
        someone decides, and this lists them so the decision is visible in review."""
        unknown = sorted({Path(f).suffix or Path(f).name for f in template_files() if plan([f])[1]})
        self.assertLessEqual(len(unknown), 40, unknown)

    def test_globs(self):
        g = TOOLS["glob_re"]
        self.assertTrue(g("**/*.md").match("a.md") and g("**/*.md").match("a/b/c.md"))
        self.assertTrue(g("docs/**").match("docs/a/b.md") and not g("docs/**").match("xdocs/a.md"))
        self.assertTrue(g("apps/*/src/**").match("apps/web/src/a/b.ts") and not g("apps/*/src/**").match("apps/web/x/src/a.ts"))
        self.assertFalse(g("*.md").match("docs/a.md"))


class CausesTest(unittest.TestCase):
    def test_builtin_causes_are_found_in_a_log(self):
        found = dict(TOOLS["causes_in"]("..\nFATAL ERROR: Reached heap limit Allocation failed - JavaScript heap out of memory\n"))
        self.assertIn("heap", found)
        self.assertNotIn("disk", found)
        self.assertIn("disk", dict(TOOLS["causes_in"]("write failed: ENOSPC: no space left on device")))
        self.assertEqual(TOOLS["causes_in"]("all green"), [])


if __name__ == "__main__":
    unittest.main()
