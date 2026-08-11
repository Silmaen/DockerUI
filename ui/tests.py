from django.core.cache import cache
from django.test import SimpleTestCase, override_settings
from django.urls import Resolver404, resolve, reverse

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
