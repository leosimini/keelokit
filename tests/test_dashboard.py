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
        html = Path(out).read_text()
        self.assert_links_land(html)
        return html

    def assert_links_land(self, html: str) -> None:
        """UX-1: every page a test renders goes through here (see dead_links)."""
        self.assertEqual(dead_links(html), [], "in-page links with nothing to land on")

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
                "blocked": [("B-001", '"Z-999"')], "done": [("C-001", "")], "no_main": [("A-001", ""), ("A-002", '"A-001"')]}
        for sid, dep in deps[stories]:
            files[f"backlog/stories/{sid}-x.md"] = STORY.format(id=sid, epic=sid[0], title=f"t {sid}", wave=1, deps=dep, body="")
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
        n = 0
        for layout, order in dashboard.GATES.items():
            for stories in ("none", "mixed", "blocked", "done", "no_main"):
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
    "scope": ["skills/project-new/references/prd-template.md", "workflows/check-bugbash-flow.js"],
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
        tables = {"T", "STAGES", "GLOSSARY", "HEADINGS"}
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
