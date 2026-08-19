"""End-to-end API tests against a live Postgres (with pgvector) and Redis.

They target whatever `DB_CONNECTION_STRING` and `REDIS_URL` point at — by default the values
in .env. Bring the stack up with
`docker compose -f infra/docker/docker-compose.yml up -d postgres redis` and run
`alembic upgrade head` first. The module skips itself when either service is unreachable, so
a developer without infrastructure still gets a clean run.
"""

import asyncio
import json
import math
import os
import uuid
import zlib

import pytest
from app.db.session import check_database_health, dispose_engines
from app.main import create_app
from app.services.redis_client import check_redis_health, close_redis
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import HumanMessage

TENANT_ORIGIN = "https://tenant.example.com"


def _infrastructure_available() -> bool:
    async def probe() -> bool:
        try:
            return await check_database_health() and await check_redis_health()
        finally:
            await dispose_engines()
            await close_redis()

    return asyncio.run(probe())


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _infrastructure_available(),
        reason="Postgres and/or Redis unreachable; check DB_CONNECTION_STRING and REDIS_URL",
    ),
]


@pytest.fixture
async def client():
    # Engines and the Redis pool are process-level singletons holding connections bound to
    # the loop that opened them, and each test runs on a fresh loop. Resetting either side
    # of the test keeps those pools from being reused across loops.
    await dispose_engines()
    await close_redis()

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http:
        yield http

    await dispose_engines()
    await close_redis()


async def _signup(client: AsyncClient) -> tuple[str, str]:
    suffix = uuid.uuid4().hex[:10]
    response = await client.post(
        "/api/v1/auth/signup",
        json={
            "organization_name": f"Acme {suffix}",
            "email": f"owner-{suffix}@example.com",
            "password": "a-sufficiently-long-password",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return body["tokens"]["access_token"], body["organization"]["id"]


async def _create_chatbot(client: AsyncClient, token: str, name: str = "Support Bot") -> dict:
    response = await client.post(
        "/api/v1/chatbots",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": name,
            "system_prompt": "You are Acme support.",
            "allowed_origins": [TENANT_ORIGIN],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


OLLAMA_URL = os.environ.get("RAG_TEST_OLLAMA_URL", "http://localhost:11434")


def _ai_payload(
    *,
    chat_provider: str = "ollama",
    chat_model: str = "a-chat-model",
    embedding_provider: str = "ollama",
    embedding_model: str = "an-embedding-model",
) -> dict:
    """Ollama by default: it is the one provider that needs no credential to be well formed."""

    def connection(provider: str) -> dict:
        # A fresh dict per half. Sharing one lets a caller tweaking `chat.connection.think`
        # put `think` on the embedding connection too, where the schema rightly refuses it.
        if provider == "ollama":
            return {"base_url": OLLAMA_URL}
        return {"endpoint": "https://example.openai.azure.com", "region": "eu-central-1"}

    credentials = {"api_key": "test-key"}
    return {
        "chat": {
            "provider": chat_provider,
            "model": chat_model,
            "connection": connection(chat_provider),
            "credentials": None if chat_provider == "ollama" else credentials,
        },
        "embedding": {
            "provider": embedding_provider,
            "model": embedding_model,
            "connection": connection(embedding_provider),
            "credentials": None if embedding_provider == "ollama" else credentials,
        },
    }


async def _configure_ai(client: AsyncClient, token: str, chatbot_id: str, **kwargs) -> dict:
    response = await client.put(
        f"/api/v1/chatbots/{chatbot_id}/ai-config",
        headers={"Authorization": f"Bearer {token}"},
        json=_ai_payload(**kwargs),
    )
    assert response.status_code == 200, response.text
    return response.json()


class TestHealth:
    async def test_liveness_needs_no_dependencies(self, client):
        assert (await client.get("/health/live")).status_code == 200

    async def test_readiness_reports_dependencies(self, client):
        response = await client.get("/health/ready")
        assert response.status_code == 200, response.text
        assert response.json()["components"] == {"database": True, "redis": True}


class TestAuth:
    async def test_signup_then_login(self, client):
        suffix = uuid.uuid4().hex[:10]
        email = f"owner-{suffix}@example.com"
        signup = await client.post(
            "/api/v1/auth/signup",
            json={
                "organization_name": f"Acme {suffix}",
                "email": email,
                "password": "a-sufficiently-long-password",
            },
        )
        assert signup.status_code == 201, signup.text
        assert signup.json()["user"]["role"] == "owner"

        login = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "a-sufficiently-long-password"},
        )
        assert login.status_code == 200, login.text
        assert login.json()["token_type"] == "bearer"

    async def test_duplicate_email_conflicts(self, client):
        suffix = uuid.uuid4().hex[:10]
        payload = {
            "organization_name": "Acme",
            "email": f"dupe-{suffix}@example.com",
            "password": "a-sufficiently-long-password",
        }
        assert (await client.post("/api/v1/auth/signup", json=payload)).status_code == 201
        second = await client.post("/api/v1/auth/signup", json=payload)
        assert second.status_code == 409
        assert second.json()["error"]["code"] == "conflict"

    async def test_wrong_password_is_rejected(self, client):
        suffix = uuid.uuid4().hex[:10]
        email = f"pw-{suffix}@example.com"
        await client.post(
            "/api/v1/auth/signup",
            json={
                "organization_name": "Acme",
                "email": email,
                "password": "a-sufficiently-long-password",
            },
        )
        response = await client.post(
            "/api/v1/auth/login", json={"email": email, "password": "not-the-password"}
        )
        assert response.status_code == 401

    async def test_unauthenticated_request_is_rejected(self, client):
        assert (await client.get("/api/v1/chatbots")).status_code == 401

    async def test_short_password_returns_422_not_500(self, client):
        """A custom field validator puts the raw ValueError in Pydantic's `ctx`, which is not
        JSON-serializable — serialising it verbatim turned this into a 500."""
        response = await client.post(
            "/api/v1/auth/signup",
            json={
                "organization_name": "Acme",
                "email": f"short-{uuid.uuid4().hex[:8]}@example.com",
                "password": "Test@123!",
            },
        )
        assert response.status_code == 422, response.text

        body = response.json()
        assert body["error"]["code"] == "validation_error"
        errors = body["error"]["details"]["errors"]
        assert errors[0]["field"] == "password"
        assert "at least" in errors[0]["message"]

    async def test_validation_error_never_echoes_the_submitted_password(self, client):
        secret = "Test@123!"
        response = await client.post(
            "/api/v1/auth/signup",
            json={
                "organization_name": "Acme",
                "email": f"leak-{uuid.uuid4().hex[:8]}@example.com",
                "password": secret,
            },
        )
        assert response.status_code == 422
        assert secret not in response.text

    async def test_missing_field_reports_the_field_name(self, client):
        response = await client.post("/api/v1/auth/signup", json={"email": "a@b.com"})
        assert response.status_code == 422
        fields = {e["field"] for e in response.json()["error"]["details"]["errors"]}
        assert {"organization_name", "password"} <= fields

    async def test_refresh_token_cannot_be_used_as_access_token(self, client):
        suffix = uuid.uuid4().hex[:10]
        signup = await client.post(
            "/api/v1/auth/signup",
            json={
                "organization_name": "Acme",
                "email": f"rt-{suffix}@example.com",
                "password": "a-sufficiently-long-password",
            },
        )
        refresh_token = signup.json()["tokens"]["refresh_token"]
        response = await client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {refresh_token}"}
        )
        assert response.status_code == 401


class TestChatbotLifecycle:
    async def test_create_read_update(self, client):
        token, org_id = await _signup(client)
        created = await _create_chatbot(client, token)

        assert created["secret"]["secret_key"].startswith("sk_")
        chatbot = created["chatbot"]
        assert chatbot["public_key"].startswith("pk_")
        assert chatbot["org_id"] == org_id

        headers = {"Authorization": f"Bearer {token}"}
        fetched = await client.get(f"/api/v1/chatbots/{chatbot['id']}", headers=headers)
        assert fetched.status_code == 200
        # The secret is returned exactly once, at creation.
        assert "secret_key" not in fetched.json()

        updated = await client.patch(
            f"/api/v1/chatbots/{chatbot['id']}",
            headers=headers,
            json={"name": "Renamed Bot"},
        )
        assert updated.status_code == 200
        assert updated.json()["name"] == "Renamed Bot"
        # Renaming leaves the slug alone: it is an identifier others may already reference.
        assert updated.json()["slug"] == chatbot["slug"]


class TestWorkerRuntime:
    """Celery tasks are synchronous and were each calling `asyncio.run()`.

    That gave every task a fresh event loop while the SQLAlchemy engine and its asyncpg
    connections stayed cached at module level, so from the second task onward a worker was
    reusing connections bound to a closed loop.
    """

    def test_repeated_calls_reuse_pooled_connections(self, client):
        import asyncio

        from app.db.session import system_session
        from app.worker.runtime import run, shutdown
        from sqlalchemy import text

        async def query() -> int:
            async with system_session() as session:
                return (await session.execute(text("select 1"))).scalar_one()

        try:
            # Three sequential calls stand in for three tasks landing in the same worker.
            assert [run(query()), run(query()), run(query())] == [1, 1, 1]
        finally:
            shutdown()

        # The API fixture owns its own loop, so the worker loop must not leave the shared
        # engine singletons pointing at a loop it already closed.
        asyncio.run(_reset_shared_state())

    def test_shutdown_is_safe_to_call_twice(self, client):
        from app.worker.runtime import shutdown

        shutdown()
        shutdown()


async def _reset_shared_state() -> None:
    from app.db.session import dispose_engines
    from app.services.redis_client import close_redis

    await dispose_engines()
    await close_redis()


class TestSlugGeneration:
    async def test_slug_is_derived_from_the_name(self, client):
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token, name="Acme Support Bot"))["chatbot"]
        assert chatbot["slug"] == "acme-support-bot"

    async def test_slug_in_the_payload_is_ignored(self, client):
        token, _ = await _signup(client)
        response = await client.post(
            "/api/v1/chatbots",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "name": "Billing Helper",
                "slug": "attacker-chosen-slug",
                "allowed_origins": [TENANT_ORIGIN],
            },
        )
        assert response.status_code == 201, response.text
        assert response.json()["chatbot"]["slug"] == "billing-helper"

    async def test_duplicate_names_get_distinct_slugs(self, client):
        token, _ = await _signup(client)
        first = (await _create_chatbot(client, token, name="Support"))["chatbot"]
        second = (await _create_chatbot(client, token, name="Support"))["chatbot"]
        third = (await _create_chatbot(client, token, name="Support"))["chatbot"]

        assert [first["slug"], second["slug"], third["slug"]] == [
            "support",
            "support-2",
            "support-3",
        ]

    async def test_slugs_do_not_collide_across_organisations(self, client):
        token_a, _ = await _signup(client)
        token_b, _ = await _signup(client)

        a = (await _create_chatbot(client, token_a, name="Support"))["chatbot"]
        b = (await _create_chatbot(client, token_b, name="Support"))["chatbot"]

        # Uniqueness is scoped per organisation, so both tenants keep the clean slug.
        assert a["slug"] == b["slug"] == "support"

    async def test_name_without_usable_characters_falls_back(self, client):
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token, name="!!! ???"))["chatbot"]
        assert chatbot["slug"] == "chatbot"

    async def test_accented_name_is_transliterated(self, client):
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token, name="Café Wörld"))["chatbot"]
        assert chatbot["slug"] == "cafe-world"

    async def test_embed_snippet_contains_the_public_key(self, client):
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]
        response = await client.get(
            f"/api/v1/chatbots/{chatbot['id']}/embed-snippet",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert chatbot["public_key"] in response.json()["snippet"]


class TestTenantIsolation:
    async def test_another_org_cannot_read_a_chatbot(self, client):
        token_a, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token_a))["chatbot"]

        token_b, _ = await _signup(client)
        response = await client.get(
            f"/api/v1/chatbots/{chatbot['id']}",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert response.status_code == 404

    async def test_another_org_cannot_list_a_chatbot(self, client):
        token_a, _ = await _signup(client)
        await _create_chatbot(client, token_a)

        token_b, _ = await _signup(client)
        listing = await client.get(
            "/api/v1/chatbots", headers={"Authorization": f"Bearer {token_b}"}
        )
        assert listing.status_code == 200
        assert listing.json()["items"] == []

    async def test_another_org_cannot_delete_a_chatbot(self, client):
        token_a, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token_a))["chatbot"]

        token_b, _ = await _signup(client)
        response = await client.delete(
            f"/api/v1/chatbots/{chatbot['id']}",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert response.status_code == 404


class TestDocumentUpload:
    async def test_upload_is_accepted_and_queued(self, client):
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]
        await _configure_ai(client, token, chatbot["id"])

        response = await client.post(
            f"/api/v1/chatbots/{chatbot['id']}/documents",
            headers={"Authorization": f"Bearer {token}"},
            files={
                "file": ("handbook.md", b"# Refunds\n\nRefunds within 30 days.", "text/markdown")
            },
        )
        assert response.status_code == 202, response.text
        document = response.json()["document"]
        assert document["status"] == "pending"
        assert document["file_type"] == "md"
        assert document["size_bytes"] > 0

    async def test_disallowed_extension_is_refused(self, client):
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]

        response = await client.post(
            f"/api/v1/chatbots/{chatbot['id']}/documents",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("payload.exe", b"MZ\x90\x00", "application/octet-stream")},
        )
        assert response.status_code == 415

    async def test_pdf_magic_bytes_are_enforced(self, client):
        # Magic bytes are read as the file streams, which is past the point where the chatbot
        # needs a provider it can embed with.
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]
        await _configure_ai(client, token, chatbot["id"])

        response = await client.post(
            f"/api/v1/chatbots/{chatbot['id']}/documents",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("fake.pdf", b"<html>not a pdf</html>", "application/pdf")},
        )
        assert response.status_code == 415


class TestAIProviderConfig:
    async def test_a_new_chatbot_has_none(self, client):
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]

        response = await client.get(
            f"/api/v1/chatbots/{chatbot['id']}/ai-config",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 404

    async def test_upload_is_refused_until_a_provider_is_configured(self, client):
        """Failing here rather than in the worker: an accepted upload that cannot be embedded
        costs the tenant the transfer and reports itself minutes later."""
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]

        response = await client.post(
            f"/api/v1/chatbots/{chatbot['id']}/documents",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("notes.md", b"# Notes\n\nSomething useful.", "text/markdown")},
        )
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "ai_provider_not_configured"

    async def test_an_impossible_extension_is_reported_before_the_provider_is(self, client):
        """The cheap local judgement comes first, so an unusable file gets the reason it is
        unusable rather than a configuration lecture. Only the checks that need the file's
        contents — magic bytes — happen after the guard, because those need the stream."""
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]

        response = await client.post(
            f"/api/v1/chatbots/{chatbot['id']}/documents",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("payload.exe", b"MZ\x90\x00", "application/octet-stream")},
        )
        assert response.status_code == 415

    async def test_saving_then_reading_never_returns_a_credential(self, client):
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]
        saved = await _configure_ai(client, token, chatbot["id"], chat_provider="azure")

        assert saved["chat"]["credentials_set"] is True
        assert saved["chat"]["ready"] is True
        assert "test-key" not in str(saved)

        fetched = await client.get(
            f"/api/v1/chatbots/{chatbot['id']}/ai-config",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert fetched.status_code == 200
        assert "test-key" not in fetched.text
        assert fetched.json()["chat"]["provider"] == "azure"
        assert fetched.json()["embedding_dimension"] is None

    async def test_an_omitted_credential_keeps_the_stored_one(self, client):
        """A key that cannot be read back must not have to be re-typed to fix a model name."""
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]
        await _configure_ai(client, token, chatbot["id"], chat_provider="azure")

        payload = _ai_payload(chat_provider="azure", chat_model="gpt-4.1")
        payload["chat"]["credentials"] = None
        updated = await client.put(
            f"/api/v1/chatbots/{chatbot['id']}/ai-config",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["chat"]["model"] == "gpt-4.1"
        assert updated.json()["chat"]["credentials_set"] is True

    async def test_an_empty_credential_object_clears_the_stored_one(self, client):
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]
        await _configure_ai(client, token, chatbot["id"], chat_provider="azure")

        payload = _ai_payload(chat_provider="azure")
        payload["chat"]["credentials"] = {}
        updated = await client.put(
            f"/api/v1/chatbots/{chatbot['id']}/ai-config",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["chat"]["credentials_set"] is False
        assert updated.json()["chat"]["ready"] is False

    async def test_anthropic_is_refused_as_an_embedding_provider(self, client):
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]

        response = await client.put(
            f"/api/v1/chatbots/{chatbot['id']}/ai-config",
            headers={"Authorization": f"Bearer {token}"},
            json=_ai_payload(embedding_provider="anthropic"),
        )
        assert response.status_code == 422, response.text
        errors = response.json()["error"]["details"]["errors"]
        assert any(error["field"] == "embedding.provider" for error in errors), errors
        assert any("no embeddings API" in error["message"] for error in errors), errors

    async def test_anthropic_can_still_be_the_chat_provider(self, client):
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]

        saved = await _configure_ai(client, token, chatbot["id"], chat_provider="anthropic")
        assert saved["chat"]["provider"] == "anthropic"
        assert saved["embedding"]["provider"] == "ollama"

    async def test_a_provider_missing_its_endpoint_is_refused(self, client):
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]

        payload = _ai_payload(embedding_provider="azure")
        payload["embedding"]["connection"] = {}
        response = await client.put(
            f"/api/v1/chatbots/{chatbot['id']}/ai-config",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )
        assert response.status_code == 422
        assert "endpoint" in response.text

    async def test_a_member_cannot_change_the_providers(self, client):
        owner_token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, owner_token))["chatbot"]
        member = await _join(client, await _invite(client, owner_token, _address()))

        response = await client.put(
            f"/api/v1/chatbots/{chatbot['id']}/ai-config",
            headers={"Authorization": f"Bearer {member['tokens']['access_token']}"},
            json=_ai_payload(),
        )
        assert response.status_code == 403

    async def test_another_org_cannot_read_the_configuration(self, client):
        token_a, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token_a))["chatbot"]
        await _configure_ai(client, token_a, chatbot["id"], chat_provider="azure")

        token_b, _ = await _signup(client)
        response = await client.get(
            f"/api/v1/chatbots/{chatbot['id']}/ai-config",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert response.status_code == 404

    async def test_another_org_cannot_overwrite_the_configuration(self, client):
        """The row carries another tenant's provider credentials; RLS is the second lock."""
        token_a, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token_a))["chatbot"]
        await _configure_ai(client, token_a, chatbot["id"], chat_provider="azure")

        token_b, _ = await _signup(client)
        response = await client.put(
            f"/api/v1/chatbots/{chatbot['id']}/ai-config",
            headers={"Authorization": f"Bearer {token_b}"},
            json=_ai_payload(),
        )
        assert response.status_code == 404

        # And the owner's row is exactly as they left it.
        unchanged = await client.get(
            f"/api/v1/chatbots/{chatbot['id']}/ai-config",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert unchanged.json()["chat"]["provider"] == "azure"

    async def test_a_test_call_reports_a_bad_address_without_quoting_the_provider(self, client):
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]

        response = await client.post(
            f"/api/v1/chatbots/{chatbot['id']}/ai-config/test",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "embedding": {
                    "provider": "ollama",
                    "model": "nomic-embed-text",
                    # Nothing listens here.
                    "connection": {"base_url": "http://127.0.0.1:1"},
                }
            },
        )
        # A provider refusing a tenant is a result this endpoint delivered, not a failure of it.
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["ok"] is False
        assert body["failed"] == "embedding"
        assert body["embedding_dimension"] is None
        # Classified, not guessed — and phrased by us, not by the provider.
        assert body["error"] == "Could not reach the provider at that address."

    async def test_a_test_call_falls_back_to_the_stored_credential(self, client):
        """Omitting credentials means "keep what is saved", the same as on a save — so the
        test exercises what the save would do rather than demanding a re-typed key."""
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]
        await _configure_ai(client, token, chatbot["id"], embedding_provider="azure")

        response = await client.post(
            f"/api/v1/chatbots/{chatbot['id']}/ai-config/test",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "embedding": {
                    "provider": "azure",
                    "model": "text-embedding-3-small",
                    "connection": {"endpoint": "https://example.openai.azure.com"},
                }
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        # The stored key was found and used; the call then failed on the fake endpoint, which
        # is a different verdict from "you gave me nothing to authenticate with".
        assert body["ok"] is False
        assert "No credentials were supplied" not in (body["error"] or "")

    async def test_a_test_call_says_so_when_there_is_no_credential_anywhere(self, client):
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]

        response = await client.post(
            f"/api/v1/chatbots/{chatbot['id']}/ai-config/test",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "chat": {
                    "provider": "anthropic",
                    "model": "claude-sonnet-4-5",
                }
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["ok"] is False
        assert "No credentials were supplied" in response.json()["error"]

    async def test_a_stored_credential_is_not_reused_for_a_different_provider(self, client):
        """A key saved for Azure proves nothing about Bedrock."""
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]
        await _configure_ai(client, token, chatbot["id"], chat_provider="azure")

        response = await client.post(
            f"/api/v1/chatbots/{chatbot['id']}/ai-config/test",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "chat": {
                    "provider": "anthropic",
                    "model": "claude-sonnet-4-5",
                }
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["ok"] is False
        assert "No credentials were supplied" in response.json()["error"]

    async def test_a_test_call_must_name_something_to_test(self, client):
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]

        response = await client.post(
            f"/api/v1/chatbots/{chatbot['id']}/ai-config/test",
            headers={"Authorization": f"Bearer {token}"},
            json={},
        )
        assert response.status_code == 422


class TestWidgetSurface:
    async def test_bootstrap_requires_an_allowed_origin(self, client):
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]

        allowed = await client.get(
            "/public/widget/bootstrap",
            headers=_widget_headers(chatbot["public_key"]),
        )
        assert allowed.status_code == 200, allowed.text
        assert allowed.headers["access-control-allow-origin"] == TENANT_ORIGIN

        blocked = await client.get(
            "/public/widget/bootstrap",
            headers={
                "X-Chatbot-Key": chatbot["public_key"],
                "Origin": "https://attacker.example.com",
            },
        )
        assert blocked.status_code == 403
        assert blocked.json()["error"]["code"] == "origin_not_allowed"

    async def test_theme_reaches_the_widget_and_can_be_taken_back(self, client):
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]
        headers = {"Authorization": f"Bearer {token}"}
        widget_headers = {"X-Chatbot-Key": chatbot["public_key"], "Origin": TENANT_ORIGIN}

        default = await client.get("/public/widget/bootstrap", headers=widget_headers)
        assert default.status_code == 200
        # Nothing chosen yet, so the widget is told nothing and falls back to its stylesheet.
        assert not any(default.json()["theme"].values()), default.text

        saved = await client.patch(
            f"/api/v1/chatbots/{chatbot['id']}",
            headers=headers,
            json={
                "theme_json": {
                    "accent": "#ff6600",
                    "scheme": "dark",
                    "position": "left",
                    "title": "Ask the shop",
                }
            },
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["theme_json"]["accent"] == "#ff6600"

        themed = (await client.get("/public/widget/bootstrap", headers=widget_headers)).json()
        assert themed["theme"]["accent"] == "#ff6600"
        assert themed["theme"]["scheme"] == "dark"
        assert themed["theme"]["position"] == "left"
        # The header override replaces the chatbot's name for the visitor, not in the API.
        assert themed["name"] == "Ask the shop"

        cleared = await client.patch(
            f"/api/v1/chatbots/{chatbot['id']}", headers=headers, json={"theme_json": {}}
        )
        assert cleared.status_code == 200
        assert cleared.json()["theme_json"] == {}

        reverted = (await client.get("/public/widget/bootstrap", headers=widget_headers)).json()
        assert reverted["theme"]["accent"] is None
        assert reverted["name"] == chatbot["name"]

    async def test_theme_colours_must_be_six_digit_hex(self, client):
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]
        headers = {"Authorization": f"Bearer {token}"}

        for value in ("#fff", "red", "javascript:alert(1)", "#2563eb; content: url(x)"):
            response = await client.patch(
                f"/api/v1/chatbots/{chatbot['id']}",
                headers=headers,
                json={"theme_json": {"accent": value}},
            )
            assert response.status_code == 422, f"{value!r} was accepted"

    async def test_unknown_public_key_is_not_found(self, client):
        response = await client.get(
            "/public/widget/bootstrap",
            headers={"X-Chatbot-Key": "pk_test_nonexistent", "Origin": TENANT_ORIGIN},
        )
        assert response.status_code == 404

    async def test_preflight_is_answered_without_the_chatbot_key(self, client):
        response = await client.request(
            "OPTIONS",
            "/public/widget/chat",
            headers={
                "Origin": TENANT_ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "x-chatbot-key,content-type",
            },
        )
        assert response.status_code == 204
        assert "X-Chatbot-Key" in response.headers["access-control-allow-headers"]

    @pytest.mark.parametrize("status", ["paused", "archived"])
    async def test_an_inactive_chatbot_serves_no_widget_surface_at_all(self, client, status):
        """Every widget entry point, not just chat.

        `chatbot_unavailable` is the specific part: the widget removes itself from the page
        on that code and sits tight on anything else, so a generic `permission_denied` here
        would be indistinguishable from a problem it should wait out.
        """
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]
        headers = {"Authorization": f"Bearer {token}"}

        changed = await client.patch(
            f"/api/v1/chatbots/{chatbot['id']}", headers=headers, json={"status": status}
        )
        assert changed.status_code == 200, changed.text

        widget_headers = _widget_headers(chatbot["public_key"])
        bootstrap = await client.get("/public/widget/bootstrap", headers=widget_headers)
        assert bootstrap.status_code == 403
        assert bootstrap.json()["error"]["code"] == "chatbot_unavailable"

        chat = await client.post(
            "/public/widget/chat",
            headers=widget_headers,
            json={"message": "Anyone there?", "session_id": uuid.uuid4().hex},
        )
        assert chat.status_code == 403
        assert chat.json()["error"]["code"] == "chatbot_unavailable"

        ticket = await client.post(
            "/public/widget/tickets",
            headers=widget_headers,
            json={"email": "visitor@example.com", "session_id": uuid.uuid4().hex},
        )
        assert ticket.status_code == 403
        assert ticket.json()["error"]["code"] == "chatbot_unavailable"

    async def test_reactivating_brings_the_widget_back(self, client):
        """The cache holds the status too, so pausing and resuming must not need a TTL to
        expire before the widget works again."""
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]
        headers = {"Authorization": f"Bearer {token}"}
        widget_headers = _widget_headers(chatbot["public_key"])

        assert (
            await client.get("/public/widget/bootstrap", headers=widget_headers)
        ).status_code == 200

        await client.patch(
            f"/api/v1/chatbots/{chatbot['id']}", headers=headers, json={"status": "paused"}
        )
        assert (
            await client.get("/public/widget/bootstrap", headers=widget_headers)
        ).status_code == 403

        await client.patch(
            f"/api/v1/chatbots/{chatbot['id']}", headers=headers, json={"status": "active"}
        )
        assert (
            await client.get("/public/widget/bootstrap", headers=widget_headers)
        ).status_code == 200


class TestAnalytics:
    async def test_new_chatbot_reports_empty_counters(self, client):
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]

        response = await client.get(
            f"/api/v1/chatbots/{chatbot['id']}/analytics",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200, response.text
        body = response.json()

        assert body["chatbot_id"] == chatbot["id"]
        assert body["conversations"] == 0
        # Every status is present rather than omitted, so the dashboard never has to guess
        # whether a missing key means zero.
        assert body["documents"] == {
            "pending": 0,
            "processing": 0,
            "ready": 0,
            "failed": 0,
            "total": 0,
            "chunks": 0,
        }
        assert body["messages"]["average_latency_ms"] is None

    async def test_uploaded_document_appears_as_pending(self, client):
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]
        await _configure_ai(client, token, chatbot["id"])
        headers = {"Authorization": f"Bearer {token}"}

        await client.post(
            f"/api/v1/chatbots/{chatbot['id']}/documents",
            headers=headers,
            files={"file": ("notes.md", b"# Notes\n\nSomething useful.", "text/markdown")},
        )

        body = (
            await client.get(f"/api/v1/chatbots/{chatbot['id']}/analytics", headers=headers)
        ).json()
        assert body["documents"]["pending"] == 1
        assert body["documents"]["total"] == 1

    async def test_daily_series_covers_the_requested_window(self, client):
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]

        body = (
            await client.get(
                f"/api/v1/chatbots/{chatbot['id']}/analytics?days=7",
                headers={"Authorization": f"Bearer {token}"},
            )
        ).json()

        assert body["window_days"] == 7
        assert len(body["daily"]) == 7
        assert [point["conversations"] for point in body["daily"]] == [0] * 7

    async def test_window_is_capped(self, client):
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]

        response = await client.get(
            f"/api/v1/chatbots/{chatbot['id']}/analytics?days=365",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 422

    async def test_another_org_cannot_read_analytics(self, client):
        token_a, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token_a))["chatbot"]
        token_b, _ = await _signup(client)

        response = await client.get(
            f"/api/v1/chatbots/{chatbot['id']}/analytics",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert response.status_code == 404


async def _invite(client: AsyncClient, token: str, email: str, role: str = "member") -> dict:
    response = await client.post(
        "/api/v1/team/invitations",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": email, "role": role},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _join(client: AsyncClient, invitation: dict) -> dict:
    response = await client.post(
        "/api/v1/auth/invitations/accept",
        json={"token": invitation["token"], "password": "another-long-password"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _address() -> str:
    return f"invitee-{uuid.uuid4().hex[:10]}@example.com"


class TestTeamMembers:
    async def test_founder_is_the_only_member_and_is_an_owner(self, client):
        token, _ = await _signup(client)
        body = (
            await client.get("/api/v1/team/members", headers={"Authorization": f"Bearer {token}"})
        ).json()

        assert len(body["members"]) == 1
        assert body["members"][0]["role"] == "owner"

    async def test_members_of_another_org_are_not_visible(self, client):
        token_a, _ = await _signup(client)
        token_b, _ = await _signup(client)

        async def emails(token: str) -> set[str]:
            response = await client.get(
                "/api/v1/team/members", headers={"Authorization": f"Bearer {token}"}
            )
            return {member["email"] for member in response.json()["members"]}

        assert (await emails(token_a)).isdisjoint(await emails(token_b))

    async def test_the_last_owner_cannot_be_demoted(self, client):
        token, _ = await _signup(client)
        headers = {"Authorization": f"Bearer {token}"}
        me = (await client.get("/api/v1/auth/me", headers=headers)).json()

        response = await client.patch(
            f"/api/v1/team/members/{me['id']}", headers=headers, json={"role": "member"}
        )
        assert response.status_code == 409
        assert "at least one active owner" in response.json()["error"]["message"]

    async def test_you_cannot_deactivate_yourself(self, client):
        token, _ = await _signup(client)
        headers = {"Authorization": f"Bearer {token}"}
        me = (await client.get("/api/v1/auth/me", headers=headers)).json()

        response = await client.patch(
            f"/api/v1/team/members/{me['id']}", headers=headers, json={"is_active": False}
        )
        assert response.status_code == 403

    async def test_you_cannot_remove_yourself(self, client):
        token, _ = await _signup(client)
        headers = {"Authorization": f"Bearer {token}"}
        me = (await client.get("/api/v1/auth/me", headers=headers)).json()

        assert (
            await client.delete(f"/api/v1/team/members/{me['id']}", headers=headers)
        ).status_code == 403

    async def test_an_admin_cannot_change_an_owners_role(self, client):
        owner_token, _ = await _signup(client)
        owner = (
            await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {owner_token}"})
        ).json()
        admin = await _join(client, await _invite(client, owner_token, _address(), role="admin"))

        response = await client.patch(
            f"/api/v1/team/members/{owner['id']}",
            headers={"Authorization": f"Bearer {admin['tokens']['access_token']}"},
            json={"role": "member"},
        )
        assert response.status_code == 403

    async def test_an_owner_can_suspend_a_member(self, client):
        owner_token, _ = await _signup(client)
        member = await _join(client, await _invite(client, owner_token, _address()))

        suspended = await client.patch(
            f"/api/v1/team/members/{member['user']['id']}",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"is_active": False},
        )
        assert suspended.status_code == 200
        assert suspended.json()["is_active"] is False

        # The access token is still cryptographically valid; the account behind it is not.
        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {member['tokens']['access_token']}"},
        )
        assert response.status_code == 401


class TestInvitations:
    async def test_invite_returns_a_single_use_token(self, client):
        token, _ = await _signup(client)
        created = await _invite(client, token, _address())

        assert created["invitation"]["status"] == "pending"
        assert created["accept_url"].endswith(created["token"])

    async def test_preview_names_the_organisation_without_a_session(self, client):
        token, _ = await _signup(client)
        email = _address()
        created = await _invite(client, token, email)

        preview = await client.get(
            "/api/v1/auth/invitations/preview", params={"token": created["token"]}
        )
        assert preview.status_code == 200, preview.text
        assert preview.json()["email"] == email
        assert preview.json()["role"] == "member"

    async def test_accepting_joins_the_inviting_organisation(self, client):
        token, org_id = await _signup(client)
        email = _address()
        joined = await _join(client, await _invite(client, token, email, role="admin"))

        assert joined["organization"]["id"] == org_id
        assert joined["user"]["role"] == "admin"
        assert joined["user"]["email"] == email

        members = (
            await client.get("/api/v1/team/members", headers={"Authorization": f"Bearer {token}"})
        ).json()["members"]
        assert email in {member["email"] for member in members}

    async def test_a_token_cannot_be_used_twice(self, client):
        token, _ = await _signup(client)
        created = await _invite(client, token, _address())
        await _join(client, created)

        second = await client.post(
            "/api/v1/auth/invitations/accept",
            json={"token": created["token"], "password": "another-long-password"},
        )
        assert second.status_code == 404

    async def test_revoked_invitations_stop_working(self, client):
        token, _ = await _signup(client)
        created = await _invite(client, token, _address())

        revoked = await client.delete(
            f"/api/v1/team/invitations/{created['invitation']['id']}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert revoked.status_code == 200
        assert revoked.json()["status"] == "revoked"

        response = await client.post(
            "/api/v1/auth/invitations/accept",
            json={"token": created["token"], "password": "another-long-password"},
        )
        assert response.status_code == 404

    async def test_an_unknown_token_looks_like_a_revoked_one(self, client):
        response = await client.get("/api/v1/auth/invitations/preview", params={"token": "x" * 40})
        assert response.status_code == 404

    async def test_a_second_pending_invitation_conflicts(self, client):
        token, _ = await _signup(client)
        email = _address()
        await _invite(client, token, email)

        duplicate = await client.post(
            "/api/v1/team/invitations",
            headers={"Authorization": f"Bearer {token}"},
            json={"email": email, "role": "member"},
        )
        assert duplicate.status_code == 409

    async def test_an_existing_account_cannot_be_invited(self, client):
        token_a, _ = await _signup(client)
        token_b, _ = await _signup(client)
        existing = (
            await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token_b}"})
        ).json()["email"]

        response = await client.post(
            "/api/v1/team/invitations",
            headers={"Authorization": f"Bearer {token_a}"},
            json={"email": existing, "role": "member"},
        )
        assert response.status_code == 409

    async def test_an_admin_cannot_invite_an_owner(self, client):
        owner_token, _ = await _signup(client)
        admin = await _join(client, await _invite(client, owner_token, _address(), role="admin"))

        response = await client.post(
            "/api/v1/team/invitations",
            headers={"Authorization": f"Bearer {admin['tokens']['access_token']}"},
            json={"email": _address(), "role": "owner"},
        )
        assert response.status_code == 403

    async def test_a_member_cannot_invite_at_all(self, client):
        owner_token, _ = await _signup(client)
        member = await _join(client, await _invite(client, owner_token, _address()))

        response = await client.post(
            "/api/v1/team/invitations",
            headers={"Authorization": f"Bearer {member['tokens']['access_token']}"},
            json={"email": _address(), "role": "member"},
        )
        assert response.status_code == 403

    async def test_invitations_of_another_org_are_not_listed(self, client):
        token_a, _ = await _signup(client)
        token_b, _ = await _signup(client)
        await _invite(client, token_a, _address())

        listed = await client.get(
            "/api/v1/team/invitations", headers={"Authorization": f"Bearer {token_b}"}
        )
        assert listed.status_code == 200
        assert listed.json() == []


def _widget_headers(public_key: str, session: str | None = None) -> dict:
    """The widget's own headers. The session id is one of them, never a query parameter —
    it replays a transcript, and a URL reaches ingress logs, history and `Referer`."""
    headers = {"X-Chatbot-Key": public_key, "Origin": TENANT_ORIGIN}
    if session is not None:
        headers["X-Widget-Session"] = session
    return headers


async def _open_ticket(
    client: AsyncClient,
    public_key: str,
    *,
    session_id: str | None = None,
    email: str = "visitor@example.com",
    **extra,
) -> dict:
    """Open a ticket the way the widget does — public key plus an allowed origin."""
    body = {"email": email, "session_id": session_id or uuid.uuid4().hex, **extra}
    response = await client.post(
        "/public/widget/tickets",
        headers={"X-Chatbot-Key": public_key, "Origin": TENANT_ORIGIN},
        json=body,
    )
    assert response.status_code == 201, response.text
    return response.json()


class TestTicketCreation:
    async def test_a_visitor_can_ask_for_a_human(self, client):
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]

        created = await _open_ticket(
            client, chatbot["public_key"], message="My order never arrived", name="Dana"
        )
        assert created["status"] == "open"

        listing = await client.get("/api/v1/tickets", headers={"Authorization": f"Bearer {token}"})
        assert listing.status_code == 200, listing.text
        items = listing.json()["items"]
        assert len(items) == 1
        assert items[0]["visitor_email"] == "visitor@example.com"
        assert items[0]["visitor_name"] == "Dana"
        assert items[0]["source"] == "visitor_contact_form"
        # The visitor's own words become a normal turn in the transcript rather than a note
        # bolted to the side of the ticket.
        assert items[0]["subject"] == "My order never arrived"

    async def test_the_visitors_message_lands_in_the_conversation(self, client):
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]

        created = await _open_ticket(client, chatbot["public_key"], message="Where is my parcel?")
        detail = await client.get(
            f"/api/v1/tickets/{created['ticket_id']}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert detail.status_code == 200, detail.text
        messages = detail.json()["messages"]
        assert [m["role"] for m in messages] == ["user"]
        assert messages[0]["content"] == "Where is my parcel?"

    async def test_a_ticket_needs_an_allowed_origin(self, client):
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]

        response = await client.post(
            "/public/widget/tickets",
            headers={
                "X-Chatbot-Key": chatbot["public_key"],
                "Origin": "https://attacker.example.com",
            },
            json={"email": "visitor@example.com", "session_id": uuid.uuid4().hex},
        )
        # The same chain as /chat, not a second one alongside it.
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "origin_not_allowed"

    async def test_a_malformed_email_is_refused(self, client):
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]

        response = await client.post(
            "/public/widget/tickets",
            headers={"X-Chatbot-Key": chatbot["public_key"], "Origin": TENANT_ORIGIN},
            json={"email": "not-an-address", "session_id": uuid.uuid4().hex},
        )
        assert response.status_code == 422

    async def test_one_conversation_can_be_escalated_more_than_once(self, client):
        """`ticket.conversation_id` is indexed but deliberately not unique."""
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]
        session = uuid.uuid4().hex

        first = await _open_ticket(client, chatbot["public_key"], session_id=session)
        second = await _open_ticket(client, chatbot["public_key"], session_id=session)

        assert first["ticket_id"] != second["ticket_id"]
        assert first["conversation_id"] == second["conversation_id"]


class TestTicketWorkflow:
    async def test_a_staff_reply_moves_an_open_ticket_to_pending(self, client):
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]
        headers = {"Authorization": f"Bearer {token}"}
        created = await _open_ticket(client, chatbot["public_key"], message="Help please")

        reply = await client.post(
            f"/api/v1/tickets/{created['ticket_id']}/messages",
            headers=headers,
            json={"content": "Happy to help — could you share your order number?"},
        )
        assert reply.status_code == 201, reply.text
        assert reply.json()["role"] == "staff"
        assert reply.json()["staff_user_id"] is not None

        detail = (
            await client.get(f"/api/v1/tickets/{created['ticket_id']}", headers=headers)
        ).json()
        assert detail["ticket"]["status"] == "pending"
        # Replying to something nobody had claimed is itself the act of claiming it.
        assert detail["ticket"]["assigned_to"] is not None
        assert [m["role"] for m in detail["messages"]] == ["user", "staff"]

    async def test_resolving_stamps_and_reopening_clears_resolved_at(self, client):
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]
        headers = {"Authorization": f"Bearer {token}"}
        created = await _open_ticket(client, chatbot["public_key"])
        url = f"/api/v1/tickets/{created['ticket_id']}"

        resolved = await client.patch(url, headers=headers, json={"status": "resolved"})
        assert resolved.status_code == 200, resolved.text
        assert resolved.json()["resolved_at"] is not None

        reopened = await client.patch(url, headers=headers, json={"status": "open"})
        assert reopened.status_code == 200
        # `resolved_at` describes the state the row is in, not the last time it was finished.
        assert reopened.json()["resolved_at"] is None

    async def test_assigning_a_colleague_claims_the_ticket(self, client):
        owner_token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, owner_token))["chatbot"]
        headers = {"Authorization": f"Bearer {owner_token}"}
        member = await _join(client, await _invite(client, owner_token, _address()))
        created = await _open_ticket(client, chatbot["public_key"])

        assigned = await client.patch(
            f"/api/v1/tickets/{created['ticket_id']}",
            headers=headers,
            json={"assigned_to": member["user"]["id"]},
        )
        assert assigned.status_code == 200, assigned.text
        assert assigned.json()["assigned_to"] == member["user"]["id"]
        assert assigned.json()["status"] == "pending"

    async def test_a_cross_org_assignee_is_rejected(self, client):
        """The foreign key alone would happily take another tenant's user id."""
        owner_token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, owner_token))["chatbot"]
        created = await _open_ticket(client, chatbot["public_key"])

        other_token, _ = await _signup(client)
        outsider = (
            await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {other_token}"})
        ).json()

        response = await client.patch(
            f"/api/v1/tickets/{created['ticket_id']}",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"assigned_to": outsider["id"]},
        )
        assert response.status_code == 422
        assert "not a member" in response.json()["error"]["message"]

    async def test_unassigning_is_distinct_from_leaving_alone(self, client):
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]
        headers = {"Authorization": f"Bearer {token}"}
        created = await _open_ticket(client, chatbot["public_key"])
        url = f"/api/v1/tickets/{created['ticket_id']}"

        me = (await client.get("/api/v1/auth/me", headers=headers)).json()
        await client.patch(url, headers=headers, json={"assigned_to": me["id"]})

        # A bare priority change must not silently drop the assignment.
        kept = await client.patch(url, headers=headers, json={"priority": "high"})
        assert kept.json()["assigned_to"] == me["id"]
        assert kept.json()["priority"] == "high"

        released = await client.patch(url, headers=headers, json={"unassign": True})
        assert released.json()["assigned_to"] is None

    async def test_an_empty_patch_is_refused(self, client):
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]
        created = await _open_ticket(client, chatbot["public_key"])

        response = await client.patch(
            f"/api/v1/tickets/{created['ticket_id']}",
            headers={"Authorization": f"Bearer {token}"},
            json={},
        )
        assert response.status_code == 422

    async def test_filters_agree_with_their_own_total(self, client):
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]
        headers = {"Authorization": f"Bearer {token}"}

        first = await _open_ticket(client, chatbot["public_key"])
        await _open_ticket(client, chatbot["public_key"])
        await client.patch(
            f"/api/v1/tickets/{first['ticket_id']}", headers=headers, json={"status": "resolved"}
        )

        body = (await client.get("/api/v1/tickets?status=open", headers=headers)).json()
        assert body["total"] == len(body["items"]) == 1
        assert body["items"][0]["status"] == "open"


class _StubChat:
    """A chat provider that answers without reaching a real model."""

    def __init__(self, answer: str = "I do not have that in the available documents.") -> None:
        self._answer = answer

    async def stream(self, _messages):
        for word in self._answer.split():
            yield word + " "


class TestGroundingMissEscalation:
    """The signal that offers a human, end to end over SSE."""

    async def _stream(self, client, chatbot, monkeypatch, session_id):
        async def _chat(*_args, **_kwargs):
            return _StubChat()

        async def _embeddings(*_args):
            # No width recorded means nothing has ever been embedded for this chatbot, so
            # retrieval returns nothing — which is exactly the grounding-miss condition.
            return _StubEmbeddings(768, locked=None)

        monkeypatch.setattr("app.services.rag.factory.get_chat_provider", _chat)
        monkeypatch.setattr("app.services.rag.factory.get_embedding_provider", _embeddings)

        events = {}
        async with client.stream(
            "POST",
            "/public/widget/chat",
            headers={"X-Chatbot-Key": chatbot["public_key"], "Origin": TENANT_ORIGIN},
            json={"message": "Do you sell submarines?", "session_id": session_id},
        ) as response:
            assert response.status_code == 200
            name = None
            async for line in response.aiter_lines():
                if line.startswith("event:"):
                    name = line[6:].strip()
                elif line.startswith("data:") and name:
                    events[name] = json.loads(line[5:].strip())
        return events

    async def test_zero_chunks_marks_the_answer_escalatable(self, client, monkeypatch):
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]
        await _configure_ai(client, token, chatbot["id"])

        events = await self._stream(client, chatbot, monkeypatch, uuid.uuid4().hex)

        assert events["sources"]["sources"] == []
        # Additive: the existing framing and the fallback copy are untouched.
        assert events["done"]["can_escalate"] is True
        assert "conversation_id" in events["done"]
        assert "message_id" in events["done"]

    async def test_the_offer_leads_to_a_ticket_the_dashboard_can_answer(self, client, monkeypatch):
        """The whole loop: miss, escalate, reply, reopen."""
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]
        await _configure_ai(client, token, chatbot["id"])
        session = uuid.uuid4().hex

        events = await self._stream(client, chatbot, monkeypatch, session)
        assert events["done"]["can_escalate"] is True

        created = await _open_ticket(
            client,
            chatbot["public_key"],
            session_id=session,
            message="Do you sell submarines?",
            source="ai_escalation",
            escalation_reason="no_grounded_answer",
        )

        detail = (
            await client.get(
                f"/api/v1/tickets/{created['ticket_id']}",
                headers={"Authorization": f"Bearer {token}"},
            )
        ).json()
        assert detail["ticket"]["source"] == "ai_escalation"
        assert detail["ticket"]["escalation_reason"] == "no_grounded_answer"
        # The escalation attached to the conversation the visitor was already having.
        assert [m["role"] for m in detail["messages"]] == ["user", "assistant", "user"]

        await client.post(
            f"/api/v1/tickets/{created['ticket_id']}/messages",
            headers={"Authorization": f"Bearer {token}"},
            json={"content": "We do not, but we sell dinghies."},
        )

        replay = (
            await client.get(
                "/public/widget/bootstrap",
                headers=_widget_headers(chatbot["public_key"], session),
            )
        ).json()["session"]
        assert replay["ticket_status"] == "pending"
        assert replay["messages"][-1]["role"] == "staff"
        assert replay["messages"][-1]["content"] == "We do not, but we sell dinghies."


class TestWidgetSessionReplay:
    async def test_a_first_visit_gets_a_greeting_and_no_session(self, client):
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]

        body = (
            await client.get(
                "/public/widget/bootstrap",
                headers=_widget_headers(chatbot["public_key"]),
            )
        ).json()
        assert body["session"] is None
        assert body["greeting"]

    async def test_a_returning_visitor_sees_the_staff_reply(self, client):
        """There is no outbound mail, so this is the whole delivery mechanism."""
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]
        session = uuid.uuid4().hex
        created = await _open_ticket(
            client, chatbot["public_key"], session_id=session, message="Is this thing on?"
        )

        await client.post(
            f"/api/v1/tickets/{created['ticket_id']}/messages",
            headers={"Authorization": f"Bearer {token}"},
            json={"content": "Yes — how can I help?"},
        )

        replay = await client.get(
            "/public/widget/bootstrap",
            headers=_widget_headers(chatbot["public_key"], session),
        )
        assert replay.status_code == 200, replay.text
        state = replay.json()["session"]
        assert state["ticket_status"] == "pending"
        assert [m["role"] for m in state["messages"]] == ["user", "staff"]
        assert state["messages"][1]["content"] == "Yes — how can I help?"

    async def test_the_replay_never_leaks_who_answered_or_the_stored_address(self, client):
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]
        session = uuid.uuid4().hex
        created = await _open_ticket(
            client, chatbot["public_key"], session_id=session, email="dana@example.com"
        )
        await client.post(
            f"/api/v1/tickets/{created['ticket_id']}/messages",
            headers={"Authorization": f"Bearer {token}"},
            json={"content": "On it."},
        )

        state = (
            await client.get(
                "/public/widget/bootstrap",
                headers=_widget_headers(chatbot["public_key"], session),
            )
        ).json()["session"]

        # A visitor learns that a human replied, never which one — and the ticket's own
        # fields stay on the organisation's side of the boundary.
        assert set(state["messages"][0]) == {"role", "content", "created_at"}
        assert set(state) == {"conversation_id", "messages", "ticket_status"}
        assert "dana@example.com" not in json.dumps(state)

    async def test_a_session_id_from_another_chatbot_replays_nothing(self, client):
        """The session id names a conversation only within the chatbot that authorised it."""
        token_a, _ = await _signup(client)
        chatbot_a = (await _create_chatbot(client, token_a))["chatbot"]
        session = uuid.uuid4().hex
        await _open_ticket(client, chatbot_a["public_key"], session_id=session, message="Mine")

        token_b, _ = await _signup(client)
        chatbot_b = (await _create_chatbot(client, token_b, name="Other Bot"))["chatbot"]

        stolen = await client.get(
            "/public/widget/bootstrap",
            headers=_widget_headers(chatbot_b["public_key"], session),
        )
        assert stolen.status_code == 200
        assert stolen.json()["session"] is None

    async def test_a_resolved_ticket_replays_as_settled_and_can_be_reopened(self, client):
        """The widget re-enables "Talk to a human" on this status, so it has to be reachable."""
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]
        headers = {"Authorization": f"Bearer {token}"}
        session = uuid.uuid4().hex
        first = await _open_ticket(client, chatbot["public_key"], session_id=session)

        await client.patch(
            f"/api/v1/tickets/{first['ticket_id']}", headers=headers, json={"status": "resolved"}
        )

        replayed = (
            await client.get(
                "/public/widget/bootstrap",
                headers=_widget_headers(chatbot["public_key"], session),
            )
        ).json()["session"]
        assert replayed["ticket_status"] == "resolved"

        # Escalating the same conversation again is allowed, and the newest ticket is the one
        # the visitor is now waiting on.
        second = await _open_ticket(client, chatbot["public_key"], session_id=session)
        assert second["ticket_id"] != first["ticket_id"]

        again = (
            await client.get(
                "/public/widget/bootstrap",
                headers=_widget_headers(chatbot["public_key"], session),
            )
        ).json()["session"]
        assert again["ticket_status"] == "open"

    async def test_a_malformed_session_id_is_refused(self, client):
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]

        for value in ("short", "semi;colon", "x" * 200):
            response = await client.get(
                "/public/widget/bootstrap",
                headers=_widget_headers(chatbot["public_key"], value),
            )
            assert response.status_code == 422, f"{value!r} was accepted"

    async def test_the_session_id_is_not_accepted_from_the_query_string(self, client):
        """It replays a transcript, so it must not travel anywhere a URL travels.

        A query parameter is written to ingress access logs (nginx's default `$request`
        includes it), kept in browser history and handed out in `Referer`. Accepting one
        "for convenience" would quietly reintroduce every one of those.
        """
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]
        session = uuid.uuid4().hex
        await _open_ticket(client, chatbot["public_key"], session_id=session, message="Hello")

        via_query = await client.get(
            "/public/widget/bootstrap",
            params={"session_id": session},
            headers=_widget_headers(chatbot["public_key"]),
        )
        assert via_query.status_code == 200
        assert via_query.json()["session"] is None, "a query parameter replayed a transcript"

    async def test_the_preflight_permits_the_session_header(self, client):
        """A custom header forces a preflight; one the middleware does not list is a browser
        error before the request is ever made."""
        response = await client.request(
            "OPTIONS",
            "/public/widget/bootstrap",
            headers={
                "Origin": TENANT_ORIGIN,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "x-chatbot-key,x-widget-session",
            },
        )
        assert response.status_code == 204
        allowed = response.headers["access-control-allow-headers"].lower()
        assert "x-widget-session" in allowed


class TestSessionIdIsNotLogged:
    """The session id became a bearer capability in iteration 7, so it stopped being
    something that may sit in a log line that ships to an aggregator."""

    def test_the_log_correlator_is_a_digest_rather_than_the_value(self):
        from app.services.rag import session_log_id

        session = uuid.uuid4().hex
        correlator = session_log_id(session)

        assert session not in correlator
        assert len(correlator) == 12
        # Still stable, so one visitor's turns remain correlatable with each other.
        assert correlator == session_log_id(session)
        assert correlator != session_log_id(uuid.uuid4().hex)

    def test_no_log_call_carries_the_raw_session_id(self):
        """A regression guard: the leak this replaced was exactly this shape.

        Scoped to logging calls rather than to the identifier, because passing
        `external_session_id=external_session_id` between functions is ordinary and fine —
        what is not fine is handing it to a logger.
        """
        import pathlib
        import re

        # `logger.bind(...)`, `log.info(...)` and friends, including multi-line calls.
        call = re.compile(
            r"\b(?:log|logger)\.(?:bind|debug|info|warning|error|exception)\((?:[^()]|\([^()]*\))*\)"
        )

        # Passing it *through the digest* is the approved form and the reason it exists.
        wrapped = re.compile(r"session_log_id\(\s*external_session_id\s*\)")

        offenders = []
        for path in pathlib.Path("app").rglob("*.py"):
            for match in call.finditer(path.read_text(encoding="utf-8")):
                if "external_session_id" in wrapped.sub("", match.group(0)):
                    offenders.append(f"{path}: {' '.join(match.group(0).split())[:70]}")

        assert offenders == [], f"raw session id passed to a logger in {offenders}"


class TestTicketIsolation:
    async def test_another_org_sees_no_tickets(self, client):
        token_a, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token_a))["chatbot"]
        await _open_ticket(client, chatbot["public_key"])

        token_b, _ = await _signup(client)
        listing = await client.get(
            "/api/v1/tickets", headers={"Authorization": f"Bearer {token_b}"}
        )
        assert listing.status_code == 200
        assert listing.json()["items"] == []

    async def test_another_org_cannot_read_or_reply_to_a_ticket(self, client):
        token_a, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token_a))["chatbot"]
        created = await _open_ticket(client, chatbot["public_key"])
        url = f"/api/v1/tickets/{created['ticket_id']}"

        token_b, _ = await _signup(client)
        headers = {"Authorization": f"Bearer {token_b}"}

        # "Missing" and "someone else's" are deliberately the same answer.
        assert (await client.get(url, headers=headers)).status_code == 404
        assert (
            await client.patch(url, headers=headers, json={"status": "closed"})
        ).status_code == 404
        assert (
            await client.post(f"{url}/messages", headers=headers, json={"content": "hello"})
        ).status_code == 404


class TestTicketRowLevelSecurity:
    """The policy itself, not the application filtering that sits in front of it.

    RLS does not apply to the table owner, and the default single-role setup runs the app *as*
    the owner — so asserting through the normal session would prove nothing. These tests
    create a throwaway unprivileged role and read `ticket` as that role instead, which is how
    production is meant to be deployed (see project_summary.md, "Notes for whoever picks this
    up"). If the test database cannot create roles, the test says so rather than passing
    quietly.
    """

    async def test_the_policy_is_enabled_with_a_fail_closed_predicate(self, client):
        from app.db.session import system_session
        from sqlalchemy import text

        async with system_session() as session:
            enabled = await session.execute(
                text("SELECT relrowsecurity FROM pg_class WHERE relname = 'ticket'")
            )
            assert enabled.scalar_one() is True

            policy = await session.execute(
                text("SELECT qual FROM pg_policies WHERE tablename = 'ticket'")
            )
            qual = policy.scalar_one()

        # An unset GUC yields NULL, so the predicate is never true and the table reads empty.
        assert "current_setting" in qual
        assert "NULLIF" in qual.upper()

    async def test_an_unprivileged_role_sees_nothing_unscoped_and_only_its_own_when_scoped(
        self, client
    ):
        from app.db.session import get_engine, system_session
        from sqlalchemy import text

        token_a, org_a = await _signup(client)
        chatbot_a = (await _create_chatbot(client, token_a))["chatbot"]
        await _open_ticket(client, chatbot_a["public_key"], email="a@example.com")

        token_b, org_b = await _signup(client)
        chatbot_b = (await _create_chatbot(client, token_b, name="B Bot"))["chatbot"]
        await _open_ticket(client, chatbot_b["public_key"], email="b@example.com")

        role = f"rls_probe_{uuid.uuid4().hex[:12]}"
        engine = get_engine()

        async with system_session() as session:
            try:
                await session.execute(text(f'CREATE ROLE "{role}" NOLOGIN'))
            except Exception as exc:  # noqa: BLE001 - reported, never swallowed
                pytest.skip(
                    f"test database cannot create roles ({type(exc).__name__}); "
                    "grant CREATEROLE to exercise the RLS policy directly"
                )
            await session.execute(text(f'GRANT SELECT ON ticket TO "{role}"'))

        try:
            async with engine.connect() as conn:
                # A fresh transaction per assertion; SET LOCAL ROLE ends with it.
                async with conn.begin():
                    await conn.execute(text(f'SET LOCAL ROLE "{role}"'))
                    unscoped = await conn.execute(text("SELECT count(*) FROM ticket"))
                    assert unscoped.scalar_one() == 0, "an unset tenant GUC must read as empty"

                async with conn.begin():
                    await conn.execute(text(f'SET LOCAL ROLE "{role}"'))
                    await conn.execute(text(f"SET LOCAL app.current_org_id = '{org_a}'"))
                    scoped = await conn.execute(text("SELECT org_id::text FROM ticket"))
                    rows = [row[0] for row in scoped]
                    assert rows == [str(org_a)]
                    assert str(org_b) not in rows
        finally:
            async with system_session() as session:
                await session.execute(text(f'REVOKE ALL ON ticket FROM "{role}"'))
                await session.execute(text(f'DROP ROLE IF EXISTS "{role}"'))


def _hash_embedding(text: str, dimension: int) -> list[float]:
    """A deterministic bag-of-words vector.

    Enough of a relevance signal to tell a matching chunk from a non-matching one, which is
    what these tests are about — the partitioned write and the cast query, not the semantics.
    """
    vector = [0.0] * dimension
    for token in text.lower().split():
        vector[zlib.crc32(token.encode()) % dimension] += 1.0
    length = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / length for value in vector]


class _StubEmbeddings:
    def __init__(self, width: int, *, locked: int | None = None) -> None:
        self._width = width
        self.dimension = locked

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [_hash_embedding(text, self._width) for text in texts]


async def _ingest(client, token, org_id, chatbot_id, body: bytes, *, width: int, monkeypatch):
    """Upload through the API, then run the worker's own pipeline against a stub provider."""
    from app.services.ai import factory
    from app.services.ingestion import pipeline

    upload = await client.post(
        f"/api/v1/chatbots/{chatbot_id}/documents",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("handbook.md", body, "text/markdown")},
    )
    assert upload.status_code == 202, upload.text
    document_id = upload.json()["document"]["id"]

    async def _stub(_org_id, _chatbot_id):
        summary = await factory.get_summary(_org_id, _chatbot_id)
        return _StubEmbeddings(width, locked=summary.embedding_dimension if summary else None)

    monkeypatch.setattr(pipeline.factory, "get_embedding_provider", _stub)
    result = await pipeline.process_document(uuid.UUID(org_id), uuid.UUID(document_id))
    return document_id, result


class TestEmbeddingDimensions:
    """`document_chunk` is partitioned by vector width, so the width is part of every write
    and every read."""

    async def test_ingestion_records_the_width_and_retrieval_finds_the_chunk(
        self, client, monkeypatch
    ):
        from app.services.rag import ChatContext, retrieve

        token, org_id = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]
        await _configure_ai(client, token, chatbot["id"])

        _, result = await _ingest(
            client,
            token,
            org_id,
            chatbot["id"],
            b"# Refunds\n\nRefund requests are accepted within thirty days of purchase.",
            width=768,
            monkeypatch=monkeypatch,
        )
        assert result.chunk_count >= 1

        # The width was measured from the vectors themselves and is now the chatbot's lock.
        config = await client.get(
            f"/api/v1/chatbots/{chatbot['id']}/ai-config",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert config.json()["embedding_dimension"] == 768
        assert config.json()["embedding_locked"] is True

        async def _stub_for_query(*_args):
            return _StubEmbeddings(768, locked=768)

        monkeypatch.setattr("app.services.rag.factory.get_embedding_provider", _stub_for_query)
        matches = await retrieve(
            ChatContext(
                org_id=uuid.UUID(org_id),
                chatbot_id=uuid.UUID(chatbot["id"]),
                system_prompt="",
                generation_config={},
            ),
            "refund requests",
        )
        assert matches, "the chunk written into the 768 partition was not retrieved"
        assert "Refund requests" in matches[0].chunk.content

    async def test_a_width_with_no_partition_still_works(self, client, monkeypatch):
        """The DEFAULT partition takes it: an unanticipated width should cost speed, not the
        whole ingestion."""
        token, org_id = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]
        await _configure_ai(client, token, chatbot["id"])

        _, result = await _ingest(
            client,
            token,
            org_id,
            chatbot["id"],
            b"# Hours\n\nThe shop opens at nine.",
            width=384,
            monkeypatch=monkeypatch,
        )
        assert result.chunk_count >= 1

        config = await client.get(
            f"/api/v1/chatbots/{chatbot['id']}/ai-config",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert config.json()["embedding_dimension"] == 384

    async def test_the_embedding_model_is_locked_once_chunks_exist(self, client, monkeypatch):
        token, org_id = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]
        await _configure_ai(client, token, chatbot["id"])
        await _ingest(
            client,
            token,
            org_id,
            chatbot["id"],
            b"# Refunds\n\nWithin thirty days.",
            width=768,
            monkeypatch=monkeypatch,
        )

        blocked = await client.put(
            f"/api/v1/chatbots/{chatbot['id']}/ai-config",
            headers={"Authorization": f"Bearer {token}"},
            json=_ai_payload(embedding_model="a-different-model"),
        )
        assert blocked.status_code == 409, blocked.text
        assert "Delete them" in blocked.json()["error"]["message"]

    async def test_the_chat_provider_can_still_be_changed_while_locked(self, client, monkeypatch):
        """The lock is about vectors already written, so it has nothing to say about chat."""
        token, org_id = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]
        await _configure_ai(client, token, chatbot["id"])
        await _ingest(
            client,
            token,
            org_id,
            chatbot["id"],
            b"# Refunds\n\nWithin thirty days.",
            width=768,
            monkeypatch=monkeypatch,
        )

        response = await client.put(
            f"/api/v1/chatbots/{chatbot['id']}/ai-config",
            headers={"Authorization": f"Bearer {token}"},
            json=_ai_payload(chat_provider="anthropic"),
        )
        assert response.status_code == 200, response.text
        assert response.json()["chat"]["provider"] == "anthropic"
        assert response.json()["embedding_dimension"] == 768

    async def test_deleting_the_documents_releases_the_lock(self, client, monkeypatch):
        token, org_id = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]
        await _configure_ai(client, token, chatbot["id"])
        document_id, _ = await _ingest(
            client,
            token,
            org_id,
            chatbot["id"],
            b"# Refunds\n\nWithin thirty days.",
            width=768,
            monkeypatch=monkeypatch,
        )

        removed = await client.delete(
            f"/api/v1/chatbots/{chatbot['id']}/documents/{document_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert removed.status_code == 204

        released = await client.put(
            f"/api/v1/chatbots/{chatbot['id']}/ai-config",
            headers={"Authorization": f"Bearer {token}"},
            json=_ai_payload(embedding_model="a-different-model"),
        )
        assert released.status_code == 200, released.text
        # The recorded width described the old model, so it is not carried over.
        assert released.json()["embedding_dimension"] is None


def _ollama_models() -> tuple[str, str] | None:
    """A chat model and an embedding model on a reachable Ollama, or nothing.

    Discovered rather than hardcoded: the point is to exercise the whole loop against a real
    provider that costs nothing, not to require one particular download. Override with
    RAG_TEST_OLLAMA_CHAT_MODEL / RAG_TEST_OLLAMA_EMBED_MODEL.
    """
    import httpx

    try:
        response = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=3.0)
        response.raise_for_status()
        names = [model["name"] for model in response.json().get("models", [])]
    except Exception:  # noqa: BLE001 - absence is a skip, not a failure
        return None

    embed = os.environ.get("RAG_TEST_OLLAMA_EMBED_MODEL") or next(
        (name for name in names if "embed" in name.lower()), None
    )
    chat = os.environ.get("RAG_TEST_OLLAMA_CHAT_MODEL") or next(
        (name for name in names if "embed" not in name.lower()), None
    )
    return (chat, embed) if chat and embed else None


def _capabilities(model: str) -> list[str]:
    import httpx

    try:
        response = httpx.post(f"{OLLAMA_URL}/api/show", json={"model": model}, timeout=30.0)
        return response.json().get("capabilities", [])
    except Exception:  # noqa: BLE001 - only used to decide whether a test applies
        return []


_OLLAMA = _ollama_models()


@pytest.mark.skipif(
    _OLLAMA is None,
    reason=f"no Ollama with both a chat and an embedding model at {OLLAMA_URL}",
)
class TestOllamaEndToEnd:
    """The whole loop against a real provider: configure, test, ingest, retrieve, answer.

    Ollama because it is the one provider that can be exercised without an account, a key or
    a bill. The other three are covered by their builders and by mocked failures.
    """

    async def _ready(self, client) -> tuple[str, str, dict]:
        chat_model, embed_model = _OLLAMA
        token, org_id = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]
        await _configure_ai(
            client,
            token,
            chatbot["id"],
            chat_model=chat_model,
            embedding_model=embed_model,
        )
        return token, org_id, chatbot

    async def test_a_connection_test_discovers_the_width_and_records_it(self, client):
        _, embed_model = _OLLAMA
        token, _, chatbot = await self._ready(client)

        response = await client.post(
            f"/api/v1/chatbots/{chatbot['id']}/ai-config/test",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "embedding": {
                    "provider": "ollama",
                    "model": embed_model,
                    "connection": {"base_url": OLLAMA_URL},
                }
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["ok"] is True, body
        # Measured from the returned vector, never looked up from the model's name.
        assert isinstance(body["embedding_dimension"], int)
        assert body["embedding_dimension"] > 0

        stored = await client.get(
            f"/api/v1/chatbots/{chatbot['id']}/ai-config",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert stored.json()["embedding_dimension"] == body["embedding_dimension"]

    async def test_a_document_is_ingested_and_then_retrieved(self, client):
        from app.services.ingestion.pipeline import process_document
        from app.services.rag import ChatContext, retrieve

        token, org_id, chatbot = await self._ready(client)

        upload = await client.post(
            f"/api/v1/chatbots/{chatbot['id']}/documents",
            headers={"Authorization": f"Bearer {token}"},
            files={
                "file": (
                    "handbook.md",
                    b"# Refunds\n\nRefund requests are accepted within thirty days of "
                    b"purchase.\n\n# Opening hours\n\nThe shop opens at nine in the morning.",
                    "text/markdown",
                )
            },
        )
        assert upload.status_code == 202, upload.text

        result = await process_document(
            uuid.UUID(org_id), uuid.UUID(upload.json()["document"]["id"])
        )
        assert result.chunk_count >= 1

        config = await client.get(
            f"/api/v1/chatbots/{chatbot['id']}/ai-config",
            headers={"Authorization": f"Bearer {token}"},
        )
        width = config.json()["embedding_dimension"]
        assert isinstance(width, int) and width > 0

        matches = await retrieve(
            ChatContext(
                org_id=uuid.UUID(org_id),
                chatbot_id=uuid.UUID(chatbot["id"]),
                system_prompt="",
                generation_config={},
            ),
            "how long do I have to ask for a refund?",
        )
        assert matches, "a real embedding round trip produced no retrievable chunk"
        assert "Refund" in matches[0].chunk.content

    async def test_an_answer_streams_and_carries_no_reasoning(self, client):
        """`think` controls whether the model reasons, not whether the visitor sees it."""
        from app.services.ai import factory

        chat_model, _ = _OLLAMA
        token, org_id, chatbot = await self._ready(client)

        # `think` off: on a reasoning model the whole token budget otherwise goes to
        # reasoning and no answer is produced at all — see test_a_reasoning_model_that_says
        # _nothing_is_reported below, which is what that failure now looks like.
        payload = _ai_payload(chat_model=chat_model, embedding_model=_OLLAMA[1])
        payload["chat"]["connection"]["think"] = False
        assert (
            await client.put(
                f"/api/v1/chatbots/{chatbot['id']}/ai-config",
                headers={"Authorization": f"Bearer {token}"},
                json=payload,
            )
        ).status_code == 200

        chat = await factory.get_chat_provider(
            uuid.UUID(org_id),
            uuid.UUID(chatbot["id"]),
            {"temperature": 0.0, "max_tokens": 64},
        )
        answer = "".join(
            [delta async for delta in chat.stream([HumanMessage(content="Say the word: ok")])]
        )
        assert answer.strip(), "the model streamed nothing"
        assert "<think>" not in answer
        assert "</think>" not in answer

    async def test_a_connection_test_turns_reasoning_off_so_it_gets_an_answer(self, client):
        """With `think` left on, a reasoning model returns nothing inside the probe's token
        budget — which would read as a green light that proved nothing."""
        chat_model, _ = _OLLAMA
        token, _, chatbot = await self._ready(client)

        response = await client.post(
            f"/api/v1/chatbots/{chatbot['id']}/ai-config/test",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "chat": {
                    "provider": "ollama",
                    "model": chat_model,
                    "connection": {"base_url": OLLAMA_URL, "think": True},
                }
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["ok"] is True, response.text

    async def test_a_model_that_says_nothing_is_reported_not_persisted(self, client):
        """A reasoning model given a small budget answers with silence. The visitor gets an
        error rather than an empty bubble, and no empty turn lands in the transcript."""
        from app.core.exceptions import UpstreamServiceError
        from app.services.rag import ChatContext, stream_answer

        chat_model, _embed_model = _OLLAMA
        token, org_id, chatbot = await self._ready(client)
        if "thinking" not in _capabilities(chat_model):
            pytest.skip(f"{chat_model} is not a reasoning model")

        context = ChatContext(
            org_id=uuid.UUID(org_id),
            chatbot_id=uuid.UUID(chatbot["id"]),
            system_prompt="",
            # Small enough that reasoning consumes all of it.
            generation_config={"temperature": 0.0, "max_tokens": 32},
        )
        with pytest.raises(UpstreamServiceError):
            async for _ in stream_answer(
                context, question="What is the refund window?", external_session_id="probe-0001"
            ):
                pass

        conversations = await client.get(
            f"/api/v1/chatbots/{chatbot['id']}/conversations",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert conversations.status_code == 200, conversations.text
        # The conversation is opened before the stream starts; what must not be there is the
        # question and an empty answer beside it.
        assert all(item["message_count"] == 0 for item in conversations.json()["items"]), (
            conversations.text
        )


class TestSessionRevocation:
    async def test_logout_prevents_further_refreshes(self, client):
        suffix = uuid.uuid4().hex[:10]
        signup = await client.post(
            "/api/v1/auth/signup",
            json={
                "organization_name": f"Revoke {suffix}",
                "email": f"revoke-{suffix}@example.com",
                "password": "a-sufficiently-long-password",
            },
        )
        refresh_token = signup.json()["tokens"]["refresh_token"]

        first = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
        assert first.status_code == 200

        logout = await client.post("/api/v1/auth/logout", json={"refresh_token": refresh_token})
        assert logout.status_code == 204

        blocked = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
        assert blocked.status_code == 401
        assert blocked.json()["error"]["code"] == "unauthenticated"

    async def test_logout_accepts_a_token_it_cannot_read(self, client):
        for value in ("not-a-token", "a.b.c", ""):
            response = await client.post("/api/v1/auth/logout", json={"refresh_token": value})
            assert response.status_code == 204

    async def test_removing_a_member_invalidates_their_session(self, client):
        owner_token, _ = await _signup(client)
        member = await _join(client, await _invite(client, owner_token, _address()))

        removed = await client.delete(
            f"/api/v1/team/members/{member['user']['id']}",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert removed.status_code == 204

        response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": member["tokens"]["refresh_token"]},
        )
        assert response.status_code == 401


# --------------------------------------------------------------- retention --


async def _age_conversation(org_id: str, conversation_id: str, *, days: int) -> None:
    """Backdate a conversation's last activity.

    The sweep keys on `updated_at`, and there is no API for moving it, so the alternative
    would be waiting a day. Written through `tenant_session` so it goes through the same RLS
    path as everything else rather than around it.
    """
    from app.db.session import tenant_session
    from sqlalchemy import text as sql_text

    async with tenant_session(uuid.UUID(org_id)) as session:
        await session.execute(
            sql_text(
                "UPDATE conversation SET updated_at = now() - make_interval(days => :days) "
                "WHERE id = :id"
            ),
            {"days": days, "id": uuid.UUID(conversation_id)},
        )


async def _conversation_ids(client: AsyncClient, token: str, chatbot_id: str) -> set[str]:
    response = await client.get(
        f"/api/v1/chatbots/{chatbot_id}/conversations",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    return {item["id"] for item in response.json()["items"]}


async def _resolve_ticket(client: AsyncClient, token: str, ticket_id: str) -> None:
    """An unresolved ticket pins its conversation, so a test about *age* has to close the
    ticket first or it proves the pin instead."""
    response = await client.patch(
        f"/api/v1/tickets/{ticket_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"status": "resolved"},
    )
    assert response.status_code == 200, response.text


async def _set_retention(client: AsyncClient, token: str, chatbot_id: str, days: int | None):
    response = await client.patch(
        f"/api/v1/chatbots/{chatbot_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"retention_days": days},
    )
    assert response.status_code == 200, response.text
    return response.json()


class TestRetentionSettings:
    async def test_a_chatbot_keeps_conversations_forever_by_default(self, client):
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]
        assert chatbot["retention_days"] is None

    async def test_retention_can_be_set_and_cleared_again(self, client):
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]

        assert (await _set_retention(client, token, chatbot["id"], 30))["retention_days"] == 30
        # Clearing it is the case a partial patch usually cannot express, because `null`
        # normally means "unchanged". Retention is the deliberate exception; without it the
        # setting would be one-way.
        assert (await _set_retention(client, token, chatbot["id"], None))["retention_days"] is None

    async def test_other_fields_still_treat_null_as_unchanged(self, client):
        """The `retention_days` exception must not have widened to the whole model."""
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token, name="Keeps its description"))["chatbot"]

        response = await client.patch(
            f"/api/v1/chatbots/{chatbot['id']}",
            headers={"Authorization": f"Bearer {token}"},
            json={"description": None, "retention_days": 14},
        )
        assert response.status_code == 200, response.text
        assert response.json()["description"] == chatbot["description"]
        assert response.json()["retention_days"] == 14

    async def test_a_nonsense_retention_is_refused(self, client):
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]

        for days in (0, -5, 4000):
            response = await client.patch(
                f"/api/v1/chatbots/{chatbot['id']}",
                headers={"Authorization": f"Bearer {token}"},
                json={"retention_days": days},
            )
            assert response.status_code == 422, (days, response.text)

    async def test_the_database_refuses_it_too(self, client):
        """The API bound is not the only guard: a backfill or a psql session hits the check
        constraint, which is what stops a zero reaching the sweep and deleting everything
        the moment it next runs."""
        from app.db.session import tenant_session
        from sqlalchemy import text as sql_text
        from sqlalchemy.exc import IntegrityError

        token, org_id = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]

        with pytest.raises(IntegrityError):
            async with tenant_session(uuid.UUID(org_id)) as session:
                await session.execute(
                    sql_text("UPDATE chatbot SET retention_days = 0 WHERE id = :id"),
                    {"id": uuid.UUID(chatbot["id"])},
                )


class TestConversationDeletion:
    async def test_an_admin_can_delete_a_conversation_and_its_messages(self, client):
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]
        headers = {"Authorization": f"Bearer {token}"}
        created = await _open_ticket(client, chatbot["public_key"], message="Delete me")
        conversation_id = created["conversation_id"]

        response = await client.delete(
            f"/api/v1/chatbots/{chatbot['id']}/conversations/{conversation_id}", headers=headers
        )
        assert response.status_code == 204, response.text
        assert await _conversation_ids(client, token, chatbot["id"]) == set()

        messages = await client.get(
            f"/api/v1/chatbots/{chatbot['id']}/conversations/{conversation_id}/messages",
            headers=headers,
        )
        assert messages.status_code == 404

        # The ticket wrapping it cascaded rather than being left pointing at nothing.
        listing = await client.get("/api/v1/tickets", headers=headers)
        assert listing.json()["items"] == []

    async def test_a_member_cannot_delete_a_conversation(self, client):
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]
        created = await _open_ticket(client, chatbot["public_key"])

        joined = await _join(client, await _invite(client, token, _address(), role="member"))
        response = await client.delete(
            f"/api/v1/chatbots/{chatbot['id']}/conversations/{created['conversation_id']}",
            headers={"Authorization": f"Bearer {joined['tokens']['access_token']}"},
        )
        assert response.status_code == 403

    async def test_another_organisation_cannot_delete_it(self, client):
        token_a, _ = await _signup(client)
        chatbot_a = (await _create_chatbot(client, token_a))["chatbot"]
        created = await _open_ticket(client, chatbot_a["public_key"])

        token_b, _ = await _signup(client)
        response = await client.delete(
            f"/api/v1/chatbots/{chatbot_a['id']}/conversations/{created['conversation_id']}",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert response.status_code == 404
        # And the conversation is still there for the org that owns it.
        assert created["conversation_id"] in await _conversation_ids(
            client, token_a, chatbot_a["id"]
        )

    async def test_the_chatbot_in_the_path_has_to_be_the_right_one(self, client):
        """RLS proves the row is this tenant's; it does not prove it belongs to the chatbot
        named in the URL, so the service checks that separately."""
        token, _ = await _signup(client)
        first = (await _create_chatbot(client, token, name="First"))["chatbot"]
        second = (await _create_chatbot(client, token, name="Second"))["chatbot"]
        created = await _open_ticket(client, first["public_key"])

        response = await client.delete(
            f"/api/v1/chatbots/{second['id']}/conversations/{created['conversation_id']}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 404
        assert created["conversation_id"] in await _conversation_ids(client, token, first["id"])


class TestRetentionSweep:
    async def test_an_aged_conversation_is_purged_and_a_recent_one_is_kept(self, client):
        from app.services.conversation import purge_expired_conversations

        token, org_id = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]
        old = await _open_ticket(client, chatbot["public_key"], message="Ancient history")
        recent = await _open_ticket(client, chatbot["public_key"], message="Asked today")

        # Resolved, so age is what decides each one's fate rather than the ticket.
        for created in (old, recent):
            await client.patch(
                f"/api/v1/tickets/{created['ticket_id']}",
                headers={"Authorization": f"Bearer {token}"},
                json={"status": "resolved"},
            )
        await _age_conversation(org_id, old["conversation_id"], days=45)
        await _set_retention(client, token, chatbot["id"], 30)

        report = await purge_expired_conversations()
        assert report.conversations_deleted >= 1
        assert report.incomplete == []

        remaining = await _conversation_ids(client, token, chatbot["id"])
        assert old["conversation_id"] not in remaining
        assert recent["conversation_id"] in remaining

    async def test_a_chatbot_without_retention_is_left_alone(self, client):
        from app.services.conversation import purge_expired_conversations

        token, org_id = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]
        created = await _open_ticket(client, chatbot["public_key"])
        await _age_conversation(org_id, created["conversation_id"], days=4000)

        await purge_expired_conversations()

        assert created["conversation_id"] in await _conversation_ids(client, token, chatbot["id"])

    async def test_an_unresolved_ticket_pins_its_conversation(self, client):
        """Deleting a support request out from under whoever is handling it would be a bug,
        so an open or pending ticket holds its transcript past the retention window."""
        from app.services.conversation import purge_expired_conversations

        token, org_id = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]
        headers = {"Authorization": f"Bearer {token}"}
        created = await _open_ticket(client, chatbot["public_key"], message="Still waiting")
        await _age_conversation(org_id, created["conversation_id"], days=90)
        await _set_retention(client, token, chatbot["id"], 7)

        await purge_expired_conversations()
        assert created["conversation_id"] in await _conversation_ids(client, token, chatbot["id"])

        # Resolve it and the same conversation ages out on the next sweep.
        await client.patch(
            f"/api/v1/tickets/{created['ticket_id']}", headers=headers, json={"status": "resolved"}
        )
        await _age_conversation(org_id, created["conversation_id"], days=90)
        await purge_expired_conversations()
        assert created["conversation_id"] not in await _conversation_ids(
            client, token, chatbot["id"]
        )

    async def test_one_organisations_retention_does_not_reach_another(self, client):
        from app.services.conversation import purge_expired_conversations

        token_a, org_a = await _signup(client)
        chatbot_a = (await _create_chatbot(client, token_a))["chatbot"]
        aged_a = await _open_ticket(client, chatbot_a["public_key"])
        await _resolve_ticket(client, token_a, aged_a["ticket_id"])
        await _age_conversation(org_a, aged_a["conversation_id"], days=90)
        await _set_retention(client, token_a, chatbot_a["id"], 7)

        token_b, org_b = await _signup(client)
        chatbot_b = (await _create_chatbot(client, token_b))["chatbot"]
        aged_b = await _open_ticket(client, chatbot_b["public_key"])
        # Resolved and just as old, so nothing but the absent retention setting is keeping
        # this one alive.
        await _resolve_ticket(client, token_b, aged_b["ticket_id"])
        await _age_conversation(org_b, aged_b["conversation_id"], days=90)

        await purge_expired_conversations()

        assert aged_a["conversation_id"] not in await _conversation_ids(
            client, token_a, chatbot_a["id"]
        )
        assert aged_b["conversation_id"] in await _conversation_ids(
            client, token_b, chatbot_b["id"]
        )

    async def test_a_second_sweep_stands_down_while_one_is_running(self, client):
        """Beat restarting, or a sweep overrunning its window, must not produce two passes
        over the same rows."""
        from app.core.config import settings
        from app.services.conversation import purge_expired_conversations
        from app.services.redis_client import get_redis

        redis = get_redis()
        key = settings.retention.lock_key
        await redis.set(key, "someone-elses-sweep", ex=60)
        try:
            report = await purge_expired_conversations()
        finally:
            await redis.delete(key)

        assert report.skipped_locked is True
        assert report.conversations_deleted == 0

    async def test_the_lock_is_released_afterwards(self, client):
        from app.core.config import settings
        from app.services.conversation import purge_expired_conversations
        from app.services.redis_client import get_redis

        await purge_expired_conversations()
        assert await get_redis().get(settings.retention.lock_key) is None


# ----------------------------------------------------------- footer links --


class TestWidgetFooterLinks:
    async def test_a_chatbot_starts_with_no_footer_links(self, client):
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]
        assert chatbot["privacy_url"] == ""
        assert chatbot["terms_url"] == ""

    async def test_links_round_trip_to_the_widget(self, client):
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]
        widget_headers = {"X-Chatbot-Key": chatbot["public_key"], "Origin": TENANT_ORIGIN}

        before = (await client.get("/public/widget/bootstrap", headers=widget_headers)).json()
        assert before["privacy_url"] == ""
        assert before["terms_url"] == ""

        saved = await client.patch(
            f"/api/v1/chatbots/{chatbot['id']}",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "privacy_url": "https://acme.example.com/privacy",
                "terms_url": "https://acme.example.com/terms",
            },
        )
        assert saved.status_code == 200, saved.text

        after = (await client.get("/public/widget/bootstrap", headers=widget_headers)).json()
        assert after["privacy_url"] == "https://acme.example.com/privacy"
        assert after["terms_url"] == "https://acme.example.com/terms"

    async def test_an_empty_string_removes_a_link(self, client):
        """The only way to take one back down. `null` means "unchanged" on this endpoint, so
        clearing has to be spelled with an empty string."""
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]
        headers = {"Authorization": f"Bearer {token}"}

        await client.patch(
            f"/api/v1/chatbots/{chatbot['id']}",
            headers=headers,
            json={"privacy_url": "https://acme.example.com/privacy"},
        )
        cleared = await client.patch(
            f"/api/v1/chatbots/{chatbot['id']}", headers=headers, json={"privacy_url": ""}
        )
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["privacy_url"] == ""

    async def test_resetting_the_theme_keeps_the_links(self, client):
        """The reason these are their own columns rather than two more members of
        `theme_json`: the dashboard's "Reset to the default theme" empties that column, and a
        tenant's privacy notice must not vanish because they changed their mind about a
        colour."""
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]
        headers = {"Authorization": f"Bearer {token}"}

        await client.patch(
            f"/api/v1/chatbots/{chatbot['id']}",
            headers=headers,
            json={
                "theme_json": {"accent": "#ff6600", "title": "Ask the shop"},
                "privacy_url": "https://acme.example.com/privacy",
                "terms_url": "https://acme.example.com/terms",
            },
        )

        # Exactly what the reset button sends: the theme, and nothing else.
        reset = await client.patch(
            f"/api/v1/chatbots/{chatbot['id']}", headers=headers, json={"theme_json": {}}
        )
        assert reset.status_code == 200, reset.text
        assert reset.json()["theme_json"] == {}
        assert reset.json()["privacy_url"] == "https://acme.example.com/privacy"
        assert reset.json()["terms_url"] == "https://acme.example.com/terms"

    async def test_a_dangerous_or_malformed_link_is_refused(self, client):
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]

        for link in (
            "javascript:alert(1)",
            "JavaScript:alert(1)",
            "data:text/html,<script>alert(1)</script>",
            "vbscript:msgbox(1)",
            "file:///etc/passwd",
            "ftp://example.com/privacy",
            "/privacy",
            "example.com/privacy",
            "https://",
        ):
            response = await client.patch(
                f"/api/v1/chatbots/{chatbot['id']}",
                headers={"Authorization": f"Bearer {token}"},
                json={"privacy_url": link},
            )
            assert response.status_code == 422, (link, response.text)

    async def test_an_overlong_link_is_refused(self, client):
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]

        response = await client.patch(
            f"/api/v1/chatbots/{chatbot['id']}",
            headers={"Authorization": f"Bearer {token}"},
            json={"privacy_url": "https://acme.example.com/" + "a" * 500},
        )
        assert response.status_code == 422

    async def test_a_poisoned_cache_entry_is_dropped_rather_than_served(self, client):
        """The widget re-validates on the way out because the value crosses a Redis cache
        after it was checked on the way in. Anything that got in there another way must cost
        the visitor a footer link, not their whole chat."""
        import json as json_module

        from app.services.redis_client import get_redis

        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]
        widget_headers = {"X-Chatbot-Key": chatbot["public_key"], "Origin": TENANT_ORIGIN}

        # Prime the cache, then rewrite the entry with something the validator refuses.
        await client.get("/public/widget/bootstrap", headers=widget_headers)
        redis = get_redis()
        key = f"chatbot:pk:{chatbot['public_key']}"
        cached = json_module.loads(await redis.get(key))
        cached["privacy_url"] = "javascript:alert(1)"
        cached["terms_url"] = "https://acme.example.com/terms"
        await redis.set(key, json_module.dumps(cached), ex=60)

        served = await client.get("/public/widget/bootstrap", headers=widget_headers)
        assert served.status_code == 200, served.text
        assert served.json()["privacy_url"] == ""
        # The good one beside it is unaffected — one bad value does not cost the other.
        assert served.json()["terms_url"] == "https://acme.example.com/terms"


# --------------------------------------------------- ticket spam controls --


async def _clear_rate_limits() -> None:
    """The suite runs with RATE_LIMIT_ENABLED=false, and these tests turn it back on. Buckets
    are keyed per chatbot and every test signs up a fresh org, so this only guards against a
    previous test in this class having consumed the shared `unknown` address bucket."""
    from app.services.redis_client import get_redis

    redis = get_redis()
    async for key in redis.scan_iter("ratelimit:*"):
        await redis.delete(key)


async def _post_ticket(client: AsyncClient, public_key: str, **headers):
    return await client.post(
        "/public/widget/tickets",
        headers={
            "X-Chatbot-Key": public_key,
            "Origin": TENANT_ORIGIN,
            **headers,
        },
        json={"email": "spam@example.com", "session_id": uuid.uuid4().hex},
    )


@pytest.fixture
async def rate_limited(monkeypatch):
    """Rate limiting on, with the shipped ticket defaults."""
    from app.core.config import settings

    monkeypatch.setattr(settings.rate_limit, "enabled", True)
    await _clear_rate_limits()
    yield
    await _clear_rate_limits()


class TestTicketSpamControls:
    async def test_a_fresh_session_id_no_longer_buys_a_fresh_allowance(self, client, rate_limited):
        """The bypass this feature exists to close.

        `session_id` is generated in the browser, so the per-session bucket is keyed on
        something the caller picks. Rotating it used to mean unlimited tickets; now the
        address bucket catches it.
        """
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]
        address = {"CF-Connecting-IP": "203.0.113.7"}

        # Each call sends a brand-new session_id, as a bot would.
        statuses = [
            (await _post_ticket(client, chatbot["public_key"], **address)).status_code
            for _ in range(6)
        ]

        assert 429 in statuses, statuses
        # The shipped per-address capacity is 3, so the first few land and the rest do not.
        assert statuses.count(201) <= 3, statuses

    async def test_the_limit_is_per_address_not_global(self, client, rate_limited):
        """One abusive visitor must not lock out everyone else on the tenant's site."""
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]

        for _ in range(6):
            await _post_ticket(client, chatbot["public_key"], **{"CF-Connecting-IP": "203.0.113.7"})

        # A different visitor, unaffected.
        other = await _post_ticket(
            client, chatbot["public_key"], **{"CF-Connecting-IP": "198.51.100.22"}
        )
        assert other.status_code == 201, other.text

    async def test_the_limit_is_per_chatbot(self, client, rate_limited):
        """A visitor throttled on one tenant's site is not thereby throttled on another's."""
        token_a, _ = await _signup(client)
        chatbot_a = (await _create_chatbot(client, token_a))["chatbot"]
        token_b, _ = await _signup(client)
        chatbot_b = (await _create_chatbot(client, token_b))["chatbot"]
        address = {"CF-Connecting-IP": "203.0.113.7"}

        for _ in range(6):
            await _post_ticket(client, chatbot_a["public_key"], **address)

        elsewhere = await _post_ticket(client, chatbot_b["public_key"], **address)
        assert elsewhere.status_code == 201, elsewhere.text

    async def test_a_distributed_attempt_still_hits_the_chatbot_ceiling(
        self, client, rate_limited, monkeypatch
    ):
        """Every request from a new address, so the per-address bucket never fills. The
        per-chatbot bucket is the only thing left, and it is what stops one tenant's queue
        being buried."""
        from app.core.config import settings

        # The shipped ceiling is 30, which would make this test 31 signups' worth of noise.
        monkeypatch.setattr(settings.rate_limit, "ticket_chatbot_capacity", 4)

        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]

        statuses = [
            (
                await _post_ticket(
                    client, chatbot["public_key"], **{"CF-Connecting-IP": f"203.0.113.{n}"}
                )
            ).status_code
            for n in range(1, 8)
        ]

        assert 429 in statuses, statuses
        assert statuses.count(201) <= 4, statuses

    async def test_the_rejection_says_when_to_come_back(self, client, rate_limited):
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]
        address = {"CF-Connecting-IP": "203.0.113.7"}

        last = None
        for _ in range(6):
            last = await _post_ticket(client, chatbot["public_key"], **address)

        assert last.status_code == 429
        assert last.json()["error"]["code"] == "rate_limit_exceeded"
        assert int(last.headers["retry-after"]) > 0

    async def test_chat_is_not_caught_by_the_ticket_limit(self, client, rate_limited):
        """Tickets get a far tighter allowance than chat precisely so chat does not have to
        share it. Six chat turns from one address must be unremarkable."""
        token, _ = await _signup(client)
        chatbot = (await _create_chatbot(client, token))["chatbot"]
        session = uuid.uuid4().hex

        for _ in range(6):
            response = await client.post(
                "/public/widget/chat",
                headers={
                    "X-Chatbot-Key": chatbot["public_key"],
                    "Origin": TENANT_ORIGIN,
                    "CF-Connecting-IP": "203.0.113.7",
                },
                json={"message": "hello", "session_id": session},
            )
            assert response.status_code != 429, response.text


class TestClientAddressResolution:
    def test_the_configured_header_wins_over_a_forgeable_one(self):
        """`X-Forwarded-For` is appended to, so a caller's own value sits at the front of it.
        `CF-Connecting-IP` is overwritten by the proxy, which is why it is the default."""
        from app.core.client_ip import client_ip

        request = _fake_request(
            {"cf-connecting-ip": "203.0.113.7", "x-forwarded-for": "1.2.3.4, 203.0.113.7"},
            client_host="10.0.0.1",
        )
        assert client_ip(request) == "203.0.113.7"

    def test_a_forged_list_in_the_trusted_header_takes_only_the_last_entry(self):
        """If something upstream appends rather than overwrites, only the rightmost entry can
        have been added by a proxy on this side of the caller."""
        from app.core.client_ip import client_ip

        request = _fake_request({"cf-connecting-ip": "1.2.3.4, 203.0.113.7"})
        assert client_ip(request) == "203.0.113.7"

    def test_rubbish_becomes_one_shared_bucket_rather_than_a_key(self):
        """This value reaches a Redis key. An unbounded header must not become one, and an
        unidentifiable caller must not thereby escape the limit."""
        from app.core.client_ip import UNKNOWN_CLIENT, client_ip

        for value in ("", "not-an-ip", "203.0.113.7; DROP", "x" * 5000):
            assert client_ip(_fake_request({"cf-connecting-ip": value})) == UNKNOWN_CLIENT

    def test_it_falls_back_to_the_socket_when_no_header_is_present(self):
        from app.core.client_ip import client_ip

        assert client_ip(_fake_request({}, client_host="198.51.100.4")) == "198.51.100.4"

    def test_ipv6_is_normalised_so_one_client_gets_one_bucket(self):
        """`2001:db8::1` and `2001:0db8:0000::0001` are the same client and must not get two
        allowances."""
        from app.core.client_ip import client_ip

        first = client_ip(
            _fake_request({"cf-connecting-ip": "2001:0db8:0000:0000:0000:0000:0000:0001"})
        )
        second = client_ip(_fake_request({"cf-connecting-ip": "2001:db8::1"}))
        assert first == second == "2001:db8::1"

    def test_the_address_never_reaches_a_log_line(self):
        from app.core.client_ip import UNKNOWN_CLIENT, client_log_id

        assert client_log_id("203.0.113.7") != "203.0.113.7"
        assert "203.0.113" not in client_log_id("203.0.113.7")
        # Stable, or it would not correlate two requests from one visitor.
        assert client_log_id("203.0.113.7") == client_log_id("203.0.113.7")
        assert client_log_id(UNKNOWN_CLIENT) == UNKNOWN_CLIENT


def _fake_request(headers: dict, client_host: str | None = None):
    """A stand-in for `starlette.Request` carrying only what `client_ip` reads."""

    class _Client:
        host = client_host

    class _Request:
        def __init__(self):
            self.headers = {k.lower(): v for k, v in headers.items()}
            self.client = _Client() if client_host else None

    request = _Request()
    # Starlette's headers are case-insensitive; the dict above already is, via lowering.
    return request
