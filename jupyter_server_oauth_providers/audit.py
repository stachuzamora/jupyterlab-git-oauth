"""
Structured audit log emitter.

Emits JSON log lines to the standard Python logger (name: jupyter_gitlab_auth.audit).
Each line is a self-contained JSON object suitable for ingestion by Loki, Elasticsearch,
Splunk, or any log aggregator that can parse JSON.

Usage:
    audit = AuditLogger()
    audit.emit(
        "device_flow_started",
        jupyter_user_id="alice@example.com",
        result="initiated",
        correlation_id="abc123",
    )
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_audit_logger = logging.getLogger("jupyter_oauth_providers.audit")

# ---------------------------------------------------------------------------
# Event type constants
# ---------------------------------------------------------------------------

EVENT_DEVICE_FLOW_STARTED = "device_flow_started"
EVENT_DEVICE_FLOW_APPROVED = "device_flow_approved"
EVENT_TOKEN_REFRESHED = "token_refreshed"
EVENT_TOKEN_REFRESH_FAILED = "token_refresh_failed"
EVENT_GIT_ACTION_PREFLIGHT = "git_action_preflight"
EVENT_IDENTITY_SYNC = "identity_sync"
EVENT_DISCONNECT = "disconnect"

ALL_EVENTS = {
    EVENT_DEVICE_FLOW_STARTED,
    EVENT_DEVICE_FLOW_APPROVED,
    EVENT_TOKEN_REFRESHED,
    EVENT_TOKEN_REFRESH_FAILED,
    EVENT_GIT_ACTION_PREFLIGHT,
    EVENT_IDENTITY_SYNC,
    EVENT_DISCONNECT,
}


# ---------------------------------------------------------------------------
# Namespace helper
# ---------------------------------------------------------------------------

_SA_NAMESPACE_FILE = "/var/run/secrets/kubernetes.io/serviceaccount/namespace"


def _get_namespace() -> str:
    if os.path.exists(_SA_NAMESPACE_FILE):
        try:
            return Path(_SA_NAMESPACE_FILE).read_text().strip()
        except OSError:
            pass
    return os.environ.get("POD_NAMESPACE", "local")


# ---------------------------------------------------------------------------
# AuditLogger
# ---------------------------------------------------------------------------


class AuditLogger:
    """
    Emits structured audit events.

    Persistent context fields (set once at construction):
      - pod_name    from HOSTNAME env var
      - namespace   from ServiceAccount namespace file or env
      - service     always 'jupyter-server-gitlab-auth'

    Per-event fields:
      - timestamp       ISO 8601 UTC
      - event           event type constant
      - correlation_id  caller-supplied or auto-generated UUID4
      - jupyter_user_id authenticated Jupyter user (from kubeflow-userid header)
      - gitlab_user_id  GitLab numeric user ID (optional)
      - repo_path       repository path involved in the action (optional)
      - action          sub-action label (optional)
      - result          'success', 'failed', 'initiated', etc.
      - error           error message (optional, present on failures)
      + any extra keyword arguments passed to emit()
    """

    def __init__(self) -> None:
        self._pod_name = os.environ.get("HOSTNAME", "unknown")
        self._namespace = _get_namespace()
        self._service = "jupyter-server-oauth-providers"

    def emit(
        self,
        event: str,
        *,
        jupyter_user_id: str = "",
        gitlab_user_id: str = "",
        repo_path: str = "",
        action: str = "",
        result: str = "",
        error: str = "",
        correlation_id: str = "",
        **extra: Any,
    ) -> None:
        """
        Emit one audit event as a JSON log line.

        Args:
            event:             Event type (see ALL_EVENTS constants).
            jupyter_user_id:   The kubeflow-userid / authenticated user.
            gitlab_user_id:    GitLab numeric user ID as string (optional).
            repo_path:         Path to the git repository (optional).
            action:            Sub-action label (optional).
            result:            Outcome: 'success', 'failed', 'initiated', etc.
            error:             Error message if result is a failure (optional).
            correlation_id:    Caller-supplied correlation ID (optional).
            **extra:           Any additional fields to include in the event.
        """
        record: dict[str, Any] = {
            "timestamp": _utc_now(),
            "service": self._service,
            "pod_name": self._pod_name,
            "namespace": self._namespace,
            "event": event,
            "correlation_id": correlation_id or uuid.uuid4().hex,
            "jupyter_user_id": jupyter_user_id,
            "gitlab_user_id": gitlab_user_id,
            "repo_path": repo_path,
            "action": action,
            "result": result,
        }

        if error:
            record["error"] = error

        record.update(extra)

        # Emit at INFO level for success/initiated events, WARNING for failures
        is_failure = result in ("failed", "error") or bool(error)
        log_level = logging.WARNING if is_failure else logging.INFO

        _audit_logger.log(log_level, "%s", json.dumps(record, default=str))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()
