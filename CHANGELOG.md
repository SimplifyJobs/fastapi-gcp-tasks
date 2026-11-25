# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Releases before this file existed are described on the
[GitHub releases page](https://github.com/SimplifyJobs/fastapi-gcp-tasks/releases).

## 0.4.0

### Changed

These can require action when upgrading:

- **Python 3.12 or newer is required** (previously 3.11).
- **FastAPI 0.137 or newer is required** (previously 0.110).
- **The upper bounds on FastAPI and Python are gone.** A new FastAPI release no longer needs a matching release of
  this package before the two can be installed together. CI now runs the suite against the newest FastAPI weekly.
- **`.delay()` and `.schedule()` raise `TypeError` for arguments that cannot be delivered.** That covers names
  the endpoint does not declare, and arguments the worker resolves itself, such as
  `db: Session = Depends(get_db)`. Both used to be dropped silently.
- **A path parameter value that is empty or contains `/` raises `ValueError`**, unless the segment is declared as
  `{name:path}`. ASGI servers decode `%2F` before routing, so such a value could never reach the route.
- **Cookie parameters are sent in the standard `Cookie` header.** They used to be sent in a `Cookies` header that
  FastAPI does not read.
- **Some scheduled jobs are recreated once after upgrading.** Model bodies are now compact JSON and omitted
  optional query parameters are no longer in the URL, so `.schedule()` sees those jobs as changed the first time.

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
- Endpoints with several body parameters, or with `Body(embed=True)`, now work. They used to raise
  `field required: body`.
- Query, header and cookie parameter models (a Pydantic model grouping several parameters) are expanded into
  individual parameters.
- A value passed for a parameter owned by a dependency is forwarded instead of dropped. Such parameters are still
  never required at the call site, because a hook or Cloud Tasks itself often supplies them.

### Added

- `.delay()` and `.schedule()` accept positional arguments, matching what the typed protocols already allowed.
- Endpoints that declare `Form()` or `File()` parameters fail with a clear error when triggered, since task bodies
  are always JSON.
- PyPI metadata: project links, keywords and classifiers.
- CI covers Python 3.12 through 3.15, plus the lowest and the newest supported FastAPI.

### Performance

- Pydantic model bodies are serialized by pydantic-core instead of `jsonable_encoder` plus `json.dumps`, and the
  request layout for each route is computed once. Client-side time per `.delay()` for a 50-item order model drops
  from about 151µs to about 31µs; a small payload goes from about 27µs to about 19µs.
