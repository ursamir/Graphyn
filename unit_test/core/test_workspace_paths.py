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
    def test_ingest_data_path_rewritten_to_workspace_input(self):
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
        assert out["nodes"][0]["config"]["path"] == (
            "workspace/datasets/input/wake-word/wake_word"
        )
        assert "examples/" not in out["nodes"][0]["config"]["path"]

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
        assert out["nodes"][0]["config"]["path"] == (
            "workspace/datasets/input/speech-commands/yes"
        )
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


    def test_dataset_exporter_examples_output_rewires_stable_not_latest(self):
        graph = _graph(
            [
                {
                    "id": "exp",
                    "node_type": "audio_exporter",
                    "config": {
                        "output_dir": "examples/06_speech_commands_e2e/output/dataset/speech_commands"
                    },
                }
            ]
        )
        out = rewire_graph_outputs(graph, slug="speech_commands_e2e_preprocess")
        assert out["nodes"][0]["config"]["output_dir"] == (
            "workspace/artifacts/speech-commands/dataset/speech_commands"
        )
        assert "/latest/" not in out["nodes"][0]["config"]["output_dir"]

    def test_dataset_ingest_of_built_dataset_rewires_stable_not_latest(self):
        graph = _graph(
            [
                {
                    "id": "ingest",
                    "node_type": "dataset_ingest",
                    "config": {
                        "path": "examples/06_speech_commands_e2e/output/dataset/speech_commands/v1"
                    },
                }
            ]
        )
        out = rewire_graph_outputs(graph, slug="speech_commands_e2e_train_ml")
        assert out["nodes"][0]["config"]["path"] == (
            "workspace/artifacts/speech-commands/dataset/speech_commands/v1"
        )
        assert "/latest/" not in out["nodes"][0]["config"]["path"]

    def test_raw_wav_ingest_rewritten_to_shared_input_tree(self):
        graph = _graph(
            [
                {
                    "id": "ingest",
                    "node_type": "dataset_ingest",
                    "config": {"path": "examples/02_speech_commands/data"},
                }
            ]
        )
        out = rewire_graph_outputs(graph, slug="speech_commands_e2e_train_ml")
        assert out["nodes"][0]["config"]["path"] == (
            "workspace/datasets/input/speech-commands"
        )

    def test_file_path_wav_under_examples_data(self):
        graph = _graph(
            [
                {
                    "id": "stream",
                    "node_type": "stream_ingest",
                    "config": {
                        "file_path": "examples/02_speech_commands/data/yes/clip.wav"
                    },
                }
            ]
        )
        out = rewire_graph_outputs(graph, slug="edge-inference")
        assert out["nodes"][0]["config"]["file_path"] == (
            "workspace/datasets/input/speech-commands/yes/clip.wav"
        )

    def test_generic_slug_does_not_flatten_example_six_outputs(self):
        graph = _graph(
            [
                {
                    "id": "exp",
                    "node_type": "audio_exporter",
                    "config": {
                        "output_dir": "examples/06_speech_commands_e2e/output/dataset/speech_commands"
                    },
                }
            ]
        )
        graph["metadata"]["name"] = "pipeline"
        out = rewire_graph_outputs(graph, slug="pipeline")
        assert out["nodes"][0]["config"]["output_dir"] == (
            "workspace/artifacts/speech-commands/dataset/speech_commands"
        )
        assert "artifacts/pipeline" not in out["nodes"][0]["config"]["output_dir"]

    def test_ingest_slug_comes_from_example_folder_not_consumer(self):
        graph = _graph(
            [
                {
                    "id": "ingest",
                    "node_type": "dataset_ingest",
                    "config": {"path": "examples/02_speech_commands/data/no"},
                }
            ]
        )
        graph["metadata"]["name"] = "pipeline"
        out = rewire_graph_outputs(graph, slug="pipeline")
        assert out["nodes"][0]["config"]["path"] == (
            "workspace/datasets/input/speech-commands/no"
        )

    def test_rewire_never_displays_examples_in_path_keys(self):
        graph = _graph(
            [
                {
                    "id": "ingest",
                    "node_type": "dataset_ingest",
                    "config": {"path": "examples/03_environmental_sounds/data/dog"},
                },
                {
                    "id": "exp",
                    "node_type": "audio_exporter",
                    "config": {
                        "output_dir": "examples/03_environmental_sounds/output/environmental_sounds"
                    },
                },
            ]
        )
        out = rewire_graph_outputs(graph, slug="environmental-sounds")
        from app.core.workspace_paths import _PATH_KEYS

        def walk(obj, key=""):
            if isinstance(obj, str):
                if key in _PATH_KEYS:
                    assert "examples/" not in obj.replace("\\", "/")
            elif isinstance(obj, dict):
                for k, v in obj.items():
                    walk(v, k)
            elif isinstance(obj, list):
                for item in obj:
                    walk(item, key)

        walk(out)

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
                    "config": {"path": "workspace/datasets/input/speech-commands/yes"},
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
        assert out["nodes"][0]["config"]["path"] == (
            "workspace/datasets/input/speech-commands/yes"
        )
        assert out["nodes"][1]["config"]["model_path"] == (
            "workspace/artifacts/speech-commands/latest/tflite/model.tflite"
        )
        assert out["nodes"][2]["config"]["path"] == (
            "workspace/artifacts/speech-commands/dataset/speech_commands/v1"
        )



    def test_dataset_exporter_not_scoped_into_runs(self):
        graph = _graph(
            [
                {
                    "id": "exp",
                    "node_type": "audio_exporter",
                    "config": {
                        "output_dir": "workspace/artifacts/speech-commands/dataset/speech_commands"
                    },
                },
                {
                    "id": "trainer",
                    "node_type": "trainer",
                    "config": {"output_path": "workspace/artifacts/speech-commands"},
                },
            ]
        )
        from app.core.workspace_paths import scope_outputs_to_run

        out = scope_outputs_to_run(graph, "abc123")
        assert out["nodes"][0]["config"]["output_dir"] == (
            "workspace/artifacts/speech-commands/dataset/speech_commands"
        )
        assert out["nodes"][1]["config"]["output_path"] == (
            "workspace/artifacts/speech-commands/runs/abc123"
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


class TestResolveIngestDir:
    def test_missing_latest_falls_back_to_bundled_speech_commands(self, tmp_path, monkeypatch):
        data = tmp_path / "examples" / "02_speech_commands" / "data"
        data.mkdir(parents=True)
        yes = data / "yes"
        yes.mkdir()
        (yes / "clip.wav").write_bytes(b"RIFF")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path / "workspace"))
        (tmp_path / "workspace").mkdir()
        from app.core.workspace_paths import resolve_ingest_dir
        # monkeypatch examples_dir
        import app.core.example_templates as et
        monkeypatch.setattr(et, "repo_root", lambda: tmp_path)
        monkeypatch.setattr(et, "examples_dir", lambda: tmp_path / "examples")
        found = resolve_ingest_dir(
            "workspace/artifacts/speech-commands/latest/dataset/speech_commands/v1"
        )
        assert found == data

    def test_empty_workspace_input_falls_back_to_examples_data(self, tmp_path, monkeypatch):
        data = tmp_path / "examples" / "02_speech_commands" / "data" / "yes"
        data.mkdir(parents=True)
        (data / "clip.wav").write_bytes(b"RIFF")
        ws = tmp_path / "workspace"
        empty = ws / "datasets" / "input" / "speech-commands" / "yes"
        empty.mkdir(parents=True)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(ws))
        import app.core.example_templates as et
        from app.core.workspace_paths import resolve_ingest_dir

        monkeypatch.setattr(et, "repo_root", lambda: tmp_path)
        monkeypatch.setattr(et, "examples_dir", lambda: tmp_path / "examples")
        found = resolve_ingest_dir("workspace/datasets/input/speech-commands/yes")
        assert found == data


class TestRewriteGraphPaths:
    def test_rewrite_graph_paths_rewires_ingest_and_outputs(self):
        from app.core.example_templates import rewrite_graph_paths

        graph = _graph(
            [
                {
                    "id": "ingest",
                    "node_type": "dataset_ingest",
                    "config": {"path": "examples/02_speech_commands/data/go"},
                },
                {
                    "id": "exp",
                    "node_type": "audio_exporter",
                    "config": {"output_dir": "examples/02_speech_commands/output/speech_commands"},
                },
            ]
        )
        out = rewrite_graph_paths(graph, slug="ex-02-speech-commands")
        assert out["nodes"][0]["config"]["path"] == (
            "workspace/datasets/input/speech-commands/go"
        )
        assert out["nodes"][1]["config"]["output_dir"] == (
            "workspace/artifacts/speech-commands/speech_commands"
        )
        assert "examples/" not in out["nodes"][0]["config"]["path"]
        assert "examples/" not in out["nodes"][1]["config"]["output_dir"]


class TestSeedExampleInputDatasets:
    def test_symlinks_example_data_into_workspace_input(self, tmp_path, monkeypatch):
        examples = tmp_path / "examples"
        src = examples / "02_speech_commands" / "data" / "yes"
        src.mkdir(parents=True)
        (src / "clip.wav").write_bytes(b"RIFF")
        ws = tmp_path / "workspace"
        ws.mkdir()
        monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(ws))
        import app.core.example_templates as et

        monkeypatch.setattr(et, "examples_dir", lambda: examples)
        seeded = et.seed_example_input_datasets()
        dest = ws / "datasets" / "input" / "speech-commands"
        assert "speech-commands" in seeded
        assert dest.exists()
        assert (dest / "yes" / "clip.wav").is_file()
        # exist_ok: second call does not raise
        again = et.seed_example_input_datasets()
        assert "speech-commands" in again
