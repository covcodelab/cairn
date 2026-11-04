# Cairn — Environments & DevOps

**Status:** Environments & DevOps v0.1 — the Phase 1.6 deliverable (Project Plan §4). Describes what is now real in the repository: environments, CI, the container reference deployment, and the release/restore runbooks.
**Derives from:** Solution Architecture v0.1 (containers, reference deployment), NFRs v0.1 (backup/restore targets, logging, `/healthz`).

---

## 1. What exists in the repo

| Artefact | Purpose |
|---|---|
| `.github/workflows/ci.yml` | CI on every push to `main` and every PR: `uv sync` → `ruff check` → `pytest`, plus a Docker image build (`push: false`) so the Dockerfile can never silently rot. **Revised 2026-11-04:** a `migrations-postgres` job runs `alembic upgrade head`, `alembic check`, then a downgrade/re-upgrade of the newest revision against a PostgreSQL 17 service — the suite runs on SQLite, which cannot catch PostgreSQL-only migration faults such as duplicate enum types |
| `Dockerfile` | Multi-stage OCI image: uv-locked prod-only install, `python:3.14-slim`, non-root `cairn` user, `HEALTHCHECK` on `/healthz`, uvicorn entrypoint |
| `docker-compose.yml` | The reference deployment: `app` + `postgres:17` with healthcheck-gated startup and a named volume. `DATABASE_URL`, `SESSION_SECRET`, `AUTH_MODE`, the `OIDC_*` variables, `SESSION_IDLE_SECONDS`/`SESSION_ABSOLUTE_SECONDS` and `LOG_FORMAT` are read by the app (`src/cairn/settings.py`, documented in `admin-reference.md` §1); migrations are a deliberate manual step (`docker compose run --rm app alembic upgrade head` — see `admin-reference.md`) |
| `src/cairn/web.py` | Application entrypoint: `create_app()` assembles session/CSRF middleware, `GET /healthz`, and the full router set (auth, setup, dashboard, vocabularies, regime policy, basis, registers, activities, imports, users, complaints) |
| `uv.lock` | The single source of dependency truth for dev, CI and the image alike |

## 2. Environments

| Environment | How | Database |
|---|---|---|
| **dev** | `uv sync` + `uv run pytest` locally; `uv run uvicorn cairn.web:app --reload` when working on the web layer | SQLite (in-memory in tests) |
| **test/staging** | `docker compose up` — the reference deployment; also the restore-test target (NFRs §4) | PostgreSQL 17 (containerised) |
| **prod** | The same image, deployed to the organisation's estate; TLS/proxy, secrets and backups supplied by the estate (Solution & Security Architecture) | PostgreSQL (managed or estate-hosted) |

One image serves all environments; behaviour differs only by injected configuration — no environment-specific builds.

## 3. Release process

1. Work happens on a branch; merge to `main` only with CI green (test, migrations-postgres and docker jobs).
2. A release is a **git tag `vX.Y.Z`** on `main`; the image is built from that tag and labelled with it (`cairn:X.Y.Z`). `cairn.__version__` and the tag move together.
3. Deploy = pull/replace the image, run `alembic upgrade head` (the image carries `alembic.ini` + `migrations/`; e.g. `docker run --rm -e DATABASE_URL=… cairn:X.Y.Z alembic upgrade head`), start, verify `/healthz`. Rollback = redeploy the previous tag; **migrations are forward-only** — a bad release rolls the app back, not the schema, so migrations must be backwards-compatible one version.
4. Seed updates (legal vocabularies, sector packs) ship as versioned migrations/data updates, never manual SQL — the legislation-watch path (Phase 6) rides the same release process.

## 4. Runbooks (operational commitments from NFRs v0.1)

- **Backup**: daily `pg_dump` (or the managed service's native backup) per NFRs §4 — 35 days rolling + 12 monthly, encrypted by the estate.
- **Restore test (quarterly)**: restore the latest backup into the compose staging stack; run `uv run pytest` smoke plus a manual register export; record the result. An untested backup is not a backup.
- **DR**: redeploy image on any estate + restore latest backup; target RTO ≤ 1 business day.
- **Dependency updates**: refresh `uv.lock` and rebuild the image on a regular cadence; CI validates. Security advisories jump the queue.

## 5. Deferred (intentionally)

- ~~**Alembic** — adopts at the start of sub-phase 2a~~ *(adopted in 2a: initial migration + parity test; tests still use `create_all` for speed).*
- **Image registry & signed releases** — decided with the first real deployment estate.
- **Infrastructure-as-code beyond compose** — the compose file *is* the reference; estate-specific IaC (Terraform/Bicep) belongs to each deployment, not the product repo.

---

*Environments & DevOps v0.1. With this, Phase 1 (Technical Architecture & Foundations) is complete; sub-phase 2a builds on a green pipeline.*
