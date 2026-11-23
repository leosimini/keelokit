# ui

### UI-1 · A long story/epic id overflows its flex row and forces a page-wide horizontal scroll at the 320 px width the dashboard is meant to support (P2)
- **Persona / context:** Any persona reading the dashboard on a phone (320 px, the narrowest width `dimensions.md`'s `ui` row and `skills/project-dashboard/references/design.md` promise: "1160 px wrap, 16 px gutter" that is meant to degrade gracefully). Standalone and Artifact-fragment mode, light and dark, es and en — the bug is theme- and mode-independent since it is a layout/CSS issue, not a data or copy issue. Sha 19b332e.
- **Steps:**
  1. `git clone /home/user/keelokit $SCRATCH/keelokit` (sha 19b332e).
  2. Built a fixture repo (`$SCRATCH/fixture`) with a normal `docs/context/`, `docs/prd.md`, `.keelokit/state.toml` (all gates approved) and a `backlog/stories/` containing one story whose id is longer than a typical `EPIC-NNN` id: `INFRAESTRUCTURA-DE-PAGOS-RECURRENTES-001` (epic ids are only specified as "a short uppercase word" in `skills/plan-backlog/SKILL.md:14`, so nothing caps their length; a founder's Spanish capability name compounded into a slug easily reaches this length).
  3. `python3 $SCRATCH/keelokit/skills/project-dashboard/scripts/dashboard.py --root $SCRATCH/fixture --lang es --standalone --out $SCRATCH/out/standalone_es.html`
  4. Opened the page in Chromium (Playwright) at `viewport 320×1000`, expanded every `<details>`, and measured `document.documentElement.scrollWidth` vs `clientWidth`.
- **Expected:** At 320 px the page has no horizontal scroll — `dimensions.md`'s `ui` row lists `320 / 768 / 1280 widths` as the three widths the dashboard must work at, and `design.md`'s layout section describes a fluid `.wrap{width:min(100% - 32px,1160px)}` meant to fit down to phone width with nothing left unhandled.
- **Observed:** `document.documentElement.scrollWidth` is `363` against a `clientWidth` of `320` (43 px of page-wide horizontal scroll) whenever a story with a long id is on the page, in every combination tested (standalone/artifact fragment × es/en × light/dark). Walking the DOM for the first non-scroll-contained element whose `getBoundingClientRect().right` exceeds the viewport finds exactly one candidate: `<span class="sid">INFRAESTRUCTURA-DE-PAGOS-RECURRENTES-001</span>`, `right: 363, width: 313`. The id text does not wrap or truncate — it renders on one unbroken mono-font line 313 px wide inside a `flex-wrap:wrap` summary row, but the span itself is `flex:none` (`.sid{...flex:none}` — no `min-width:0`/`overflow-wrap`), so the row is allowed to wrap around it but the id's own box cannot shrink, and it is the one element on the whole page that overflows the 320 px viewport and drags the entire `<html>` into horizontal scroll (every table on the page that is wider than 320 px — the Environments/Gaps/Stack tables — is correctly contained in a `.scroll{overflow-x:auto}` wrapper and does **not** cause page-level scroll; only the `.sid` span does, because it has no such containment).
- **Evidence:**
  ```
  $ python3 shoot.py  # Playwright, viewport 320×1000, standalone_es, light
  standalone_es    light   320  docScrollW=  363 clientW=  320 bodyScrollW=  363 HSCROLL
  standalone_es    dark    320  docScrollW=  363 clientW=  320 bodyScrollW=  363 HSCROLL
  artifact_es      light   320  docScrollW=  363 clientW=  320 bodyScrollW=  363 HSCROLL
  artifact_es      dark    320  docScrollW=  363 clientW=  320 bodyScrollW=  363 HSCROLL
  (768 px and 1280 px runs of the same page: docScrollW == clientW, no scroll)

  $ python3 find_overflow3.py  # elements overflowing 320px, excluding anything under a .scroll ancestor
  {'tag': 'SPAN', 'cls': 'sid', 'right': 363, 'width': 313, 'text': 'INFRAESTRUCTURA-DE-PAGOS-RECURRENTES-001'}
  {'tag': 'CODE', 'cls': '', 'right': 324, 'width': 14, 'text': '["api","web"]'}          # 4px, cosmetic, same root cause class
  {'tag': 'CODE', 'cls': '', 'right': 324, 'width': 14, 'text': '04f7428 context, prd...'} # 4px, cosmetic, same root cause class
  ```
  Screenshot of the overflowing row cut off at the right edge of a 320 px viewport (`sid_overflow_320.png`, cropped to the story's `<summary>`): the id `INFRAESTRUCTURA-DE-PAGOS-RECU` is visibly truncated by the viewport edge with no ellipsis, no wrap, and the rest of the id (`RRENTES-001`) only reachable by scrolling the whole page sideways.
- **Where:** `skills/project-dashboard/scripts/dashboard.py:1248` — `details.story .sid{font:13px var(--mono);color:var(--ink-2);flex:none}`, rendered from `story_row()` at `skills/project-dashboard/scripts/dashboard.py:1516`. Same root cause, smaller (4 px) manifestation on the inline `<code>` chips used for `apps` and commit hashes (no `code{overflow-wrap}` rule in the CSS block starting at `skills/project-dashboard/scripts/dashboard.py:1097`).
- **Root cause (probable):** `.sid` is pinned `flex:none` with no `max-width`, `overflow-wrap: anywhere` or truncation, so a mono-font id longer than the 320 px content width cannot shrink or wrap and instead sets the intrinsic width of its flex row past the viewport, which (unlike the tables, which are all wrapped in `.scroll`) is not contained and so pushes `<html>`'s scroll width past `clientWidth`.
- **Class:** other (layout/CSS containment)
- **Should have been caught by:** `dimensions.md`'s `ui` row: "UI-1 lint" (an automatic, every-commit/CI check for the 320/768/1280 widths) and the bug-bash lens itself ("Screenshots per viewport × theme") — there is no such lint wired up against `skills/project-dashboard/scripts/dashboard.py`'s own output (this script has no test coverage at all; `tests/` only covers `guard.py`/`doctor.py`), so a 320 px regression in the dashboard's own markup has no automatic backstop.
- **Proposed fix:** Give `.sid` `overflow-wrap: anywhere; min-width: 0` (dropping `flex:none` in favour of e.g. `flex: 0 1 auto`) so a long id wraps onto a second line inside its own box instead of forcing the row past the viewport; add the same `overflow-wrap` to the bare `code{...}` rule for the 4 px chip case.

### UI-2 · Story rows carry duplicate DOM ids (one per "by wave" / "by epic" view), so a direct link to `#story-<ID>` silently lands on nothing when the hidden view holds the first match (P3)
- **Persona / context:** Any persona who bookmarks, shares, or otherwise opens the dashboard with a `#story-<ID>` fragment while the segmented "by epic" view is the one remembered in `localStorage` (`keelokit-backlog-view`) — e.g. someone switched to "Por épica" last session, then a teammate sends them a link straight to a specific story. Sha 19b332e.
- **Steps:**
  1. Same fixture as UI-1 (`backlog/stories/PAY-001.md` etc.), `standalone_es.html`, viewport 1280×1000 (desktop — this is not a width-specific bug).
  2. Expanded all `<details>`, then `page.evaluate(() => document.querySelectorAll('#story-PAY-001'))` — confirms two elements share the id `story-PAY-001`: one inside `<div data-view="wave">…</div>` (rendered first), one inside `<div data-view="epic" hidden>…</div>` (rendered second) — `skills/project-dashboard/scripts/dashboard.py:1555` renders both `by_wave` and `by_epic` unconditionally, each calling `story_row()` (which sets `id="story-{id}"`) for every story.
  3. Clicked the "Por épica" segmented button (`data-show="epic"`), which the page's own `show()` handler (`skills/project-dashboard/scripts/dashboard.py:1340`) implements by toggling the `hidden` attribute on the two `[data-view]` containers — the wave view's container becomes `hidden`, the epic view's becomes visible.
  4. Ran `location.hash = '#story-PAY-001'` (equivalent to opening `dashboard.html#story-PAY-001`, or clicking any in-page `href="#story-PAY-001"` link, both routed through the same `reveal()` function at `skills/project-dashboard/scripts/dashboard.py:1345`) and inspected the element `document.getElementById('story-PAY-001')` actually resolves to.
- **Expected:** `design.md`'s Layout/behaviour section: "Links to a section open it." A link or hash to a specific story should reveal that story regardless of which of the two equivalent groupings ("Por ola" / "Por épica") is currently showing.
- **Observed:** `getElementById('story-PAY-001')` — which both the browser's native `:target`/hash scrolling and the page's own `reveal()` helper use — always resolves to the **first** matching node in document order, i.e. the copy inside the wave view, even when the wave view is the one currently `hidden`. `reveal()` (`skills/project-dashboard/scripts/dashboard.py:1345-1347`) walks up from that node opening any `<details>` ancestor, but it never clears `hidden` on a `[data-view]` ancestor — so after switching to "Por épica" and then jumping to `#story-PAY-001`, the browser scrolls to a node whose bounding box is `{top: 0, all zero}` (it is inside a `display:none` subtree) and nothing visibly happens: no scroll, no opened card, no error. The story is only reachable by manually switching back to "Por ola" or scrolling to find the (correctly visible) second copy by eye.
- **Evidence:**
  ```
  $ python3 test_anchor.py
  story-PAY-001 occurrences: [{'hiddenAncestor': True, 'open': True}, {'hiddenAncestor': False, 'open': True}]
  after hash nav, first #story-PAY-001: {'inViewport': True, 'top': 0, 'hiddenAncestor': True, 'open': True}
  ```
  (`top: 0` / a trivially "in viewport" rect is exactly the zeroed rect Chromium reports for an element inside a `display:none` ancestor — i.e. `getElementById` picked the invisible copy.)
- **Where:** `skills/project-dashboard/scripts/dashboard.py:1516` (`story_row()` sets `id="story-{esc(st['id'])}"` with no view-scoping) and `:1555` (`backlog_block()` renders `by_wave` and `by_epic` — each a full second copy of every story row — into the DOM at the same time); the click/hash router at `:1348-1350` relies on `getElementById`, which cannot distinguish the two copies.
- **Root cause (probable):** The "by wave / by epic" segmented control was built by rendering both full groupings into the DOM and hiding one with CSS/`hidden`, rather than rendering one grouping and re-grouping the same nodes (or scoping the ids per view, e.g. `story-wave-PAY-001` / `story-epic-PAY-001`) — so every story id is duplicated in the document, which is invalid HTML (ids must be unique) and makes `getElementById`/`:target`-based navigation pick whichever copy happens to come first, independent of which one is visible.
- **Class:** consistency
- **Should have been caught by:** `dimensions.md`'s `ui` row ("UI-1 lint") would catch this if it validated markup (duplicate ids are a standard HTML-validity lint rule); no such lint runs against `dashboard.py`'s generated output today.
- **Proposed fix:** Suffix the id by view (`story-wave-{id}` / `story-epic-{id}`) and have `reveal()` prefer the currently-visible copy (e.g. query `#story-wave-{id}:not([hidden] *), #story-epic-{id}:not([hidden] *)`), or simpler: keep one DOM copy of each story and re-parent/re-sort it into the active grouping instead of rendering two.

### UI-3 · The sea band's "waiting for review" pill uses a bare hex colour with no backing token, breaking the "tokens only" rule the `ui` dimension is meant to enforce (P3)
- **Persona / context:** Any persona, any stage that is `review` (ready to approve but not yet approved) — e.g. right after `/keelokit:plan-backlog` finishes and before the founder approves the Backlog gate. Standalone, es, light theme, 1280 px (theme/width-independent — this is a colour-authoring issue, not a responsive one). Sha 19b332e.
- **Steps:**
  1. Same fixture as UI-1, but with `backlog = "2026-08-05"` removed from `[gates]` in `.keelokit/state.toml` so the Backlog stage is `review` (ready evidence present, gate not yet approved) — the same state a project is in right after `/keelokit:plan-backlog` and before the founder says "apruebo".
  2. `python3 dashboard.py --root $SCRATCH/fixture2 --lang es --standalone --out standalone_es_review.html`
  3. Rendered in Chromium, located `.sea .pill.review` (the "Para revisar" pill next to "Etapa actual: Backlog" in the sea band) and read `getComputedStyle(el).color`.
- **Expected:** `design.md`'s Colour section states the palette is "unchanged" and lists a fixed set of named colours (foam/ink/sea/board/foil/reef, etc.) that every status colour is drawn from; the dashboard's own CSS backs every other themed colour with a `:root` custom property (`--attn`, `--board`, `--reef`, …) so it can vary correctly between light and dark. The sibling rules right next to this one, `.sea .pill.current` and `.sea .pill.done`, both use `var(--board)` / `var(--reef)`.
- **Observed:** `.sea .pill.review{color:#FFC08A;background:rgba(238,123,36,.2)}` is a bare literal hex colour, not `var(--attn)` (which the non-`.sea` `.pill.review` rule two lines above correctly uses) and not any other named custom property — `getComputedStyle` confirms `rgb(255, 192, 138)` is actually painted. It doesn't match any token in `:root`'s dark-mode block either (`--attn` dark is `#FFAE6B`, `--foil` is `#EE7B24`): it's a fourth, one-off orange that exists only as this literal, invisible to anyone auditing the page's tokens and impossible to retheme without editing this one selector by hand.
- **Evidence:**
  ```
  $ grep -n "pill.review" skills/project-dashboard/scripts/dashboard.py
  1198:.pill.review{color:var(--attn);background:var(--attn-soft)}
  1203:.sea .pill.review{color:#FFC08A;background:rgba(238,123,36,.2)}

  $ python3 -c "playwright: pill.first.evaluate(el => getComputedStyle(el).color)"
  rgb(255, 192, 138)   # = #FFC08A, matches the literal exactly; not derived from --attn (#AD540F light / #FFAE6B dark)
  ```
  Screenshot `sea_review_pill_1280.png`: the "● Para revisar" pill next to "Etapa actual: Backlog" in the sea band, rendered in this off-token peach.
- **Where:** `skills/project-dashboard/scripts/dashboard.py:1203`.
- **Root cause (probable):** The `.sea` variants of the status pills were hand-tuned against the dark sea gradient for contrast and `--board`/`--reef` happened to already read correctly on that background, but `--attn`'s light-mode value (`#AD540F`, a dark rust meant for the *light* "foil tint" background) would be unreadable on the sea gradient, so a bespoke lighter orange was inlined instead of adding a themed token (e.g. a `--attn-on-sea` custom property) for it.
- **Class:** other (design-token consistency)
- **Should have been caught by:** `dimensions.md`'s `ui` row, "Tokens only" — the one thing the `ui` dimension's contract explicitly calls out before the width/theme requirements — and its "UI-1 lint" automatic check; no lint enforces "no bare hex outside `:root`" against this file today.
- **Proposed fix:** Add a themed custom property (e.g. `--attn-on-sea: #FFC08A` light / reuse `--attn` `#FFAE6B` dark if that already contrasts, verifying against the sea gradient) in both `:root` blocks and reference it from `.sea .pill.review`, instead of the inline literal.
