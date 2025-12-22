"""Developer smoke test for ingest → preview flow.

The script can start the FastAPI app locally or attach to an already
running instance, trigger text ingestion, wait for preview readiness,
and print a compact summary of the extracted preview.
"""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any, Mapping

import httpx


DEFAULT_BASE_URL = os.getenv("LOGOS_BASE_URL", "http://127.0.0.1:8000")
DEFAULT_SAMPLE_TEXT = (
    "Alex at Example Corp will send the contract draft to Pat from Contoso next week."
)


@dataclass
class SmokeResult:
    interaction_id: str
    summary: str
    person_count: int
    org_count: int
    commitment_count: int


class AppProcess:
    """Context manager to optionally start the FastAPI app."""

    def __init__(self, should_start: bool, port: int) -> None:
        self.should_start = should_start
        self.port = port
        self.process: subprocess.Popen[str] | None = None

    def __enter__(self) -> "AppProcess":
        if self.should_start:
            cmd = [
                sys.executable,
                "-m",
                "uvicorn",
                "logos.main:app",
                "--host",
                "0.0.0.0",
                "--port",
                str(self.port),
            ]
            env = os.environ.copy()
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
                env=env,
            )
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        if self.process:
            try:
                self.process.send_signal(signal.SIGINT)
                self.process.wait(timeout=10)
            except Exception:
                self.process.kill()


def wait_for_ready(base_url: str, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    with httpx.Client() as client:
        while time.time() < deadline:
            try:
                resp = client.get(f"{base_url}/health", timeout=5)
                if resp.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(1)
    raise RuntimeError("FastAPI app did not become ready in time")


def ingest_text(base_url: str, text: str, topic: str | None = None) -> str:
    payload: dict[str, Any] = {"text": text}
    if topic:
        payload["topic"] = topic
    with httpx.Client() as client:
        resp = client.post(f"{base_url}/api/v1/ingest/text", json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    interaction_id = data.get("interaction_id")
    if not interaction_id:
        raise RuntimeError("Ingest response missing interaction_id")
    return interaction_id


def poll_status(base_url: str, interaction_id: str, timeout: float = 60.0) -> str:
    status_url = f"{base_url}/api/v1/interactions/{interaction_id}/status"
    deadline = time.time() + timeout
    with httpx.Client() as client:
        while time.time() < deadline:
            resp = client.get(status_url, timeout=10)
            resp.raise_for_status()
            state = resp.json().get("state")
            if state == "preview_ready":
                return state
            if state == "failed":
                error_message = resp.json().get("error_message")
                raise RuntimeError(f"Preview failed: {error_message}")
            time.sleep(2)
    raise RuntimeError("Preview did not become ready in time")


def fetch_preview(base_url: str, interaction_id: str) -> Mapping[str, Any]:
    preview_url = f"{base_url}/api/v1/interactions/{interaction_id}/preview"
    with httpx.Client() as client:
        resp = client.get(preview_url, timeout=30)
        resp.raise_for_status()
        return resp.json()


def extract_counts(preview: Mapping[str, Any]) -> tuple[int, int, int]:
    entities = preview.get("entities") or {}
    persons = entities.get("persons") or []
    orgs = entities.get("orgs") or []
    commitments = entities.get("commitments") or []
    return len(persons), len(orgs), len(commitments)


def extract_summary(preview: Mapping[str, Any]) -> str:
    interaction = preview.get("interaction") or {}
    summary = interaction.get("summary") or interaction.get("text") or ""
    return str(summary).strip()


def run_smoke(base_url: str, sample_text: str, start_app: bool, port: int) -> SmokeResult:
    with AppProcess(start_app, port):
        wait_for_ready(base_url)
        interaction_id = ingest_text(base_url, sample_text)
        poll_status(base_url, interaction_id)
        preview = fetch_preview(base_url, interaction_id)
        person_count, org_count, commitment_count = extract_counts(preview)
        summary = extract_summary(preview)
    return SmokeResult(
        interaction_id=interaction_id,
        summary=summary,
        person_count=person_count,
        org_count=org_count,
        commitment_count=commitment_count,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke test ingest → preview")
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"FastAPI base URL (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--text",
        default=DEFAULT_SAMPLE_TEXT,
        help="Sample text to ingest",
    )
    parser.add_argument(
        "--topic",
        default=None,
        help="Optional topic to tag the note with",
    )
    parser.add_argument(
        "--no-start",
        action="store_true",
        help="Assume the FastAPI app is already running",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to start FastAPI on when managed by this script",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    base_url = args.base_url.rstrip("/")
    result = run_smoke(base_url, args.text, start_app=not args.no_start, port=args.port)
    print("\nSmoke test preview ready")
    print(f"Interaction ID: {result.interaction_id}")
    if result.summary:
        print(f"Summary: {result.summary}")
    else:
        print("Summary: <none>")
    print(f"Persons: {result.person_count}")
    print(f"Organisations: {result.org_count}")
    print(f"Commitments: {result.commitment_count}")


if __name__ == "__main__":
    main()
