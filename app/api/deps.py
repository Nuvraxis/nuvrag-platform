from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, Path, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings
from app.core.exceptions import AuthenticationError, PermissionDeniedError
from app.core.logging import chatbot_id_var, org_id_var
from app.core.security import decode_token
from app.models import Chatbot, User, UserRole
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
