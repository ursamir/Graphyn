# PluginPackage/Common/trainer/model_architecture.py
"""Paper-documented Keras presets and a custom layer-spec compiler for ModelBuilderNode.

Presets (topology from the papers; depth/width remain user-tunable):
  - ds_cnn    — Hello Edge / DS-CNN (Zhang et al., 2017)
  - mobilenet — MobileNetV2 inverted residuals (Sandler et al., 2018)
  - simple_cnn — non-paper baseline (two conv+pool stacks)

Custom:
  - architecture=\"custom\" + layers=[{type, ...}, ...] compiled by build_from_layer_specs.
  - export_layer_specs() is the single source of truth for \"Load from preset\".
"""

from __future__ import annotations

import logging
from typing import Any, Mapping, Sequence

log = logging.getLogger(__name__)

PRESET_ARCHITECTURES = ("ds_cnn", "mobilenet", "simple_cnn")
ALL_ARCHITECTURES = (*PRESET_ARCHITECTURES, "custom")

SUPPORTED_LAYER_TYPES = frozenset(
    {
        "conv2d",
        "depthwise_conv2d",
        "batch_norm",
        "relu",
        "relu6",
        "max_pool2d",
        "avg_pool2d",
        "global_avg_pool2d",
        "dropout",
        "dense",
        "inverted_residual",
        "ds_separable_block",
    }
)


def _as_int_pair(value: Any, default: tuple[int, int] = (3, 3)) -> tuple[int, int]:
    if value is None:
        return default
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return int(value[0]), int(value[1])
    if isinstance(value, int):
        return int(value), int(value)
    raise ValueError(f"Expected int or [h, w] for kernel/strides, got {value!r}")


def _as_stride(value: Any, default: int = 1) -> int | tuple[int, int]:
    if value is None:
        return default
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return int(value[0]), int(value[1])
    return int(value)


def validate_layer_spec(spec: Mapping[str, Any], *, index: int) -> dict[str, Any]:
    """Fail-closed validation for one custom layer dict."""
    if not isinstance(spec, Mapping):
        raise ValueError(f"layers[{index}]: expected object/dict, got {type(spec).__name__}")
    layer_type = str(spec.get("type") or "").strip().lower()
    if not layer_type:
        raise ValueError(f"layers[{index}]: missing required 'type'")
    if layer_type not in SUPPORTED_LAYER_TYPES:
        raise ValueError(
            f"layers[{index}]: unknown type {layer_type!r}. "
            f"Supported: {', '.join(sorted(SUPPORTED_LAYER_TYPES))}"
        )
    out = dict(spec)
    out["type"] = layer_type
    if layer_type in ("conv2d", "depthwise_conv2d", "ds_separable_block", "inverted_residual"):
        if layer_type in ("conv2d", "ds_separable_block", "inverted_residual") and "filters" not in out:
            raise ValueError(f"layers[{index}] ({layer_type}): 'filters' is required")
        if "filters" in out and int(out["filters"]) < 1:
            raise ValueError(f"layers[{index}]: filters must be >= 1")
    if layer_type == "dense" and "units" not in out:
        raise ValueError(f"layers[{index}] (dense): 'units' is required")
    if layer_type == "dropout" and "rate" not in out:
        raise ValueError(f"layers[{index}] (dropout): 'rate' is required")
    if "strides" in out:
        _as_stride(out["strides"])
    if "kernel_size" in out:
        _as_int_pair(out["kernel_size"])
    if "padding" in out and str(out["padding"]).lower() not in ("same", "valid"):
        raise ValueError(f"layers[{index}]: padding must be 'same' or 'valid'")
    return out


def validate_layers(layers: Sequence[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    if not layers:
        raise ValueError(
            "ModelBuilderNode: architecture='custom' requires a non-empty 'layers' list. "
            "Use Load from preset in the Builder, or paste a layer JSON array."
        )
    return [validate_layer_spec(spec, index=i) for i, spec in enumerate(layers)]


def export_layer_specs(
    architecture: str,
    *,
    filters: int = 64,
    num_layers: int = 4,
    expansion_factor: int = 6,
    stem_stride: int = 2,
    dropout_rate: float = 0.25,
) -> list[dict[str, Any]]:
    """Export the body layer list for a preset (same list custom would execute).

    Head (global average pool → dropout → softmax dense) is applied by the
    compiler for presets and for custom bodies that omit a classifier.
    ``dropout_rate`` is recorded on a trailing marker only when the caller
    wants docs/fixtures; the live head still uses the config dropout.
    """
    arch = str(architecture or "").strip().lower()
    if arch not in PRESET_ARCHITECTURES:
        raise ValueError(
            f"export_layer_specs: architecture must be one of {PRESET_ARCHITECTURES}, got {architecture!r}"
        )
    filters = int(filters)
    num_layers = int(num_layers)
    expansion_factor = int(expansion_factor)
    stem_stride = int(stem_stride)
    if filters < 1:
        raise ValueError("filters must be >= 1")
    if num_layers < 0:
        raise ValueError("num_layers must be >= 0")
    if expansion_factor < 1:
        raise ValueError("expansion_factor must be >= 1")
    if stem_stride < 1:
        raise ValueError("stem_stride must be >= 1")

    if arch == "ds_cnn":
        # Hello Edge / DS-CNN (Zhang et al., 2017): stem Conv → DS blocks.
        layers: list[dict[str, Any]] = [
            {"type": "conv2d", "filters": filters, "kernel_size": 3, "strides": 1, "padding": "same", "use_bias": True},
            {"type": "batch_norm"},
            {"type": "relu"},
        ]
        for _ in range(num_layers):
            layers.append({"type": "ds_separable_block", "filters": filters, "kernel_size": 3, "padding": "same"})
        return layers

    if arch == "mobilenet":
        # MobileNetV2 (Sandler et al., 2018): stem stride-s Conv → inverted residuals.
        # Per-block stride: stride 2 on odd block indices (1, 3, …); residual only
        # when shapes match (stride 1 and same channel count).
        base = filters
        width = filters
        layers = [
            {
                "type": "conv2d",
                "filters": width,
                "kernel_size": 3,
                "strides": stem_stride,
                "padding": "same",
                "use_bias": False,
            },
            {"type": "batch_norm"},
            {"type": "relu6"},
        ]
        for i in range(num_layers):
            stride = 2 if (i % 2 == 1) else 1
            out_ch = min(width * 2, base * 4) if stride == 2 else width
            layers.append(
                {
                    "type": "inverted_residual",
                    "filters": out_ch,
                    "expansion_factor": expansion_factor,
                    "stride": stride,
                    "kernel_size": 3,
                    "use_bias": False,
                }
            )
            width = out_ch
        return layers

    # simple_cnn — non-paper baseline
    _ = dropout_rate  # head dropout applied by compiler
    return [
        {"type": "conv2d", "filters": filters, "kernel_size": 3, "padding": "same", "activation": "relu"},
        {"type": "max_pool2d", "pool_size": 2},
        {"type": "conv2d", "filters": filters * 2, "kernel_size": 3, "padding": "same", "activation": "relu"},
        {"type": "max_pool2d", "pool_size": 2},
    ]


def _apply_layer(keras: Any, x: Any, spec: Mapping[str, Any], *, index: int) -> Any:
    t = spec["type"]
    padding = str(spec.get("padding") or "same").lower()
    use_bias = bool(spec.get("use_bias", True))

    if t == "conv2d":
        filters = int(spec["filters"])
        kernel = _as_int_pair(spec.get("kernel_size"), (3, 3))
        strides = _as_stride(spec.get("strides"), 1)
        activation = spec.get("activation")
        kwargs: dict[str, Any] = {
            "filters": filters,
            "kernel_size": kernel,
            "strides": strides,
            "padding": padding,
            "use_bias": use_bias,
        }
        if activation:
            kwargs["activation"] = str(activation)
        return keras.layers.Conv2D(**kwargs)(x)

    if t == "depthwise_conv2d":
        kernel = _as_int_pair(spec.get("kernel_size"), (3, 3))
        strides = _as_stride(spec.get("strides"), 1)
        return keras.layers.DepthwiseConv2D(
            kernel_size=kernel,
            strides=strides,
            padding=padding,
            use_bias=use_bias,
        )(x)

    if t == "batch_norm":
        return keras.layers.BatchNormalization()(x)

    if t == "relu":
        return keras.layers.ReLU()(x)

    if t == "relu6":
        return keras.layers.ReLU(6.0)(x)

    if t == "max_pool2d":
        pool = _as_int_pair(spec.get("pool_size"), (2, 2))
        strides = _as_stride(spec.get("strides"), pool)
        return keras.layers.MaxPooling2D(pool_size=pool, strides=strides, padding=padding)(x)

    if t == "avg_pool2d":
        pool = _as_int_pair(spec.get("pool_size"), (2, 2))
        strides = _as_stride(spec.get("strides"), pool)
        return keras.layers.AveragePooling2D(pool_size=pool, strides=strides, padding=padding)(x)

    if t == "global_avg_pool2d":
        return keras.layers.GlobalAveragePooling2D()(x)

    if t == "dropout":
        return keras.layers.Dropout(float(spec["rate"]))(x)

    if t == "dense":
        units = int(spec["units"])
        activation = spec.get("activation")
        kwargs = {"units": units}
        if activation is not None:
            kwargs["activation"] = str(activation)
        return keras.layers.Dense(**kwargs)(x)

    if t == "ds_separable_block":
        # Hello Edge separable: DW 3×3 → BN → ReLU → PW 1×1 → BN → ReLU
        filters = int(spec["filters"])
        kernel = _as_int_pair(spec.get("kernel_size"), (3, 3))
        x = keras.layers.DepthwiseConv2D(kernel, padding=padding, use_bias=use_bias)(x)
        x = keras.layers.BatchNormalization()(x)
        x = keras.layers.ReLU()(x)
        x = keras.layers.Conv2D(filters, (1, 1), padding="same", use_bias=use_bias)(x)
        x = keras.layers.BatchNormalization()(x)
        x = keras.layers.ReLU()(x)
        return x

    if t == "inverted_residual":
        # MobileNetV2 inverted residual (Sandler et al., 2018).
        out_filters = int(spec["filters"])
        expansion = int(spec.get("expansion_factor") or 6)
        stride = int(spec.get("stride") or spec.get("strides") or 1)
        kernel = _as_int_pair(spec.get("kernel_size"), (3, 3))
        in_ch = int(x.shape[-1])
        expanded = max(in_ch * expansion, out_filters)
        shortcut = x
        x = keras.layers.Conv2D(expanded, (1, 1), padding="same", use_bias=False)(x)
        x = keras.layers.BatchNormalization()(x)
        x = keras.layers.ReLU(6.0)(x)
        x = keras.layers.DepthwiseConv2D(
            kernel, strides=stride, padding=padding, use_bias=False
        )(x)
        x = keras.layers.BatchNormalization()(x)
        x = keras.layers.ReLU(6.0)(x)
        x = keras.layers.Conv2D(out_filters, (1, 1), padding="same", use_bias=False)(x)
        x = keras.layers.BatchNormalization()(x)
        if stride == 1 and in_ch == out_filters:
            x = keras.layers.Add()([shortcut, x])
        return x

    raise ValueError(f"layers[{index}]: unsupported type {t!r}")


def _layers_include_classifier(layers: Sequence[Mapping[str, Any]]) -> bool:
    return any(str(s.get("type", "")).lower() == "dense" for s in layers)


def _layers_include_gap(layers: Sequence[Mapping[str, Any]]) -> bool:
    return any(str(s.get("type", "")).lower() == "global_avg_pool2d" for s in layers)


def build_from_layer_specs(
    layers: Sequence[Mapping[str, Any]],
    input_shape: tuple,
    n_classes: int,
    *,
    dropout_rate: float = 0.25,
    learning_rate: float = 0.001,
    append_classifier_head: bool | None = None,
):
    """Compile a Keras model from a validated layer-spec list."""
    import keras

    validated = validate_layers(layers)
    if append_classifier_head is None:
        append_classifier_head = not _layers_include_classifier(validated)

    inputs = keras.Input(shape=input_shape)
    x = inputs
    for i, spec in enumerate(validated):
        x = _apply_layer(keras, x, spec, index=i)

    if append_classifier_head:
        if not _layers_include_gap(validated):
            x = keras.layers.GlobalAveragePooling2D()(x)
        x = keras.layers.Dropout(float(dropout_rate))(x)
        x = keras.layers.Dense(int(n_classes), activation="softmax")(x)

    model = keras.Model(inputs, x)
    model.compile(
        optimizer=keras.optimizers.Adam(learning_rate=float(learning_rate)),
        loss="sparse_categorical_crossentropy",
        metrics=["accuracy"],
    )
    return model


def build_preset_model(
    architecture: str,
    input_shape: tuple,
    n_classes: int,
    *,
    filters: int = 64,
    num_layers: int = 4,
    expansion_factor: int = 6,
    stem_stride: int = 2,
    dropout_rate: float = 0.25,
    learning_rate: float = 0.001,
):
    """Build a preset by exporting layer specs then compiling (single code path)."""
    specs = export_layer_specs(
        architecture,
        filters=filters,
        num_layers=num_layers,
        expansion_factor=expansion_factor,
        stem_stride=stem_stride,
        dropout_rate=dropout_rate,
    )
    return build_from_layer_specs(
        specs,
        input_shape,
        n_classes,
        dropout_rate=dropout_rate,
        learning_rate=learning_rate,
        append_classifier_head=True,
    )


def build_keras_model(
    *,
    architecture: str,
    input_shape: tuple,
    n_classes: int,
    filters: int = 64,
    num_layers: int = 4,
    expansion_factor: int = 6,
    stem_stride: int = 2,
    dropout_rate: float = 0.25,
    learning_rate: float = 0.001,
    layers: Sequence[Mapping[str, Any]] | None = None,
):
    """Dispatch for ModelBuilderNode."""
    arch = str(architecture or "").strip().lower()
    if arch == "custom":
        model = build_from_layer_specs(
            layers or [],
            input_shape,
            n_classes,
            dropout_rate=dropout_rate,
            learning_rate=learning_rate,
        )
    elif arch in PRESET_ARCHITECTURES:
        model = build_preset_model(
            arch,
            input_shape,
            n_classes,
            filters=filters,
            num_layers=num_layers,
            expansion_factor=expansion_factor,
            stem_stride=stem_stride,
            dropout_rate=dropout_rate,
            learning_rate=learning_rate,
        )
    else:
        raise ValueError(
            f"ModelBuilderNode: unknown architecture {architecture!r}. "
            f"Choose from: {', '.join(ALL_ARCHITECTURES)}"
        )
    log.info(
        "model_architecture: built %s — input_shape=%s n_classes=%d params=%d",
        arch,
        input_shape,
        n_classes,
        model.count_params(),
    )
    return model
