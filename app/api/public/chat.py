import json
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Header, Request, status
from fastapi.responses import StreamingResponse

from app.api.deps import WidgetSession
from app.core.client_ip import client_ip
from app.core.exceptions import DomainError, UpstreamServiceError
from app.core.logging import get_logger
from app.schemas.chat import (
    SESSION_ID_MAX_LENGTH,
    SESSION_ID_MIN_LENGTH,
    SESSION_ID_PATTERN,
    WidgetBootstrap,
    WidgetChatRequest,
    WidgetMessage,
    WidgetSessionState,
)
from app.schemas.ticket import TicketCreate, TicketCreated
from app.services import ticket as ticket_service
from app.services import widget as widget_service
from app.services.rag import stream_answer

logger = get_logger(__name__)

router = APIRouter(prefix="/widget", tags=["widget"])

_SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    # Nginx buffers proxied responses by default, which would defeat streaming entirely.
    "X-Accel-Buffering": "no",
}


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


@router.get("/bootstrap", response_model=WidgetBootstrap)
async def bootstrap(
    session: WidgetSession,
    session_id: Annotated[
        str | None,
        Header(
            alias="X-Widget-Session",
            min_length=SESSION_ID_MIN_LENGTH,
            max_length=SESSION_ID_MAX_LENGTH,
            pattern=SESSION_ID_PATTERN,
            description="Widget session to replay, if the visitor has one",
        ),
    ] = None,
) -> WidgetBootstrap:
    """Called once when the widget iframe loads, before any message is sent.

    A visitor who opened a ticket comes back with their session id, and gets the transcript
    plus the ticket's status with it — there is no outbound mail, so reopening the widget is
    how a staff reply reaches the person who asked for it.

    The session id is a bearer capability, not an identity: it is 128 bits of browser-
    generated randomness, and it only means anything alongside the public key and an
    allow-listed origin that got this request past `WidgetSession` in the first place. It is
    rate-limited on the same buckets as chat so it cannot be used to sweep for live sessions.

    It arrives as a **header rather than a query parameter** precisely because its job changed
    from labelling a conversation to granting read access to one. A query string is written to
    ingress access logs (nginx's default `$request` includes it), kept in browser history, and
    handed to third parties in `Referer`; a request header is in none of those places. The
    widget already sends `X-Chatbot-Key` and `X-Widget-Site`, so this costs nothing new.
    """
    theme = session.theme
    name = theme.title or session.name
    context = session.context

    replay: WidgetSessionState | None = None
    if session_id:
        await widget_service.enforce_rate_limits(str(context.chatbot_id), session_id)
        state = await ticket_service.session_state(context.org_id, context.chatbot_id, session_id)
        if state is not None:
            conversation, messages, ticket_status = state
            replay = WidgetSessionState(
                conversation_id=conversation.id,
                messages=[WidgetMessage.model_validate(message) for message in messages],
                ticket_status=ticket_status,
            )

    return WidgetBootstrap(
        chatbot_id=context.chatbot_id,
        name=name,
        greeting=theme.greeting
        or f"Hi! Ask me anything and I'll answer from {session.name}'s documents.",
        status=session.status,
        theme=theme,
        privacy_url=session.privacy_url,
        terms_url=session.terms_url,
        session=replay,
    )


@router.post("/tickets", response_model=TicketCreated, status_code=status.HTTP_201_CREATED)
async def create_ticket(
    payload: TicketCreate, session: WidgetSession, request: Request
) -> TicketCreated:
    """Open a ticket from the widget's contact form.

    Goes through the same public-key + origin allow-list + rate-limit chain as `/chat`, and
    then a second, tighter gate of its own. The shared chain is not enough here: none of the
    public key, the origin or the session id is anything a script cannot present a fresh one
    of, so on their own they shape ordinary traffic rather than stopping deliberate abuse.
    This endpoint is the one worth abusing — it writes a row carrying an address the caller
    chose and up to 4000 characters that a human then reads — so it is also keyed on the
    client address, which a caller cannot simply pick.
    """
    context = session.context
    await widget_service.enforce_rate_limits(str(context.chatbot_id), payload.session_id)
    await widget_service.enforce_ticket_limits(str(context.chatbot_id), client_ip(request))

    ticket, conversation = await ticket_service.create_ticket(
        context.org_id, context.chatbot_id, payload
    )
    return TicketCreated(ticket_id=ticket.id, conversation_id=conversation.id, status=ticket.status)


@router.post("/chat")
async def chat(
    payload: WidgetChatRequest, session: WidgetSession, request: Request
) -> StreamingResponse:
    """Stream one answer over SSE.

    Once the first byte is on the wire the status code is fixed, so failures after that
    point are delivered as an `error` event and the stream is closed cleanly.
    """
    context = session.context
    await widget_service.enforce_rate_limits(str(context.chatbot_id), payload.session_id)

    async def event_stream() -> AsyncIterator[str]:
        try:
            async for event in stream_answer(
                context, question=payload.message, external_session_id=payload.session_id
            ):
                if await request.is_disconnected():
                    logger.info("widget.client_disconnected", chatbot_id=str(context.chatbot_id))
                    return
                yield _sse(event["event"], event["data"])
        except DomainError as exc:
            yield _sse("error", {"code": exc.code, "message": exc.message})
        except Exception as exc:
            logger.exception("widget.chat_failed", error=str(exc))
            yield _sse(
                "error",
                {
                    "code": UpstreamServiceError.code,
                    "message": "The assistant is unavailable right now.",
                },
            )

    # `Access-Control-Allow-Origin` is left to the widget CORS middleware, which echoes the
    # origin the browser actually sent. That is the frame's, not the tenant site's — the site
    # is what authorised this request, not what is fetching it.
    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=_SSE_HEADERS)
