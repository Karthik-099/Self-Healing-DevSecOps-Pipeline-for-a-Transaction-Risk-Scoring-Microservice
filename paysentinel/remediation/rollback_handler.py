import json
import os
import sys
import logging
from datetime import datetime, timezone, timedelta

import boto3
from kubernetes import client, config
from kubernetes.client.rest import ApiException

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("rollback_handler")

DEPLOYMENT_NAME = os.getenv("DEPLOYMENT_NAME", "paysentinel")
NAMESPACE = os.getenv("NAMESPACE", "paysentinel")
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
RECENT_DEPLOY_WINDOW_MINUTES = int(os.getenv("RECENT_DEPLOY_WINDOW_MINUTES", "30"))


def _load_kube_config():
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()


def _get_deployment_age_minutes(apps_v1: client.AppsV1Api) -> float | None:
    try:
        dep = apps_v1.read_namespaced_deployment(DEPLOYMENT_NAME, NAMESPACE)
        last_update = None
        for cond in dep.status.conditions or []:
            if cond.type == "Progressing" and cond.reason == "NewReplicaSetAvailable":
                last_update = cond.last_update_time
                break
        if last_update is None:
            return None
        age = (datetime.now(timezone.utc) - last_update).total_seconds() / 60
        return age
    except ApiException as e:
        log.error("failed to read deployment: %s", e)
        return None


def _rollback(apps_v1: client.AppsV1Api) -> dict:
    if DRY_RUN:
        log.warning("[DRY RUN] would execute: kubectl rollout undo deployment/%s -n %s", DEPLOYMENT_NAME, NAMESPACE)
        return {"action": "dry_run_rollback", "deployment": DEPLOYMENT_NAME, "namespace": NAMESPACE}

    body = {
        "spec": {
            "template": {
                "metadata": {
                    "annotations": {
                        "kubectl.kubernetes.io/last-applied-configuration": ""
                    }
                }
            }
        }
    }
    try:
        apps_v1.create_namespaced_deployment_rollback(
            DEPLOYMENT_NAME,
            NAMESPACE,
            {
                "name": DEPLOYMENT_NAME,
                "rollbackTo": {"revision": 0},
            },
        )
    except ApiException:
        patch = {"spec": {"rollbackTo": {"revision": 0}}}
        apps_v1.patch_namespaced_deployment(DEPLOYMENT_NAME, NAMESPACE, patch)

    log.info("rollback triggered for %s/%s", NAMESPACE, DEPLOYMENT_NAME)
    return {"action": "rollback_triggered", "deployment": DEPLOYMENT_NAME, "namespace": NAMESPACE}


def handle(event: dict, context=None) -> dict:
    log.info("received event: %s", json.dumps(event))

    alert_name = event.get("result", {}).get("savedsearch_name", "unknown")
    log.info("alert: %s", alert_name)

    _load_kube_config()
    apps_v1 = client.AppsV1Api()

    age_minutes = _get_deployment_age_minutes(apps_v1)
    if age_minutes is None:
        return {"status": "skipped", "reason": "could not determine deployment age"}

    log.info("deployment last updated %.1f minutes ago", age_minutes)

    if age_minutes > RECENT_DEPLOY_WINDOW_MINUTES:
        log.info("deployment is %.1f min old (threshold %d min) — not rolling back", age_minutes, RECENT_DEPLOY_WINDOW_MINUTES)
        return {"status": "skipped", "reason": "deployment predates alert window"}

    result = _rollback(apps_v1)
    return {"status": "ok", **result}


if __name__ == "__main__":
    sample = {"result": {"savedsearch_name": "paysentinel_error_rate_high"}}
    print(json.dumps(handle(sample), indent=2))
