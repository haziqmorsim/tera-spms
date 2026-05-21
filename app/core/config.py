import os
from dotenv import load_dotenv

load_dotenv()
print(os.getenv("DATABASE_URL"))

DATABASE_URL = os.getenv("DATABASE_URL")

FUSIONSOLAR_BASE_URL = os.getenv("FUSIONSOLAR_BASE_URL")
FUSIONSOLAR_USERNAME = os.getenv("FUSIONSOLAR_USERNAME")
FUSIONSOLAR_PASSWORD = os.getenv("FUSIONSOLAR_PASSWORD")
FUSIONSOLAR_LANG = os.getenv("FUSIONSOLAR_LANG", "en_US")
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-me")
SESSION_MAX_AGE = int(os.getenv("SECRET_MAX_AGE", "86400"))

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")

if not FUSIONSOLAR_BASE_URL:
    raise RuntimeError("FUSIONSOLAR_BASE_URL is not set")