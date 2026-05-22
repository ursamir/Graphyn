# PluginPackage/Common/trainer/nodes.py
"""TrainerNode — unified model training orchestration for Keras and PyTorch.

Migrated from app/core/nodes/ml/model_trainer.py and expanded with:
  - PyTorch training loop with EarlyStopping and Adam optimizer
  - Mixed precision support (Keras mixed_float16 / torch.cuda.amp.autocast)
  - Backend auto-detection (prefers Keras/TF if available, else PyTorch)
  - DatasetArtifact input (accessed by attribute name at runtime)
  - Configurable output path, patience, batch size, epochs

Import note: DatasetArtifact is accessed at runtime via attribute access on the
dataset input — we do NOT import it at module level to avoid coupling to the
dataset_builder plugin. The dataset port uses data_type=object.
"""
# NOTE: No `from __future__ import annotations` — avoids Pydantic forward-ref issues.

import logging
from pathlib import Path
from typing import ClassVar

import numpy as np

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort
from app.models.model_artifact import ModelArtifact

log = logging.getLogger(__name__)


class TrainerNode(Node):
    """Unified model training for Keras and PyTorch with EarlyStopping and checkpointing.

    Multi-port node: reads a compiled Keras model or PyTorch nn.Module from the
    'model' port and a DatasetArtifact from the 'dataset' port. Produces a
    ModelArtifact on the 'output' port.

    Backend selection:
        - "keras"   — always use Keras/TensorFlow
        - "pytorch" — always use PyTorch
        - "auto"    — prefer Keras if tensorflow is importable, else PyTorch

    Config options:
        backend          (str):   "keras" | "pytorch" | "auto". Default: "auto"
        epochs           (int):   Maximum training epochs. Default: 30
        batch_size       (int):   Training batch size. Default: 32
        output_path      (str):   Directory for model artifacts. Default: "workspace/artifacts/models"
        patience         (int):   EarlyStopping patience. Default: 5
        mixed_precision  (bool):  Enable mixed precision training. Default: False
        min_val_accuracy (float): Warn if best val_accuracy falls below this. Default: 0.0
        checkpoint_path  (str):   Path for best checkpoint (auto-derived if empty). Default: ""
    """

    node_type: ClassVar[str] = "trainer"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="trainer",
        label="Trainer",
        description="Unified model training for Keras and PyTorch with EarlyStopping and checkpointing.",
        category="ML",
        version="1.0.0",
        tags=["ml", "training", "keras", "pytorch", "common"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=False,
        deterministic=False,
        cacheable=False,
        streaming_support=False,
        realtime_support=False,
        memory_requirements="high",
        batch_support=True,
    )

    input_ports: ClassVar[dict] = {
        "model": InputPort(
            name="model",
            data_type=object,
            cardinality="single",
            required=True,
            description="Compiled keras.Model or PyTorch nn.Module.",
        ),
        "dataset": InputPort(
            name="dataset",
            data_type=object,
            cardinality="single",
            required=True,
            description="DatasetArtifact from DatasetBuilderNode.",
        ),
    }

    output_ports: ClassVar[dict] = {
        "output": OutputPort(
            name="output",
            data_type=ModelArtifact,
            description="ModelArtifact with model_path, labels, history.",
        )
    }

    class Config(NodeConfig):
        backend: str = "auto"           # "keras" | "pytorch" | "auto"
        epochs: int = 30
        batch_size: int = 32
        output_path: str = "workspace/artifacts/models"
        patience: int = 5
        mixed_precision: bool = False
        min_val_accuracy: float = 0.0
        checkpoint_path: str = ""

    # ── backend detection ─────────────────────────────────────────────────────

    def _detect_backend(self) -> str:
        """Determine which ML backend to use based on config and available packages."""
        if self.config.backend == "keras":
            return "keras"
        if self.config.backend == "pytorch":
            return "pytorch"
        # auto: prefer keras if tensorflow available, else pytorch
        try:
            import tensorflow  # noqa: F401
            return "keras"
        except ImportError:
            pass
        try:
            import torch  # noqa: F401
            return "pytorch"
        except ImportError:
            pass
        raise ImportError(
            "TrainerNode: no ML framework found. "
            "Install tensorflow (venv/bin/pip install tensorflow) or "
            "torch (venv/bin/pip install torch)."
        )

    # ── Keras training ────────────────────────────────────────────────────────

    def _train_keras(self, model, dataset, out_path: Path) -> ModelArtifact:
        """Train a Keras model with EarlyStopping, ModelCheckpoint, ReduceLROnPlateau.

        Saves:
          - <output_path>/model.keras          — best model in Keras format
          - <output_path>/saved_model/         — TF SavedModel export
          - <output_path>/saved_model/X_train_repr.npy — INT8 calibration data
        """
        import keras

        if self.config.mixed_precision:
            keras.mixed_precision.set_global_policy("mixed_float16")
            log.info("TrainerNode (keras): mixed_float16 precision enabled.")

        keras.utils.set_random_seed(self.seed)

        ckpt_path = self.config.checkpoint_path
        if not ckpt_path:
            ckpt_path = str(out_path / "checkpoints" / "best.keras")
        Path(ckpt_path).parent.mkdir(parents=True, exist_ok=True)

        callbacks = [
            keras.callbacks.EarlyStopping(
                monitor="val_loss",
                patience=self.config.patience,
                restore_best_weights=True,
                verbose=1,
            ),
            keras.callbacks.ModelCheckpoint(
                ckpt_path,
                monitor="val_accuracy",
                save_best_only=True,
                verbose=1,
            ),
            keras.callbacks.ReduceLROnPlateau(
                monitor="val_loss",
                factor=0.5,
                patience=3,
                verbose=1,
            ),
        ]

        log.info(
            "TrainerNode (keras): training for up to %d epochs (batch_size=%d)...",
            self.config.epochs, self.config.batch_size,
        )

        history = model.fit(
            dataset.X_train,
            dataset.y_train,
            validation_data=(dataset.X_val, dataset.y_val),
            epochs=self.config.epochs,
            batch_size=self.config.batch_size,
            callbacks=callbacks,
            verbose=1,
        )

        # Save in .keras format
        keras_model_path = str(out_path / "model.keras")
        model.save(keras_model_path)
        log.info("TrainerNode (keras): Keras model saved to: %s", keras_model_path)

        # Export as TF SavedModel for TFLite conversion
        saved_model_path = str(out_path / "saved_model")
        try:
            model.export(saved_model_path)  # Keras 3.x API
        except AttributeError:
            # Keras 2.x fallback
            import tensorflow as tf  # type: ignore
            tf.saved_model.save(model, saved_model_path)
        log.info("TrainerNode (keras): SavedModel exported to: %s", saved_model_path)

        # Save X_train representative data for INT8 TFLite calibration
        repr_path = str(out_path / "saved_model" / "X_train_repr.npy")
        np.save(repr_path, dataset.X_train)

        # Warn if val_accuracy is below threshold
        val_accs = history.history.get("val_accuracy", [0.0])
        best_val_acc = max(val_accs) if val_accs else 0.0
        if best_val_acc < self.config.min_val_accuracy:
            log.warning(
                "TrainerNode (keras): best val_accuracy %.4f is below "
                "min_val_accuracy %.4f",
                best_val_acc,
                self.config.min_val_accuracy,
            )

        return ModelArtifact(
            model_path=saved_model_path,
            labels=list(dataset.labels),
            history=dict(history.history),
            metrics={"keras_model_path": keras_model_path},
        )

    # ── PyTorch training ──────────────────────────────────────────────────────

    def _train_pytorch(self, model, dataset, out_path: Path) -> ModelArtifact:
        """Train a PyTorch nn.Module with Adam, CrossEntropyLoss, and EarlyStopping.

        Saves:
          - <output_path>/model.pt — model state dict
        """
        import torch
        import torch.nn as nn
        from torch.utils.data import DataLoader, TensorDataset

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model = model.to(device)

        # Build DataLoaders from dataset attributes
        X_train = torch.from_numpy(np.asarray(dataset.X_train, dtype=np.float32))
        y_train = torch.from_numpy(np.asarray(dataset.y_train, dtype=np.int64))
        X_val = torch.from_numpy(np.asarray(dataset.X_val, dtype=np.float32))
        y_val = torch.from_numpy(np.asarray(dataset.y_val, dtype=np.int64))

        train_loader = DataLoader(
            TensorDataset(X_train, y_train),
            batch_size=self.config.batch_size,
            shuffle=True,
        )
        val_loader = DataLoader(
            TensorDataset(X_val, y_val),
            batch_size=self.config.batch_size,
            shuffle=False,
        )

        optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
        criterion = nn.CrossEntropyLoss()

        # Mixed precision scaler (only meaningful on CUDA)
        use_amp = self.config.mixed_precision and torch.cuda.is_available()
        # Use torch.amp (PyTorch 2.x+); fall back to torch.cuda.amp for older versions
        try:
            scaler = torch.amp.GradScaler("cuda") if use_amp else None
        except TypeError:
            scaler = torch.cuda.amp.GradScaler() if use_amp else None  # type: ignore[attr-defined]
        if use_amp:
            log.info("TrainerNode (pytorch): AMP (autocast) enabled.")

        history: dict = {
            "loss": [],
            "val_loss": [],
            "accuracy": [],
            "val_accuracy": [],
        }

        # EarlyStopping state
        best_val_loss = float("inf")
        patience_counter = 0
        best_state: dict | None = None

        log.info(
            "TrainerNode (pytorch): training for up to %d epochs (batch_size=%d, device=%s)...",
            self.config.epochs, self.config.batch_size, device,
        )

        for epoch in range(self.config.epochs):
            # ── Training pass ─────────────────────────────────────────────────
            model.train()
            train_loss = 0.0
            train_correct = 0
            train_total = 0

            for X_batch, y_batch in train_loader:
                X_batch, y_batch = X_batch.to(device), y_batch.to(device)
                optimizer.zero_grad()

                if use_amp:
                    try:
                        ctx = torch.amp.autocast("cuda")
                    except TypeError:
                        ctx = torch.cuda.amp.autocast()  # type: ignore[attr-defined]
                    with ctx:
                        logits = model(X_batch)
                        loss = criterion(logits, y_batch)
                    scaler.scale(loss).backward()
                    scaler.step(optimizer)
                    scaler.update()
                else:
                    logits = model(X_batch)
                    loss = criterion(logits, y_batch)
                    loss.backward()
                    optimizer.step()

                train_loss += loss.item() * X_batch.size(0)
                preds = logits.argmax(dim=1)
                train_correct += (preds == y_batch).sum().item()
                train_total += X_batch.size(0)

            avg_train_loss = train_loss / max(train_total, 1)
            avg_train_acc = train_correct / max(train_total, 1)

            # ── Validation pass ───────────────────────────────────────────────
            model.eval()
            val_loss = 0.0
            val_correct = 0
            val_total = 0

            with torch.no_grad():
                for X_batch, y_batch in val_loader:
                    X_batch, y_batch = X_batch.to(device), y_batch.to(device)
                    if use_amp:
                        try:
                            ctx = torch.amp.autocast("cuda")
                        except TypeError:
                            ctx = torch.cuda.amp.autocast()  # type: ignore[attr-defined]
                        with ctx:
                            logits = model(X_batch)
                            loss = criterion(logits, y_batch)
                    else:
                        logits = model(X_batch)
                        loss = criterion(logits, y_batch)
                    val_loss += loss.item() * X_batch.size(0)
                    preds = logits.argmax(dim=1)
                    val_correct += (preds == y_batch).sum().item()
                    val_total += X_batch.size(0)

            avg_val_loss = val_loss / max(val_total, 1)
            avg_val_acc = val_correct / max(val_total, 1)

            history["loss"].append(avg_train_loss)
            history["val_loss"].append(avg_val_loss)
            history["accuracy"].append(avg_train_acc)
            history["val_accuracy"].append(avg_val_acc)

            log.info(
                "TrainerNode (pytorch): epoch %d/%d — loss=%.4f acc=%.4f val_loss=%.4f val_acc=%.4f",
                epoch + 1, self.config.epochs,
                avg_train_loss, avg_train_acc, avg_val_loss, avg_val_acc,
            )

            # ── EarlyStopping ─────────────────────────────────────────────────
            if avg_val_loss < best_val_loss:
                best_val_loss = avg_val_loss
                patience_counter = 0
                # Deep-copy state dict to CPU for safe storage
                best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
            else:
                patience_counter += 1
                if patience_counter >= self.config.patience:
                    log.info(
                        "TrainerNode (pytorch): EarlyStopping triggered at epoch %d (patience=%d).",
                        epoch + 1, self.config.patience,
                    )
                    break

        # Restore best weights
        if best_state is not None:
            model.load_state_dict(best_state)

        # Save model state dict
        pt_path = out_path / "model.pt"
        torch.save(model.state_dict(), str(pt_path))
        log.info("TrainerNode (pytorch): model saved to: %s", pt_path)

        # Warn if val_accuracy is below threshold
        val_accs = history.get("val_accuracy", [0.0])
        best_val_acc = max(val_accs) if val_accs else 0.0
        if best_val_acc < self.config.min_val_accuracy:
            log.warning(
                "TrainerNode (pytorch): best val_accuracy %.4f is below "
                "min_val_accuracy %.4f",
                best_val_acc,
                self.config.min_val_accuracy,
            )

        return ModelArtifact(
            model_path=str(pt_path),
            labels=list(dataset.labels),
            history=history,
        )

    # ── main process ─────────────────────────────────────────────────────────

    def process(self, inputs: dict) -> dict:
        """Train the model and return a ModelArtifact.

        Args:
            inputs: dict with keys:
                "model"   — compiled keras.Model or PyTorch nn.Module
                "dataset" — DatasetArtifact (accessed by attribute name)

        Returns:
            dict with key "output" → ModelArtifact
        """
        model = inputs["model"]
        dataset = inputs["dataset"]

        backend = self._detect_backend()

        out_path = Path(self.config.output_path)
        try:
            out_path.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise OSError(
                f"TrainerNode: cannot create output directory '{out_path}': {e}"
            ) from e

        if backend == "keras":
            artifact = self._train_keras(model, dataset, out_path)
        else:
            artifact = self._train_pytorch(model, dataset, out_path)

        return {"output": artifact}


class ModelBuilderNode(Node):
    """Build a compiled Keras or PyTorch model from a DatasetArtifact.

    Reads ``input_shape`` and ``n_classes`` from the incoming DatasetArtifact
    and constructs a model ready for training. This node bridges the gap between
    ``DatasetBuilderNode`` and ``TrainerNode`` in a fully pipeline-based workflow.

    Architectures (Keras):
        - ``ds_cnn``    — Depthwise Separable CNN (lightweight, edge-deployable)
        - ``mobilenet`` — MobileNet-V2 style (wider, higher accuracy)
        - ``simple_cnn`` — 2-layer CNN (fast baseline)

    Config:
        architecture (str): "ds_cnn" | "mobilenet" | "simple_cnn". Default: "ds_cnn"
        filters (int): Base filter count. Default: 64
        num_layers (int): Number of DS blocks (ds_cnn) or inverted residuals (mobilenet). Default: 4
        dropout_rate (float): Dropout before final Dense layer. Default: 0.25
        learning_rate (float): Adam learning rate. Default: 0.001
        backend (str): "keras" | "auto". Default: "auto"
    """

    node_type: ClassVar[str] = "model_builder"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="model_builder",
        label="Model Builder",
        description=(
            "Build a compiled Keras model from a DatasetArtifact. "
            "Supports DS-CNN, MobileNet, and simple CNN architectures."
        ),
        category="ML",
        version="1.0.0",
        tags=["ml", "model", "keras", "ds_cnn", "mobilenet", "common"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=False,
        deterministic=True,
        cacheable=False,  # always rebuild — model depends on dataset shape
        streaming_support=False,
        realtime_support=False,
    )

    input_ports: ClassVar[dict] = {
        "input": InputPort(
            name="input",
            data_type=object,
            cardinality="single",
            required=True,
            description="DatasetArtifact from DatasetBuilderNode.",
        )
    }

    output_ports: ClassVar[dict] = {
        "output": OutputPort(
            name="output",
            data_type=object,
            description="Compiled Keras model ready for TrainerNode.",
        )
    }

    class Config(NodeConfig):
        architecture: str = "ds_cnn"    # "ds_cnn" | "mobilenet" | "simple_cnn"
        filters: int = 64
        num_layers: int = 4
        dropout_rate: float = 0.25
        learning_rate: float = 0.001
        backend: str = "auto"           # "keras" | "auto"

    def _build_keras_model(self, input_shape: tuple, n_classes: int):
        """Build and compile a Keras model."""
        import keras

        arch = self.config.architecture
        filters = self.config.filters
        n_layers = self.config.num_layers
        dropout = self.config.dropout_rate
        lr = self.config.learning_rate

        inputs = keras.Input(shape=input_shape)

        if arch == "ds_cnn":
            x = keras.layers.Conv2D(filters, (3, 3), padding="same")(inputs)
            x = keras.layers.BatchNormalization()(x)
            x = keras.layers.ReLU()(x)
            for _ in range(n_layers):
                x = keras.layers.DepthwiseConv2D((3, 3), padding="same")(x)
                x = keras.layers.BatchNormalization()(x)
                x = keras.layers.ReLU()(x)
                x = keras.layers.Conv2D(filters, (1, 1), padding="same")(x)
                x = keras.layers.BatchNormalization()(x)
                x = keras.layers.ReLU()(x)

        elif arch == "mobilenet":
            x = keras.layers.Conv2D(filters, (3, 3), padding="same")(inputs)
            x = keras.layers.BatchNormalization()(x)
            x = keras.layers.ReLU(6.0)(x)
            for _ in range(n_layers):
                # Inverted residual block (simplified)
                expanded = filters * 6
                shortcut = x
                x = keras.layers.Conv2D(expanded, (1, 1), padding="same")(x)
                x = keras.layers.BatchNormalization()(x)
                x = keras.layers.ReLU(6.0)(x)
                x = keras.layers.DepthwiseConv2D((3, 3), padding="same")(x)
                x = keras.layers.BatchNormalization()(x)
                x = keras.layers.ReLU(6.0)(x)
                x = keras.layers.Conv2D(filters, (1, 1), padding="same")(x)
                x = keras.layers.BatchNormalization()(x)
                if shortcut.shape == x.shape:
                    x = keras.layers.Add()([shortcut, x])

        elif arch == "simple_cnn":
            x = keras.layers.Conv2D(filters, (3, 3), padding="same", activation="relu")(inputs)
            x = keras.layers.MaxPooling2D((2, 2))(x)
            x = keras.layers.Conv2D(filters * 2, (3, 3), padding="same", activation="relu")(x)
            x = keras.layers.MaxPooling2D((2, 2))(x)

        else:
            raise ValueError(
                f"ModelBuilderNode: unknown architecture '{arch}'. "
                "Choose from: ds_cnn, mobilenet, simple_cnn"
            )

        x = keras.layers.GlobalAveragePooling2D()(x)
        x = keras.layers.Dropout(dropout)(x)
        outputs = keras.layers.Dense(n_classes, activation="softmax")(x)

        model = keras.Model(inputs, outputs)
        model.compile(
            optimizer=keras.optimizers.Adam(learning_rate=lr),
            loss="sparse_categorical_crossentropy",
            metrics=["accuracy"],
        )

        n_params = model.count_params()
        log.info(
            "ModelBuilderNode: built %s — input_shape=%s n_classes=%d params=%d",
            arch, input_shape, n_classes, n_params,
        )
        return model

    def process(self, inputs: dict) -> dict:
        """Build a model from the dataset's input_shape and n_classes.

        Uses multi-port signature (inputs: dict) so the base class does not
        apply the SISO wrapper — avoids double-wrapping the return value.
        """
        dataset = inputs.get("input")
        backend = self.config.backend
        if backend == "auto":
            try:
                import tensorflow  # noqa: F401
                backend = "keras"
            except ImportError:
                raise ImportError(
                    "ModelBuilderNode: TensorFlow/Keras not found. "
                    "Install with: pip install tensorflow"
                )

        if backend == "keras":
            model = self._build_keras_model(dataset.input_shape, dataset.n_classes)
        else:
            raise ValueError(
                f"ModelBuilderNode: backend '{backend}' not supported. Use 'keras' or 'auto'."
            )

        return {"output": model}
