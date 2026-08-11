# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

DockerUI is a Django web application that provides a browser-based UI for Docker container registries. It supports both
classic Docker Registry and JFrog Artifactory backends.

**There is no database.** No models, no migrations, no `django.contrib.auth`, no `django.contrib.admin`: `DATABASES` is
`{}`. The only server-side state is the admin flag, and it lives in a signed session cookie. Registry data is never
persisted — every page comes from a live HTTP call, cached in a file-backed cache under `/tmp`.

## Development Commands

```bash
# Deployment / production-like runs — the single entry point
./deploy.sh                  # pull + build + up + wait for the UI to answer
./deploy.sh --no-pull        # same, without touching git or the registry (dirty tree)
./deploy.sh --dry-run        # print the commands, run none
./deploy.sh check            # is an update pending? exit 0 / 10 / 1
./deploy.sh logs|status|restart|stop
./deploy.sh tests [app]      # tests in a throwaway container
./deploy.sh lint [--fix]     # ruff, in the pinned ruff image
./deploy.sh shell            # Django shell in the running container
./deploy.sh sh               # interactive shell in the running container

# Directly, when a container is not wanted
python manage.py runserver
python manage.py test --settings=DockerUI.settings_test
python manage.py collectstatic   # required after CSS/JS changes for production
```

Tests **must** run against `DockerUI.settings_test` (`./deploy.sh tests` does this). It swaps the manifest static-files
storage for the plain one — otherwise every template render fails with "Missing staticfiles manifest entry" unless
`collectstatic` happened to have run — uses an in-process cache, and points the registry at a hostname that resolves to
nothing so an accidental real call fails loudly.

## Architecture

**Request flow:** Browser → Django URL router → `ui/views.py` → `ui/registry_client.py` → Docker Registry/Artifactory
HTTP API

The UI is deliberately front-loaded: the initial HTML carries only names, and every expensive value (tag counts, tag
dates/sizes/architectures, per-repo storage) is fetched afterwards by JSON endpoints, which in turn fan out to the
registry in parallel.

### Key Modules

- **`DockerUI/settings.py`** — everything configurable comes from the environment, through the `env_flag()` /
  `env_list()` helpers (an empty value counts as unset, so a variable present-but-empty falls back to the default).
  Defines the file-backed `CACHES`, signed-cookie sessions, and the `TRUST_PROXY` switch that gates both
  `SECURE_PROXY_SSL_HEADER` and whether `X-Forwarded-For` is believed.
- **`DockerUI/settings_test.py`** — test overlay, see above.
- **`ui/converters.py`** — `RepositoryConverter`, the URL converter every repository-carrying route uses. Its regex
  requires each path component to start with an alphanumeric, which is what makes `.`, `..` and `%2e%2e`
  unroutable. **This is a security control**: `requests` normalises `..` when preparing a URL, so a name like
  `../../v2/_catalog` used to redirect a credentialed registry call outside the configured namespace, from an endpoint
  that needs no authentication.
- **`ui/registry_client.py`** — all registry API communication.
  - `get_registry_session()` — one `requests.Session` per thread, cached and rebuilt only when the credentials or the
    verify flag change. Not a fresh session per call: that defeated connection pooling and paid for a TLS handshake on
    every request.
  - `map_concurrently(func, items)` — the fan-out used by every multi-item call. Bounded by `REGISTRY_MAX_WORKERS`,
    preserves input order (callers `zip()` against it with `strict=True`), and propagates exceptions, so `func` handles
    its own failures when a partial result beats none.
  - `check_endpoint(endpoint)` — second lock against traversal, on the sink rather than the route.
  - `_build_registry_url(endpoint)` — the single place that knows what a registry URL looks like, per registry type.
  - `get_registry_data(endpoint)` — cached GET. Uses a `_CACHE_MISS` sentinel so an empty payload is a hit, and caches
    404s as `None`.
  - `get_tag_count` (None on failure, never 0) / `get_tag_counts_for` / `get_all_tag_counts(force_refresh)`.
  - `get_manifest_digest` (HEAD) / `delete_manifest` (DELETE) — the mutating pair used by admin mode.
  - `_collect_manifest_blobs` / `get_repo_stats` — recursive manifest-list walk summing unique blob sizes per repo. Each
    tag walks into its own dict and the dicts are merged afterwards: same deduplication, no lock.
  - `invalidate_cache(repository, tags=())` — purge after a mutation. Pass the deleted tags, or their manifest entries
    outlive them.
- **`ui/views.py`** — page views: `repository_list` (recursive namespace nesting, `<default>` bucket sorted last),
  `repository_detail`, `registry_stats`, `admin_login` / `admin_logout`. JSON endpoints: `get_tag_details`,
  `get_tag_counts`, `registry_stats_summary`, `registry_stats_repo` — all of which answer **502** with a JSON body when
  the registry is unreachable, rather than a bare 500. Mutations: `delete_tag`, `delete_repository`.
- **`ui/formating.py`** — `format_time_difference()` and `format_size()`.
- **`ui/context_processors.py`** — injects `app_version` (from the `VERSION` file), `is_admin` and `admin_enabled`.

### Admin mode

Not Django auth. `ADMIN_PASSWORD` is compared with `hmac.compare_digest` and, on success,
`request.session["is_admin"]` is set; every admin view re-checks that flag and returns `HttpResponseForbidden`
otherwise. Failures are counted per client address in the cache (`admin_login_failures_<address>`) and the form locks
after `ADMIN_LOGIN_MAX_ATTEMPTS`. Empty `ADMIN_PASSWORD` disables the feature and the templates hide every admin
affordance.

Because sessions are signed cookies, a test cannot assign to `self.client.session` — log in through the view instead
(`AdminLoginTests`, `StatsSummaryTests` do this).

### URL Routes

Order matters in `ui/urls.py`: `<repo:repository>` accepts slashes, so it also matches `foo/delete`, and every more
specific route has to be declared before `repository_detail`.

- `/` → permanent redirect to `/ui/`
- `/ui/`, `/ui/repositories/` → repository list
- `/ui/repositories/<repo>/` → repository detail
- `/ui/repositories/<repo>/tag-details/` → JSON per-tag metadata
- `/ui/repositories/<repo>/delete-tag/`, `/ui/repositories/<repo>/delete/` → POST, admin only
- `/ui/tag-counts/` → JSON counts, `?repos=a,b,c` for a subset, `?force=true` to bypass the cache
- `/ui/admin/login/`, `/ui/admin/logout/`
- `/ui/stats/`, `/ui/stats/summary/`, `/ui/stats/repo/<repo>/` → admin only

### Frontend

Vanilla JavaScript + Bootstrap 5.3, **served from `ui/static/ui/vendor/`, not a CDN** (see README for versions and how
to upgrade them). Templates in `ui/templates/ui/` over a `base.html` layout; `_namespace_level.html` includes itself to
render the namespace tree.

`scripts.js` is a set of `init*()` functions, all called on `DOMContentLoaded`, each a no-op when its anchor element is
absent: `initThemeToggle`, `initFolderStates` (localStorage), `initCopyButtons`, `initTagDetails`, `initAdminDelete`
(modals + CSRF from the cookie), `initTagCounts` (batches of 10; a `null` count means unreadable and renders as an
error, not as "0 tags"), `initAdminStats` (summary then per-repo fan-out, 4 concurrent). Both scripts are `defer`red —
the inline theme snippet in `<head>` is the only one that must run before paint.

### Deployment

`docker compose` with a single `registry-ui` service. Image from `python:3.13-slim`, gunicorn with 2 workers × 8 threads
(the work is I/O, not CPU), running as the unprivileged `dockerui` user, with a `HEALTHCHECK` on `/ui/` and json-file
log rotation. `collectstatic` runs in the Dockerfile; nothing else does.

`.dockerignore` matters: the Dockerfile does `COPY . .`, so anything not excluded — `.env` included — stays readable in
an image layer.

`deploy.sh` drives all of it and waits for `/ui/` to answer from inside the container before declaring success. That
path returns 200 even when the registry is unreachable (the view renders an error banner), which is the intended
signal: it checks the UI, not the registry.

`docker-compose.yml` hands `.env` to the container with `env_file` rather than an explicit `environment:` list — the
list meant a key missing from `.env` arrived as an empty string and *overrode* the Django default instead of falling
back to it.

## Environment Variables

See README.md for the full tables (essentials, hardening, performance). The ones whose absence bites:

| Variable | Default | Why it matters |
|----------|---------|----------------|
| `REGISTRY_URL` | `http://registry:5000` | An empty value gets you an error banner and nothing else |
| `SECRET_KEY` | dev default | Signs the admin session cookie; a known key means a forgeable admin session |
| `CSRF_TRUSTED_ORIGINS` | (empty) | Required over HTTPS or a non-localhost host, or the admin login 403s |
| `ADMIN_PASSWORD` | (empty) | Empty disables admin mode entirely |
| `REGISTRY_MAX_WORKERS` | `8` | Parallel registry requests per page load; lower it if the registry complains |

## Conventions

- Lint with ruff (`./deploy.sh lint`), configured in `pyproject.toml`: line length 110, import sorting, pyupgrade and
  bugbear on. Keep it clean; it is quick.
- Tests are `SimpleTestCase` — there is no database to talk to. `ui/tests.py` fakes the registry with
  `RecordingSession`, which answers from a dict of URL-suffix → payload and records the calls, so tests can assert on
  how many requests were made.
- Comments explain the *why*, especially where the obvious-looking version was wrong (see the notes on the URL
  converter, the cache sentinel, and the per-tag blob dicts).
