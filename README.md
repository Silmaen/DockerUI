# DockerUI

A lightweight web interface for browsing Docker registries. It supports both the standard Docker Registry API and JFrog
Artifactory Docker repositories, and stores nothing of its own: there is no database, no user account and no persistent
state — every page is rendered from live registry data.

## Features

### Browsing

- Hierarchical namespace tree — `team/project/image` is displayed as nested folders, at any depth
- Folder expansion state persisted in `localStorage`, so a reload keeps the tree as you left it
- Tag counts and tag details (creation date, size, architectures) loaded asynchronously, and fetched from the registry
  in parallel, so a large registry renders immediately instead of blocking on the registry API
- Multi-architecture images: one badge per platform, attestation manifests filtered out
- One-click copy of the `docker pull` command for any tag
- Light/dark theme toggle, following the system preference by default
- Registry responses cached for 5 minutes, shared by every worker process

### Admin mode (optional)

Enabled by setting `ADMIN_PASSWORD`. It is a single shared password kept in a signed session cookie — deliberately
simple, and not a user database. Failed attempts are counted per client address and the form locks after ten of them.

- **Registry stats** page: repository and tag totals, storage usage per repository (blobs deduplicated by digest),
  top 10 by size and by tag count, the list of empty repositories that are garbage-collection candidates, and the list
  of repositories the registry could not answer for
- **Delete a tag** or **delete every tag of a repository**, from the detail page or the list page

Deleting requires the registry to allow it (see [Deletion](#deletion) below).

## Quick start

```bash
git clone https://github.com/Silmaen/DockerUI.git
cd DockerUI
cp .env_sample .env
$EDITOR .env          # at least REGISTRY_URL and SECRET_KEY
./deploy.sh
```

The UI is then served on `http://localhost:8000/ui/` (or the `PORT` set in `.env`).

## Deployment

`deploy.sh` is the single entry point: it updates the checkout, refreshes the base image, rebuilds, starts the
container and waits until the UI actually answers before reporting success.

| Command                   | Effect                                                               |
|---------------------------|----------------------------------------------------------------------|
| `./deploy.sh`             | full deployment: git pull + image refresh + build + up + health wait  |
| `./deploy.sh --no-pull`   | deploy without fetching anything (required if the tree is dirty)     |
| `./deploy.sh --tests`     | run the test suite before starting                                   |
| `./deploy.sh --dry-run`   | print every command, execute none                                    |
| `./deploy.sh check`       | report whether an update is pending, change nothing                  |
| `./deploy.sh status`      | service status                                                       |
| `./deploy.sh logs`        | follow the logs                                                      |
| `./deploy.sh restart`     | restart without rebuilding                                           |
| `./deploy.sh stop`        | stop and remove the container                                        |
| `./deploy.sh tests [app]` | run the tests in a throwaway container                               |
| `./deploy.sh lint [--fix]`| run ruff, in its own container                                       |
| `./deploy.sh shell`       | Django shell inside the container                                    |
| `./deploy.sh sh`          | interactive shell inside the container                                |
| `./deploy.sh help`        | the full help                                                        |

`check` is meant to be scripted — it only writes remote-tracking refs, never the working tree:

| Exit code | Meaning                                                       |
|-----------|---------------------------------------------------------------|
| `0`       | already up to date                                            |
| `10`      | an update is pending                                          |
| `1`       | cannot tell (not a git repository, no upstream, fetch failed)  |

Upgrading is therefore just `./deploy.sh`: no need to remove the image by hand, the build reuses the layer cache and
only the changed layers are rebuilt.

### Under the hood

Gunicorn on port 8000 inside the container: 2 workers × 8 threads, because a request spends its life waiting on the
registry rather than on a CPU. WhiteNoise serves the pre-collected static files. `collectstatic` runs at **build**
time, the container runs as an unprivileged user, writes nothing outside `/tmp`, and declares a `HEALTHCHECK` so
`docker compose ps` reports whether gunicorn actually answers.

There is no `migrate` step and no database: the only server-side state is the admin flag, and it lives in a signed
cookie. An admin session therefore survives a redeployment.

## Configuration

All configuration comes from environment variables. `docker-compose.yml` hands `.env` to the container as a file, so a
variable left out of `.env` simply keeps its default. Start from `.env_sample`.

### Essentials

| Variable                | Description                                                     | Default                               |
|-------------------------|-----------------------------------------------------------------|---------------------------------------|
| `REGISTRY_URL`          | URL of the registry                                             | `http://registry:5000`                |
| `REGISTRY_TYPE`         | `classic` or `artifactory`                                      | `classic`                             |
| `REGISTRY_REPO`         | Repository/namespace prefix (the Artifactory repository key)     | `""`                                  |
| `REGISTRY_SSL_VERIFY`   | Verify the registry's TLS certificate                           | `False`                               |
| `REGISTRY_USERNAME`     | Registry username (basic auth)                                  | `""`                                  |
| `REGISTRY_PASSWORD`     | Registry password or API token                                  | `""`                                  |
| `SECRET_KEY`            | Django secret key — signs the admin session cookie              | `django-insecure-default-key-for-dev` |
| `DEBUG`                 | Django debug mode; serves tracebacks, keep it off in production  | `False`                               |
| `PORT`                  | Host port published by compose                                   | `8000`                                |
| `CSRF_TRUSTED_ORIGINS`  | Comma-separated `scheme://host` list trusted for POSTs           | `""`                                  |
| `ADMIN_PASSWORD`        | Enables admin mode; empty disables it entirely                   | `""`                                  |

**`CSRF_TRUSTED_ORIGINS` is required as soon as the UI is reached over HTTPS or under a hostname that is not
`localhost`.** Without it the admin login POST is rejected with a 403 that explains nothing. Example:
`CSRF_TRUSTED_ORIGINS=https://dockerui.example.com`

### Hardening

| Variable                      | Description                                                              | Default |
|-------------------------------|--------------------------------------------------------------------------|---------|
| `ALLOWED_HOSTS`               | Comma-separated hostnames Django answers for                             | `*`     |
| `TRUST_PROXY`                 | Believe `X-Forwarded-Proto` / `X-Forwarded-For`                          | `False` |
| `SECURE_COOKIES`              | Restrict the session and CSRF cookies to HTTPS                           | `False` |
| `SESSION_COOKIE_AGE`          | Admin session lifetime, in seconds                                        | `28800` |
| `ADMIN_LOGIN_MAX_ATTEMPTS`    | Failed logins per client address before the form locks                    | `10`    |
| `ADMIN_LOGIN_LOCKOUT_SECONDS` | How long that lock lasts                                                  | `300`   |

`TRUST_PROXY` is only safe behind a proxy that *always* overwrites those headers; otherwise a client can claim its
plain HTTP request was secure, and can forge the address the login throttle counts against.

### Performance

| Variable               | Description                                            | Default               |
|------------------------|--------------------------------------------------------|-----------------------|
| `REGISTRY_CACHE_TTL`   | Seconds a registry response stays cached               | `300`                 |
| `REGISTRY_MAX_WORKERS` | Parallel registry requests per page load               | `8`                   |
| `CACHE_LOCATION`       | Where the response cache is written in the container    | `/tmp/dockerui-cache` |
| `CACHE_MAX_ENTRIES`    | Entries the cache keeps before culling                  | `20000`               |
| `LOG_LEVEL`            | `DEBUG`, `INFO`, `WARNING`, `ERROR`                     | `INFO`                |

The cache is file-backed rather than in-process: every gunicorn worker shares it, and it survives a restart. Point
`CACHE_LOCATION` at a tmpfs if the write churn matters, or swap the backend for Redis in `settings.py`.

### Registry types

Classic Docker registry:

```ini
REGISTRY_TYPE=classic
REGISTRY_URL=https://your-registry:5000
REGISTRY_REPO=
```

JFrog Artifactory — `REGISTRY_REPO` is the Docker repository key, and requests are routed through
`/artifactory/api/docker/<repo>/v2/`:

```ini
REGISTRY_TYPE=artifactory
REGISTRY_URL=https://artifactory.example.com
REGISTRY_REPO=your-docker-repo
```

### Deletion

Admin mode can delete tags, but only if the registry accepts it. For a classic registry, that means starting it with:

```ini
REGISTRY_STORAGE_DELETE_ENABLED=true
```

Without it the registry answers `405` and the UI reports it as such. Note that deleting a tag removes its *manifest*:
the blobs stay on disk until a garbage collection runs on the registry host.

```bash
registry garbage-collect -m /etc/docker/registry/config.yml
```

This is why the stats page lists empty repositories — they are exactly the ones worth collecting. Repositories the
registry failed to answer for are listed apart, never as empty: "unknown" is not "safe to delete".

## Development

```bash
pip install -r requirements.txt
cp .env_sample .env          # DEBUG=True is fine here
python manage.py runserver
```

Tests and lint both run in containers, so nothing has to be installed for them:

```bash
./deploy.sh tests            # or: python manage.py test --settings=DockerUI.settings_test
./deploy.sh lint --fix
```

`DockerUI/settings_test.py` is a thin overlay on the real settings: plain static-files storage (so tests do not depend
on `collectstatic` having run), an in-process cache, and a registry hostname that resolves to nothing — the suite never
talks to a real registry.

After changing anything under `ui/static/`, the production image needs a rebuild: WhiteNoise serves the hashed files
produced by `collectstatic` at build time, not the sources.

### Front-end assets

Bootstrap and Bootstrap Icons are served from `ui/static/ui/vendor/`, not from a CDN. A registry UI is typically
deployed on an internal network, and a page whose stylesheet lives on `cdn.jsdelivr.net` renders unstyled and iconless
exactly there — besides announcing every visit to a third party.

| File                                                                                | Upstream                                            | Version | License |
|-------------------------------------------------------------------------------------|-----------------------------------------------------|---------|---------|
| `bootstrap.min.css`, `bootstrap.bundle.min.js`                                      | [getbootstrap.com](https://getbootstrap.com/)       | 5.3.8   | MIT     |
| `bootstrap-icons.css`, `fonts/bootstrap-icons.woff2`, `fonts/bootstrap-icons.woff`   | [icons.getbootstrap.com](https://icons.getbootstrap.com/) | 1.13.1  | MIT     |

The files are upstream's as published, with one edit: the trailing `sourceMappingURL` comment is stripped from the two
minified Bootstrap files, because `CompressedManifestStaticFilesStorage` resolves that pointer like any other asset
reference and aborts `collectstatic` when the `.map` is missing.

To upgrade them:

```bash
BS=5.3.8 BI=1.13.1
cd ui/static/ui/vendor
curl -sSfL -o bootstrap.min.css           "https://cdn.jsdelivr.net/npm/bootstrap@$BS/dist/css/bootstrap.min.css"
curl -sSfL -o bootstrap.bundle.min.js     "https://cdn.jsdelivr.net/npm/bootstrap@$BS/dist/js/bootstrap.bundle.min.js"
curl -sSfL -o bootstrap-icons.css         "https://cdn.jsdelivr.net/npm/bootstrap-icons@$BI/font/bootstrap-icons.css"
curl -sSfL -o fonts/bootstrap-icons.woff2 "https://cdn.jsdelivr.net/npm/bootstrap-icons@$BI/font/fonts/bootstrap-icons.woff2"
curl -sSfL -o fonts/bootstrap-icons.woff  "https://cdn.jsdelivr.net/npm/bootstrap-icons@$BI/font/fonts/bootstrap-icons.woff"
sed -i 's|/\*# sourceMappingURL=[^ ]* \*/||; s|//# sourceMappingURL=.*$||' bootstrap.min.css bootstrap.bundle.min.js
```

Then update the versions in the table above and rebuild the image.

### URL routes

| Route                                      | View                                                    |
|--------------------------------------------|---------------------------------------------------------|
| `/`                                        | permanent redirect to `/ui/`                            |
| `/ui/`, `/ui/repositories/`                | repository list                                         |
| `/ui/repositories/<repo>/`                 | repository detail (tags)                                |
| `/ui/repositories/<repo>/tag-details/`     | JSON: dates, sizes, architectures for every tag         |
| `/ui/repositories/<repo>/delete-tag/`      | POST, admin: delete one tag                             |
| `/ui/repositories/<repo>/delete/`          | POST, admin: delete every tag                           |
| `/ui/tag-counts/`                          | JSON: tag counts, optionally `?repos=a,b,c`             |
| `/ui/admin/login/`, `/ui/admin/logout/`    | admin mode session                                      |
| `/ui/stats/`                               | admin: stats page                                       |
| `/ui/stats/summary/`                       | JSON: catalog-wide counts                               |
| `/ui/stats/repo/<repo>/`                   | JSON: per-repository size and blob count                |

`<repo>` accepts slashes but every path component has to start with an alphanumeric character, which is what keeps `..`
out of the URLs sent to the registry. Django's own `/admin/` is not mounted: this project has no models and no user
accounts, so it only ever offered a login form to brute-force.

## License

This project is licensed under the terms of the license included in the [LICENSE](LICENSE) file at the root of this
project.
