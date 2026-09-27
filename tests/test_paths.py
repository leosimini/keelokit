"""Every file has a plain path and every description is plain text. Run: python3 -m unittest discover -s tests

claude.ai's plugin upload rejects a zip whose paths carry characters like {, %, ' or spaces, so the
template's conditions live in copier.yml's _exclude, never in file names."""
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAFE = re.compile(r"^[A-Za-z0-9._/@+-]+$")


class PathsTest(unittest.TestCase):
    def test_every_tracked_path_is_plain(self):
        files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split("\n")
        unsafe = [f for f in files if f and not SAFE.match(f)]
        self.assertEqual(unsafe, [], "rename these; put the condition in copier.yml's _exclude")


    def test_descriptions_have_no_tags(self):
        """claude.ai's upload rejects a skill or agent whose description has anything like <idea>."""
        tagged = []
        for path in [*ROOT.glob("skills/*/SKILL.md"), *ROOT.glob("agents/*.md")]:
            m = re.search(r"(?m)^description:(.*)$", path.read_text())
            if m and re.search(r"<[^>]+>", m.group(1)):
                tagged.append(path.relative_to(ROOT).as_posix())
        self.assertEqual(tagged, [])


if __name__ == "__main__":
    unittest.main()
