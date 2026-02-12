# ui/views.py

import logging
from datetime import datetime

import requests
import urllib3
from django.conf import settings
from django.contrib import messages
from django.http import JsonResponse, HttpResponseForbidden
from django.shortcuts import render, redirect
from django.views.decorators.http import require_GET, require_POST

from .formating import format_time_difference, format_size
from .registry_client import (
    get_registry_data,
    get_all_tag_counts,
    get_manifest_digest,
    delete_manifest,
    invalidate_cache,
)

logger = logging.getLogger(__name__)

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def repository_list(request):
    data, error_message = None, None
    try:
        data = get_registry_data("_catalog")
    except requests.exceptions.RequestException as e:
        error_message = str(e)

    repositories = data.get("repositories", []) if data else []

    # Structure namespaces avec hiérarchie récursive
    namespaces = {}

    for repo in repositories:
        # Ignorer les repositories vides
        if not repo:
            continue

        parts = repo.split("/")

        # Déterminer le namespace principal
        namespace = parts[0] if parts else "<default>"

        # Ignorer les namespaces vides
        if not namespace:
            continue

        if namespace not in namespaces:
            namespaces[namespace] = {
                "repos": [],
                "sub_namespaces": {},
                "total_count": 0,
            }

        # Gérer les repositories avec ou sans sous-namespaces
        current_level = namespaces[namespace]

        if len(parts) == 1:
            # Repo sans namespace
            repo_info = {"full_name": repo, "name": repo}
            current_level["repos"].append(repo_info)
        elif len(parts) == 2:
            # Repo avec un seul namespace
            repo_info = {"full_name": repo, "name": parts[1]}
            current_level["repos"].append(repo_info)
        else:
            # Repo avec des sous-namespaces multiples
            # Naviguer et créer la structure récursive de sous-namespaces
            valid_path = True  # Pour vérifier si tous les segments sont valides
            for i in range(1, len(parts) - 1):
                sub_namespace = parts[i]

                # Ignorer les sous-namespaces vides
                if not sub_namespace:
                    valid_path = False
                    break

                if sub_namespace not in current_level["sub_namespaces"]:
                    current_level["sub_namespaces"][sub_namespace] = {
                        "repos": [],
                        "sub_namespaces": {},
                        "total_count": 0,
                    }
                current_level = current_level["sub_namespaces"][sub_namespace]
                # Incrémenter le compteur à chaque niveau
                current_level["total_count"] += 1

            # Ajouter le repo au niveau actuel seulement si le chemin est valide
            if valid_path and parts[-1]:  # Vérifier que le nom du repo n'est pas vide
                repo_info = {"full_name": repo, "name": parts[-1]}
                current_level["repos"].append(repo_info)

                # Incrémenter le compteur total du namespace principal
                namespaces[namespace]["total_count"] += 1

    # Trier les namespaces et sous-namespaces
    sorted_keys = sorted(namespaces.keys())
    ordered_namespaces = {k: namespaces[k] for k in sorted_keys if k != "<default>"}

    # Fonction récursive pour trier les sous-namespaces
    def sort_sub_namespaces(ns_dict):
        if not ns_dict["sub_namespaces"]:
            return ns_dict

        sorted_subs = {}
        for k in sorted(ns_dict["sub_namespaces"].keys()):
            sorted_subs[k] = sort_sub_namespaces(ns_dict["sub_namespaces"][k])

        ns_dict["sub_namespaces"] = sorted_subs
        return ns_dict

    # Appliquer le tri récursif à tous les namespaces
    for k in ordered_namespaces:
        ordered_namespaces[k] = sort_sub_namespaces(ordered_namespaces[k])

    # Ajouter default à la fin
    if "<default>" in namespaces:
        ordered_namespaces["<default>"] = namespaces["<default>"]

    context = {"namespaces": ordered_namespaces, "error_message": error_message}
    return render(request, "ui/repository_list.html", context)


def repository_detail(request, repository):
    # Get list of tags (names only — details are loaded async via get_tag_details)
    tags_data, error_message = None, None
    try:
        tags_data = get_registry_data(f"{repository}/tags/list")
    except requests.exceptions.RequestException as e:
        error_message = str(e)

    tags = sorted(tags_data.get("tags", [])) if tags_data and tags_data.get("tags") else []

    # Add registry URL to context
    registry_url = settings.REGISTRY_URL.replace("http://", "").replace("https://", "")
    if registry_url.endswith("/"):
        registry_url = registry_url[:-1]

    registry_repo = getattr(settings, "REGISTRY_REPO", None)
    registry_type = getattr(settings, "REGISTRY_TYPE", "standard")

    if registry_repo and registry_type.lower() != "artifactory":
        repo_path = f"{registry_repo}/{repository}"
    elif registry_type.lower() == "artifactory" and registry_repo:
        repo_path = f"{registry_repo}/{repository}"
    else:
        repo_path = repository

    pull_command_base = f"docker pull {registry_url}/{repo_path}"

    context = {
        "repository": repository,
        "tags": tags,
        "error_message": error_message,
        "registry_url": registry_url,
        "pull_command_base": pull_command_base,
    }
    return render(request, "ui/repository_detail.html", context)


def _get_tag_detail(repository, tag):
    """Fetch manifest/config details for a single tag and return a detail dict."""
    manifest_data = get_registry_data(f"{repository}/manifests/{tag}")
    created_date = None
    size = 0
    architectures = []

    # Check if the manifest is multi-arch
    if manifest_data and manifest_data.get("manifests"):
        for entry in manifest_data.get("manifests", []):
            platform = entry.get("platform", {})
            arch = platform.get("architecture", "unknown")
            if (
                arch != "unknown"
                and not entry.get("annotations", {}).get(
                    "vnd.docker.reference.type"
                )
                == "attestation-manifest"
            ):
                architectures.append(arch)

                # Récupérer les détails du premier manifeste valide trouvé
                if created_date is None:
                    digest = entry.get("digest", "")
                    arch_manifest = get_registry_data(
                        f"{repository}/manifests/{digest}"
                    )
                    if (
                        arch_manifest
                        and "config" in arch_manifest
                        and "digest" in arch_manifest.get("config", {})
                    ):
                        config_digest = arch_manifest["config"]["digest"]
                        config_data = get_registry_data(
                            f"{repository}/blobs/{config_digest}"
                        )
                        if config_data and "created" in config_data:
                            created_date = config_data["created"]

                        if "layers" in arch_manifest:
                            for layer in arch_manifest.get("layers", []):
                                size += layer.get("size", 0)
    else:
        # Single architecture manifest
        if (
            manifest_data
            and "config" in manifest_data
            and "digest" in manifest_data.get("config", {})
        ):
            config_data = get_registry_data(
                f"{repository}/blobs/{manifest_data['config']['digest']}"
            )
            if "created" in config_data:
                created_date = config_data["created"]
            if "architecture" in config_data:
                architectures.append(config_data["architecture"])

        if manifest_data and "layers" in manifest_data:
            for layer in manifest_data["layers"]:
                size += layer.get("size", 0)

    # Format age
    age = "Unknown"
    if created_date:
        try:
            if "." in created_date:
                parts = created_date.split(".")
                microseconds = parts[1].replace("Z", "")[:6]
                created_date = f"{parts[0]}.{microseconds}Z"

            created_datetime = datetime.fromisoformat(
                created_date.replace("Z", "+00:00")
            )
            age = format_time_difference(created_datetime)
        except Exception as e:
            print(f"Date parsing error: {e}, value: '{created_date}'")

    return {
        "created": created_date,
        "age": age,
        "size": format_size(size) if size else "Unknown",
        "size_bytes": size,
        "architectures": architectures or ["Unknown"],
    }


@require_GET
def get_tag_details(request, repository):
    """Return details (date, size, architectures) for all tags of a repository."""
    tags_data = get_registry_data(f"{repository}/tags/list")
    tags = tags_data.get("tags", []) if tags_data else []

    result = {}
    for tag in tags:
        try:
            result[tag] = _get_tag_detail(repository, tag)
        except Exception as e:
            print(f"Error retrieving manifest for {tag}: {e}")
            result[tag] = {
                "created": None,
                "age": "Error",
                "size": "Error",
                "size_bytes": 0,
                "architectures": ["Error"],
            }

    return JsonResponse(result)


@require_GET
def get_tag_counts(request):
    """Return tag counts for all repositories"""
    force = request.GET.get("force", "").lower() == "true"
    tag_counts = get_all_tag_counts(force_refresh=force)
    return JsonResponse(tag_counts)


def admin_login(request):
    """Admin login view."""
    if not settings.ADMIN_PASSWORD:
        return redirect("ui:repository_list")

    if request.method == "POST":
        password = request.POST.get("password", "")
        if password == settings.ADMIN_PASSWORD:
            request.session["is_admin"] = True
            messages.success(request, "Admin mode activated.")
            return redirect("ui:repository_list")
        else:
            messages.error(request, "Invalid password.")

    return render(request, "ui/admin_login.html")


@require_POST
def admin_logout(request):
    """Admin logout view."""
    request.session.pop("is_admin", None)
    messages.info(request, "Admin mode deactivated.")
    return redirect("ui:repository_list")


@require_POST
def delete_tag(request, repository):
    """Delete a single tag from a repository."""
    if not request.session.get("is_admin", False):
        return HttpResponseForbidden("Admin access required.")

    tag = request.POST.get("tag", "")
    if not tag:
        return JsonResponse({"success": False, "error": "No tag specified."}, status=400)

    try:
        digest = get_manifest_digest(repository, tag)
        if not digest:
            return JsonResponse({"success": False, "error": "Could not resolve digest."}, status=404)
        delete_manifest(repository, digest)
        invalidate_cache(repository)
        return JsonResponse({"success": True, "tag": tag})
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 405:
            return JsonResponse(
                {"success": False, "error": "Delete is not enabled on the registry. Set REGISTRY_STORAGE_DELETE_ENABLED=true."},
                status=405,
            )
        logger.error(f"Error deleting tag {tag} from {repository}: {e}")
        return JsonResponse({"success": False, "error": str(e)}, status=500)
    except Exception as e:
        logger.error(f"Error deleting tag {tag} from {repository}: {e}")
        return JsonResponse({"success": False, "error": str(e)}, status=500)


@require_POST
def delete_repository(request, repository):
    """Delete all tags from a repository."""
    if not request.session.get("is_admin", False):
        return HttpResponseForbidden("Admin access required.")

    try:
        tags_data = get_registry_data(f"{repository}/tags/list")
        tags = tags_data.get("tags", []) if tags_data else []
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=500)

    deleted = []
    errors = []
    for tag in tags:
        try:
            digest = get_manifest_digest(repository, tag)
            if digest:
                delete_manifest(repository, digest)
                deleted.append(tag)
            else:
                errors.append({"tag": tag, "error": "Could not resolve digest."})
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 405:
                errors.append({"tag": tag, "error": "Delete not enabled on registry."})
            else:
                errors.append({"tag": tag, "error": str(e)})
        except Exception as e:
            errors.append({"tag": tag, "error": str(e)})

    invalidate_cache(repository)

    status_code = 207 if errors and deleted else (200 if not errors else 500)
    return JsonResponse({"success": len(errors) == 0, "deleted": deleted, "errors": errors}, status=status_code)
