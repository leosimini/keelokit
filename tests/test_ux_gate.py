"""UX-3: the gate that wants captures and a critique with every interface change.
Run: python3 -m unittest discover -s tests"""
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

GATE = Path(__file__).resolve().parents[1] / "template/.keelokit/bin/ux_gate.py"
DOCTOR = Path(__file__).resolve().parents[1] / "template/.keelokit/bin/doctor.py"
FOUR = "# Journey\nok\n# Design critique\nok\n## Consistency and coherence\nok\n## Real device\nok\n"
SKILLS = ("design:design-critique", "design:ux-copy", "design:accessibility-review")


def skills_section(skills=SKILLS, findings=None, ran="Ran: 2026-11-23"):
    """A `## Skills` section with one `### <skill id>` subsection per skill (FLEET-004)."""
    findings = findings or {}
    out = "## Skills\n"
    for s in skills:
        out += f"### {s}\n{ran}\n" + "".join(f"- {f}\n" for f in findings.get(s, [])) + "\n"
    return out


CRITIQUE = FOUR + skills_section()


def sh(cwd, *cmd):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


class UxGateTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.write(".keelokit/bin/ux_gate.py", GATE.read_text())
        self.write(".keelokit/profile.toml", 'kind = "web-product"\ntraits = ["ui", "web"]\n')
        self.write(".keelokit/ux.toml", '[gate]\nsurfaces = ["desktop"]\nthemes = ["light"]\n[gate.widths]\ndesktop = [1280]\n')
        self.write("apps/web/src/home.tsx", "export {}\n")
        for cmd in (("init", "-q", "-b", "main"), ("config", "user.email", "t@e.x"), ("config", "user.name", "T")):
            sh(self.root, "git", *cmd)
        self.commit("base")
        sh(self.root, "git", "checkout", "-qb", "feature")

    def tearDown(self):
        shutil.rmtree(self.root)

    def write(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(text))

    def commit(self, msg):
        sh(self.root, "git", "add", "-A")
        sh(self.root, "git", "commit", "-qm", msg, "--allow-empty")

    def gate(self):
        r = sh(self.root, "python3", ".keelokit/bin/ux_gate.py")
        return r.returncode, r.stdout + r.stderr

    def evidence(self, piece="home", capture=True, critique=CRITIQUE):
        if capture:
            self.write(f"docs/design/captures/{piece}/desktop-1280-light-default.png", "png")
        if critique is not None:
            self.write(f"docs/design/captures/{piece}/CRITIQUE.md", critique)

    def test_ui_change_without_evidence_fails(self):
        self.write("apps/web/src/home.tsx", "export const a = 1\n")
        self.commit("feat: home")
        code, out = self.gate()
        self.assertEqual(code, 1)
        self.assertIn("nothing under docs/design/captures/", out)

    def test_ui_change_with_captures_and_critique_passes(self):
        self.write("apps/web/src/home.tsx", "export const a = 1\n")
        self.evidence()
        self.commit("feat: home")
        code, out = self.gate()
        self.assertEqual((code, "1 piece(s)" in out), (0, True), out)

    def test_missing_capture_names_it(self):
        self.write("apps/web/src/home.tsx", "export const a = 1\n")
        self.evidence(capture=False)
        self.write("docs/design/captures/home/desktop-1440-light-default.png", "x")
        self.commit("feat: home")
        code, out = self.gate()
        self.assertEqual(code, 1)
        self.assertIn("no capture desktop-1280-light-<state>.png", out)

    def test_critique_must_exist_and_have_its_sections(self):
        self.write("apps/web/src/home.tsx", "export const a = 1\n")
        self.evidence(critique="# Design critique\nok\n")
        self.commit("feat: home")
        code, out = self.gate()
        self.assertEqual(code, 1)
        self.assertIn('lacks the section "Consistency and coherence"', out)
        self.assertIn('lacks the section "Real device"', out)

    def test_missing_critique_file_fails(self):
        self.write("apps/web/src/home.tsx", "export const a = 1\n")
        self.evidence(critique=None)
        self.commit("feat: home")
        code, out = self.gate()
        self.assertEqual(code, 1)
        self.assertIn("CRITIQUE.md missing or empty", out)

    def test_exception_passes_and_says_so(self):
        self.write("apps/web/src/home.tsx", "export const a = 1\n")
        self.commit("refactor: rename\n\nux-gate: n/a — pure rename, no visual change")
        code, out = self.gate()
        self.assertEqual(code, 0)
        self.assertIn("n/a — pure rename, no visual change", out)

    def test_exception_without_reason_does_not_count(self):
        self.write("apps/web/src/home.tsx", "export const a = 1\n")
        self.commit("refactor\n\nux-gate: n/a")
        self.assertEqual(self.gate()[0], 1)

    def test_no_ui_change_is_left_alone(self):
        self.write("apps/api/src/x.ts", "export {}\n")
        self.write("apps/web/src/home.test.tsx", "export {}\n")
        self.write("docs/notes.md", "x\n")
        self.commit("feat: api")
        code, out = self.gate()
        self.assertEqual((code, "no interface files changed" in out), (0, True), out)

    def test_project_without_ui_is_not_asked(self):
        self.write(".keelokit/profile.toml", 'kind = "api-service"\ntraits = ["api"]\n')
        (self.root / ".keelokit/ux.toml").unlink()
        self.write("apps/web/src/home.tsx", "export const a = 1\n")
        self.commit("feat")
        code, out = self.gate()
        self.assertEqual((code, "not applicable" in out), (0, True), out)

    def test_configured_matrix_is_enforced(self):
        self.write(".keelokit/ux.toml", '[gate]\nsurfaces = ["mobile"]\nthemes = ["light", "dark"]\n[gate.widths]\nmobile = [360, 390]\n')
        self.write("apps/web/src/home.tsx", "export const a = 1\n")
        self.write("docs/design/captures/home/mobile-360-light-default.png", "x")
        self.evidence(capture=False)
        self.commit("feat")
        code, out = self.gate()
        self.assertEqual(code, 1)
        for want in ("mobile-360-dark", "mobile-390-light", "mobile-390-dark"):
            self.assertIn(f"no capture {want}-<state>", out)
        self.assertNotIn("no capture mobile-360-light", out)

    def test_evidence_must_be_committed(self):
        self.write("apps/web/src/home.tsx", "export const a = 1\n")
        self.commit("feat: home")
        self.evidence()  # on disk, not committed: CI would not see it
        self.write("docs/design/captures/home/x.txt", "x")
        sh(self.root, "git", "add", "docs/design/captures/home/x.txt")
        sh(self.root, "git", "commit", "-qm", "docs: notes")  # only the staged file
        code, out = self.gate()
        self.assertEqual(code, 1, out)

    def test_names_with_spaces_and_uppercase_config(self):
        self.write(".keelokit/ux.toml", '[gate]\nsurfaces = ["Desktop"]\nthemes = ["Light"]\n[gate.widths]\nDesktop = [1280]\n')
        self.write("apps/web/src/my page.tsx", "export {}\n")
        self.evidence()
        self.commit("feat")
        code, out = self.gate()
        self.assertEqual(code, 0, out)  # the space in the path and the capitals in the config are fine

    def test_before_captures_do_not_fill_the_matrix(self):
        self.write("apps/web/src/home.tsx", "export const a = 1\n")
        self.evidence(capture=False)
        self.write("docs/design/captures/home/before/desktop-1280-light-default.png", "x")
        self.commit("feat")
        code, out = self.gate()
        self.assertEqual(code, 1, out)
        self.assertIn("no capture desktop-1280-light", out)

    def test_critique_needs_the_journey(self):
        self.write("apps/web/src/home.tsx", "export const a = 1\n")
        self.evidence(critique="# Design critique\nok\n## Consistency and coherence\nok\n## Real device\nok\n")
        self.commit("feat")
        code, out = self.gate()
        self.assertEqual(code, 1)
        self.assertIn('lacks the section "Journey"', out)

    def test_doctor_turns_a_failure_into_an_error(self):
        self.write(".keelokit/bin/doctor.py", DOCTOR.read_text())
        self.write("apps/web/src/home.tsx", "export const a = 1\n")
        self.commit("feat: home")
        out = sh(self.root, "python3", ".keelokit/bin/doctor.py").stdout
        self.assertIn("UX-3: ux-gate:", out)
        self.assertIn("ERROR", out)

    # ── FLEET-004: the critique comes from the design skills ──

    def ui_change(self, critique):
        self.write("apps/web/src/home.tsx", "export const a = 1\n")
        self.evidence(critique=critique)
        self.commit("feat: home")
        return self.gate()

    def test_fleet_004_s1_no_skills_section_fails(self):
        """FLEET-004.S1: the four sections and no "## Skills" fail, naming the missing skills."""
        code, out = self.ui_change(FOUR)
        self.assertEqual(code, 1, out)
        self.assertIn('lacks the section "Skills"', out)
        for s in SKILLS:
            self.assertIn(s, out)

    def test_fleet_004_s2_a_missing_skill_fails_naming_it(self):
        """FLEET-004.S2: a Skills section without design:ux-copy fails naming it, and only it."""
        code, out = self.ui_change(FOUR + skills_section(("design:design-critique", "design:accessibility-review")))
        self.assertEqual(code, 1, out)
        self.assertIn('no "### design:ux-copy" subsection', out)
        self.assertNotIn("### design:design-critique", out)
        self.assertNotIn("### design:accessibility-review", out)

    def test_fleet_004_s3_an_open_p1_fails_naming_it(self):
        """FLEET-004.S3: a P1 neither fixed nor decided fails, naming the finding and its skill."""
        findings = {"design:ux-copy": ["P1 The refund amount is not shown before closing",
                                       "P2 Button says Submit — fixed in a1b2c3d",
                                       "P3 Title could be shorter"]}
        code, out = self.ui_change(FOUR + skills_section(findings=findings))
        self.assertEqual(code, 1, out)
        self.assertIn("design:ux-copy", out)
        self.assertIn("P1 The refund amount is not shown before closing", out)
        self.assertNotIn("Button says Submit", out)  # fixed
        self.assertNotIn("Title could be shorter", out)  # a P3 needs no decision

    def test_fleet_004_s3_an_open_p2_and_a_resolution_mid_line_fail(self):
        """FLEET-004.S3: a P2 open fails too, and "fixed in" must end the item, not sit in its middle."""
        findings = {"design:design-critique": ["P2 Two tab bars in Settings",
                                               "P1 Says fixed in the title — but nothing was done"],
                    "design:accessibility-review": ["P2 Contrast — fixed in"]}
        code, out = self.ui_change(FOUR + skills_section(findings=findings))
        self.assertEqual(code, 1, out)
        self.assertIn("P2 Two tab bars in Settings", out)
        self.assertIn("P1 Says fixed in the title", out)
        self.assertIn("P2 Contrast", out)  # "fixed in" with nothing after it names nothing

    def test_fleet_004_s3_an_undated_skill_fails(self):
        """FLEET-004.S3: each subsection says when the skill ran (`Ran: YYYY-MM-DD`, a real date)."""
        code, out = self.ui_change(FOUR + skills_section(ran="Ran: soon"))
        self.assertEqual(code, 1, out)
        self.assertIn('design:ux-copy: no "Ran: YYYY-MM-DD" line', out)
        code, out = self.ui_change(FOUR + skills_section(ran="Ran: 2026-13-40"))
        self.assertEqual(code, 1, out)
        self.assertIn("Ran: YYYY-MM-DD", out)

    def test_fleet_004_s4_a_complete_section_passes(self):
        """FLEET-004.S4: three dated subsections, every P1 and P2 fixed or decided, pass."""
        findings = {"design:design-critique": ["P1 Refund amount missing — fixed in apps/web/src/close.tsx",
                                               "P2 Two tab bars — decided: one bar, the latest critique wins"],
                    "design:ux-copy": ["P2 Vague CTA — fixed in 4f5e6d7", "P3 Shorter title"],
                    "design:accessibility-review": []}
        code, out = self.ui_change(FOUR + skills_section(findings=findings))
        self.assertEqual(code, 0, out)
        self.assertIn("1 piece(s)", out)

    def test_fleet_004_s4_subsections_end_at_the_next_heading(self):
        """FLEET-004.S4: a subsection is read up to the next heading: a heading after the Skills
        section, or a skill named only in another skill's text, does not count as its subsection."""
        text = FOUR + "## Skills\n### design:design-critique\nRan: 2026-11-23\nsee design:ux-copy\n" \
               "### design:accessibility-review\nRan: 2026-11-23\n## Notes\n### design:ux-copy\nRan: 2026-11-23\n"
        code, out = self.ui_change(text)
        self.assertEqual(code, 1, out)
        self.assertIn('no "### design:ux-copy" subsection', out)

    def test_fleet_004_s5_the_projects_list_rules(self):
        """FLEET-004.S5: critique_skills = ["design:design-critique"] requires only that subsection;
        an empty list requires no Skills section at all."""
        base = '[gate]\nsurfaces = ["desktop"]\nthemes = ["light"]\n'
        self.write(".keelokit/ux.toml", base + 'critique_skills = ["design:design-critique"]\n[gate.widths]\ndesktop = [1280]\n')
        code, out = self.ui_change(FOUR + skills_section(("design:design-critique",)))
        self.assertEqual(code, 0, out)
        self.write(".keelokit/ux.toml", base + 'critique_skills = []\n[gate.widths]\ndesktop = [1280]\n')
        self.write("apps/web/src/home.tsx", "export const a = 2\n")
        self.evidence(critique=FOUR)
        self.commit("feat: home again")
        code, out = self.gate()
        self.assertEqual(code, 0, out)

    def test_fleet_004_s5_without_the_key_the_defaults_apply(self):
        """FLEET-004.S5: an adopted project whose ux.toml lacks critique_skills gets the three defaults."""
        out = sh(self.root, "python3", ".keelokit/bin/ux_gate.py", "--config").stdout
        self.assertIn("critique_skills = " + str(list(SKILLS)), out)

    def test_fleet_004_s5_the_shipped_ux_toml_lists_the_defaults(self):
        """FLEET-004.S5: template/.keelokit/ux.toml carries critique_skills with the three defaults."""
        import tomllib
        shipped = tomllib.loads((GATE.parents[1] / "ux.toml").read_text())["gate"]
        self.assertEqual(shipped["critique_skills"], list(SKILLS))

    def test_fleet_004_s6_na_still_passes_and_the_doctor_reports_it(self):
        """FLEET-004.S6: `ux-gate: n/a — <reason>` passes with no Skills section and the doctor warns."""
        self.write(".keelokit/bin/doctor.py", DOCTOR.read_text())
        self.write("apps/web/src/home.tsx", "export const a = 1\n")
        self.commit("refactor: rename\n\nux-gate: n/a — pure rename, no visual change")
        code, out = self.gate()
        self.assertEqual(code, 0, out)
        self.assertIn("n/a — pure rename", out)
        doc = sh(self.root, "python3", ".keelokit/bin/doctor.py").stdout
        self.assertIn("UX-3: ux-gate: n/a — pure rename", doc)


if __name__ == "__main__":
    unittest.main()
