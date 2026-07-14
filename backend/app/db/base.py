"""Import every model here so Alembic autogenerate can see the full metadata."""

from app.db.base_class import Base  # noqa: F401
from app.models.alert import WebhookAlert  # noqa: F401
from app.models.audit_log import AuditLog  # noqa: F401
from app.models.broker_credential import BrokerCredential  # noqa: F401
from app.models.order import OrderRecord  # noqa: F401
from app.models.refresh_token import RefreshToken  # noqa: F401
from app.models.scan import ScannerAlert, ScanResult  # noqa: F401
from app.models.user import User  # noqa: F401
from app.models.watchlist import Watchlist  # noqa: F401

__all__ = [
    "Base",
    "User",
    "RefreshToken",
    "AuditLog",
    "BrokerCredential",
    "OrderRecord",
    "WebhookAlert",
]
