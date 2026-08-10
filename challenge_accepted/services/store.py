"""The shared data source -- Firestore in the cloud, in-memory dict locally.

Firestore is the source of truth for anything two agents or two people can both touch.
Session state is deliberately NOT trusted for that: ADK's ParallelAgent docs say branch
state is not automatically shared during execution, and recommend locks or external
state management. This module IS that external state management.

Collections mirror the architecture diagram:

    /challenges/{id}
        /nodes/{id}
            /tools/{id}
        /journal/{id}
        /feedback/{id}
    /groups/{id}
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from .. import config


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


class Store:
    """Minimal repository. Swap the backend without touching agent code."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._client: Any = None
        self._mem: dict[str, dict[str, Any]] = {
            "challenges": {},
            "nodes": {},
            "tools": {},
            "journal": {},
            "feedback": {},
            "groups": {},
        }
        if config.use_firestore():
            try:  # pragma: no cover - requires GCP creds
                from google.cloud import firestore  # type: ignore

                self._client = firestore.Client(project=config.GOOGLE_CLOUD_PROJECT)
            except Exception:
                # Fall back silently to memory; the agent tree must still boot.
                self._client = None

    @property
    def backend(self) -> str:
        return "firestore" if self._client else "memory"

    # -- writes --------------------------------------------------------------

    def create_challenge(self, charter: dict[str, Any], owner_id: str, group_id: str) -> str:
        cid = new_id("chal_")
        doc = {
            "id": cid,
            "owner_id": owner_id,
            "group_id": group_id,
            "status": "accepted",
            "charter": charter,
            "created_at": _now(),
        }
        self._put("challenges", cid, doc)
        return cid

    def put_node(self, challenge_id: str, node: dict[str, Any]) -> str:
        nid = f"{challenge_id}:{node['id']}"
        doc = {
            **node,
            "challenge_id": challenge_id,
            "status": node.get("status", "todo"),
            "evidence": node.get("evidence", []),
            "updated_at": _now(),
        }
        self._put("nodes", nid, doc)
        return nid

    def put_tool(self, challenge_id: str, node_id: str, tool: dict[str, Any]) -> str:
        tid = new_id("tool_")
        doc = {
            **tool,
            "id": tid,
            "challenge_id": challenge_id,
            "node_id": node_id,
            "run_count": 0,
            "rating": None,
            "created_at": _now(),
        }
        self._put("tools", tid, doc)
        return tid

    def add_journal(self, challenge_id: str, entry: dict[str, Any]) -> str:
        jid = new_id("j_")
        doc = {**entry, "id": jid, "challenge_id": challenge_id, "created_at": _now()}
        self._put("journal", jid, doc)
        return jid

    def add_feedback(self, challenge_id: str, fb: dict[str, Any]) -> str:
        fid = new_id("fb_")
        doc = {**fb, "id": fid, "challenge_id": challenge_id, "created_at": _now()}
        self._put("feedback", fid, doc)
        return fid

    def set_node_status(self, challenge_id: str, node_id: str, status: str,
                        evidence: Optional[str] = None) -> None:
        nid = f"{challenge_id}:{node_id}"
        patch: dict[str, Any] = {"status": status, "updated_at": _now()}
        if evidence:
            existing = self.get("nodes", nid) or {}
            patch["evidence"] = [*existing.get("evidence", []), evidence]
        self._patch("nodes", nid, patch)

    def add_group_fact(self, group_id: str, fact: str) -> None:
        """Goal-scoped shared memory. This is the group-intelligence primitive."""
        existing = self.get("groups", group_id) or {"id": group_id, "members": [], "shared_facts": []}
        facts = existing.get("shared_facts", [])
        if fact not in facts:
            facts.append(fact)
        existing["shared_facts"] = facts
        self._put("groups", group_id, existing)

    # -- reads ---------------------------------------------------------------

    def get(self, collection: str, doc_id: str) -> Optional[dict[str, Any]]:
        if self._client:  # pragma: no cover
            snap = self._client.collection(collection).document(doc_id).get()
            return snap.to_dict() if snap.exists else None
        with self._lock:
            return self._mem[collection].get(doc_id)

    def list_nodes(self, challenge_id: str) -> list[dict[str, Any]]:
        return self._query("nodes", "challenge_id", challenge_id)

    def list_journal(self, challenge_id: str) -> list[dict[str, Any]]:
        return sorted(
            self._query("journal", "challenge_id", challenge_id),
            key=lambda d: d.get("created_at", ""),
        )

    def list_feedback(self, challenge_id: str) -> list[dict[str, Any]]:
        return self._query("feedback", "challenge_id", challenge_id)

    def list_tools(self, challenge_id: str) -> list[dict[str, Any]]:
        return self._query("tools", "challenge_id", challenge_id)

    # -- backend plumbing ----------------------------------------------------

    def _put(self, collection: str, doc_id: str, doc: dict[str, Any]) -> None:
        if self._client:  # pragma: no cover
            self._client.collection(collection).document(doc_id).set(doc)
            return
        with self._lock:
            self._mem[collection][doc_id] = doc

    def _patch(self, collection: str, doc_id: str, patch: dict[str, Any]) -> None:
        if self._client:  # pragma: no cover
            self._client.collection(collection).document(doc_id).set(patch, merge=True)
            return
        with self._lock:
            self._mem[collection].setdefault(doc_id, {}).update(patch)

    def _query(self, collection: str, field: str, value: Any) -> list[dict[str, Any]]:
        if self._client:  # pragma: no cover
            return [d.to_dict() for d in
                    self._client.collection(collection).where(field, "==", value).stream()]
        with self._lock:
            return [d for d in self._mem[collection].values() if d.get(field) == value]


#: Process-wide singleton. Cloud Run gives us one per instance, which is fine --
#: Firestore is the real coordination point.
store = Store()
