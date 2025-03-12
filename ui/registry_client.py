# registry_client.py
import requests
from django.conf import settings
from django.core.cache import cache


def get_registry_session():
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
        "Accept": "application/vnd.docker.distribution.manifest.v2+json, application/json"
    }

    print(f"DEBUG: Requesting {url}")

    response = session.get(url, headers=headers)
    response.raise_for_status()

    result = response.json()
    cache.set(cache_key, result, 300)
    return result
