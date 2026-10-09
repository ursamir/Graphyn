# Checklist: Template (apply to every template / catalog entry)

Tip `6978329f529c59567fdfa4397c5bea5a6b1c9099`. Per-template results are in `SWEEP_TEMPLATES.csv/.md`.

| ID | Item | How to verify | Pass criteria | Fleet result |
|---|---|---|---|---|
| TPL-C01 | JSON parses; `schema_version` 1.2/1.3; `metadata.seed` present | load + POST `/api/v1/pipelines/validate` | 200 `valid:true` | 58/129 file templates valid |
| TPL-C02 | Every node type exists in the live registry | compare node types vs `GET /nodes` | No missing types | **Fail for 71/129**; all invalid ones reference packs removed from this branch |
| TPL-C03 | Catalog entries materialize | `POST /pipeline-templates/{id}/materialize` (or equivalent) | 200 | 3,032/3,032 |
| TPL-C04 | Materialized catalog entries validate | validate the materialized IR | ≥95% (repo test gate) | **Fail**: 112/3,032 (3.7%) |
| TPL-C05 | `runnable` / `missing_node_types` flags are honest | `GET /pipelines/templates` | Unrunnable ones flagged | Pass (16/31 flagged). The catalog UI still lists ~2,900 unrunnable entries. |
| TPL-C06 | Runs end to end with shipped defaults | POST run with only sandbox output overrides | `succeeded` | 17 runs succeeded. ex06 train as-is fails (expects `audio_export/latest` from a prior run); ex30 fails (expects an existing saved_model). |
| TPL-C07 | Prerequisites are declared (chained datasets/models) | read template meta / README | Declared | **Fail**: ex06 train and ex30 don't declare their upstream dependency in IR metadata |
| TPL-C08 | Required config is either pre-filled or flagged before run | marketplace seeds | Flagged at validate time | **Fail**: email-alert, notify-on-run, http-poll and kws-* validate OK but fail at run time (empty `to`/`url`/ingest path) |
| TPL-C09 | No secrets embedded; credentials referenced by connection name | IR scan | No secret-shaped values | Pass (secret_in_ir scanner enforced) |
| TPL-C10 | Output paths are deterministic and inside the workspace | inspect `audio_exporter.output_dir` etc. | Jailed | Pass |
| TPL-C11 | Mode B placement honoured when the backend is distributed | ex29 on Mode B | Node→worker map populated | **Unverified**: ran in Mode A only (placement ignored, 1c786d06) |
| TPL-C12 | No duplicate templates under different names | hash the IR | Unique | **Fail**: 15 workspace copies duplicate examples/templates; smart-home marketplace graphs duplicate automotive |
| TPL-C13 | Tests that cover templates are green | test_example_templates, materializer, catalog ≥95% | Green | **Fail**: 84 template-related test failures or errors |
