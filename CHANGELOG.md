# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Releases before this file existed are described on the
[GitHub releases page](https://github.com/SimplifyJobs/fastapi-gcp-tasks/releases).

## 0.4.1

### Fixed

- `{x:float}` path segments keep every digit of the value. In 0.4.0, values with more than 20 decimal places
  were rounded, and values below `1e-20` were sent as `0`. Values that 0.4.0 wrote correctly keep their spelling.
- A fractional value for an `{n:int}` path segment raises `ValueError`. It used to be truncated.
- A header parameter model can no longer add a second `Content-Type` header, or one that Cloud Tasks or Cloud
  Scheduler sets. Setting such a field raises `TypeError`; a field that only the endpoint's default sets is left
  out.
- A body parameter typed with a generic alias sends an explicit `None` as JSON `null` when the alias or its
  argument is nullable, such as `Maybe[str]` for `type Maybe[T] = T | None`.

## 0.4.0

### Changed

These can require action when upgrading:

- **Python 3.12 or newer is required** (previously 3.11).
- **FastAPI 0.151 or newer is required** (previously 0.110). It is the first release that delivers a JSON `null`
  body field to the endpoint as `None` instead of treating it as missing.
- **The upper bounds on FastAPI and Python are gone.** A new FastAPI release no longer needs a matching release of
  this package before the two can be installed together. CI now runs the suite against the newest FastAPI weekly.
- **`.delay()` and `.schedule()` raise `TypeError` for arguments that cannot be delivered.** That covers names
  the endpoint does not declare, and arguments the worker resolves itself, such as
  `db: Session = Depends(get_db)`. Both used to be dropped silently.
- **An empty path parameter value raises `ValueError`, and so does one containing `/`** unless the segment is
  declared as `{name:path}`. ASGI servers decode `%2F` before routing, so such a value could never reach the route.
- **`Scheduler.delete()` and `AsyncScheduler.delete()` return `bool` and raise on unexpected errors**
  ([#119](https://github.com/SimplifyJobs/fastapi-gcp-tasks/issues/119)). They return `True` when the job was
  deleted and `False` when it did not exist. They used to return the exception object instead of raising it.
- **`.schedule()` raises when the existing job cannot be read.** Any error from the lookup used to be treated as
  "the job changed", which deleted and recreated the job on a guess. Only "not found" means the job is missing,
  and a missing job is created without a delete, so first-time scheduling needs no permission to delete jobs.
- **Collections that cannot be delivered raise `ValueError`.** That covers a list header with more than one value
  (a task request sends each header once), any list passed to a cookie parameter, and an empty list for a query,
  header or cookie parameter whose default is not also empty.
- **Cookie parameters are sent in the standard `Cookie` header.** They used to be sent in a `Cookies` header that
  FastAPI does not read.
- **Headers the task request sets itself cannot be passed.** A value for an `X-CloudTasks-*` or
  `X-CloudScheduler*` header, or for `Content-Type`, raises `TypeError`; it used to be dropped silently. A
  `SecretStr` outside the body raises `ValueError`, because Pydantic would send its mask.
- **Some scheduled jobs are recreated once after upgrading.** `.schedule()` sees a job as changed the first time
  if its request is now built differently: omitted optional query parameters (no longer in the URL), list, enum
  and boolean query values, cookie parameters (now in `Cookie`), path values that need percent-encoding, routes
  with a trailing slash, and Decimal or duration values outside a model body.

### Fixed

- Optional query parameters that were left out are no longer sent as the text `None`, which made the worker fail
  validation or receive the string `"None"`.
- List, enum and boolean query parameters are serialized the way FastAPI parses them back (`ids=1&ids=2`,
  `color=red`, `flag=true`).
- `Header()` parameters can be passed by their Python name and are sent under their real header name
  (`x_request_id=...` becomes `x-request-id`). Required headers could not be passed at all before, and optional
  ones were dropped.
- Path parameter values are percent-encoded, so a space, `?` or `#` in a value can no longer break the URL or
  inject query parameters.
- A trailing slash in a route (`"/send_email/"`) or in a `{name:path}` value is kept. It used to be stripped, so
  the worker answered with a redirect or a 404.
- Decimals and durations are sent in a form Pydantic parses back exactly, in every location. Outside a model
  body, Decimals used to go through `float`, and a duration in a URL, header or cookie was rejected by the worker.
- Bodies that are not a single model (lists, dicts, scalars next to a model) are serialized like model bodies.
- `TypedDict` bodies, an `int` for a `float` body parameter and a generic model built without its type argument
  are accepted. They used to fail the argument check.
- `{x:float}` path segments are written in plain notation, and a value a typed segment cannot match, such as a
  negative number for `{n:int}`, raises `ValueError` instead of producing a URL that 404s.
- A scheduled job that a `pre_create_hook` renames is replaced under its new name. The original name used to be
  deleted instead.
- A per-call `callback_base_url` or `base_url` replaces an endpoint default given under the other name instead
  of raising, and query parameters without a value on the callback URL are kept.
- Endpoints with several body parameters, or with `Body(embed=True)`, now work. They used to raise
  `field required: body`.
- Query, header and cookie parameter models (a Pydantic model grouping several parameters) are expanded into
  individual parameters.
- A value passed for a query, header or cookie parameter owned by a dependency is forwarded instead of dropped.
  Such parameters are still never required at the call site, because a hook or Cloud Tasks itself often supplies
  them.
- Cookie values are quoted, so a `;` or `,` in a value no longer cuts it short.
- `.schedule()` no longer fails when another instance creates or replaces the same job at the same moment. The
  instance that loses the race compares its job with the one that won and only replaces it if they differ. It
  raises `AlreadyExists` only if, after three attempts, the job is still not the one it asked for (or, with
  `force=True`, if it loses the create every time).
- Passing `None` for a body parameter that accepts it sends JSON `null` instead of the parameter's default.

### Added

- `.delay()` and `.schedule()` accept positional arguments, matching what the typed protocols already allowed.
- Endpoints that declare `Form()` or `File()` parameters fail with a clear error when triggered, since task bodies
  are always JSON.
- PyPI metadata: project links, keywords and classifiers.
- CI covers Python 3.12 through 3.15, plus the lowest and the newest supported FastAPI.

### Performance

- Pydantic model bodies are no longer walked a second time in Python after pydantic-core has dumped them, and the
  request layout for each route is computed once. The JSON of a model body is the same, with one exception:
  dictionary keys starting with `_sa` are no longer stripped (a SQLAlchemy safeguard in `jsonable_encoder`).
  Client-side time per `.delay()` for a 50-item order model drops from about 150µs to under 50µs; a small payload
  goes from about 27µs to about 20µs.
