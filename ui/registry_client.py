# registry_client.py
import logging

import requests
import urllib3
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

# Silence the "unverified HTTPS request" warning only when unverified requests are
# what the deployment asked for. It used to be disabled unconditionally at import
# time, which also hid the warning from a deployment that had verification on and a
# genuine certificate problem.
if not settings.REGISTRY_SSL_VERIFY:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def get_registry_session():
    """
    Create and configure a session for interacting with the Docker Registry API.
    """
    session = requests.Session()
    session.verify = settings.REGISTRY_SSL_VERIFY

    if settings.REGISTRY_USERNAME and settings.REGISTRY_PASSWORD:
        session.auth = (settings.REGISTRY_USERNAME, settings.REGISTRY_PASSWORD)

    return session


def check_endpoint(endpoint):
    """Refuse an endpoint that could escape the registry's API prefix.

    `requests` resolves `..` when it prepares a URL, so a crafted repository name
    is enough to point a credentialed call at any path on the registry host. The
    URL converter in `converters.py` already rejects those names at the routing
    layer; this is the second lock, on the sink itself, for endpoints assembled
    from anywhere else.
    """
    for part in endpoint.split("/"):
        if part in ("", ".", ".."):
            raise ValueError(f"invalid registry endpoint: {endpoint!r}")


def _build_registry_url(endpoint):
    """Build the full registry URL for an endpoint, whatever the registry type.

    This used to exist twice: `get_registry_data` inlined its own copy with extra
    branches for `_catalog` and `/tags/list`, both of which produced exactly the
    string the general case produces. The duplicate is gone -- one place decides
    what a registry URL looks like.
    """
    check_endpoint(endpoint)
    if settings.REGISTRY_TYPE.lower() == "artifactory":
        return f"{settings.REGISTRY_URL}/artifactory/api/docker/{settings.REGISTRY_REPO}/v2/{endpoint}"
    elif settings.REGISTRY_REPO:
        return f"{settings.REGISTRY_URL}/v2/{settings.REGISTRY_REPO}/{endpoint}"
    else:
        return f"{settings.REGISTRY_URL}/v2/{endpoint}"


# Distinguishes "not in the cache" from "cached, and the value is None" -- a 404 is
# a legitimate answer worth remembering, and `cache.get(key)` alone cannot tell the
# two apart.
_CACHE_MISS = object()

# Every manifest media type this UI knows how to read, plus plain JSON for the
# catalog and blob endpoints.
_ACCEPT_HEADER = ", ".join(
    (
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.docker.distribution.manifest.v2+json",
        "application/vnd.docker.distribution.manifest.v1+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.oci.image.index.v1+json",
        "application/json",
    )
)


def cache_key_for(endpoint):
    """The cache key holding the response for `endpoint`."""
    return f"registry_{endpoint}"


def get_registry_data(endpoint):
    """Get data from Docker Registry API, cached. Returns None for a missing resource."""
    check_endpoint(endpoint)
    cache_key = cache_key_for(endpoint)
    cached_data = cache.get(cache_key, _CACHE_MISS)

    # `if cached_data:` here used to treat an empty-but-valid response -- an image
    # with no tags, most commonly -- as a miss, and refetched it every single time.
    if cached_data is not _CACHE_MISS:
        return cached_data

    session = get_registry_session()
    url = _build_registry_url(endpoint)

    response = session.get(url, headers={"Accept": _ACCEPT_HEADER}, timeout=30)
    if response.status_code == 404:
        logger.warning(f"Resource not found: {url}")
        # Remembered as well: a repository listed in the catalog but already
        # garbage-collected would otherwise be re-requested on every page load.
        cache.set(cache_key, None, settings.REGISTRY_CACHE_TTL)
        return None

    response.raise_for_status()

    result = response.json()
    cache.set(cache_key, result, settings.REGISTRY_CACHE_TTL)
    return result


def get_tag_count(repository):
    """Get tag count for a single repository"""
    try:
        tags_data = get_registry_data(f"{repository}/tags/list")
        return len(tags_data.get("tags", [])) if tags_data else 0
    except Exception as e:
        logger.error(f"Error getting tags for {repository}: {str(e)}")
        return 0


def get_tag_counts_for(repositories):
    """Tag counts for the given repositories, keyed by name."""
    return {repo: get_tag_count(repo) for repo in repositories}


def get_all_tag_counts(force_refresh=False):
    """Get tag counts for all repositories with better error handling and logging"""

    # Check cache first
    tag_counts = cache.get("repository_tag_counts")
    if tag_counts is not None and not force_refresh:
        logger.debug(f"Using cached tag counts: {tag_counts}")
        return tag_counts

    logger.info("Refreshing repository tag counts")
    tag_counts = {}

    # Get all repositories
    data = get_registry_data("_catalog")
    repositories = data.get("repositories", []) if data else []

    # Process all repositories synchronously (more reliable than threading)
    for repo in repositories:
        try:
            logger.debug(f"Fetching tags for repo: {repo}")
            tags_data = get_registry_data(f"{repo}/tags/list")

            if tags_data and "tags" in tags_data:
                tag_counts[repo] = len(tags_data["tags"])
                logger.debug(f"Found {tag_counts[repo]} tags for {repo}")
            else:
                logger.warning(f"No tags found for {repo}")
                tag_counts[repo] = 0

        except Exception as e:
            logger.error(f"Error getting tags for {repo}: {str(e)}")
            tag_counts[repo] = 0

    # Cache for 1 hour
    cache.set("repository_tag_counts", tag_counts, 3600)
    logger.info(f"Tag counts updated and cached: {tag_counts}")

    return tag_counts


def get_manifest_digest(repository, tag):
    """Get the Docker-Content-Digest for a tag via HEAD request."""
    session = get_registry_session()
    url = _build_registry_url(f"{repository}/manifests/{tag}")
    response = session.head(url, headers={"Accept": _ACCEPT_HEADER}, timeout=30)
    response.raise_for_status()
    return response.headers.get("Docker-Content-Digest")


def delete_manifest(repository, digest):
    """Delete a manifest by digest."""
    session = get_registry_session()
    url = _build_registry_url(f"{repository}/manifests/{digest}")
    response = session.delete(url, timeout=30)
    response.raise_for_status()
    return True


def invalidate_cache(repository, tags=()):
    """Purge cache keys after a mutation.

    `tags` are the tags that were just deleted. Without them the manifest entries
    survive -- `registry_<repo>/manifests/<tag>` is a separate key from the tag
    list -- and a deleted tag kept reporting its size and creation date for the
    rest of the TTL.
    """
    keys = [
        cache_key_for(f"{repository}/tags/list"),
        cache_key_for("_catalog"),
        "repository_tag_counts",
        stats_cache_key(repository),
    ]
    keys += [cache_key_for(f"{repository}/manifests/{tag}") for tag in tags]
    cache.delete_many(keys)


def _collect_manifest_blobs(repository, reference, seen):
    """Recursively walk a manifest (or manifest list) and add (digest, size) pairs to `seen`.

    `seen` is a dict {digest: size} used for cross-repo deduplication.
    Returns the sum of unique blob sizes added by this call (not the full repo size).
    """
    manifest = get_registry_data(f"{repository}/manifests/{reference}")
    if not manifest:
        return 0

    added = 0

    # Manifest list (multi-arch / OCI index)
    if manifest.get("manifests"):
        for entry in manifest["manifests"]:
            digest = entry.get("digest")
            if not digest:
                continue
            added += _collect_manifest_blobs(repository, digest, seen)
        return added

    # Single-arch manifest: config + layers
    config = manifest.get("config") or {}
    config_digest = config.get("digest")
    if config_digest and config_digest not in seen:
        seen[config_digest] = config.get("size", 0)
        added += config.get("size", 0)

    for layer in manifest.get("layers", []):
        digest = layer.get("digest")
        if not digest or digest in seen:
            continue
        size = layer.get("size", 0)
        seen[digest] = size
        added += size

    return added


def stats_cache_key(repository):
    """The cache key holding the computed stats for `repository`."""
    return f"registry_repo_stats_{repository}"


def get_repo_stats(repository, force_refresh=False):
    """Return per-repo stats: {tags, size, blobs}. Cached for REGISTRY_CACHE_TTL.

    `size` is the sum of unique blob sizes within this repo (deduped by digest).
    `blobs` is the unique blob digest count.
    """
    cache_key = stats_cache_key(repository)
    if not force_refresh:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

    tags_data = get_registry_data(f"{repository}/tags/list")
    tags = tags_data.get("tags", []) if tags_data else []

    repo_blobs = {}
    errors = []
    for tag in tags:
        try:
            _collect_manifest_blobs(repository, tag, repo_blobs)
        except Exception as e:
            logger.error(f"Error reading manifest {repository}:{tag}: {e}")
            errors.append({"tag": tag, "error": str(e)})

    result = {
        "repository": repository,
        "tags": len(tags),
        "size": sum(repo_blobs.values()),
        "blobs": len(repo_blobs),
        "errors": errors,
    }
    cache.set(cache_key, result, 300)
    return result


def invalidate_repo_stats(repository):
    """Purge per-repo stats cache entry."""
    cache.delete(f"registry_repo_stats_{repository}")
