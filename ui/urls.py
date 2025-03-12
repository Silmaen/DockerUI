# ui/urls.py
from django.urls import path, re_path

from . import views

app_name = "ui"

urlpatterns = [
    path("", views.index, name="index"),
    path("repositories/", views.repository_list, name="repository_list"),
    path("tag-counts/", views.get_tag_counts, name="tag_counts"),
    # Use re_path to handle repository names with slashes
    re_path(
        r"^repositories/(?P<repository>.+)/$",
        views.repository_detail,
        name="repository_detail",
    ),
]
