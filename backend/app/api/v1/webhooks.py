"""TradingView webhook receiver.

Security reality: TradingView cannot sign requests or send custom headers, so
HMAC is off the table. The standard mitigation is a shared secret **inside the
JSON body**, compared with ``hmac.compare_digest`` (constant-time), plus the
fact that the webhook can only *record* an alert — it cannot place an order.
An alert becomes a trade only if something downstream, with real auth, decides
it should. A webhook that trades directly is an unauthenticated order API.
"""

from __future__ import annotations

import hmac
import json

from fastapi import APIRouter, Request, status

from app.core.config import settings
from app.core.exceptions import AuthenticationError
from app.core.logging import get_logger
from app.db.session import AsyncSessionLocal
from app.models.alert import WebhookAlert
from app.schemas.common import Message

router = APIRouter()
logger = get_logger(__name__)

MAX_BODY_BYTES = 8_192


@router.post(
    "/tradingview",
    response_model=Message,
    status_code=status.HTTP_202_ACCEPTED,
    summary="TradingView alert webhook (secret in body, records only)",
)
async def tradingview(request: Request) -> Message:
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise AuthenticationError("payload too large", code="webhook_rejected")

    if not settings.TRADINGVIEW_WEBHOOK_SECRET:
        raise AuthenticationError(
            "TRADINGVIEW_WEBHOOK_SECRET is not configured; refusing all webhooks",
            code="webhook_disabled",
        )

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise AuthenticationError("body must be JSON", code="webhook_rejected") from exc

    supplied = str(payload.get("secret", ""))
    if not hmac.compare_digest(supplied, settings.TRADINGVIEW_WEBHOOK_SECRET):
        logger.warning("TradingView webhook rejected: bad secret")
        raise AuthenticationError("invalid webhook secret", code="webhook_rejected")

    # Strip the secret before persisting — the audit trail must not contain it.
    payload.pop("secret", None)

    alert = WebhookAlert(
        source="tradingview",
        symbol=str(payload.get("ticker") or payload.get("symbol") or "")[:32] or None,
        alert_name=str(payload.get("alert_name") or payload.get("name") or "")[:128] or None,
        direction=str(payload.get("direction") or "")[:16] or None,
        price=float(payload["price"]) if payload.get("price") is not None else None,
        raw_body=json.dumps(payload)[:8000],
    )

    # The webhook has no user context, so it gets its own session.
    async with AsyncSessionLocal() as db:
        db.add(alert)
        await db.commit()

    logger.info("TradingView alert stored: %s %s", alert.symbol, alert.alert_name)
    return Message(message="alert recorded")
