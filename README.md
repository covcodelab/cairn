# Cairn

Cairn manages a Record of Processing Activities (ROPA) and Information Asset Register to meet UK GDPR Article 30 and DPA 2018 Part 3 (s61) requirements. Each organisation runs its own instance. The Fire & Rescue Service pack is the first sector pack.

## Quick start

Requires [uv](https://docs.astral.sh/uv/). Python 3.14 is pinned in `.python-version`.

```sh
uv sync                                # install dependencies
uv run alembic upgrade head            # create the dev database (SQLite)
uv run uvicorn cairn.web:app --reload  # http://127.0.0.1:8000 (first visit runs setup)
```

## Checks

CI runs these on every pull request, and `main` requires them to pass:

```sh
uv run pytest -q        # test
uv run ruff check .     # lint
```

CI also applies the migrations to a fresh PostgreSQL 17 database (`migrations-postgres`) and builds the Docker image (`docker`).

## Documentation

- `docs/admin-reference.md`: start, stop, deploy and manage each environment
- `CLAUDE.md`: how the design documents in `docs/` fit together
- `docs/Cairn-backlog.md`: known gaps and what's next
