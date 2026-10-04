"""FeatureArray lists must round-trip as FeatureArray, never as AudioSample WAVs."""
import numpy as np

from app.models.audio_artifact_serializer import AudioSampleHandler
from app.models.audio_sample import AudioSample
from app.models.feature_array import FeatureArray
from app.models.feature_array_serializer import FeatureArrayHandler


def _features():
    return [
        FeatureArray(data=np.arange(12, dtype=np.float32).reshape(3, 4), label="yes",
                     source_path="/d/train/yes/a.wav", feature_type="mfcc", metadata={"split": "train"}),
        FeatureArray(data=np.ones((5, 4), dtype=np.float32), label="no",
                     source_path="/d/test/no/b.wav", feature_type="mfcc"),
    ]


def test_audio_handler_does_not_claim_feature_arrays():
    assert AudioSampleHandler().infer_type(_features()) is None


def test_audio_handler_still_claims_audio_samples():
    samples = [AudioSample(path="/x.wav", sample_rate=16000, data=np.zeros(10, dtype=np.float32))]
    assert AudioSampleHandler().infer_type(samples) == "audio_samples"
    assert FeatureArrayHandler().infer_type(samples) is None


def test_feature_arrays_round_trip(tmp_path):
    handler = FeatureArrayHandler()
    feats = _features()
    assert handler.infer_type(feats) == "feature_arrays"
    dest = tmp_path / "port_output"
    handler.serialize(feats, dest)
    back = handler.deserialize(dest)
    assert [type(f) for f in back] == [FeatureArray, FeatureArray]
    assert [f.source_path for f in back] == [f.source_path for f in feats]
    assert back[0].metadata == {"split": "train"}
    np.testing.assert_array_equal(back[0].data, feats[0].data)
    assert back[1].data.shape == (5, 4)
    assert handler.compute_content_hash_input(back) == handler.compute_content_hash_input(feats)


def test_missing_npz_is_cache_miss(tmp_path):
    handler = FeatureArrayHandler()
    dest = tmp_path / "p"
    handler.serialize(_features(), dest)
    (dest / "features.npz").unlink()
    assert handler.deserialize(dest) is None
