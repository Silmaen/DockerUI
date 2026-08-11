#!/usr/bin/env bash
#
# All-in-one deployment for DockerUI: git, build, start, health check.
#
# collectstatic runs at image build time and the application has no database, so
# this script has nothing to prepare before starting the container.
#
#   ./deploy.sh                 full deployment (pull + build + up + wait)
#   ./deploy.sh --no-pull       fetch nothing: neither the git update nor the images
#   ./deploy.sh --tests         run the test suite before starting
#   ./deploy.sh --dry-run       print what would run, execute nothing
#   ./deploy.sh check           only look for a pending update, change nothing
#   ./deploy.sh status          service status
#   ./deploy.sh logs            follow the logs
#   ./deploy.sh stop            stop everything
#   ./deploy.sh restart         restart without rebuilding
#   ./deploy.sh tests [app]     run the tests
#   ./deploy.sh lint [--fix]    ruff, in its own container
#   ./deploy.sh shell           Django shell inside the container
#   ./deploy.sh sh              interactive shell inside the container
#   ./deploy.sh help            this help
#
# `check` (alias `--check`) exits with a status meant to be scripted:
#   0   already up to date
#   10  an update is pending
#   1   cannot tell (not a git repository, no upstream, fetch failed)
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

SERVICE=registry-ui
MANAGE=(python /app/manage.py)
# Pinned: a linter that changes its mind on its own turns a green tree red without
# a single line of code moving.
RUFF_IMAGE=ghcr.io/astral-sh/ruff:0.14.4
HEALTH_TIMEOUT=90
# Probed from inside the container: the image always ships python, the host may
# ship neither curl nor wget, and this works even when the port is not published.
HEALTH_PATH=/ui/

PULL=1
TESTS=0
DRY_RUN=0
FIX=0

# --- Output ------------------------------------------------------------------

if [ -t 1 ]; then
    C_STEP=$'\033[1;34m'; C_OK=$'\033[0;32m'; C_WARN=$'\033[0;33m'
    C_ERR=$'\033[0;31m'; C_END=$'\033[0m'
else
    C_STEP=""; C_OK=""; C_WARN=""; C_ERR=""; C_END=""
fi

step() { printf '\n%s==> %s%s\n' "$C_STEP" "$1" "$C_END"; }
ok()   { printf '%s  ✓ %s%s\n' "$C_OK" "$1" "$C_END"; }
warn() { printf '%s  ! %s%s\n' "$C_WARN" "$1" "$C_END"; }
fail() { printf '%s  ✗ %s%s\n' "$C_ERR" "$1" "$C_END" >&2; exit 1; }

# Run a command, or just print it in --dry-run mode.
run() {
    if [ "$DRY_RUN" -eq 1 ]; then
        printf '  [dry-run] %s\n' "$*"
        return 0
    fi
    "$@"
}

# The help text is the file header: one place to keep up to date.
usage() {
    awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "${BASH_SOURCE[0]}"
}

# --- Preflight checks --------------------------------------------------------

check_tools() {
    command -v docker >/dev/null 2>&1 || fail "docker not found."
    docker compose version >/dev/null 2>&1 \
        || fail "the 'docker compose' plugin is missing (docker-compose v1 is not supported)."
    docker info >/dev/null 2>&1 \
        || fail "the docker daemon is not responding: is it running, and is your account in the docker group?"
    ok "docker and docker compose available"
}

# Read a variable from .env, falling back to the given default.
env_value() {
    local key="$1" default="${2:-}" line
    line="$(grep -E "^${key}=" .env 2>/dev/null | tail -1 || true)"
    if [ -z "$line" ]; then
        printf '%s' "$default"
    else
        printf '%s' "${line#*=}"
    fi
}

check_env() {
    if [ ! -f .env ]; then
        warn ".env missing, copying .env_sample"
        cp .env_sample .env
        fail "edit .env (at least REGISTRY_URL and SECRET_KEY) then run again."
    fi

    # Since compose passes .env as a file, a key left out simply keeps its default --
    # only an empty REGISTRY_URL is fatal, and that is the number one cause of a UI
    # that renders an error banner and nothing else.
    [ -n "$(env_value REGISTRY_URL)" ] || fail "REGISTRY_URL is empty in .env."

    case "$(env_value DEBUG)" in
        [Tt]rue) warn "DEBUG=True: tracebacks are served to visitors, do not leave this on a shared host" ;;
    esac
    case "$(env_value SECRET_KEY)" in
        ""|change-me|iamsecret|django-insecure-*)
            warn "SECRET_KEY is a default/example value: the admin session cookie can be forged" ;;
    esac
    # HTTPS or a non-localhost hostname makes Django reject the admin login POST
    # without this, with a 403 that says nothing useful.
    if [ -n "$(env_value ADMIN_PASSWORD)" ] && [ -z "$(env_value CSRF_TRUSTED_ORIGINS)" ]; then
        warn "ADMIN_PASSWORD set but CSRF_TRUSTED_ORIGINS empty: the login will 403 unless served from localhost"
    fi
    ok ".env present"
}

# --- Steps -------------------------------------------------------------------

update_repository() {
    step "Updating the repository"
    if [ ! -d .git ]; then
        warn "not a git repository, skipping the update"
        return 0
    fi
    if [ -n "$(git status --porcelain)" ]; then
        git status --short
        fail "the repository has local changes: commit them, stash them, or use --no-pull."
    fi
    local before
    before="$(git rev-parse HEAD)"
    run git pull --ff-only
    if [ "$DRY_RUN" -eq 0 ]; then
        local after
        after="$(git rev-parse HEAD)"
        if [ "$before" = "$after" ]; then
            ok "already up to date ($(git rev-parse --short HEAD))"
        else
            ok "updated: $(git rev-parse --short "$before") -> $(git rev-parse --short "$after")"
            git --no-pager log --oneline "$before..$after"
        fi
    fi
}

# Report whether the remote is ahead, and touch nothing else. `git fetch` only writes
# remote-tracking refs, never the working tree, so this is safe to run on a schedule.
check_update() {
    step "Checking for a pending update"
    [ -d .git ] || fail "not a git repository, cannot check for updates."

    local branch upstream
    branch="$(git rev-parse --abbrev-ref HEAD)"
    # An unresolvable revision makes rev-parse echo the argument back and still exit
    # 0, which is what happens once the remote branch has been deleted. So the ref is
    # verified rather than merely non-empty.
    upstream="$(git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null || true)"
    if [ -z "$upstream" ] || [ "$upstream" = "@{upstream}" ] \
       || ! git rev-parse --verify --quiet "${upstream}^{commit}" >/dev/null; then
        fail "branch '$branch' has no usable upstream (never set, or the remote branch is gone)."
    fi

    if [ "$DRY_RUN" -eq 1 ]; then
        printf '  [dry-run] git fetch --quiet\n'
        warn "comparing against the remote refs already on disk"
    else
        git fetch --quiet || fail "git fetch failed: is the remote reachable?"
    fi

    local behind ahead counts
    counts="$(git rev-list --left-right --count "${upstream}...HEAD" 2>/dev/null || true)"
    [ -n "$counts" ] || fail "cannot compare '$branch' with '$upstream'."
    read -r behind ahead <<< "$counts"
    ok "branch '$branch' tracking '$upstream'"

    # A dirty tree does not block this check, but it will block the deployment.
    if [ -n "$(git status --porcelain)" ]; then
        warn "local changes present: a deployment will need --no-pull"
    fi

    if [ "$ahead" -gt 0 ] && [ "$behind" -eq 0 ]; then
        ok "up to date ($ahead local commit(s) not pushed)"
        return 0
    fi

    if [ "$behind" -eq 0 ]; then
        ok "up to date ($(git rev-parse --short HEAD))"
        return 0
    fi

    if [ "$ahead" -gt 0 ]; then
        warn "branches have diverged: $behind incoming, $ahead local commit(s)"
    else
        warn "$behind commit(s) pending"
    fi
    git --no-pager log --oneline "HEAD..${upstream}"
    printf '\n     deploy with: ./deploy.sh\n'
    exit 10
}

# Refresh the Dockerfile's base image. `docker compose pull` skips buildable
# services, so without this explicit pull a pinned `python:3.13-slim` stays on
# whatever was fetched the first time -- and that is where the CVE fixes land.
# The tag is read from the Dockerfile rather than repeated here.
#
# A registry we cannot reach is a warning, not a failure: the image already on
# disk is enough to deploy, and aborting would leave the update half done.
pull_images() {
    step "Refreshing the images"
    local stale=0 base
    run docker compose pull --ignore-buildable --quiet || stale=1
    base="$(awk '/^FROM/ { print $2; exit }' Dockerfile 2>/dev/null || true)"
    if [ -n "$base" ]; then
        run docker pull --quiet "$base" || stale=1
    fi
    if [ "$stale" -eq 1 ]; then
        warn "some images could not be refreshed, keeping the ones already on disk"
    else
        ok "images up to date"
    fi
}

build_image() {
    step "Building the image"
    run docker compose build
    ok "image built"
}

run_tests() {
    local target="${1:-}"
    step "Tests${target:+ ($target)}"
    # Throwaway container, no network dependency on the running service, and
    # settings that point at no registry at all: the tests must never talk to a
    # real one.
    run docker compose run --rm --no-deps "$SERVICE" \
        "${MANAGE[@]}" test ${target:+"$target"} --noinput \
        --settings=DockerUI.settings_test
    ok "tests passed"
}

# ruff comes from its own published image rather than from the application image:
# the linter has no business being installed next to the running server, and this
# keeps the runtime image free of development tooling. Configuration lives in
# pyproject.toml.
run_lint() {
    local extra="${1:-}"
    step "Lint${extra:+ ($extra)}"
    run docker run --rm -v "$ROOT:/io" -w /io --user "$(id -u):$(id -g)" \
        "$RUFF_IMAGE" check . ${extra:+"$extra"}
    ok "lint clean"
}

start_services() {
    step "Starting the services"
    # --remove-orphans: a renamed service otherwise keeps its old container running
    # and holding the published port.
    if ! run docker compose up -d --remove-orphans; then
        # By far the most common cause, and the daemon's own message ("Bind for
        # 0.0.0.0:8000 failed") does not say which knob to turn.
        local port
        # Same precedence as compose: the shell environment wins over .env.
        port="${PORT:-$(env_value PORT 8000)}"
        warn "port ${port} may already be used by another service (change PORT in .env)"
        fail "docker compose up failed."
    fi
    ok "services started"
}

# The compose file declares no healthcheck, so "running" is all Docker can tell us.
# Gunicorn answering on /ui/ is the real signal -- and it answers 200 even when the
# registry itself is unreachable (the view renders the error banner), which is
# exactly right here: this checks the UI, not the registry behind it.
check_health() {
    step "Checking health"
    if [ "$DRY_RUN" -eq 1 ]; then
        printf '  [dry-run] would wait for %s to answer on %s\n' "$SERVICE" "$HEALTH_PATH"
        return 0
    fi

    local elapsed=0 cid status
    cid="$(docker compose ps -q "$SERVICE" 2>/dev/null || true)"
    [ -n "$cid" ] || fail "service $SERVICE did not start."

    while [ "$elapsed" -lt "$HEALTH_TIMEOUT" ]; do
        status="$(docker inspect -f '{{.State.Status}}' "$cid")"
        [ "$status" = "running" ] || break
        if docker exec "$cid" python -c "
import sys, urllib.request
try:
    with urllib.request.urlopen('http://127.0.0.1:8000${HEALTH_PATH}', timeout=5) as r:
        sys.exit(0 if r.status < 400 else 1)
except Exception:
    sys.exit(1)
" >/dev/null 2>&1; then
            printf '\r'
            ok "$SERVICE answers on $HEALTH_PATH"
            return 0
        fi
        sleep 3
        elapsed=$((elapsed + 3))
        printf '\r  ... %s: waiting (%ss)' "$SERVICE" "$elapsed"
    done
    printf '\n'
    docker compose logs --tail 40 "$SERVICE" || true
    fail "$SERVICE did not become operational within ${HEALTH_TIMEOUT}s."
}

summary() {
    step "Service status"
    docker compose ps
    local port
    # Same precedence as compose: the shell environment wins over .env.
    port="${PORT:-$(env_value PORT 8000)}"
    printf '\n'
    ok "UI available at http://localhost:${port}/ui/"
    if [ -n "$(env_value ADMIN_PASSWORD)" ]; then
        printf '     admin:   http://localhost:%s/ui/admin/login/\n' "$port"
    fi
    printf '     registry: %s\n' "$(env_value REGISTRY_URL)"
    printf '     logs:     ./deploy.sh logs\n'
}

deploy() {
    step "Deploying DockerUI"
    [ "$DRY_RUN" -eq 1 ] && warn "--dry-run mode: no command is executed"
    check_tools
    check_env
    [ "$PULL" -eq 1 ] && update_repository
    [ "$PULL" -eq 1 ] && pull_images
    build_image
    [ "$TESTS" -eq 1 ] && run_tests
    start_services
    check_health
    [ "$DRY_RUN" -eq 0 ] && summary
    return 0
}

# --- Entry point -------------------------------------------------------------

COMMAND="deploy"
ARGUMENT=""

while [ $# -gt 0 ]; do
    case "$1" in
        --no-pull)  PULL=0 ;;
        --tests)    TESTS=1 ;;
        --dry-run)  DRY_RUN=1 ;;
        --fix)      FIX=1 ;;
        -h|--help|help) usage; exit 0 ;;
        --check)    COMMAND="check" ;;
        deploy|check|status|logs|stop|restart|tests|lint|shell|sh)
            COMMAND="$1"
            if [ $# -gt 1 ] && [[ "$2" != -* ]]; then
                ARGUMENT="$2"
                shift
            fi
            ;;
        *) fail "unknown argument: $1 (see ./deploy.sh help)" ;;
    esac
    shift
done

case "$COMMAND" in
    deploy)  deploy ;;
    check)   check_update ;;
    status)  check_tools; docker compose ps ;;
    logs)    docker compose logs -f "$SERVICE" ;;
    stop)    step "Stopping"; docker compose down; ok "services stopped" ;;
    restart) step "Restarting"; docker compose restart; check_health; summary ;;
    tests)   check_tools; check_env; run_tests "$ARGUMENT" ;;
    lint)
        check_tools
        if [ "$FIX" -eq 1 ]; then run_lint --fix; else run_lint; fi
        ;;
    shell)   docker compose exec "$SERVICE" "${MANAGE[@]}" shell ;;
    sh)      docker compose exec "$SERVICE" bash ;;
esac
