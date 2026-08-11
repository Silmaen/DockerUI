# DockerUI

A lightweight web interface for browsing Docker registries. It supports both the standard Docker Registry API and JFrog
Artifactory Docker repositories, and stores nothing of its own: every page is rendered from live registry data.

## Features

### Browsing

- Hierarchical namespace tree — `team/project/image` is displayed as nested folders, at any depth
- Folder expansion state persisted in `localStorage`, so a reload keeps the tree as you left it
- Tag counts and tag details (creation date, size, architectures) loaded asynchronously, in batches, so a large registry
  renders immediately instead of blocking on the registry API
- Multi-architecture images: one badge per platform, attestation manifests filtered out
- One-click copy of the `docker pull` command for any tag
- Light/dark theme toggle, following the system preference by default
- 5-minute cache on registry responses, 1 hour on the catalog-wide tag counts

### Admin mode (optional)

Enabled by setting `ADMIN_PASSWORD`. It is a single shared password stored in the session — deliberately simple, and not
a user database.

- **Registry stats** page: repository and tag totals, storage usage per repository (blobs deduplicated by digest),
  top 10 by size and by tag count, and the list of empty repositories that are garbage-collection candidates
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

| Command                | Effect                                                              |
|------------------------|---------------------------------------------------------------------|
| `./deploy.sh`          | full deployment: git pull + image refresh + build + up + health wait |
| `./deploy.sh --no-pull` | deploy without fetching anything (required if the tree is dirty)   |
| `./deploy.sh --tests`  | run the test suite before starting                                  |
| `./deploy.sh --dry-run` | print every command, execute none                                  |
| `./deploy.sh check`    | report whether an update is pending, change nothing                 |
| `./deploy.sh status`   | service status                                                      |
| `./deploy.sh logs`     | follow the logs                                                     |
| `./deploy.sh restart`  | restart without rebuilding                                          |
| `./deploy.sh stop`     | stop and remove the container                                       |
| `./deploy.sh tests`    | run the tests in a throwaway container                              |
| `./deploy.sh shell`    | Django shell inside the container                                   |
| `./deploy.sh sh`       | interactive shell inside the container                               |
| `./deploy.sh help`     | the full help                                                       |

`check` is meant to be scripted — it only writes remote-tracking refs, never the working tree:

| Exit code | Meaning                                                     |
|-----------|-------------------------------------------------------------|
| `0`       | already up to date                                          |
| `10`      | an update is pending                                        |
| `1`       | cannot tell (not a git repository, no upstream, fetch failed) |

Upgrading is therefore just `./deploy.sh`: no need to remove the image by hand, the build reuses the layer cache and
only the changed layers are rebuilt.

### Under the hood

Gunicorn (2 workers, 2 threads) on port 8000 inside the container, WhiteNoise serving the pre-collected static files.
Migrations and `collectstatic` run at **build** time, so the container has nothing to prepare on startup.

## Configuration

All configuration comes from environment variables, read from `.env` by `docker compose`. Start from `.env_sample`.

| Variable                | Description                                                    | Default                               |
|-------------------------|----------------------------------------------------------------|---------------------------------------|
| `REGISTRY_URL`          | URL of the registry                                            | `http://registry:5000`                |
| `REGISTRY_TYPE`         | `classic` or `artifactory`                                     | `classic`                             |
| `REGISTRY_REPO`         | Repository/namespace prefix (the Artifactory repository key)    | `""`                                  |
| `REGISTRY_SSL_VERIFY`   | Verify the registry's TLS certificate                          | `False`                               |
| `REGISTRY_USERNAME`     | Registry username (basic auth)                                 | `""`                                  |
| `REGISTRY_PASSWORD`     | Registry password or API token                                 | `""`                                  |
| `SECRET_KEY`            | Django secret key — set it, sessions are signed with it        | `django-insecure-default-key-for-dev` |
| `DEBUG`                 | Django debug mode; serves tracebacks, keep it off in production | `False`                               |
| `PORT`                  | Host port published by compose                                  | `8000`                                |
| `CSRF_TRUSTED_ORIGINS`  | Comma-separated `scheme://host` list trusted for POSTs          | `""`                                  |
| `ADMIN_PASSWORD`        | Enables admin mode; empty disables it entirely                  | `""`                                  |

Two of these have consequences that are easy to miss:

- **`CSRF_TRUSTED_ORIGINS`** is required as soon as the UI is reached over HTTPS or under a hostname that is not
  `localhost`. Without it the admin login POST is rejected with a 403 that explains nothing. Example:
  `CSRF_TRUSTED_ORIGINS=https://dockerui.example.com`
- **A variable absent from `.env` is passed to the container as an empty string**, because `docker-compose.yml`
  enumerates them explicitly. An empty `REGISTRY_URL` overrides the default instead of falling back to it, so the app
  talks to nothing at all. `deploy.sh` warns about any missing key.

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

This is why the stats page lists empty repositories — they are exactly the ones worth collecting.

## Development

```bash
pip install -r requirements.txt
cp .env_sample .env          # DEBUG=True is fine here
python manage.py migrate
python manage.py runserver
```

Tests run either natively (`python manage.py test`) or, preferably, in the image: `./deploy.sh tests`.

After changing anything under `ui/static/`, the production image needs a rebuild — WhiteNoise serves the hashed files
produced by `collectstatic` at build time, not the sources.

### URL routes

| Route                                      | View                                                   |
|--------------------------------------------|--------------------------------------------------------|
| `/`                                        | permanent redirect to `/ui/`                           |
| `/ui/`, `/ui/repositories/`                | repository list                                        |
| `/ui/repositories/<repo>/`                 | repository detail (tags)                               |
| `/ui/repositories/<repo>/tag-details/`     | JSON: dates, sizes, architectures for every tag        |
| `/ui/repositories/<repo>/delete-tag/`      | POST, admin: delete one tag                            |
| `/ui/repositories/<repo>/delete/`          | POST, admin: delete every tag                          |
| `/ui/tag-counts/`                          | JSON: tag counts, optionally `?repos=a,b,c`            |
| `/ui/admin/login/`, `/ui/admin/logout/`    | admin mode session                                     |
| `/ui/stats/`                               | admin: stats page                                      |
| `/ui/stats/summary/`                       | JSON: catalog-wide counts                              |
| `/ui/stats/repo/<repo>/`                   | JSON: per-repository size and blob count               |

## License

This project is licensed under the terms of the license included in the [LICENSE](LICENSE) file at the root of this
project.
