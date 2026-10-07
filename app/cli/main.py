# app/cli/main.py
"""
Bounded Context:  CLI Interface
Responsibility:   Command-line entry point for pipeline execution, validation,
                  migration, inspection, node listing, and run history.
Owns:             Argument parsing, subcommand dispatch, startup registration.
                  Command bodies live in app.cli.cmd_*.
Public Surface:   main() — invoked as ``python -m app.cli.main`` or ``graphyn``.
Must NOT:         Contain pipeline execution logic — delegate to SDK/orchestrator.
                  Must not import app.api.
Dependencies:     argparse, app.core.sdk, app.core.ir, app.core.nodes.registry,
                  app.core.runs.run_journal, app.core.config,
                  app.models.audio_artifact_serializer (startup hook).
Reason To Change: New CLI subcommand added, or output format changes.

Subcommands:
  run      --graph PATH [--seed N]    Execute a pipeline from IR JSON (canonical)
  run      --config PATH [--seed N]   Execute a pipeline from YAML (deprecated)
  validate --graph PATH               Validate an IR JSON graph file
  validate --config PATH              Validate a pipeline YAML file
  migrate  --config PATH [--output P] Convert YAML config to IR JSON
  inspect  --graph PATH               Inspect an IR JSON graph file (summary)
  nodes    [--category CAT]           List registered node types
  runs     list                       List recent pipeline runs
  runs     logs <run_id>              Print log entries for a run
  worker   start                      Register as a distributed worker
           join                       Enroll this host with a join token
  data     ls|upload|snapshot|download  Manage input labels / dataset versions
"""

import argparse
import json
import os
import sys
import yaml


# ─── Helpers ──────────────────────────────────────────────────────────────────

from app.core.config import runs_dir as _runs_dir

# NEW-18 fix: do NOT resolve RUNS_DIR at module import time.
# GRAPHYN_PROJECT_DIR may be set after this module is imported (e.g. in tests).
# Each function that needs the runs directory calls _runs_dir() at call time.

# ── Domain serializer registration ───────────────────────────────────────────
# Register the AudioSampleHandler so that artifact_store, pipeline_cache, and
# checkpoint can serialize/deserialize AudioSample objects without importing
# domain models themselves (ARCH-2 fix).
from app.models.serializers import register_builtin_serializers as _reg_serializers
_reg_serializers()

# ── Registry initialization ───────────────────────────────────────────────────
# Explicitly populate the NodeRegistry singleton after the domain serializer
# is registered so node imports that reference AudioSample work correctly.
from app.core.nodes import initialize_registry as _init_registry
_init_registry()


from app.cli.cmd_artifacts import (
    cmd_artifacts_get,
    cmd_artifacts_lineage,
    cmd_artifacts_list,
    cmd_artifacts_replay,
)
from app.cli.cmd_data import cmd_data_download, cmd_data_ls, cmd_data_snapshot, cmd_data_upload
from app.cli.cmd_graph import cmd_inspect, cmd_migrate, cmd_nodes, cmd_run, cmd_validate
from app.cli.cmd_mcp import cmd_mcp
from app.cli.cmd_plugins import (
    cmd_plugin_disable,
    cmd_plugin_enable,
    cmd_plugin_info,
    cmd_plugin_install,
    cmd_plugin_list,
    cmd_plugin_remove,
    cmd_plugin_search,
)
from app.cli.cmd_runs import (
    cmd_runs_cancel,
    cmd_runs_list,
    cmd_runs_logs,
    cmd_runs_pause,
    cmd_runs_resume,
)
from app.cli.cmd_secrets import cmd_secrets_delete, cmd_secrets_list, cmd_secrets_set
from app.cli.cmd_worker import (
    LEGACY_DEFAULT_WORKER_ID,
    WorkerHTTPError,
    resolve_worker_id,
    retry_http,
    worker_heartbeat_payload,
    cmd_worker_start,
)
from app.cli.support import list_cli_runs, run_with_seed

# Names kept for existing tests that import them from app.cli.main.
_LEGACY_DEFAULT_WORKER_ID = LEGACY_DEFAULT_WORKER_ID
_WorkerHTTPError = WorkerHTTPError
_resolve_worker_id = resolve_worker_id
_retry_http = retry_http
_worker_heartbeat_payload = worker_heartbeat_payload
_list_runs = list_cli_runs
_run_with_seed = run_with_seed


def build_parser():
    parser = argparse.ArgumentParser(
        prog="graphyn",
        description="Graphyn CLI — build and manage AI/workflow pipelines",
    )
    # CLI-000 global flags (also readable from GRAPHYN_API_URL / GRAPHYN_API_TOKEN)
    parser.add_argument(
        "--api-url",
        default=None,
        metavar="URL",
        help="Remote API base URL (env GRAPHYN_API_URL). Enables remote mode for supported commands.",
    )
    parser.add_argument(
        "--token",
        default=None,
        metavar="TOKEN",
        help="Bearer token (env GRAPHYN_API_TOKEN).",
    )
    parser.add_argument(
        "--actor",
        default=None,
        metavar="ACTOR",
        help="X-Actor value for remote mutations (env GRAPHYN_ACTOR).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Machine-readable JSON on stdout where supported.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help="Verbose diagnostics on stderr.",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
    subparsers.required = True

    # ── inspect ── (V1.md §9 — graph inspection)
    inspect_parser = subparsers.add_parser(
        "inspect",
        help="Inspect an IR JSON graph file",
        description="Print a human-readable summary of an IR JSON graph file.",
    )
    inspect_parser.add_argument(
        "--graph",
        required=True,
        metavar="PATH",
        help="Path to the IR JSON graph file",
    )
    inspect_parser.set_defaults(func=cmd_inspect)

    # ── nodes ── (V1.md §9 — registry inspection)
    nodes_parser = subparsers.add_parser(
        "nodes",
        help="List registered node types",
        description="List all registered node types with optional filtering.",
    )
    nodes_parser.add_argument(
        "--category",
        default=None,
        metavar="CATEGORY",
        help="Filter by category (e.g. 'audio', 'ml')",
    )
    nodes_parser.add_argument(
        "--capability",
        nargs="*",
        metavar="KEY=VALUE",
        help="Filter by capability (e.g. --capability requires_gpu=false supports_edge=true)",
    )
    nodes_parser.set_defaults(func=cmd_nodes)

    # ── migrate ── (Req 4.3)
    migrate_parser = subparsers.add_parser(
        "migrate",
        help="Convert a YAML pipeline config to IR JSON",
        description="Convert a YAML pipeline config file to the canonical IR JSON format.",
    )
    migrate_parser.add_argument(
        "--config",
        required=True,
        metavar="PATH",
        help="Path to the YAML pipeline config file to convert",
    )
    migrate_parser.add_argument(
        "--output",
        default=None,
        metavar="PATH",
        help="Output path for the IR JSON file (default: same dir, .graph.json extension)",
    )
    migrate_parser.set_defaults(func=cmd_migrate)

    # ── run ── (Req 4.5)
    run_parser = subparsers.add_parser(
        "run",
        help="Execute a pipeline synchronously",
        description="Execute a pipeline from an IR JSON file (canonical) or YAML config (deprecated).",
    )
    run_parser.add_argument(
        "--graph",
        required=False,
        default=None,
        metavar="PATH",
        help="Path to the IR JSON graph file (canonical format)",
    )
    run_parser.add_argument(
        "--config",
        required=False,
        default=None,
        metavar="PATH",
        help="Path to the pipeline YAML config file (deprecated — use --graph)",
    )
    run_parser.add_argument(
        "--seed",
        type=int,
        default=None,
        metavar="N",
        help="Override the pipeline seed (integer)",
    )
    run_parser.add_argument(
        "--parallel",
        action="store_true",
        default=False,
        help="Enable parallel wave execution.",
    )
    run_parser.add_argument(
        "--resume",
        dest="resume_run_id",
        default=None,
        metavar="RUN_ID",
        help="Resume from a prior run ID.",
    )
    run_parser.add_argument(
        "--include-nodes",
        dest="include_nodes",
        default=None,
        metavar="ID,...",
        help="Comma-separated node IDs to include (partial execution).",
    )
    run_parser.add_argument(
        "--exclude-nodes",
        dest="exclude_nodes",
        default=None,
        metavar="ID,...",
        help="Comma-separated node IDs to exclude (partial execution).",
    )
    run_parser.add_argument(
        "--event-driven",
        dest="event_driven",
        action="store_true",
        default=False,
        help="Run in event-driven mode.",
    )
    run_parser.set_defaults(func=cmd_run)

    # ── validate ── (Req 4.6)
    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate a pipeline YAML file or IR JSON graph",
        description="Validate a pipeline config against the node registry.",
    )
    validate_parser.add_argument(
        "--graph",
        required=False,
        default=None,
        metavar="PATH",
        help="Path to the IR JSON graph file",
    )
    validate_parser.add_argument(
        "--config",
        required=False,
        default=None,
        metavar="PATH",
        help="Path to the pipeline YAML config file",
    )
    validate_parser.set_defaults(func=cmd_validate)

    # ── runs ──
    runs_parser = subparsers.add_parser(
        "runs",
        help="Manage pipeline run history",
        description="List and inspect past pipeline runs.",
    )
    runs_subparsers = runs_parser.add_subparsers(dest="runs_command", metavar="ACTION")
    runs_subparsers.required = True

    runs_list_parser = runs_subparsers.add_parser(
        "list",
        help="Print a table of recent runs",
    )
    runs_list_parser.add_argument(
        "--limit",
        type=int,
        default=50,
        metavar="N",
        help="Maximum number of runs to show (default: 50; 0 = all)",
    )
    runs_list_parser.set_defaults(func=cmd_runs_list)

    runs_logs_parser = runs_subparsers.add_parser(
        "logs",
        help="Print log entries for a run",
    )
    runs_logs_parser.add_argument(
        "run_id",
        metavar="RUN_ID",
        help="Run ID (or unique prefix) to fetch logs for",
    )
    runs_logs_parser.set_defaults(func=cmd_runs_logs)

    # pause
    runs_pause_parser = runs_subparsers.add_parser(
        "pause",
        help="Pause an active run after its current node completes",
    )
    runs_pause_parser.add_argument(
        "run_id",
        metavar="RUN_ID",
        help="Run ID of the active run to pause",
    )
    runs_pause_parser.set_defaults(func=cmd_runs_pause)

    # resume
    runs_resume_parser = runs_subparsers.add_parser(
        "resume",
        help="Resume a paused run",
    )
    runs_resume_parser.add_argument(
        "run_id",
        metavar="RUN_ID",
        help="Run ID of the paused run to resume",
    )
    runs_resume_parser.set_defaults(func=cmd_runs_resume)

    # cancel
    runs_cancel_parser = runs_subparsers.add_parser(
        "cancel",
        help="Cancel an active run after its current node completes",
    )
    runs_cancel_parser.add_argument(
        "run_id",
        metavar="RUN_ID",
        help="Run ID of the active run to cancel",
    )
    runs_cancel_parser.set_defaults(func=cmd_runs_cancel)

    # ── artifacts ──
    artifacts_parser = subparsers.add_parser(
        "artifacts",
        help="Manage artifacts",
        description="List, inspect, and replay pipeline artifacts.",
    )
    artifacts_subparsers = artifacts_parser.add_subparsers(dest="artifacts_command", metavar="ACTION")
    artifacts_subparsers.required = True

    # list subcommand
    list_parser = artifacts_subparsers.add_parser("list", help="List artifacts")
    list_parser.add_argument("--run", default=None, metavar="RUN_ID", help="Filter by run ID")
    list_parser.add_argument("--type", default=None, metavar="TYPE", help="Filter by artifact type")
    list_parser.set_defaults(func=cmd_artifacts_list)

    # get subcommand
    get_parser = artifacts_subparsers.add_parser("get", help="Get artifact by ID")
    get_parser.add_argument("artifact_id", metavar="ARTIFACT_ID")
    get_parser.set_defaults(func=cmd_artifacts_get)

    # lineage subcommand
    lineage_parser = artifacts_subparsers.add_parser("lineage", help="Get artifact lineage")
    lineage_parser.add_argument("artifact_id", metavar="ARTIFACT_ID")
    lineage_parser.set_defaults(func=cmd_artifacts_lineage)

    # replay subcommand
    replay_parser = artifacts_subparsers.add_parser("replay", help="Replay a run")
    replay_parser.add_argument("run_id", metavar="RUN_ID")
    replay_parser.set_defaults(func=cmd_artifacts_replay)

    # ── plugin ── (req-06 §7.1–§7.11)
    plugin_parser = subparsers.add_parser(
        "plugin",
        help="Manage plugins",
        description="Install, list, enable, disable, remove, search, and inspect plugins.",
    )
    plugin_subparsers = plugin_parser.add_subparsers(dest="plugin_command", metavar="ACTION")
    plugin_subparsers.required = True

    # install
    plugin_install_parser = plugin_subparsers.add_parser(
        "install",
        help="Install a plugin from a source",
    )
    plugin_install_parser.add_argument(
        "source",
        metavar="SOURCE",
        help="Plugin source: local path, Git URL, HTTP archive URL, or plugin name",
    )
    plugin_install_parser.add_argument(
        "--upgrade",
        action="store_true",
        default=False,
        help="Replace an existing installation with the same name",
    )
    plugin_install_parser.set_defaults(func=cmd_plugin_install)

    # list
    plugin_list_parser = plugin_subparsers.add_parser(
        "list",
        help="List installed plugins",
    )
    plugin_list_parser.add_argument(
        "--enabled",
        action="store_true",
        default=False,
        help="Show only enabled plugins",
    )
    plugin_list_parser.set_defaults(func=cmd_plugin_list)

    # enable
    plugin_enable_parser = plugin_subparsers.add_parser(
        "enable",
        help="Enable an installed plugin",
    )
    plugin_enable_parser.add_argument(
        "name",
        metavar="NAME",
        help="Plugin name to enable",
    )
    plugin_enable_parser.set_defaults(func=cmd_plugin_enable)

    # disable
    plugin_disable_parser = plugin_subparsers.add_parser(
        "disable",
        help="Disable an installed plugin",
    )
    plugin_disable_parser.add_argument(
        "name",
        metavar="NAME",
        help="Plugin name to disable",
    )
    plugin_disable_parser.set_defaults(func=cmd_plugin_disable)

    # remove
    plugin_remove_parser = plugin_subparsers.add_parser(
        "remove",
        help="Uninstall a plugin",
    )
    plugin_remove_parser.add_argument(
        "name",
        metavar="NAME",
        help="Plugin name to remove",
    )
    plugin_remove_parser.set_defaults(func=cmd_plugin_remove)

    # search
    plugin_search_parser = plugin_subparsers.add_parser(
        "search",
        help="Search the plugin index",
    )
    plugin_search_parser.add_argument(
        "query",
        metavar="QUERY",
        help="Search query string",
    )
    plugin_search_parser.set_defaults(func=cmd_plugin_search)

    # info
    plugin_info_parser = plugin_subparsers.add_parser(
        "info",
        help="Show full info for a plugin",
    )
    plugin_info_parser.add_argument(
        "name",
        metavar="NAME",
        help="Plugin name to inspect",
    )
    plugin_info_parser.set_defaults(func=cmd_plugin_info)

    # ── secrets ──
    secrets_parser = subparsers.add_parser(
        "secrets",
        help="Manage local named secrets (GRAPHYN_HOME/secrets)",
        description=(
            "File-per-secret store under GRAPHYN_HOME/secrets (mode 0600). "
            "List returns names only. `set` reads the value from the process "
            "environment variable of the same NAME, or from stdin — never argv."
        ),
    )
    secrets_sub = secrets_parser.add_subparsers(dest="secrets_command", metavar="ACTION")
    secrets_sub.required = True
    secrets_list_parser = secrets_sub.add_parser("list", help="List secret names")
    secrets_list_parser.add_argument("--json", action="store_true", help="JSON output")
    secrets_list_parser.set_defaults(func=cmd_secrets_list)
    secrets_set_parser = secrets_sub.add_parser(
        "set",
        help="Store a secret (value from env NAME or stdin, not argv)",
    )
    secrets_set_parser.add_argument("name", help="Secret name, e.g. OPENAI_API_KEY")
    secrets_set_parser.set_defaults(func=cmd_secrets_set)
    secrets_del_parser = secrets_sub.add_parser("delete", help="Delete a named secret")
    secrets_del_parser.add_argument("name")
    secrets_del_parser.set_defaults(func=cmd_secrets_delete)

    # ── users ── (console users / RBAC, control host)
    from app.cli.cmd_users import add_users_parser

    add_users_parser(subparsers)

    # ── data ── (input labels / dataset versions)
    data_parser = subparsers.add_parser(
        "data",
        help="Datasets: list, upload, freeze (snapshot), download",
        description=(
            "Manage workspace/datasets. Local by default; with --api-url / GRAPHYN_API_URL "
            "the commands call the REST /data endpoints. Mutations are audited."
        ),
    )
    data_sub = data_parser.add_subparsers(dest="data_command", metavar="ACTION")
    data_sub.required = True
    data_ls = data_sub.add_parser("ls", help="List input labels, a label's files, or output versions")
    data_ls.add_argument("label", nargs="?", default=None, help="Input label to list files of")
    data_ls.add_argument("--outputs", action="store_true", help="List output dataset versions instead")
    data_ls.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="JSON output")
    data_ls.set_defaults(func=cmd_data_ls)
    data_up = data_sub.add_parser("upload", help="Upload files, folders or zip/tar archives into a label")
    data_up.add_argument("paths", nargs="+", help="Files, folders or .zip/.tar(.gz) archives")
    data_up.add_argument("--label", default="uploads", help="Target input label (default: uploads)")
    fal = data_up.add_mutually_exclusive_group()
    fal.add_argument("--folders-as-labels", dest="folders_as_labels", action="store_true", default=None,
                     help="First folder of each path names the label (default for archives)")
    fal.add_argument("--keep-folders", dest="folders_as_labels", action="store_false",
                     help="Keep sub-folders under --label (default for plain files)")
    data_up.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="JSON output")
    data_up.set_defaults(func=cmd_data_upload)
    data_snap = data_sub.add_parser("snapshot", help="Freeze an input label as an immutable version")
    data_snap.add_argument("label")
    data_snap.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="JSON output")
    data_snap.set_defaults(func=cmd_data_snapshot)
    data_dl = data_sub.add_parser("download", help="Zip an input label or an output version")
    data_dl.add_argument("target", help="<label> or <project>/<version> (e.g. _inputs/yes/v1)")
    data_dl.add_argument("-o", "--output", default=None, help="Zip path (default: <name>.zip)")
    data_dl.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="JSON output")
    data_dl.set_defaults(func=cmd_data_download)

    # ── mcp ── (Req 1.6, 8.1)
    mcp_parser = subparsers.add_parser(
        "mcp",
        help="Start the MCP server (stdio transport)",
        description=(
            "Start the Graphyn MCP server. "
            "Reads JSON-RPC from stdin, writes responses to stdout. "
            "Set GRAPHYN_API_TOKEN to require authentication. "
            "GRAPHYN_AUTH_REQUIRED=1 or GRAPHYN_ENV=production forbids an empty token."
        ),
    )
    mcp_parser.set_defaults(func=cmd_mcp)


    # ── worker ── (distributed execution)
    worker_parser = subparsers.add_parser(
        "worker",
        help="Run as a distributed execution worker",
        description="Register with a Graphyn control plane and claim node jobs.",
    )
    worker_sub = worker_parser.add_subparsers(dest="worker_command", metavar="ACTION")
    worker_sub.required = True
    worker_start = worker_sub.add_parser(
        "start",
        help="Register, heartbeat, claim and execute jobs",
    )
    worker_start.add_argument(
        "--control-url",
        default=os.environ.get("GRAPHYN_CONTROL_URL"),
        metavar="URL",
        help="Control plane API base, e.g. http://host:8001/api/v1",
    )
    worker_start.add_argument(
        "--worker-id",
        default=os.environ.get("GRAPHYN_WORKER_ID"),
        metavar="ID",
        help="Unique worker id (default: GRAPHYN_WORKER_ID or auto <hostname>-<8hex>)",
    )
    worker_start.add_argument(
        "--labels",
        default="",
        metavar="LIST",
        help="Comma-separated labels, e.g. gpu,lab",
    )
    worker_start.add_argument(
        "--pool",
        default=None,
        metavar="NAME",
        help="Optional pool name, e.g. gpu-lab",
    )
    worker_start.add_argument(
        "--heartbeat",
        type=float,
        default=15.0,
        help="Heartbeat / poll interval seconds (default 15)",
    )
    worker_start.add_argument(
        "--once",
        action="store_true",
        help="Process at most one claim attempt then exit (useful for tests)",
    )
    worker_start.add_argument(
        "--in-process",
        action="store_true",
        help="Use in-memory registry/queue instead of HTTP (dev/tests)",
    )
    worker_start.add_argument(
        "--plugins",
        default="",
        metavar="LIST",
        help=(
            "Comma-separated node_type advertisement override "
            "(default: all registry node types). Empty advertisement "
            "disables hard-refuse."
        ),
    )
    worker_start.add_argument(
        "--no-enrollment",
        action="store_true",
        help="Ignore a saved `worker join` enrollment (use GRAPHYN_WORKER_TOKEN / flags)",
    )
    worker_start.set_defaults(func=cmd_worker_start)
    from app.cli.cmd_worker_join import add_worker_join_parser

    add_worker_join_parser(worker_sub)

    return parser


def _apply_global_env(args) -> None:
    """Propagate global CLI flags into process env for remote helpers."""
    import os

    api_url = getattr(args, "api_url", None) or os.environ.get("GRAPHYN_API_URL")
    token = getattr(args, "token", None) or os.environ.get("GRAPHYN_API_TOKEN")
    actor = getattr(args, "actor", None) or os.environ.get("GRAPHYN_ACTOR")
    if api_url:
        os.environ["GRAPHYN_API_URL"] = str(api_url).rstrip("/")
        args.api_url = os.environ["GRAPHYN_API_URL"]
    if token:
        os.environ["GRAPHYN_API_TOKEN"] = str(token)
        args.token = str(token)
    if actor:
        os.environ["GRAPHYN_ACTOR"] = str(actor)
        args.actor = str(actor)


def _remote_get(path: str, *, api_url: str, token: str | None) -> tuple[int, object]:
    """Low-risk GET helper for optional remote mode. Returns (http_status, json_or_text)."""
    import json as _json
    import urllib.error
    import urllib.request

    url = api_url.rstrip("/") + path
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            try:
                return resp.status, _json.loads(raw)
            except Exception:
                return resp.status, raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            body = _json.loads(raw)
        except Exception:
            body = raw
        return exc.code, body


_REMOTE_NODES_PAGE = 500  # server max for GET /api/v1/nodes?limit=


def _remote_list_all_nodes(
    *, api_url: str, token: str | None, category: str | None = None
) -> tuple[int, object]:
    """Page through GET /api/v1/nodes until every node type is fetched.

    The endpoint defaults to ``limit=50`` (envelope ``{items,total,next_offset}``),
    so a single GET silently truncated the catalog. Returns ``(status, body)``
    where a successful body is ``{"items": [...all...], "total": N}``; the
    first non-2xx page status/body is returned as-is.
    """
    from urllib.parse import urlencode

    items: list = []
    offset = 0
    total: int | None = None
    for _ in range(10_000):  # hard stop against a misbehaving server
        query = {"limit": _REMOTE_NODES_PAGE, "offset": offset}
        if category:
            query["category"] = category
        status, body = _remote_get(
            f"/api/v1/nodes?{urlencode(query)}", api_url=api_url, token=token
        )
        if status >= 400:
            return status, body
        if isinstance(body, list):
            # Bare-array server (envelope off / legacy): page until short.
            items.extend(body)
            if len(body) < _REMOTE_NODES_PAGE:
                break
            offset += len(body)
            continue
        if not isinstance(body, dict):
            return status, body
        page = body.get("items")
        if not isinstance(page, list):
            return status, body
        items.extend(page)
        if isinstance(body.get("total"), int):
            total = body["total"]
        next_offset = body.get("next_offset")
        if not page or next_offset is None:
            break
        if not isinstance(next_offset, int) or next_offset <= offset:
            break
        offset = next_offset
    return 200, {"items": items, "total": total if total is not None else len(items)}


def main():
    from app.cli.exit_codes import (
        EXIT_AUTH,
        EXIT_CANCELLED,
        EXIT_CONFLICT,
        EXIT_GENERAL,
        EXIT_NOT_FOUND,
        EXIT_VALIDATION,
        CliError,
    )

    parser = build_parser()
    args = parser.parse_args()
    _apply_global_env(args)

    # Optional remote mode for low-risk list commands
    if getattr(args, "api_url", None) and getattr(args, "command", None) == "nodes":
        status, body = _remote_list_all_nodes(
            api_url=args.api_url,
            token=getattr(args, "token", None),
            category=getattr(args, "category", None),
        )
        if status == 401:
            print("Error: unauthorized", file=sys.stderr)
            sys.exit(EXIT_AUTH)
        if status == 404:
            print("Error: not found", file=sys.stderr)
            sys.exit(EXIT_NOT_FOUND)
        if status >= 400:
            print(f"Error: remote nodes failed ({status})", file=sys.stderr)
            sys.exit(EXIT_GENERAL)
        if getattr(args, "json", False):
            print(json.dumps(body, indent=2))
        else:
            items = body.get("items", body) if isinstance(body, dict) else body
            if isinstance(items, list):
                for n in items:
                    if isinstance(n, dict):
                        print(n.get("node_type") or n.get("name") or n)
                    else:
                        print(n)
            else:
                print(body)
        sys.exit(0)

    try:
        args.func(args)
    except CliError as exc:
        print(f"Error: {exc.message}", file=sys.stderr)
        sys.exit(exc.code)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)
    except PermissionError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(EXIT_AUTH)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(EXIT_CANCELLED)
    except SystemExit:
        raise
    except Exception as exc:
        # Map common conflict markers
        msg = str(exc)
        if "version_conflict" in msg or "invalid_transition" in msg or "conflict" in msg.lower():
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(EXIT_CONFLICT)
        if "valid" in msg.lower() and "fail" in msg.lower():
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(EXIT_VALIDATION)
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(EXIT_GENERAL)


if __name__ == "__main__":
    main()
