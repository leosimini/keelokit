"""Keelokit's own CI stays in step with its releases. Run: python3 -m unittest discover -s tests

docs/releasing.md step 6 is a manual edit after a release: when the release changed the template,
CI's "update from" row must move to the new tag, so the next release tests the upgrade users will
actually run. Nothing made that edit happen: after 0.7.1, which renamed dozens of template files,
main kept upgrading from 0.7.0 (DOC-2). This test fails until the row is moved, on
main, in every pull request, and in scripts/release.sh, which runs these tests before a release."""
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CI = ROOT / ".github/workflows/ci.yml"
# What `copier copy`/`copier update` read from a tag: the template and its questions and tasks.
TEMPLATE = ["template", "copier.yml"]
TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


def git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True)


def release_tags():
    """The release tags main has already passed, oldest first. A tag on HEAD itself is left out:
    that is the release commit, and step 6 can only come in a commit after it."""
    listed = git("tag", "--merged", "HEAD", "--list", "v*")
    if listed.returncode != 0:
        return []
    head = git("rev-parse", "HEAD").stdout.strip()
    tags = []
    for tag in listed.stdout.split():
        m = TAG.match(tag)
        if m and git("rev-parse", f"{tag}^{{commit}}").stdout.strip() != head:
            tags.append((tuple(map(int, m.groups())), tag))
    return [tag for _, tag in sorted(tags)]


class UpdateFromRowTest(unittest.TestCase):
    def update_from_rows(self):
        text = CI.read_text()
        rows = [line for line in text.splitlines() if re.match(r"\s*- \{.*--update-from", line)]
        self.assertEqual(len(rows), 1, f"{CI.name}: expected one `--update-from` row in the template matrix, found {rows}")
        row = rows[0]
        flag = re.search(r"--update-from\s+(v\S+?)\b['\"}\s]", row + " ")
        name = re.search(r"name:\s*update from\s+(v[\d.]+\d)", row)
        self.assertTrue(flag and name, f"{CI.name}: can't read the tag of {row.strip()!r}")
        self.assertEqual(name.group(1), flag.group(1), f"{CI.name}: the row's name and its --update-from tag differ")
        return flag.group(1)

    def test_DOC_2_update_from_row_names_the_last_release_that_changed_the_template(self):
        tags = release_tags()
        if not tags:
            if os.environ.get("CI"):
                self.fail("no release tags in this checkout; CI's unit job needs `fetch-depth: 0`")
            self.skipTest("no release tags in this checkout (a shallow clone)")
        row = self.update_from_rows()
        self.assertIn(row, tags, f"{CI.name}: `--update-from {row}` is not a release tag main has passed")
        latest = tags[-1]
        # Every release after the row's tag must ship the same template; otherwise CI tests an
        # upgrade from a template nobody installs any more, and skips the one users run.
        changed = [
            tag for tag in tags[tags.index(row) + 1:]
            if git("diff", "--quiet", row, tag, "--", *TEMPLATE).returncode != 0
        ]
        self.assertFalse(
            changed,
            f"{', '.join(changed)} changed the template since {row}: point the \"update from\" row of "
            f".github/workflows/ci.yml at {latest} "
            "(docs/releasing.md, Cutting a release, step 6)",
        )

    def test_DOC_2_unit_job_sees_the_tags(self):
        text = CI.read_text()
        job = re.search(r"\n  unit:\n(.*?)(?=\n  \w[\w-]*:\n)", text, re.S)
        self.assertTrue(job, "ci.yml has no `unit` job")
        self.assertRegex(job.group(1), r"uses: actions/checkout@[^\n]*\n\s+with:\n(\s+[\w-]+:[^\n]*\n)*?\s+fetch-depth: 0",
                         "the unit job's checkout is shallow, so this test can't see the release tags; add `fetch-depth: 0`")


# Every shell check that looks a release's version up in CHANGELOG.md: a `grep` on CHANGELOG.md
# whose pattern uses $version, in any tracked workflow, template workflow or script (found, not
# listed). ship-release and scripts/release.sh write the heading as "## X.Y.Z — <date>[ — title]".
VERSION_GREP = re.compile(r"\bgrep\b[^|;()\n]*\$\{?version\b[^|;()\n]*\bCHANGELOG\.md\b")
ENTRY = "## {v} — 2026-10-14"
# (version, CHANGELOG headings, has its own entry)
CASES = [
    ("0.7.1", ["## Unreleased", ENTRY.format(v="0.7.1"), ENTRY.format(v="0.7.0")], True),
    ("0.7.1", [ENTRY.format(v="0.7.1") + " — Faster bookings"], True),
    ("1.3.0", [ENTRY.format(v="1.3.1"), ENTRY.format(v="1.3.0")], True),
    ("0.7.1", ["## Unreleased", ENTRY.format(v="0.7.0")], False),
    ("0.7.1", [ENTRY.format(v="0.7.10")], False),
    ("0.7.1", [ENTRY.format(v="0.7.100")], False),
    ("0.7.1", [ENTRY.format(v="0.7.1-rc.1")], False),
    ("0.7.1", [ENTRY.format(v="0.7.1.1")], False),
    ("1.2.3", [ENTRY.format(v="1.2.30"), ENTRY.format(v="1.2.3-beta")], False),
    ("0.7.1", ["### " + ENTRY.format(v="0.7.1")[3:], "- fixed in " + ENTRY.format(v="0.7.1")], False),
]


def version_greps():
    found = []
    for name in git("ls-files").stdout.splitlines():
        if not re.search(r"(^|/)(\.github/workflows/[^/]+|scripts/[^/]+)$", name):
            continue
        for number, line in enumerate((ROOT / name).read_text().splitlines(), 1):
            found += [(f"{name}:{number}", m.group(0)) for m in VERSION_GREP.finditer(line)]
    return found


class ChangelogEntryCheckTest(unittest.TestCase):
    def test_PKG_101_changelog_entry_check_matches_the_whole_version(self):
        """REL-1 / INV-001: a tag vX.Y.Z passes only if CHANGELOG.md has the entry of X.Y.Z itself.
        Each check runs for real against CHANGELOGs where only a longer version sharing its digits
        (0.7.10, 0.7.1-rc.1, ...) has an entry, which a prefix match takes for the tag's own."""
        bash = shutil.which("bash")
        if not bash:
            self.skipTest("bash not installed")
        greps = version_greps()
        where = {w.split(":")[0] for w, _ in greps}
        for release in (".github/workflows/release.yml", "template/.github/workflows/release.yml.jinja"):
            self.assertIn(release, where, f"no CHANGELOG entry check found in {release}; update VERSION_GREP")
        with tempfile.TemporaryDirectory() as tmp:
            for location, command in greps:
                for version, headings, has_entry in CASES:
                    with self.subTest(location, version=version, changelog=headings):
                        Path(tmp, "CHANGELOG.md").write_text("# Changelog\n\n" + "\n\n- a change\n\n".join(headings) + "\n")
                        run = subprocess.run([bash, "-c", f"set -u; version={version}; {command} >/dev/null"],
                                             cwd=tmp, capture_output=True, text=True)
                        self.assertIn(run.returncode, (0, 1), f"{location}: `{command}` failed: {run.stderr}")
                        self.assertEqual(run.returncode == 0, has_entry,
                                         f"{location}: `{command}` for v{version} " +
                                         ("missed its entry" if has_entry else "took another version's entry for its own"))


if __name__ == "__main__":
    unittest.main()
