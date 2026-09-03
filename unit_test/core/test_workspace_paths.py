# unit_test/core/test_workspace_paths.py
"""Unit tests for rewire_graph_outputs."""
from __future__ import annotations

from app.core.workspace_paths import artifact_slug, rewire_graph_outputs


def _graph(nodes):
    return {
        "schema_version": "1.1",
        "metadata": {"name": "demo", "seed": 42},
        "nodes": nodes,
        "edges": [],
    }


class TestArtifactSlug:
    def test_template_id_strips_ex_and_number(self):
        assert artifact_slug("ex-01-wake-word") == "wake-word"

    def test_example_folder(self):
        assert artifact_slug("01_wake_word") == "wake-word"

    def test_example_six_collapses(self):
        assert artifact_slug("speech_commands_e2e_preprocess") == "speech-commands"
        assert artifact_slug("ex-06-speech-commands-e2e") == "speech-commands"


class TestRewireGraphOutputs:
    def test_ingest_data_path_unchanged(self):
        graph = _graph(
            [
                {
                    "id": "ingest",
                    "node_type": "dataset_ingest",
                    "config": {"path": "examples/01_wake_word/data/wake_word"},
                }
            ]
        )
        out = rewire_graph_outputs(graph, slug="wake-word")
        assert out["nodes"][0]["config"]["path"] == "examples/01_wake_word/data/wake_word"

    def test_output_dir_rewritten(self):
        graph = _graph(
            [
                {
                    "id": "exp",
                    "node_type": "dataset_exporter",
                    "config": {"output_dir": "examples/01_wake_word/output/wake_word_detection"},
                }
            ]
        )
        out = rewire_graph_outputs(graph, slug="wake-word")
        assert out["nodes"][0]["config"]["output_dir"] == (
            "workspace/artifacts/wake-word/wake_word_detection"
        )

    def test_meritech_absolute_rewritten(self):
        graph = _graph(
            [
                {
                    "id": "ingest",
                    "node_type": "dataset_ingest",
                    "config": {
                        "path": "/home/meritech/Desktop/newAudio3/examples/02_speech_commands/data/yes"
                    },
                },
                {
                    "id": "exp",
                    "node_type": "dataset_exporter",
                    "config": {
                        "output_dir": "/home/meritech/Desktop/newAudio3/examples/09_parallel_execution/output/yes"
                    },
                },
            ]
        )
        out = rewire_graph_outputs(graph, slug="parallel-execution")
        assert out["nodes"][0]["config"]["path"] == "examples/02_speech_commands/data/yes"
        assert out["nodes"][1]["config"]["output_dir"] == "workspace/artifacts/parallel-execution/yes"

    def test_already_workspace_left_alone(self):
        graph = _graph(
            [
                {
                    "id": "trainer",
                    "node_type": "trainer",
                    "config": {"output_path": "workspace/artifacts/speech-commands"},
                }
            ]
        )
        out = rewire_graph_outputs(graph, slug="other")
        assert out["nodes"][0]["config"]["output_path"] == "workspace/artifacts/speech-commands"

    def test_csv_output_path_rewritten(self):
        graph = _graph(
            [
                {
                    "id": "csv",
                    "node_type": "csv_table",
                    "config": {
                        "operation": "write",
                        "path": "examples/26_nightly_compliance/output/compliance.csv",
                    },
                }
            ]
        )
        out = rewire_graph_outputs(graph, slug="nightly-compliance")
        assert out["nodes"][0]["config"]["path"] == (
            "workspace/artifacts/nightly-compliance/compliance.csv"
        )

    def test_custom_path_outside_examples_output_untouched(self):
        graph = _graph(
            [
                {
                    "id": "exp",
                    "node_type": "dataset_exporter",
                    "config": {"output_dir": "/mnt/models/custom"},
                }
            ]
        )
        out = rewire_graph_outputs(graph, slug="builder")
        assert out["nodes"][0]["config"]["output_dir"] == "/mnt/models/custom"

    def test_does_not_mutate_original(self):
        graph = _graph(
            [
                {
                    "id": "exp",
                    "node_type": "dataset_exporter",
                    "config": {"output_dir": "examples/01_wake_word/output"},
                }
            ]
        )
        rewire_graph_outputs(graph, slug="wake-word")
        assert graph["nodes"][0]["config"]["output_dir"] == "examples/01_wake_word/output"


class TestScopeOutputsToRun:
    def test_inserts_runs_id_after_slug(self):
        graph = _graph(
            [
                {
                    "id": "trainer",
                    "node_type": "trainer",
                    "config": {"output_path": "workspace/artifacts/speech-commands"},
                },
                {
                    "id": "edge",
                    "node_type": "edge_optimizer",
                    "config": {
                        "output_path": "workspace/artifacts/speech-commands/tflite",
                        "model_path": "workspace/artifacts/speech-commands/tflite/model.tflite",
                    },
                },
            ]
        )
        from app.core.workspace_paths import scope_outputs_to_run

        out = scope_outputs_to_run(graph, "abc123")
        cfg0 = out["nodes"][0]["config"]
        cfg1 = out["nodes"][1]["config"]
        assert cfg0["output_path"] == "workspace/artifacts/speech-commands/runs/abc123"
        assert cfg1["output_path"] == "workspace/artifacts/speech-commands/runs/abc123/tflite"
        assert cfg1["model_path"] == (
            "workspace/artifacts/speech-commands/runs/abc123/tflite/model.tflite"
        )

    def test_leaves_latest_and_examples_data_alone(self):
        graph = _graph(
            [
                {
                    "id": "ingest",
                    "node_type": "dataset_ingest",
                    "config": {"path": "examples/02_speech_commands/data/yes"},
                },
                {
                    "id": "infer",
                    "node_type": "realtime_inference",
                    "config": {
                        "model_path": "workspace/artifacts/speech-commands/latest/tflite/model.tflite"
                    },
                },
                {
                    "id": "train_data",
                    "node_type": "dataset_ingest",
                    "config": {
                        "path": "workspace/artifacts/speech-commands/latest/dataset/speech_commands/v1"
                    },
                },
            ]
        )
        from app.core.workspace_paths import scope_outputs_to_run

        out = scope_outputs_to_run(graph, "abc123")
        assert out["nodes"][0]["config"]["path"] == "examples/02_speech_commands/data/yes"
        assert out["nodes"][1]["config"]["model_path"] == (
            "workspace/artifacts/speech-commands/latest/tflite/model.tflite"
        )
        assert out["nodes"][2]["config"]["path"] == (
            "workspace/artifacts/speech-commands/latest/dataset/speech_commands/v1"
        )


class TestPublishLatest:
    def test_symlink_points_at_run_dir(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path))
        from app.core.workspace_paths import artifact_fs_path, artifact_layout, latest_run_id, publish_latest

        slug, run_id = "speech-commands", "runone"
        layout = artifact_layout(slug, run_id)
        run_dir = artifact_fs_path(layout["run_dir"])
        run_dir.mkdir(parents=True)
        (run_dir / "metrics.json").write_text('{"accuracy": 0.91}', encoding="utf-8")
        latest = publish_latest(slug, run_id)
        assert latest == layout["latest_dir"]
        latest_path = artifact_fs_path(latest)
        assert latest_path.is_symlink()
        assert latest_run_id(slug) == run_id
        assert (latest_path / "metrics.json").is_file()
