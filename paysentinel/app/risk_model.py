from collections import defaultdict, deque
from dataclasses import dataclass, field
from time import time


HIGH_RISK_COUNTRIES = {"NG", "RU", "KP", "IR", "BY", "MM", "SY", "YE", "SO", "LY"}

MERCHANT_AMOUNT_THRESHOLDS = {
    "grocery": 500,
    "electronics": 5000,
    "travel": 10000,
    "entertainment": 1000,
    "restaurant": 300,
    "fuel": 200,
    "healthcare": 3000,
    "other": 2000,
}

_velocity_store: dict[str, deque] = defaultdict(lambda: deque())
VELOCITY_WINDOW_SECONDS = 300
VELOCITY_MAX_ALLOWED = 5


@dataclass
class ScoreResult:
    risk_score: int
    flagged: bool
    reasons: list[str] = field(default_factory=list)


def _velocity_check(transaction_id: str, account_id: str) -> tuple[int, list[str]]:
    now = time()
    window = _velocity_store[account_id]
    while window and now - window[0] > VELOCITY_WINDOW_SECONDS:
        window.popleft()
    window.append(now)
    count = len(window)
    if count > VELOCITY_MAX_ALLOWED:
        return 30, [f"high transaction velocity: {count} transactions in 5 minutes"]
    return 0, []


def score_transaction(
    transaction_id: str,
    amount: float,
    merchant_category: str,
    country: str,
    account_age_days: int,
    account_id: str = "default",
) -> ScoreResult:
    score = 0
    reasons: list[str] = []

    category = merchant_category.lower().strip()
    threshold = MERCHANT_AMOUNT_THRESHOLDS.get(category, MERCHANT_AMOUNT_THRESHOLDS["other"])
    if amount > threshold:
        score += 25
        reasons.append(f"amount {amount} exceeds typical {category} threshold of {threshold}")

    if amount <= 0:
        score += 20
        reasons.append("non-positive transaction amount")

    if country.upper() in HIGH_RISK_COUNTRIES:
        score += 30
        reasons.append(f"transaction originates from high-risk country: {country.upper()}")

    if account_age_days < 30:
        score += 20
        reasons.append(f"new account: {account_age_days} days old")
    elif account_age_days < 90:
        score += 10
        reasons.append(f"relatively new account: {account_age_days} days old")

    vel_score, vel_reasons = _velocity_check(transaction_id, account_id)
    score += vel_score
    reasons.extend(vel_reasons)

    risk_score = min(score, 100)
    return ScoreResult(risk_score=risk_score, flagged=risk_score >= 60, reasons=reasons)
