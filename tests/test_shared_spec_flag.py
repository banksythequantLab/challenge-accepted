"""Where `shared` comes from, and why it is not an argument to `save_tool`.

A Toolwright would have to echo the flag back correctly on every build for an argument
to be trustworthy, and a boolean a model can quietly drop is a boolean that decides, at
random, whether your teammates can see your ledger. The Quartermaster's spec already
carries it, the worker does not write the spec, so `save_tool` reads it from there.
"""

from __future__ import annotations

import json

from challenge_accepted.services.tools import _spec_is_shared


class _Ctx:
    """Just enough of a ToolContext: `state`."""

    def __init__(self, state):
        self.state = state


def _specs(*pairs):
    return {"specs": [{"node_id": nid, "needed": True, "shared": sh}
                      for nid, sh in pairs]}


def test_reads_the_flag_off_the_matching_spec():
    ctx = _Ctx({"tool_specs": _specs(("split", True), ("log", False))})
    assert _spec_is_shared(ctx, "split") is True
    assert _spec_is_shared(ctx, "log") is False


def test_accepts_a_json_string_like_the_dispatcher_does():
    """output_schema can arrive as a dict or as a JSON string depending on the model
    path. The Dispatcher handles both shapes; so must this, or the scope silently
    defaults to personal on exactly the runs where the string form shows up."""
    ctx = _Ctx({"tool_specs": json.dumps(_specs(("split", True)))})
    assert _spec_is_shared(ctx, "split") is True


def test_unknown_node_is_personal():
    ctx = _Ctx({"tool_specs": _specs(("split", True))})
    assert _spec_is_shared(ctx, "something_else") is False


def test_missing_or_unreadable_specs_are_personal():
    """Every failure mode falls to the private scope. Getting this backwards would
    publish somebody's private log to their party on a parse error."""
    assert _spec_is_shared(_Ctx({}), "split") is False
    assert _spec_is_shared(_Ctx({"tool_specs": "not json at all"}), "split") is False
    assert _spec_is_shared(_Ctx({"tool_specs": []}), "split") is False
    assert _spec_is_shared(_Ctx({"tool_specs": {"specs": None}}), "split") is False


def test_a_spec_with_no_shared_key_is_personal():
    """Older specs, and any model output that omits the field, must not become shared
    just because the key is absent."""
    ctx = _Ctx({"tool_specs": {"specs": [{"node_id": "split", "needed": True}]}})
    assert _spec_is_shared(ctx, "split") is False
