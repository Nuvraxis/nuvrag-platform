from uuid import UUID

from fastapi import APIRouter, File, Query, UploadFile, status

from app.api.deps import CurrentPrincipal, OwnedChatbot, Pagination, RequireAdmin
from app.models import DocumentStatus
from app.schemas.common import Page
from app.schemas.document import DocumentRead, DocumentUploadResponse
from app.services import document as document_service

router = APIRouter(prefix="/chatbots/{chatbot_id}/documents", tags=["documents"])


@router.post(
    "",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload a document for ingestion",
)
async def upload_document(
    chatbot: OwnedChatbot,
    principal: CurrentPrincipal,
    file: UploadFile = File(..., description="PDF, DOCX, Markdown or plain text"),
) -> DocumentUploadResponse:
    """Accepted immediately; parsing and embedding happen on the ingestion worker.

    Answers 429 when the chatbot has spent its monthly ingestion allowance, with the current
    total and the ceiling in `details` so the dashboard can say which it is.
    """
    outcome = await document_service.upload_document(
        org_id=principal.org_id,
        chatbot_id=chatbot.id,
        uploaded_by=principal.user.id,
        upload=file,
        cap_units=chatbot.monthly_ingestion_unit_cap,
    )
    return DocumentUploadResponse(
        document=DocumentRead.model_validate(outcome.document), task_id=outcome.task_id
    )


@router.get("", response_model=Page[DocumentRead])
async def list_documents(
    chatbot: OwnedChatbot,
    principal: CurrentPrincipal,
    page: Pagination,
    status_filter: DocumentStatus | None = Query(default=None, alias="status"),
) -> Page[DocumentRead]:
    items, total = await document_service.list_documents(
        principal.org_id,
        chatbot.id,
        status=status_filter,
        limit=page.limit,
        offset=page.offset,
    )
    return Page(
        items=[DocumentRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{document_id}", response_model=DocumentRead)
async def get_document(
    chatbot: OwnedChatbot, principal: CurrentPrincipal, document_id: UUID
) -> DocumentRead:
    document = await document_service.get_document(principal.org_id, chatbot.id, document_id)
    return DocumentRead.model_validate(document)


@router.post("/{document_id}/reprocess", status_code=status.HTTP_202_ACCEPTED)
async def reprocess_document(
    chatbot: OwnedChatbot, principal: RequireAdmin, document_id: UUID
) -> dict[str, str | None]:
    task_id = await document_service.reprocess_document(principal.org_id, chatbot.id, document_id)
    return {"document_id": str(document_id), "task_id": task_id}


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    chatbot: OwnedChatbot, principal: RequireAdmin, document_id: UUID
) -> None:
    await document_service.delete_document(principal.org_id, chatbot.id, document_id)
