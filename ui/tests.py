import threading
import time
from unittest import mock

import requests
from django.core.cache import cache
from django.test import SimpleTestCase, override_settings
from django.urls import Resolver404, resolve, reverse

from . import registry_client, views
from .registry_client import check_endpoint


class RepositoryRoutingTests(SimpleTestCase):
    """The routing layer is what keeps `..` out of registry URLs."""

    def test_nested_repository_name_resolves(self):
        match = resolve("/ui/repositories/team/project/image/")
        self.assertEqual(match.view_name, "ui:repository_detail")
        self.assertEqual(match.kwargs["repository"], "team/project/image")

    def test_specific_routes_win_over_the_greedy_detail_route(self):
        for suffix, view_name in (
            ("tag-details/", "ui:tag_details"),
            ("delete-tag/", "ui:delete_tag"),
            ("delete/", "ui:delete_repository"),
        ):
            with self.subTest(suffix=suffix):
                match = resolve(f"/ui/repositories/team/image/{suffix}")
                self.assertEqual(match.view_name, view_name)
                self.assertEqual(match.kwargs["repository"], "team/image")

    def test_traversal_in_repository_name_is_not_routed(self):
        # Before the RepositoryConverter, this resolved to get_tag_details with
        # repository="../../v2/_catalog", and requests then normalised the `..`
        # away -- sending a credentialed call outside the configured namespace.
        for path in (
            "/ui/repositories/../../v2/_catalog/tag-details/",
            "/ui/repositories/..%2F..%2Fv2/tag-details/",
            "/ui/repositories/team/../../../etc/",
            "/ui/repositories/./tag-details/",
            "/ui/stats/repo/../../v2/",
        ):
            with self.subTest(path=path):
                with self.assertRaises(Resolver404):
                    resolve(path)

    def test_overlong_repository_name_is_not_routed(self):
        with self.assertRaises(Resolver404):
            resolve(f"/ui/repositories/{'a' * 256}/")

    def test_reverse_keeps_slashes_unescaped(self):
        url = reverse("ui:repository_detail", kwargs={"repository": "team/image"})
        self.assertEqual(url, "/ui/repositories/team/image/")


class CheckEndpointTests(SimpleTestCase):
    """Second lock, on the sink itself."""

    def test_plain_endpoints_pass(self):
        for endpoint in (
            "_catalog",
            "team/image/tags/list",
            "team/image/manifests/sha256:" + "a" * 64,
            "team/image/blobs/sha256:" + "b" * 64,
        ):
            with self.subTest(endpoint=endpoint):
                check_endpoint(endpoint)

    def test_traversal_and_empty_components_are_refused(self):
        for endpoint in (
            "../../v2/_catalog",
            "team/../../../secret/tags/list",
            "team/./image/tags/list",
            "/tags/list",
            "team//image/tags/list",
        ):
            with self.subTest(endpoint=endpoint):
                with self.assertRaises(ValueError):
                    check_endpoint(endpoint)


@override_settings(
    ADMIN_PASSWORD="s3cret",
    ADMIN_LOGIN_MAX_ATTEMPTS=3,
    ADMIN_LOGIN_LOCKOUT_SECONDS=300,
    TRUST_PROXY=False,
)
class AdminLoginTests(SimpleTestCase):
    """Admin mode is a shared password, so the throttle is the only brake."""

    url = "/ui/admin/login/"

    def setUp(self):
        # The throttle counter lives in the cache, which is shared between tests.
        cache.clear()
        self.addCleanup(cache.clear)

    def test_good_password_activates_admin_mode(self):
        response = self.client.post(self.url, {"password": "s3cret"})
        self.assertRedirects(response, "/ui/repositories/", fetch_redirect_response=False)
        self.assertTrue(self.client.session["is_admin"])

    def test_bad_password_does_not(self):
        response = self.client.post(self.url, {"password": "nope"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.client.session.get("is_admin", False))

    def test_attempts_are_capped(self):
        for _ in range(3):
            self.client.post(self.url, {"password": "nope"})
        # Locked out: even the right password stops being accepted.
        response = self.client.post(self.url, {"password": "s3cret"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.client.session.get("is_admin", False))

    def test_success_clears_the_counter(self):
        self.client.post(self.url, {"password": "nope"})
        self.client.post(self.url, {"password": "s3cret"})
        self.assertIsNone(cache.get("admin_login_failures_127.0.0.1"))

    def test_forwarded_for_is_ignored_without_a_trusted_proxy(self):
        # Otherwise an attacker invents a new X-Forwarded-For per request and the
        # per-address budget never runs out.
        for i in range(3):
            self.client.post(
                self.url, {"password": "nope"}, HTTP_X_FORWARDED_FOR=f"10.0.0.{i}"
            )
        self.assertEqual(cache.get("admin_login_failures_127.0.0.1"), 3)

    @override_settings(ADMIN_PASSWORD="")
    def test_disabled_admin_mode_redirects_away(self):
        response = self.client.get(self.url)
        self.assertRedirects(response, "/ui/repositories/", fetch_redirect_response=False)


class AdminGatingTests(SimpleTestCase):
    """Every admin endpoint re-checks the session flag."""

    def test_admin_endpoints_refuse_anonymous_callers(self):
        for method, url in (
            ("get", "/ui/stats/"),
            ("get", "/ui/stats/summary/"),
            ("get", "/ui/stats/repo/team/image/"),
            ("post", "/ui/repositories/team/image/delete-tag/"),
            ("post", "/ui/repositories/team/image/delete/"),
        ):
            with self.subTest(url=url):
                response = getattr(self.client, method)(url)
                self.assertEqual(response.status_code, 403)


class FakeResponse:
    """Enough of a requests.Response for the registry client."""

    def __init__(self, payload=None, status_code=200, headers=None):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"{self.status_code}", response=self)


class RecordingSession:
    """A registry that answers from a dict and counts what it was asked."""

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        for suffix, payload in self.responses.items():
            if url.endswith(suffix):
                if payload is None:
                    return FakeResponse(status_code=404)
                return FakeResponse(payload)
        return FakeResponse(status_code=404)


class RegistryCacheTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def _patched(self, responses):
        session = RecordingSession(responses)
        return session, mock.patch.object(
            registry_client, "get_registry_session", return_value=session
        )

    def test_response_is_cached(self):
        session, patch = self._patched({"/v2/_catalog": {"repositories": ["a"]}})
        with patch:
            self.assertEqual(registry_client.get_registry_data("_catalog"), {"repositories": ["a"]})
            self.assertEqual(registry_client.get_registry_data("_catalog"), {"repositories": ["a"]})
        self.assertEqual(len(session.calls), 1)

    def test_empty_result_is_cached_too(self):
        # `if cached_data:` treated an empty payload as a miss, so a repository
        # with no tags was refetched on every single request.
        session, patch = self._patched({"/tags/list": {}})
        with patch:
            for _ in range(3):
                registry_client.get_registry_data("team/image/tags/list")
        self.assertEqual(len(session.calls), 1)

    def test_missing_resource_is_cached_as_none(self):
        session, patch = self._patched({"/tags/list": None})
        with patch:
            self.assertIsNone(registry_client.get_registry_data("team/gone/tags/list"))
            self.assertIsNone(registry_client.get_registry_data("team/gone/tags/list"))
        self.assertEqual(len(session.calls), 1)

    def test_invalidate_cache_drops_the_deleted_tag_manifest(self):
        cache.set(registry_client.cache_key_for("team/image/manifests/v1"), {"layers": []})
        cache.set(registry_client.cache_key_for("team/image/tags/list"), {"tags": ["v1"]})
        registry_client.invalidate_cache("team/image", tags=["v1"])
        # Both keys have to go: the manifest one used to survive, so a deleted tag
        # kept reporting its size and date until its TTL ran out.
        self.assertIsNone(cache.get(registry_client.cache_key_for("team/image/manifests/v1")))
        self.assertIsNone(cache.get(registry_client.cache_key_for("team/image/tags/list")))


@override_settings(REGISTRY_TYPE="classic", REGISTRY_REPO="", REGISTRY_URL="http://reg:5000")
class RegistryUrlTests(SimpleTestCase):
    def test_classic(self):
        self.assertEqual(
            registry_client._build_registry_url("_catalog"), "http://reg:5000/v2/_catalog"
        )

    @override_settings(REGISTRY_REPO="ns")
    def test_classic_with_namespace(self):
        self.assertEqual(
            registry_client._build_registry_url("a/tags/list"), "http://reg:5000/v2/ns/a/tags/list"
        )

    @override_settings(REGISTRY_TYPE="artifactory", REGISTRY_REPO="docker-local")
    def test_artifactory(self):
        # The inlined copy in get_registry_data had dedicated branches for
        # _catalog and /tags/list; they produced exactly these strings.
        self.assertEqual(
            registry_client._build_registry_url("_catalog"),
            "http://reg:5000/artifactory/api/docker/docker-local/v2/_catalog",
        )
        self.assertEqual(
            registry_client._build_registry_url("a/b/tags/list"),
            "http://reg:5000/artifactory/api/docker/docker-local/v2/a/b/tags/list",
        )


class TagDetailTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_missing_config_blob_does_not_break_the_row(self):
        # `"created" in None` was a TypeError, and the caller turned it into a row
        # that read "Error" everywhere with nothing in the logs to explain it.
        responses = {
            "/manifests/v1": {"config": {"digest": "sha256:cfg"}, "layers": [{"size": 42}]},
            "/blobs/sha256:cfg": None,
        }
        session = RecordingSession(responses)
        with mock.patch.object(registry_client, "get_registry_session", return_value=session):
            detail = views._get_tag_detail("team/image", "v1")
        self.assertEqual(detail["age"], "Unknown")
        self.assertEqual(detail["size_bytes"], 42)
        self.assertEqual(detail["architectures"], ["Unknown"])

    def test_single_arch_detail(self):
        responses = {
            "/manifests/v1": {
                "config": {"digest": "sha256:cfg"},
                "layers": [{"size": 1024}, {"size": 1024}],
            },
            "/blobs/sha256:cfg": {"created": "2026-01-01T00:00:00Z", "architecture": "amd64"},
        }
        session = RecordingSession(responses)
        with mock.patch.object(registry_client, "get_registry_session", return_value=session):
            detail = views._get_tag_detail("team/image", "v1")
        self.assertEqual(detail["architectures"], ["amd64"])
        self.assertEqual(detail["size_bytes"], 2048)
        self.assertEqual(detail["size"], "2.0 KB")


class ErrorPropagationTests(SimpleTestCase):
    """A registry that is down should say so, not 500."""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_tag_counts_reports_a_bad_gateway(self):
        with mock.patch.object(
            registry_client, "get_registry_session", side_effect=requests.exceptions.ConnectionError("down")
        ):
            response = self.client.get("/ui/tag-counts/")
        self.assertEqual(response.status_code, 502)
        self.assertIn("error", response.json())

    def test_tag_details_reports_a_bad_gateway(self):
        with mock.patch.object(
            registry_client, "get_registry_session", side_effect=requests.exceptions.ConnectionError("down")
        ):
            response = self.client.get("/ui/repositories/team/image/tag-details/")
        self.assertEqual(response.status_code, 502)
        self.assertIn("error", response.json())


class ConcurrencyTests(SimpleTestCase):
    """The registry fan-out has to stay ordered, bounded, and failure-tolerant."""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    @override_settings(REGISTRY_MAX_WORKERS=4)
    def test_results_keep_the_input_order(self):
        # dict(zip(items, results)) upstream depends on it.
        items = list(range(20))
        self.assertEqual(registry_client.map_concurrently(lambda i: i * 2, items),
                         [i * 2 for i in items])

    @override_settings(REGISTRY_MAX_WORKERS=4)
    def test_pool_size_is_capped(self):
        seen = set()
        lock = threading.Lock()

        def record(_):
            with lock:
                seen.add(threading.current_thread().name)
            time.sleep(0.01)

        registry_client.map_concurrently(record, range(40))
        self.assertLessEqual(len(seen), 4)

    def test_empty_input_starts_no_threads(self):
        self.assertEqual(registry_client.map_concurrently(lambda i: 1 / 0, []), [])

    @override_settings(REGISTRY_MAX_WORKERS=1)
    def test_single_worker_runs_inline(self):
        self.assertEqual(registry_client.map_concurrently(str, [1, 2]), ["1", "2"])

    @override_settings(REGISTRY_MAX_WORKERS=4)
    def test_one_broken_tag_does_not_sink_the_others(self):
        responses = {
            "/manifests/ok": {"config": {"digest": "sha256:cfg"}, "layers": [{"size": 10}]},
            "/blobs/sha256:cfg": {"created": "2026-01-01T00:00:00Z", "architecture": "amd64"},
        }
        session = RecordingSession(responses)  # "/manifests/bad" falls through to 404
        with mock.patch.object(registry_client, "get_registry_session", return_value=session):
            details = views.get_tag_details_map("team/image", ["ok", "bad"])
        self.assertEqual(details["ok"]["architectures"], ["amd64"])
        self.assertEqual(details["bad"]["architectures"], ["Unknown"])

    @override_settings(REGISTRY_MAX_WORKERS=4)
    def test_repo_stats_dedupes_blobs_shared_between_tags(self):
        # Two tags sharing a layer: the size is counted once, which is the property
        # the per-tag dicts have to preserve now that they are merged afterwards.
        shared = {"config": {"digest": "sha256:cfg"}, "layers": [{"digest": "sha256:layer", "size": 100}]}
        session = RecordingSession({
            "/tags/list": {"tags": ["v1", "v2"]},
            "/manifests/v1": shared,
            "/manifests/v2": shared,
        })
        with mock.patch.object(registry_client, "get_registry_session", return_value=session):
            stats = registry_client.get_repo_stats("team/image")
        self.assertEqual(stats["tags"], 2)
        self.assertEqual(stats["blobs"], 2)  # one config + one layer
        self.assertEqual(stats["size"], 100)
        self.assertEqual(stats["errors"], [])

    @override_settings(REGISTRY_MAX_WORKERS=4)
    def test_sessions_are_reused_within_a_thread(self):
        first = registry_client.get_registry_session()
        self.assertIs(first, registry_client.get_registry_session())

    @override_settings(REGISTRY_USERNAME="bob", REGISTRY_PASSWORD="pw")
    def test_session_is_rebuilt_when_credentials_change(self):
        registry_client._local.__dict__.clear()
        with_auth = registry_client.get_registry_session()
        self.assertEqual(with_auth.auth, ("bob", "pw"))
        with override_settings(REGISTRY_USERNAME="", REGISTRY_PASSWORD=""):
            self.assertIsNone(registry_client.get_registry_session().auth)


@override_settings(ADMIN_PASSWORD="s3cret", ADMIN_LOGIN_MAX_ATTEMPTS=10)
class StatsSummaryTests(SimpleTestCase):
    """An unreadable repository is not an empty one."""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        # Through the real login: with signed-cookie sessions, assigning to
        # `self.client.session` does not set the client's cookie.
        self.client.post("/ui/admin/login/", {"password": "s3cret"})

    def test_unreadable_repository_is_not_offered_for_collection(self):
        counts = {"team/full": 3, "team/empty": 0, "team/broken": None}
        with mock.patch.object(views, "get_all_tag_counts", return_value=counts):
            payload = self.client.get("/ui/stats/summary/").json()
        self.assertEqual(payload["empty_repositories"], ["team/empty"])
        self.assertEqual(payload["unreadable_repositories"], ["team/broken"])
        self.assertEqual(payload["total_tags"], 3)
        self.assertEqual(payload["total_repositories"], 3)

    def test_failed_tag_count_is_none_not_zero(self):
        with mock.patch.object(
            registry_client,
            "get_registry_data",
            side_effect=requests.exceptions.ConnectionError("down"),
        ):
            self.assertIsNone(registry_client.get_tag_count("team/image"))
