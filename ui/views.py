# ui/views.py
import json
from datetime import datetime, timezone

import requests
import urllib3
from django.conf import settings
from django.shortcuts import render

from .registry_client import get_registry_data

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def index(request):
    return render(request, "ui/index.html")


def repository_list(request):
    data, error_message = None, None
    try:
        data = get_registry_data("_catalog")
    except requests.exceptions.RequestException as e:
        error_message = str(e)

    repositories = data.get("repositories", []) if data else []
    namespaces = {}

    # Process in batches to avoid too many concurrent requests
    batch_size = 10
    for i in range(0, len(repositories), batch_size):
        batch = repositories[i : i + batch_size]
        for repo in batch:
            # Get tag count for repository
            tag_data = get_registry_data(f"{repo}/tags/list")
            tag_count = 0
            if tag_data and "tags" in tag_data and tag_data["tags"]:
                tag_count = len(tag_data["tags"])

            parts = repo.split("/")
            if len(parts) > 1:
                namespace = parts[0]
                repo_name = "/".join(parts[1:])
                if namespace not in namespaces:
                    namespaces[namespace] = []
                namespaces[namespace].append(
                    {"full_name": repo, "name": repo_name, "tag_count": tag_count}
                )
            else:
                if "default" not in namespaces:
                    namespaces["default"] = []
                namespaces["default"].append(
                    {"full_name": repo, "name": repo, "tag_count": tag_count}
                )

    # Rename 'default' and prepare sorted namespaces
    if "default" in namespaces:
        namespaces["<default>"] = namespaces.pop("default")

    # Create sorted dict with default at the end
    sorted_namespaces = {}
    for key in sorted(namespaces.keys()):
        if key != "<default>":
            sorted_namespaces[key] = namespaces[key]

    # Add default at the end
    if "<default>" in namespaces:
        sorted_namespaces["<default>"] = namespaces["<default>"]

    context = {"namespaces": sorted_namespaces, "error_message": error_message}
    return render(request, "ui/repository_list.html", context)


def repository_detail(request, repository):
    # Get list of tags
    tags_data, error_message = None, None
    try:
        tags_data = get_registry_data(f"{repository}/tags/list")
    except requests.exceptions.RequestException as e:
        error_message = str(e)

    tags_with_details = []
    if tags_data and "tags" in tags_data and tags_data["tags"]:
        for tag in tags_data["tags"]:
            # Get manifest for tag
            manifest_url = f"/v2/{repository}/manifests/{tag}"

            # Try with v2 manifest first
            headers = {"Accept": "application/vnd.docker.distribution.manifest.v2+json"}
            url = f"{settings.REGISTRY_URL}{manifest_url}"

            try:
                response = requests.get(
                    url, headers=headers, verify=settings.REGISTRY_SSL_VERIFY, timeout=5
                )
                manifest_data = response.json() if response.status_code == 200 else None

                # If v2 manifest fails, try with v1 manifest
                if not manifest_data or response.status_code != 200:
                    headers = {
                        "Accept": "application/vnd.docker.distribution.manifest.v1+json"
                    }
                    response = requests.get(
                        url,
                        headers=headers,
                        verify=settings.REGISTRY_SSL_VERIFY,
                        timeout=5,
                    )
                    manifest_data = (
                        response.json() if response.status_code == 200 else None
                    )

                # Initialize values
                created_date = None
                size = 0
                arch = "Unknown"

                # Extract creation date and arch from image config
                if (
                    manifest_data
                    and "config" in manifest_data
                    and "digest" in manifest_data["config"]
                ):
                    config_url = (
                        f"/v2/{repository}/blobs/{manifest_data['config']['digest']}"
                    )
                    config_response = requests.get(
                        f"{settings.REGISTRY_URL}{config_url}",
                        headers=headers,
                        verify=settings.REGISTRY_SSL_VERIFY,
                        timeout=5,
                    )

                    if config_response.status_code == 200:
                        config_data = config_response.json()
                        if "created" in config_data:
                            created_date = config_data["created"]
                        if "architecture" in config_data:
                            arch = config_data["architecture"]

                # Try to get from v1Compatibility as fallback
                if not created_date and manifest_data and "history" in manifest_data:
                    for history_item in manifest_data["history"]:
                        if "v1Compatibility" in history_item:
                            try:
                                v1_data = json.loads(history_item["v1Compatibility"])
                                if not created_date and "created" in v1_data:
                                    created_date = v1_data["created"]
                                if arch == "Unknown" and "architecture" in v1_data:
                                    arch = v1_data["architecture"]
                                # Break once we have both values
                                if created_date and arch != "Unknown":
                                    break
                            except:
                                continue

                # Calculate size
                if manifest_data and "layers" in manifest_data:
                    for layer in manifest_data["layers"]:
                        if "size" in layer:
                            size += layer["size"]

                # Format age
                age = "Unknown"
                if created_date:
                    try:
                        created_datetime = datetime.fromisoformat(
                            created_date.replace("Z", "+00:00")
                        )
                        age = format_time_difference(created_datetime)
                    except:
                        # Handle invalid date format
                        pass

                size_str = format_size(size) if size else "Unknown"

                tags_with_details.append(
                    {
                        "name": tag,
                        "created": created_date,
                        "age": age,
                        "arch": arch,
                        "size": size_str,
                        "size_bytes": size,
                    }
                )

            except Exception as e:
                print(f"Error retrieving manifest for {tag}: {e}")
                # Add tag with minimal info on error
                tags_with_details.append(
                    {
                        "name": tag,
                        "created": None,
                        "age": "Error",
                        "arch": "Error",
                        "size": "Error",
                        "size_bytes": 0,
                    }
                )

        # Sort by creation date
        def safe_sort_key(sorting_tag):
            created = sorting_tag.get("created")
            return created if created is not None else ""

        tags_with_details.sort(key=safe_sort_key, reverse=True)

    # Add registry URL to context
    registry_url = settings.REGISTRY_URL.replace("http://", "").replace("https://", "")
    if registry_url.endswith("/"):
        registry_url = registry_url[:-1]

    context = {
        "repository": repository,
        "tags": tags_with_details,
        "error_message": error_message,
        "registry_url": registry_url,
    }
    return render(request, "ui/repository_detail.html", context)


def format_time_difference(datetime_obj):
    """Format time difference between datetime_obj and now in a human-readable format"""
    now = datetime.now(timezone.utc)
    diff = now - datetime_obj

    if diff.days > 365:
        years = diff.days // 365
        return f"{years} year{'s' if years > 1 else ''} ago"
    elif diff.days > 30:
        months = diff.days // 30
        return f"{months} month{'s' if months > 1 else ''} ago"
    elif diff.days > 0:
        return f"{diff.days} day{'s' if diff.days > 1 else ''} ago"
    elif diff.seconds > 3600:
        hours = diff.seconds // 3600
        return f"{hours} hour{'s' if hours > 1 else ''} ago"
    elif diff.seconds > 60:
        minutes = diff.seconds // 60
        return f"{minutes} minute{'s' if minutes > 1 else ''} ago"
    else:
        return "Just now"


def format_size(size_bytes):
    """Format byte size to human-readable format"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"
