import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

FUSIONSOLAR_BASE_URL = os.getenv("FUSIONSOLAR_BASE_URL")
FUSIONSOLAR_USERNAME = os.getenv("FUSIONSOLAR_USERNAME")
FUSIONSOLAR_PASSWORD = os.getenv("FUSIONSOLAR_PASSWORD")
FUSIONSOLAR_LANG = os.getenv("FUSIONSOLAR_LANG", "en_US")

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-me")
SESSION_MAX_AGE = int(os.getenv("SESSION_MAX_AGE", os.getenv("SECRET_MAX_AGE", "86400")))

FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL", "").strip()

CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ALLOWED_ORIGINS",
        "http://localhost:8888,http://localhost:5173,http://127.0.0.1:8888",
    ).split(",")
    if origin.strip()
]

SESSION_COOKIE_SAMESITE = os.getenv("SESSION_COOKIE_SAMESITE", "lax").strip().lower()
SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "y",
}

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")

if not FUSIONSOLAR_BASE_URL:
    raise RuntimeError("FUSIONSOLAR_BASE_URL is not set")