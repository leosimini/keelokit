"""Dashboard state and page on a tiny project. Run: python3 -m unittest discover -s tests"""
import builtins
import contextlib
import errno
import html as html_lib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

DASHBOARD = Path(__file__).resolve().parents[1] / "skills/project-dashboard/scripts/dashboard.py"
DOCTOR = Path(__file__).resolve().parents[1] / "template/.keelokit/bin/doctor.py"

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


def esc(text: str) -> str:
    return html_lib.escape(text, quote=False)


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
        self.assertIn("Of 3 rules: 1 covered by what the repo already had · 1 dated exception ·", html)

    def one_of_each(self, lang: str) -> None:
        """A harness project where every count the page shows is 1."""
        self.write(".keelokit/answers.yml", "mode: harness\nproject_name: Legacy\n")
        self.write(".keelokit/harness/rules.toml", '[[rule]]\nid = "A"\n')
        self.write(".keelokit/rules.local.toml", '[[rule]]\nid = "A"\nenforced_by = ["ci:test"]\n')
        self.write(".keelokit/exceptions.toml", '[[exception]]\nrule = "A"\nreason = "r"\napprover = "Ana"\nexpires = "2026-12-31"\n')
        self.gates("intake", "adopt", "backlog", lang=lang)
        self.write("docs/context/gaps.md", "| Id | File | Missing | Owner | Question | Blocking |\n|---|---|---|---|---|---|\n"
                                           "| GAP-001 | domain.md | window | Owner | How long? | yes |\n")
        self.write("docs/context/environments.md", "| Environment | Purpose | URL |\n|---|---|---|\n| staging | main | s.shop.app |\n")
        self.write("docs/deploy.md", "# Deploy\n\n## staging\n- [x] Fly.io account\n")
        self.story("AUTH-001", 1)
        self.commit("chore: adopt")

    def test_CPY_6_a_count_of_one_reads_in_the_singular(self):
        for lang, singular, plural in (
                ("en", ["Of 1 rule: 1 covered by what the repo already had · 1 dated exception ·", "1 exception recorded",
                        "1 open question (1 blocking)", "1 story · 1 wave · 1 epic", "0 of 1 story done",
                        "1 of 1 step ready", "1 of 1 environment ready", "1 open question blocks progress."],
                 ["1 rules", "1 dated exceptions", "1 exceptions", "1 open questions", "1 stories", "1 waves", "1 epics",
                  "1 steps", "1 environments"]),
                ("es", ["De 1 regla: 1 cubierta por lo que el repo ya tenía · 1 excepción con fecha ·", "1 excepción registrada",
                        "1 pregunta abierta (1 bloquea)", "1 historia · 1 ola · 1 épica", "0 de 1 historia terminada",
                        "1 de 1 paso listo", "1 de 1 entorno listo", "Hay 1 pregunta abierta que bloquea el avance."],
                 ["1 reglas", "1 cubiertas", "1 excepciones", "1 preguntas", "1 bloquean", "1 historias", "1 olas",
                  "1 épicas", "1 pasos", "1 entornos"])):
            with self.subTest(lang=lang):
                self.one_of_each(lang)
                html = self.page("--lang", lang)
                for text in singular:
                    self.assertIn(esc(text), html)
                for text in plural:
                    self.assertNotIn(text, html)

    def doctor_speaks(self, lang: str) -> list[str]:
        """A project whose own doctor prints every kind of --brief line: a pending gate, a ready
        story, the profile, drift both ways (the repo shows `web`, the profile lists `mobile`) and
        errors. Returns what it printed."""
        (self.root / ".keelokit/bin").mkdir(parents=True, exist_ok=True)
        shutil.copy(DOCTOR, self.root / ".keelokit/bin/doctor.py")
        self.gates(lang=lang)
        self.context()
        self.write(".keelokit/profile.toml", 'kind = "web-product"\ntraits = ["mobile"]\n')
        self.write("apps/web/package.json", "{}\n")
        self.story("AUTH-001", 1)
        self.commit("chore: start")
        brief = [line for line in sh(self.root, "python3", ".keelokit/bin/doctor.py", "--brief").splitlines() if line.strip()]
        for kind in ("Keelokit: gate pending", "Next ready stories:", "Profile:", "Harness errors:"):
            self.assertTrue(any(line.startswith(kind) for line in brief), f"the fixture no longer prints {kind!r}: {brief}")
        self.assertEqual(sum(line.startswith("Profile drift:") for line in brief), 2, brief)
        return brief

    def test_I18N_1_a_spanish_page_says_nothing_in_the_doctor_s_english_outside_its_quoted_log(self):
        """The class: any of doctor.py's (English) output reaching the page's own prose. The only
        place it may appear is the health block's log, marked lang="en" under a caption that says so."""
        brief = self.doctor_speaks("es")
        html = self.page("--lang", "es")
        logs = re.findall(r'<(\w+)[^>]*\blang="en"[^>]*>(.*?)</\1>', html, re.S)
        self.assertEqual(len(logs), 1, "the doctor's output is quoted once, as a log marked lang=\"en\"")
        self.assertIn(html_lib.escape("\n".join(brief)), logs[0][1])
        self.assertIn(esc("Salida del doctor (doctor.py --brief), tal como la imprime, en inglés:"), html)
        prose = re.sub(r'<(\w+)[^>]*\blang="en"[^>]*>.*?</\1>', " ", html, flags=re.S)
        prose = html_lib.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<(script|style)\b.*?</\1>", " ", prose, flags=re.S)))
        words = " " + " ".join(re.findall(r"[A-Za-z']+", prose)) + " "
        for line in brief:  # names (`web`) and paths ((apps/web)) are the same in any language
            for part in re.split(r"`[^`]*`|\([^)]*\)|:", line):
                run = re.findall(r"[A-Za-z']+", part)
                for i in range(len(run) - 2):
                    with self.subTest(line=line, words=run[i:i + 3]):
                        self.assertNotIn(" " + " ".join(run[i:i + 3]) + " ", words)
        drift = [w["text"] for w in self.state()["waiting"] if "perfil" in w["text"]]
        self.assertEqual(drift, ["El perfil del proyecto quedó desactualizado: el repo tiene `web` (apps/web) "
                                 "y el perfil no lo lista"])

    def test_I18N_1_an_english_page_words_the_drift_it_read(self):
        self.doctor_speaks("en")
        self.assertIn("The project's profile is out of date: the repo shows `web` (apps/web) but the profile "
                      "doesn't list it", [w["text"] for w in self.state()["waiting"]])
        self.assertEqual(self.state()["drift"], [{"trait": "web", "seen": "apps/web"}, {"trait": "mobile", "seen": None}])

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


def load_dashboard():
    spec = importlib.util.spec_from_file_location("keelokit_dashboard_under_test", DASHBOARD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# COPY-1 for the dashboard's own copy (the I18N-1 idea: no "1 items"). A number followed by a word
# needs a singular, so it lives in a (one, other) pair rendered by plural(). Placeholders that are
# text, not numbers, may sit before a word, and so may a number before a word that doesn't agree
# with it ("up to {n} at once", "{inn} in scope").
TEXT_PLACEHOLDERS = {"name", "when", "new", "date"}
NOT_A_NOUN = {"a", "at", "de", "en", "in", "of", "out", "afuera"}
PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


class DashboardCopyTest(unittest.TestCase):
    """CPY-6: the page read "1 exceptions recorded" because every count was a flat template. The
    class: any count before a word, in any string of T, in either language."""

    def setUp(self):
        self.dashboard = load_dashboard()
        self.T = self.dashboard.T

    def test_CPY_6_both_languages_have_the_same_keys_shapes_and_placeholders(self):
        es, en = self.T["es"], self.T["en"]
        self.assertEqual(set(es), set(en))
        for key in es:
            with self.subTest(key=key):
                self.assertIs(type(es[key]), type(en[key]))
                self.assertIn(type(es[key]), (str, list, dict, tuple))
                if isinstance(es[key], dict):
                    self.assertEqual(set(es[key]), set(en[key]))
                if isinstance(es[key], tuple):
                    self.assertEqual((len(es[key]), len(en[key])), (2, 2), "a count is a (one, other) pair")
                    forms = [*es[key], *en[key]]
                    self.assertIn("n", PLACEHOLDER_RE.findall(forms[1]), "a pair counts {n}")
                    self.assertEqual(len({frozenset(PLACEHOLDER_RE.findall(f)) - {"n"} for f in forms}), 1)
                elif isinstance(es[key], str):
                    self.assertEqual(set(PLACEHOLDER_RE.findall(es[key])), set(PLACEHOLDER_RE.findall(en[key])))

    def test_CPY_6_no_count_sits_before_a_word_outside_a_pair(self):
        for lang, t in self.T.items():
            for key, value in t.items():
                if isinstance(value, tuple):
                    continue
                texts = value.values() if isinstance(value, dict) else value if isinstance(value, list) else [value]
                for m in (m for text in texts for m in re.finditer(r"\{(\w+)\}\s+([^\W\d_]+)", text)):
                    with self.subTest(lang=lang, key=key, text=m.group(0)):
                        self.assertTrue(m.group(1) in TEXT_PLACEHOLDERS or m.group(2).lower() in NOT_A_NOUN,
                                        f"{key}: a count before a word needs a singular; make it a (one, other) "
                                        "pair and render it with plural()")

    def test_CPY_6_pairs_render_through_plural_and_plain_strings_through_format(self):
        source = DASHBOARD.read_text()
        pairs = {k for k, v in self.T["en"].items() if isinstance(v, tuple)}
        formatted = set(re.findall(r't\["(\w+)"\]\.format\(', source))
        pluralised = set(re.findall(r'plural\(t, "(\w+)"', source))
        self.assertEqual(formatted & pairs, set(), "a pair has no .format(): render it with plural()")
        self.assertEqual(pluralised - pairs, set(), "plural() takes a (one, other) pair")
        self.assertEqual(pairs - pluralised, set(), "a pair nothing renders")

    def test_CPY_6_plural_picks_one_only_for_one(self):
        t = {"k": ("{n} rule of {x}", "{n} rules of {x}")}
        self.assertEqual([self.dashboard.plural(t, "k", n, x="A") for n in (0, 1, 2)],
                         ["0 rules of A", "1 rule of A", "2 rules of A"])


def load_doctor(path: Path):
    spec = importlib.util.spec_from_file_location(f"keelokit_doctor_{abs(hash(path))}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DashboardReadsTheDoctorTest(unittest.TestCase):
    """I18N-1: the dashboard spliced doctor.py's English drift clause into a Spanish sentence. It now
    reads each drift line back into (trait, what shows it) and words it through T; this holds both
    readers to one wording, for both copies of the doctor, and every line it can't read to a
    sentence with nothing of the doctor's in it."""

    PATHS = ["apps/web", "apps/my web (old)/x", "Dockerfile", "apps/a`b"]

    def setUp(self):
        self.dashboard = load_dashboard()

    def test_I18N_1_every_drift_line_the_doctor_prints_reads_back_into_trait_and_path(self):
        for copy in (DOCTOR, DOCTOR.parents[3] / ".keelokit/bin/doctor.py"):
            doctor = load_doctor(copy)
            for trait in sorted(doctor.TRAIT_EVIDENCE):
                for seen in [*self.PATHS, None]:
                    with self.subTest(copy=str(copy), trait=trait, seen=seen):
                        line = f"Profile drift: {doctor.drift_text(trait, seen)}"
                        self.assertEqual(self.dashboard.read_drift(line), {"trait": trait, "seen": seen})

    def test_I18N_1_a_drift_line_it_cannot_read_is_still_said_in_the_page_s_language(self):
        s = {"drift": [self.dashboard.read_drift("Profile drift: web is now spelled differently")]}
        self.assertEqual(s["drift"], [{"trait": None, "seen": None}])
        for lang in ("es", "en"):
            with self.subTest(lang=lang):
                self.assertEqual(self.dashboard.drift_sentence(s["drift"][0], self.dashboard.T[lang]),
                                 self.dashboard.T[lang]["wait_profile_drift"])


# Every filesystem primitive that writes. The source may write only through these (the structural
# case below), so failing each of them in turn covers every write the dashboard makes.
WRITERS = ("write_text", "write_bytes", "mkdir", "touch", "open", "rename", "replace", "symlink_to",
           "hardlink_to", "unlink", "rmdir", "chmod")


class DashboardIOContractTest(unittest.TestCase):
    """DX-2 (and NFR-3): the dashboard's I/O contract. A --root that isn't a folder (missing, a file,
    a symlink loop, the current folder deleted) is exit 2 and a line naming it, never a greenfield
    page; any write that fails (read-only checkout, a directory where the page goes, a file where
    its folder goes, no space) is exit 1 and a line naming the path and --out/--json, never a
    traceback. In both cases nothing is written."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.project = self.tmp / "shop"
        (self.project / ".keelokit").mkdir(parents=True)
        (self.project / ".keelokit/state.toml").write_text('[dashboard]\nlang = "en"\n')

    def run_cli(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(["python3", str(DASHBOARD), *args], cwd=cwd or self.tmp,
                              capture_output=True, text=True)

    def assert_clean_failure(self, r: subprocess.CompletedProcess, code: int, *named: str) -> None:
        self.assertEqual(r.returncode, code, r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertEqual(r.stdout, "")
        self.assertEqual(len(r.stderr.strip().splitlines()), 1, r.stderr)
        for text in named:
            self.assertIn(text, r.stderr)

    def test_DX_2_a_root_that_is_not_a_folder_is_an_error_not_a_greenfield_page(self):
        a_file = self.tmp / "notes.txt"
        a_file.write_text("x")
        loop = self.tmp / "loop"
        loop.symlink_to(loop)
        dangling = self.tmp / "dangling"
        dangling.symlink_to(self.tmp / "gone")
        for root in (self.tmp / "missing/xyz", a_file, loop, dangling):
            for mode in ([], ["--json"], ["--standalone"]):
                with self.subTest(root=root.name, mode=mode):
                    out = self.tmp / "dash.html"
                    r = self.run_cli("--root", str(root), "--out", str(out), *mode)
                    self.assert_clean_failure(r, 2, "no such project", root.name)
                    self.assertFalse(out.exists())
        # A real folder, even an empty one or reached through a symlink, is still a project.
        (self.tmp / "empty").mkdir()
        (self.tmp / "link").symlink_to(self.project)
        for root in (self.tmp / "empty", self.tmp / "link"):
            with self.subTest(root=root.name):
                r = self.run_cli("--root", str(root), "--out", str(self.tmp / f"{root.name}.html"))
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertTrue((self.tmp / f"{root.name}.html").exists())

    def test_DX_2_a_deleted_current_folder_without_root_is_an_error(self):
        gone = self.tmp / "gone"
        gone.mkdir()
        out = self.tmp / "dash.html"
        r = subprocess.run(["sh", "-c", 'cd "$1" && rmdir "$1" && exec python3 "$2" --out "$3"', "_",
                            str(gone), str(DASHBOARD), str(out)], capture_output=True, text=True)
        self.assert_clean_failure(r, 2, "no such project", "the current folder", "--root")
        self.assertFalse(out.exists())

    def test_NFR_3_a_write_the_filesystem_refuses_is_a_clean_error(self):
        # Real refusals the sandbox can make even as root.
        (self.project / "page.html").mkdir()
        blocked = self.tmp / "blocked"
        (blocked / ".keelokit").mkdir(parents=True)
        (blocked / ".keelokit/out").write_text("a file where the output folder goes")
        cases = {
            "a directory where the page goes": (["--root", str(self.project), "--out", str(self.project / "page.html")],
                                                "page.html"),
            "a file where the output folder goes": (["--root", str(blocked)], ".keelokit/out"),
            "a file where --out's folder goes": (["--root", str(self.project), "--out",
                                                  str(self.project / ".keelokit/state.toml/dash.html")], "state.toml"),
        }
        for name, (args, named) in cases.items():
            with self.subTest(name):
                self.assert_clean_failure(self.run_cli(*args), 1, named, "--out", "--json")

    @unittest.skipIf(os.geteuid() == 0, "root writes through permission bits; the fault-injection case covers it")
    def test_NFR_3_a_read_only_checkout_is_a_clean_error(self):
        self.project.chmod(0o555)
        (self.project / ".keelokit").chmod(0o555)
        self.addCleanup(self.project.chmod, 0o755)
        self.addCleanup((self.project / ".keelokit").chmod, 0o755)
        self.assert_clean_failure(self.run_cli("--root", str(self.project)), 1, ".keelokit/out", "--out")

    def test_NFR_3_every_write_fails_cleanly_whichever_one_the_filesystem_refuses(self):
        dashboard = load_dashboard()
        real = {name: getattr(Path, name) for name in WRITERS}

        def run(fail_at: int | None, err: int) -> tuple[int | str, str, list]:
            calls = []

            def wrap(name):
                def writer(path, *args, **kwargs):
                    mode = (args[0] if args else kwargs.get("mode", "r")) if name == "open" else "w"
                    if name == "mkdir" and kwargs.get("exist_ok") and Path(path).is_dir():
                        mode = "r"  # a folder already there: nothing is written
                    if isinstance(mode, str) and not set(mode) & set("wax+"):
                        return real[name](path, *args, **kwargs)
                    calls.append((name, str(path)))
                    if len(calls) - 1 == fail_at:
                        raise OSError(err, os.strerror(err), str(path))
                    return real[name](path, *args, **kwargs)
                return writer

            shutil.rmtree(self.project / ".keelokit/out", ignore_errors=True)
            stdout, stderr = io.StringIO(), io.StringIO()
            patches = [mock.patch.object(Path, name, wrap(name)) for name in WRITERS]
            patches += [mock.patch.object(builtins, "open", wrap("open")),
                        mock.patch.object(sys, "argv", ["dashboard.py", "--root", str(self.project)])]
            with contextlib.ExitStack() as stack:
                for p in patches:
                    stack.enter_context(p)
                stack.enter_context(contextlib.redirect_stdout(stdout))
                stack.enter_context(contextlib.redirect_stderr(stderr))
                try:
                    code = dashboard.main()
                except SystemExit as e:
                    code = e.code
                except BaseException as e:  # what a user would see as a traceback
                    code = f"raised {type(e).__name__}: {e}"
            return code, stderr.getvalue(), calls

        code, _, writes = run(None, 0)
        self.assertEqual(code, 0)
        self.assertGreaterEqual(len(writes), 3, writes)  # the folder, its .gitignore, the page
        for err in (errno.EROFS, errno.EACCES, errno.ENOSPC, errno.EISDIR):
            for n, (name, path) in enumerate(writes):
                with self.subTest(errno=errno.errorcode[err], write=f"{name} {path}"):
                    code, stderr, _ = run(n, err)
                    self.assertEqual(code, 1, stderr)
                    self.assertIn(Path(path).name, stderr)
                    self.assertIn(os.strerror(err), stderr)
                    self.assertIn("--out", stderr)

    def test_NFR_3_the_dashboard_writes_only_through_the_primitives_the_contract_fails(self):
        source = DASHBOARD.read_text()
        for pattern in (r"\bos\.(write|replace|rename|makedirs|mkdir|link|symlink|truncate)\b", r"\bshutil\.",
                        r"\btempfile\.", r"\.write\(", r"\bio\.open\b"):
            with self.subTest(pattern):
                self.assertIsNone(re.search(pattern, source),
                                  "a new way to write: add it to WRITERS in tests/test_dashboard.py")


if __name__ == "__main__":
    unittest.main()
