# registry_client.py
import logging

import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)


def get_registry_session():
    """
    Create and configure a session for interacting with the Docker Registry API.
    """
    session = requests.Session()
    session.verify = settings.REGISTRY_SSL_VERIFY

    if settings.REGISTRY_USERNAME and settings.REGISTRY_PASSWORD:
        session.auth = (settings.REGISTRY_USERNAME, settings.REGISTRY_PASSWORD)

    return session


def get_registry_data(endpoint):
    """Get data from Docker Registry API"""
    cache_key = f"registry_{endpoint}"
    cached_data = cache.get(cache_key)

    if cached_data:
        return cached_data

    session = get_registry_session()

    # Determine if we're using Artifactory based on URL
    is_artifactory = settings.REGISTRY_TYPE.lower() == "artifactory"

    # Construct URL based on registry type
    if is_artifactory:
        # Artifactory format
        if endpoint == "_catalog":
            url = f"{settings.REGISTRY_URL}/artifactory/api/docker/{settings.REGISTRY_REPO}/v2/_catalog"
        elif "/tags/list" in endpoint:
            repository = endpoint.split("/tags/list")[0]
            url = f"{settings.REGISTRY_URL}/artifactory/api/docker/{settings.REGISTRY_REPO}/v2/{repository}/tags/list"
        else:
            url = f"{settings.REGISTRY_URL}/artifactory/api/docker/{settings.REGISTRY_REPO}/v2/{endpoint}"
    else:
        # Standard Docker registry format
        if settings.REGISTRY_REPO:
            url = f"{settings.REGISTRY_URL}/v2/{settings.REGISTRY_REPO}/{endpoint}"
        else:
            url = f"{settings.REGISTRY_URL}/v2/{endpoint}"

    # Add Accept headers for both manifest types
    headers = {
        "Accept": (
            "application/vnd.docker.distribution.manifest.list.v2+json, "
            "application/vnd.docker.distribution.manifest.v2+json, "
            "application/vnd.docker.distribution.manifest.v1+json, "
            "application/vnd.oci.image.manifest.v1+json, "
            "application/vnd.oci.image.index.v1+json, "
            "application/json"
        )
    }

    # logger.debug(f"Requesting {url}")

    response = session.get(url, headers=headers)
    if response.status_code == 404:
        logger.warning(f"Resource not found: {url}")
        return None

    response.raise_for_status()

    result = response.json()
    cache.set(cache_key, result, 300)
    return result


# ui/registry_client.py - Ajoutez cette fonction
def get_tag_count(repository):
    """Get tag count for a single repository"""
    try:
        tags_data = get_registry_data(f"{repository}/tags/list")
        return len(tags_data.get("tags", [])) if tags_data else 0
    except Exception as e:
        logger.error(f"Error getting tags for {repository}: {str(e)}")
        return 0


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
