import os

import pytest
from cryptography.fernet import Fernet

# Settings are read once at import time, so test-specific values must be in place before
# anything under `app` is imported. Database and Redis are deliberately *not* set here:
# they fall through to .env so the suite targets whatever the developer already configured.
os.environ.setdefault("ENVIRONMENT", "local")
os.environ.setdefault("STORAGE_BACKEND", "local")
os.environ.setdefault("STORAGE_LOCAL_ROOT", "./var/test-uploads")
os.environ.setdefault("SECURITY_JWT_SECRET", "test-secret")
# The application has no default for this and refuses to start without one, so the suite
# brings its own. A fresh key per run is deliberate: nothing encrypted by one run should be
# readable by the next.
os.environ.setdefault("AI_CREDENTIALS_ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ.setdefault("OTEL_LOG_FORMAT", "console")
os.environ.setdefault("OTEL_LOG_LEVEL", "WARNING")
os.environ.setdefault("OTEL_METRICS_ENABLED", "false")
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "integration: needs a reachable Postgres (pgvector) and Redis"
    )
