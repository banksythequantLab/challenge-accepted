"""The nine agents of Challenge Accepted.

Note two of them are exposed as AgentTools rather than as sub-agents:
`scout_tool` (a built-in tool excludes all other tools on its agent) and
`referee_tool` (as a sibling it deadlocked -- see referee.py).
"""

from .archivist import archivist
from .cartographer import cartographer
from .coach import coach
from .forge import forge, quartermaster
from .interviewer import interviewer
from .referee import referee, referee_tool
from .scout import scout, scout_tool

__all__ = [
    "archivist",
    "cartographer",
    "coach",
    "forge",
    "interviewer",
    "quartermaster",
    "referee",
    "referee_tool",
    "scout",
    "scout_tool",
]
