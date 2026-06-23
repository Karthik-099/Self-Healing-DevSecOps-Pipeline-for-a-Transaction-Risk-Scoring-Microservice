import argparse
import json

import random
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import requests


HIGH_RISK_COUNTRIES = ["NG", "RU", "KP", "IR", "BY", "MM", "SY", "YE", "SO", "LY"]
MERCHANT_CATEGORIES = [
    "grocery",
    "electronics",
    "travel",
    "entertainment",
    "restaurant",
    "fuel",
    "healthcare",
    "other",
]


@dataclass
class TxEvent:
    transaction_id: str
    amount: float
    merchant_category: str
    country: str
    timestamp: str
    account_age_days: int
    account_id: str


def _iso_z(ts: float) -> str:
    # ISO8601 with Z (UTC)
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def generate_transactions(
    n: int,
    account_id: str,
    base_time: float,
    inject_error_rate: float,
    inject_velocity_burst: bool,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for i in range(n):
        ts = base_time + i * 0.01

        # Velocity burst: create tighter timestamps by using a small multiplier
        if inject_velocity_burst and i % 30 < 20:
            ts = base_time + (i % 30) * 0.7  # ~ < 5 mins for the burst window

        tx_id = f"tx-{account_id}-{int(ts)}-{i}".replace(" ", "")
        category = random.choice(MERCHANT_CATEGORIES)

        # Amount distribution (wide) to hit multiple branches in risk model
        amount = round(random.uniform(10, 15000), 2)
        # Bias toward large amounts sometimes
        if random.random() < 0.25:
            amount = round(random.uniform(500, 20000), 2)

        country = random.choice(HIGH_RISK_COUNTRIES) if random.random() < 0.12 else "US"
        account_age_days = int(random.uniform(0, 1200))
        if random.random() < 0.25:
            account_age_days = int(random.uniform(0, 29))  # new accounts
        elif random.random() < 0.25:
            account_age_days = int(random.uniform(30, 89))  # relatively new

        events.append(
            {
                "transaction_id": tx_id,
                "amount": amount,
                "merchant_category": category,
                "country": country,
                "timestamp": _iso_z(ts),
                "account_age_days": account_age_days,
                "account_id": account_id,
                "_simulate": {
                    "should_error_log": random.random() < inject_error_rate,
                },
            }
        )

    return events


def call_api(api_url: str, event: dict[str, Any], timeout_s: float = 10.0):
    payload = {k: event[k] for k in ["transaction_id", "amount", "merchant_category", "country", "timestamp", "account_age_days", "account_id"]}
    t0 = time.time()
    try:
        r = requests.post(f"{api_url}/score", json=payload, timeout=timeout_s)
        latency_ms = round((time.time() - t0) * 1000, 2)
        if r.status_code != 200:
            return None, latency_ms, {"status_code": r.status_code, "error": r.text}
        return r.json(), latency_ms, None
    except Exception as e:
        latency_ms = round((time.time() - t0) * 1000, 2)
        return None, latency_ms, {"exception": str(e)}


def emit_log_lines(
    out_dir: Path,
    cluster: str,
    environment: str,
    results: list[dict[str, Any]],
):
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "paysentinel-replay.log"

    with log_path.open("w", encoding="utf-8") as f:
        for ev in results:
            f.write(json.dumps(ev))
            f.write("\n")

    return log_path


def compute_search_results(results: list[dict[str, Any]], window_minutes: int = 5):
    # Approximate what SPL would compute
    now = time.time()

    # error rate (last 5 minutes): count ERROR level events within window
    window_start = now - window_minutes * 60
    error_events = [r for r in results if r.get("level") == "ERROR" and r.get("timestamp_epoch", 0) >= window_start]
    error_count = len(error_events)

    # p95 latency: use transaction_scored latency_ms
    latencies = [r["latency_ms"] for r in results if "latency_ms" in r and r.get("event_type") == "transaction_scored"]
    if not latencies:
        p95_latency = None
    else:
        s = sorted(latencies)
        idx = min(len(s) - 1, int(len(s) * 0.95))
        p95_latency = s[idx]

    # flagged rate in last window: events with flagged==true
    scored_window = [
        r
        for r in results
        if r.get("event_type") == "transaction_scored" and r.get("timestamp_epoch", 0) >= window_start
    ]
    total = len(scored_window)
    flagged = sum(1 for r in scored_window if r.get("flagged") is True)
    flag_rate = round(flagged / total * 100, 2) if total else 0.0

    # risk distribution: bucket risk_score into span=10 0-100 => 10 buckets
    buckets = {i * 10: 0 for i in range(10)}
    for r in results:
        if r.get("event_type") != "transaction_scored":
            continue
        s = int(r.get("risk_score", 0))
        b = min(9, s // 10) * 10
        buckets[b] = buckets.get(b, 0) + 1

    alert = error_count > 10
    return {
        "error_count": error_count,
        "p95_latency_ms": p95_latency,
        "flagged_count": flagged,
        "total_count": total,
        "flag_rate_pct": flag_rate,
        "risk_distribution": buckets,
        "alert": {
            "savedsearch_name": "paysentinel_error_rate_high",
            "condition": "error_count > 10",
            "error_count": error_count,
            "fires": alert,
        },
    }


def build_webhook_payload(alert_info: dict[str, Any]):
    # Matches rollback_handler.py: event["result"]["savedsearch_name"]
    return {"result": {"savedsearch_name": alert_info.get("savedsearch_name", "paysentinel_error_rate_high")}, "alert": alert_info}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-url", required=True, help="Base URL, e.g. http://localhost:8000")
    ap.add_argument("--out-dir", required=True, help="Directory to write replay outputs")
    ap.add_argument("--transactions", type=int, default=200)
    ap.add_argument("--account-id", default="acct-001")
    ap.add_argument("--emit-interval-ms", type=int, default=10)
    ap.add_argument("--inject-error-rate", type=float, default=0.03)
    ap.add_argument("--velocity-burst", action="store_true", help="Create velocity bursts to trigger rule-based velocity")
    ap.add_argument("--dry-webhook", action="store_true", help="Do not send webhook to rollback handler; just write payload")
    ap.add_argument("--webhook-url", default=None, help="Optional rollback handler endpoint URL")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)

    base_time = time.time()
    txs = generate_transactions(
        n=args.transactions,
        account_id=args.account_id,
        base_time=base_time,
        inject_error_rate=args.inject_error_rate,
        inject_velocity_burst=args.velocity_burst,
    )

    results: list[dict[str, Any]] = []

    for idx, tx in enumerate(txs):
        data, latency_ms, err = call_api(args.api_url, tx)
        timestamp_epoch = time.time()

        # Simulate Fluent Bit -> Splunk JSON event fields. logging_config uses:
        # {timestamp, level, name, message, ... extra...}
        # In addition, the FluentBit record_modifier adds cluster and environment in config.
        if tx["_simulate"]["should_error_log"] or err:
            # Emit an ERROR-level log with message similar to app
            results.append(
                {
                    "timestamp": _iso_z(timestamp_epoch),
                    "timestamp_epoch": timestamp_epoch,
                    "level": "ERROR",
                    "name": "paysentinel",
                    "message": "scoring_error" if not err else "scoring_error_simulated",
                    "transaction_id": tx["transaction_id"],
                    "error": (err or {}).get("error") or (err or {}).get("exception") or "simulated_error",
                    "cluster": "paysentinel-eks",
                    "environment": "production",
                    "sourcetype": "_json",
                    "event_type": "error_event",
                }
            )

        if data:
            results.append(
                {
                    "timestamp": _iso_z(timestamp_epoch),
                    "timestamp_epoch": timestamp_epoch,
                    "level": "INFO",
                    "name": "paysentinel",
                    "message": "transaction_scored",
                    "transaction_id": data["transaction_id"],
                    "risk_score": data["risk_score"],
                    "flagged": data["flagged"],
                    "latency_ms": latency_ms,
                    "country": tx["country"],
                    "merchant_category": tx["merchant_category"],
                    "cluster": "paysentinel-eks",
                    "environment": "production",
                    "sourcetype": "_json",
                    "event_type": "transaction_scored",
                    "reasons": data.get("reasons", []),
                }
            )

        # pacing
        time.sleep(args.emit_interval_ms / 1000.0)

    log_path = emit_log_lines(out_dir, "paysentinel-eks", "production", results)

    search = compute_search_results(results, window_minutes=5)
    search_out = out_dir / "search_results.json"
    search_out.write_text(json.dumps(search, indent=2), encoding="utf-8")

    webhook_payload = build_webhook_payload(search["alert"])
    payload_out = out_dir / "alert_webhook_payload.json"
    payload_out.write_text(json.dumps(webhook_payload, indent=2), encoding="utf-8")

    # Optionally send webhook
    if args.webhook_url:
        if not args.dry_webhook:
            r = requests.post(args.webhook_url, json=webhook_payload, timeout=10)
            (out_dir / "webhook_response.json").write_text(json.dumps({"status_code": r.status_code, "body": r.text}, indent=2), encoding="utf-8")

    print(f"Wrote log file: {log_path}")
    print(f"Wrote search results: {search_out}")
    print(f"Wrote webhook payload: {payload_out}")


if __name__ == "__main__":
    main()

