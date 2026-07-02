# Type safety

The package ships a `py.typed` marker (PEP 561), so mypy and pyright check everything you import from it.

## The problem with `.delay`

`.delay`, `.options`, and `.scheduler` are attached to your endpoint function at route registration time.
A plain function annotation can't express that, so out of the box a type checker rejects the call:

```python
@delayed_router.post("/hello")
async def hello(p: Payload) -> None: ...

hello.delay(p=Payload(message="hi"))
# error: "Callable[[Payload], Coroutine[Any, Any, None]]" has no attribute "delay"
```

## The `as_*_task` decorators

Add one of the `as_*_task` decorators as the **innermost** decorator. They are identity functions at runtime
(zero overhead) and cast the endpoint to a `Protocol` that carries the endpoint's own signature via
`ParamSpec`:

```python
from fastapi_gcp_tasks import as_delayed_task


@delayed_router.post("/{restaurant}/make_dinner")
@as_delayed_task
async def make_dinner(restaurant: str, recipe: Recipe) -> None: ...


make_dinner.delay(restaurant="Taj", recipe=Recipe(ingredients=["Pav", "Bhaji"]))  # statically checked
make_dinner.delay(restaurant="Taj", recipe="oops")  # type error: wrong type for "recipe"
make_dinner.delay(restaurant="Taj")                 # type error: missing "recipe"
make_dinner.options(countdown=1800).delay(restaurant="Taj", recipe=Recipe(ingredients=["Pav", "Bhaji"]))
```

Each route builder has a matching decorator:

| Route builder | Decorator | Typed protocol |
| --- | --- | --- |
| `DelayedRouteBuilder` | `as_delayed_task` | `DelayedTask` |
| `AsyncDelayedRouteBuilder` | `as_async_delayed_task` | `AsyncDelayedTask` |
| `ScheduledRouteBuilder` | `as_scheduled_task` | `ScheduledTask` |
| `AsyncScheduledRouteBuilder` | `as_async_scheduled_task` | `AsyncScheduledTask` |

## Typed options

Options accepted by `.options()`, `.scheduler()`, and `task_default_options` are `TypedDict`s
(`DelayOptions`, `AsyncDelayOptions`, `SchedulerOptions`, `AsyncSchedulerOptions`, `TaskDefaultOptions`), so
misspelled or wrongly-typed options are caught statically too:

```python
make_dinner.options(countdown="soon")  # type error: countdown expects int
make_dinner.options(countdwn=60)       # type error: unknown option
```

## Caveats

- Call `.delay()` and `.schedule()` with **keyword arguments** — the runtime only accepts keywords. The
  protocols mirror the endpoint's full signature, so a positional call may typecheck but fail at runtime.
- The decorators are casts: they tell the type checker the methods will exist. They do exist as soon as the
  router is registered with `route_class=...` from the matching builder — using `as_delayed_task` on a plain
  (non-delayed) route will typecheck but fail at runtime.

See the [Typed protocols API reference](../api/protocols.md) for the full definitions.
