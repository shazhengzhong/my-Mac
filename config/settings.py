"""Django settings for the family English diary project."""

from datetime import timedelta
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Local secrets live in .env only. The file is gitignored and never sent to the browser.
load_dotenv(BASE_DIR / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ImproperlyConfigured(f"{name} must be an integer") from exc


def env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ImproperlyConfigured(f"{name} must be a number") from exc


def env_list(name: str, default: str = "") -> list[str]:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "").strip()
if not SECRET_KEY:
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY is missing. Copy .env.example to .env and set a private value."
    )

DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost,testserver")


# Application definition

INSTALLED_APPS = [
    "axes",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "diaries",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "axes.middleware.AxesMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# Database. The var directory is local runtime data and is not committed.

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "var" / "db.sqlite3",
        "OPTIONS": {"timeout": 20},
    }
}


# Authentication

AUTH_USER_MODEL = "accounts.User"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "login"

AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

# Temporary login lockout after repeated failures.
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = timedelta(minutes=15)
AXES_RESET_ON_SUCCESS = True


# Internationalization

LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True


# Static files. Private recordings/TTS are deliberately NOT served from a public media URL.

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "var" / "staticfiles"

PRIVATE_MEDIA_ROOT = BASE_DIR / "private_media"


# Upload limits for short audio clips.
DATA_UPLOAD_MAX_MEMORY_SIZE = 6 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024


# Sessions and basic security headers.

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 14 * 24 * 60 * 60
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "same-origin"
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

if not DEBUG:
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")


# Pluggable external services. Start with mocks until credentials are deliberately supplied.

TRANSLATION_PROVIDER = os.getenv("TRANSLATION_PROVIDER", "mock").strip().lower()
TTS_PROVIDER = os.getenv("TTS_PROVIDER", "mock").strip().lower()

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip()

VOLCENGINE_API_KEY = os.getenv("VOLCENGINE_API_KEY", "").strip()
VOLCENGINE_APP_ID = os.getenv("VOLCENGINE_APP_ID", "").strip()
VOLCENGINE_ACCESS_TOKEN = os.getenv("VOLCENGINE_ACCESS_TOKEN", "").strip()
VOLCENGINE_TTS_VOICE = os.getenv("VOLCENGINE_TTS_VOICE", "").strip()
VOLCENGINE_RESOURCE_ID = os.getenv("VOLCENGINE_RESOURCE_ID", "seed-tts-2.0").strip()
VOLCENGINE_TTS_SAMPLE_RATE = env_int("VOLCENGINE_TTS_SAMPLE_RATE", 24_000)
VOLCENGINE_TTS_NORMAL_SPEECH_RATE = env_int("VOLCENGINE_TTS_NORMAL_SPEECH_RATE", -20)
VOLCENGINE_TTS_SLOW_SPEECH_RATE = env_int("VOLCENGINE_TTS_SLOW_SPEECH_RATE", -35)
VOLCENGINE_TTS_WORD_SPEECH_RATE = env_int("VOLCENGINE_TTS_WORD_SPEECH_RATE", -20)

TRANSLATION_DAILY_REQUEST_LIMIT = env_int("TRANSLATION_DAILY_REQUEST_LIMIT", 20)
TTS_DAILY_CHAR_LIMIT = env_int("TTS_DAILY_CHAR_LIMIT", 5000)

# Word-level pronunciation assessment. Mock by default; Tencent SOE when configured.
ASSESSMENT_PROVIDER = os.getenv("ASSESSMENT_PROVIDER", "mock").strip().lower()
ASSESSMENT_DAILY_REQUEST_LIMIT = env_int("ASSESSMENT_DAILY_REQUEST_LIMIT", 30)
TENCENTCLOUD_SECRET_ID = os.getenv("TENCENTCLOUD_SECRET_ID", "").strip()
TENCENTCLOUD_SECRET_KEY = os.getenv("TENCENTCLOUD_SECRET_KEY", "").strip()
TENCENT_SOE_APP_ID = os.getenv("TENCENT_SOE_APP_ID", "").strip()
TENCENT_SOE_ENGINE = os.getenv("TENCENT_SOE_ENGINE", "16k_en").strip()
TENCENT_SOE_SCORE_COEFF = env_float("TENCENT_SOE_SCORE_COEFF", 1.0)
TENCENT_SOE_TIMEOUT = env_int("TENCENT_SOE_TIMEOUT", 20)

# The test suite must never reach a paid provider, even when .env enables one.
TEST_RUNNER = "config.test_runner.OfflineProvidersTestRunner"


# Default primary key field type

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
