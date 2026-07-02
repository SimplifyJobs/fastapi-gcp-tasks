# Contributing

- Run `make lint` and `make format` before raising a PR.
- Add examples and/or tests for new features.
- If the change is massive, open an issue to discuss it before writing code.

## Development setup

Prerequisites:

- [uv](https://docs.astral.sh/uv/)
- Docker (for the Cloud Tasks emulator)

### Running tests

```sh
docker compose up -d       # start emulator
make test                  # run tests
docker compose down        # stop emulator
```

### Linting & formatting

```sh
make lint                  # mypy strict + ruff check
make format                # auto-fix
```

### Docs

```sh
make docs                  # live-reloading docs server
make docs-build            # strict build (what CI runs)
```

The docs live in `docs/` and are built with [MkDocs Material](https://squidfunk.github.io/mkdocs-material/);
the API reference is generated from source docstrings with
[mkdocstrings](https://mkdocstrings.github.io/). They deploy to GitHub Pages automatically on every push to
`master` via the Pages artifact flow (repo setting: Settings → Pages → Source → GitHub Actions).
