from fastapi import APIRouter, Query, status

from app.api.deps import CurrentPrincipal
from app.schemas.auth import (
    LoginRequest,
    OrganizationRead,
    RefreshRequest,
    SignupRequest,
    SignupResponse,
    TokenPair,
    UserRead,
)
from app.schemas.team import (
    AcceptInvitationRequest,
    AcceptInvitationResponse,
    InvitationPreview,
)
from app.services import auth as auth_service
from app.services import team as team_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=SignupResponse, status_code=status.HTTP_201_CREATED)
async def signup(payload: SignupRequest) -> SignupResponse:
    organization, user, tokens = await auth_service.signup(
        organization_name=payload.organization_name,
        email=payload.email,
        password=payload.password,
        full_name=payload.full_name,
    )
    return SignupResponse(
        organization=OrganizationRead.model_validate(organization),
        user=UserRead.model_validate(user),
        tokens=tokens,
    )


@router.post("/login", response_model=TokenPair)
async def login(payload: LoginRequest) -> TokenPair:
    _, tokens = await auth_service.authenticate(email=payload.email, password=payload.password)
    return tokens


@router.post("/refresh", response_model=TokenPair)
async def refresh(payload: RefreshRequest) -> TokenPair:
    return await auth_service.refresh_tokens(payload.refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(payload: RefreshRequest) -> None:
    """Retires the refresh token so the session cannot be renewed.

    Unauthenticated on purpose: possession of the refresh token is the only thing being
    acted on, and a client whose access token has already expired must still be able to sign
    out cleanly.
    """
    await auth_service.logout(payload.refresh_token)


@router.get("/me", response_model=UserRead)
async def me(principal: CurrentPrincipal) -> UserRead:
    return UserRead.model_validate(principal.user)


@router.get("/invitations/preview", response_model=InvitationPreview)
async def preview_invitation(
    token: str = Query(min_length=16, max_length=256),
) -> InvitationPreview:
    """Lets the acceptance page name the organisation before the invitee sets a password."""
    organization, invitation = await team_service.preview_invitation(token)
    return InvitationPreview(
        organization_name=organization.name,
        email=invitation.email,
        role=invitation.role,
        expires_at=invitation.expires_at,
    )


@router.post(
    "/invitations/accept",
    response_model=AcceptInvitationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def accept_invitation(payload: AcceptInvitationRequest) -> AcceptInvitationResponse:
    organization, user, tokens = await team_service.accept_invitation(
        token=payload.token, password=payload.password, full_name=payload.full_name
    )
    return AcceptInvitationResponse(
        organization=OrganizationRead.model_validate(organization),
        user=UserRead.model_validate(user),
        tokens=tokens,
    )
