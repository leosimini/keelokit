"""UX-2: the gate that wants captures and a critique with every interface change.
Run: python3 -m unittest discover -s tests"""
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

GATE = Path(__file__).resolve().parents[1] / "template/.keelokit/bin/ux_gate.py"
DOCTOR = Path(__file__).resolve().parents[1] / "template/.keelokit/bin/doctor.py"
CRITIQUE = "# Design critique\nok\n## Consistency and coherence\nok\n## Real device\nok\n"


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

    def test_doctor_turns_a_failure_into_an_error(self):
        self.write(".keelokit/bin/doctor.py", DOCTOR.read_text())
        self.write("apps/web/src/home.tsx", "export const a = 1\n")
        self.commit("feat: home")
        out = sh(self.root, "python3", ".keelokit/bin/doctor.py").stdout
        self.assertIn("UX-2: ux-gate:", out)
        self.assertIn("ERROR", out)


if __name__ == "__main__":
    unittest.main()
