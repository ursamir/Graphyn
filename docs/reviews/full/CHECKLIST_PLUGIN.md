# Checklist: Plugin (apply to every plugin / node type)

Tip `6978329f529c59567fdfa4397c5bea5a6b1c9099`. Results across the 36 live node types are in `SWEEP_PLUGINS.csv/.md`. Under the honesty rule, a stub mode, a placeholder, `NotImplementedError` or fake output scores **Fail** for that item.

| ID | Item | How to verify | Pass criteria | Fleet result (36 nodes) |
|---|---|---|---|---|
| PLG-C01 | Manifest parses; name/version/entry_points/node_types present | load plugin.toml with tomllib | All present | 36/36 pass |
| PLG-C02 | `runtime` declared (inprocess or isolated) | manifest key | Present | **28/36**: missing for 7 Audio plugins and deployment_packager |
| PLG-C03 | Loads live and registers its node type | `GET /api/v1/nodes` | Type listed | 36/36 |
| PLG-C04 | Config schema in manifest matches the live config keys | compare manifest vs live `config_schema` | Equal | 36/36 key counts equal |
| PLG-C05 | Ports carry domain types (not `object`/`list`) | live port types | Domain type | **Fail** for 22 Common/Agents workflow nodes (`object`) and 7 Audio (`builtins.list`); Pass for the ML chain |
| PLG-C06 | Accepts the platform's standard upstream payloads (CodeResult, CsvTableResult, dict, list) | wire python_code → node | Uses `data`; doesn't operate on the wrapper | **Fail** for set_map, json_transform, merge, if_switch, prompt_template, output_schema_validate, llm_chat, structured_llm, object_store; Pass for eval_gate and guardrail_filter |
| PLG-C07 | Default mode runs end to end live | minimal graph run | `succeeded`, meaningful output | 36/36 (see sweep) |
| PLG-C08 | Every advertised mode/backend/target is real | run each enum value | No stub file, no NotImplementedError | **Fail**: edge_optimizer (3), deployment_packager (4), segmenter speaker_turn, realtime_inference ultralytics/auto+audio |
| PLG-C09 | Default behaviour is honest (no fake LLM/extraction by default) | run with defaults | Output is real, or clearly labelled demo | **Fail**: llm_chat default `local` echo; structured_llm local_heuristic |
| PLG-C10 | Write nodes either write or fail; no silent no-op | object_store put with assorted inputs | File written or error | **Fail**: object_store returns `[]` |
| PLG-C11 | Paths are jailed to the workspace, but legitimate workspace inputs are readable | csv_table read of a datasets/input CSV | Readable; traversal blocked | **Partial**: traversal blocked, but symlinked inputs are unreadable |
| PLG-C12 | Credentials only by `connection_id`; values redacted in outputs/logs | credential_probe, llm_chat | Redacted | Pass |
| PLG-C13 | Outbound network nodes honour the egress policy and are safe by default | http_request to loopback/metadata | Blocked by default | **Fail** (trusted default) |
| PLG-C14 | Side-effect nodes respect dry-run | send_email with SMTP_DRY_RUN=1 | No send; dry-run recorded | Pass |
| PLG-C15 | Path-bearing outputs use ArtifactRef (Mode B-safe) | grep for ArtifactRef; outputs carry refs | Refs present | Partial: object_store, trainer, evaluator, edge_optimizer, deployment_packager, csv_table yes; dataset_builder no |
| PLG-C16 | Dependencies declared (heavy ones optional / isolated) | manifest deps vs imports; check_deps.py | Covered | Pass |
| PLG-C17 | Has a dedicated unit test | unit_test refs | ≥1 | 35/36: credential_probe has 0 (suite also red because of removed plugins) |
| PLG-C18 | Description is accurate (no undisclosed stubs, no jargon) | `GET /nodes` description; test_ux_plugins_schema_ux | Accurate | **Fail**: deployment_packager stub targets undisclosed; send_email jargon test fails; if_switch expression hint misleading |
| PLG-C19 | Works in Mode B (worker execution) | ex29 with a registered worker | Succeeds | **Unverified / Fail**: Mode B broken (transfer.py) and down live |
| PLG-C20 | Errors are actionable (message names the config key) | run with missing required config | Clear error | Pass (send_email `to` required, http_webhook `url` required) |
