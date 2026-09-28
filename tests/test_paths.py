"""Every file has a plain path and every description is plain text. Run: python3 -m unittest discover -s tests

claude.ai's plugin upload rejects a zip whose paths carry characters like {, %, ' or spaces, so the
template's conditions live in copier.yml's _exclude, never in file names."""
import json
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

    def test_CPY_4_the_manifests_describe_the_plugin_one_way_without_tags(self):
        """CPY-4: marketplace.json's plugin entry and plugin.json described Keelokit with different
        sentences, and no test read either. Every description in both manifests is plain text, and
        the plugin's entry says what plugin.json says."""
        plugin = json.loads((ROOT / ".claude-plugin/plugin.json").read_text())
        market = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text())

        def descriptions(node):
            if isinstance(node, dict):
                yield from ([node["description"]] if isinstance(node.get("description"), str) else [])
                for value in node.values():
                    yield from descriptions(value)
            elif isinstance(node, list):
                for value in node:
                    yield from descriptions(value)

        for text in [*descriptions(plugin), *descriptions(market)]:
            with self.subTest(text=text[:40]):
                self.assertNotRegex(text, r"<[^>]+>")
        entry = next(p for p in market["plugins"] if p["name"] == plugin["name"])
        self.assertEqual(entry["description"], plugin["description"])


if __name__ == "__main__":
    unittest.main()
