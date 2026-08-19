from fastapi import APIRouter

from app.api.public import chat as widget_chat
from app.api.v1 import (
    ai_config,
    auth,
    chatbots,
    conversations,
    documents,
    health,
    team,
    tickets,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(team.router)
api_router.include_router(chatbots.router)
api_router.include_router(ai_config.router)
api_router.include_router(documents.router)
api_router.include_router(conversations.router)
api_router.include_router(tickets.router)

# Widget traffic is unauthenticated in the dashboard sense and is expected to be the
# highest-volume surface, so it lives under its own prefix and can be routed or scaled
# separately at the ingress.
public_router = APIRouter()
public_router.include_router(widget_chat.router)

health_router = health.router
