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
