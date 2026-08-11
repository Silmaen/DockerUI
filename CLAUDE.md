# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

DockerUI is a Django web application that provides a browser-based UI for Docker container registries. It supports both
classic Docker Registry and JFrog Artifactory backends.

There are no custom database models. SQLite holds Django internals only — and that database is created at **image build
time**, so anything written to it at runtime (sessions, in practice) is discarded on the next rebuild. Registry data is
never persisted: every page comes from a live HTTP call, cached in memory.

## Development Commands

```bash
# Deployment / production-like runs — the single entry point
./deploy.sh                  # pull + build + up + wait for the UI to answer
./deploy.sh --no-pull        # same, without touching git or the registry (dirty tree)
./deploy.sh --dry-run        # print the commands, run none
./deploy.sh check            # is an update pending? exit 0 / 10 / 1
./deploy.sh logs|status|restart|stop
./deploy.sh tests [app]      # tests in a throwaway container
./deploy.sh shell            # Django shell in the running container

# Local (native) development
pip install -r requirements.txt
python manage.py runserver
python manage.py test
python manage.py collectstatic   # required after CSS/JS changes for production
python manage.py migrate
```

`ui/tests.py` is still empty — `manage.py test` currently reports "NO TESTS RAN" and passes. Any test added is picked up
by `./deploy.sh --tests`.

## Architecture

**Request flow:** Browser → Django URL router → `ui/views.py` → `ui/registry_client.py` → Docker Registry/Artifactory
HTTP API

The UI is deliberately front-loaded: the initial HTML carries only names, and every expensive value (tag counts, tag
dates/sizes/architectures, per-repo storage) is fetched afterwards by JSON endpoints so a big registry does not stall
the first paint.

### Key Modules

- **`DockerUI/settings.py`** — all registry configuration comes from environment variables. `ALLOWED_HOSTS` is `["*"]`;
  `CSRF_TRUSTED_ORIGINS` is parsed from a comma-separated env var. No `CACHES` block, so Django's default per-process
  `LocMemCache` is in use (see Constraints).
- **`ui/registry_client.py`** — all registry API communication: session/auth setup, URL construction per registry type,
  caching, manifest walking.
  - `get_registry_data(endpoint)` — cached GET (300 s), returns `None` on 404, raises otherwise. Builds the URL inline,
    with a special case for Artifactory `_catalog`.
  - `_build_registry_url(endpoint)` — the same URL logic again, for the non-cached verbs.
  - `get_tag_count` / `get_all_tag_counts(force_refresh)` — per-repo and catalog-wide counts (cached 3600 s).
  - `get_manifest_digest` (HEAD) / `delete_manifest` (DELETE) — the mutating pair used by admin mode.
  - `_collect_manifest_blobs` / `get_repo_stats` — recursive manifest-list walk summing unique blob sizes per repo,
    deduplicated by digest (cached 300 s).
  - `invalidate_cache(repository)` / `invalidate_repo_stats` — purge after a mutation.
- **`ui/views.py`** — page views: `repository_list` (recursive namespace nesting, `<default>` bucket sorted last),
  `repository_detail` (tag names + `docker pull` base command), `registry_stats` (admin shell page), `admin_login` /
  `admin_logout`. JSON endpoints: `get_tag_details`, `get_tag_counts`, `registry_stats_summary`,
  `registry_stats_repo`. Mutations: `delete_tag`, `delete_repository` (both `@require_POST` + admin check; a registry
  that refuses deletion answers 405 and that is surfaced verbatim).
- **`ui/formating.py`** — `format_time_difference()` and `format_size()`.
- **`ui/context_processors.py`** — injects `app_version` (from the `VERSION` file), `is_admin` (session flag) and
  `admin_enabled` (is `ADMIN_PASSWORD` set) into every template.

### Admin mode

Not Django auth. `ADMIN_PASSWORD` is compared to the posted password and, on success, `request.session["is_admin"]` is
set; every admin view and endpoint re-checks that flag and returns `HttpResponseForbidden` otherwise. Empty
`ADMIN_PASSWORD` disables the feature, and the templates hide every admin affordance. Django's own `/admin/` is mounted
but has no models and no users — it is unused.

### URL Routes

Order matters in `ui/urls.py`: repository names contain slashes, so `repository_detail` uses a greedy `re_path` and
every more specific route (`tag-details/`, `delete-tag/`, `delete/`) must be declared before it.

- `/` → permanent redirect to `/ui/`
- `/ui/`, `/ui/repositories/` → repository list
- `/ui/repositories/<repo>/` → repository detail
- `/ui/repositories/<repo>/tag-details/` → JSON per-tag metadata
- `/ui/repositories/<repo>/delete-tag/`, `/ui/repositories/<repo>/delete/` → POST, admin only
- `/ui/tag-counts/` → JSON counts, `?repos=a,b,c` for a subset, `?force=true` to bypass the cache
- `/ui/admin/login/`, `/ui/admin/logout/`
- `/ui/stats/`, `/ui/stats/summary/`, `/ui/stats/repo/<repo>/` → admin only

### Frontend

Vanilla JavaScript + Bootstrap 5.3 (loaded from the jsDelivr CDN, so the UI degrades on an air-gapped network). Static
files in `ui/static/ui/`, templates in `ui/templates/ui/` over a `base.html` layout; `_namespace_level.html` includes
itself to render the namespace tree.

`scripts.js` is a set of `init*()` functions, all called on `DOMContentLoaded`, each a no-op when its anchor element is
absent: `initThemeToggle`, `initFolderStates` (localStorage), `initCopyButtons`, `initTagDetails` (one fetch per
repository page, then client-side sort by date), `initAdminDelete` (modals + CSRF from the cookie), `initTagCounts`
(batches of 10), `initAdminStats` (summary then per-repo fan-out, 4 concurrent).

### Deployment

`docker compose` with a single `registry-ui` service, image built from `python:3.13-slim`, Gunicorn (2 workers,
2 threads) on port 8000, WhiteNoise serving hashed static files. `migrate` and `collectstatic` run in the Dockerfile, so
startup is immediate and the container needs no writable volume.

`deploy.sh` drives all of it and waits for `/ui/` to answer from inside the container before declaring success — that
path returns 200 even when the registry itself is unreachable (the view renders an error banner), which is the intended
signal: it checks the UI, not the registry.

`.dockerignore` matters here: the Dockerfile does `COPY . .`, so anything not excluded — `.env` included — ends up
readable in an image layer.

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `REGISTRY_URL` | `http://registry:5000` | Registry server URL |
| `REGISTRY_TYPE` | `classic` | `classic` or `artifactory` |
| `REGISTRY_REPO` | (empty) | Namespace prefix / Artifactory repository key |
| `REGISTRY_SSL_VERIFY` | `False` | SSL certificate verification |
| `REGISTRY_USERNAME` | (empty) | Registry auth username |
| `REGISTRY_PASSWORD` | (empty) | Registry auth password |
| `SECRET_KEY` | dev default | Django secret key |
| `DEBUG` | `False` | Django debug mode |
| `PORT` | `8000` | Host port published by compose |
| `CSRF_TRUSTED_ORIGINS` | (empty) | Comma-separated origins trusted for POSTs; required over HTTPS or a non-localhost host |
| `ADMIN_PASSWORD` | (empty) | Enables admin mode; empty disables it |

`docker-compose.yml` lists these explicitly rather than using `env_file`, so a key missing from `.env` reaches the
container as an empty string and *overrides* the Django default instead of falling back to it. `deploy.sh check_env`
warns about missing keys for that reason.

## Constraints worth knowing before optimizing

- **The cache is per worker process.** No `CACHES` setting means `LocMemCache`: each Gunicorn worker holds its own copy,
  and its default `MAX_ENTRIES` is 300 with a cull of one third — a registry with many tags evicts manifest entries
  while they are still being used. A shared or larger cache is the single highest-leverage change available.
- **Registry calls are sequential.** `get_all_tag_counts`, `get_tag_details` and `get_repo_stats` loop over
  repositories/tags one HTTP request at a time (the comment in `get_all_tag_counts` says threading was dropped as
  unreliable). Latency scales linearly with catalog size.
- **Only 4 requests can be served at once** (2 workers × 2 threads), and the stats page alone opens 4 concurrent
  fetches; each of those holds a thread for the whole manifest walk.
- Cache reads use `if cached_data:`, so a legitimately empty response is treated as a miss and refetched.
