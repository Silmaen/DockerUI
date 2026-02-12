# ui/urls.py
from django.urls import path, re_path

from . import views

app_name = "ui"

urlpatterns = [
    path("", views.repository_list, name="index"),
    path("repositories/", views.repository_list, name="repository_list"),
    path("tag-counts/", views.get_tag_counts, name="tag_counts"),
    path("admin/login/", views.admin_login, name="admin_login"),
    path("admin/logout/", views.admin_logout, name="admin_logout"),
    # Delete endpoints (must be before the greedy repository_detail pattern)
    re_path(
        r"^repositories/(?P<repository>.+)/delete-tag/$",
        views.delete_tag,
        name="delete_tag",
    ),
    re_path(
        r"^repositories/(?P<repository>.+)/delete/$",
        views.delete_repository,
        name="delete_repository",
    ),
    # Tag details endpoint (must be before the greedy repository_detail pattern)
    re_path(
        r"^repositories/(?P<repository>.+)/tag-details/$",
        views.get_tag_details,
        name="tag_details",
    ),
    # Use re_path to handle repository names with slashes
    re_path(
        r"^repositories/(?P<repository>.+)/$",
        views.repository_detail,
        name="repository_detail",
    ),
]
