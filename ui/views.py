# ui/views.py

import hmac
import logging
from datetime import datetime

import requests
from django.conf import settings
from django.contrib import messages
from django.core.cache import cache
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render
from django.utils.text import slugify
from django.views.decorators.http import require_GET, require_POST

from .formating import format_size, format_time_difference
from .registry_client import (
    delete_manifest,
    get_all_tag_counts,
    get_manifest_digest,
    get_registry_data,
    get_repo_stats,
    get_tag_counts_for,
    invalidate_cache,
    map_concurrently,
)

logger = logging.getLogger(__name__)


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
        if not repo:
            continue

        parts = repo.split("/")
        namespace = parts[0] if parts else "<default>"

        if not namespace:
            continue

        if namespace not in namespaces:
            namespaces[namespace] = {
                "repos": [],
                "sub_namespaces": {},
            }

        current_level = namespaces[namespace]

        if len(parts) <= 2:
            repo_info = {"full_name": repo, "name": parts[-1]}
            current_level["repos"].append(repo_info)
        else:
            valid_path = True
            for i in range(1, len(parts) - 1):
                sub_namespace = parts[i]

                if not sub_namespace:
                    valid_path = False
                    break

                if sub_namespace not in current_level["sub_namespaces"]:
                    current_level["sub_namespaces"][sub_namespace] = {
                        "repos": [],
                        "sub_namespaces": {},
                    }
                current_level = current_level["sub_namespaces"][sub_namespace]

            if valid_path and parts[-1]:
                repo_info = {"full_name": repo, "name": parts[-1]}
                current_level["repos"].append(repo_info)

    def compute_counts_and_sort(ns_dict, id_prefix):
        """Trier les sous-namespaces, calculer total_count et collapse_id récursivement."""
        ns_dict["collapse_id"] = id_prefix
        sorted_subs = {}
        for k in sorted(ns_dict["sub_namespaces"].keys()):
            sub_prefix = f"{id_prefix}-{slugify(k)}"
            sorted_subs[k] = compute_counts_and_sort(ns_dict["sub_namespaces"][k], sub_prefix)
        ns_dict["sub_namespaces"] = sorted_subs
        ns_dict["total_count"] = len(ns_dict["repos"]) + len(ns_dict["sub_namespaces"])
        return ns_dict

    sorted_keys = sorted(namespaces.keys())
    ordered_namespaces = {}
    for k in sorted_keys:
        if k != "<default>":
            ordered_namespaces[k] = compute_counts_and_sort(namespaces[k], slugify(k))

    if "<default>" in namespaces:
        ordered_namespaces["<default>"] = compute_counts_and_sort(
            namespaces["<default>"], slugify("<default>")
        )

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

    # Both registry types prefix the image with the namespace, so the three
    # branches this used to have all produced the same two outcomes.
    registry_repo = getattr(settings, "REGISTRY_REPO", "")
    repo_path = f"{registry_repo}/{repository}" if registry_repo else repository

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
            # A config blob the registry no longer has returns None, and `"created"
            # in None` is a TypeError -- caught upstream, which turned a missing
            # blob into an unexplained "Error" on the whole row.
            if config_data:
                created_date = config_data.get("created")
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
            logger.warning(f"Date parsing error: {e}, value: '{created_date}'")

    return {
        "created": created_date,
        "age": age,
        "size": format_size(size) if size else "Unknown",
        "size_bytes": size,
        "architectures": architectures or ["Unknown"],
    }


_TAG_DETAIL_ERROR = {
    "created": None,
    "age": "Error",
    "size": "Error",
    "size_bytes": 0,
    "architectures": ["Error"],
}


def get_tag_details_map(repository, tags):
    """Details for every tag of a repository, keyed by tag.

    Fetched in parallel: each tag costs a manifest call plus a config blob call --
    two or three round trips -- and a repository with thirty tags used to spend all
    of them one after the other while the table sat on its loading spinners.

    One unreadable tag must not cost the whole table, so a failure is reported in
    that tag's own entry.
    """

    def detail(tag):
        try:
            return _get_tag_detail(repository, tag)
        except Exception as e:
            logger.error(f"Error retrieving manifest for {repository}:{tag}: {e}")
            return dict(_TAG_DETAIL_ERROR)

    tags = list(tags)
    # strict: map_concurrently returns one result per input, and a silent mismatch
    # here would shift every row's details onto the wrong tag.
    return dict(zip(tags, map_concurrently(detail, tags), strict=True))


@require_GET
def get_tag_details(request, repository):
    """Return details (date, size, architectures) for all tags of a repository."""
    try:
        tags_data = get_registry_data(f"{repository}/tags/list")
    except requests.exceptions.RequestException as e:
        # Used to escape as a bare 500 with an empty body, which the page reported
        # as "Error" on every row without saying why.
        logger.error(f"Cannot list tags of {repository}: {e}")
        return JsonResponse({"error": str(e)}, status=502)

    tags = tags_data.get("tags", []) if tags_data else []

    return JsonResponse(get_tag_details_map(repository, tags))


@require_GET
def get_tag_counts(request):
    """Return tag counts for repositories. If ?repos=a,b,c is provided, count only those."""
    repos_param = request.GET.get("repos", "").strip()
    try:
        if repos_param:
            repos = [r.strip() for r in repos_param.split(",") if r.strip()]
            return JsonResponse(get_tag_counts_for(repos))

        force = request.GET.get("force", "").lower() == "true"
        return JsonResponse(get_all_tag_counts(force_refresh=force))
    except requests.exceptions.RequestException as e:
        logger.error(f"Cannot read tag counts: {e}")
        return JsonResponse({"error": str(e)}, status=502)


def _client_address(request):
    """Best guess at the caller's address, for throttling purposes.

    X-Forwarded-For is only read when the deployment says a proxy is in front:
    otherwise any client could send that header and get a fresh attempt budget for
    every value it invents.
    """
    if settings.TRUST_PROXY:
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR") or "unknown"


def _password_matches(candidate):
    """Compare against ADMIN_PASSWORD without leaking its length through timing."""
    return hmac.compare_digest(
        candidate.encode("utf-8", "surrogatepass"),
        settings.ADMIN_PASSWORD.encode("utf-8", "surrogatepass"),
    )


def admin_login(request):
    """Admin login view.

    A single shared password, deliberately -- but a single shared password with no
    limit on attempts is a password that gets guessed offline-fast, so failures are
    counted per client address in the (process-shared) cache.
    """
    if not settings.ADMIN_PASSWORD:
        return redirect("ui:repository_list")

    address = _client_address(request)
    throttle_key = f"admin_login_failures_{address}"
    failures = cache.get(throttle_key, 0)
    locked_out = failures >= settings.ADMIN_LOGIN_MAX_ATTEMPTS

    if locked_out:
        messages.error(
            request,
            f"Too many failed attempts. Try again in "
            f"{settings.ADMIN_LOGIN_LOCKOUT_SECONDS // 60} minutes.",
        )
    elif request.method == "POST":
        if _password_matches(request.POST.get("password", "")):
            request.session["is_admin"] = True
            cache.delete(throttle_key)
            logger.info(f"Admin mode activated from {address}")
            messages.success(request, "Admin mode activated.")
            return redirect("ui:repository_list")
        else:
            # Refreshing the TTL on every failure means a persistent attacker stays
            # locked out instead of getting a new budget once the window rolls.
            cache.set(throttle_key, failures + 1, settings.ADMIN_LOGIN_LOCKOUT_SECONDS)
            logger.warning(f"Failed admin login from {address} (attempt {failures + 1})")
            messages.error(request, "Invalid password.")

    return render(request, "ui/admin_login.html")


def registry_stats(request):
    """Admin-only registry statistics page (shell; data loaded via JS)."""
    if not request.session.get("is_admin", False):
        return HttpResponseForbidden("Admin access required.")

    context = {
        "registry_url": settings.REGISTRY_URL,
        "registry_type": settings.REGISTRY_TYPE,
        "registry_repo": settings.REGISTRY_REPO,
    }
    return render(request, "ui/admin_stats.html", context)


@require_GET
def registry_stats_summary(request):
    """Return quick stats: repo list, tag counts per repo, empty repos."""
    if not request.session.get("is_admin", False):
        return HttpResponseForbidden("Admin access required.")

    force = request.GET.get("refresh", "").lower() == "true"
    try:
        tag_counts = get_all_tag_counts(force_refresh=force)
    except requests.exceptions.RequestException as e:
        return JsonResponse({"error": str(e)}, status=502)

    repositories = sorted(tag_counts.keys())
    # `not tag_counts.get(r)` also caught None, so a repository the registry failed
    # to answer for was reported as empty -- and empty repositories are what this
    # page recommends garbage-collecting.
    empty = [r for r in repositories if tag_counts.get(r) == 0]
    total_tags = sum(count for count in tag_counts.values() if count)
    unreadable = sorted(r for r, count in tag_counts.items() if count is None)

    return JsonResponse(
        {
            "repositories": repositories,
            "tag_counts": tag_counts,
            "empty_repositories": empty,
            "unreadable_repositories": unreadable,
            "total_repositories": len(repositories),
            "total_tags": total_tags,
        }
    )


@require_GET
def registry_stats_repo(request, repository):
    """Return per-repo stats (tags, deduped size, blob count)."""
    if not request.session.get("is_admin", False):
        return HttpResponseForbidden("Admin access required.")

    force = request.GET.get("refresh", "").lower() == "true"
    try:
        stats = get_repo_stats(repository, force_refresh=force)
    except requests.exceptions.RequestException as e:
        return JsonResponse({"error": str(e), "repository": repository}, status=502)

    stats["size_human"] = format_size(stats["size"]) if stats["size"] else "0 B"
    return JsonResponse(stats)


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
        invalidate_cache(repository, tags=[tag])
        return JsonResponse({"success": True, "tag": tag})
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 405:
            return JsonResponse(
                {
                    "success": False,
                    "error": (
                        "Delete is not enabled on the registry. "
                        "Set REGISTRY_STORAGE_DELETE_ENABLED=true."
                    ),
                },
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

    invalidate_cache(repository, tags=tags)

    status_code = 207 if errors and deleted else (200 if not errors else 500)
    return JsonResponse(
        {"success": len(errors) == 0, "deleted": deleted, "errors": errors},
        status=status_code,
    )
