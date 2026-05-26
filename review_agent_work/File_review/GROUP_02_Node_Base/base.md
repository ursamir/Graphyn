# Functional Review — app/core/nodes/base.py

**Group:** 2 — Node Base
**Reviewed:** 2026-05-26
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/core/nodes/base.py
FUNCTION:    Node.__init__
CATEGORY:    Type Safety
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Accept a config as `Config | dict | None`, validate it, and store as `self.config`.

WHAT IT ACTUALLY DOES:
The `else` branch calls `self.Config.model_validate(config.model_dump())` for any
`NodeConfig` subclass that is not an instance of `self.Config`. This silently
discards fields that exist on the passed config but not on `self.Config`, because
`model_dump()` serialises the passed object's fields and `model_validate` then
applies `extra="forbid"` — which will raise a `ValidationError` if the passed
config has extra fields relative to `self.Config`.

THE BUG / RISK:
If a caller passes a `NodeConfig` subclass with extra fields (e.g. a richer
config from a parent class), `model_validate` raises `ValidationError` with a
confusing message that does not mention the type mismatch. The docstring says
"Accept any NodeConfig subclass" but the implementation can raise.

EVIDENCE:
Lines 76-78:
```python
else:
    # Accept any NodeConfig subclass (e.g. when called from tests)
    self.config = self.Config.model_validate(config.model_dump())
```

REPRODUCTION SCENARIO:
```python
class RichConfig(NodeConfig):
    extra_field: int = 5

class MyNode(Node):
    class Config(NodeConfig):
        pass  # no extra_field

node = MyNode(config=RichConfig(extra_field=5))
# Raises ValidationError: extra inputs are not permitted
```

IMPACT:
Silent contract violation — the comment says "Accept any NodeConfig subclass"
but it raises for configs with fields not in `self.Config`. Misleads callers.

FIX DIRECTION:
Either document that only compatible subclasses are accepted, or use
`model_validate(config.model_dump(exclude_unset=False), strict=False)` and
catch `ValidationError` to re-raise with a clearer message.

--------------------------------------------------------------------
FILE:        app/core/nodes/base.py
FUNCTION:    Node.on_start / Node.on_end / Node.on_error
CATEGORY:    Contract Mismatch
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Call observer lifecycle hooks with `run_id` from `self._run_id`.

WHAT IT ACTUALLY DOES:
All three methods pass `run_id=getattr(self, "_current_run_id", "")` — but the
attribute set by the executor is `self._run_id` (line 83), not `_current_run_id`.

THE BUG / RISK:
`_current_run_id` is never set anywhere in this file. `getattr` silently falls
back to `""` for every observer call. The run_id passed to observers is always
an empty string, making observer logs useless for correlating events to runs.

EVIDENCE:
Line 83: `self._run_id: str = ""`
Lines 163, 176, 188 (on_start, on_end, on_error):
```python
run_id=getattr(self, "_current_run_id", ""),
```

REPRODUCTION SCENARIO:
Any node execution with an observer attached. The observer's `on_node_start`,
`on_node_end`, and `on_node_error` will always receive `run_id=""`.

IMPACT:
Silent wrong result — observer logs cannot be correlated to pipeline runs.
Monitoring and debugging are silently broken.

FIX DIRECTION:
Replace `_current_run_id` with `_run_id` in all three lifecycle methods:
```python
run_id=self._run_id,
```

--------------------------------------------------------------------
FILE:        app/core/nodes/base.py
FUNCTION:    Node.process_stream
CATEGORY:    Async Bug
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Wrap `process()` as a single-item async generator, offloading CPU-bound work
to a `ThreadPoolExecutor` so the event loop is not blocked.

WHAT IT ACTUALLY DOES:
Calls `loop.run_in_executor(None, self.process, inputs)` which runs `process()`
in the default thread pool. However, `process_stream` is an `async def` that
uses `yield`, making it an async generator. The `await` inside an async
generator is valid, but the function is declared to return
`AsyncGenerator[dict[str, Any], None]` — which is correct. The issue is that
`loop.run_in_executor` submits `self.process` to a thread, but if `self.process`
itself is a coroutine (i.e. a subclass overrides `process` as `async def`),
`run_in_executor` will return the coroutine object unawaited, not its result.

THE BUG / RISK:
If a subclass overrides `process` as `async def process(self, inputs)`, the
default `process_stream` will call `run_in_executor(None, self.process, inputs)`
which submits the coroutine *object* to a thread. The thread receives a coroutine
and returns it unawaited. `result` will be a coroutine object, not a dict.
`yield result` then yields a coroutine object to the caller — a silent wrong result.

EVIDENCE:
Lines 196-200:
```python
loop = _asyncio.get_running_loop()
result = await loop.run_in_executor(None, self.process, inputs)
yield result
```

REPRODUCTION SCENARIO:
```python
class AsyncNode(Node):
    async def process(self, inputs):
        return {"output": 42}
# process_stream yields a coroutine object, not {"output": 42}
```

IMPACT:
Silent wrong result — downstream nodes receive a coroutine object instead of
the expected dict. No exception is raised.

FIX DIRECTION:
Add a guard before `run_in_executor`:
```python
import inspect as _inspect
if _inspect.iscoroutinefunction(self.process):
    result = await self.process(inputs)
else:
    result = await loop.run_in_executor(None, self.process, inputs)
yield result
```

--------------------------------------------------------------------
FILE:        app/core/nodes/base.py
FUNCTION:    _install_siso_wrapper / _siso_process
CATEGORY:    Silent Failure
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Wrap SISO nodes so that `process(self, data)` is transparently called with
`inputs["input"]` and the result is repacked as `{"output": result}`.

WHAT IT ACTUALLY DOES:
The guard at lines 249-252 checks:
```python
if isinstance(result, dict) and set(result.keys()) == set(cls.output_ports.keys()):
    return result
```
This guard is evaluated at call time using `cls.output_ports` captured in the
closure. However, `cls` is the class at the time `_install_siso_wrapper` is
called (during `__init_subclass__`). If a subclass later modifies `output_ports`
(e.g. adds ports), the guard compares against the *original* port set, not the
current one. More critically: if a SISO node's `process()` legitimately returns
a dict whose keys happen to match `output_ports` (e.g. `{"output": some_dict}`),
the guard passes it through — correct. But if the node returns a dict with keys
that are a *subset* of output_ports (e.g. node has ports `{"output", "aux"}` but
returns `{"output": x}`), the guard fails and wraps it as `{"output": {"output": x}}`,
producing a doubly-nested result.

THE BUG / RISK:
For multi-output SISO nodes (contradictory but possible if `_siso=True` is set
explicitly), the guard only passes through if ALL output port keys are present.
A partial return dict gets double-wrapped silently.

EVIDENCE:
Lines 249-252:
```python
if isinstance(result, dict) and set(result.keys()) == set(cls.output_ports.keys()):
    return result
return {"output": result}
```

REPRODUCTION SCENARIO:
```python
class MyNode(Node):
    _siso = True
    output_ports = {"output": OutputPort(name="output", data_type=dict),
                    "aux": OutputPort(name="aux", data_type=dict)}
    def process(self, data):
        return {"output": data}  # only returns "output", not "aux"
# result becomes {"output": {"output": data}} — double-wrapped
```

IMPACT:
Silent wrong result — downstream nodes receive a doubly-nested dict.

FIX DIRECTION:
The guard should check if the result is a dict with at least one key matching
an output port, or document that `_siso=True` is only valid for single-output nodes.
Add a validation in `_install_siso_wrapper` that raises if `_siso=True` is set
on a node with more than one output port.

--------------------------------------------------------------------
FILE:        app/core/nodes/base.py
FUNCTION:    Node.on_end
CATEGORY:    Contract Mismatch
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Pass `duration_s`, `input_counts`, and `output_counts` to `observer.on_node_end`.

WHAT IT ACTUALLY DOES:
Passes `duration_s=getattr(self, "_last_duration", 0.0)` and similar. These
attributes (`_last_duration`, `_last_input_counts`, `_last_output_counts`) are
never set in `base.py`. They would need to be set by the executor before calling
`on_end()`. If the executor does not set them, the observer always receives
`duration_s=0.0` and empty dicts.

THE BUG / RISK:
If the executor calls `node.on_end()` without first setting `_last_duration` etc.,
the observer silently receives zeroed metrics. No error is raised.

EVIDENCE:
Lines 174-179:
```python
duration_s=getattr(self, "_last_duration", 0.0),
input_counts=getattr(self, "_last_input_counts", {}),
output_counts=getattr(self, "_last_output_counts", {}),
```

REPRODUCTION SCENARIO:
Call `node.on_end()` directly (as the executor does) without setting
`_last_duration` first. Observer receives `duration_s=0.0`.

IMPACT:
Silent wrong result in observer metrics. Monitoring dashboards show zero
durations for all nodes.

FIX DIRECTION:
Document that the executor must set `_last_duration`, `_last_input_counts`,
`_last_output_counts` before calling `on_end()`, or add these as instance
attributes in `__init__` with their defaults.

--------------------------------------------------------------------
FILE:        app/core/nodes/base.py
FUNCTION:    Node.port_schemas
CATEGORY:    Error Handling
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Return JSON Schema representations of all ports.

WHAT IT ACTUALLY DOES:
Calls `_type_to_schema(port.data_type)` for each port. If `_type_to_schema`
raises (e.g. for an unusual type), the exception propagates uncaught from
`port_schemas()`. The docstring does not mention any exceptions.

THE BUG / RISK:
Callers (e.g. API endpoints returning node metadata) will receive an unhandled
exception if any port has an unusual data type. The fallback in `_type_to_schema`
is broad but not exhaustive.

EVIDENCE:
Lines 120-128 — no try/except around `_type_to_schema` calls.

REPRODUCTION SCENARIO:
A node with `data_type=SomeExoticType` where `_type_to_schema` raises.

IMPACT:
Crash in API endpoint returning node metadata.

FIX DIRECTION:
Wrap each `_type_to_schema` call in a try/except and return `{"type": "object"}`
as a safe fallback, or document that exceptions may propagate.

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | HIGH |
| Silent Failures | 3 |
| Error Handling | PARTIAL |
| Async Safety | UNSAFE |
| State Safety | SAFE |
| Resource Safety | SAFE |
| Test Hostile | NO |
| Top Risk | `process_stream` silently yields a coroutine object instead of a result dict when a subclass overrides `process` as `async def`. |
