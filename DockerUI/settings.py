"""
Django settings for DockerUI project.

Everything configurable comes from the environment: see README.md for the full
table. This application stores nothing of its own -- no models, no database, no
server-side session store -- so the settings below are mostly about talking to a
registry and about not trusting the network in between.
"""

import os
from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


def env_flag(name, default=False):
    """Read a boolean environment variable.

    Empty counts as unset: docker compose passes a variable missing from .env as
    an empty string, and that must fall back to the default rather than to False.
    """
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    return raw.lower() in ("1", "true", "yes", "on")


def env_list(name):
    """Read a comma-separated environment variable into a list."""
    return [item.strip() for item in os.environ.get(name, "").split(",") if item.strip()]


# SECURITY WARNING: keep the secret key used in production secret!
# It signs the session cookie, which is what carries the admin flag.
SECRET_KEY = os.environ.get("SECRET_KEY") or "django-insecure-default-key-for-dev"

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = env_flag("DEBUG")

# `*` stays the default because the UI is normally published behind a reverse
# proxy that already validates the host. Set it to the real hostname(s) to have
# Django reject forged Host headers itself.
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS") or ["*"]

# Required as soon as the UI is served over HTTPS or under a hostname that is not
# localhost: without it Django rejects the admin login POST with an opaque 403.
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")

# Whether the X-Forwarded-* headers can be believed. Only true behind a proxy that
# *always* overwrites them: if a client can set them, it can claim its plain HTTP
# request was secure, and can forge the address the login throttle counts against.
TRUST_PROXY = env_flag("TRUST_PROXY")
if TRUST_PROXY:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Cookies restricted to HTTPS. Off by default: turning it on while serving plain
# HTTP silently breaks the admin login, since the browser then never sends them.
SESSION_COOKIE_SECURE = env_flag("SECURE_COOKIES")
CSRF_COOKIE_SECURE = env_flag("SECURE_COOKIES")


# Application definition
#
# No django.contrib.admin / auth / contenttypes: this project has no models and no
# user accounts, so they were three unused apps, a login form exposed on /admin/,
# and the only reason a database was needed at all.
INSTALLED_APPS = [
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "ui",
]

# Docker Registry configuration
REGISTRY_URL = os.environ.get("REGISTRY_URL") or "http://registry:5000"
REGISTRY_REPO = os.environ.get("REGISTRY_REPO", "")
REGISTRY_SSL_VERIFY = env_flag("REGISTRY_SSL_VERIFY")
REGISTRY_USERNAME = os.environ.get("REGISTRY_USERNAME", "")
REGISTRY_PASSWORD = os.environ.get("REGISTRY_PASSWORD", "")
REGISTRY_TYPE = os.environ.get("REGISTRY_TYPE") or "classic"

# How long a registry response stays cached, in seconds.
REGISTRY_CACHE_TTL = int(os.environ.get("REGISTRY_CACHE_TTL") or 300)
# Parallel requests to the registry when walking a catalog or a tag list. The work
# is pure I/O, so this is about the registry's tolerance, not about CPU.
REGISTRY_MAX_WORKERS = int(os.environ.get("REGISTRY_MAX_WORKERS") or 8)

# Admin mode configuration
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
# Failed logins allowed per client address before the form stops answering.
ADMIN_LOGIN_MAX_ATTEMPTS = int(os.environ.get("ADMIN_LOGIN_MAX_ATTEMPTS") or 10)
ADMIN_LOGIN_LOCKOUT_SECONDS = int(os.environ.get("ADMIN_LOGIN_LOCKOUT_SECONDS") or 300)

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "DockerUI.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.messages.context_processors.messages",
                "ui.context_processors.version_context",
            ],
        },
    },
]

WSGI_APPLICATION = "DockerUI.wsgi.application"


# Database
#
# There is none. The admin flag lives in a signed cookie, so nothing needs to be
# written anywhere: the container has no writable state, `migrate` has nothing to
# do, and an admin session now survives a redeployment instead of being dropped
# with the rebuilt SQLite file.
DATABASES = {}

SESSION_ENGINE = "django.contrib.sessions.backends.signed_cookies"
# A signed cookie cannot be revoked server-side, so it is given a bounded life:
# 8 hours, after which Django refuses it whatever the signature says.
SESSION_COOKIE_AGE = int(os.environ.get("SESSION_COOKIE_AGE") or 8 * 3600)
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"


# Caches
#
# The default LocMemCache holds 300 entries per *worker process*, culling a third
# at a time: walking a mid-sized registry evicts manifests while they are still in
# use, and each worker repeats every call the others already made. A file-backed
# cache is shared by every worker, survives a restart, and needs no extra service.
# Point CACHE_LOCATION at a tmpfs, or swap in Redis, if the churn matters.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
        "LOCATION": os.environ.get("CACHE_LOCATION") or "/tmp/dockerui-cache",
        "TIMEOUT": REGISTRY_CACHE_TTL,
        "OPTIONS": {
            # Manifest walks generate one entry per blob digest; 300 is nowhere
            # near enough, and a file entry costs a few hundred bytes.
            "MAX_ENTRIES": int(os.environ.get("CACHE_MAX_ENTRIES") or 20000),
        },
    }
}


LOG_LEVEL = (os.environ.get("LOG_LEVEL") or "INFO").upper()

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "%(levelname)s %(name)s %(message)s"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "simple",
        },
    },
    "loggers": {
        "ui": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
        # Without this, an unhandled view exception is a bare 500 in the browser
        # and *nothing at all* in the container logs: django.request had no
        # handler attached.
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}

# Internationalization
LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

STATIC_URL = "static/"
STATICFILES_DIRS = [
    BASE_DIR / "ui" / "static",
]
STATIC_ROOT = BASE_DIR / "staticfiles"

# Default primary key field type
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
