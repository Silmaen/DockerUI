# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

DockerUI is a Django web application that provides a browser-based UI for Docker container registries. It supports both classic Docker Registry and JFrog Artifactory backends. There are no custom database models — SQLite is only used for Django internals.

## Development Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run development server
python manage.py runserver

# Run tests
python manage.py test

# Collect static files (required after CSS/JS changes for production)
python manage.py collectstatic

# Run migrations
python manage.py migrate

# Docker build and run
docker compose up -d
docker compose down
```

## Architecture

**Request flow:** Browser → Django URL router → `ui/views.py` → `ui/registry_client.py` → Docker Registry/Artifactory HTTP API

### Key Modules

- **`DockerUI/settings.py`** — Django settings; all registry configuration comes from environment variables (REGISTRY_URL, REGISTRY_TYPE, REGISTRY_USERNAME, REGISTRY_PASSWORD, etc.)
- **`ui/registry_client.py`** — Encapsulates all Docker Registry API communication. Handles authentication, caching (5–300s TTL), and abstracts the difference between classic and Artifactory registry types.
- **`ui/views.py`** — Three view functions: `repository_list` (hierarchical namespace grouping with recursive nesting), `repository_detail` (tags with metadata, multi-architecture support), and `get_tag_counts` (JSON API for lazy-loaded counts).
- **`ui/formating.py`** — Utility formatters: `format_time_difference()` and `format_size()`.
- **`ui/context_processors.py`** — Injects app version (from `VERSION` file) into all templates.

### URL Routes

- `/` → redirects to `/ui/`
- `/ui/` and `/ui/repositories/` → repository list
- `/ui/repositories/<repo_name>/` → repository detail (uses `re_path` to handle slashes in names)
- `/ui/tag-counts/` → JSON endpoint for async tag count loading

### Frontend

Vanilla JavaScript + Bootstrap 5.3 dark theme. Static files in `ui/static/ui/`. Templates in `ui/templates/ui/` with a `base.html` layout. Key frontend behaviors: localStorage-persisted folder expansion, async tag count fetching, clipboard copy for `docker pull` commands, architecture badges.

### Deployment

Gunicorn (3 workers, 2 threads) on port 8000. WhiteNoise serves static files. Docker image based on `python:slim`.

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `REGISTRY_URL` | `http://registry:5000` | Registry server URL |
| `REGISTRY_TYPE` | `classic` | `classic` or `artifactory` |
| `REGISTRY_REPO` | (empty) | Namespace prefix for repositories |
| `REGISTRY_SSL_VERIFY` | `False` | SSL certificate verification |
| `REGISTRY_USERNAME` | (empty) | Registry auth username |
| `REGISTRY_PASSWORD` | (empty) | Registry auth password |
| `SECRET_KEY` | dev default | Django secret key |
| `DEBUG` | `False` | Django debug mode |
