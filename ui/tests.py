from django.test import SimpleTestCase
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
