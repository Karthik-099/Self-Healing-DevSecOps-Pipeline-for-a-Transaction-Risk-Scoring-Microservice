import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response
from pydantic import BaseModel, field_validator

from logging_config import logger
from risk_model import score_transaction


class TransactionRequest(BaseModel):
    transaction_id: str
    amount: float
    merchant_category: str
    country: str
    timestamp: str
    account_age_days: int
    account_id: str = "default"

    @field_validator("amount")
    @classmethod
    def amount_must_be_numeric(cls, v):
        if not isinstance(v, (int, float)):
            raise ValueError("amount must be numeric")
        return v

    @field_validator("account_age_days")
    @classmethod
    def age_non_negative(cls, v):
        if v < 0:
            raise ValueError("account_age_days must be >= 0")
        return v


class ScoreResponse(BaseModel):
    transaction_id: str
    risk_score: int
    flagged: bool
    reasons: list[str]


REQUESTS_TOTAL = Counter("paysentinel_requests_total", "Total score requests")
FLAGGED_TOTAL = Counter("paysentinel_flagged_total", "Total flagged transactions")
LATENCY = Histogram("paysentinel_request_latency_seconds", "Request latency")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("PaySentinel starting up")
    yield
    logger.info("PaySentinel shutting down")


app = FastAPI(title="PaySentinel", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/score", response_model=ScoreResponse)
async def score(req: TransactionRequest, request: Request):
    start = time.time()
    REQUESTS_TOTAL.inc()
    try:
        result = score_transaction(
            transaction_id=req.transaction_id,
            amount=req.amount,
            merchant_category=req.merchant_category,
            country=req.country,
            account_age_days=req.account_age_days,
            account_id=req.account_id,
        )
    except Exception as e:
        logger.error("scoring_error", extra={"transaction_id": req.transaction_id, "error": str(e)})
        raise HTTPException(status_code=500, detail="scoring failed")

    latency_ms = round((time.time() - start) * 1000, 2)
    if result.flagged:
        FLAGGED_TOTAL.inc()

    logger.info(
        "transaction_scored",
        extra={
            "transaction_id": req.transaction_id,
            "risk_score": result.risk_score,
            "flagged": result.flagged,
            "latency_ms": latency_ms,
            "country": req.country,
            "merchant_category": req.merchant_category,
        },
    )
    return ScoreResponse(
        transaction_id=req.transaction_id,
        risk_score=result.risk_score,
        flagged=result.flagged,
        reasons=result.reasons,
    )


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    with open("/app/ui/index.html") as f:
        return HTMLResponse(content=f.read())
