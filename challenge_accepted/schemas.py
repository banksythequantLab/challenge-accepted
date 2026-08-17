"""Structured contracts between agents.

Every hand-off in the pipeline is a typed object, not free text. This is what makes
the architecture legible to a judge reading the repo, and it's what stops Flash-tier
models from drifting between phases.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

# --- ACCEPT -----------------------------------------------------------------


class ChallengeCharter(BaseModel):
    """Output of the Interviewer. The graph is not drawn until this is complete."""

    title: str = Field(description="Short name for the challenge, in the user's words.")
    outcome: str = Field(
        description="The specific end state. Must be observable by a third party."
    )
    definition_of_done: str = Field(
        description="How we will know it is finished. Concrete and checkable."
    )
    deadline: Optional[str] = Field(
        default=None, description="ISO date, or a relative phrase the user gave."
    )
    constraints: list[str] = Field(
        default_factory=list,
        description="Time, money, skill, access and energy limits the user stated.",
    )
    prior_attempts: list[str] = Field(
        default_factory=list,
        description="What the user already tried and why it did not work. High signal.",
    )
    stakeholders: list[str] = Field(
        default_factory=list,
        description="Other people involved. Drives group membership.",
    )
    open_questions: list[str] = Field(
        default_factory=list,
        description="Things still unknown that a later phase may need to re-open.",
    )


# --- MAP --------------------------------------------------------------------


class GoalNode(BaseModel):
    """One micro-task. Small enough to finish in a single sitting."""

    id: str = Field(description="Stable slug, e.g. 'draft-outreach-email'.")
    title: str
    description: str
    acceptance_criteria: str = Field(
        description=(
            "A single sentence a third party could verify, stated as something the "
            "user can TELL you: a number, a date, a name, a result, or a link. Never "
            "require a file, photo, screenshot or receipt -- the user has a chat box "
            "and cannot hand one over, so the Referee would refuse the step forever. "
            "Good: 'User reports the 5k finish time and average pace.' "
            "Bad: 'GPS log file saved.'"
        )
    )
    depends_on: list[str] = Field(
        default_factory=list, description="ids of nodes that must finish first."
    )
    effort_mins: int = Field(
        default=60, description="Estimated human effort. Keep <= 120."
    )


class GoalGraph(BaseModel):
    """Output of the Cartographer. A DAG, not a list -- ordering is the value."""

    challenge_id: str
    nodes: list[GoalNode]
    rationale: str = Field(
        description="Two sentences on why the graph is shaped this way. Shown to the user."
    )


# --- FORGE ------------------------------------------------------------------

#: Closed set. Open-ended codegen is the single biggest demo risk, so Quartermaster
#: may only request one of these. Anything else is rejected back for reshaping.
ToolType = Literal[
    "calculator",
    "checklist",
    "research_brief",
    "drill",
    "tracker",
    "script",
    "mini_app",
]


class ToolSpec(BaseModel):
    """Output of the Quartermaster: the capability a node is missing."""

    node_id: str
    needed: bool = Field(
        description="False when the node is trivial and needs no tool. Be honest."
    )
    tool_type: Optional[ToolType] = None
    name: Optional[str] = None
    purpose: Optional[str] = Field(
        default=None, description="What the user can do with it that they could not before."
    )
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    smoke_test: Optional[str] = Field(
        default=None,
        description="A concrete example input and the expected output. Toolwright must pass this.",
    )


class BuiltTool(BaseModel):
    """Output of a Toolwright worker."""

    node_id: str
    tool_type: ToolType
    name: str
    source: str = Field(
        description="What the user opens. A self-contained HTML document for "
                    "calculator/tracker/drill/mini_app -- the dashboard runs it in a "
                    "sandboxed iframe and the user cannot run Python. JSON for "
                    "checklist, plain text for script and research_brief."
    )
    usage: str = Field(description="One paragraph telling the user how to use it.")
    smoke_test_passed: bool
    smoke_test_output: str = ""
    degraded: bool = Field(
        default=False,
        description="True when the build failed and this fell back to a plain checklist.",
    )


# --- CLIMB ------------------------------------------------------------------


class NodeVerdict(BaseModel):
    """Output of the Referee."""

    node_id: str
    complete: bool
    evidence: str = Field(description="What the user showed, in their words or ours.")
    reasoning: str
    reopen_interview: bool = Field(
        default=False,
        description="True when a new constraint surfaced that should redraw the graph.",
    )


class Feedback(BaseModel):
    target_type: Literal["node", "tool", "question", "graph"]
    target_id: str
    verdict: Literal["up", "down"]
    reason: str = ""


# --- Cross-cutting ----------------------------------------------------------


class JournalEntry(BaseModel):
    """The 'takes notes' requirement, made literal and user-visible."""

    actor: str = Field(description="Agent name, or a user id.")
    kind: Literal["decision", "question", "answer", "insight", "blocker", "build"]
    text: str
    node_id: Optional[str] = None
