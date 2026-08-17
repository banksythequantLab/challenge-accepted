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

import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from .. import config

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


#: Words carrying no distinguishing content, dropped before comparing two facts.
_STOPWORDS = frozenset("""
a an the and or but if then than that this these those of on in to for with without
is are was were be been being do does did doing have has had having it its as at by
from into over under not no need needs needed require requires required user users
which who whom whose there their they them he she his her i you we us our your
""".split())


#: Suffixes stripped before comparing. Crude on purpose -- the job is to make
#: "deployment", "deployed" and "deploy" the same token, not to be linguistically
#: correct. Without it two people describing one blocker score 0.57 and both get stored.
_SUFFIXES = ("ments", "ment", "ing", "ies", "ed", "es", "s")


def _stem(word: str) -> str:
    for _ in range(2):  # "deployments" -> "deployment" -> "deploy"
        for suffix in _SUFFIXES:
            if word.endswith(suffix) and len(word) - len(suffix) >= 4:
                word = word[: -len(suffix)]
                break
        else:
            break
    return word


def _content_words(text: str) -> frozenset[str]:
    cleaned = "".join(c.lower() if (c.isalnum() or c.isspace()) else " " for c in text)
    return frozenset(
        _stem(w) for w in cleaned.split() if w not in _STOPWORDS and len(w) > 2
    )


def _similar(a: frozenset[str], b: frozenset[str], threshold: float = 0.6) -> bool:
    """Jaccard-ish overlap against the SMALLER set.

    Plain Jaccard is too strict here: a terse restatement of a verbose fact shares
    almost all of its own words but only half the longer one's, so it reads as new.
    Comparing against the smaller set catches the restatement.
    """
    if not a or not b:
        return a == b
    return len(a & b) / min(len(a), len(b)) >= threshold


class Store:
    """Minimal repository. Swap the backend without touching agent code."""

    def __init__(self, client: Any = None) -> None:
        """`client` is injectable so the Firestore branch can be tested.

        Every Firestore path here went unexecuted for the project's first nine commits
        -- marked `# pragma: no cover` and shipped on trust. That is precisely the code
        most likely to fail on demo day, when GOOGLE_CLOUD_PROJECT is finally set.
        tests/test_store_firestore.py now drives these branches through a fake client.
        """
        self._lock = threading.Lock()
        self._client: Any = client
        self._mem: dict[str, dict[str, Any]] = {
            "challenges": {},
            "nodes": {},
            "tools": {},
            "journal": {},
            "feedback": {},
            "groups": {},
            #: uid -> {name, email, picture}, written from a verified Google token.
            "users": {},
            # ADK conversations. See services/session_store.py for why these live here
            # rather than in the per-instance SQLite file ADK defaults to.
            "sessions": {},
            "session_events": {},
        }
        if client is None and config.use_firestore():
            try:  # pragma: no cover - requires GCP creds
                from google.cloud import firestore  # type: ignore

                self._client = firestore.Client(project=config.GOOGLE_CLOUD_PROJECT)
            except Exception as exc:  # pragma: no cover - requires GCP creds
                # Falling back SILENTLY was the dangerous version: with
                # GOOGLE_CLOUD_PROJECT set the app looked healthy, served happily, and
                # quietly lost every write on restart -- with no multiplayer, because
                # two Cloud Run instances would each hold their own dict. Now it is
                # loud, and CA_REQUIRE_FIRESTORE=1 turns it into a hard failure so a
                # misconfigured deploy cannot reach the judges.
                logger.error(
                    "Firestore requested (GOOGLE_CLOUD_PROJECT=%s) but unavailable: "
                    "%s: %s -- FALLING BACK TO IN-MEMORY STORE. Data will not persist "
                    "and teammates will not see each other.",
                    config.GOOGLE_CLOUD_PROJECT, type(exc).__name__, exc,
                )
                if os.getenv("CA_REQUIRE_FIRESTORE") == "1":
                    raise RuntimeError(
                        "CA_REQUIRE_FIRESTORE=1 and Firestore is unavailable"
                    ) from exc
                self._client = None

    @staticmethod
    def _field_filter(field: str, value: Any) -> Any:
        """Build a Firestore filter.

        `where(field, "==", value)` positionally is DEPRECATED in google-cloud-firestore
        (2.28 warns; Google has said it will be removed). Using the positional form was
        a silent time bomb: it works today, warns tomorrow, breaks on a routine
        dependency bump -- most likely the one you do the night before submitting.
        """
        from google.cloud.firestore_v1.base_query import FieldFilter

        return FieldFilter(field, "==", value)

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

    def put_user(self, uid: str, profile: dict[str, Any]) -> None:
        """The name and avatar behind a uid, as Google stated them.

        Kept apart from the group roster on purpose: a group stores ids, so renaming
        yourself does not mean rewriting every party you belong to. Merged rather than
        replaced so a later write with a thinner token cannot blank a name.
        """
        clean = {k: v for k, v in profile.items() if v}
        if clean:
            self._patch("users", uid, {**clean, "updated_at": _now()})

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

    def join_group(self, group_id: str, user_id: str) -> list[str]:
        """Put a user on the party roster. Idempotent. Returns the full roster.

        Membership is what makes "shared" mean anything. Without it a group is an
        anonymous bucket of facts and there is no way to answer "who else is on
        this?" -- which is the whole premise of the collaborative track.
        """
        existing = self.get("groups", group_id) or {
            "id": group_id, "members": [], "shared_facts": []
        }
        members = list(existing.get("members", []))
        if user_id and user_id not in members:
            members.append(user_id)
            existing["members"] = members
            self._put("groups", group_id, existing)
        return members

    def leave_group(self, group_id: str, user_id: str) -> list[str]:
        """Take a user off the party roster. Idempotent. Returns the new roster.

        The facts they contributed stay. That is deliberate and it is the only defensible
        choice: shared memory is the point of a party, a teammate leaving does not make
        what they discovered untrue, and unpicking it would silently rewrite everyone
        else's plan. What leaving revokes is ACCESS -- `_mine()` reads this list, so the
        challenge disappears from their quest picker and every read 403s from here on.
        """
        existing = self.get("groups", group_id)
        if not existing:
            return []
        members = [m for m in (existing.get("members") or []) if m != user_id]
        if len(members) != len(existing.get("members") or []):
            existing["members"] = members
            self._put("groups", group_id, existing)
        return members

    def add_group_fact(self, group_id: str, fact: str) -> bool:
        """Goal-scoped shared memory. This is the group-intelligence primitive.

        Returns True if the fact was stored, False if it duplicated an existing one.

        Exact-string dedup is not enough. A live run stored the same constraint three
        times because three agents phrased it three ways:

            "User lacks admin privileges on Google account required to enable Cloud Run billing."
            "User lacks admin access on Google account required to enable billing for Cloud Run."
            "Cloud Run requires Google account admin access to enable billing, which the user does not have."

        A teammate reading that sees noise, not intelligence. We compare normalised
        content-word sets instead, which collapses all three.
        """
        existing = self.get("groups", group_id) or {
            "id": group_id, "members": [], "shared_facts": []
        }
        facts = existing.get("shared_facts", [])
        incoming = _content_words(fact)
        for known in facts:
            if _similar(incoming, _content_words(known)):
                return False
        facts.append(fact)
        existing["shared_facts"] = facts
        self._put("groups", group_id, existing)
        return True

    def supersede_nodes(self, challenge_id: str, keep_ids: list[str]) -> int:
        """Retire nodes that a redrawn graph no longer contains.

        Without this, re-planning APPENDS. One live run redrew a 12-node graph after a
        blocker and ended up with 24 nodes -- the old plan and the new one side by side,
        which is worse than either. Superseded nodes are kept (not deleted) so finished
        work and its evidence stay auditable.
        """
        retired = 0
        for node in self.list_nodes(challenge_id):
            nid = node.get("id")
            if nid in keep_ids or node.get("status") in ("done", "superseded"):
                continue
            self._patch("nodes", f"{challenge_id}:{nid}",
                        {"status": "superseded", "updated_at": _now()})
            retired += 1
        return retired

    # -- reads ---------------------------------------------------------------

    def get(self, collection: str, doc_id: str) -> Optional[dict[str, Any]]:
        if self._client:
            snap = self._client.collection(collection).document(doc_id).get()
            return snap.to_dict() if snap.exists else None
        with self._lock:
            return self._mem[collection].get(doc_id)

    def list_challenges(self, group_id: Optional[str] = None) -> list[dict[str, Any]]:
        """Newest first. Optionally scoped to one group."""
        if self._client:
            col = self._client.collection("challenges")
            query = (
                col.where(filter=self._field_filter("group_id", group_id))
                if group_id else col
            )
            rows = [d.to_dict() for d in query.stream()]
        else:
            with self._lock:
                rows = [
                    c for c in self._mem["challenges"].values()
                    if group_id is None or c.get("group_id") == group_id
                ]
        return sorted(rows, key=lambda c: c.get("created_at", ""), reverse=True)

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
        if self._client:
            self._client.collection(collection).document(doc_id).set(doc)
            return
        with self._lock:
            self._mem[collection][doc_id] = doc

    def _patch(self, collection: str, doc_id: str, patch: dict[str, Any]) -> None:
        if self._client:
            self._client.collection(collection).document(doc_id).set(patch, merge=True)
            return
        with self._lock:
            self._mem[collection].setdefault(doc_id, {}).update(patch)

    def delete(self, collection: str, doc_id: str) -> None:
        if self._client:
            self._client.collection(collection).document(doc_id).delete()
            return
        with self._lock:
            self._mem[collection].pop(doc_id, None)

    def delete_where(self, collection: str, field: str, value: Any) -> int:
        """Delete every document matching one field. Returns how many went.

        Used to drop a session's events when the session is deleted. Firestore has no
        server-side "delete by query", so this is a read then a batch of deletes --
        which is exactly what the client library's own docs prescribe.
        """
        if self._client:
            col = self._client.collection(collection)
            docs = list(col.where(filter=self._field_filter(field, value)).stream())
            for d in docs:
                d.reference.delete()
            return len(docs)
        with self._lock:
            gone = [k for k, v in self._mem[collection].items() if v.get(field) == value]
            for k in gone:
                del self._mem[collection][k]
            return len(gone)

    def _query(self, collection: str, field: str, value: Any) -> list[dict[str, Any]]:
        if self._client:
            query = self._client.collection(collection).where(
                filter=self._field_filter(field, value)
            )
            return [d.to_dict() for d in query.stream()]
        with self._lock:
            return [d for d in self._mem[collection].values() if d.get(field) == value]


#: Process-wide singleton. Cloud Run gives us one per instance, which is fine --
#: Firestore is the real coordination point.
store = Store()
