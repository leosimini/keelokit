"""Dashboard state and page on a tiny project. Run: python3 -m unittest discover -s tests"""
import json
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

DASHBOARD = Path(__file__).resolve().parents[1] / "skills/project-dashboard/scripts/dashboard.py"

STORY = """\
+++
id = "{id}"
epic = "{epic}"
title = "{title}"
wave = {wave}
depends_on = [{deps}]
touches = ["apps/api/src/{id}/"]
dimensions = ["api"]
+++
{body}
"""


def sh(cwd: Path, *cmd: str) -> str:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True).stdout


class DashboardTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        sh(self.root, "git", "init", "-q", "-b", "main")
        sh(self.root, "git", "config", "user.email", "t@example.com")
        sh(self.root, "git", "config", "user.name", "T")

    def tearDown(self):
        shutil.rmtree(self.root)

    def write(self, rel: str, text: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text))

    def gates(self, *names: str, lang: str = "en") -> None:
        lines = ["[gates]", *(f'{n} = "2026-09-20"' for n in names), "", "[dashboard]", f'lang = "{lang}"']
        self.write(".keelokit/state.toml", "\n".join(lines) + "\n")

    def context(self, gaps: str = "") -> None:
        for f in ("product", "domain", "constraints", "environments"):
            self.write(f"docs/context/{f}.md", f"# {f}\n")
        self.write("docs/context/gaps.md",
                   "| Id | File | Missing | Owner | Question | Blocking |\n|---|---|---|---|---|---|\n" + gaps)

    def story(self, sid: str, wave: int, deps: str = "", body: str = "") -> None:
        self.write(f"backlog/stories/{sid}-x.md",
                   STORY.format(id=sid, epic=sid.split("-")[0], title=f"t {sid}", wave=wave, deps=deps, body=body))

    def commit(self, message: str) -> None:
        sh(self.root, "git", "add", "-A")
        sh(self.root, "git", "commit", "-qm", message, "--allow-empty")

    def state(self) -> dict:
        return json.loads(sh(self.root, "python3", str(DASHBOARD), "--root", str(self.root), "--json"))

    def page(self, *args: str) -> str:
        out = sh(self.root, "python3", str(DASHBOARD), "--root", str(self.root), *args).strip()
        return Path(out).read_text()

    def test_new_project_starts_at_intake(self):
        self.gates()
        s = self.state()
        self.assertEqual(s["layout"], "project")
        self.assertEqual([(x["id"], x["status"]) for x in s["stages"]],
                         [("intake", "current"), ("product", "todo"), ("stack", "todo"),
                          ("skeleton", "todo"), ("backlog", "todo")])
        self.assertEqual(s["next"]["command"], "/keelokit:project-new")

    def test_gate_with_its_output_waits_for_review(self):
        self.gates("intake")
        self.context()
        self.write("docs/prd.md", "# Shop — PRD\n\n## Success metrics\n| Metric | Target |\n|---|---|\n| Orders | 10 |\n")
        s = self.state()
        self.assertEqual(s["name"], "Shop")
        self.assertEqual(s["stages"][1]["status"], "review")
        self.assertEqual(s["next"]["anchor"], "stage-product")
        self.assertEqual(s["waiting"][0], {"text": 'Approve "Product (PRD)"', "anchor": "stage-product",
                                           "ask": 'I approve the "Product (PRD)" stage.', "act": "Approve"})

    def test_story_status_from_trailers_dependencies_and_gaps(self):
        self.gates("intake", "product", "stack", "skeleton", "backlog")
        self.context("| GAP-001 | domain.md | window | Owner | How long? | yes |\n")
        self.story("AUTH-001", 1)
        self.story("AUTH-002", 2, '"AUTH-001"')
        self.story("SHOP-001", 1, body="Needs [GAP-001].")
        self.story("SHOP-002", 2, '"SHOP-001"')
        self.commit("chore: skeleton")
        self.commit("feat: sign up\n\nStory: AUTH-001")
        s = self.state()
        status = {x["id"]: x["status"] for x in s["stories"]}
        self.assertEqual(status, {"AUTH-001": "done", "AUTH-002": "ready", "SHOP-001": "gap", "SHOP-002": "blocked"})
        self.assertIn("GAP-001", s["waiting"][0]["text"])
        self.assertEqual(s["next"]["title"], "Answer the blocking questions")
        self.context("| GAP-001 | domain.md | window | Owner | How long? | no |\n")
        s = self.state()
        self.assertEqual({x["id"]: x["status"] for x in s["stories"]}["SHOP-001"], "gap")
        self.assertEqual(s["next"]["command"], "/keelokit:build-story AUTH-002")

    def test_INT_1_without_main_nothing_counts_as_done(self):
        """INV-005: with neither main nor origin/main (a PR's shallow CI checkout, a detached HEAD)
        the dashboard must not take HEAD's own `Story:` trailers for done work."""
        self.gates("intake", "product", "stack", "skeleton", "backlog")
        self.context()
        self.story("AUTH-001", 1)
        self.commit("chore: skeleton")
        sh(self.root, "git", "checkout", "-q", "--detach")
        sh(self.root, "git", "branch", "-q", "-D", "main")
        self.commit("feat: sign up\n\nStory: AUTH-001")
        s = self.state()
        self.assertEqual(s["done"], [])
        self.assertEqual({x["id"]: x["status"] for x in s["stories"]}, {"AUTH-001": "ready"})
        self.assertEqual([e for e in s["history"] if e["kind"] == "story"], [])
        self.assertIn("main", " ".join(w["text"] for w in s["waiting"]))
        self.assertTrue(any("origin/main" in w["text"] for w in s["waiting"]))
        self.gates("intake", "product", "stack", "skeleton", "backlog", lang="es")
        self.assertTrue(any("origin/main" in w["text"] for w in self.state()["waiting"]))
        sh(self.root, "git", "branch", "-q", "main", "HEAD")
        s = self.state()
        self.assertEqual(s["done"], ["AUTH-001"])
        self.assertFalse(any("origin/main" in w["text"] for w in s["waiting"]))

    def test_adopted_repo_uses_the_adopt_gates(self):
        self.write(".keelokit/answers.yml", "mode: harness\nproject_name: Legacy\n")
        self.gates("intake")
        self.context()
        self.write(".keelokit/exceptions.toml", "")
        s = self.state()
        self.assertEqual(s["layout"], "harness")
        self.assertEqual([x["id"] for x in s["stages"]], ["intake", "adopt", "backlog"])
        self.assertEqual(s["stages"][1]["status"], "review")
        self.assertEqual(s["next"]["command"], None)

    def test_run_decisions_and_automatic_approvals(self):
        self.gates("intake")
        self.context()
        self.assertIn({"text": "Choose the run mode and how stories are built", "anchor": "decisions"}, self.state()["waiting"])
        self.write(".keelokit/state.toml", """\
            [gates]
            intake = "2026-09-20 auto"

            [run]
            mode = "auto"
            build = "parallel"
            parallel = 3
            decided = "2026-09-20"
            """)
        self.write("docs/prd.md", "# Shop — PRD\n")
        s = self.state()
        self.assertEqual(s["run"]["mode"], "auto")
        self.assertEqual((s["stages"][0]["date"], s["stages"][0]["auto"]), ("2026-09-20", True))
        self.assertNotIn("decisions", [w["anchor"] for w in s["waiting"]])
        html = self.page()
        self.assertIn("Approved automatically on 2026-09-20", html)
        self.assertIn("In parallel · up to 3 at once", html)
        # Only the stage waiting for the user is open.
        self.assertIn('<details class="stage review" id="stage-product" open>', html)
        self.assertIn('<details class="stage done" id="stage-intake">', html)

    def test_bug_bash_history_and_the_stories_it_fed(self):
        self.gates("intake", "product", "stack", "skeleton", "backlog")
        self.context()
        self.story("AUTH-001", 1)
        self.write("backlog/stories/AUTH-002-x.md",
                   STORY.format(id="AUTH-002", epic="AUTH", title="undo", wave=2, deps="", body="")
                   .replace('dimensions = ["api"]\n+++', 'dimensions = ["api"]\norigin = "bugbash:2026-09-26 UX-3"\n+++'))
        self.write("docs/bugbash/2026-09-26/report.md", """\
            # Bug bash

            ## Scope
            sha 3f9c2ab

            | Id | Lens | Severity | Title | Status | Fix commit | Check added |
            |---|---|---|---|---|---|---|
            | INT-1 | integrity | P0 | Two bookings | fixed | 8a1b2c3 | race() test |
            | UX-3 | ux | P2 | No undo | story AUTH-002 | — | — |
            | CPY-1 | copy | P1 | Promises SMS | pending decision | — | — |

            ## Pending decisions
            - CPY-1: change the text or add SMS.
            """)
        self.commit("chore: skeleton")
        self.commit("feat: a\n\nStory: AUTH-001")
        s = self.state()
        bb = s["bugbashes"][0]
        self.assertEqual((bb["date"], bb["sha"], bb["stories"]), ("2026-09-26", "3f9c2ab", ["AUTH-002"]))
        self.assertEqual([f["severity"] for f in bb["findings"]], ["P0", "P2", "P1"])
        self.assertIn("bb-2026-09-26", [w["anchor"] for w in s["waiting"]])
        self.assertEqual([e["kind"] for e in s["history"][:2]], ["story", "bugbash"])
        html = self.page()
        self.assertIn('id="bugbash" open', html)
        self.assertIn('data-ask="/keelokit:build-story AUTH-002"', html)
        self.assertIn("New product (greenfield)", html)
        self.assertIn('id="ask-send"', html)

    def test_environments_security_and_harness_notice(self):
        self.gates("intake", "product", "stack", "skeleton")
        self.context()
        self.write("docs/context/environments.md", "| Environment | Purpose | URL |\n|---|---|---|\n| staging | every green main | staging.shop.app |\n")
        self.write("docs/deploy.md", "# Deploy\n\n## staging\nTry things here.\n- [x] Fly.io account\n- [ ] Logged in\n\n## production\n- [ ] Domain\n")
        self.write(".keelokit/answers.yml", "_commit: v0.0.1\nmode: project\nproject_name: Shop\n")
        self.write("docs/security/2026-10-01/report.md", "| Id | Area | Severity | Title | Status | Fix | Check |\n|---|---|---|---|---|---|---|\n| SEC-1 | logs | P1 | Emails in logs | pending decision | — | — |\n")
        s = self.state()
        self.assertEqual(s["name"], "Shop")
        envs = {e["name"]: e for e in s["environments"]}
        self.assertEqual([x["done"] for x in envs["staging"]["steps"]], [True, False])
        self.assertEqual((envs["staging"]["url"], envs["staging"]["purpose"]), ("staging.shop.app", "every green main"))
        self.assertEqual(len(envs["production"]["steps"]), 1)
        anchors = [w["anchor"] for w in s["waiting"]]
        self.assertIn("sec-2026-10-01", anchors)
        self.assertIn({"text": f"Upgrade the harness: v0.0.1 → v{s['plugin_version']}", "anchor": "decisions",
                       "ask": "/keelokit:harness-upgrade", "act": "Upgrade the harness"}, s["waiting"])
        html = self.page()
        self.assertIn('id="environments"', html)
        self.assertIn("1 of 2 steps ready", html)
        self.assertIn('id="security" open', html)

    def test_brownfield_shows_what_was_found(self):
        self.write(".keelokit/answers.yml", "mode: harness\nproject_name: Legacy\n_commit: v0.7.0\n")
        self.write(".keelokit/profile.toml", 'kind = "web-product"\ntraits = ["ui", "web", "database", "hosted"]\n\n[detected]\nstack = ["Next.js 14", "Prisma"]\nci = ["GitHub Actions: test"]\n')
        self.write(".keelokit/harness/rules.toml", '[[rule]]\nid = "A"\n\n[[rule]]\nid = "B"\n\n[[rule]]\nid = "C"\n')
        self.write(".keelokit/rules.local.toml", '[[rule]]\nid = "A"\nenforced_by = ["ci:test"]\n')
        self.write(".keelokit/exceptions.toml", '[[exception]]\nrule = "B"\nreason = "no e2e yet"\napprover = "Ana"\nexpires = "2026-12-31"\n')
        self.gates("intake")
        self.context()
        s = self.state()
        self.assertEqual(s["layout"], "harness")
        self.assertEqual((s["mapping"]["house"], s["mapping"]["mapped"], len(s["mapping"]["exceptions"])), (3, 1, 1))
        html = self.page()
        self.assertIn("What we found", html)
        self.assertIn("Next.js 14", html)
        self.assertIn("Existing repository (brownfield)", html)
        self.assertIn("Of 3 rules: 1 covered by what the repo already had · 1 dated exceptions", html)

    def test_credit_defaults_and_levels(self):
        self.gates("intake")
        self.context()
        self.write(".keelokit/answers.yml", "mode: project\nproject_name: Shop\n")
        self.assertEqual(self.state()["credit"], "off")  # generated before the credit existed
        self.write("README.md", "# Shop\n\n<!-- keelokit:credit -->\n[![Built with Keelokit](x.svg)](https://keelokit.com)\n<!-- /keelokit:credit -->\n")
        self.assertEqual(self.state()["credit"], "visible")
        html = self.page()
        self.assertIn("<strong>Keelokit credit</strong>: visible", html)
        self.assertIn("Switch to quiet", html)
        self.write(".keelokit/answers.yml", "mode: project\nproject_name: Shop\ncredit: \"off\"\n")
        self.assertEqual(self.state()["credit"], "off")
        self.write(".keelokit/answers.yml", "mode: harness\nproject_name: Legacy\n")
        self.write("README.md", "# Legacy\n")  # an adopted repo keeps its own README
        self.assertEqual(self.state()["credit"], "off")

    def test_profile_hides_what_does_not_apply(self):
        self.gates("intake", "adopt")
        self.context()
        self.write(".keelokit/answers.yml", "mode: harness\nproject_name: Tool\n")
        self.write(".keelokit/profile.toml", 'kind = "plugin"\ntraits = ["developer-facing"]\n')
        self.write("docs/context/environments.md", "| Environment | Purpose | URL |\n|---|---|---|\n| local | dev | — |\n")
        html = self.page()
        self.assertIn("What the project is", html)
        self.assertIn("Plugin", html)
        self.assertIn("for developers", html)
        self.assertNotIn('id="environments"', html)  # nothing to host
        self.write(".keelokit/profile.toml", 'kind = "unknown"\ntraits = []\n')
        self.assertIn("decisions", [w["anchor"] for w in self.state()["waiting"] if "Diagnose" in w["text"]])

    def test_page_for_the_artifact_tool_escapes_documents(self):
        self.gates("intake", lang="es")
        self.context()
        self.write("docs/prd.md", "# Shop — PRD\n\n<script>alert(1)</script> **in**\n")
        html = self.page()
        self.assertFalse(html.lstrip().startswith("<!doctype"))
        self.assertTrue(html.startswith("<title>Tablero de Shop</title>"))
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt; <strong>in</strong>", html)
        self.assertIn('id="stage-product"', html)
        self.assertEqual((self.root / ".keelokit/out/.gitignore").read_text(), "*\n")

    def test_standalone_page_and_github_links(self):
        self.gates()
        self.context()
        sh(self.root, "git", "remote", "add", "origin", "git@github.com:acme/shop.git")
        html = self.page("--standalone")
        self.assertTrue(html.startswith("<!doctype html>"))
        self.assertIn('href="https://github.com/acme/shop/blob/main/docs/context/gaps.md"', html)


if __name__ == "__main__":
    unittest.main()
