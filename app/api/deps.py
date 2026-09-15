from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, Path, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings
from app.core.exceptions import (
    AuthenticationError,
    ChatbotUnavailableError,
    PermissionDeniedError,
)
from app.core.logging import chatbot_id_var, org_id_var
from app.core.security import decode_token
from app.models import Chatbot, ChatbotStatus, User, UserRole
from app.schemas.common import PageParams
from app.services import chatbot as chatbot_service
from app.services import widget as widget_service
from app.services.auth import get_active_user

_bearer = HTTPBearer(auto_error=False, description="Dashboard access token")


@dataclass(frozen=True, slots=True)
class Principal:
    user: User

    @property
    def org_id(self) -> UUID:
        return self.user.org_id

    @property
    def role(self) -> UserRole:
        return UserRole(self.user.role)


async def current_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Principal:
    if credentials is None:
        raise AuthenticationError("Missing bearer token")

    payload = decode_token(
        credentials.credentials, expected_type="access", config=settings.security
    )
    user = await get_active_user(UUID(payload["org"]), UUID(payload["sub"]))
    org_id_var.set(str(user.org_id))
    return Principal(user=user)


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]


def require_role(minimum: UserRole):
    """Role gate for destructive or billing-relevant operations."""

    async def guard(principal: CurrentPrincipal) -> Principal:
        if not principal.role.can_act_as(minimum):
            raise PermissionDeniedError(f"This action requires the {minimum} role or higher")
        return principal

    return guard


RequireAdmin = Annotated[Principal, Depends(require_role(UserRole.ADMIN))]
RequireOwner = Annotated[Principal, Depends(require_role(UserRole.OWNER))]


async def resolve_chatbot(
    principal: CurrentPrincipal,
    chatbot_id: Annotated[UUID, Path(description="Chatbot identifier")],
) -> Chatbot:
    """Loads the chatbot and proves it belongs to the caller's organisation."""
    chatbot = await chatbot_service.get_chatbot(principal.org_id, chatbot_id)
    chatbot_id_var.set(str(chatbot.id))
    return chatbot


OwnedChatbot = Annotated[Chatbot, Depends(resolve_chatbot)]


def page_params(
    limit: int = 50,
    offset: int = 0,
) -> PageParams:
    return PageParams(limit=limit, offset=offset)


Pagination = Annotated[PageParams, Depends(page_params)]


async def secret_key_chatbot(
    x_chatbot_secret: Annotated[
        str,
        Header(
            alias="X-Chatbot-Secret",
            description="Chatbot secret key (sk_...), for server-to-server calls",
        ),
    ],
) -> Chatbot:
    """Authenticates a server-to-server call as one chatbot.

    Its own header rather than `Authorization: Bearer`, which in this application already
    means a dashboard access token. One header with two meanings is how an auth bug gets
    written, and the name mirrors the widget's `X-Chatbot-Key` so which credential goes where
    is legible from the request alone.

    The key is never stored or compared in plaintext: the row is found by the digest, which is
    what the unique index in 0016 covers, and then confirmed with a constant-time compare. The
    lookup is unscoped because the key *is* the tenant — the same shape as the widget's public
    key, with the difference that this one is a secret and grants a chatbot's whole corpus.

    A paused or archived chatbot serves nothing here either, matching the widget: the toggle
    means "this chatbot is not answering", not "this chatbot is not answering the widget".
    """
    presented = x_chatbot_secret.strip()
    chatbot = await chatbot_service.authenticate_secret_key(presented)
    if chatbot is None:
        # One message for an unknown key and for a wrong one. Which of the two it was is not
        # something an unauthenticated caller is entitled to learn.
        raise AuthenticationError("Invalid chatbot secret key")
    if ChatbotStatus(chatbot.status) is not ChatbotStatus.ACTIVE:
        raise ChatbotUnavailableError("This chatbot is not currently available")

    org_id_var.set(str(chatbot.org_id))
    chatbot_id_var.set(str(chatbot.id))
    return chatbot


SecretKeyChatbot = Annotated[Chatbot, Depends(secret_key_chatbot)]


async def widget_session(
    request: Request,
    x_chatbot_key: Annotated[
        str, Header(alias="X-Chatbot-Key", description="Public widget key (pk_...)")
    ],
    x_widget_site: Annotated[
        str | None,
        Header(
            alias="X-Widget-Site",
            description="Origin of the page hosting the widget, as attested by the browser",
        ),
    ] = None,
    origin: Annotated[str | None, Header(alias="Origin")] = None,
) -> widget_service.WidgetSession:
    """Authenticates a widget call: the public key identifies the chatbot, the site authorises it."""
    config = await widget_service.resolve_chatbot(x_chatbot_key)
    site_origin = widget_service.resolve_site_origin(
        declared=x_widget_site, origin=origin, referer=request.headers.get("referer")
    )
    allowed_origin = widget_service.enforce_origin(config, site_origin)
    widget_service.ensure_active(config)

    org_id_var.set(config["org_id"])
    chatbot_id_var.set(config["id"])
    return widget_service.build_session(config, allowed_origin)


WidgetSession = Annotated[widget_service.WidgetSession, Depends(widget_session)]
