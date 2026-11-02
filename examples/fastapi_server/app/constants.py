"""Server defaults and endpoint validation bounds."""

DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///example_notifications.db"
DEFAULT_PROVIDER_NAME = "console"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
MIN_TEXT_LENGTH = 1
MAX_WORKER_JOBS = 1000
DEFAULT_WORKER_JOBS = 100
MIN_WORKER_JOBS = 1
API_PREFIX = "/v1"
