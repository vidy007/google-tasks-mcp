"""MCP tools exposing Google Tasks."""

from __future__ import annotations

import json
from functools import lru_cache, wraps
from typing import Any

try:  # mcp >= 2.0
    from mcp.server.mcpserver import MCPServer as _Server
    from mcp.server.mcpserver.exceptions import ToolError
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server
    from mcp.server.fastmcp.exceptions import ToolError
from googleapiclient.errors import HttpError

from .auth import load_credentials
from .tasks import TasksService

INSTRUCTIONS = """\
Google Tasks of the user.

- At the start of a conversation where plans, deadlines or to-dos may matter, call
  `tasks_context` once and use its result as background; do not dump it on the user.
- Create a task with `create_task` when the user asks, or when you agree to follow up on
  something later. Tasks you create are marked `created_by_claude`.
- Completing tasks:
  * Tasks with created_by_claude=true: call `complete_task` on your own as soon as the work
    the task describes is actually done in the conversation (or the user says it is done),
    and mention it in one short line.
  * Any other task: complete it only when the user explicitly asks, with
    user_requested=true. Never guess.
- Dates are YYYY-MM-DD. Google Tasks stores only the date of a due, not a time.
"""

mcp = _Server("google-tasks", instructions=INSTRUCTIONS)


def _tool(fn):
    """Register fn as a tool, passing expected failures to Claude as readable errors."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (RuntimeError, ValueError, PermissionError) as e:
            raise ToolError(str(e)) from e
        except HttpError as e:
            raise ToolError(f"Google Tasks API error {e.status_code}: {e.reason}") from e

    return mcp.tool()(wrapper)


@lru_cache(maxsize=1)
def _svc() -> TasksService:
    from googleapiclient.discovery import build

    return TasksService(build("tasks", "v1", credentials=load_credentials(), cache_discovery=False))


@_tool
def list_task_lists() -> list[dict[str, Any]]:
    """List the user's Google Tasks lists (id and title)."""
    return _svc().task_lists()


@_tool
def tasks_context(days_ahead: int = 7) -> dict[str, Any]:
    """Snapshot of all open tasks across every list for use as conversation context:
    overdue, due within `days_ahead` days, without a due date, later, and the open tasks
    Claude created earlier (candidates for automatic completion)."""
    return _svc().context(days_ahead=days_ahead)


@_tool
def list_tasks(
    tasklist: str | None = None,
    show_completed: bool = False,
    query: str | None = None,
    due_before: str | None = None,
    only_created_by_claude: bool = False,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """List tasks in one list. `tasklist` is a list id or title (default list if omitted).
    `query` filters by text in title/notes; `due_before` (YYYY-MM-DD) keeps tasks due on or
    before that date."""
    return _svc().list_tasks(tasklist, show_completed, query, due_before, only_created_by_claude, limit)


@_tool
def create_task(
    title: str,
    notes: str | None = None,
    due: str | None = None,
    tasklist: str | None = None,
    parent_task_id: str | None = None,
) -> dict[str, Any]:
    """Create a task (marked as created by Claude). `due` is YYYY-MM-DD; `tasklist` is a list
    id or title; `parent_task_id` makes it a subtask."""
    return _svc().create_task(title, notes, due, tasklist, parent_task_id)


@_tool
def update_task(
    task_id: str,
    tasklist: str | None = None,
    title: str | None = None,
    notes: str | None = None,
    due: str | None = None,
) -> dict[str, Any]:
    """Change a task's title, notes or due date (YYYY-MM-DD; empty string clears it).
    Only fields that are passed are changed."""
    return _svc().update_task(task_id, tasklist, title, notes, due)


@_tool
def complete_task(task_id: str, tasklist: str | None = None, user_requested: bool = False) -> dict[str, Any]:
    """Mark a task completed. Without user_requested=true only tasks created by Claude can be
    completed; set it only when the user explicitly asked to complete this task."""
    return _svc().set_status(task_id, True, tasklist, user_requested)


@_tool
def reopen_task(task_id: str, tasklist: str | None = None, user_requested: bool = False) -> dict[str, Any]:
    """Mark a completed task as not done again (same ownership rule as complete_task)."""
    return _svc().set_status(task_id, False, tasklist, user_requested)


@mcp.resource("tasks://context")
def context_resource() -> str:
    """Open tasks for the next 7 days, as JSON."""
    return json.dumps(_svc().context(), ensure_ascii=False, indent=2)


@mcp.prompt()
def with_my_tasks() -> str:
    """Start a conversation with the user's open Google Tasks loaded as context."""
    return (
        "Here are my open Google Tasks. Keep them in mind for this conversation:\n\n"
        + json.dumps(_svc().context(), ensure_ascii=False, indent=2)
    )


def run() -> None:
    mcp.run()
