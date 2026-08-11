"""Settings for the test suite.

Two production choices are unhelpful under test:

* `CompressedManifestStaticFilesStorage` refuses to resolve `{% static %}` unless
  `collectstatic` has run, so rendering any template in a fresh checkout raises
  "Missing staticfiles manifest entry" -- a failure about the build, not the code.
* the file-backed cache is shared with the running application, so a test that
  fills it (the login throttle, for one) reaches outside its own process.

Used by `./deploy.sh tests`; run it by hand with
`python manage.py test --settings=DockerUI.settings_test`.
"""

from .settings import *  # noqa: F403

STORAGES = {
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "dockerui-tests",
    }
}

# WhiteNoise warns on every run that STATIC_ROOT does not exist -- true, and
# irrelevant: nothing under test serves a static file.
MIDDLEWARE = [m for m in MIDDLEWARE if "whitenoise" not in m]  # noqa: F405

# Signing has to be deterministic and independent of the deployment's key.
SECRET_KEY = "dockerui-test-key"

# Expected warnings (rejected logins, unreadable manifests) would otherwise be
# interleaved with the progress dots and read as failures.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"null": {"class": "logging.NullHandler"}},
    "loggers": {
        "ui": {"handlers": ["null"], "level": "CRITICAL", "propagate": False},
        "django": {"handlers": ["null"], "level": "CRITICAL", "propagate": False},
    },
}

# The suite never talks to a real registry; a bare hostname makes an accidental
# call fail fast and loudly instead of reaching something real.
REGISTRY_URL = "http://registry.invalid:5000"
REGISTRY_REPO = ""
REGISTRY_TYPE = "classic"
