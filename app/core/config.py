from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, PostgresDsn, RedisDsn, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Environment = Literal["local", "staging", "production"]
StorageBackend = Literal["local", "azure_blob", "s3"]


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DB_", env_file=".env", extra="ignore")

    dsn: PostgresDsn = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/rag_db",
        validation_alias="DB_CONNECTION_STRING",
    )
    read_replica_dsn: PostgresDsn | None = None
    # Table-owner role used for pre-tenant operations (login lookup, signup) and migrations.
    # Leave unset in local dev, where the application already owns its tables.
    privileged_dsn: PostgresDsn | None = None
    pool_size: int = 10
    max_overflow: int = 5
    pool_recycle_seconds: int = 1800
    pool_pre_ping: bool = True
    pgbouncer_transaction_mode: bool = False
    echo: bool = False
    statement_timeout_ms: int = 15_000

    @field_validator("dsn", "read_replica_dsn", mode="before")
    @classmethod
    def normalise_driver(cls, value: object) -> object:
        """Accept bare `asyncpg://` or `postgres://` and coerce to SQLAlchemy's URL form."""
        if not isinstance(value, str) or not value:
            return value
        for prefix, replacement in (
            ("asyncpg://", "postgresql+asyncpg://"),
            ("postgres://", "postgresql+asyncpg://"),
        ):
            if value.startswith(prefix):
                return replacement + value[len(prefix) :]
        if value.startswith("postgresql://"):
            return "postgresql+asyncpg://" + value[len("postgresql://") :]
        return value

    @property
    def sync_dsn(self) -> str:
        """Alembic and other sync tooling need psycopg-style URLs."""
        return str(self.dsn).replace("+asyncpg", "")


class RedisSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="REDIS_", env_file=".env", extra="ignore")

    url: RedisDsn = "redis://localhost:6379/0"
    broker_url: RedisDsn | None = None
    result_backend_url: RedisDsn | None = None
    chatbot_cache_ttl_seconds: int = 60
    max_connections: int = 50

    @property
    def broker(self) -> str:
        return str(self.broker_url or self.url)

    @property
    def result_backend(self) -> str:
        return str(self.result_backend_url or self.url)


class SecuritySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SECURITY_", env_file=".env", extra="ignore")

    jwt_secret: str = "insecure-development-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_ttl_seconds: int = 900
    refresh_token_ttl_seconds: int = 60 * 60 * 24 * 14
    # `NoDecode` stops pydantic-settings from JSON-parsing the raw value at the source layer,
    # which would raise before the validator below ever runs. Without it, the natural
    # `A,B` form in a .env file fails outright instead of being split.
    dashboard_cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]
    password_min_length: int = 10
    invitation_ttl_seconds: int = 60 * 60 * 24 * 7
    # Refresh tokens are stateless, so revocation is a Redis deny-list keyed by `jti`. Each
    # entry expires with the token it revokes, which bounds the list by the refresh TTL
    # rather than letting it grow forever.
    revocation_key_prefix: str = "auth:revoked:"
    # Which header carries the real client address. Cloudflare overwrites `CF-Connecting-IP`
    # on every proxied request, so unlike `X-Forwarded-For` a value the caller supplies is
    # discarded rather than appended to. Behind a different proxy, name that proxy's
    # equivalent; set it empty to use the socket address instead. See app/core/client_ip.py
    # for the assumption this rests on — the origin must not be reachable around the proxy.
    client_ip_header: str = "cf-connecting-ip"

    @field_validator("dashboard_cors_origins", mode="before")
    @classmethod
    def split_origins(cls, value: object) -> object:
        """Accept either a comma-separated list or a JSON array."""
        if not isinstance(value, str):
            return value
        candidate = value.strip()
        if candidate.startswith("["):
            import json

            return json.loads(candidate)
        return [item.strip() for item in candidate.split(",") if item.strip()]


class AISettings(BaseSettings):
    """Operational settings shared by every AI provider.

    *Which* provider a chatbot talks to, and the credentials for it, are a per-chatbot row in
    `chatbot_ai_config` rather than deployment configuration — one deployment serves tenants
    on Azure, Bedrock, Anthropic and Ollama at once. What is left here is the handful of knobs
    that belong to the process rather than to a tenant.
    """

    model_config = SettingsConfigDict(env_prefix="AI_", env_file=".env", extra="ignore")

    # Encrypts the credentials tenants type into the dashboard. Deliberately without a working
    # default: a development fallback here would mean a deployment that silently protects
    # other people's API keys with a value published in this repository.
    credentials_encryption_key: str = Field(default="", validate_default=True)

    embedding_batch_size: int = 100
    request_timeout_seconds: int = 60
    max_retries: int = 3
    # A connection test calls someone else's API from inside a request handler, so it gets a
    # shorter leash than ingestion does.
    test_timeout_seconds: int = 20

    @field_validator("credentials_encryption_key")
    @classmethod
    def check_fernet_key(cls, value: str) -> str:
        from cryptography.fernet import Fernet

        try:
            Fernet(value.encode())
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "AI_CREDENTIALS_ENCRYPTION_KEY must be a url-safe base64-encoded 32-byte key. "
                'Generate one with: python -c "from cryptography.fernet import Fernet; '
                'print(Fernet.generate_key().decode())"'
            ) from exc
        return value


class StorageSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STORAGE_", env_file=".env", extra="ignore")

    backend: StorageBackend = "local"
    container: str = "rag-documents"
    local_root: str = "./var/uploads"

    azure_connection_string: str | None = None
    azure_account_url: str | None = None

    s3_endpoint_url: str | None = None
    s3_region: str = "us-east-1"
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None


class IngestionSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="INGESTION_", env_file=".env", extra="ignore")

    max_upload_bytes: int = 25 * 1024 * 1024
    upload_stream_chunk_bytes: int = 1024 * 1024
    chunk_size_tokens: int = 700
    chunk_overlap_tokens: int = 90
    max_chunks_per_document: int = 20_000
    max_task_retries: int = 4
    retry_backoff_seconds: int = 20
    retry_backoff_max_seconds: int = 600
    # Malware scanning is opt-in by host. When a host is set the scan is mandatory: a
    # scanner that cannot be reached fails the job rather than letting the file through.
    clamav_host: str | None = None
    clamav_port: int = 3310
    clamav_timeout_seconds: float = 30.0
    clamav_chunk_bytes: int = 64 * 1024


class RetrievalSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RETRIEVAL_", env_file=".env", extra="ignore")

    top_k: int = 5
    min_similarity: float = 0.25
    history_window_messages: int = 8
    max_context_characters: int = 12_000
    hnsw_ef_search: int = 80


class RetentionSettings(BaseSettings):
    """When the conversation sweep runs, and how hard it is allowed to push.

    *How long* a transcript is kept is deliberately not here: it is `chatbot.retention_days`,
    a per-chatbot column, because the obligation belongs to the tenant whose visitors are in
    the transcript rather than to whoever operates the cluster. One deployment therefore
    serves a tenant purging after 30 days and one keeping everything, at the same time.
    """

    model_config = SettingsConfigDict(env_prefix="RETENTION_", env_file=".env", extra="ignore")

    enabled: bool = True
    # Local midnight somewhere is business hours somewhere else, so the schedule is UTC and
    # says so in the name. Off-peak by default: the sweep competes with ingestion for the
    # same worker pool.
    purge_hour_utc: int = Field(default=3, ge=0, le=23)
    purge_minute_utc: int = Field(default=30, ge=0, le=59)
    # One statement deletes at most this many conversations. Bounds the transaction, and with
    # it how long a lock is held on rows the chat path may be writing to.
    purge_batch_size: int = Field(default=500, ge=1, le=10_000)
    # A ceiling per chatbot per run, so one tenant's enormous backlog cannot starve every
    # other tenant's sweep. What is left is picked up by the next run.
    purge_max_batches_per_chatbot: int = Field(default=40, ge=1)
    # Beat can fire again while the previous sweep is still going. The lock makes the second
    # run a no-op rather than a second pass over rows the first is already deleting.
    lock_key: str = "maintenance:purge-conversations"
    lock_ttl_seconds: int = Field(default=3600, ge=60)


class NuvragMemSettings(BaseSettings):
    """Per-visitor memory: what is extracted, what is retrieved, and when it is swept.

    *How long* an entry is kept is not here, for the same reason retention's duration is not:
    it is `chatbot.nuvrag_mem_retention_days`, per tenant, because the obligation belongs to
    whoever's visitors are being remembered rather than to whoever runs the cluster.
    """

    model_config = SettingsConfigDict(env_prefix="NUVRAG_MEM_", env_file=".env", extra="ignore")

    # Off would mean no extraction and no retrieval; the tables and columns still exist, so
    # turning it back on loses nothing already written.
    enabled: bool = True

    # --- read path ---
    # Deliberately smaller than `RETRIEVAL_TOP_K`. Memory is a handful of sentences about one
    # person, not a corpus, and a large k here mostly buys weakly-related facts crowding the
    # prompt next to the documents that actually answer the question.
    retrieval_top_k: int = Field(default=5, ge=1, le=50)
    # Higher than document retrieval's 0.25 floor, because the cost of a wrong hit is worse:
    # an irrelevant passage is ignorable, whereas an irrelevant "fact about you" is the model
    # confidently telling a visitor something untrue about themselves.
    retrieval_min_similarity: float = Field(default=0.45, ge=0.0, le=1.0)

    # --- write path ---
    # How many recent turns the extractor is shown. Enough for a preference stated across two
    # or three messages, short enough that the call stays cheap on every assistant turn.
    extraction_window_messages: int = Field(default=6, ge=2, le=40)
    # A ceiling on what one turn may produce, so a model that decides to enumerate cannot
    # write forty rows about a single exchange.
    max_entries_per_extraction: int = Field(default=3, ge=1, le=20)
    # Above this cosine similarity to an entry the subject already has, the new one is a
    # restatement and is dropped. A preference mentioned five times should be one row.
    dedupe_similarity: float = Field(default=0.92, ge=0.0, le=1.0)
    # A hard ceiling per visitor per chatbot. Without one, a talkative regular accumulates
    # rows forever and their retrieval slowly degrades into a lucky dip.
    max_entries_per_subject: int = Field(default=200, ge=1)

    # --- sweep ---
    # Shares beat with the conversation sweep and the same off-peak hour, but never its lock:
    # one key for two different sweeps would let whichever ran first silently skip the other.
    purge_hour_utc: int = Field(default=3, ge=0, le=23)
    purge_minute_utc: int = Field(default=45, ge=0, le=59)
    purge_batch_size: int = Field(default=500, ge=1, le=10_000)
    purge_max_batches_per_chatbot: int = Field(default=40, ge=1)
    lock_key: str = "maintenance:purge-nuvrag-mem"
    lock_ttl_seconds: int = Field(default=3600, ge=60)


class UsageCapSettings(BaseSettings):
    """What happens when the counters cannot be read, and nothing else.

    *How much* a chatbot may spend is per chatbot — `monthly_ingestion_unit_cap` and
    `monthly_retrieval_call_cap` — for the same reason retention's duration is: the budget
    belongs to whoever runs the providers for that bot. What is here is the one judgement an
    operator might reasonably want to make differently.
    """

    model_config = SettingsConfigDict(env_prefix="USAGE_CAP_", env_file=".env", extra="ignore")

    # Fail open, matching the rate limiter. If Postgres cannot be reached the cap status is
    # unknown, and a transient blip silencing every widget on the platform is worse than a
    # bounded amount of uncounted spend during it — bounded because the outage that hid the
    # counters is also stopping most of the work. An operator who would rather stop spending
    # than keep answering flips this, and both enforcement points honour it identically.
    fail_closed: bool = False


class RateLimitSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RATE_LIMIT_", env_file=".env", extra="ignore")

    enabled: bool = True
    chatbot_capacity: int = 120
    chatbot_refill_per_second: float = 2.0
    session_capacity: int = 20
    session_refill_per_second: float = 0.25

    # Opening a ticket gets its own, far tighter buckets, for two reasons. It is rare — a
    # visitor asks for a human once, not once a minute — so a limit that would strangle chat
    # is generous here. And it is the expensive one to abuse: each call writes a row carrying
    # an address the caller chose and up to 4000 characters that a human then reads.
    #
    # Keyed on the client address rather than the session id, which the caller generates and
    # can rotate freely. Roughly five an hour from one address, per chatbot.
    ticket_ip_capacity: int = 3
    ticket_ip_refill_per_second: float = 0.0014
    # A second bucket for the whole chatbot, so a botnet rotating addresses still cannot bury
    # one tenant's queue. Roughly 36 an hour, which is a busy support desk.
    ticket_chatbot_capacity: int = 30
    ticket_chatbot_refill_per_second: float = 0.01


class ObservabilitySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OTEL_", env_file=".env", extra="ignore")

    service_name: str = "rag-api"
    tracing_enabled: bool = False
    exporter_otlp_endpoint: str | None = None
    metrics_enabled: bool = True
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: Environment = "local"
    project_name: str = "RAG Chatbot Platform"
    api_v1_prefix: str = "/api/v1"
    docs_enabled: bool = True
    # Where the widget bundle is served from; used to generate tenant embed snippets.
    widget_cdn_base_url: str = "http://localhost:8080/widget"
    # Where the dashboard is served from; used to build invitation links.
    dashboard_base_url: str = "http://localhost:3000"

    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    ai: AISettings = Field(default_factory=AISettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    ingestion: IngestionSettings = Field(default_factory=IngestionSettings)
    retrieval: RetrievalSettings = Field(default_factory=RetrievalSettings)
    retention: RetentionSettings = Field(default_factory=RetentionSettings)
    nuvrag_mem: NuvragMemSettings = Field(default_factory=NuvragMemSettings)
    usage_cap: UsageCapSettings = Field(default_factory=UsageCapSettings)
    rate_limit: RateLimitSettings = Field(default_factory=RateLimitSettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
