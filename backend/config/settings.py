import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from django.core.exceptions import ImproperlyConfigured

# backend/
BASE_DIR = Path(__file__).resolve().parent.parent

# Racine du projet
PROJECT_ROOT = BASE_DIR.parent

load_dotenv(PROJECT_ROOT / ".env")


def env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default

    normalized_value = value.strip().lower()
    if normalized_value in {"1", "true", "yes", "on"}:
        return True
    if normalized_value in {"0", "false", "no", "off"}:
        return False
    raise ImproperlyConfigured(
        f"{name} doit contenir une valeur booléenne valide."
    )


def env_int(name, default):
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as error:
        raise ImproperlyConfigured(
            f"{name} doit contenir un nombre entier."
        ) from error


def env_list(name, default=""):
    return [
        value.strip()
        for value in os.getenv(name, default).split(",")
        if value.strip()
    ]


DEBUG = env_bool("DJANGO_DEBUG", False)

SECRET_KEY = os.getenv(
    "DJANGO_SECRET_KEY",
    "development-only-change-me",
).strip()

INSECURE_SECRET_KEYS = {
    "change-me-in-production",
    "development-only-change-me",
}
if not DEBUG and (
    SECRET_KEY in INSECURE_SECRET_KEYS or len(SECRET_KEY) < 50
):
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY doit être remplacée par une valeur aléatoire "
        "d’au moins 50 caractères lorsque DJANGO_DEBUG=False."
    )

ALLOWED_HOSTS = env_list(
    "DJANGO_ALLOWED_HOSTS",
    "localhost,127.0.0.1",
)
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts.apps.AccountsConfig",
    "companies.apps.CompaniesConfig",
    "core.apps.CoreConfig",
    "dashboard.apps.DashboardConfig",
    "documents.apps.DocumentsConfig",
    "imports.apps.ImportsConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [
            BASE_DIR / "templates",
        ],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "accounts.context_processors.company_context",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("POSTGRES_DB", os.getenv("DB_NAME", "paperless")),
        "USER": os.getenv("POSTGRES_USER", os.getenv("DB_USER", "paperless")),
        "PASSWORD": os.getenv("POSTGRES_PASSWORD", os.getenv("DB_PASSWORD", "paperless")),
        "HOST": os.getenv("POSTGRES_HOST", os.getenv("DB_HOST", "localhost")),
        "PORT": os.getenv("POSTGRES_PORT", os.getenv("DB_PORT", "5432")),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

LANGUAGE_CODE = "fr-fr"
TIME_ZONE = "Europe/Paris"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"

STATICFILES_DIRS = [
    BASE_DIR / "static",
]

STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
DOCUMENT_PDF_MAX_BYTES = env_int(
    "DOCUMENT_PDF_MAX_BYTES",
    25 * 1024 * 1024,
)
SCAN_INPUT_DIRECTORY = Path(
    os.getenv("SCAN_INPUT_DIRECTORY", "/scan/incoming")
)
SCAN_PAPERLESS_DIRECTORY = Path(
    os.getenv("SCAN_PAPERLESS_DIRECTORY", "/scan/paperless-consume")
)
SCAN_STABILITY_SECONDS = env_int("SCAN_STABILITY_SECONDS", 10)
SCAN_POLL_SECONDS = env_int("SCAN_POLL_SECONDS", 5)
SCAN_DEFAULT_COMPANY_CODE = os.getenv(
    "SCAN_DEFAULT_COMPANY_CODE",
    "",
).strip()
SCAN_DEFAULT_DOCUMENT_TYPE_CODE = os.getenv(
    "SCAN_DEFAULT_DOCUMENT_TYPE_CODE",
    "",
).strip()
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "/admin/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"

SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SAMESITE = "Lax"
SECURE_SSL_REDIRECT = env_bool(
    "DJANGO_SECURE_SSL_REDIRECT",
    not DEBUG,
)
SECURE_REDIRECT_EXEMPT = [r"^health/$"]
CSRF_COOKIE_SECURE = env_bool(
    "DJANGO_CSRF_COOKIE_SECURE",
    not DEBUG,
)
SESSION_COOKIE_SECURE = env_bool(
    "DJANGO_SESSION_COOKIE_SECURE",
    not DEBUG,
)
SECURE_HSTS_SECONDS = env_int(
    "DJANGO_SECURE_HSTS_SECONDS",
    31536000 if not DEBUG else 0,
)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool(
    "DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS",
    not DEBUG,
)
SECURE_HSTS_PRELOAD = env_bool(
    "DJANGO_SECURE_HSTS_PRELOAD",
    not DEBUG,
)
SECURE_REFERRER_POLICY = "same-origin"

if env_bool("DJANGO_TRUST_PROXY_HEADERS", False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    USE_X_FORWARDED_HOST = True

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG or "test" in sys.argv
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        ),
    },
}
