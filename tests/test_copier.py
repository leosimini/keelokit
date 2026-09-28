"""copier.yml's questions accept what a user can type. Run: python3 -m unittest discover -s tests

Keelokit always runs copier with --defaults, so a computed default that fails its own validator
never gets a second prompt: copier exits with a traceback. project_slug was derived by dropping
everything outside [a-z0-9], so "3D Store" gave a slug starting with a digit, which the validator
rejects, and "Peña" gave "pe-a" (DX-4, DX-5). These cases render every computed default with
copier's own Jinja for names of every kind, and run every `copier copy` the skills document with
the names that broke it. They need uv (CI's unit job installs it); without it they skip locally."""
import json
import os
import re
import shutil
import subprocess
import tempfile
import unicodedata
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COPIER = "copier==9.18.2"  # the version every skill and scripts/test-template.sh run
UV = shutil.which("uv")

# Letters whose compatibility decomposition isn't an ASCII letter plus marks, spelled as their
# languages write them in ASCII (German, Nordic, Icelandic, Polish, Croatian, Maltese, Turkish...).
SPELLED = {"ß": "ss", "æ": "ae", "œ": "oe", "þ": "th", "ĳ": "ij", "ð": "d", "đ": "d", "ø": "o",
           "ħ": "h", "ı": "i", "ĸ": "k", "ŀ": "l", "ł": "l", "ŉ": "n", "ŋ": "n", "ŧ": "t"}
# The Latin letters of Western, Central and Northern Europe: Latin-1 Supplement, Latin
# Extended-A and the Romanian comma-below letters of Latin Extended-B.
LATIN = [chr(cp) for cp in [*range(0xC0, 0x180), 0x218, 0x219, 0x21A, 0x21B] if chr(cp).isalpha()]

# Names people give products: digit-led, punctuation only, empty after cleaning, non-Latin scripts,
# emoji, decomposed accents (macOS file names), odd whitespace, very long.
NAMES = [
    "Acme", "3D Store", "24/7 Clinic", "7-Eleven", "1", "2024", "0xCafe", "Peña S.A.", "Café Olé",
    "Größe", "Łódź Kebab", "Ærø Ferries", "İstanbul Çay", "Pen\u0303a", "東京", "Москва", "مطعم",
    "🚀 Rocket", "🚀", "!!!", "---", " ", "\t\n", "_", "a", "Z", "x" * 300, "-3D-", "Ǆemal",
    "Ångström Lab", "Straße 42", "Ḃlog", "Việt Nam",
]


def run_uv(code, payload):
    """Runs `code` in a Python that has copier, with `payload` as JSON on stdin; returns its JSON."""
    out = subprocess.run(
        [UV, "run", "--quiet", "--no-project", "--with", COPIER, "python", "-c", code],
        input=json.dumps(payload), capture_output=True, text=True, cwd=tempfile.gettempdir(),
    )
    if out.returncode != 0:
        raise AssertionError(f"copier probe failed:\n{out.stderr[-3000:]}")
    return json.loads(out.stdout)


# Renders every question's computed default with the Jinja environment copier builds for this
# template (its filters and options), then that question's validator on the result.
PROBE = r'''
import json, sys, tempfile, warnings
import yaml
from copier._main import Worker
warnings.simplefilter("ignore")
req = json.load(sys.stdin)
env = Worker(src_path=req["root"], dst_path=tempfile.mkdtemp(), vcs_ref="HEAD", defaults=True).jinja_env
questions = {k: v for k, v in yaml.safe_load(open(req["root"] + "/copier.yml")).items()
             if not k.startswith("_") and isinstance(v, dict)}
static = {k: v.get("default") for k, v in questions.items() if "{{" not in str(v.get("default", ""))}
free = [k for k, v in questions.items() if v.get("type") == "str" and not v.get("choices")
        and "{{" not in str(v.get("default", ""))]
computed = {k: (env.from_string(v["default"]), env.from_string(v.get("validator", "")))
            for k, v in questions.items() if "{{" in str(v.get("default", ""))}
out = []
for name in req["names"]:
    ctx = {**static, **{k: name for k in free}}
    for key, (default, validator) in computed.items():
        value = default.render(**ctx)
        error = validator.render(**{**ctx, key: value}).strip()
        out.append({"name": name, "question": key, "default": value, "error": error})
print(json.dumps({"free": free, "results": out}))
'''


def fold(letter):
    """What a Latin letter should become in a slug: its ASCII base, or how its language spells it."""
    letter = letter.lower()
    base = "".join(c for c in unicodedata.normalize("NFKD", letter) if not unicodedata.combining(c))
    if re.fullmatch(r"[a-z]+", base):
        return base
    return SPELLED.get(letter) or SPELLED[base[0]]


def cased(letters):
    """Each letter as typed in either case (ß's and ŉ's upper cases are two letters, left out)."""
    return sorted({v for c in letters for v in (c, c.lower(), c.upper()) if len(v) == 1})


def uv_or_skip(test):
    if not UV:
        if os.environ.get("CI"):
            test.fail("uv not installed; CI's unit job needs astral-sh/setup-uv")
        test.skipTest("uv not installed")


class ComputedDefaultsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not UV:
            cls.probe = None
            return
        # Every Latin letter, upper and lower, between two letters; every character of the Basic
        # Multilingual Plane's first 0x3000 code points alone and after a digit.
        latin = [f"x{c}x" for c in cased(LATIN)]
        every = [chr(cp) for cp in range(0x20, 0x3000) if not 0xD800 <= cp <= 0xDFFF]
        cls.names = NAMES + latin + every + ["9" + c for c in every]
        cls.probe = run_uv(PROBE, {"root": str(ROOT), "names": cls.names})
        cls.slug = {r["name"]: r["default"] for r in cls.probe["results"] if r["question"] == "project_slug"}

    def setUp(self):
        uv_or_skip(self)

    def test_DX_4_every_computed_default_passes_its_own_validator(self):
        self.assertIn("project_name", self.probe["free"])
        failing = [(r["question"], r["name"], r["default"], r["error"]) for r in self.probe["results"] if r["error"]]
        self.assertEqual(failing[:10], [], f"{len(failing)} names get a computed default its validator rejects, "
                         "which crashes `copier copy --defaults`: (question, name, default, error)")

    def test_DX_4_digit_led_and_empty_names_get_a_slug_that_starts_with_a_letter(self):
        self.assertEqual(self.slug["3D Store"], "app-3d-store")
        self.assertEqual(self.slug["24/7 Clinic"], "app-24-7-clinic")
        self.assertEqual(self.slug["-3D-"], "app-3d")
        self.assertEqual(self.slug["東京"], "app")
        self.assertEqual(self.slug["!!!"], "app")
        self.assertEqual(self.slug["Acme"], "acme")

    def test_DX_5_latin_letters_fold_to_their_ascii_spelling(self):
        self.assertEqual(self.slug["Peña S.A."], "pena-s-a")
        self.assertEqual(self.slug["Pen\u0303a"], "pena")
        self.assertEqual(self.slug["Straße 42"], "strasse-42")
        self.assertEqual(self.slug["Łódź Kebab"], "lodz-kebab")
        wrong = {}
        for letter in cased(LATIN):
            got, want = self.slug[f"x{letter}x"], f"x{fold(letter)}x"
            if got != want:
                wrong[letter] = (got, want)
        self.assertEqual(wrong, {}, "letter: (slug, expected)")


def documented_copies():
    """Every `copier copy` command in a skill's bash block, continuation lines joined."""
    found = []
    for path in sorted(ROOT.glob("skills/*/SKILL.md")):
        for block in re.findall(r"```bash\n(.*?)```", path.read_text(), re.S):
            for command in block.replace("\\\n", " ").splitlines():
                if re.search(r"\bcopier(==\S+)?\s+copy\b", command):
                    found.append((path.relative_to(ROOT).as_posix(), " ".join(command.split())))
    return found


class DocumentedCopyTest(unittest.TestCase):
    def test_DX_4_every_documented_copier_copy_works_for_any_name(self):
        """What an agent runs: the skill's command with its placeholders filled. A placeholder the
        agent has to derive (a slug) is where a wrong value crashes copier, so copier derives it."""
        uv_or_skip(self)
        copies = documented_copies()
        self.assertTrue(any(p.startswith("skills/project-new/") for p, _ in copies))
        self.assertTrue(any(p.startswith("skills/project-adopt/") for p, _ in copies))
        fills = {
            "v<version>": "HEAD",
            '"${KEELOKIT_TEMPLATE:-gh:leosimini/keelokit}"': "\"$SRC\"",
            "<folder>": "\"$DST\"",
            "<one sentence>": "What it does",
        }
        for path, command in copies:
            for name in ["3D Store", "Peña S.A.", "東京"]:
                filled = command.replace("<name>", name.replace('"', '\\"'))
                for placeholder, value in fills.items():
                    filled = filled.replace(placeholder, value)
                left = re.findall(r"<[^>]+>", filled)
                self.assertEqual(left, [], f"{path}: a placeholder copier doesn't check before it runs: {command}")
                with self.subTest(path=path, name=name), tempfile.TemporaryDirectory() as tmp:
                    dst = Path(tmp, "product")
                    dst.mkdir()
                    env = {**os.environ, "SRC": str(ROOT), "DST": str(dst)}
                    out = subprocess.run(["bash", "-c", filled], cwd=dst, env=env, capture_output=True, text=True)
                    self.assertEqual(out.returncode, 0, f"{path}: {filled}\n{out.stderr[-2000:]}")
                    answers = (dst / ".keelokit/answers.yml").read_text()
                    slug = re.search(r"(?m)^project_slug: (\S+)$", answers).group(1)
                    self.assertRegex(slug, r"^[a-z][a-z0-9-]*$")


if __name__ == "__main__":
    unittest.main()
