# Functional Review — PluginPackage/Audio/audio_annotator/nodes.py

**Group:** 14 — Audio Plugins Batch 2
**Reviewed:** 2026-05-26
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/audio_annotator/nodes.py
FUNCTION:    AudioAnnotatorNode.process
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Iterates over all samples and applies the configured annotation mode.

WHAT IT ACTUALLY DOES:
When `samples` is an empty list, the function returns an empty list without
error — this is correct. However, when `samples` is `None` (e.g., upstream
node returns None instead of []), the `for sample in samples` loop raises
`TypeError: 'NoneType' object is not iterable` with no domain-level error
message.

THE BUG / RISK:
If an upstream node returns None instead of an empty list (a known risk
documented in Group 6 findings), this node crashes with a generic TypeError
rather than a clear domain error.

EVIDENCE:
```python
def process(self, samples: list[AudioSample]) -> list[AudioSample]:
    ...
    for sample in samples:  # line ~118 — no None guard
```

REPRODUCTION SCENARIO:
upstream_node.process() returns None
audio_annotator.process(None) → TypeError: 'NoneType' object is not iterable

IMPACT:
Crash with opaque error message; no indication of which upstream node produced None.

FIX DIRECTION:
```python
if samples is None:
    return []
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/audio_annotator/nodes.py
FUNCTION:    AudioAnnotatorNode._rule_matches
CATEGORY:    Silent Failure
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Evaluate a single rule against a sample. Returns True if it matches.

WHAT IT ACTUALLY DOES:
When the rule dict is missing the "field" key, `field` defaults to `""`.
`_resolve_field("", sample)` falls through all named field checks and calls
`sample.metadata.get("")`, which returns `None`. The function then returns
`False` (no match) silently — the rule is skipped without any warning.

Similarly, when the rule dict is missing the "op" key, `op` defaults to `"=="`.
This is a silent default that may produce unexpected matches.

THE BUG / RISK:
A misconfigured rule (missing "field" or "op") silently never matches instead
of raising a configuration error. Users debugging why their auto-labeling
isn't working will get no indication that their rule config is malformed.

EVIDENCE:
```python
field = rule.get("field", "")   # silent default
op = rule.get("op", "==")       # silent default
...
actual = self._resolve_field(field, sample)
if actual is None:
    return False  # silent skip
```

REPRODUCTION SCENARIO:
auto_rules = [{"op": ">", "value": 1.0, "label": "long"}]  # missing "field"
→ rule silently never matches; no warning logged

IMPACT:
Silent wrong result — auto-labeling rules are silently ignored when misconfigured.

FIX DIRECTION:
```python
field = rule.get("field")
if not field:
    log.warning("AudioAnnotatorNode: rule missing 'field' key — skipping: %s", rule)
    return False
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/audio_annotator/nodes.py
FUNCTION:    AudioAnnotatorNode._annotate_weak
CATEGORY:    Type Safety
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Merges config-level and per-sample weak_labels; accepts labels above confidence_threshold.

WHAT IT ACTUALLY DOES:
The `float(w.get("confidence", 0.0))` call in the list comprehension will raise
`ValueError` if a weak label entry has a non-numeric confidence value (e.g.,
`"high"` or `None`). This exception is not caught, so a single malformed weak
label entry in `sample.metadata["weak_labels"]` will crash the entire
`process()` call for that sample.

EVIDENCE:
```python
accepted = [
    w for w in all_weak
    if float(w.get("confidence", 0.0)) >= threshold  # raises on non-numeric
]
```

REPRODUCTION SCENARIO:
sample.metadata["weak_labels"] = [{"label": "speech", "confidence": "high"}]
→ ValueError: could not convert string to float: 'high'

IMPACT:
Crash on malformed per-sample metadata; entire batch fails if one sample has
bad weak label data.

FIX DIRECTION:
```python
def _safe_confidence(w: dict) -> float:
    try:
        return float(w.get("confidence", 0.0))
    except (TypeError, ValueError):
        return 0.0

accepted = [w for w in all_weak if _safe_confidence(w) >= threshold]
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/audio_annotator/nodes.py
FUNCTION:    AudioAnnotatorNode._resolve_field
CATEGORY:    Edge Case
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Resolve a field name to its value on the sample.

WHAT IT ACTUALLY DOES:
For `field == "duration"`, computes `len(sample.data) / sr` where
`sr = sample.sample_rate or 1`. If `sample.data` is `None`, `len(None)` raises
`TypeError`. The `if sample.data is not None` guard only applies to the `rms`
field, not the `duration` field.

EVIDENCE:
```python
if field == "duration":
    sr = sample.sample_rate or 1
    return len(sample.data) / sr if sample.data is not None else 0.0
```
Wait — re-reading: `if sample.data is not None else 0.0` IS present for duration.
This is actually correct. Retracting this finding.

No finding for _resolve_field duration path.

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/audio_annotator/nodes.py
FUNCTION:    AudioAnnotatorNode._annotate_auto
CATEGORY:    State Bug
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Apply rule-based labeling. First matching rule wins.

WHAT IT ACTUALLY DOES:
When a rule matches and `matched_label = str(rule.get("label", ""))`, if the
rule dict has `"label": ""` (empty string), `matched_label` is `""` (truthy
check: `if matched_label is not None` passes since `""` is not None), so the
sample's label is set to an empty string. This is a silent data corruption —
the sample gets an empty label with no warning.

EVIDENCE:
```python
matched_label = str(rule.get("label", ""))
...
if matched_label is not None:  # "" passes this check
    sample.label = matched_label  # label set to ""
```

REPRODUCTION SCENARIO:
auto_rules = [{"field": "duration", "op": ">", "value": 0.5, "label": ""}]
→ all samples longer than 0.5s get label=""

IMPACT:
Silent data corruption — samples get empty string labels.

FIX DIRECTION:
```python
if matched_label is not None and matched_label != "":
    sample.label = matched_label
else:
    log.warning("AudioAnnotatorNode: rule matched but 'label' is empty — skipping label assignment")
```

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | MEDIUM |
| Silent Failures | 2 |
| Error Handling | PARTIAL |
| Async Safety | N/A |
| State Safety | SAFE |
| Resource Safety | SAFE |
| Test Hostile | NO |
| Top Risk | `_rule_matches` silently ignores misconfigured rules (missing "field" key) with no warning, making auto-labeling failures invisible to users. |
