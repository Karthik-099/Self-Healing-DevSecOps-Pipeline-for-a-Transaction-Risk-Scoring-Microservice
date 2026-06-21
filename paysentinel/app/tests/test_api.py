import pytest
from httpx import AsyncClient, ASGITransport
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app


@pytest.mark.asyncio
async def test_health():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_score_valid():
    payload = {
        "transaction_id": "api_tx001",
        "amount": 50.0,
        "merchant_category": "grocery",
        "country": "US",
        "timestamp": "2024-01-01T00:00:00Z",
        "account_age_days": 365,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/score", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["transaction_id"] == "api_tx001"
    assert 0 <= data["risk_score"] <= 100
    assert isinstance(data["flagged"], bool)


@pytest.mark.asyncio
async def test_score_high_risk():
    payload = {
        "transaction_id": "api_tx002",
        "amount": 9000.0,
        "merchant_category": "grocery",
        "country": "NG",
        "timestamp": "2024-01-01T00:00:00Z",
        "account_age_days": 5,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/score", json=payload)
    assert resp.status_code == 200
    assert resp.json()["flagged"] is True


@pytest.mark.asyncio
async def test_metrics_endpoint():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/metrics")
    assert resp.status_code == 200
    assert b"paysentinel_requests_total" in resp.content
