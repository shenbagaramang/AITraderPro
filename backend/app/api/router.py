from fastapi import APIRouter

from app.api.v1 import (
    analysis,
    auth,
    broker,
    health,
    orders,
    research,
    scanner,
    users,
    webhooks,
)

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(broker.router, prefix="/broker", tags=["broker"])
api_router.include_router(orders.router, prefix="/orders", tags=["orders"])
api_router.include_router(analysis.router, prefix="/analysis", tags=["analysis"])
api_router.include_router(research.router, prefix="/research", tags=["research"])
api_router.include_router(scanner.router, prefix="/scanner", tags=["scanner"])
api_router.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
