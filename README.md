# PaySentinel

A transaction risk-scoring microservice with a self-healing DevSecOps pipeline. Incoming transactions are scored 0-100 for fraud risk using a rule-based engine. The pipeline runs security gates on every commit, deploys to AWS EKS, and automatically rolls back if Splunk detects anomalies post-deploy.

---

## Architecture

```
GitHub
  |
  v
Jenkins (CI/CD)
  |-- pytest + coverage
  |-- SonarQube quality gate (SAST)
  |-- Docker build (multi-stage, non-root)
  |-- Trivy image scan (blocks on HIGH/CRITICAL CVEs)
  |-- Push to Docker Hub (main/release branches only)
  |-- kubectl rolling deploy to AWS EKS
  |
  v
AWS EKS
  |-- paysentinel pods (FastAPI, port 8000)
  |-- Fluent Bit DaemonSet -> Splunk HEC
  |-- HPA (CPU-based, 2-8 replicas)
  |
  v
Splunk
  |-- Dashboards: error rate, p95 latency, flagged-transaction rate
  |-- Saved search alert: error rate > threshold over 5 min
  |-- Webhook -> rollback_handler.py
  |
  v
rollback_handler.py (Lambda or local script)
  |-- Checks deployment age
  |-- If recent deploy + alert firing: kubectl rollout undo
```

---

## Branch Strategy

| Branch | Purpose |
|--------|---------|
| `main` | Production-ready code. Protected. Merges trigger full pipeline + EKS deploy. |
| `dev` | Active development integration branch. |
| `test` | QA / integration testing branch. |
| `release/*` | Release candidates. Also triggers deploy pipeline. |

---

## Repository Structure

```
paysentinel/
  app/
    main.py               FastAPI: POST /score, GET /health, GET /metrics, GET /
    risk_model.py         Rule-based scorer with velocity tracking
    logging_config.py     Structured JSON logging for Splunk ingestion
    requirements.txt
    tests/
      test_risk_model.py  Unit tests (model logic)
      test_api.py         Integration tests (HTTP layer)
  ui/
    index.html            Browser dashboard for live transaction scoring
  infra/
    terraform/
      main.tf             VPC + EKS cluster (SPOT instances)
      ecr.tf              ECR repository with lifecycle policy
      iam.tf              IRSA role for pod-level AWS access
      variables.tf
  k8s/
    deployment.yaml       Rolling update, resource limits, health probes
    service.yaml          LoadBalancer service
    hpa.yaml              CPU-based autoscaling (2-8 replicas)
    fluent-bit-configmap.yaml  Log shipping to Splunk HEC
  remediation/
    rollback_handler.py   Self-healing rollback (Lambda-compatible)
    requirements.txt
  splunk_queries.spl      SPL searches for dashboards and alerts
  Dockerfile              Multi-stage, python:3.12-slim, non-root
  Jenkinsfile             Declarative pipeline (all stages)
  sonar-project.properties
  pytest.ini
docker-compose.yml        Full local stack (app + Jenkins + SonarQube + Splunk)
```

---

## Scoring Rules

| Rule | Score Added | Threshold |
|------|------------|-----------|
| Amount exceeds merchant category threshold | +25 | grocery $500, electronics $5000, travel $10000 |
| Non-positive amount | +20 | <= 0 |
| High-risk country | +30 | NG, RU, KP, IR, BY, MM, SY, YE, SO, LY |
| New account | +20 | < 30 days |
| Relatively new account | +10 | 30-89 days |
| High velocity | +30 | > 5 transactions in 5 minutes (same account) |

Score is capped at 100. Transactions with score >= 60 are flagged.

---

## Local Setup

### Prerequisites

- Python 3.12
- Docker and Docker Compose
- Git

### Virtual environment

```bash
cd paysentinel
python3 -m venv .venv
source .venv/bin/activate
pip install -r app/requirements.txt
```

### Run tests

```bash
cd paysentinel
source .venv/bin/activate
pytest app/tests/ -v
```

### Run the app locally

```bash
cd paysentinel
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

API is at `http://localhost:8000`. Dashboard at `http://localhost:8000/`.

### Score a transaction

```bash
curl -X POST http://localhost:8000/score \
  -H "Content-Type: application/json" \
  -d '{
    "transaction_id": "tx-001",
    "amount": 9000,
    "merchant_category": "grocery",
    "country": "NG",
    "timestamp": "2024-01-01T00:00:00Z",
    "account_age_days": 10
  }'
```

### Build and run with Docker

```bash
cd paysentinel
docker build -t paysentinel:local .
docker run -p 8000:8000 paysentinel:local
```

---

## Full Local Stack (Docker Compose)

```bash
docker-compose up -d
```

| Service | URL | Credentials |
|---------|-----|-------------|
| PaySentinel app | http://localhost:8000 | — |
| Jenkins | http://localhost:8080 | admin / (initial password in container logs) |
| SonarQube | http://localhost:9000 | admin / admin |
| Splunk | http://localhost:5601 | admin / PaySentinel123! |

---

## Jenkins Pipeline Setup

Assumes Jenkins is running at http://localhost:8080 with these plugins installed:
- Pipeline, Git, SonarQube Scanner, Coverage, Docker Pipeline

Steps:

1. In Jenkins > Manage Jenkins > Configure System, add a SonarQube server named `SonarQube` pointing at `http://sonarqube:9000`.
2. Add credentials:
   - `dockerhub-credentials` (Username/Password) — your Docker Hub login
   - `kubeconfig-eks` (Secret file) — your EKS kubeconfig
3. Create a Multibranch Pipeline job pointing at this repository.
4. The Jenkinsfile is at `paysentinel/Jenkinsfile`. Set the Script Path to that value in the job config.

Pipeline stages:
1. Checkout
2. Setup Python (venv + pip)
3. Unit Tests (pytest, coverage report)
4. SonarQube Analysis + Quality Gate
5. Docker Build (tagged with git short SHA)
6. Trivy Image Scan (fails on HIGH/CRITICAL)
7. Push to Docker Hub (main and release/* branches only)
8. Deploy to EKS (main and release/* branches only)

---

## AWS Infrastructure (Terraform)

```bash
cd paysentinel/infra/terraform

# Create the S3 backend bucket first (one-time)
aws s3 mb s3://paysentinel-tfstate --region us-east-1

terraform init
terraform plan -var="dockerhub_username=<your-dockerhub-username>"
terraform apply -var="dockerhub_username=<your-dockerhub-username>"

# Update kubeconfig after cluster creation
aws eks update-kubeconfig --region us-east-1 --name paysentinel
```

You will need to provide:
- `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` (or an IAM role)
- The S3 bucket name for Terraform state (update `backend.tf` if you change it)

---

## Splunk Observability

Splunk runs locally via Docker Compose. The HEC endpoint is `http://splunk:8088`.

In production (Splunk Cloud or Splunk Enterprise), replace `SPLUNK_HEC_HOST` and `SPLUNK_HEC_TOKEN` in `k8s/fluent-bit-configmap.yaml`.

SPL queries for dashboards are in `paysentinel/splunk_queries.spl`:
- Error rate (1-minute buckets)
- P95 latency
- Flagged transaction rate
- Risk score distribution
- Alert search: error count > 10/min over 5 min

To wire the alert webhook to the rollback handler, set the alert action URL to the Lambda function URL or the endpoint where `rollback_handler.py` is running.

---

## Splunk Simulation / Replay (Local)

To validate the end-to-end flow (transaction scoring -> log events -> saved-search conditions -> webhook payload -> rollback handler contract) without requiring a running Splunk instance, the repo includes a replay harness.

### Files

- `paysentinel/splunk_simulator/run_replay.py`: Generates realistic scoring traffic by calling `POST /score`, writes replay events to disk, and computes search results aligned with `paysentinel/splunk_queries.spl`.
- `paysentinel/splunk_simulator/simulate_rollback_webhook.py`: Sends the generated webhook payload to a rollback handler endpoint.

### Run

1) Start the app locally:

```bash
cd paysentinel
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

2) Install replay dependencies (separately):

```bash
pip install -r paysentinel/splunk_simulator/requirements.txt
```

3) Execute replay with controlled error injection and velocity burst:

```bash
python3 paysentinel/splunk_simulator/run_replay.py \
  --api-url http://localhost:8000 \
  --out-dir ./splunk_simulator_output \
  --transactions 250 \
  --account-id acct-001 \
  --emit-interval-ms 5 \
  --inject-error-rate 0.04 \
  --velocity-burst
```

Outputs:
- `splunk_simulator_output/paysentinel-replay.log`: JSON replay events.
- `splunk_simulator_output/search_results.json`: Evaluated metrics + `alert` block.
- `splunk_simulator_output/alert_webhook_payload.json`: Webhook payload in the shape expected by `remediation/rollback_handler.py`.

### Trigger webhook contract (optional)

If your rollback handler is reachable over HTTP, send the payload:

```bash
python3 paysentinel/splunk_simulator/simulate_rollback_webhook.py \
  --rollback-handler-url http://localhost:8081/webhook \
  --payload ./splunk_simulator_output/alert_webhook_payload.json
```

If you run rollback handler locally as a script, you can load `alert_webhook_payload.json` and pass it as the `event` to `handle(event)`.

---


## Self-Healing Rollback

`remediation/rollback_handler.py` receives the Splunk alert webhook payload and:
1. Loads kube config (in-cluster or from file)
2. Checks how long ago the deployment last rolled out
3. If the deployment is within the configured window (default 30 minutes), triggers `kubectl rollout undo`
4. If `DRY_RUN=true` (default), logs what it would do without executing

Test the handler locally:

```bash
cd paysentinel
pip install -r remediation/requirements.txt
DRY_RUN=true DEPLOYMENT_NAME=paysentinel NAMESPACE=paysentinel \
  python remediation/rollback_handler.py
```

Deploy as a Lambda function by zipping `rollback_handler.py` + `requirements.txt`, or run it as a sidecar/script on an EC2 instance reachable by Splunk's webhook.

---

## Credentials and Secrets Required

You need to supply these before deploying:

| Secret | Where |
|--------|-------|
| Docker Hub username + password | Jenkins credential `dockerhub-credentials` |
| EKS kubeconfig | Jenkins credential `kubeconfig-eks` |
| Splunk HEC token | `k8s/fluent-bit-configmap.yaml` — replace `SPLUNK_HEC_TOKEN` |
| Splunk HEC host | `k8s/fluent-bit-configmap.yaml` — replace `SPLUNK_HEC_HOST` |
| AWS credentials | Environment variables or IAM role for Terraform and kubectl |
| SonarQube token | Jenkins credential auto-generated by SonarQube plugin |

---

## Build Phases

| Phase | Scope | Status |
|-------|-------|--------|
| 1 | App + Dockerfile + Jenkinsfile (test/build/scan) | Complete |
| 2 | Terraform EKS + ECR, Jenkins deploy stages | Complete |
| 3 | Fluent Bit + Splunk dashboards and alert | Complete |
| 4 | Self-healing rollback handler | Complete |
