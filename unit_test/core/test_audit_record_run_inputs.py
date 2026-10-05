"""Run-input fingerprints and webhook receipts are sealed into the run record."""
from app.core.runs.audit_record import _run_input_fingerprints


def test_fingerprints_present_only_when_recorded():
    assert _run_input_fingerprints({}) is None
    meta = {"inputs_sha256": "ab", "input_keys": ["hook.body"], "inputs_bytes": 12, "parameter_names": []}
    assert _run_input_fingerprints(meta) == {"inputs_sha256": "ab", "input_keys": ["hook.body"], "inputs_bytes": 12}
