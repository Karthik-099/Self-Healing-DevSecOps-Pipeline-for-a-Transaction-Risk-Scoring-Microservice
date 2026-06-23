# Splunk Simulation / Replay (Local)

This folder contains a local simulation harness to generate realistic PaySentinel transaction traffic, emit structured JSON logs in the same shape your Fluent Bit + Splunk pipeline expects, and run the Splunk saved-search logic over the generated events.

## What it does

- Generates dummy transactions and calls the PaySentinel `/score` API.
- Writes the resulting JSON logs to a local directory using the same JSON logging schema.
- Runs a local evaluator that mirrors the logic of `paysentinel/splunk_queries.spl` (error rate, p95 latency approximation, flagged transaction rate, risk distribution, and the error-rate alert condition).
- Optionally prepares a webhook payload you can feed into `paysentinel/remediation/rollback_handler.py`.

This keeps the flow end-to-end without requiring any external Splunk instance.


## Run

1) Start the app locally:

```bash
cd paysentinel
python3 -m venv .venv && source .venv/bin/activate
pip install -r app/requirements.txt
uvicorn app.main:app --reload --port 8000
```

2) In another terminal, run the simulation:

```bash
cd ..
python3 paysentinel/splunk_simulator/run_replay.py \
  --api-url http://localhost:8000 \
  --out-dir ./splunk_simulator_output \
  --transactions 200 \
  --account-id acct-001 \
  --emit-interval-ms 10 \
  --inject-error-rate 0.03
```

3) Inspect results:

```bash
ls -la splunk_simulator_output
cat splunk_simulator_output/search_results.json
cat splunk_simulator_output/alert_webhook_payload.json
```

## Inputs / Controls

- `--inject-error-rate`: Forces a fraction of requests to generate an error log entry (to trigger the saved alert condition logic).
- `--account-id`: Uses one account id to make the velocity rule realistic.
- `--emit-interval-ms`: Spacing between requests.

## Mapping to existing repo files

- Generated JSON logs match the shape emitted by `paysentinel/app/logging_config.py` and `paysentinel/app/main.py`.
- Query logic is aligned to `paysentinel/splunk_queries.spl`.
- Webhook payload structure is aligned to `paysentinel/remediation/rollback_handler.py` expectations (uses `result.savedsearch_name`).

