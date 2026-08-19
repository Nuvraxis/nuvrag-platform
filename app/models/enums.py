from enum import StrEnum


class Plan(StrEnum):
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class UserRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"

    @property
    def rank(self) -> int:
        return _ROLE_RANK[self]

    def can_act_as(self, required: UserRole) -> bool:
        return self.rank >= required.rank


_ROLE_RANK = {UserRole.MEMBER: 0, UserRole.ADMIN: 1, UserRole.OWNER: 2}


class InvitationStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REVOKED = "revoked"


class ChatbotStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class DocumentStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class FileType(StrEnum):
    PDF = "pdf"
    DOCX = "docx"
    MD = "md"
    MDX = "mdx"
    TXT = "txt"


class MessageRole(StrEnum):
    # `staff` is a human reply written from the dashboard after a conversation was escalated.
    # It shares the transcript with the AI turns rather than living in its own table, so
    # history, citations and the transcript UI all keep working unchanged.
    USER = "user"
    ASSISTANT = "assistant"
    STAFF = "staff"


class TicketStatus(StrEnum):
    """`open` = new and unclaimed. `pending` = assigned, or a staff member has replied at
    least once. `resolved` = done, with `resolved_at` set. `closed` = archived terminal
    state. Reopening from either terminal state clears `resolved_at`."""

    OPEN = "open"
    PENDING = "pending"
    RESOLVED = "resolved"
    CLOSED = "closed"


class TicketPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class TicketSource(StrEnum):
    """How the visitor got here: offered the option after a grounding miss, or they asked."""

    AI_ESCALATION = "ai_escalation"
    VISITOR_CONTACT_FORM = "visitor_contact_form"


# The `Name` suffix keeps these clear of the `ChatProvider` / `EmbeddingProvider` protocols in
# app/services/ai/base.py: these are the values a column holds, those are the things that
# actually make the calls.
class ChatProviderName(StrEnum):
    AZURE = "azure"
    BEDROCK = "bedrock"
    ANTHROPIC = "anthropic"
    OLLAMA = "ollama"


class EmbeddingProviderName(StrEnum):
    """Anthropic is absent on purpose — it publishes no embeddings API.

    Its omission here is what the API's 422, the database check constraint and the factory's
    dispatch all derive from, so there is one place to change if that ever stops being true.
    """

    AZURE = "azure"
    BEDROCK = "bedrock"
    OLLAMA = "ollama"
