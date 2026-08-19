from uuid import UUID

from fastapi import APIRouter

from app.api.deps import CurrentPrincipal, RequireAdmin
from app.schemas.ai_config import (
    AIConfigRead,
    AIConfigTest,
    AIConfigTestResult,
    AIConfigUpdate,
)
from app.services import ai_config as ai_config_service

router = APIRouter(prefix="/chatbots/{chatbot_id}/ai-config", tags=["ai-config"])


@router.get("", response_model=AIConfigRead)
async def get_ai_config(chatbot_id: UUID, principal: CurrentPrincipal) -> AIConfigRead:
    """Providers, models and connection detail. Credentials are write-only and never returned,
    the same posture as the chatbot's secret key."""
    return await ai_config_service.get_config(principal.org_id, chatbot_id)


@router.put("", response_model=AIConfigRead)
async def put_ai_config(
    chatbot_id: UUID, payload: AIConfigUpdate, principal: RequireAdmin
) -> AIConfigRead:
    """Replace the whole configuration.

    Omit a `credentials` object to keep the key already stored. Changing the embedding
    provider or model is refused with a 409 once the chatbot has chunks: existing vectors
    cannot be compared against a different model's.
    """
    return await ai_config_service.save_config(principal.org_id, chatbot_id, payload)


@router.post("/test", response_model=AIConfigTestResult)
async def test_ai_config(
    chatbot_id: UUID, payload: AIConfigTest, principal: RequireAdmin
) -> AIConfigTestResult:
    """Call the providers with values that have not been saved yet.

    Always 200 — the verdict is in the body, because a provider rejecting a tenant's key is a
    result this endpoint delivered successfully, not a failure of this endpoint.
    """
    return await ai_config_service.test_config(principal.org_id, chatbot_id, payload)
