"""Central configuration — PostgreSQL locally, SQLite fallback.

Local production DB: postgresql://postgres:123@localhost:5432/azadexa
Set it via the DATABASE_URL env var (or the local .env file). Any explicit
postgresql:// URI is honoured directly. A stray global DATABASE_URL from
another project (non-postgres, no opt-in) still falls back to local SQLite
so dev runs are never hijacked.
"""
import os

try:
    from dotenv import load_dotenv
    # override=True: the project's own .env always wins over stray global
    # env vars from other projects on the same machine (e.g. a global
    # DATABASE_URL pointing at another database). Local runs must never
    # be hijacked by another project's connection string.
    load_dotenv(os.path.join(os.path.abspath(os.path.dirname(__file__)),
                             ".env"),
                override=True)
except Exception:
    pass

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


def _resolve_db_uri() -> str:
    local_sqlite = "sqlite:///" + os.path.join(BASE_DIR, "instance", "reports.db")
    raw = os.environ.get("DATABASE_URL", "").strip()
    if not raw:
        return local_sqlite

    # If explicitly set to PostgreSQL, use it regardless of markers
    if raw.startswith("postgresql://"):
        return raw

    # If set to legacy postgres://, upgrade to postgresql://
    if raw.startswith("postgres://"):
        raw = raw.replace("postgres://", "postgresql://", 1)
        return raw

    # Otherwise check cloud markers and opts
    cloud_markers = ("RENDER", "RAILWAY_ENVIRONMENT", "HEROKU_APP_NAME", "DYNO",
                     "K_SERVICE", "CONTAINER_APP_NAME")
    opted_in = (
        os.environ.get("USE_CLOUD_DB", "0") == "1"
        or os.environ.get("FLASK_ENV") == "production"
        or any(os.environ.get(m) for m in cloud_markers)
        or os.path.exists(os.path.join(BASE_DIR, ".env"))
    )
    if not opted_in:
        return local_sqlite

    return raw


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-in-production")
    SQLALCHEMY_DATABASE_URI = _resolve_db_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAX_CONTENT_LENGTH = 4 * 1024 * 1024
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
    ALLOWED_MIME = {"image/jpeg", "image/png", "image/gif",
                    "image/webp", "application/pdf"}
    APP_NAME_AR = "منصة أزادكسا لتقارير المشاريع الإنشائية"
    # ---- AZAD Intelligent Systems brand identity
    COMPANY_NAME_AR = "شركة أزاد للأنظمة الذكية"
    COMPANY_NAME_EN = "AZAD Intelligent Systems"
    DEVELOPER_AR = "م. أحمد غنيم (أبو أزاد)"
    DEVELOPER_EN = "Eng. Ahmad Ghannam"
    CONTACT_EMAIL = "rafideen.ahmadghannam@gmail.com"
    CONTACT_PHONE = "+972 56 215 0193"
    HQ_AR = "رام الله – فلسطين"
