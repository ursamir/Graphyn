"""AudioAnnotatorNode — attach semantic labels and annotations to audio samples.

Modes:
    passthrough  — preserve existing labels, enrich metadata
    auto         — apply rule-based labeling from auto_rules config
    taxonomy     — map raw labels to a canonical taxonomy
    weak         — assign confidence-weighted labels
"""
from __future__ import annotations

import copy
import logging
import operator
import re
from typing import ClassVar

import numpy as np

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort
from app.models.audio_sample import AudioSample

log = logging.getLogger(__name__)

# Supported comparison operators for auto_rules
_OPS: dict[str, object] = {
    ">":  operator.gt,
    ">=": operator.ge,
    "<":  operator.lt,
    "<=": operator.le,
    "==": operator.eq,
    "!=": operator.ne,
}


class AudioAnnotatorNode(Node):
    """Attach semantic labels and annotations to audio samples.

    Modes:
        passthrough  — preserve existing labels, add annotation metadata
        auto         — apply rule-based labeling from ``auto_rules``
        taxonomy     — map raw labels to canonical labels via ``taxonomy``
        weak         — assign confidence-weighted labels from ``weak_labels``

    Config:
        annotation_mode (str): one of passthrough | auto | taxonomy | weak
        taxonomy (dict): raw_label → canonical_label mapping
        confidence_threshold (float): minimum confidence to accept a weak label
        auto_rules (list[dict]): rules for auto mode — each rule is a dict:
            {
                "field":  "duration" | "rms" | "label" | "path" | <metadata_key>,
                "op":     ">" | ">=" | "<" | "<=" | "==" | "!=" | "contains" | "matches",
                "value":  <threshold or string>,
                "label":  <label to assign if rule matches>,
                "confidence": <float, default 1.0>
            }
        weak_labels (list[dict]): for weak mode — each entry:
            {
                "label": str,
                "confidence": float,
                "source": str   # optional provenance
            }
            Applied to all samples uniformly; per-sample weak labels can be
            passed via sample.metadata["weak_labels"].
        propagate_metadata (bool): merge upstream metadata into annotation dict
    """

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="audio_annotator",
        label="Audio Annotator",
        description=(
            "Attach semantic labels and annotations to audio samples. "
            "Supports passthrough, rule-based auto-labeling, taxonomy mapping, "
            "and confidence-weighted weak labeling."
        ),
        category="Preprocessing",
        version="1.0.0",
        tags=["audio", "annotation", "labeling", "taxonomy", "weak-supervision"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=True,
        streaming_support=False,
        realtime_support=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(
            name="input",
            data_type=list[AudioSample],
            cardinality="single",
            required=True,
            description="Audio samples to annotate",
        )
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(
            name="output",
            data_type=list[AudioSample],
            description="Annotated audio samples with enriched metadata",
        )
    }

    class Config(NodeConfig):
        annotation_mode: str = "passthrough"  # "passthrough" | "auto" | "taxonomy" | "weak"
        taxonomy: dict = {}
        confidence_threshold: float = 0.5
        auto_rules: list = []
        # auto_rules evaluation: first matching rule wins (short-circuit).
        # Each rule dict: {"field": str, "op": str, "value": any, "label": str, "confidence": float}
        weak_labels: list = []
        propagate_metadata: bool = True

    # ── SISO process ──────────────────────────────────────────────────────────

    def process(self, samples: list[AudioSample]) -> list[AudioSample]:
        if samples is None:
            return []
        mode = self.config.annotation_mode
        output: list[AudioSample] = []

        for sample in samples:
            new_sample = copy.deepcopy(sample)

            if mode == "passthrough":
                new_sample = self._annotate_passthrough(new_sample)
            elif mode == "auto":
                new_sample = self._annotate_auto(new_sample)
            elif mode == "taxonomy":
                new_sample = self._annotate_taxonomy(new_sample)
            elif mode == "weak":
                new_sample = self._annotate_weak(new_sample)
            else:
                raise ValueError(
                    f"AudioAnnotatorNode: unknown annotation_mode '{mode}'. "
                    "Choose from: passthrough, auto, taxonomy, weak"
                )

            output.append(new_sample)

        return output

    # ── passthrough mode ──────────────────────────────────────────────────────

    def _annotate_passthrough(self, sample: AudioSample) -> AudioSample:
        """Preserve existing label; enrich metadata with annotation record."""
        annotation: dict = {
            "mode": "passthrough",
            "label": sample.label,
            "confidence": 1.0,
        }
        if self.config.propagate_metadata:
            # Only propagate scalar values to avoid unbounded metadata growth
            annotation["upstream_metadata"] = {
                k: v for k, v in sample.metadata.items()
                if isinstance(v, (str, int, float, bool))
            }

        sample.metadata["annotation"] = annotation
        return sample

    # ── auto (rule-based) mode ────────────────────────────────────────────────

    def _annotate_auto(self, sample: AudioSample) -> AudioSample:
        """Apply rule-based labeling. First matching rule wins."""
        matched_label: str | None = None
        matched_confidence: float = 1.0
        matched_rule: dict | None = None

        for rule in self.config.auto_rules:
            if self._rule_matches(rule, sample):
                matched_label = str(rule.get("label", ""))
                matched_confidence = float(rule.get("confidence", 1.0))
                matched_rule = rule
                break

        if matched_label is not None and matched_label != "":
            sample.label = matched_label
            sample.metadata["annotation"] = {
                "mode": "auto",
                "label": matched_label,
                "confidence": matched_confidence,
                "rule": matched_rule,
            }
        elif matched_label == "":
            log.warning(
                "AudioAnnotatorNode: rule matched but 'label' is empty — skipping label assignment"
            )
            sample.metadata["annotation"] = {
                "mode": "auto",
                "label": sample.label,
                "confidence": matched_confidence,
                "rule": matched_rule,
                "note": "rule matched but label was empty string",
            }
        else:
            # No rule matched — keep existing label
            sample.metadata["annotation"] = {
                "mode": "auto",
                "label": sample.label,
                "confidence": 1.0,
                "rule": None,
                "note": "no rule matched",
            }

        return sample

    def _rule_matches(self, rule: dict, sample: AudioSample) -> bool:
        """Evaluate a single rule against a sample. Returns True if it matches."""
        field = rule.get("field")
        if not field:
            log.warning(
                "AudioAnnotatorNode: rule missing 'field' key — skipping: %s", rule
            )
            return False
        op = rule.get("op", "==")
        value = rule.get("value")

        # Resolve field value
        actual = self._resolve_field(field, sample)
        if actual is None:
            return False

        # String operators
        if op == "contains":
            return str(value) in str(actual)
        if op == "matches":
            try:
                return bool(re.search(str(value), str(actual)))
            except re.error:
                return False

        # Numeric / equality operators — try float coercion first, then string
        op_fn = _OPS.get(op)
        if op_fn is None:
            log.warning("AudioAnnotatorNode: unknown operator '%s' in rule — skipping", op)
            return False

        # Try numeric comparison first (handles int/float fields with string config values)
        try:
            actual_num = float(actual)
            value_num = float(value)
            return bool(op_fn(actual_num, value_num))
        except (TypeError, ValueError):
            pass

        # Fall back to same-type coercion then string comparison
        try:
            return bool(op_fn(actual, type(actual)(value)))
        except (TypeError, ValueError):
            try:
                return bool(op_fn(str(actual), str(value)))
            except Exception:
                return False

    def _resolve_field(self, field: str, sample: AudioSample):
        """Resolve a field name to its value on the sample."""
        if field == "duration":
            sr = sample.sample_rate or 1
            return len(sample.data) / sr if sample.data is not None else 0.0
        if field == "rms":
            if sample.data is not None and len(sample.data) > 0:
                return float(np.sqrt(np.mean(sample.data.astype(np.float32) ** 2)))
            return 0.0
        if field == "label":
            return sample.label
        if field == "path":
            return str(sample.path)
        if field == "sample_rate":
            return sample.sample_rate
        # Fall back to metadata lookup
        return sample.metadata.get(field)

    # ── taxonomy mode ─────────────────────────────────────────────────────────

    def _annotate_taxonomy(self, sample: AudioSample) -> AudioSample:
        """Map raw label to canonical taxonomy label."""
        raw_label = sample.label
        canonical = self.config.taxonomy.get(raw_label)

        if canonical is not None:
            sample.label = str(canonical)
            sample.metadata["annotation"] = {
                "mode": "taxonomy",
                "raw_label": raw_label,
                "canonical_label": str(canonical),
                "confidence": 1.0,
            }
        else:
            # No mapping found — keep raw label, flag it
            log.debug(
                "AudioAnnotatorNode: no taxonomy mapping for label '%s' — keeping as-is",
                raw_label,
            )
            sample.metadata["annotation"] = {
                "mode": "taxonomy",
                "raw_label": raw_label,
                "canonical_label": raw_label,
                "confidence": 1.0,
                "note": "no taxonomy mapping found",
            }

        return sample

    # ── weak labeling mode ────────────────────────────────────────────────────

    def _annotate_weak(self, sample: AudioSample) -> AudioSample:
        """Assign confidence-weighted labels.

        Merges config-level weak_labels with per-sample metadata["weak_labels"].
        Accepts labels above confidence_threshold; picks the highest-confidence
        accepted label as the primary label.
        """
        # Merge config-level and per-sample weak labels
        all_weak: list[dict] = list(self.config.weak_labels)
        per_sample = sample.metadata.get("weak_labels", [])
        if isinstance(per_sample, list):
            all_weak.extend(per_sample)

        threshold = self.config.confidence_threshold

        def _safe_confidence(w: dict) -> float:
            try:
                return float(w.get("confidence", 0.0))
            except (TypeError, ValueError):
                return 0.0

        accepted = [
            w for w in all_weak
            if _safe_confidence(w) >= threshold
        ]

        if accepted:
            # Sort by confidence descending; pick top label
            accepted.sort(key=lambda w: _safe_confidence(w), reverse=True)
            best = accepted[0]
            sample.label = str(best.get("label", sample.label))
            sample.metadata["annotation"] = {
                "mode": "weak",
                "assigned_label": sample.label,
                "confidence": float(best.get("confidence", 1.0)),
                "all_labels": accepted,
                "threshold": threshold,
            }
        else:
            sample.metadata["annotation"] = {
                "mode": "weak",
                "assigned_label": sample.label,
                "confidence": 0.0,
                "all_labels": all_weak,
                "threshold": threshold,
                "note": "no label met confidence threshold",
            }

        return sample
