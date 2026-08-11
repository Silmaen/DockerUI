"""
URL configuration for DockerUI project.

Django's own admin site is not mounted: this project has no models and no user
accounts, so /admin/ only ever offered a login form to brute-force. Admin mode
lives under /ui/admin/ and is a shared password, see ui/views.py.
"""

from django.urls import include, path
from django.views.generic.base import RedirectView

urlpatterns = [
    path("ui/", include("ui.urls", namespace="ui")),
    path("", RedirectView.as_view(url="/ui/", permanent=True), name="index"),
]
