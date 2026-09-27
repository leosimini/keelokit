"""Dashboard state and page on a tiny project. Run: python3 -m unittest discover -s tests"""
import json
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

DASHBOARD = Path(__file__).resolve().parents[1] / "skills/dashboard/scripts/dashboard.py"

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
        self.assertEqual(s["next"]["command"], "/keelokit:kickstart")

    def test_gate_with_its_output_waits_for_review(self):
        self.gates("intake")
        self.context()
        self.write("docs/prd.md", "# Shop — PRD\n\n## Success metrics\n| Metric | Target |\n|---|---|\n| Orders | 10 |\n")
        s = self.state()
        self.assertEqual(s["name"], "Shop")
        self.assertEqual(s["stages"][1]["status"], "review")
        self.assertEqual(s["next"]["anchor"], "stage-product")
        self.assertIn({"text": 'Approve "Product (PRD)"', "anchor": "stage-product"}, s["waiting"])

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
        self.assertEqual(s["next"]["command"], "/keelokit:build AUTH-002")

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
