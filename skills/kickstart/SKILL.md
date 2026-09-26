---
name: kickstart
description: Start a new product from zero with the Keelokit harness — intake interview, PRD, stack decision, monorepo skeleton with CI and staging from day 1, and the first backlog. Use when the user says "nuevo producto", "arrancar un proyecto", "kickstart", "quiero construir <idea>", "armá el proyecto", "new product", or when /keelokit finds no project and the user wants one. Resumes from the pending gate when .keelokit/state.toml exists.
---

# Kickstart — five gates from idea to a working skeleton

| Gate | Output | Human |
|---|---|---|
| 1 intake | `docs/context/` | approves the context |
| 2 product | `docs/prd.md` | approves scope and metrics |
| 3 stack | apps chosen; `docs/decisions/` only for deviations | approves deviations |
| 4 skeleton | generated monorepo, `pnpm verify` green, first commit | nothing (unless setup needs their accounts) |
| 5 backlog | `backlog/` with epics, stories, waves | approves the order |

Rules for the whole run:
- Interview in the user's language; write files in English unless the user asks otherwise.
- After each approval, record it in `.keelokit/state.toml` under `[gates]` as
  `<gate> = "<YYYY-MM-DD>"` (create the file if needed). That file only records human approvals.
- Between gates report progress in one line and continue; stop only at the approvals above.
- Resume: if `.keelokit/state.toml` exists, continue from the first gate without a date.

## 0. Where

Ask for the product's name and one sentence of what it is, and propose the folder
`~/Development/<slug>`. Create it (empty) once the user agrees. If it exists and is not empty,
ask before using it.

## 1. Intake

Run `/keelokit:intake` in the new folder. When it finishes, show the gap summary and ask for
approval. Blocking gaps can stay open only if the user explicitly accepts them.

## 2. Product (PRD)

Write `docs/prd.md` from the context using `references/prd-template.md`. Every metric has a
number and a date; every scope line is either in or out. Anything the context doesn't support
becomes a gap in `docs/context/gaps.md`, not an assumption. Ask for approval.

## 3. Stack

The house stack is fixed (`${CLAUDE_PLUGIN_ROOT}/template/.keelokit/harness/stack.md`). Decide
only:
- **apps** — any of `api`, `web`, `mobile`, `site`, justified from the PRD's users and channels;
- **postgis** — only if the domain has geospatial queries.
If a requirement truly can't be met by the house stack, write `docs/decisions/0001-<title>.md`
(Status, Context, Decision, Consequences) and get approval. "Would be nicer" is not a reason.

## 4. Skeleton

1. Template source: `$KEELOKIT_TEMPLATE` if set (a fork: `gh:<you>/keelokit`), otherwise
   `gh:leosimini/keelokit`, at the plugin's version tag (`v` + `version` from
   `${CLAUDE_PLUGIN_ROOT}/.claude-plugin/plugin.json`). If git can't reach it (offline), use
   `${CLAUDE_PLUGIN_ROOT}` and warn that the project can't `/keelokit:upgrade` until its
   `.keelokit/answers.yml` `_src_path` points at a git source.
2. Generate into the product folder (existing `docs/` is kept):
   ```bash
   uvx copier==9.18.2 copy --defaults --vcs-ref v<version> \
     --data project_name="<name>" --data project_slug="<slug>" \
     --data description="<one sentence>" --data 'apps=["api","web"]' --data postgis=false \
     "${KEELOKIT_TEMPLATE:-gh:leosimini/keelokit}" <folder>
   ```
3. `git init -b main`, `pnpm install`, then `pnpm verify`. Fix until green — the fix belongs in
   the generated project only if it is product-specific; if the template itself is wrong, say
   so: it must be fixed in Keelokit.
4. First commit: `chore: skeleton from Keelokit v<version>`.
5. Ask whether to create a private GitHub repo (`gh repo create <slug> --private --source . --push`).
6. Staging: the API deploys to Fly.io from CI. The Fly account, `fly auth login`, secrets and the
   `FLY_API_TOKEN` GitHub secret are the user's — walk them through the README's Deploy section;
   never type credentials yourself. Record the gate even if staging setup is deferred, and add a
   non-blocking gap "staging not configured" (owner: user).

## 5. Backlog

Run `/keelokit:backlog`. Ask for approval of the epics and the wave order.

## Close

Report in five lines: what exists, `pnpm verify` status, open gaps by owner, the first ready
story, and what needs the user (accounts, approvals).
