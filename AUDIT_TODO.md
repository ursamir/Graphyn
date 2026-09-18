# Professional-polish audit — full scope tracker

Rule for every item: read the full source, reload fresh, click through via the
UI (not guessed URLs), **scroll to the bottom of every section**, click **every**
button/link once to confirm it lands in the correct place or does the correct
thing, check state continuity (leave and come back), fix anything wrong or
sub-par, rebuild+redeploy+verify live. Add newly discovered issues back to this
list instead of fixing tangents mid-flow when they'd derail the current item.

Status legend: `[ ]` not started · `[~]` in progress · `[x]` done this pass

## Re-verify with full rigor (touched last pass, but not scrolled/click-tested exhaustively)
- [x] App shell — header, sidebar (all groups), command palette (run real actions — verified Models jump works), "?" shortcuts overlay (press every key). FOUND+FIXED: Models/Access had no keyboard jump-key at all (every other nav item did) and KeyboardHelp.tsx's Navigation list was a hand-duplicated copy of JUMP_KEYS that had silently drifted (missing Models+Access rows entirely). Unified into one source (routes/nav.ts), added m/c keys. Verified live: tooltips, overlay rows, and actual key-press navigation all correct now.
- [x] Home dashboard — Spec & metadata all 6 sub-tabs opened (Versions/Spec/Taxonomy/Contract/Snapshots/Diff) — all render sensibly, no defects. Project settings: Rename/Clone prefill verified intentional (not a bug — Clone gets "-copy" suffix, Rename prefills current name, both are deliberate per source). Did a full rename round-trip (renamed live project, verified sidebar+header+page title+doc title+URL all updated consistently, then renamed back) — continuity confirmed correct, transient "Loading…" during refetch is expected, not a bug.
- [x] Settings drawer, workspace switcher, mode explainer modal — all checked. Mode explainer shows correct Mode A copy + Got it/Mode B·Worker fleet buttons.
- [ ] Home dashboard at narrow viewport width (not yet checked — lower priority, note for next pass)
- [~] Editor — toolbar graph-name fix verified live earlier this round; still want: a pipeline with real staging/prod envs, 3+ different node inspector types, AgentDrawer, TriggersDock, Import/Export graph round-trip, execution log Raw toggle — not yet done this pass
- [x] Runs — Live tab (clean empty state, correct copy), Lineage tab (context breadcrumb, repro pack, per-node artifacts, upstream inputs — solid), Checkpoints tab (correct empty state for a non-training run). Compare-with-real-metrics still not done (no ML training run with metrics was at hand this pass) — minor, defer.

## Not yet audited at all
- [x] Templates — scrolled full ~30-card gallery (holds up structurally), tested search/filter tabs, "More" menu (Sync examples/Save from Editor), stamped a template end-to-end into Editor (correct: pipeline picker showed "not a saved pipeline", name field correct, toast correct). FOUND+FIXED: "..." → Delete on an EXAMPLE template used the same generic "Confirm delete" as a real saved pipeline, with no hint that examples are trivially restorable via "Sync examples" — now says so in the confirm label.
- [x] Agent inbox (Proposals) — created a real pending proposal, verified Accept→Editor (empty-state canvas correct, name/picker correct, pending badge correctly cleared — was briefly stale in one screenshot but confirmed that was just async timing, not a bug), created another and verified Reject (moves to Rejected filter correctly, toast correct). No issues found.
- [x] Datasets — Browse×Inputs (open link tested), Ingest tab, Merge tab all checked, forms look correct. FOUND+FIXED A REAL ONE: clicking "open" on any file (the core interaction on this whole page) opened the browser's bare native audio/image player in a new unbranded tab (window.open on a blob URL) — the only place in the app that did this; Runs → Run outputs already handles the identical case properly via the existing FileViewer component (audio player, image, JSON tree, download button, in an inline modal). Generalized FileViewer to take a `source: 'outputs'|'inputs'` prop (Datasets' Inputs library is a different jailed file API than run outputs) and switched Datasets to open files in that same modal. Verified live: an actual input .wav file now opens in-app with working playback, filename, download button, and close button — no more new-tab escape from the app.
- [x] Plugins — scrolled full 48-plugin list (Installed + Install/Search tabs), tested "..." menu (Dependencies/Disable/Uninstall), "Manage dependencies" expand. No issues found — genuinely solid.
- [x] Models — stage view, "Use in Ship" continuity fully re-verified (run_id carried through correctly, "Use edge template" loaded, model auto-pick resolved a real on-disk path, validated). No issues found.
- [x] Ship — Package wizard walked through Graph→Configure→Package run with real data end-to-end (auto-pick model, path verification, labels/optimizer/quantization/target all sensible defaults). Did not actually execute the packaging job (long-running, real TF/ONNX work) but the wizard UX itself is solid. Devices tab already confirmed as an honest stub in an earlier pass.
- [x] Worker fleet — Workers tab (control-plane/worker-start copy commands), Queue tab already fixed earlier this session (mtime bug). Copy-button click feedback couldn't be visually confirmed in this automated browser (clipboard permission is unreliable under CDP) — fixed anyway on the merits: added a checkmark-icon swap to CopyableMono (previously only a tooltip attribute changed, easy to miss), matching the visible-feedback pattern ErrorBanner's own copy button already uses.
- [x] Secrets — store/rotate-guard/delete flow fully tested with a real throwaway secret. Note: ConfirmButton's 4s auto-disarm window is shorter than my own tool round-trip latency — two separate tool calls looked like a stuck "Confirm delete", but batching both clicks into one call confirmed delete works correctly. (Testing artifact, not a product bug — worth remembering for any further ConfirmButton testing.)
- [x] Artifacts — re-clicked into a card, confirmed Run filter auto-scopes correctly, Lineage/Download/Open run/Replay/Editor/Copy path all present and consistent with earlier review. No new issues.
- [x] Ops — full Schedules lifecycle tested with a real schedule (create → shows ENABLED with correct next-run text → Disable → shows DISABLED/paused with correct button flip → Delete → gone, toast correct). Status/Webhooks/Cleanup/Audit already deep-audited earlier this session (Webhooks clear-bug fixed then). No new issues this pass.
- [x] Access — actor field persistence confirmed (via keyboard-shortcut test earlier this round), "API token & Settings" button correctly opens the same Settings modal (incl. this round's Content-layout relocation). No issues.

## Real bug class found by the user, then swept for systematically (not just the one instance)
User caught: Home → Spec & metadata → Versions tab showed a fully-enabled "Load stats" /
"Restore" toolbar even with zero versions — "Load stats" silently no-opped, "Restore" armed
into the literally-broken label "Restore ?" (empty interpolation). My first response only
grepped for the exact `confirmLabel={\`...\`}` syntax, which is too narrow — it wouldn't even
have caught "Load stats" itself (a plain button, not a ConfirmButton). Correctly called out for
that. Did a real sweep instead:
- Every `if (!x) return` early-guard in every feature view (22 files) + every shared
  components/layout/store file, cross-referenced against the button/control that triggers it —
  checked whether that control is `disabled`/conditionally-rendered to match the same guard.
- Every `<ConfirmButton>` usage in the codebase (16 total) — checked whether `onConfirm` can
  silently no-op in some reachable UI state.
- Every visible label/title with a template-literal interpolation, for the "renders as broken
  text" variant of the same bug.
Found 2 more real instances this way (both ProjectsView.tsx, same page): "Rename" and "Clone"
buttons had no `disabled` guard even though `rename()`/`clone()` silently no-op on an empty
field (these fields are pre-filled by default so it's a lower-frequency path than the Versions
one, but the same shape of bug). Fixed both, verified live. Everything else checked out safe —
either already properly disabled/gated, or a plain no-op with an actual toast/message (correct
pattern, e.g. TriggersDock's "Add schedule").
**What this does NOT cover** (being upfront rather than overclaiming again): this is one specific
bug *class* (dead/misleading controls under empty state), checked by static reading, solo, no
independent re-verification. It doesn't touch layout/visual bugs, backend edge cases, race
conditions, or anything outside this one pattern.

## Cross-link / transition pass on 3 screens the user flagged (picker → Home → Templates)
User asked specifically: how does cross-linking work today and how can it be better.
Mapped the actual link graph in source first, then fixed what it showed.

**Dead ends fixed (a page that knows where you'd want to go, but doesn't take you):**
- Templates card "Open Datasets" called `openData({ mode: 'inputs' })` with NO context,
  while the card was *displaying* the template's declared input path. Added
  `datasetInputLabel()` to derive the Datasets label from the path
  (`workspace/datasets/input/wake-word/wake_word` → `wake-word`) and pass it through.
  Verified live: the Call-analytics card's button now lands on Inputs with wake-word
  selected and its 406 files listed. Templates with no declared input keep the generic
  fallback. Button now shows the label, so you know where it goes before clicking.
- Home "Activity" had no exit at all — 8 rows, then nothing. Added "View all in Runs"
  (workspace-scoped) and "Browse artifacts".
- Home header stats "Pipelines N" / "Pinned inputs N" were dead text sitting beside a
  "Last run" link that *was* clickable — three identical-looking things, one interactive.
  All three now navigate; the two new ones scroll to and flash their card.

**Wrong destination fixed:**
- Home "Linked inputs" card (entirely about Datasets input labels) had "Browse Artifacts"
  as its header action, with the actual Datasets link buried as a tertiary button below
  the form. Swapped: header now goes to Datasets, Artifacts moved up to Activity where
  the runs that produce them live. Also deleted "Browse library", which opened the same
  Datasets view as the header link one row away.

**Duplicate controls for one referent:**
- Header rendered TWO adjacent chips for the same finished run: a bare outcome word
  ("Succeeded" — at what?) and the "Last <id>" menu. Outcome is now a coloured dot inside
  the run chip (+ tooltip + sr-only text); the standalone pill is kept only for in-flight
  runs and for a status with no run id yet.
- Home toolbar's "Last run" button was a third control for that same run on that same
  screen. Removed; the metrics-line entry carries more (status + id).

**Another instance of the known bug class (visible, enabled, does nothing):**
- With no project open, the header showed "Open workspace" whose handler navigates to the
  projects picker — i.e. the page you are already on. Hidden in that state.
- Project settings "Rename" was enabled when the field still held the current name.
  Now disabled with "That is already the current name"; same for Clone → own name.
- Picker "New" was enabled with an empty name field. Now disabled.

**Layout / professionalism on the same three screens:**
- Picker had two identically-styled bare text inputs stacked — one creates a project, one
  filters — distinguishable only by placeholder. Filter moved to its own block with the
  list it filters, given a search icon, and hidden entirely below 8 projects.
- Picker printed "DRAFT" on all 30 rows (every project is draft until changed), which is
  30 repetitions of no information. Badge now only renders for non-default statuses.
- Added Recent workspaces (localStorage, cap 5, filtered against projects that still
  exist) as a sidebar group and a "Jump back in" list on the welcome pane — returning to
  yesterday's work was previously a scan of 30 alphabetical rows.
- Welcome pane's only CTA was "Browse Datasets" — the one action its own step 1 does not
  ask for. Now: New project (primary) / Browse templates / Browse Datasets, step 1 links
  to the create field. Also corrected copy claiming Editor and Runs "appear in the
  activity bar once a workspace is open" — they are visibly present but disabled, so the
  sentence described something the user could see was false.
- Home's two bottom drawers (Spec & metadata, Project settings) were bare `border-t` rows
  on the page background while everything above was a white card — they read as page
  footer, which is exactly why the dead Versions toolbar survived the earlier audit.
  Both now have card chrome and say what's inside before you open them
  ("0 versions · 0 snapshots", current status).
- Project settings was one flat row: a status select, two prefilled text inputs whose only
  labels were `aria-label` (sighted users saw two identical boxes), and Delete in the same
  row as everything else. Now labelled rows + a separated danger zone whose copy states
  the verified deletion scope (checked against `ProjectManager.delete`: it rmtree's
  `workspace/datasets/output/{name}` only — `workspace/artifacts/{name}/runs` survives).
- Templates cards: the node list — the only content saying what a template *does* — was a
  comma-joined grey line at the card's bottom edge. Promoted to a visual `A › B › C` chain.
  Input/output chips showed `workspace/datasets/input/speec…`, i.e. 25 characters shared by
  every card with the differing part elided; now show the tail, full path still in `title`.
  "Unversioned" filler dropped. "Open" → "Open in Editor" (it was ambiguous about both the
  action and the destination), and both actions moved into one right-aligned group so the
  primary sits in the same place on every card — `ml-auto` on "Open" had been pushing it to
  the middle whenever the Datasets button rendered.
- Templates page header said templates "stamp GraphIR into a workspace" and never named
  which workspace. Now names the active one and says the original is left untouched.

Verified live on all three screens after rebuild+redeploy; tsc + oxlint clean; no console
errors. Same caveat as the section above: this is a targeted pass on three screens the
user pointed at, not a claim about the rest of the app.

**Noted, not fixed (low value, logged so it isn't re-chased):** Datasets URLs carry
`project=`/`version=` from the Outputs tab even while Inputs is showing, so the URL can
name a different workspace than the header. Inert (Inputs ignores them) and it does
preserve the Outputs selection across a share, so leaving it.

## Landing page rebuilt as a workspace management console + URL aliasing fixed
User asked why `localhost:5173` and `localhost:5173/workspaces` render the same page, and
for the landing page to be a real project-management surface.

**Why the two URLs looked identical — they were, plus more:** `parsePathname` returned
`{view:'projects'}` for `parts.length === 0` AND for its final unmatched fallback, and
nothing ever rewrote the address bar. So `/`, `/workspaces` and *any* nonsense path
(`/totally-made-up-path`, verified live) were all the same page under different URLs,
and whichever one you arrived on stayed there — bookmarks and shared links disagreed
about a single page's address. Added `ParsedPath.canonical`, set on the alias cases, and
an App effect that `replaceState`s onto it (not `navigatePath` — no popstate, so it
cannot re-enter the parse).

**Second, worse finding underneath it:** `/workspaces` could never actually be reached.
The mount effect treated `/` and `/workspaces` as one "bare picker" case and bounced you
into your stored workspace, so the console had a canonical address you could not navigate
to. Split them: `/` keeps "resume what I was doing", `/workspaces` means the console. The
entry pathname is captured during first render, before the canonicalisation effect can
rewrite `/`, or the distinction would be lost.

**Third, found while testing that:** landing on `/workspaces` calls `setActiveProject(null)`
(correct — the sidebar must say NO PROJECT OPEN), but `activeProject` was ALSO the app's
only memory of your last workspace. So one visit to the console permanently amnesia'd the
app: resume stopped working and the header's "Back to X" chip could never appear again.
Separated the two concerns into `lib/recentWorkspaces.ts` — a durable list that survives
the clear, kept honest on rename/delete via `forgetRecentWorkspace`. Verified all three
URLs live: `/workspaces` stays put with recents intact, `/` resumes into the workspace
with `activeProject` null, `/totally-made-up-path` canonicalises.

**Landing page:** was a 15.5rem column of 30 truncated names (each badged "DRAFT") beside
an empty welcome pane. Nothing told you which workspace had run, failed, or been touched
last — you opened them one at a time to find out. Two facts made a real console cheap:
GET /projects already returns `updated_at` + `versions` (all discarded), and the unscoped
GET /runs carries `project` per row. Two requests, no N+1. Now:
- Stat strip: Workspaces / Active / Failed runs / Last activity. "Failed runs" filters the
  activity feed rather than being a dead number; the others are plain stats, deliberately
  not fake buttons (there is no global Runs route to send them to).
- Workspace cards (or compact rows — toggle, persisted, as is the sort): name, Recent tag,
  status chip only when non-draft, last run as a coloured dot + graph name + relative time,
  and a meta line of run count / dataset versions / updated-ago.
- Last run links straight to that run — verified it lands on
  `/workspaces/<ws>/runs/<id>`, saving open-workspace → scan-activity → click. Uses the
  stretched-link pattern (title button's `::after` covers the card) so whole-card click and
  the inner controls coexist without nested buttons.
- Cross-workspace activity rail — previously there was NO way to see activity across
  projects without opening each one. Only runs tagged with a project are listed, because
  `openRun` with no workspace resolves to no path and silently does nothing; the untagged
  ones are counted out loud ("N runs not tagged … are hidden") rather than dropped.
- Per-card ⋯ menu: Open in Editor / View runs / Clone… / Delete. Clone→delete round-trip
  tested end to end live (30 → 31 → 30, no junk left).
- Create is a real labelled card, not a text box in a sidebar gutter; disabled until named.
tsc + oxlint clean, rebuilt, redeployed, no console errors. Note: `npx vitest` cannot run
in this environment (EACCES on node_modules/.vite-temp), so `legacyHash.test.ts` was not
executed — it does not reference `parsePathname`, which is the only routing function I
changed, but that is reasoning, not a green test run.

## Follow-up on the landing console (user-reported, from screenshots)
- **⋯ menu painted under the rows below it.** Every row's trigger sits in its own
  `relative` wrapper and they all shared `z-10`; at equal z-index later siblings win, so
  the open menu was overlapped by the wrappers of subsequent rows and their ⋯ buttons
  showed straight through it — the menu read as garbled. Fixed by raising the *open* row's
  wrapper above its siblings (`z-40` while open, `z-10` otherwise). The inner `z-30` was
  never the problem: it only ranked the menu inside its own wrapper's context.
- **Menu clipped by the bottom of the window.** On the last rows of a 30-workspace list it
  opened downwards off-screen and Clone/Delete were unreachable. Now measures the trigger
  on open and flips to `bottom-full` when the remaining viewport is under the menu height.
  Verified in both card and compact views on the final row: opens upwards, fully visible.
- **Activity rail scrolled away.** The workspace list is far taller than the rail, so the
  cross-workspace activity — the whole reason the rail exists — was only visible at the top
  of the page. Now `sticky` at xl and up.
- **`/` always opened the last project.** Removed the auto-resume entirely (it was in the
  legacy-hash effect). It meant the app had no landing page you could actually reach: every
  entry bounced past it into a workspace you may not have wanted, and typing a URL got you
  somewhere else. The console already surfaces recents (sorted recently-opened first, with
  a Recent tag), so returning to yesterday's work is one visible click rather than an
  invisible redirect. Verified: `/` → `/workspaces` showing the console, recents intact.

## Templates brought up to the same standard as the workspaces console
Same approach: find the data the page already fetches and throws away, then fix the
controls that don't lead anywhere.

**Discarded data, now used.** `/pipelines/templates` returns `tags` on all 30 templates
and `required_plugins` on all 30; the UI rendered neither and used them only as invisible
search-blob text. So a 30-card wall had no way to narrow to "the ASR ones" short of
guessing the right search word.
- Plugin facet bar (counts verified against the API: audio 17, segmenter 13, asr 9,
  augmentation 9, eval 8, pii 6 …), AND-combining, with a clear-filters escape.
- The plugin chips **on each card** are the same control — click `pii` on a card to see
  everything else that needs it. Verified live: 30 → 9 on `asr`, → 6 adding `pii` from a
  card chip, "Clear 2 filters" → 30.
- Facet counts are computed from the tab+search result, NOT the fully-filtered list —
  otherwise picking one plugin zeroes every other chip and you can never widen without
  clearing first.
- Tags now render on cards and seed a search on click.
- Sort by name / node count / plugin count (verified descending: 20, 10, 8, 8, 7).

**Dead rows and duplicated controls removed.**
- `Outputs: None declared` printed on 16 of 30 cards and `Inputs: None declared` on 5 —
  rows of nothing on most cards. Both now omitted (not CSS-hidden — not rendered, so they
  stay out of the accessibility tree). Verified 0 remaining in the DOM.
- The Datasets cross-link moved off the footer and onto the **Inputs chip itself**. As a
  footer button its label truncated to "speech-comma…" — a cross-link you couldn't read,
  restating a path already printed one row above. Verified: clicking the chip lands on
  Datasets with `label=wake-word`.
- Deleted `isDatasetRelatedTemplate()`: it keyword-matched a template's text to offer a
  context-free "Open Datasets" button even for templates declaring no input at all —
  exactly the unfiltered dump this pass set out to remove. A template with no declared
  input now simply doesn't offer a link it can't target.
- EXAMPLE badge suppressed while the Examples tab is active (it would print the same word
  on all 25 visible cards). Verified: 25 badges on All, 0 on Examples.

**Same two menu bugs as the workspaces console, pre-emptively fixed here:** the card ⋯ menu
now flips above the trigger near the window edge, with the threshold sized to the actual
menu (one Delete item vs. two with versions) rather than a fixed worst case.

**Toolbar is sticky** (search + tabs + sort + facets + count) — 30 cards is several screens
and the filters used to scroll away, so changing what you were looking at meant scrolling
back up. Deliberately opaque, not `backdrop-blur`: a full-width blur over a 30-card grid is
an expensive composite on every scroll frame.

Verified live, tsc + oxlint clean, no console errors. Testing note: the screenshot tool
wedged on one tab mid-session while `javascript_tool` kept working and the container served
200s throughout — it was the extension's capture path, not the app. A fresh tab recovered
it; don't misread that as a page hang.

## Sticky-toolbar bleed (user-reported) — and the same trap swept for app-wide
User's screenshot: card INPUTS/OUTPUTS rows scrolling through a strip ABOVE the Templates
filter bar. Measured rather than guessed:
`scrollportTop 56, barTop 80, gapAboveBar 24, parentPadTop 24px`, and `elementFromPoint`
just above the bar returned a card's node-chain div.

**Cause:** a sticky child's `top: 0` resolves against the scroll container's **padding
box**, not its border box. The container was `overflow-y-auto p-6`, so the bar pinned
exactly 24px — one `p-6` — below the visible top edge, leaving a window for content to
scroll through. My own change introduced this: the sticky bar was added without noticing
the container's padding.

**Fix:** move the top padding off the scroll container and onto the header
(`px-6 pb-6` + `<PageHeader className="pt-6">`), so `top-0` pins flush. Added an optional
`className` to the shared `PageHeader` for this. Verified after: `gapAboveBar 0`,
`barTop === scrollportTop`, and the element above the bar is now the app's own `<header>`.

**Swept every other `position: sticky` in the app** with a probe comparing each one's
actual offset against its declared `top` and its scrollport's padding:
- `ProjectsView` activity rail (`xl:top-4`) — measured `unexpectedGap: 0`, already correct
  (its scroll container has no padding; the 16px is the intended offset).
- `EdgeWizardView` (Ship) and `ExperimentsView` (Compare) — **same structure**
  (`overflow-y-auto p-6` + `sticky top-0`), same latent bug. Fixed identically.
- `RunsView` / `BuilderView` sticky elements are not in padded `p-6` scrollports — not
  affected by this trap.

**Honest verification gap:** Ship and Compare could not be observed in the pinned state —
Ship's content fits without scrolling even at a 500px-tall window, and Compare's sticky bar
only renders once runs are selected. Their containers now report `padding-top: 0px`, which
is the condition that makes `top-0` pin flush, but unlike Templates I did not watch them
stick. Worth a look next time either page has enough content to scroll.

## Datasets file browser rebuilt (first backend change of this engagement)
The table was three columns: a PATH repeating the label as a prefix on every row, a META
column printing that same label again (186 identical cells), and a lowercase "open" text
link. No size, no date, no sort, no totals.

**Root cause was the API, not just the UI.** `GET /data/inputs/{label}` returned only
`{path, label}` per file — the label being the thing the caller just asked for. There was
literally nothing else to show, so the UI padded a column with a constant. Added
`size_bytes` and `modified_at` from an `os.stat` on the path `os.walk` already surfaces;
wrapped in try/except so a file that vanishes or is unreadable mid-walk drops its metadata
instead of failing the whole listing. Additive and backward-compatible.

**Table now:** Name (label prefix stripped — the picker above already says which label
you're in; full path stays on the copy button and tooltip), Size, Modified, all three
sortable, with a "1200 files · 37 MB total" summary computed over the whole filtered set
rather than the rendered page. The 200-row cap is now stated with a "show all" that
raises it (verified 200 → 1200) instead of silently hiding the rest. Row actions (copy
path, preview) appear on hover but stay reachable via `group-focus-within`.

**Two sticky-header traps, both measured:**
1. Same padding-box trap as Templates — fixed the same way (`px-6 pb-6` + header `pt-6`).
2. NEW one: I wrapped the table in `overflow-hidden rounded-2xl` for corner clipping, which
   silently killed the sticky header — an ancestor with `overflow: hidden` becomes the
   sticky element's scroll container, so the header stuck inside a box that never scrolls.
   Measured before: `gapAboveThead -279, theadStillVisible false`, blocker identified as
   that exact wrapper. After removing it and rounding the outer `<th>` corners instead:
   `gapAboveThead 0, pinnedAtTop true, blockers []`.
   **Lesson: `overflow-hidden` anywhere between a sticky element and its scrollport
   disables stickiness. Check ancestors, not just the element.**

**Also:** "Use in workspace" navigated to the picker and implied it would link the label
for you — it can't; pinning happens on a workspace's Home. Renamed to "Pick a workspace…"
with a toast and title naming the actual next step.

Verified live: preview opens a real `<audio>` for a row and closes; sort by size flips
`aria-sort`; nested paths (`down/0c40e715_nohash_0.wav`) keep their subfolder; no console
errors. **Not verified:** `unit_test/api/test_data_router.py` could not be run — pytest is
absent from both the API container and the host. Those tests only assert status codes and
key presence (not exact dict equality), and I exercised the same paths by hand
(list 200, missing label 404, empty label `[]`), but that is not a test run.

## Plugins page — including a render that had never once fired
**Real bug, found by diffing the declared type against the actual payload.** The card read
`p.node_types?.length ? \`${p.node_types.length} nodes\` : null` and `interface Plugin`
declared `node_types?: string[]` — but `GET /plugins` sends node types only under
`manifest.node_types` (verified: 0/48 have it top-level, 48/48 have it nested). So that
chip resolved to `null` for every plugin, on every render, since it was written. Optional
chaining on an always-absent field fails silently and reads as correct code; nothing but
comparing the interface to a real response catches it. Added `nodeTypesOf()` (manifest
first, top-level as fallback) and the card now lists the actual node-type names — the
strings you search for in the Editor catalog — instead of a count that never appeared.

**More discarded data** (the pattern that has paid off on every page this round):
- `manifest.description` — present on 48/48, rendered on none. The one line saying what a
  plugin is for.
- `manifest.tags` — present on 48/48, used only as invisible search text.
- `installed_at` — never shown, so "what did I just install" was unanswerable.

**Installed tab had no text search at all** — 48 plugins, four status pills, and nothing
else. Added search over name/description/tags/node types, a runtime filter
(isolated 16 / inprocess 32), sort (name / recently installed / most node types), tag
facets, and an "N of M shown" count. Verified live: `audio` facet → 21 of 48 (matches the
API exactly), + isolated → 10, search "yamnet" → 3.

**Facet threshold is n > 2, not n > 1.** These manifests carry ~34 tags used exactly
twice, which filled the bar with two wrapped rows of near-useless chips. The tail stays
reachable: search matches tags, and a tag clicked on a card joins the bar because
`activeTags` is always unioned into the facet list. Verified: clicking `asr` (count 2, not
in the bar) pulled it in and narrowed to 2 of 48.

**Removed constant-state noise:** "required deps ok" printed in green on all 48 rows —
the same defect as badging every project DRAFT. It made the one row needing attention
harder to find. Only the exceptional state is loud now.

Also carried over the ⋯ menu flip-up fix from the other pages. tsc + oxlint clean, no
console errors.

## Plugins, second pass — after the user asked whether I had actually LOOKED at it
Fair challenge, and the answer was "not properly". For Templates/Datasets/Workspaces the
user supplied a screenshot of the before state. For Plugins there was none and I did not
take one: I queried the API, read the source, made changes, and only then loaded the page
to confirm the changes landed. Everything I found in pass 1 was therefore a defect visible
in *code or data* — a dead render, discarded fields, a missing search box. Nothing that is
only visible when rendered. I had also never opened the Install / Search tab in a browser.

Looking at it properly found four things code-reading had missed:
- **48 full-width cards.** Each spanned ~1300px for ~140px of content, leaving a huge dead
  gap between the text and the ⋯ menu, and an enormous scroll. Now a 2-column grid; a card
  expands to full width while its dependency table is open.
- **"Optional packages install into this plugin's isolated venv — not into the API image."
  printed on all 16 isolated cards** — one general fact, repeated, that the Deps banner at
  the top of the page already states. Moved to the button's tooltip. I had actually added
  the tag/description rows directly above this sentence in pass 1 without noticing it.
- **"Install optional (venv)" was a filled button** — the loudest element on half the
  cards, louder than the plugin names, for a maintenance action. Now quiet.
- **Node-type and tag chips were visually identical**, so `alignment_node` read as just
  another tag. Node types now carry a NODES label.
- **Install / Search tab** (never before viewed): the source input stretched the full
  ~1300px card for a short package string while the search box beside it was 200px; both
  are now capped and matched, side by side. "Search index" never said what index — it only
  admitted it needs a configured plugin directory *after* a search failed. Said upfront
  now, and Search is disabled until something is typed.

**Process correction going forward: look at the rendered page before designing the fix,
not only after.** Reading source and API payloads finds a different class of defect than
looking does, and this page proved both classes were present.

## Artifacts page — looked at it first this time
Applied the process correction: opened the rendered page and used it as a user *before*
reading a line of source. That immediately surfaced a defect I would not have found in
code — a horizontal scrollbar across the master pane.

- **Horizontal overflow (measured, then root-caused).** The master pane reported
  `scrollWidth 436 vs clientWidth 350`. Cause: the filter row was `flex flex-wrap` holding
  selects with `min-w-[12rem]` and `min-w-[8rem]`. A min-width cannot shrink, so the row's
  intrinsic width (~416px) exceeded the ~310px pane and pushed a horizontal scrollbar onto
  the entire list. In a narrow pane those controls now stack full-width. Verified after:
  the pane no longer overflows (the only remaining entries are `truncate` elements, which
  legitimately report scrollWidth > clientWidth while rendering an ellipsis).
- **Full 32-char artifact ids** were printed unwrapped in ~310px cards — the second
  overflow source, and unreadable. Shortened, full id on the tooltip and Copy path.
- **Silent list collapse.** Selecting an artifact adopts its run into the Run filter, so
  the cross-run list you were browsing silently shrank (100 → 3) with no explanation on a
  page whose own description calls it a *cross-run* registry. Added a count line that says
  which state you are in: "100 artifacts across all runs" / "3 artifacts in run c0bb2845".
  Left the behaviour alone — it has a real rationale (see the run's siblings); it just
  needed to be legible. My earlier audit had recorded this as "auto-scopes correctly",
  which was true mechanically and wrong experientially.
- **Internal TODO shown to users**: "Downstream consumers — needs provenance API". A note
  about a missing backend, rendered verbatim, telling the user nothing they can act on and
  implying something is broken. Now says what it means and where provenance does live.
- **Same bug class again**: `registerModelFromArtifact()` bails with a toast on an empty
  name, but the Register model button was only `disabled={registerBusy}`. Now disabled on
  empty name with a title. Verified: disabled + "Enter a model name first", enables on type.
- **Guidance stated three times on one screen** (page description, above the list, and the
  detail footer). Kept the page description; deleted both repeats.

Verified live after a hard reload; tsc + oxlint clean; no console errors.

## Artifact scope question — answered from evidence, and the UI made honest
User asked why artifacts are visible with no workspace set, and whether artifacts are
project-scoped or global. Checked three layers rather than guessing; all three agree:
- **Record:** `ArtifactRecord` has no project field — artifact_id, content_hash,
  artifact_type, node_id, node_type, run_id, name, metadata, created_at, schema_version,
  data_path. Verified against a live response.
- **API:** `GET /api/v1/artifacts` accepts only `run_id`, `node_type`, `artifact_type`,
  `limit`, `offset`. There is no project parameter to pass.
- **Storage:** `workspace/artifacts/` is keyed by graph name and run
  (`workspace/artifacts/edge-deploy/runs/<run_id>`), plus `by_name/` and `by_run/`
  indexes. Not by project. (I previously misread `workspace/artifacts/<name>` as a project
  dir — it is the graph name, which merely coincides with the project name in the e2e
  fixtures.)

**So artifacts are global, and showing all of them with no workspace open is correct
behaviour, not a leak.** The nav placement under Library (the global group) matches.

What was actually wrong was that nothing said so:
- The description said "Cross-run artifact registry", which reads as "across the runs of
  this workspace". Now: "Every artifact on this API, across all workspaces."
- The count line said "across all runs"; now "across all workspaces".
- `ArtifactsView` uses `activeProject` **only** to populate the Run picker
  (`/runs?project=…`); the artifact list itself is never project-filtered. With a workspace
  open that is genuinely easy to misread, so the page now says it outright and points at
  the Run picker as the way to narrow.

**Caveat on my own earlier work:** the "Browse artifacts" link I added to Home's Activity
passes `{ project }`, which cannot filter the list — it only seeds the Run picker. It is
not useless, but it does not scope, and that is now stated on the destination page rather
than implied by the link.

**CORRECTION — I was wrong that this needs a backend change.** The user pointed out the
obvious: a run belongs to a project and an artifact belongs to a run, so project → runs →
artifacts is a join the client can already do. It needs no new API. Implemented:
- `/runs?project=X` (already fetched for the Run picker, limit raised 20 → 200) yields the
  workspace's run ids; artifacts are filtered on `run_id ∈ thatSet`.
- Scope toggle "This workspace" / "All workspaces", defaulting to the open workspace.
- Verified live against an offline join computed from the raw API: 13 runs →
  **14 artifacts** for e2e-ex-06-speech-commands-e2e, and 121 under All workspaces. Both
  match exactly.

**Found while doing it — a silent truncation the page never disclosed.** `load()` passed
no `limit`, so it took the endpoint default of 100 while 121 artifacts exist: the list had
been quietly dropping 21, and the count line read as a total. Now requests the endpoint
maximum (1000) and says so if that is ever hit.

**Honest about the join's edges rather than implying completeness:** 88 of 128 runs on this
API carry no project at all, so their artifacts belong to no workspace view. With the
workspace scope active the page states the number ("107 artifacts come from runs with no
workspace recorded…") and links to All workspaces, instead of letting them silently vanish.
A per-record project field would still be the more robust fix, but it is an optimisation,
not a prerequisite — the view works today without it.

## Clicking an artifact silently opened a workspace (user-reported) — reproduced and fixed
Reproduced exactly as described. With no workspace open, one click on a row in the browse
list:
1. wrote `graphyn.activeProject = e2e-ex-06-speech-commands-e2e` to **localStorage**,
2. flipped the sidebar from "No project open" to that workspace with Home/Editor/Runs
   enabled, and it survived navigation,
3. collapsed the list from **121 artifacts to 3**.

**Chain:** `open()` set `runFilter` to the artifact's run on every click → an effect
watching `runFilter` fetched the run, read `meta.project`, and called `setActiveProject()`,
which persists. A selection in a browse list was reconfiguring the whole app.

**Why it existed:** the detail actions need a workspace — `openRun()` builds
`/workspaces/<W>/runs/<id>` and silently no-ops without one (a real trap already noted
elsewhere in this file). Adopting the project globally was a way to make those links work.

**Fix — resolve it locally instead of hijacking global state:**
- `detailProject`: the selected artifact's workspace, resolved from its run, used for
  building that artifact's links and displayed as "Produced in workspace X". Never written
  to the store.
- `openRun`/`openTrace` now receive that project explicitly, so the links work with no
  workspace open — removing the reason for the adoption.
- Opening the workspace is an explicit "Open workspace" button; narrowing to the run is an
  explicit "Show this run's artifacts" button.
- Run adoption now happens only on a genuine deep link, not on every click.

**Two self-inflicted bugs found while fixing it, both caught only by re-testing:**
- The URL write that selection performs dispatches the same path-change event the view
  listens to, so `apply()` re-opened the just-opened artifact with `adoptRun` set — the list
  still collapsed. Needed a re-entry guard.
- Guarding on `selected` broke deep links: `selected` is seeded from the URL before effects
  run, so the guard skipped the one `open()` that was needed and the detail pane stayed
  blank. Guard on `openedRef`, which only `open()` sets.

**Verified both paths live:** click from browse → 121 stays 121, detail loads, no workspace
opened. Deep link `?artifactId=…` → scopes to that run (3), detail loads, no workspace
opened. No console errors.

## Testing-tool gotchas learned this round
- **`npx tsc --noEmit` does NOT catch what the real build catches.** It passed clean on an
  ArtifactsView change that used `clsx` without importing it; `npm run build` (which runs
  `tsc -b`, using the project-reference configs) failed with TS2304. Two rounds of
  "tsc_exit=0, lint_exit=0" were false confidence. Verify with `npm run build` — or accept
  that the docker build is the real gate and read its error output instead of only `tail`ing
  the success line.
- **`tsc -b` exits non-zero locally for an unrelated reason:** EACCES writing
  `node_modules/.tmp/*.tsbuildinfo` (same permission problem that blocks vitest). So a
  non-zero local build exit is not by itself a type error — read the actual TS codes, and
  treat the docker build as authoritative.
- **The dev server serves a stale bundle after a rebuild unless you hard-reload.** A
  plain `navigate` to the page after `docker compose up -d` returned the PREVIOUS build:
  the screenshot showed single-column cards and the repeated venv note as though none of
  the changes had shipped. `ctrl+shift+r` then showed `ul.grid.xl:grid-cols-2`, 0 repeated
  notes, 48 NODES labels. This cuts both ways — it can show a fix as failed, or (worse)
  an earlier state as passing. Hard-reload after every rebuild before believing a
  screenshot, and prefer a DOM assertion over eyeballing. (not app bugs — noting so future passes don't re-chase these)
- ConfirmButton has a 4s auto-disarm timer that is SHORTER than a typical multi-tool-call round-trip latency in this environment — always batch both clicks (arm + confirm) into one browser_batch call, never two separate tool invocations.
- Native `<select>` dropdown option clicks are unreliable via synthetic coordinate clicks after opening the dropdown (OS-level popup) — use JS to set `.value` + dispatch a `change` event instead when testing select-driven flows.
- `navigator.clipboard` read/write is unreliable to verify from this automated browser context (permissions) — don't treat an unconfirmed clipboard result as a product bug; verify via source code instead.
- My own long-running session accumulates real localStorage state (layout widths, dismissed hints, actor name) that can look like a "bug" (e.g. a narrow master-pane width) when it's actually just leftover state from earlier manual testing — clear the specific key and reload before concluding a layout issue is real.

## Cross-cutting continuity checks
- [ ] Every keyboard jump-key (b/t/p/r/a/d/j/g/w/l/k/s/o/e) from 2+ different starting pages
- [ ] Command palette: run 3+ real actions from it
- [ ] Mid-task navigation-away-and-back (e.g. mid form edit) — confirm no silent data loss or stale display
- [ ] Header run-status chip / Last-run menu stays correct across at least 3 page navigations
