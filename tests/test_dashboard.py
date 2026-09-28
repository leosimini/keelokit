"""Dashboard state and page on a tiny project. Run: python3 -m unittest discover -s tests"""
import ast
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
import types
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


def dead_links(html: str) -> list[str]:
    """UX-1, the class: every in-page link (the next step, each waiting item, the stage strip, the
    decisions card, the sections' own links) must land on an element the same page renders."""
    ids = set(re.findall(r'\bid="([^"]+)"', html))
    return sorted({h for h in re.findall(r'\bhref="#([^"]*)"', html) if html_lib.unescape(h) not in ids})


def duplicate_ids(html: str) -> list[str]:
    """UI-2, the class: an id is one element. The page draws the same card in more than one place
    (a story in the backlog by wave, by epic and in a bug bash's history), and a repeated id sends
    every link and #hash to the first copy, hidden or not."""
    ids = re.findall(r'\bid="([^"]+)"', html)
    return sorted({i for i in ids if ids.count(i) > 1})


def build_buttons(html: str) -> list[tuple[str, list[str]]]:
    """Every button that starts /keelokit:build-story, as (its label, the arguments it sends)."""
    found = re.findall(r'data-ask="/keelokit:build-story([^"]*)">([^<]*)<', html)
    return [(html_lib.unescape(label), html_lib.unescape(args).split()) for args, label in found]


def vague_build_buttons(html: str) -> list[str]:
    """UX-2, the class: a button is tied to what its label names (a story, a wave), so it sends
    those stories by id. A bare count means "the first ready story and more of its wave" to
    build-story, which is another wave whenever an earlier one still has ready work."""
    return [label for label, args in build_buttons(html) if not args or any(a.isdigit() for a in args)]


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
        """The full report, which shows everything the repo says (most tests read it)."""
        out = sh(self.root, "python3", str(DASHBOARD), "--root", str(self.root), "--report", *args).strip()
        html = Path(out).read_text()
        self.assert_links_land(html)
        self.assertEqual(vague_build_buttons(html), [], "build buttons that don't name their stories")
        return html

    def ops(self, *args: str) -> str:
        """The operational dashboard, the page people work from."""
        out = sh(self.root, "python3", str(DASHBOARD), "--root", str(self.root), *args).strip()
        html = Path(out).read_text()
        self.assertEqual(duplicate_ids(html), [], "ids on more than one element")
        return html

    def assert_links_land(self, html: str) -> None:
        """UX-1 and UI-2: every page a test renders goes through here (see dead_links, duplicate_ids)."""
        self.assertEqual(dead_links(html), [], "in-page links with nothing to land on")
        self.assertEqual(duplicate_ids(html), [], "ids on more than one element")

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

    def test_UX_1_harness_errors_before_a_backlog_link_to_the_health_they_count(self):
        """A repo with no backlog yet whose doctor reports errors: the waiting item and the next step
        that count them must open the doctor's output, not a Build stage the page only renders once
        there are stories. Both layouts, with a gate still pending (the waiting item) and with every
        gate approved (the next step is then "fix the harness" itself)."""
        cases = (("harness", ("intake",)), ("harness", ("intake", "adopt", "backlog")),
                 ("project", ("intake", "product", "stack", "skeleton")),
                 ("project", ("intake", "product", "stack", "skeleton", "backlog")))
        for layout, gates in cases:
            with self.subTest(layout=layout, gates=gates):
                self.write(".keelokit/answers.yml", f"mode: {layout}\nproject_name: Legacy\n")
                (self.root / ".keelokit/bin").mkdir(parents=True, exist_ok=True)
                shutil.copy(DOCTOR, self.root / ".keelokit/bin/doctor.py")
                (self.root / ".keelokit/harness").mkdir(parents=True, exist_ok=True)
                shutil.copy(DOCTOR.parents[1] / "harness/rules.toml", self.root / ".keelokit/harness/rules.toml")
                self.gates(*gates)
                self.context()
                self.write(".keelokit/profile.toml", 'kind = "web-product"\ntraits = []\n')
                self.commit("chore: adopt")
                s = self.state()
                self.assertEqual(s["stories"], [])
                self.assertGreater(s["errors"], 0, s["doctor"])
                errors = [w for w in s["waiting"] if "harness error" in w["text"]]
                self.assertEqual(len(errors), 1, s["waiting"])
                anchors = {errors[0]["anchor"]}
                if s["pending"] is None:  # every gate approved: fixing the harness is the next step
                    self.assertEqual(s["next"]["command"], "/keelokit:check-health")
                    anchors.add(s["next"]["anchor"])
                self.assertEqual(len(anchors), 1, anchors)
                anchor = anchors.pop()
                html = self.page()  # asserts every in-page link lands
                self.assertIn(f'href="#{anchor}"', html)
                health = re.search(rf'id="{anchor}".*?</details>', html, re.S)
                self.assertIsNotNone(health)
                self.assertIn(html_lib.escape("\n".join(s["doctor"])), health[0])
                self.assertIn('data-ask="/keelokit:check-health"', health[0])
            self.assertEqual(s["pending"], None if gates[-1] == "backlog" else "backlog" if layout == "project" else "adopt")

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
        self.assertIn("Approved automatically on Sep 20, 2026", html)
        self.assertIn("In parallel · up to 3 at once", html)
        # Only the stage waiting for the user is open.
        self.assertIn('<details class="stage review" id="stage-product" open>', html)
        self.assertIn('<details class="stage done" id="stage-intake">', html)

    def test_UX_2_build_wave_button_names_the_stories_of_its_wave(self):
        """Two waves with ready work at once: each "Build wave N in parallel" button sends wave N's
        ready stories by id, not a count build-story would spend on the first ready wave."""
        self.gates("intake", "product", "stack", "skeleton", "backlog")
        self.context()
        self.story("AUTH-001", 1)
        self.story("AUTH-002", 1)
        self.story("SHOP-001", 2)
        self.story("SHOP-002", 2)
        self.story("SHOP-003", 2, '"AUTH-001"')
        self.story("CART-001", 3)
        self.commit("chore: skeleton")
        html = self.page()
        waves = {label: args for label, args in build_buttons(html) if "wave" in label}
        self.assertEqual(waves, {"Build wave 1 in parallel": ["AUTH-001", "AUTH-002"],
                                 "Build wave 2 in parallel": ["SHOP-001", "SHOP-002"]})
        # One ready story is no wave to build in parallel: wave 3 gets no button.
        self.assertNotIn("Build wave 3 in parallel", html)
        # The next step's hint names the same stories as the button of its wave.
        detail = self.state()["next"]["detail"]
        self.assertIn('"/keelokit:build-story AUTH-001 AUTH-002"', detail)
        self.assertNotRegex(detail, r"build-story \d")
        # The same in Spanish.
        self.gates("intake", "product", "stack", "skeleton", "backlog", lang="es")
        html = self.page()
        self.assertIn('data-ask="/keelokit:build-story SHOP-001 SHOP-002">Construir la ola 2 en paralelo<', html)
        self.assertIn("«/keelokit:build-story AUTH-001 AUTH-002»", self.state()["next"]["detail"])

    @staticmethod
    def story_list(text: str) -> list[str]:
        """Counts where the next step's hint should name stories."""
        return re.findall(r"build-story \d", text)

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
        self.assertNotIn('id="ask-send"', html, "the report is read-only")
        self.assertIn('id="ask-send"', self.ops(), "the dashboard can send requests to Claude")

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

    def docs_in(self, lang: str, variant: int = 0) -> None:
        """A PRD (the shape of prd-template.md), a bug bash report and a security report (the shape
        their skills write), in `lang`, each with the same content: 2 metrics, 1 thing in scope,
        2 out, the sha in the scope section (another sha before it) and one pending decision. A
        `**…:**` label in the scope that isn't In/Out, and whose name starts like one, has 3 bullets."""
        words = DOC_WORDS[lang]
        h = {k: v[variant % len(v)] if isinstance(v, tuple) else v for k, v in words.items()}
        self.write("docs/prd.md", f"""\
            # Shop — PRD

            {h['status']}: approved (2026-01-02) · Owner: Ana

            ## {h['problem']}
            Buyers can't pay online.

            ## {h['metrics']}
            | Metric | Target | By | How |
            |---|---|---|---|
            | Orders | 10 | 2026-12 | db |
            | Returns | 2% | 2026-12 | db |

            ## {h['scope']}
            **{h['integrations']}:**
            - Stripe
            - Mercado Pago
            - Post

            **{h['in']}:**
            - Checkout — for buyers

            **{h['out']}:**
            - Loyalty — later
            - Gift cards — later

            ## {h['risks']}
            None yet.
            """)
        for folder, day in (("bugbash", "2026-09-26"), ("security", "2026-10-01")):
            self.write(f"docs/{folder}/{day}/report.md", f"""\
                # Report {day}

                ## {h['summary']}
                Follows up 1111111.

                ## {h['scope']}
                sha 3f9c2ab, full.

                | Id | Lens | Severity | Title | Status | Fix commit | Check added |
                |---|---|---|---|---|---|---|
                | CPY-1 | copy | P1 | Promises SMS | {h['pending_status']} | — | — |

                ## {h['pending']}
                - CPY-1: change the text or add SMS.

                ## {h['notes']}
                Nothing else.
                """)

    def test_I18N_2_a_prd_and_reports_in_any_page_language_read_the_same_in_every_language(self):
        """md_section() matched only English headings, so a Spanish PRD showed 0 metrics, 0 in scope,
        0 out and no Metrics/Scope blocks, and a Spanish report lost its pending decisions (and read
        its sha from the wrong section). The class: a section the dashboard reads out of a document
        by its heading, in a document written in any language T speaks, under a page in any of them."""
        expected = {"metrics": 2, "in": 1, "out": 2}
        for docs in DOC_WORDS:
            for variant in range(max(len(v) for v in DOC_WORDS[docs].values() if isinstance(v, tuple))):
                for page in ("en", "es"):
                    with self.subTest(docs=docs, variant=variant, page=page):
                        self.gates("intake", "product", lang=page)
                        self.context()
                        self.docs_in(docs, variant)
                        s = self.state()
                        self.assertEqual({k: s["counts"][k] for k in expected}, expected)
                        for run in (s["bugbashes"][0], s["security"][0]):
                            self.assertEqual(run["sha"], "3f9c2ab", run["path"])
                            self.assertEqual(run["pending"], "- CPY-1: change the text or add SMS.", run["path"])
                        html = self.page("--lang", page)
                        t = load_dashboard().T[page]
                        for key in ("metrics", "scope"):
                            self.assertIn(f'<div class="block"><h3>{esc(t[key])}</h3><div class="md bare">', html)
                        self.assertIn("Orders", html.split(f'<h3>{esc(t["metrics"])}</h3>')[1].split("</div></div>")[0])
                        self.assertEqual(html.count(f'<div class="block"><h3>{esc(t["bb_pending"])}</h3>'), 2)

    def test_I18N_2_a_decision_record_and_the_stack_read_their_fields_in_every_language(self):
        """The ADR's status came from an English-only regex (`Status:` or `## Status`), and the stack's
        apps from `^apps?:` over docs/stack.md, so a Spanish ADR showed no status and a Spanish
        stack.md no apps. Same class as the PRD: a field read out of a document by an English name."""
        adrs = {"en": ("## Status\n\nAccepted\n", "Status: Accepted\n", "**Status:** Accepted\n", "- Status: Accepted\n"),
                "es": ("## Estado\n\nAceptada\n", "Estado: Aceptada\n", "**Estado:** Aceptada\n", "- **Estado**: Aceptada\n",
                       "ESTADO:\nAceptada\n")}
        stacks = {"en": ("Apps: web, api\n", "**Apps:** web, api\n", "App: web, api\n"),
                  "es": ("Aplicaciones: web, api\n", "**Aplicaciones:** web, api\n", "Aplicación: web, api\n", "Apps: web, api\n")}
        word = {"en": "Accepted", "es": "Aceptada"}
        for docs in ("en", "es"):
            for variant in range(max(len(adrs[docs]), len(stacks[docs]))):
                for page in ("en", "es"):
                    with self.subTest(docs=docs, variant=variant, page=page):
                        self.gates("intake", "product", "stack", lang=page)
                        self.context()
                        self.write("docs/prd.md", "# Shop — PRD\n")
                        adr = adrs[docs][variant % len(adrs[docs])]
                        self.write("docs/decisions/0001-queue.md", f"# 0001 — A queue\n\n{adr}\n## Context\nStatus quo: none.\n")
                        self.write("docs/stack.md", f"# Stack\n\n{stacks[docs][variant % len(stacks[docs])]}\nPostGIS: no.\n")
                        s = self.state()
                        self.assertEqual([a["status"] for a in s["adrs"]], [word[docs]])
                        html = self.page("--lang", page)
                        self.assertIn(f'A queue</a> <span class="muted">· {word[docs]}</span>', html)
                        self.assertIn(esc(load_dashboard().T[page]["sum_stack"].format(apps="web, api")), html)

    def test_I18N_2_a_bold_label_inside_in_or_out_groups_its_bullets(self):
        """Turning every bold line of Scope into a heading ended In at the first sub-label: a PRD that
        groups its bullets under **Buyers** counted 0 in scope. Only In and Out are headings."""
        for label in ("**Buyers**", "**Buyers:**", "**Integrations**", "**In-store pickup**"):
            with self.subTest(label=label):
                self.gates("intake")
                self.context()
                self.write("docs/prd.md", f"# Shop — PRD\n\n## Scope\n**In (MVP):**\n{label}\n- Checkout\n- Cart\n\n"
                                          f"**Sellers**\n- Payouts\n\n**Out (explicitly):**\n**Later**\n- Gift cards\n\n## Risks\n- x\n")
                self.assertEqual({k: self.state()["counts"][k] for k in ("in", "out")}, {"in": 3, "out": 1})

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
        self.assertTrue(html.startswith("<title>Reporte de Shop</title>"))
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

    def test_I18N_5_the_report_writes_dates_in_its_language(self):
        """I18N-5: the report printed every date as ISO in both languages, though the skill says the
        page's language governs dates. Visible dates follow the language; requests keep ISO."""
        for lang, approved, generated in (("en", "Approved on Sep 20, 2026", r"Report generated [A-Z][a-z]{2} \d{1,2}, \d{4}, \d\d:\d\d"),
                                          ("es", "Aprobada el 20 sep 2026", r"Reporte generado el \d{1,2} [a-z]{3} \d{4}, \d\d:\d\d")):
            with self.subTest(lang=lang):
                self.gates("intake", "product", lang=lang)
                self.context()
                self.write("docs/prd.md", "# PRD\n")
                html = self.page("--standalone")
                self.assertIn(approved, html)
                self.assertRegex(html, generated)
                self.assertNotRegex(re.sub(r"<[^>]*>", " ", html), r"(Approved on|Aprobada el) 2026-")

    def test_SEC_4_a_doc_link_never_leaves_the_project(self):
        """SEC-4 (bug bash 2026-09-27): /etc/passwd or a ../.. chain in a project doc is plain text."""
        dash = load_dashboard()
        out = self.root / "out"
        for links in (dash.Links(None, True, out, self.root), dash.Links("https://github.com/a/b/blob/main/", False, out, self.root)):
            for url in ("/etc/passwd", "../../../../etc/hosts", "../../../x.md"):
                with self.subTest(url=url, github=bool(links.github)):
                    self.assertIsNone(links.href(url))
                    self.assertNotIn("<a ", dash.inline(f"[x]({url})", links, "docs/context/product.md"))
            self.assertTrue(links.href("docs/context/gaps.md").endswith("docs/context/gaps.md"))
            self.assertTrue(links.href("docs/decisions/").endswith("docs/decisions/"))
        self.assertIn('href="https://github.com/a/b/blob/main/docs/context/gaps.md"',
                      dash.inline("[g](gaps.md)", links, "docs/context/product.md"))

    def building(self, lang: str = "en") -> None:
        """A project in build: one story done, one ready, one waiting for it, a bug bash with a
        pending decision, and an environment half set up."""
        self.gates("intake", "product", "stack", "skeleton", "backlog", lang=lang)
        self.context()
        self.write(".keelokit/answers.yml", "mode: project\nproject_name: Shop\n")
        self.story("AUTH-001", 1)
        self.story("AUTH-002", 2, deps='"AUTH-001"')
        self.write("backlog/stories/CART-001-x.md", STORY.format(id="CART-001", epic="CART", title="t CART-001", wave=2,
                                                                 deps='"AUTH-002"', body="").replace(
            'dimensions = ["api"]', 'dimensions = ["api"]\norigin = "bugbash:2026-09-24 UX-3"'))
        self.write("docs/bugbash/2026-09-24/report.md",
                   "# Bug bash\n\n## Scope\nsha 4be91c0\n\n## Findings\n\n"
                   "| Id | Lens | Severity | Title | Status | Fix commit | Check added |\n|---|---|---|---|---|---|---|\n"
                   "| CPY-1 | copy | P1 | The page promises SMS | pending decision | — | — |\n"
                   "| UX-2 | ux | P2 | Empty agenda spins | fixed | 9d8e7f6 | E2E step |\n\n"
                   "## Pending decisions\n\n- **CPY-1** — the page promises SMS; the PRD says WhatsApp. Recommendation: (a).\n")
        self.write("docs/context/environments.md", "| Environment | Purpose | URL |\n|---|---|---|\n| staging | main | s.shop.app |\n")
        self.write("docs/deploy.md", "# Deploy\n\n## staging\n- [x] Fly.io account\n- [ ] Domain and HTTPS\n")
        self.commit("chore: start")
        self.commit("feat: sign in\n\nStory: AUTH-001")

    def test_the_dashboard_is_the_short_operational_page(self):
        self.building()
        html = self.ops("--standalone")
        for text in ("Stage 6 of 6 · Build", "/keelokit:build-story AUTH-002", "Waiting on you", "CPY-1",
                     "the page promises SMS; the PRD says WhatsApp", "Development waves", "1 of 3 stories",
                     "Waits for AUTH-002", "from a bug bash", "1 step left for staging: Domain and HTTPS.",
                     "Health and environments", 'data-ask="/keelokit:project-report"'):
            self.assertIn(esc(text), html)
        # Every story links to its file, and a ready one copies its command.
        self.assertIn('backlog/stories/AUTH-002-x.md', html)
        self.assertIn('data-ask="/keelokit:build-story AUTH-002"', html)
        # It carries no stage documents: those are the report's.
        self.assertNotIn('class="stage ', html)
        self.assertLess(len(html), len(self.page()))

    def test_the_report_is_read_only(self):
        self.building()
        html = self.page()
        self.assertIn("<title>Shop report</title>", html)
        self.assertNotIn('id="ask"', html, "no Ask Claude box on a report")
        self.assertIn("button[data-ask]{display:none}", html, "no button that prepares a request")
        self.assertIn(esc("the page promises SMS"), html)

    def test_live_writes_a_shell_without_project_data_and_one_data_document(self):
        self.building()
        out = json.loads(sh(self.root, "python3", str(DASHBOARD), "--root", str(self.root), "--live"))
        shell = Path(out["shell"]["file"]).read_text()
        doc = json.loads(Path(out["data"]["file_path"]).read_text())
        self.assertEqual((out["data"]["collection"], out["data"]["doc_id"]), ("dash", "ops"))
        self.assertTrue(out["shell"]["publish"], "nothing is published yet")
        self.assertNotIn("AUTH-002", shell)
        self.assertIn(f'data-shell="{out["shell"]["id"]}"', shell)
        self.assertEqual(doc["shell"], out["shell"]["id"])
        self.assertIn("AUTH-002", doc["html"])
        self.assertLess(len(json.dumps(doc)), 256 * 1024)
        # Recording the published shell makes the next refresh a data write only, until the design changes.
        with (self.root / ".keelokit/state.toml").open("a") as f:
            f.write('url = "https://claude.ai/artifact/abc"\n')
        sh(self.root, "python3", str(DASHBOARD), "--root", str(self.root), "--live", "--shell-published")
        state = (self.root / ".keelokit/state.toml").read_text()
        self.assertIn(f'shell = "{out["shell"]["id"]}"', state)
        self.assertIn('lang = "en"', state, "the rest of [dashboard] stays")
        self.assertIn("[gates]", state)
        self.story("AUTH-003", 3)
        again = json.loads(sh(self.root, "python3", str(DASHBOARD), "--root", str(self.root), "--live"))
        self.assertEqual(again["shell"]["id"], out["shell"]["id"], "new data never changes the shell")
        self.assertFalse(again["shell"]["publish"], again)
        self.assertEqual(again["url"], "https://claude.ai/artifact/abc")

    def test_live_shell_changes_with_the_language(self):
        self.building()
        en = json.loads(sh(self.root, "python3", str(DASHBOARD), "--root", str(self.root), "--live"))["shell"]["id"]
        es = json.loads(sh(self.root, "python3", str(DASHBOARD), "--root", str(self.root), "--live", "--lang", "es"))["shell"]["id"]
        self.assertNotEqual(en, es)

    def test_operational_page_in_spanish(self):
        self.building("es")
        html = self.ops()
        for text in ("Etapa 6 de 6 · Construcción", "Te esperan", "Olas de desarrollo", "Espera a AUTH-002",
                     "del bug bash", "Salud y entornos", "Generar el reporte completo", "24 sep"):
            self.assertIn(esc(text), html)


# I18N-2: the headings of the PRD and the reports as someone would write them in each language of
# the page (project-new writes documents in English unless the user asks otherwise). A tuple is
# ways of writing the same heading; each variant renders one of them. Written by hand, so the test
# does not read the dashboard's own list of names back to itself.
DOC_WORDS = {
    "en": {"status": "Status", "problem": "Problem", "metrics": ("Success metrics", "SUCCESS METRICS"),
           "scope": ("Scope", "Scope (MVP)"), "integrations": "Integrations",
           "in": ("In (MVP)", "In"), "out": ("Out (explicitly)", "Out"), "risks": "Risks",
           "summary": "Summary", "pending_status": "pending decision",
           "pending": ("Pending decisions", "Pending decisions (2)"), "notes": "Notes"},
    "es": {"status": "Estado", "problem": "Problema",
           "metrics": ("Métricas de éxito", "Metricas de exito", "MÉTRICAS DE ÉXITO"),
           "scope": ("Alcance", "Alcance (MVP)", "Alcance"), "integrations": "Integraciones",
           "in": ("Dentro (MVP)", "Dentro", "Dentro del MVP"),
           "out": ("Afuera (a propósito)", "Fuera (explícitamente)", "Fuera"), "risks": "Riesgos",
           "summary": "Resumen", "pending_status": "pendiente de decisión",
           "pending": ("Decisiones pendientes", "Decisiones pendientes", "Decisiones pendientes (1)"),
           "notes": "Notas"},
}


def load_dashboard_marking_anchors():
    """dashboard.py with every dict literal that has an "anchor" key (the next step, each waiting
    item) wrapped in __anchor_site__(i, {...}), so a test knows which of them its states reached.
    Returns the module, each site's line, and the set of sites hit so far."""
    tree = ast.parse(DASHBOARD.read_text(), str(DASHBOARD))
    lines: list[int] = []

    class Mark(ast.NodeTransformer):
        def visit_Dict(self, node):
            self.generic_visit(node)
            if not any(isinstance(k, ast.Constant) and k.value == "anchor" for k in node.keys):
                return node
            lines.append(node.lineno)
            call = ast.Call(ast.Name("__anchor_site__", ast.Load()), [ast.Constant(len(lines) - 1), node], [])
            return ast.copy_location(call, node)

    tree = ast.fix_missing_locations(Mark().visit(tree))
    hit: set[int] = set()
    module = types.ModuleType("keelokit_dashboard_anchors")
    module.__file__ = str(DASHBOARD)
    module.__anchor_site__ = lambda i, d: (hit.add(i), d)[1]
    exec(compile(tree, str(DASHBOARD), "exec"), module.__dict__)
    return module, lines, hit


class DashboardAnchorsLandTest(unittest.TestCase):
    """UX-1, the class: the next step and the waiting list linked to #stage-build before the page
    drew it. Tests render only the states their fixtures happen to build, so a branch no fixture
    reaches could keep a dead link. Here a matrix of real projects (both layouts; no backlog, a mixed
    one, a blocked one, a finished one, one without main; with and without bug bash and security
    reports; the first gate pending, the last one, all approved) times what the doctor and the user
    report (errors, blocking gaps, an unknown or drifted profile, an old harness, no run mode) is
    rendered, every in-page link must land, and every dict with an "anchor" in dashboard.py must be
    reached by some state in the matrix: a new one no state reaches fails here until a state does."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def project(self, layout: str, stories: str, reports: bool) -> Path:
        root = self.tmp / f"{layout}-{stories}-{int(reports)}"
        files = {
            ".keelokit/answers.yml": f"_commit: v0.7.1\nmode: {layout}\nproject_name: Shop\n",
            "docs/context/product.md": "# product\n", "docs/context/constraints.md": "# constraints\n",
            "docs/context/domain.md": "# domain\n\n- **INV-001** [MUST] A booking is paid once.\n",
            "docs/context/environments.md": "| Environment | Purpose | URL |\n|---|---|---|\n| staging | main | staging.shop.app |\n",
            "docs/context/gaps.md": "| Id | File | Missing | Owner | Question | Blocking |\n|---|---|---|---|---|---|\n"
                                    "| GAP-001 | domain.md | window | Owner | How long? | no |\n",
            "docs/decisions/0001-postgres.md": "# Use Postgres\n\nStatus: Accepted\n",
            ".keelokit/profile.toml": 'kind = "web-product"\ntraits = ["hosted"]\n',
        }
        if layout == "project":
            files["docs/prd.md"] = "# Shop — PRD\n\n## Success metrics\n| Metric | Target |\n|---|---|\n| Orders | 10 |\n"
            files["docs/stack.md"] = "# Stack\n\nApps: api, web\n"
        else:
            files[".keelokit/exceptions.toml"] = ""
            files["docs/diagnosis.md"] = "# Diagnosis\n"
        deps = {"none": [], "mixed": [("A-001", ""), ("A-002", '"A-001"'), ("A-003", '"A-002"')],
                "blocked": [("B-001", '"Z-999"')], "done": [("C-001", "")], "no_main": [("A-001", ""), ("A-002", '"A-001"')],
                "waves": [("A-001", ""), ("A-002", ""), ("W-001", ""), ("W-002", "")]}
        for sid, dep in deps[stories]:
            wave = 2 if sid.startswith("W") else 1
            files[f"backlog/stories/{sid}-x.md"] = STORY.format(id=sid, epic=sid[0], title=f"t {sid}", wave=wave, deps=dep, body="")
        if reports:
            table = "| Id | Lens | Severity | Title | Status | Fix commit | Check added |\n|---|---|---|---|---|---|---|\n"
            files["docs/bugbash/2026-09-01/report.md"] = f"# Bug bash\n\n## Scope\nsha 3f9c2ab\n\n{table}| UX-9 | ux | P2 | x | pending decision | — | — |\n"
            files["docs/security/2026-09-01/report.md"] = f"{table}| SEC-9 | logs | P1 | y | pending decision | — | — |\n"
            files["docs/deploy.md"] = "# Deploy\n\n## staging\n- [x] Account\n- [ ] Domain\n"
        for rel, text in files.items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(text)
        sh(root, "git", "init", "-q", "-b", "main")
        sh(root, "git", "config", "user.email", "t@example.com")
        sh(root, "git", "config", "user.name", "T")
        sh(root, "git", "add", "-A")
        sh(root, "git", "commit", "-qm", "chore: skeleton")
        done = {"mixed": "A-001", "done": "C-001", "no_main": "A-001"}.get(stories)
        if stories == "no_main":
            sh(root, "git", "checkout", "-q", "--detach")
            sh(root, "git", "branch", "-q", "-D", "main")
        if done:
            sh(root, "git", "commit", "-q", "--allow-empty", "-m", f"feat: x\n\nStory: {done}")
        return root

    def test_UX_1_every_anchor_the_page_can_link_lands_in_every_state(self):
        dashboard, lines, hit = load_dashboard_marking_anchors()
        self.assertGreaterEqual(len(lines), 10, "the anchors moved: update load_dashboard_marking_anchors")
        errors = ["Harness errors: 3 — run `pnpm run doctor`"]
        reported = [
            {},
            {"doctor": errors, "errors": 3, "profile": {"kind": "unknown", "traits": []}, "harness": "0.1.0", "run": {},
             "gaps": [{"id": "GAP-002", "file": "domain.md", "missing": "m", "owner": "o", "question": "q?", "blocking": True}]},
            {"doctor": errors + ["Profile drift: the profile lists `hosted` but nothing in the repo shows it yet"],
             "errors": 3, "drift": [{"trait": "hosted", "seen": None}], "run": {"mode": "auto"}},
            {"doctor": ["Harness errors: 0"], "profile": None, "run": {"mode": "step"},
             "gaps": [{"id": "GAP-002", "file": "domain.md", "missing": "m", "owner": "o", "question": "", "blocking": True}]},
        ]
        n = waves_seen = 0
        for layout, order in dashboard.GATES.items():
            for stories in ("none", "mixed", "blocked", "done", "no_main", "waves"):
                for reports in (False, True):
                    root = self.project(layout, stories, reports)
                    for gates in (order[:0], order[:-1], order):
                        (root / ".keelokit/state.toml").write_text(
                            "[gates]\n" + "".join(f'{g} = "2026-09-20"\n' for g in gates))
                        base = dashboard.collect(root)
                        for i, extra in enumerate(reported):
                            s = {**base, **extra}
                            lang = ("en", "es")[n % 2]
                            n += 1
                            with self.subTest(layout=layout, stories=stories, reports=reports, gates=len(gates),
                                              reported=i, lang=lang):
                                html = dashboard.render(s, lang, bool(n % 3), self.tmp, "0.7.1")
                                self.assertEqual(dead_links(html), [], "in-page links with nothing to land on")
                                self.assertEqual(duplicate_ids(html), [], "ids on more than one element")
                                self.assertEqual(vague_build_buttons(html), [], "build buttons that don't name their stories")
                                waves_seen += sum("W-001 W-002" in " ".join(args) for _, args in build_buttons(html))
        self.assertGreater(waves_seen, 0, "no state rendered a wave's build button: UX-2's check saw nothing")
        missed = [lines[i] for i in range(len(lines)) if i not in hit]
        self.assertEqual(missed, [], "dashboard.py lines with an anchor no state here renders: add a state that "
                                     "reaches each one, so its link is checked")


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


REPO = DASHBOARD.parents[3]
# Where each English name of HEADINGS comes from: the documents that write those headings (as a
# `## Heading` or `**Label:**`), or, for the decision records, name their sections in prose.
HEADING_SOURCES = {
    "metrics": ["skills/project-new/references/prd-template.md"],
    "scope": ["skills/project-new/references/prd-template.md", "skills/check-bugbash/SKILL.md", "skills/check-security/SKILL.md",
              "workflows/check-bugbash-flow.js"],
    "in": ["skills/project-new/references/prd-template.md"],
    "out": ["skills/project-new/references/prd-template.md"],
    "pending": ["skills/check-bugbash/SKILL.md", "skills/check-security/SKILL.md", "workflows/check-bugbash-flow.js"],
    "status": ["template/docs/decisions/README.md", "skills/project-new/SKILL.md"],
    "apps": ["skills/project-new/SKILL.md"],
}
IN_PROSE = {"status"}
# Words a pattern in dashboard.py may match literally without HEADINGS, because no language changes
# them: ids and tags (GAP-001, INV-001, [MUST NOT]), the acronym in "<Product> — PRD", a TOML key and
# table (rules.toml's `id = "`, exceptions.toml's `[[exception]]`) and the parts of a GitHub URL.
# A phrase of two words or more that a pattern takes from doctor.py's output passes when doctor.py
# prints it (English by design, I18N-1).
NEUTRAL_WORDS = {"gap", "inv", "must", "not", "prd", "id", "exception", "http", "https", "git", "github", "com", "ssh"}
RE_CALLS = {"compile", "match", "fullmatch", "search", "findall", "finditer", "sub", "subn", "split"}


def literal_runs(pattern: str) -> list[str]:
    """The runs of text a regex matches literally ("apps?" → "app", "s"), from Python's own parser."""
    try:
        import re._parser as parser
    except ImportError:  # Python < 3.11
        import sre_parse as parser
    runs, cur = [], []

    def flush():
        if cur:
            runs.append("".join(cur))
            cur.clear()

    def walk(sub):
        for op, av in sub:
            name = str(op)
            if name == "LITERAL":
                cur.append(chr(av))
                continue
            flush()
            if name == "SUBPATTERN":
                walk(av[3])
            elif name == "BRANCH":
                for alt in av[1]:
                    walk(alt)
                    flush()
            elif name.endswith("_REPEAT"):
                walk(av[2])
            elif name in ("ASSERT", "ASSERT_NOT"):
                walk(av[1])
            elif name == "ATOMIC_GROUP":
                walk(av)
            elif name == "GROUPREF_EXISTS":
                walk(av[1])
                flush()
                walk(av[2] or [])
            flush()

    walk(parser.parse(pattern))
    flush()
    return runs


class DashboardDocHeadingsTest(unittest.TestCase):
    """I18N-2: md_section() took one English heading from each caller, and an ADR's status and the
    stack's apps came from English-only regexes, so a PRD, report, decision record or stack.md written
    in Spanish lost its metrics, scope, pending decisions, status or apps. The class: a document the
    dashboard reads by a name only one language writes. Every section or field it reads is a key of
    HEADINGS, named in every language of T; no caller passes a name of its own, no heading of the
    documents it reads appears anywhere else in its code, and no pattern matches a word literally
    unless no language changes it."""

    def setUp(self):
        self.dashboard = load_dashboard()
        self.tree = ast.parse(DASHBOARD.read_text())
        tables = {"T", "OPS_T", "STAGES", "GLOSSARY", "HEADINGS"}
        self.skip = {id(n) for node in self.tree.body if isinstance(node, ast.Assign)
                     and any(isinstance(t, ast.Name) and t.id in tables for t in node.targets) for n in ast.walk(node)}

    def test_I18N_2_every_section_is_named_in_every_language_of_the_page(self):
        for key, names in self.dashboard.HEADINGS.items():
            with self.subTest(key=key):
                self.assertEqual(set(names), set(self.dashboard.T), "a section needs its name in every language of T")
                self.assertTrue(all(isinstance(n, tuple) and n and all(x.strip() for x in n) for n in names.values()))

    def test_I18N_2_the_english_names_are_the_headings_the_documents_write(self):
        self.assertEqual(set(HEADING_SOURCES), set(self.dashboard.HEADINGS), "say where each section's heading is written")
        for key, files in HEADING_SOURCES.items():
            name = re.escape(self.dashboard.HEADINGS[key]["en"][0])
            for rel in files:
                text = (REPO / rel).read_text()
                with self.subTest(key=key, file=rel):
                    pattern = rf"(?i)\b{name}\b" if key in IN_PROSE else rf"(?mi)(^|[\"`]|^\s*[-*] )(#+ |\*\*){name}\b"
                    self.assertTrue(re.search(pattern, text), f"{rel} doesn't write {name!r}")

    def test_DOC_203_every_skill_that_writes_a_report_the_dashboard_reads_writes_the_headings_it_reads(self):
        """DOC-203: check-security's report format named its Scope in prose while the dashboard reads
        the report's sha from `## Scope`, so the sha came from the whole report's first hex word. The
        class: a skill writes a report the dashboard parses without the headings the parser reads.
        Every folder reports() is called on, every section it reads there, and every skill whose
        report section writes into that folder must write that section as a heading."""
        func = next(n for n in ast.walk(self.tree) if isinstance(n, ast.FunctionDef) and n.name == "reports")
        keys = {c.args[1].value for c in ast.walk(func) if isinstance(c, ast.Call)
                and getattr(c.func, "id", "") == "md_section" and isinstance(c.args[1], ast.Constant)}
        folders = {c.args[0].value for c in ast.walk(self.tree) if isinstance(c, ast.Call)
                   and getattr(c.func, "id", "") == "reports" and isinstance(c.args[0], ast.Constant)}
        self.assertTrue(keys >= {"scope", "pending"} and folders >= {"docs/security", "docs/bugbash"}, (keys, folders))
        for folder in sorted(folders):
            writers = [p for p in sorted(REPO.glob("skills/*/SKILL.md"))
                       if re.search(rf"(?m)^#+ .*Report\b.*`{re.escape(folder)}/<date>/report\.md`", p.read_text())]
            self.assertTrue(writers, f"no skill writes {folder}/<date>/report.md")
            for path, key in ((p, k) for p in writers for k in sorted(keys)):
                rel = path.relative_to(REPO).as_posix()
                with self.subTest(folder=folder, file=rel, key=key):
                    self.assertIn(rel, HEADING_SOURCES[key], f"{rel} writes {folder} reports: list it for {key!r}")
                    name = re.escape(self.dashboard.HEADINGS[key]["en"][0])
                    self.assertRegex(path.read_text(), rf"`#+ {name}\b", f"{rel} must require the literal `## {name}` heading")

    def test_I18N_2_a_heading_matches_whole_words_in_any_case_and_accents(self):
        md = self.dashboard.md_section
        self.assertEqual(md("## Integrations\nx\n## In (MVP):\ny\n", "in"), "y")
        self.assertEqual(md("## In-store\nx\n## In\ny\n", "in"), "y")
        self.assertEqual(md("## Métricas\nx\n", "metrics"), "x")
        self.assertEqual(md("### METRICAS DE EXITO\nx\n## next\n", "metrics"), "x")
        self.assertEqual(md("## Alcanceextra\nx\n", "scope"), "")
        with self.assertRaises(KeyError):
            md("## Scope\nx\n", "Scope")  # a caller names a section, never a heading

    def test_I18N_2_a_field_is_a_label_or_a_heading_naming_it_exactly(self):
        field = self.dashboard.md_field
        self.assertEqual(field("Status quo: bad\nStatus: Accepted\n", "status"), "Accepted")
        self.assertEqual(field("# T\n\n## ESTADO\n\nAceptada\n", "status", heading=True), "Aceptada")
        self.assertEqual(field("## Estado\nAceptada\n", "status"), "")  # a heading only when asked for
        self.assertEqual(field("**Aplicación:** web\n", "apps"), "web")
        with self.assertRaises(KeyError):
            field("Status: x\n", "Status")

    def test_I18N_2_no_caller_reads_a_document_by_a_heading_of_its_own(self):
        headings = set()
        for key, files in HEADING_SOURCES.items():
            for rel in set(files):
                text = (REPO / rel).read_text()
                found = re.findall(r"(?m)^#+ +(.+)$|^\*\*([^*]+)\*\*", text)
                headings |= {h.strip(" :*").split(" (")[0] for pair in found for h in pair if h}
                headings |= {w for m in re.findall(r"\b[A-Z]\w+(?:, [A-Z]\w+){2,}", text) for w in m.split(", ")}
        headings = {h for h in headings if h and "<" not in h and "$" not in h}
        self.assertTrue({"Success metrics", "Scope", "In", "Out", "Risks", "Status", "Consequences"} <= headings, headings)
        readers = {"md_section", "md_field", "is_named"}
        for node in ast.walk(self.tree):
            if id(node) in self.skip:
                continue
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") in readers:
                arg = node.args[1]
                with self.subTest(line=node.lineno):
                    self.assertTrue(isinstance(arg, ast.Name) or (isinstance(arg, ast.Constant) and arg.value in self.dashboard.HEADINGS),
                                    f"{node.func.id}() takes a key of HEADINGS")
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                bare = node.value.strip(" #*:")
                with self.subTest(line=node.lineno, value=node.value):
                    self.assertFalse(bare in headings and bare not in self.dashboard.HEADINGS,
                                     "a document's heading in the code reads only English: add it to HEADINGS")

    def test_I18N_2_no_pattern_matches_a_word_that_a_language_changes(self):
        """A heading or label buried in a regex (`(?im)^status:`, `^apps?:`) reads only the language it
        is written in. Every pattern is a literal (so this can read it), and every word it matches
        literally is in NEUTRAL_WORDS or is text doctor.py prints."""
        doctor = DOCTOR.read_text()
        self.assertEqual(literal_runs(r"(?im)^(?:status:\s*|##\s*status\s*\n+)"), ["status:", "##", "status", "\n"])
        self.assertEqual(literal_runs(r"(?im)^apps?:\s*(.+)$"), ["app", "s", ":"])
        patterns = 0
        for node in ast.walk(self.tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in RE_CALLS
                    and getattr(node.func.value, "id", "") == "re"):
                continue
            arg = node.args[0]
            with self.subTest(line=node.lineno):
                self.assertTrue(isinstance(arg, ast.Constant) and isinstance(arg.value, str),
                                "a pattern is a string literal, so this test can read it")
                patterns += 1
                for run in literal_runs(arg.value):
                    words = {w.lower() for w in re.findall(r"[A-Za-z]{2,}", run)} - NEUTRAL_WORDS
                    if len(words) > 1 and run.strip() in doctor:
                        continue  # a phrase doctor.py prints, not one word that also happens to be in it
                    self.assertFalse(words, f"{arg.value!r} matches {sorted(words)} literally: name it in HEADINGS "
                                            "and read it with md_section() or md_field()")
        self.assertGreater(patterns, 20)


try:
    from playwright.sync_api import sync_playwright
except ImportError:  # CI installs it (.github/workflows/ci.yml), so there the layout test runs
    sync_playwright = None

LONG = "INFRAESTRUCTURA-DE-PAGOS-RECURRENTES"  # an id, epic, path or value with nowhere to break

# The innermost elements, outside the tables that scroll on their own (.scroll), whose box runs
# past the viewport, whose text spills out of their box or is crushed to a few letters a line, as
# [tag.classes, right edge, text].
OVERFLOW_JS = """() => {
  const W = document.documentElement.clientWidth, bad = new Set();
  for (const el of document.body.querySelectorAll('*'))
    if (!el.closest('.scroll, svg') && el.getClientRects().length && el.getBoundingClientRect().right > W + 0.5) bad.add(el);
  const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let node; (node = walk.nextNode());) {
    let box = node.parentElement;
    if (!node.textContent.trim() || box.closest('.scroll, svg, script, style, textarea')) continue;
    while (getComputedStyle(box).display === 'inline') box = box.parentElement;
    if (getComputedStyle(box).textOverflow === 'ellipsis') continue;  // cut on purpose, with its ellipsis
    const range = document.createRange();
    range.selectNodeContents(node);
    const edge = box.getBoundingClientRect().right, lines = [...range.getClientRects()].filter(r => r.width);
    const text = node.textContent.trim();
    if (lines.some(r => r.right > edge + 1)) bad.add(box);
    // Wrapping is the fix, not a column crushed to a letter or two a line by a wider neighbour.
    else if (text.length >= 8 && new Set(lines.map(r => Math.round(r.top))).size > text.length / 3) bad.add(box);
  }
  const all = [...bad], name = el => el.tagName.toLowerCase()
    + (typeof el.className === 'string' && el.className.trim() ? '.' + el.className.trim().split(/\\s+/).join('.') : '');
  const out = all.filter(el => !all.some(o => o !== el && el.contains(o))).map(el =>
    [name(el), Math.round(el.getBoundingClientRect().right), (el.textContent || '').trim().slice(0, 30)]);
  return {scroll: document.documentElement.scrollWidth, width: W, out: out};
}"""


@unittest.skipUnless(sync_playwright or os.environ.get("CI"), "playwright not installed (CI installs it)")
class DashboardLayoutTest(unittest.TestCase):
    """UI-1, the class: project text the page can't choose (a story or epic id, a path, a command, a
    finding id, a value in backticks, a URL) has no length limit, and one that couldn't break pushed
    the page sideways at 320 px. Both pages (the dashboard and the report, in English and Spanish)
    are rendered for a project whose every slot holds a long unbroken word, every section open, in a
    real browser at 320 / 768 / 1280 px (dimensions.md, ui): nothing may run past the viewport or
    spill out of its own box. A new slot that can't wrap fails here once the fixture fills it."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)

    def project(self) -> None:
        a, b, c = f"{LONG}-001", f"{LONG}-002", f"{LONG}-003"
        low, epic = LONG.lower(), LONG.replace("-", "")
        word = LONG.replace("-", "_") + "_CONFIGURATION_VALUE"
        table = "| Id | Lens | Severity | Title | Status | Fix commit | Check added |\n|---|---|---|---|---|---|---|\n"
        files = {
            ".keelokit/state.toml": "[gates]\n" + "".join(f'{g} = "2026-09-20"\n' for g in
                                                           ("intake", "product", "stack", "skeleton", "backlog")),
            ".keelokit/answers.yml": f"mode: project\nproject_name: Plataformadepagosrecurrentesparacomercios\n"
                                     f"apps: [{low}-api, {low}-web]\n",
            ".keelokit/profile.toml": f'kind = "{low}"\ntraits = ["{low}-trait"]\n',
            "docs/context/product.md": "# product\n", "docs/context/constraints.md": "# constraints\n",
            "docs/context/domain.md": f"# domain\n\n- **INV-001** [MUST] `{word}` is paid once.\n",
            "docs/context/environments.md": "| Environment | Purpose | URL |\n|---|---|---|\n"
                                            f"| {low} | `{word}` | {low}.{low}.app |\n",
            "docs/context/gaps.md": "| Id | File | Missing | Owner | Question | Blocking |\n|---|---|---|---|---|---|\n"
                                    f"| GAP-{LONG} | {LONG}.md | `{word}` | Owner | `{word}`? | yes |\n",
            "docs/deploy.md": f"# Deploy\n\n## {low}\n- [x] Account\n- [ ] Set `{word}`\n",
            "docs/prd.md": f"# Shop — PRD\n\n## Scope\n`{word}`\n",
            "docs/stack.md": f"# Stack\n\nApps: {low}-api\n",
            "docs/decisions/0001-x.md": f"# Use {word}\n\nStatus: Accepted\n",
            "backlog/epics.md": f"| Epic | Goal |\n|---|---|\n| {epic} | `{word}` |\n",
            "backlog/stories/A-001-x.md": STORY.format(id="A-001", epic="A", title="t", wave=1, deps="", body=""),
        }
        for kind, prefix in (("bugbash", "UX"), ("security", "SEC")):
            files[f"docs/{kind}/2026-09-24/report.md"] = (
                f"# Report\n\n## Scope\nsha 4be91c0\n\n## Findings\n\n{table}"
                f"| {prefix}-{LONG} | ux | P1 | `{word}` | pending decision | — | `{word}` |\n\n"
                f"## Pending decisions\n\n- **{prefix}-{LONG}** — `{word}`. Recommendation: (a).\n")
        for sid, wave, deps, origin in ((a, 1, "", ""), (b, 2, f'"{a}"', f'\norigin = "bugbash:2026-09-24 UX-{LONG}"'),
                                        (c, 2, f'"{a}", "{b}"', "")):
            files[f"backlog/stories/{sid}-x.md"] = STORY.format(
                id=sid, epic=epic, title=f"Set {word}", wave=wave, deps=deps,
                body=f"Touches `apps/{low}/src/{word}.ts`.\n").replace('dimensions = ["api"]', 'dimensions = ["api"]' + origin)
        for rel, text in files.items():
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.root / rel).write_text(text)
        for cmd in (("init", "-q", "-b", "main"), ("config", "user.email", "t@example.com"), ("config", "user.name", "T"),
                    ("add", "-A"), ("commit", "-qm", f"chore: {word}"),
                    ("commit", "-q", "--allow-empty", "-m", f"feat: {word}\n\nStory: A-001")):
            sh(self.root, "git", *cmd)

    def test_UI_1_no_project_text_pushes_the_page_sideways_at_any_width(self):
        self.project()
        pages = {}
        for lang in ("en", "es"):
            for name, args in (("dashboard", []), ("report", ["--report"])):
                out = sh(self.root, "python3", str(DASHBOARD), "--root", str(self.root), "--standalone", "--lang", lang,
                         "--out", str(self.root / f"{name}-{lang}.html"), *args).strip()
                pages[f"{name} {lang}"] = Path(out).as_uri()
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for name, uri in pages.items():
                for width in (320, 768, 1280):
                    with self.subTest(page=name, width=width):
                        page = browser.new_page(viewport={"width": width, "height": 900})
                        page.goto(uri)
                        page.evaluate("document.querySelectorAll('details').forEach(d => d.open = true)")
                        got = page.evaluate(OVERFLOW_JS)
                        page.close()
                        self.assertEqual(got["out"], [], f"{got['scroll']} px of page in a {width} px window:\n"
                                         + "\n".join(map(str, got["out"])))
                        self.assertLessEqual(got["scroll"], got["width"])
            browser.close()


STORY_TARGET_JS = """sel => {
  const el = document.querySelector(sel);
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return {open: el.open, hidden: !!el.closest('[hidden]'), top: Math.round(r.top), height: Math.round(r.height)};
}"""


@unittest.skipUnless(sync_playwright or os.environ.get("CI"), "playwright not installed (CI installs it)")
class DashboardStoryLinkTest(unittest.TestCase):
    """UI-2: design.md says a link to a section opens it. A story is drawn in both backlog views
    (by wave, by epic) and the one not chosen is hidden, so a link or a #hash to a story must open
    the copy in the view showing, and a link into the hidden view must switch to it."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        files = {".keelokit/state.toml": "[gates]\n" + "".join(
            f'{g} = "2026-09-20"\n' for g in ("intake", "product", "stack", "skeleton", "backlog"))}
        for n in range(1, 13):
            sid = f"PAY-{n:03d}"
            files[f"backlog/stories/{sid}-x.md"] = STORY.format(
                id=sid, epic="PAY", title=f"t {sid}", wave=1 + n % 3, deps="", body="Body.\n" * 20)
        for rel, text in files.items():
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.root / rel).write_text(text)
        for cmd in (("init", "-q", "-b", "main"), ("config", "user.email", "t@example.com"), ("config", "user.name", "T"),
                    ("add", "-A"), ("commit", "-qm", "chore: skeleton")):
            sh(self.root, "git", *cmd)

    def test_UI_2_a_link_to_a_story_opens_it_in_the_backlog_view_showing(self):
        out = sh(self.root, "python3", str(DASHBOARD), "--root", str(self.root), "--standalone", "--report",
                 "--out", str(self.root / "report.html")).strip()
        uri = Path(out).as_uri()
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 700})
            page.goto(uri)
            page.evaluate("document.querySelectorAll('details').forEach(d => d.open = true)")
            page.click('button[data-show="epic"]')
            page.evaluate("location.hash = '#story-PAY-009'")
            got = page.evaluate(STORY_TARGET_JS, '[data-view="epic"] [id$="-PAY-009"]')
            self.assertIsNotNone(got, "the epic view has no card for PAY-009")
            self.assertEqual((got["open"], got["hidden"]), (True, False), f"#story-PAY-009 by epic: {got}")
            self.assertTrue(got["height"] > 0 and 0 <= got["top"] < 700, f"not scrolled to: {got}")

            page.evaluate("""() => {const a = document.createElement('a'); a.href = '#story-PAY-004';
                a.textContent = 'x'; document.body.prepend(a); a.click()}""")
            got = page.evaluate(STORY_TARGET_JS, '[data-view="epic"] [id$="-PAY-004"]')
            self.assertEqual((got["open"], got["hidden"]), (True, False), f"a link to PAY-004 by epic: {got}")

            wave_id = page.evaluate("document.querySelector('[data-view=\"wave\"] [id$=\"-PAY-007\"]').id")
            page.evaluate(f"location.hash = '#{wave_id}'")
            got = page.evaluate(STORY_TARGET_JS, f'#{wave_id}')
            self.assertEqual((got["open"], got["hidden"]), (True, False), f"a link into the hidden view: {got}")
            self.assertEqual(page.get_attribute('button[data-show="wave"]', "aria-pressed"), "true")
            browser.close()


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


# A11Y-2, the class: a colour token the page writes text in that nobody measured against what it
# sits on. dimensions.md's a11y row asks for a contrast test; this is it, in Python, over every
# stylesheet dashboard.py ships (so a new one is checked the day it lands) and both themes.
def _rgba(value: str) -> tuple[float, float, float, float]:
    value = value.strip()
    if m := re.fullmatch(r"#([0-9a-fA-F]{6})", value):
        return (*(int(m.group(1)[i:i + 2], 16) for i in (0, 2, 4)), 1.0)
    if m := re.fullmatch(r"rgba\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*\)", value):
        return tuple(float(x) for x in m.groups())
    raise ValueError(f"a colour the contrast test can't read: {value!r}")


def _over(top, below):
    a = top[3]
    return (*(top[i] * a + below[i] * (1 - a) for i in range(3)), 1.0)


def _contrast(fg, bg) -> float:
    def lum(c):
        ch = [x / 255 for x in c[:3]]
        r, g, b = (x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in ch)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b
    hi, lo = sorted((lum(fg), lum(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _tokens(block: str) -> dict[str, str]:
    return {k: v.strip() for k, v in re.findall(r"--([\w-]+):([^;}]+)", block)}


class DashboardCopyAnnouncedTest(unittest.TestCase):
    def test_A11Y_6_copied_is_announced(self):
        """A11Y-6: the report's Copy → Copied swap changed only the button's text, with no live
        region, so a screen reader heard nothing. The page has a polite status region, and the copy
        script writes the confirmation into it."""
        dash = load_dashboard()
        self.assertIn('<p class="sr" id="copy-status" role="status" aria-live="polite"></p>', DASHBOARD.read_text())
        self.assertIn(".sr{position:absolute;width:1px;height:1px", dash.CSS)
        ok = dash.JS[dash.JS.index("function ok()"):dash.JS.index("function fallback()")]
        self.assertIn("getElementById('copy-status')", ok)
        self.assertIn("textContent=btn.getAttribute('data-done')", ok.split("copy-status")[1])


class DashboardPaletteTest(unittest.TestCase):
    def test_UI_3_every_text_colour_is_a_palette_token(self):
        """UI-3: the sea band's review pill wrote its text in a bare #FFC08A that no token named, so
        the palette in design.md and the contrast tests never saw it. Every literal text colour in a
        stylesheet dashboard.py ships is one of that stylesheet's tokens."""
        dash = load_dashboard()
        sheets = {k: v for k, v in vars(dash).items() if k.endswith("CSS") and isinstance(v, str)}
        self.assertIn("CSS", sheets)
        for name, css in sheets.items():
            tokens = {v.upper() for v in re.findall(r"--[\w-]+:\s*(#[0-9A-Fa-f]{6})\b", css)}
            for literal in re.findall(r"(?<![\w-])color:\s*(#[0-9A-Fa-f]{3,6})\b", css):
                with self.subTest(sheet=name, colour=literal):
                    self.assertIn(literal.upper(), tokens, "name it as a token in :root and use var()")


class DashboardContrastTest(unittest.TestCase):
    """A11Y-2: light-theme secondary text (--ink-3 at 4.27:1 on paper, 3.86:1 on the ground), the
    review pill and MUST tag (--attn on --attn-soft, 4.31:1) and the 'Not started' pill (--idle on
    --idle-soft, 3.47:1; 4.42:1 in dark) were below WCAG AA's 4.5:1. The class: every themed token
    the page writes text in must reach 4.5:1 on every page surface (ground, paper, sunk) and on its
    own -soft tint, and every rule that sets both a text and a background token must too, in light
    and dark, in every stylesheet dashboard.py ships. This reads the stylesheets alone, so it sees
    neither the tokens that are the same in both themes (the foam text on the sea band), nor
    gradients, literal colours, or text inheriting a colour inside a tinted parent:
    DashboardRenderedContrastTest measures what the browser draws."""

    AA = 4.5
    SURFACES = ("ground", "paper", "paper-2", "sunk")

    def stylesheets(self) -> dict[str, str]:
        module = load_dashboard()
        sheets = {name: value for name, value in vars(module).items()
                  if name.endswith("CSS") and isinstance(value, str) and ":root{" in value}
        self.assertTrue(sheets, "no stylesheet found in dashboard.py")
        return sheets

    def themes(self, css: str) -> dict[str, dict[str, str]]:
        light = _tokens(re.search(r":root\{(.*?)\}", css, re.S).group(1))
        dark_attr = re.search(r':root\[data-theme="dark"\]\{(.*?)\}', css, re.S)
        dark_media = re.search(r'@media \(prefers-color-scheme:dark\)\{:root:not\(\[data-theme="light"\]\)\{(.*?)\}\}',
                               css, re.S)
        self.assertIsNotNone(dark_attr)
        self.assertIsNotNone(dark_media)
        # The system dark theme and the toggled one are two copies of one palette.
        self.assertEqual(_tokens(dark_media.group(1)), _tokens(dark_attr.group(1)))
        return {"light": light, "dark": {**light, **_tokens(dark_attr.group(1))}}

    def test_A11Y_2_every_text_token_reaches_AA_on_every_surface_and_its_tint_in_both_themes(self):
        failures = []
        for name, css in self.stylesheets().items():
            themes = self.themes(css)
            themed = set(themes["dark"]) - {k for k, v in themes["light"].items() if themes["dark"][k] == v}
            used = set(re.findall(r"(?<![-\w])color:var\(--([\w-]+)\)", css))
            text = sorted((used & themed) - set(self.SURFACES))
            self.assertIn("ink-3", text, name)
            for theme, t in themes.items():
                surfaces = {s: _rgba(t[s]) for s in self.SURFACES if s in t}
                for token in text:
                    fg = _rgba(t[token])
                    grounds = dict(surfaces)
                    if f"{token}-soft" in t:
                        soft = _rgba(t[f"{token}-soft"])
                        grounds.update({f"{token}-soft on {s}": _over(soft, bg) for s, bg in surfaces.items()})
                    for where, bg in grounds.items():
                        ratio = _contrast(_over(fg, bg), bg)
                        if ratio < self.AA:
                            failures.append(f"{name} {theme}: --{token} on {where} is {ratio:.2f}:1")
        self.assertEqual(failures, [])

    def test_A11Y_102_the_focus_ring_reaches_3_to_1_on_every_surface_and_on_the_sea(self):
        """A11Y-102: the report's focus ring was --foil, 2.5:1 on the light ground (WCAG's non-text
        contrast asks 3:1). Every stylesheet's ring token reaches 3:1 on every surface in both
        themes, and on the sea band the ring switches to one that reaches 3:1 on its lightest stop."""
        sea = ["#1A64B0", "#040F28"]
        for name, css in self.stylesheets().items():
            ring = re.search(r"(?m)^:focus-visible\{outline:\d+px solid var\(--([\w-]+)\)", css)
            sea_ring = re.search(r"\.sea :focus-visible\{outline-color:var\(--([\w-]+)\)\}", css)
            self.assertTrue(ring and sea_ring, name)
            for theme, t in self.themes(css).items():
                for surface in (x for x in self.SURFACES if x in t):
                    with self.subTest(sheet=name, theme=theme, surface=surface):
                        bg = _rgba(t[surface])
                        self.assertGreaterEqual(_contrast(_over(_rgba(t[ring.group(1)]), bg), bg), 3)
                for stop in sea:
                    with self.subTest(sheet=name, theme=theme, sea=stop):
                        self.assertGreaterEqual(_contrast(_rgba(t[sea_ring.group(1)]), _rgba(stop)), 3)

    def test_A11Y_2_every_rule_that_sets_text_and_background_reaches_AA_in_both_themes(self):
        failures = []
        for name, css in self.stylesheets().items():
            themes = self.themes(css)
            pairs = set()
            for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
                fg = re.search(r"(?<![-\w])color:var\(--([\w-]+)\)", body)
                bg = re.search(r"background(?:-color)?:var\(--([\w-]+)\)", body)
                if fg and bg:
                    pairs.add((selector.strip(), fg.group(1), bg.group(1)))
            self.assertTrue(any(sel.startswith(".pill") or sel.startswith(".stale") for sel, _, _ in pairs), name)
            for theme, t in themes.items():
                surfaces = [_rgba(t[s]) for s in self.SURFACES if s in t]
                for selector, fg_token, bg_token in sorted(pairs):
                    for surface in surfaces:
                        bg = _over(_rgba(t[bg_token]), surface)
                        ratio = _contrast(_over(_rgba(t[fg_token]), bg), bg)
                        if ratio < self.AA:
                            failures.append(f"{name} {theme}: {selector} (--{fg_token} on --{bg_token}) is {ratio:.2f}:1")
                            break
        self.assertEqual(failures, [])


# A11Y-2, the rest of the class: the stylesheet test above can't see where text lands. In the
# browser, every visible text node's colour (times its opacity) is measured against everything
# under it up to the first opaque background: tints, and a linear gradient over the stretch of it
# the text covers (both ends and every stop between), composited as the browser does. 4.5:1, or
# 3:1 for large text (24 px, or 18.66 px bold). Decorative glyphs (aria-hidden) and disabled
# controls are exempt in WCAG and here. Returns the failures as [path [colour], ratio, need, text].
CONTRAST_JS = r"""() => {
  const rgba = s => { const m = s.match(/rgba?\(([^)]+)\)/); if (!m) return null;
    const p = m[1].split(/[\s,\/]+/).filter(Boolean).map(Number); return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1]; };
  const over = (top, below) => { const a = top[3]; return [0, 1, 2].map(i => top[i] * a + below[i] * (1 - a)).concat(1); };
  const lum = c => { const [r, g, b] = c.slice(0, 3).map(x => { x /= 255; return x <= 0.04045 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4; });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
  const ratio = (a, b) => { const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x); return (hi + 0.05) / (lo + 0.05); };
  const split = s => { const out = []; let depth = 0, cur = '';
    for (const ch of s) { if (ch === '(') depth++; if (ch === ')') depth--; if (ch === ',' && !depth) { out.push(cur.trim()); cur = ''; } else cur += ch; }
    return out.concat(cur.trim()); };
  const SIDES = {'to top': 0, 'to right': 90, 'to bottom': 180, 'to left': 270};
  // A linear gradient's colours over the stretch of it a text box covers: both ends and every stop between.
  const gradient = (image, box, text) => {
    const m = image.match(/^linear-gradient\((.*)\)$/); if (!m) return null;
    let parts = split(m[1]), angle = 180;
    if (/deg$/.test(parts[0])) angle = parseFloat(parts.shift());
    else if (parts[0] in SIDES) angle = SIDES[parts.shift()];
    else if (/^to /.test(parts[0])) return null;
    const stops = parts.map((p, i) => { const c = rgba(p), pos = p.match(/([\d.]+)%\s*$/);
      return {c, t: pos ? parseFloat(pos[1]) / 100 : i / (parts.length - 1)}; });
    if (stops.some(s => !s.c)) return null;
    const rad = angle * Math.PI / 180, dx = Math.sin(rad), dy = -Math.cos(rad);
    const L = Math.abs(box.width * dx) + Math.abs(box.height * dy), cx = box.left + box.width / 2, cy = box.top + box.height / 2;
    const at = (x, y) => Math.min(1, Math.max(0, ((x - cx) * dx + (y - cy) * dy) / L + 0.5));
    const ts = [text.left, text.right].flatMap(x => [text.top, text.bottom].map(y => at(x, y)));
    const lo = Math.min(...ts), hi = Math.max(...ts);
    const colour = t => { let i = 0; while (i < stops.length - 1 && stops[i + 1].t < t) i++;
      const a = stops[i], b = stops[Math.min(i + 1, stops.length - 1)], f = b.t > a.t ? Math.min(1, Math.max(0, (t - a.t) / (b.t - a.t))) : 0;
      return [0, 1, 2, 3].map(k => a.c[k] + (b.c[k] - a.c[k]) * f); };
    return [colour(lo), colour(hi), ...stops.filter(s => s.t > lo && s.t < hi).map(s => s.c)];
  };
  const name = el => el.tagName.toLowerCase()
    + (typeof el.className === 'string' && el.className.trim() ? '.' + el.className.trim().split(/\s+/).join('.') : '');
  const path = el => { const out = []; for (let e = el; e && e !== document.body && out.length < 3; e = e.parentElement) out.unshift(name(e)); return out.join(' > '); };
  const bad = new Map(), unread = new Set();
  const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let node; (node = walk.nextNode());) {
    const el = node.parentElement;
    if (!node.textContent.trim() || el.closest('script, style, svg, [hidden], [aria-hidden="true"], :disabled')) continue;
    const range = document.createRange(); range.selectNodeContents(node);
    const rects = [...range.getClientRects()].filter(r => r.width && r.height);
    const cs = getComputedStyle(el);
    if (!rects.length || cs.visibility !== 'visible') continue;
    const text = {left: Math.min(...rects.map(r => r.left)), right: Math.max(...rects.map(r => r.right)),
                  top: Math.min(...rects.map(r => r.top)), bottom: Math.max(...rects.map(r => r.bottom))};
    let fg = rgba(cs.color), opacity = 1;
    for (let e = el; e; e = e.parentElement) opacity *= parseFloat(getComputedStyle(e).opacity);
    if (!opacity) continue;
    fg = [fg[0], fg[1], fg[2], fg[3] * opacity];
    // What the text sits on: every background from its element up to the first opaque one.
    const layers = []; let opaque = false;
    for (let e = el; e && !opaque; e = e.parentElement) {
      const s = getComputedStyle(e);
      const bg = rgba(s.backgroundColor);
      if (s.backgroundImage !== 'none') {
        const g = gradient(s.backgroundImage, e.getBoundingClientRect(), text);
        if (!g) { unread.add(name(e) + ': ' + s.backgroundImage.slice(0, 60)); break; }
        layers.push(g); opaque = g.every(c => c[3] === 1);
      }
      if (!opaque && bg && bg[3] > 0) { layers.push([bg]); opaque = bg[3] === 1; }
    }
    let grounds = [[255, 255, 255, 1]];
    for (const layer of layers.reverse()) grounds = grounds.flatMap(g => layer.map(c => over(c, g)));
    const worst = Math.min(...grounds.map(g => ratio(over(fg, g), g)));
    const size = parseFloat(cs.fontSize), large = size >= 24 || (size >= 18.66 && parseInt(cs.fontWeight) >= 700);
    const need = large ? 3 : 4.5;
    if (worst < need) {
      const key = path(el) + ' [' + cs.color + ']';
      if (!bad.has(key) || bad.get(key)[0] > worst) bad.set(key, [Math.round(worst * 100) / 100, need, node.textContent.trim().slice(0, 30)]);
    }
  }
  return {bad: [...bad].map(([k, v]) => [k, ...v]).sort(), unread: [...unread]};
}"""


@unittest.skipUnless(sync_playwright or os.environ.get("CI"), "playwright not installed (CI installs it)")
class DashboardRenderedContrastTest(unittest.TestCase):
    """A11Y-2, the class in the browser: text nobody measured against what it sits on. The sea band
    is dark in both themes, so its foam text tokens are not themed and the stylesheet test skipped
    them: the report's eyebrows (--foam-3, 2.6–3.1:1 on the gradient's light top), the live page's
    eyebrow (2.9:1) and stepper labels (4.0:1). Both pages, English and Spanish, light and dark, at
    320 / 768 / 1280 px, every section open, with the sea band in each of its states (the current
    stage waiting for review, in progress, every gate approved): every text node reaches AA."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)

    def test_A11Y_2_every_text_the_browser_draws_reaches_AA_on_what_it_sits_on(self):
        DashboardLayoutTest.project(self)  # every slot filled, a backlog, reports, a pending decision
        dashboard = load_dashboard()
        order = dashboard.GATES["project"]
        pages = {}
        for state in ("review", "current", "building"):
            gates = order if state == "building" else order[:-1]
            (self.root / ".keelokit/state.toml").write_text(
                "[gates]\n" + "".join(f'{g} = "2026-09-20"\n' for g in gates))
            s = dashboard.collect(self.root)
            if state == "current":
                s["stages"][-1]["status"] = "current"
            self.assertEqual(s["stages"][-1]["status"], "done" if state == "building" else state)
            for lang in ("en", "es"):
                for name, html in (("report", dashboard.render(s, lang, True, self.root, "0.7.1")),
                                   ("dashboard", dashboard.ops_page(s["name"], lang, dashboard.render_ops(
                                       s, lang, True, self.root, "0.7.1"), True)[0])):
                    out = self.root / f"{name}-{state}-{lang}.html"
                    out.write_text(html, encoding="utf-8")
                    pages[f"{name} {state} {lang}"] = out.as_uri()
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for name, uri in pages.items():
                for scheme in ("light", "dark"):
                    for width in (320, 768, 1280):
                        with self.subTest(page=name, scheme=scheme, width=width):
                            page = browser.new_page(viewport={"width": width, "height": 900}, color_scheme=scheme)
                            page.goto(uri)
                            page.evaluate("document.querySelectorAll('details').forEach(d => d.open = true)")
                            got = page.evaluate(CONTRAST_JS)
                            page.close()
                            self.assertEqual(got["unread"], [], "a background the contrast check can't read")
                            self.assertEqual(got["bad"], [], "text below WCAG AA on what it sits on")
            browser.close()


if __name__ == "__main__":
    unittest.main()
