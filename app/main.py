import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from openai import APIError
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pymongo.errors import PyMongoError

from app.config import get_settings
from app.models import ChatRequest, ChatResponse, Source
from app.rag import generate_answer, mongo_client, retrieve, seed_bundled_corpus
from app.security import (
    require_audit_key,
    require_chatbot_key,
    require_monitoring_key,
)
from app.text_utils import contains_prompt_injection, redact_pii

settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("governai")

REQUESTS = Counter("chatbot_requests_total", "Chatbot requests", ["endpoint", "status"])
LATENCY = Histogram("chatbot_request_duration_seconds", "Chatbot request latency", ["endpoint"])
GUARDRAIL_BLOCKS = Counter(
    "chatbot_guardrail_blocks_total", "Requests blocked by guardrails", ["reason"]
)
RETRIEVAL_COUNT = Histogram("chatbot_retrieved_chunks", "Retrieved chunks per chat")


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("service_started env=%s model=%s", settings.app_env, settings.openai_model)
    try:
        seeded = await asyncio.to_thread(seed_bundled_corpus)
        logger.info("bundled_corpus_ready new_chunks=%d", seeded)
    except (APIError, PyMongoError, RuntimeError, ValueError):
        logger.exception("bundled_corpus_seed_failed")
    yield
    logger.info("service_stopped")


app = FastAPI(
    title="GovernAI Open RAG Chatbot",
    version="1.0.0",
    description="ACI knowledge chatbot using OpenAI generation and embeddings with MongoDB Atlas.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/", include_in_schema=False)
async def home() -> FileResponse:
    return FileResponse(static_dir / "index.html")


@app.get("/health")
async def health() -> dict:
    dependencies = {"openai": "configured", "mongodb": "unreachable"}
    try:
        mongo_client().admin.command("ping")
        dependencies["mongodb"] = "healthy"
    except PyMongoError:
        pass
    ok = dependencies["mongodb"] == "healthy" and dependencies["openai"] == "configured"
    return {"status": "healthy" if ok else "degraded", "dependencies": dependencies}


@app.post("/v1/chat", response_model=ChatResponse, dependencies=[Depends(require_chatbot_key)])
@app.post(
    "/v1/chat/completions",
    response_model=ChatResponse,
    dependencies=[Depends(require_chatbot_key)],
)
async def chat(payload: ChatRequest) -> ChatResponse:
    started = time.perf_counter()
    request_id = str(uuid4())
    question = next(
        (message.content for message in reversed(payload.messages) if message.role == "user"),
        "",
    )
    if contains_prompt_injection(question):
        GUARDRAIL_BLOCKS.labels("prompt_injection").inc()
        REQUESTS.labels("chat", "blocked").inc()
        raise HTTPException(
            status_code=400,
            detail="The request was blocked by the prompt-injection guardrail.",
        )
    try:
        chunks = retrieve(question, payload.tenant_id)
        RETRIEVAL_COUNT.observe(len(chunks))
        answer = redact_pii(
            await generate_answer(
                question,
                chunks,
                payload.tenant_id,
                payload.max_tokens,
            )
        )
        REQUESTS.labels("chat", "success").inc()
        return ChatResponse(
            answer=answer,
            sources=[
                Source(
                    document=item["document"],
                    chunk=item["chunk"],
                    score=round(item["score"], 4),
                )
                for item in chunks
            ],
            request_id=request_id,
            grounded=bool(chunks),
        )
    except (APIError, PyMongoError) as exc:
        REQUESTS.labels("chat", "dependency_error").inc()
        logger.error(
            "generation_failed request_id=%s error_type=%s",
            request_id,
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=503, detail="The AI or database service is unavailable."
        ) from exc
    finally:
        LATENCY.labels("chat").observe(time.perf_counter() - started)


@app.post("/v1/web-chat", response_model=ChatResponse, include_in_schema=False)
async def web_chat(payload: ChatRequest) -> ChatResponse:
    return await chat(payload.model_copy(update={"tenant_id": "aci-infotech"}))


@app.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/api/monitoring/summary", dependencies=[Depends(require_monitoring_key)])
async def monitoring_summary() -> dict:
    return {
        "provider": "Prometheus + Grafana OSS",
        "metrics_endpoint": "/metrics",
        "tracked": ["request count", "latency", "guardrail blocks", "retrieval count"],
        "log_policy": "Prompts, responses, and API keys are not written to application logs.",
    }


@app.get("/api/audit/config", dependencies=[Depends(require_audit_key)])
async def audit_config() -> JSONResponse:
    return JSONResponse(
        {
            "provider": "MongoDB Atlas + OpenAI API",
            "access": "read-only",
            "encryption_in_transit": "TLS is required at the reverse proxy in staging/production",
            "secrets": "environment variables; never returned by this endpoint",
            "data_store": "MongoDB Atlas with tenant-filtered vector search",
            "embedding": "OpenAI text-embedding-3-small",
            "container_hardening": {
                "read_only_root_filesystem": True,
                "capabilities_dropped": "ALL",
                "no_new_privileges": True,
                "non_root_user": True,
            },
            "data_controls": {
                "tenant_filtering": True,
                "pii_response_redaction": True,
                "prompt_injection_guardrail": True,
                "knowledge_base": "Bundled ACI services and industries corpus",
            },
        },
        headers={"Cache-Control": "no-store"},
    )
