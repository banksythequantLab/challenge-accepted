"""The Interviewer has to END its task, not talk to the user.

`mode="task"` agents run until they call `finish_task`. ADK is explicit about what
happens otherwise: "If the agent outputs text directed to the user instead of calling
`finish_task`, the framework pauses execution and delivers the message", and "a task
will not complete successfully if the task agent fails to call `finish_task`".

The prompt used to end with *"call save_charter, tell the user in one sentence what you
heard, and finish"* -- an instruction to do exactly the thing that stalls the run. On
the deployed service that produced:

    22:25:23  [FLOW] enter interviewer  branch=interviewer@call_2058
    22:25:35  [FLOW] leave interviewer
    (nothing after it -- no warden, no cartographer, no forge, no error)

Charter saved, graph never drawn, 0 specs, 0 tools, and a dashboard that looks like a
challenge someone simply has not started yet. This is a prompt whose wording is
load-bearing, sitting in a file full of prose nobody diffs carefully.
"""

from __future__ import annotations

from challenge_accepted import prompts
from challenge_accepted.sub_agents.interviewer import interviewer


def test_the_prompt_names_finish_task():
    assert "finish_task" in prompts.INTERVIEWER


def test_the_prompt_does_not_tell_it_to_sign_off_to_the_user():
    """The specific regression. Ending a task turn with a message to the user is how
    the framework is told 'I am asking a question', which is the stall."""
    tail = prompts.INTERVIEWER.strip().splitlines()[-8:]
    joined = " ".join(tail).lower()
    assert "tell the user in one sentence what you heard, and finish" not in joined
    assert "finish_task" in joined


def test_saving_the_charter_and_finishing_are_the_same_turn():
    """Split across turns, the charter is saved and the task still never completes --
    the failure looks identical and the fix looks applied."""
    assert "SAME turn" in prompts.INTERVIEWER


def test_the_interviewer_is_still_a_task_agent():
    """If this ever becomes single_turn or chat, the whole rule above changes and the
    prompt would be telling it to call a tool it no longer has."""
    assert interviewer.mode == "task"


def test_it_still_has_the_tools_the_prompt_tells_it_to_call():
    names = {getattr(t, "name", getattr(t, "__name__", "")) for t in interviewer.tools}
    assert {"save_charter", "read_challenge_state", "write_journal"} <= names
