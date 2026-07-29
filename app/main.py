import asyncio
import logging
import re
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
from app.telemetry import complete_trace, get_trace, record_stage, start_trace
from app.text_utils import (
    contains_prompt_injection,
    contains_sensitive_extraction_request,
    contains_unsupported_realtime_request,
    redact_pii,
)

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
TRACE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{8,128}$")


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
    start_trace(request_id, payload.tenant_id)
    input_guardrail_started = time.perf_counter()
    if contains_prompt_injection(question):
        GUARDRAIL_BLOCKS.labels("prompt_injection").inc()
        REQUESTS.labels("chat", "blocked").inc()
        record_stage(
            request_id,
            name="input_guardrail",
            status="blocked",
            summary="Prompt-injection policy blocked the request before retrieval.",
            duration_ms=round((time.perf_counter() - input_guardrail_started) * 1000),
            metrics={"retrieval_started": False},
        )
        complete_trace(
            request_id,
            status="blocked",
            duration_ms=round((time.perf_counter() - started) * 1000),
        )
        return JSONResponse(
            status_code=400,
            content={
                "detail": "The request was blocked by the prompt-injection guardrail.",
                "request_id": request_id,
            },
        )
    if contains_sensitive_extraction_request(question):
        GUARDRAIL_BLOCKS.labels("sensitive_extraction").inc()
        REQUESTS.labels("chat", "blocked").inc()
        record_stage(
            request_id,
            name="input_guardrail",
            status="blocked",
            summary="Sensitive-credential extraction policy blocked the request before retrieval.",
            duration_ms=round((time.perf_counter() - input_guardrail_started) * 1000),
            metrics={"retrieval_started": False},
        )
        complete_trace(
            request_id,
            status="blocked",
            duration_ms=round((time.perf_counter() - started) * 1000),
        )
        return JSONResponse(
            status_code=400,
            content={
                "detail": "The request was blocked by the sensitive-information guardrail.",
                "request_id": request_id,
            },
        )
    if contains_unsupported_realtime_request(question):
        GUARDRAIL_BLOCKS.labels("unsupported_realtime").inc()
        REQUESTS.labels("chat", "bounded_refusal").inc()
        record_stage(
            request_id,
            name="scope_guardrail",
            status="blocked",
            summary=(
                "The domain boundary refused an unsupported real-time request before retrieval."
            ),
            duration_ms=round((time.perf_counter() - input_guardrail_started) * 1000),
            metrics={"retrieval_started": False, "model_called": False},
        )
        complete_trace(
            request_id,
            status="blocked",
            duration_ms=round((time.perf_counter() - started) * 1000),
        )
        return ChatResponse(
            answer="Current weather is not available in the approved knowledge base.",
            sources=[],
            request_id=request_id,
            grounded=False,
        )
    record_stage(
        request_id,
        name="input_guardrail",
        status="pass",
        summary="Input policy checks completed without logging prompt content.",
        duration_ms=round((time.perf_counter() - input_guardrail_started) * 1000),
    )
    try:
        retrieval_started = time.perf_counter()
        chunks = retrieve(question, payload.tenant_id)
        RETRIEVAL_COUNT.observe(len(chunks))
        record_stage(
            request_id,
            name="retrieval",
            status="pass" if chunks else "partial",
            summary="Tenant-filtered vector retrieval completed.",
            duration_ms=round((time.perf_counter() - retrieval_started) * 1000),
            metrics={
                "chunks": len(chunks),
                "documents": len({item["document"] for item in chunks}),
                "top_score": round(max((item["score"] for item in chunks), default=0), 4),
                "tenant_filtering": True,
            },
        )
        generation_started = time.perf_counter()
        raw_answer = await generate_answer(
            question,
            chunks,
            payload.tenant_id,
            payload.max_tokens,
        )
        record_stage(
            request_id,
            name="generation",
            status="pass",
            summary="The model generated an answer from the assembled retrieved context.",
            duration_ms=round((time.perf_counter() - generation_started) * 1000),
            metrics={
                "model": settings.openai_model,
                "max_output_tokens": payload.max_tokens,
                "grounded_context": bool(chunks),
            },
        )
        validation_started = time.perf_counter()
        answer = redact_pii(raw_answer)
        record_stage(
            request_id,
            name="output_validation",
            status="pass",
            summary="Output privacy filtering and grounded-response metadata completed.",
            duration_ms=round((time.perf_counter() - validation_started) * 1000),
            metrics={
                "pii_redacted": answer != raw_answer,
                "grounded": bool(chunks),
                "sources_returned": len(chunks),
            },
        )
        REQUESTS.labels("chat", "success").inc()
        complete_trace(
            request_id,
            status="success",
            duration_ms=round((time.perf_counter() - started) * 1000),
        )
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
        record_stage(
            request_id,
            name="dependency_error",
            status="error",
            summary="A model or database dependency failed; no dependency details were exposed.",
            duration_ms=round((time.perf_counter() - started) * 1000),
            metrics={"error_type": type(exc).__name__},
        )
        complete_trace(
            request_id,
            status="error",
            duration_ms=round((time.perf_counter() - started) * 1000),
        )
        logger.error(
            "generation_failed request_id=%s error_type=%s",
            request_id,
            type(exc).__name__,
        )
        return JSONResponse(
            status_code=503,
            content={
                "detail": "The AI or database service is unavailable.",
                "request_id": request_id,
            },
        )
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
        "request_trace_endpoint": "/api/monitoring/requests/{request_id}",
        "trace_schema_version": "1.0",
        "tracked": [
            "request count",
            "latency",
            "guardrail blocks",
            "retrieval count",
            "request-correlated RAG stages",
        ],
        "log_policy": "Prompts, responses, and API keys are not written to application logs.",
    }


@app.get(
    "/api/monitoring/requests/{request_id}",
    dependencies=[Depends(require_monitoring_key)],
)
async def request_trace(request_id: str) -> JSONResponse:
    if not TRACE_ID_PATTERN.fullmatch(request_id):
        raise HTTPException(status_code=400, detail="Invalid request trace identifier.")
    trace = get_trace(request_id)
    if not trace:
        raise HTTPException(status_code=404, detail="Request trace was not found or expired.")
    return JSONResponse(trace, headers={"Cache-Control": "no-store"})


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
