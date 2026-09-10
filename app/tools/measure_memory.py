"""What one API process actually costs, and whether that cost grows with traffic.

    python -m app.tools.measure_memory [--turns 500]

Seeds an organisation, a chatbot on Ollama and a small corpus, starts uvicorn against the
local compose stack, drives chat turns through the widget endpoint and samples the server
process's resident memory as it goes. Prints the series and the growth per hundred turns.

Deliberately not an HTTP endpoint and deliberately not `tracemalloc`. The number that matters
is the one the kubelet sees, which is RSS read from outside the process — a diagnostic route
would measure the wrong thing and would have to be shipped to production to do it. Linux
only, because `/proc` is where that number lives and Linux is what the pods run.

Needs Postgres, Redis and Ollama up:

    docker compose -f infra/docker/docker-compose.yml up -d postgres redis
    ollama pull qwen3:0.6b && ollama pull nomic-embed-text
"""

import argparse
import asyncio
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx

from app.db.session import dispose_engines, tenant_session
from app.models import Document, DocumentChunk, DocumentStatus, FileType
from app.schemas.ai_config import AIConfigUpdate
from app.schemas.chatbot import ChatbotCreate
from app.services.ai import factory
from app.services.ai_config import save_config
from app.services.auth import signup
from app.services.chatbot import create_chatbot

# Small enough to answer quickly on a laptop GPU, which is what makes 500 turns a coffee
# break rather than an afternoon. None of it is a judgement about answer quality; 64 is the
# smallest budget the schema accepts.
CHAT_MODEL = "qwen3:0.6b"
EMBEDDING_MODEL = "nomic-embed-text"
MAX_TOKENS = 64

SITE = "https://measure.example"
CORPUS = [
    "Refunds are issued to the original payment method within five working days.",
    "The XR-7742B flange requires a torque of 40 Nm on the mounting bracket.",
    "Support is open Monday to Friday, 9am to 5pm Central European Time.",
    "To reset a password, open the sign-in page and choose Forgotten password.",
    "Orders above 100 euro ship free of charge inside the European Union.",
]
QUESTIONS = [
    "how long does a refund take",
    "what torque does the flange need",
    "when is support open",
    "how do I reset my password",
    "is shipping free",
]


def rss_mib(pid: int) -> float:
    """Resident set size of another process, the way the kubelet accounts for it."""
    for line in Path(f"/proc/{pid}/status").read_text().splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) / 1024.0
    raise RuntimeError(f"no VmRSS for pid {pid}")


async def seed() -> tuple[str, str]:
    """An organisation, a chatbot pointed at Ollama, and enough corpus to retrieve from."""
    suffix = uuid.uuid4().hex[:8]
    org, _user, _token = await signup(
        organization_name=f"Memory probe {suffix}",
        email=f"probe-{suffix}@example.com",
        password="a-sufficiently-long-password",
        full_name=None,
    )
    chatbot, _secret = await create_chatbot(
        org.id,
        ChatbotCreate(
            name=f"probe-{suffix}",
            system_prompt="Answer in one short sentence.",
            allowed_origins=[SITE],
            model_config_json={"temperature": 0.0, "max_tokens": MAX_TOKENS},
        ),
    )

    base_url = os.environ.get("PROBE_OLLAMA_URL", "http://127.0.0.1:11434")
    await save_config(
        org.id,
        chatbot.id,
        AIConfigUpdate.model_validate(
            {
                "chat": {
                    "provider": "ollama",
                    "model": CHAT_MODEL,
                    "connection": {"base_url": base_url, "think": False},
                },
                "embedding": {
                    "provider": "ollama",
                    "model": EMBEDDING_MODEL,
                    "connection": {"base_url": base_url},
                },
            }
        ),
    )

    embedder = await factory.get_embedding_provider(org.id, chatbot.id)
    vectors = await embedder.embed_batch(CORPUS)

    async with tenant_session(org.id) as session:
        document = Document(
            org_id=org.id,
            chatbot_id=chatbot.id,
            filename="handbook.md",
            file_type=FileType.MD,
            content_type="text/markdown",
            storage_path="probe/handbook.md",
            size_bytes=sum(len(body) for body in CORPUS),
            chunk_count=len(CORPUS),
            status=DocumentStatus.READY,
        )
        session.add(document)
        await session.flush()
        document_id = document.id
        for index, (body, vector) in enumerate(zip(CORPUS, vectors, strict=True)):
            session.add(
                DocumentChunk(
                    org_id=org.id,
                    document_id=document_id,
                    chatbot_id=chatbot.id,
                    chunk_index=index,
                    content=body,
                    embedding_dim=len(vector),
                    embedding=vector,
                )
            )

    return chatbot.public_key, str(chatbot.id)


def start_api(port: int) -> subprocess.Popen[bytes]:
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return process


async def wait_ready(client: httpx.AsyncClient, deadline: float = 60.0) -> None:
    started = time.monotonic()
    while time.monotonic() - started < deadline:
        try:
            if (await client.get("/health/ready", timeout=5.0)).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        await asyncio.sleep(0.5)
    raise RuntimeError("the API never became ready")


async def one_turn(client: httpx.AsyncClient, public_key: str, question: str) -> None:
    """One widget chat turn, drained to the end so the server finishes the whole path."""
    async with client.stream(
        "POST",
        "/public/widget/chat",
        json={"message": question, "session_id": uuid.uuid4().hex},
        headers={"X-Chatbot-Key": public_key, "Origin": SITE},
        timeout=120.0,
    ) as response:
        response.raise_for_status()
        async for _ in response.aiter_bytes():
            pass


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--turns", type=int, default=500)
    parser.add_argument("--port", type=int, default=8099)
    parser.add_argument("--sample-every", type=int, default=100)
    args = parser.parse_args()

    print("seeding...", flush=True)
    public_key, chatbot_id = await seed()
    await dispose_engines()
    print(f"chatbot {chatbot_id}, arenas={os.environ.get('MALLOC_ARENA_MAX', '(unset)')}")

    server = start_api(args.port)
    samples: list[tuple[int, float]] = []
    try:
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{args.port}") as client:
            await wait_ready(client)
            # Sample zero is after startup and before any traffic: the floor the process
            # costs simply by existing, which is the number the Helm request has to cover.
            samples.append((0, rss_mib(server.pid)))
            print(f"{0:6d} turns  {samples[0][1]:8.1f} MiB", flush=True)

            for turn in range(1, args.turns + 1):
                await one_turn(client, public_key, QUESTIONS[turn % len(QUESTIONS)])
                if turn % args.sample_every == 0:
                    samples.append((turn, rss_mib(server.pid)))
                    print(f"{turn:6d} turns  {samples[-1][1]:8.1f} MiB", flush=True)
    finally:
        server.send_signal(signal.SIGTERM)
        server.wait(timeout=30)

    floor, ceiling = samples[0][1], samples[-1][1]
    turns = samples[-1][0] or 1
    print()
    print(f"start {floor:.1f} MiB, end {ceiling:.1f} MiB over {turns} turns")
    print(f"growth {(ceiling - floor) / turns * 100:+.2f} MiB per 100 turns")
    return 0


if __name__ == "__main__":
    if not Path("/proc/self/status").exists():
        raise SystemExit("This reads /proc, so it needs Linux — run it inside the api image.")
    raise SystemExit(asyncio.run(main()))
