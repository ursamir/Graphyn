# Work log — Run outputs, inventories, viewers (2026-10)

Do not re-litigate these decisions without reading this file. Class/schema OOP mismatch is **deferred** (see §5).

## 1. Design decisions (locked)

| Decision | Choice |
|---|---|
| Listing source of truth | ArtifactStore inventories + `handler.list_files` / `Node.publish_files` → `file_tree` — **not** domain scavenger walks (`labels.csv`, rglob wav) |
| Ports vs folders | Typed ports ≠ write dirs; write dirs are config keys (`WRITE_CONFIG_KEYS`); path side-effects announced via `publish_files` |
| Opaque run ids in UI | Never show as pipeline step titles; group journal paths as **Run-level**; hide `outputs_index.json` |
| File viewers | Pluggable registry (`registerFileViewer`); built-ins cover common kinds; popup expand supported |
| Mental model diagram | Containment: Workspace → Graphs + Datasets → Nodes/Edges/Run → Artifacts/Logs/Proof; Models/secrets/… orbit that spine |

## 2. What we fixed (this thread + prior)

### Outputs inventory (backend)

- `FileListing` + optional `ArtifactTypeHandler.list_files` (audio + dataset handlers)
- Platform `file_tree` artifact + `Node.publish_files` / `take_published_file_trees`
- `audio_exporter` publishes export trees
- Listing rewritten from ArtifactStore; `outputs_index.json` is artifact-id cache only; excluded from downloadables
- Docs: ARCHITECTURE, API_REFERENCE, DATA_FLOW; audits in `KNOWN_ISSUES.md` (AUDIT-2026-10)

### Isolated worker publish pipe (AUDIT-ISOLATED-PUBLISH-1)

- Worker pickles envelope `{__graphyn_isolated_envelope__, outputs, published_file_trees}`
- Host `IsolatedResult` + `Node.accept_published_file_trees` before executor drain
- Files: `app/core/plugins/worker.py`, `isolated_executor.py`, `nodes/base.py`, `node_executor.py`

### Publish adoption

- `evaluator` and `edge_optimizer` call `publish_files` after writing plots/models

### Config write-dir bridge (existing runs)

- `_collect_configured_write_files` merges allowed files under graph-declared `output_path` / `output_dir` / … so **already finished** runs still show PNGs / tflite without re-scavenging unknown trees

### Allowlist + MIME

- Expanded `ALLOWED_SUFFIXES` (video, pickle, pt/pth, …)
- `/outputs/file` correct media types; **inline** for audio/image/video so players work
- Client `blobUrlWithMime` prefers extension MIME for audio/video/image when server sent `octet-stream`, a generic download type, or a mismatched family; normalizes `audio/x-wav` → `audio/wav` (browser blob playback)
- `lib/wavPlayable.ts` converts IEEE-float32 (and 32-bit PCM) WAV → 16-bit PCM for `<audio>`; AudioViewer applies this before play
- CSP: `media-src 'self' blob: data:` on `graphyn-ui/index.html` (blob/data media otherwise blocked by `default-src 'self'`)

### Runs UI

- Hex / opaque ids filtered in `runOutputs.ts`, `runNodes.ts`, `PipelineStack`, truncation chips
- `shortOutputPath`, hide internal `outputs_index.json`
- Truncation chips under each step + panel banner (not floating raw text)

### Viewers (pluggable)

- `graphyn-ui/src/components/viewers/registry.ts` — `registerFileViewer`
- Built-ins: image, audio, video, json, text, npy (header+sample), pickle (safe hex card), model card, binary
- `FileViewer` shell + popup expand
- Kinds in `lib/fileKind.ts`

### Builder catalog ports + copy node

- Root cause: isolated stub `NodeMetadata` often had empty `input_ports`/`output_ports`, so `GET /nodes` + `catalogPorts` fell back to bare `input`/`output` — templates looked fine (edges carried real port names) while catalog-drag did not.
- Fix: `NodeRegistry.register` fills empty meta ports from the class; Builder `portsNeedResync` / `decorateNodeData` re-syncs existing canvas nodes; Copy button on each node clones type/config/ports (no edges).
- Restart the API after pulling so the registry fill is live.

### Shared write paths + Run outputs mis-attribution (2026-10)

- **Config:** Example 06 train template used one `output_path` for trainer+evaluator; catalog-added model_builder+trainer both defaulted to `workspace/artifacts/models`. Backend path-stamping then tagged eval plots as trainer (and trainer weights as model_builder).
- **Fixes:** template paths split (`…/trainer`, `…/evaluation`, `…/model_builder`, `…/tflite`); `scope_outputs_to_run` uniquifies colliding sinks with `/{node_id}`; Builder isolates catalog-add / load / copy sinks; `run_outputs` prefers basename producer hints (plots→evaluator, `model.keras`→trainer, `compiled_*.keras`→model_builder) over shared-folder stamps; pipeline focus matches instance ids only (`focusMatchesNode` exact when focus is instance-like; Run outputs filters by group id, not `humanNodeLabel`, so hex-suffix Trainer/Evaluator does not re-merge the `_0` sibling).
- Re-load the graph in the Editor (or re-import the template) so canvas configs uniquify, then re-run. Listing an old run picks up the attribution hint fix after API restart.

### MobileNet early-stop / single-class collapse (2026-10)

- **Symptom (run a152ea…):** MobileNet branch EarlyStopping at epoch ~9 (`patience=5`); train acc ~80% while val stuck at chance (16.7%); evaluator matrix all-`go`.
- **Cause:** oversized non-paper MobileNet-style stack on small MFCC KWS data → memorize train, never improve val → early stop mid-run. Dataset was shared/full; not a shuffle/data bug.
- **Fix (superseded by architecture redesign):** `model_builder` now has paper presets (`ds_cnn` Hello Edge 2017, `mobilenet` MobileNetV2 2018 with tunable `expansion_factor`/`stem_stride`/`num_layers`/`filters`) plus `architecture=custom` + `layers` JSON and Builder **Load layers from preset**. For small KWS sets prefer `ds_cnn` or a custom body with pooling; do not expect ImageNet MobileNetV2 defaults to train well on 840 MFCC clips without tuning.

## 3. Still open (do not “rediscover” as new)

See `docs/KNOWN_ISSUES.md` AUDIT-2026-10 for remaining items (cache publish, data API scavenger, suffix dedupe, …). Trainer / other path writers may still need `publish_files`.

## 4. How to add a viewer addon

```ts
import { registerFileViewer } from '../components/viewers/registry'

registerFileViewer({
  id: 'my.pack.viewer',
  label: 'My format',
  extensions: ['.foo'],
  // or kinds: ['binary'],
  priority: 20,
  component: MyViewerComponent,
})
```

## 5. Deferred — class vs schema mismatch

Audit conclusion: Graph spine (`GraphIR` / `IRNode` / `IREdge` / `Node`) matches the mental model; **Workspace / Run / Schedule / Experiment / Template / Secret** are mostly dirs + managers + JSON, not nested OOP members. **Discuss explicitly before inventing `Workspace`/`Run` entity classes.** Dataset “project” ≠ workspace (`ProjectManager` under `datasets/output/{name}`).

## 6. Verify quickly

1. Refresh UI — pipeline stack must not show a 32-char hex as step N.
2. Open a speech-commands run → Evaluator / Edge Optimizer should list `.png` / `.tflite` / `metrics.json` (config write-dir bridge and/or new publish).
3. Click a `.wav` — audio control should play (correct MIME).
4. Click `.png` — image; `.npy` — shape/dtype; `.pkl` — safe card; model file — model card; expand icon opens popup.
