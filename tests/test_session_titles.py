"""HARN-014: a session's canonical title, `status.py title`, which build-story, coordinate and Harbor use.

`<project> · <wave|ola> <n> · <ID>` for a story, `<project> · <coordinator|coordinador>` for the
coordinator: the project from .keelokit/answers.yml, the wave from the story's front matter, the words
from [dashboard] lang. Anything it can't find is exit 2 with the reason, never a made-up title.

Run: python3 -m unittest discover -s tests"""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

STATUS = Path(__file__).resolve().parents[1] / "template/.keelokit/bin/status.py"
STORY = '+++\nid = "{id}"\nepic = "AUTH"\ntitle = "t"\n{wave}touches = []\n+++\nScenario: [S1] works\n'


class TitleTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        self.write(".keelokit/bin/status.py", STATUS.read_text())
        self.write(".keelokit/answers.yml", "# Written by Copier\n_commit: v0.11.1\nmode: project\nproject_name: Demo\n"
                                            "project_slug: demo\n")
        self.write("backlog/stories/AUTH-003-sign-up.md", STORY.format(id="AUTH-003", wave="wave = 2\n"))

    def write(self, rel, text):
        (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
        (self.root / rel).write_text(text, encoding="utf-8")

    def title(self, *args):
        return subprocess.run([sys.executable, ".keelokit/bin/status.py", "title", *args], cwd=self.root,
                              capture_output=True, text=True)

    def ok(self, *args):
        r = self.title(*args)
        self.assertEqual((r.returncode, r.stderr), (0, ""), r.stdout)
        return r.stdout.rstrip("\n")

    def refused(self, *args):
        r = self.title(*args)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertEqual(r.stdout, "", "no title, not even a guessed one")
        return r.stderr

    def test_HARN_014_S1_a_story_title_in_english_without_a_dashboard_language(self):
        self.assertEqual(self.ok("AUTH-003"), "Demo · wave 2 · AUTH-003")
        self.write(".keelokit/state.toml", '[gates]\nintake = "2026-11-02"\n')  # a state.toml with no [dashboard]
        self.assertEqual(self.ok("AUTH-003"), "Demo · wave 2 · AUTH-003")
        self.write(".keelokit/state.toml", '[dashboard]\nlang = "en"\n')
        self.assertEqual(self.ok("AUTH-003"), "Demo · wave 2 · AUTH-003")

    def test_HARN_014_S2_a_story_title_in_spanish(self):
        for lang in ("es", "es-AR"):
            with self.subTest(lang=lang):
                self.write(".keelokit/state.toml", f'[dashboard]\nlang = "{lang}"\n')
                self.assertEqual(self.ok("AUTH-003"), "Demo · ola 2 · AUTH-003")

    def test_HARN_014_S3_the_coordinator_title(self):
        self.assertEqual(self.ok("--role", "coordinator"), "Demo · coordinator")
        self.write(".keelokit/state.toml", '[dashboard]\nlang = "es"\n')
        self.assertEqual(self.ok("--role", "coordinator"), "Demo · coordinador")
        self.assertIn("unknown role", self.refused("AUTH-003", "--role", "builder"))

    def test_HARN_014_S4_an_unknown_id_is_exit_2_with_the_reason(self):
        self.assertIn("no story AUTH-999 in backlog/stories", self.refused("AUTH-999"))
        self.assertIn("usage", self.refused())

    def test_HARN_014_S5_a_story_without_a_wave_is_exit_2_with_the_reason(self):
        self.write("backlog/stories/AUTH-004-x.md", STORY.format(id="AUTH-004", wave=""))
        self.assertIn("story AUTH-004 (AUTH-004-x.md) has no wave", self.refused("AUTH-004"))
        self.write("backlog/stories/AUTH-005-x.md", STORY.format(id="AUTH-005", wave='wave = "2"\n'))
        self.assertIn("has no wave", self.refused("AUTH-005"))

    def test_HARN_014_S6_the_project_name_as_copier_writes_it(self):
        """Unicode as is, single quotes with '' for a quote, folded over indented lines when long: what
        copier 9.18.2 wrote for these names."""
        for written, name in [
            ("project_name: Peña S.A.\n", "Peña S.A."),
            ("project_name: '3D Store: it''s \"new\"'\n", '3D Store: it\'s "new"'),
            ("project_name: 'Long name Long name Long name\n    Long name '\n", "Long name Long name Long name Long name"),
            ('project_name: "Pe\\xF1a \\"x\\""\n', 'Peña "x"'),
        ]:
            with self.subTest(written=written):
                self.write(".keelokit/answers.yml", f"mode: project\n{written}project_slug: x\n")
                self.assertEqual(self.ok("AUTH-003"), f"{name} · wave 2 · AUTH-003")
        self.write(".keelokit/answers.yml", "mode: project\nproject_slug: x\n")
        self.assertIn("no project_name in .keelokit/answers.yml", self.refused("AUTH-003"))
        self.assertIn("no project_name", self.refused("--role", "coordinator"))


if __name__ == "__main__":
    unittest.main()
