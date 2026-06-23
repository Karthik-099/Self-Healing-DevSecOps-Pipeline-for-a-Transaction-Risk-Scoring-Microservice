import argparse
import json
import os
import sys

import requests


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rollback-handler-url", required=True, help="Endpoint that accepts Splunk webhook payload")
    ap.add_argument("--payload", required=True, help="Path to alert_webhook_payload.json")
    args = ap.parse_args()

    payload = json.loads(open(args.payload, "r", encoding="utf-8").read())
    r = requests.post(args.rollback_handler_url, json=payload, timeout=15)
    print(json.dumps({"status_code": r.status_code, "body": r.text}, indent=2))


if __name__ == "__main__":
    main()

