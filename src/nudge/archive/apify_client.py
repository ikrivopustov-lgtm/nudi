"""Minimal Apify Actor runner via REST (no apify-client dependency)."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

log = logging.getLogger(__name__)

_API = "https://api.apify.com/v2"
_TIMEOUT = httpx.Timeout(60.0, read=120.0)


class ApifyError(RuntimeError):
    pass


def run_actor(
    actor_id: str,
    run_input: dict[str, Any],
    *,
    token: str,
    wait_secs: int = 180,
    poll_secs: float = 3.0,
) -> list[dict[str, Any]]:
    """Start actor, wait until SUCCEEDED, return dataset items.

    actor_id like ``clockworks/tiktok-transcript-extractor``
    → path ``clockworks~tiktok-transcript-extractor``.
    """
    if not token:
        raise ApifyError("APIFY_TOKEN is empty")

    actor_path = actor_id.replace("/", "~")
    headers = {"Authorization": f"Bearer {token}"}

    with httpx.Client(timeout=_TIMEOUT, headers=headers) as client:
        start = client.post(
            f"{_API}/acts/{actor_path}/runs",
            params={"waitForFinish": 0},
            json=run_input,
        )
        if start.status_code >= 400:
            raise ApifyError(f"start actor {actor_id}: {start.status_code} {start.text[:300]}")
        run = start.json().get("data") or {}
        run_id = run.get("id")
        if not run_id:
            raise ApifyError(f"no run id in response: {start.text[:300]}")

        deadline = time.monotonic() + wait_secs
        status = run.get("status") or "READY"
        while status not in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
            if time.monotonic() > deadline:
                raise ApifyError(f"actor {actor_id} timed out after {wait_secs}s")
            time.sleep(poll_secs)
            got = client.get(f"{_API}/actor-runs/{run_id}")
            if got.status_code >= 400:
                raise ApifyError(f"poll run: {got.status_code}")
            status = (got.json().get("data") or {}).get("status") or status
            log.info("apify run %s status=%s", run_id, status)

        if status != "SUCCEEDED":
            raise ApifyError(f"actor {actor_id} finished with {status}")

        dataset_id = (got.json().get("data") or {}).get("defaultDatasetId")
        if not dataset_id:
            # refresh
            got = client.get(f"{_API}/actor-runs/{run_id}")
            dataset_id = (got.json().get("data") or {}).get("defaultDatasetId")
        if not dataset_id:
            return []

        items = client.get(
            f"{_API}/datasets/{dataset_id}/items",
            params={"format": "json"},
        )
        if items.status_code >= 400:
            raise ApifyError(f"dataset: {items.status_code}")
        data = items.json()
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        return []
