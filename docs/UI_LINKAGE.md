# UI linkage map (brief)

Surface | Primary job | Bridges
--- | --- | ---
**Overview** | Workspace home | Activity → Run; Continue → Editor; Linked input → Data; Browse files → Artifacts
**Editor** | Edit & run graph | Open Overview; Run result → History / Lineage / Files
**Run History** | Inspect runs | Quiet: Editor / Lineage / Files / Compare / Promote (succeeded)
**Compare** | Diff params/metrics | Back to History; add runs from History
**Data library** | Browse datasets | Use in workspace / Open Overview / Open Editor (by context)
**Artifacts** | Cross-run file search | Open Run; prefer Run → Files for one run
**Templates** | Stamp starter → project | Success → Editor
**Trace (standalone)** | Artifact-id deep links | Banner → Run → Lineage; Open Run when `run_id` set
**Edge** | Deploy TFLite path | Open source run (secondary)
**Proposals** | Review agent graphs | Empty → Editor; Accept → Editor
**Plugins** | Install & deps | One primary CTA per card/panel

---

## Workspace vs global chrome

Sidebar switches like an IDE: **workspace activity strip** (Home · Editor · Runs · Models · Ship · Datasets) when `/workspaces/:id` is open; **global** Build/Library/Deploy/Admin otherwise. Library & admin (Templates, Agent inbox, Artifacts, Plugins, Workers, Secrets, Ops, Access) stays collapsed secondary in workspace mode. Contract: `docs/UI_WORKSPACE_IDE.md`, `docs/IA_PROJECT_FIRST.md`.
