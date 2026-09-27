"""Every file in the repo has a plain path. Run: python3 -m unittest discover -s tests

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


if __name__ == "__main__":
    unittest.main()
