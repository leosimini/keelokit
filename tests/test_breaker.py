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
        self.close(repo, "AUTH-001")
        self.assertEqual(self.check(repo)[0], 1)
        repo.commit("docs: AUTH-001's rounds\n\nPart-of: AUTH-001",
                    {path_of("AUTH-001"): story("AUTH-001", touches=("scripts/verify.sh",),
                                                rounds=round_line(1, HEAD))})
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

    def test_HARN_021_S4_more_rounds_than_the_cap_need_a_decision(self):
        rounds = "".join(round_line(n, f"{n}" * 40, "1 finding · fixed") for n in (1, 2, 3)) + round_line(4, HEAD)
        self.assertEqual(self.run_rounds(rounds), [("warning", "BREAKER_UNRESOLVED", "AUTH-001")])
        rounds += "- Decision · Leo · 2026-11-25 · a fourth round, then land\n"
        self.assertEqual(self.run_rounds(rounds), [])

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
        repo = self.project(stories)
        first = self.close(repo, "AUTH-001")
        harness(repo, "chore: the rule from here\n\nNo-story: harness", {RISKY: f'since = "{first}"\n' + RISKY_TOML})
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
                                                                  rounds=round_line(1, HEAD))})
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
        self.close(repo, "AUTH-001", rounds=round_line(1, "abc1234"))
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
        self.assertFalse([c for c in calls if "--name-only" in c], calls)


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


if __name__ == "__main__":
    unittest.main()
