# ui/urls.py
from django.urls import path, register_converter

from . import views
from .converters import RepositoryConverter

app_name = "ui"

# Registered under a short name because it appears in most of the routes below.
register_converter(RepositoryConverter, "repo")

urlpatterns = [
    path("", views.repository_list, name="index"),
    path("repositories/", views.repository_list, name="repository_list"),
    path("tag-counts/", views.get_tag_counts, name="tag_counts"),
    path("admin/login/", views.admin_login, name="admin_login"),
    path("admin/logout/", views.admin_logout, name="admin_logout"),
    path("stats/", views.registry_stats, name="registry_stats"),
    path("stats/summary/", views.registry_stats_summary, name="registry_stats_summary"),
    path("stats/repo/<repo:repository>/", views.registry_stats_repo, name="registry_stats_repo"),
    # The <repo> pattern accepts slashes, so it also matches `foo/delete`. Every
    # route more specific than repository_detail has to come first.
    path("repositories/<repo:repository>/delete-tag/", views.delete_tag, name="delete_tag"),
    path("repositories/<repo:repository>/delete/", views.delete_repository, name="delete_repository"),
    path("repositories/<repo:repository>/tag-details/", views.get_tag_details, name="tag_details"),
    path("repositories/<repo:repository>/", views.repository_detail, name="repository_detail"),
]
