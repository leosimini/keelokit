"""The plugin's workflows load and run the way Claude Code expects. Run: python3 -m unittest discover -s tests

A workflow is plain JavaScript: `export const meta = {...}` first, as a pure literal (anything else
drops it from the / menu), then a body with top-level await that can't read the clock or randomness
(a relaunched run must repeat the same agent calls) and can't import modules."""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((ROOT / "workflows").glob("*.js"))
META = re.compile(r"\Aexport const meta = (\{.*?\n\})\n", re.S)
STRING = re.compile(r"'(?:[^'\\\n]|\\.)*'")


def split(path):
    text = path.read_text()
    m = META.match(text)
    if not m:
        raise AssertionError(f"{path.name}: must start with `export const meta = {{` and close it with `}}` on its own line")
    return m.group(1), text[m.end():]


def meta_of(path):
    """The meta literal as data, refusing anything but quoted strings, keys, numbers and brackets."""
    literal, _ = split(path)
    strings = []
    bare = STRING.sub(lambda s: strings.append(s.group(0)) or f"\0{len(strings) - 1}\0", literal)
    leftover = re.sub(r"\0\d+\0|\b[A-Za-z_]\w*\s*:|-?\d+(\.\d+)?|\btrue\b|\bfalse\b|\bnull\b|[{}\[\],\s]", "", bare)
    if leftover:
        raise AssertionError(f"{path.name}: meta must be a pure literal, found {leftover!r}")
    as_json = re.sub(r"\b([A-Za-z_]\w*)\s*:", r'"\1":', bare)
    as_json = re.sub(r",(\s*[}\]])", r"\1", as_json)
    as_json = re.sub(r"\0(\d+)\0", lambda m: json.dumps(strings[int(m.group(1))][1:-1].replace("\\'", "'")), as_json)
    return json.loads(as_json)


class WorkflowsTest(unittest.TestCase):
    def test_there_are_workflows(self):
        self.assertTrue(WORKFLOWS)

    def test_meta(self):
        for path in WORKFLOWS:
            with self.subTest(path.name):
                meta = meta_of(path)
                self.assertEqual(meta["name"], path.stem, "invoked as /keelokit:<meta.name>; keep the file name the same")
                self.assertRegex(meta["name"], r"^[a-z][a-z-]*[a-z]$")
                self.assertTrue(meta["description"])
                self.assertNotRegex(meta["description"], r"<[^>]+>", "claude.ai's upload rejects tag-like text")
                _, body = split(path)
                called = re.findall(r"\bphase\('([^']+)'\)|phase: '([^']+)'", body)
                used = {a or b for a, b in called}
                listed = [p["title"] for p in meta.get("phases", [])]
                self.assertEqual(set(listed), used, "every phase used has its entry in meta.phases, and back")

    def test_body_is_replayable(self):
        for path in WORKFLOWS:
            with self.subTest(path.name):
                _, body = split(path)
                code = re.sub(r"//[^\n]*", "", body)
                for banned in (r"Date\.now\(", r"Math\.random\(", r"new Date\(\s*\)", r"\bimport\s*\(", r"\brequire\s*\("):
                    self.assertNotRegex(code, banned)

    def test_body_parses(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        for path in WORKFLOWS:
            with self.subTest(path.name):
                _, body = split(path)
                check = ("const AsyncFunction = (async () => {}).constructor;"
                         "new AsyncFunction('agent','parallel','pipeline','phase','log','args','budget','workflow',"
                         "require('fs').readFileSync(0, 'utf8'));")
                run = subprocess.run([node, "-e", check], input=body, capture_output=True, text=True)
                self.assertEqual(run.returncode, 0, run.stderr)

    def test_skills_name_existing_workflows(self):
        names = {p.stem for p in WORKFLOWS}
        for skill in ROOT.glob("skills/*/SKILL.md"):
            for name in re.findall(r"keelokit:([a-z-]+-flow)\b", skill.read_text()):
                with self.subTest(skill=skill.parent.name, workflow=name):
                    self.assertIn(name, names)


if __name__ == "__main__":
    unittest.main()
