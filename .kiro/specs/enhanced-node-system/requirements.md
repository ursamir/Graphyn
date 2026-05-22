# Requirements Document — Enhanced Node System

## Introduction

This feature enhances the core `Node` base class and surrounding infrastructure in `app/core/nodes/` to support:

- **Auto-registration**: any node file dropped into the nodes folder (or a configured plugins directory) is discovered and registered automatically — no manual edits to `registry.py` required.
- **Multi-port typed I/O**: nodes declare named, typed input and output ports using real Python types, supporting single-input/single-output, multi-input, multi-output, and fan-in/fan-out topologies.
- **Universal pipeline support**: the node contract is domain-agnostic so the same infrastructure can power audio processing, ML pipelines, data transformation, work automation, and any other workflow.
- **Full Pydantic compatibility**: all node configuration, metadata, and I/O contracts are expressed as Pydantic models, making the system serialisable, validatable, and introspectable.
- **Rich node capabilities**: the base `Node` class gains lifecycle hooks, observability, retry logic, streaming support, and other capabilities that a general-purpose node needs.

The existing audio-processing nodes (`InputNode`, `CleanNode`, `AugmentNode`, etc.) **will be migrated** to the new system as part of this feature. The new system fully replaces the old one — there are no legacy dict configs, no string-based type tokens, and no old `registry.py` format.

---

## Document Structure

This master document defines the glossary and links to sub-documents for each requirement group:

| Sub-document | Requirements covered |
|---|---|
| [req-01-node-contract.md](req-01-node-contract.md) | R1 Node Config · R2 Multi-Port Typed I/O · R9 Universal Domain Support |
| [req-02-registration.md](req-02-registration.md) | R3 Auto-Registration · R4 NodeMetadata · R13 Type Catalogue |
| [req-03-runtime.md](req-03-runtime.md) | R5 Lifecycle Hooks · R6 Retry Policy · R7 Streaming · R8 Observability |
| [req-04-serialisation.md](req-04-serialisation.md) | R10 Migration · R11 Round-Trip Serialisation · R12 Config Schema Export |

---

## Glossary

- **Node**: A self-contained processing unit that declares named, typed input ports and output ports, a Pydantic configuration model, and a `process` method. A node is the atomic unit of any pipeline.
- **InputPort**: A named, typed descriptor on a node that declares what data the node accepts on that port, whether the port is required, and whether it accepts a single connection or multiple connections.
- **OutputPort**: A named, typed descriptor on a node that declares what data the node produces on that port.
- **PortCardinality**: Either `single` (the port accepts exactly one upstream connection and receives one value) or `multi` (the port accepts N upstream connections and receives a list of values).
- **PortType**: The Python type carried by a port. Must be one of: a concrete built-in (`int`, `str`, `float`, `bool`, `bytes`), a generic alias (`list[X]`, `dict[K,V]`, `tuple[X,...]`), a `pydantic.BaseModel` subclass, or `None` (for source/sink ports).
- **PortDataType**: A base class that node authors subclass to define custom domain-specific data types (e.g. `AudioSample`, `TFLiteModel`). Subclasses are auto-registered in the `TypeCatalogue` during `AutoDiscovery`.
- **NodeConfig**: A `pydantic.BaseModel` subclass that holds the validated, typed configuration for a specific node type.
- **NodeMetadata**: A Pydantic model that describes a node's identity, category, version, port definitions, and tags for introspection and UI rendering.
- **NodeRegistry**: The runtime singleton that maps node type names to their class and metadata.
- **TypeCatalogue**: A registry mapping fully-qualified type names (`"{module}.{qualname}"`) to Python `type` objects, enabling string-to-type resolution in YAML/JSON pipeline configs.
- **AutoDiscovery**: The mechanism that scans `app/core/nodes/` and the plugins directory at import time, registering `Node` subclasses and `PortDataType` subclasses automatically.
- **CompatibilityChecker**: The component that determines whether an output port of one node can be connected to an input port of another node, using Python's type system.
- **Fully-Qualified Type Name**: `"{module}.{qualname}"` — e.g. `"app.core.nodes.tflite.TFLiteModel"`. Used as the canonical key in `TypeCatalogue`.
- **Pipeline**: A directed acyclic graph (DAG) of connected nodes. Each edge connects a named output port of one node to a named input port of another node. The output port's type must be compatible with the input port's type.
- **NodeLifecycle**: The ordered sequence of runtime calls on a node: `setup` → (`on_start` → `process` → `on_end`)* → `teardown`.
- **StreamingNode**: A node that overrides `process_stream` to yield output items incrementally as an async generator.
- **NodeObserver**: A callback interface that receives structured events at each lifecycle stage for logging, metrics, and tracing.
- **RetryPolicy**: A Pydantic model specifying how many times and with what back-off a failing node should be retried.
- **System**: The enhanced node system as a whole (`app/core/nodes/`).
- **SISO**: Single-Input Single-Output — a node with exactly one input port and one output port. The common case; supported as a convenience shorthand.
