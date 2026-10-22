"""Google Tasks operations, independent of MCP so they can be tested with a fake service."""

from __future__ import annotations

import datetime as dt
from typing import Any

# Google Tasks has no custom fields, so tasks created through this server carry
# this line at the end of their notes. It survives sync to every device and lets
# Claude tell its own tasks apart from the user's.
CLAUDE_MARKER = "[created-by: claude]"


def is_claude_task(task: dict[str, Any]) -> bool:
    return CLAUDE_MARKER in (task.get("notes") or "")


def _with_marker(notes: str | None) -> str:
    notes = (notes or "").rstrip()
    return f"{notes}\n\n{CLAUDE_MARKER}" if notes else CLAUDE_MARKER


def _strip_marker(notes: str | None) -> str:
    return (notes or "").replace(CLAUDE_MARKER, "").rstrip()


def _due_to_rfc3339(due: str) -> str:
    # The API stores only the date part of `due`; the time is ignored.
    return dt.date.fromisoformat(due[:10]).isoformat() + "T00:00:00.000Z"


def _due_date(task: dict[str, Any]) -> dt.date | None:
    due = task.get("due")
    return dt.date.fromisoformat(due[:10]) if due else None


def simplify(task: dict[str, Any], tasklist_id: str, tasklist_title: str | None = None) -> dict[str, Any]:
    out = {
        "id": task["id"],
        "tasklist_id": tasklist_id,
        "title": task.get("title", ""),
        "status": task.get("status"),
        "created_by_claude": is_claude_task(task),
    }
    if tasklist_title:
        out["tasklist"] = tasklist_title
    if notes := _strip_marker(task.get("notes")):
        out["notes"] = notes
    if due := _due_date(task):
        out["due"] = due.isoformat()
    if task.get("parent"):
        out["parent"] = task["parent"]
    if task.get("completed"):
        out["completed"] = task["completed"]
    return out


class TasksService:
    def __init__(self, service: Any):
        self.svc = service

    # --- task lists -------------------------------------------------------
    def task_lists(self) -> list[dict[str, Any]]:
        items, token = [], None
        while True:
            resp = self.svc.tasklists().list(maxResults=100, pageToken=token).execute()
            items += resp.get("items", [])
            token = resp.get("nextPageToken")
            if not token:
                return [{"id": i["id"], "title": i.get("title", "")} for i in items]

    def resolve_list(self, tasklist: str | None) -> str:
        """Accept a list id, a list title (case-insensitive) or None for the default list."""
        if not tasklist or tasklist == "@default":
            return "@default"
        lists = self.task_lists()
        for tl in lists:
            if tl["id"] == tasklist:
                return tl["id"]
        for tl in lists:
            if tl["title"].casefold() == tasklist.casefold():
                return tl["id"]
        names = ", ".join(repr(t["title"]) for t in lists)
        raise ValueError(f"Task list {tasklist!r} not found. Available: {names}")

    # --- tasks ------------------------------------------------------------
    def raw_tasks(self, tasklist_id: str, show_completed: bool) -> list[dict[str, Any]]:
        items, token = [], None
        while True:
            resp = (
                self.svc.tasks()
                .list(
                    tasklist=tasklist_id,
                    maxResults=100,
                    pageToken=token,
                    showCompleted=show_completed,
                    showHidden=show_completed,
                )
                .execute()
            )
            items += resp.get("items", [])
            token = resp.get("nextPageToken")
            if not token:
                return items

    def list_tasks(
        self,
        tasklist: str | None = None,
        show_completed: bool = False,
        query: str | None = None,
        due_before: str | None = None,
        only_claude: bool = False,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        tl = self.resolve_list(tasklist)
        before = dt.date.fromisoformat(due_before) if due_before else None
        q = query.casefold() if query else None
        out = []
        for t in self.raw_tasks(tl, show_completed):
            if only_claude and not is_claude_task(t):
                continue
            if q and q not in (t.get("title", "") + " " + _strip_marker(t.get("notes"))).casefold():
                continue
            if before and not ((d := _due_date(t)) and d <= before):
                continue
            out.append(simplify(t, tl))
            if len(out) >= limit:
                break
        return out

    def context(self, days_ahead: int = 7, today: dt.date | None = None) -> dict[str, Any]:
        """Open tasks across all lists, grouped for use at the start of a conversation."""
        today = today or dt.date.today()
        horizon = today + dt.timedelta(days=days_ahead)
        groups: dict[str, list] = {"overdue": [], "due_soon": [], "no_due_date": [], "later": []}
        claude_open = []
        for tl in self.task_lists():
            for t in self.raw_tasks(tl["id"], show_completed=False):
                if t.get("status") == "completed":
                    continue
                s = simplify(t, tl["id"], tl["title"])
                d = _due_date(t)
                key = (
                    "no_due_date" if d is None
                    else "overdue" if d < today
                    else "due_soon" if d <= horizon
                    else "later"
                )
                groups[key].append(s)
                if s["created_by_claude"]:
                    claude_open.append(s)
        for key in ("overdue", "due_soon", "later"):
            groups[key].sort(key=lambda s: s["due"])
        return {
            "today": today.isoformat(),
            **groups,
            "open_tasks_created_by_claude": claude_open,
        }

    def get_task(self, task_id: str, tasklist: str | None = None) -> dict[str, Any]:
        tl = self.resolve_list(tasklist)
        return self.svc.tasks().get(tasklist=tl, task=task_id).execute()

    def create_task(
        self,
        title: str,
        notes: str | None = None,
        due: str | None = None,
        tasklist: str | None = None,
        parent: str | None = None,
    ) -> dict[str, Any]:
        tl = self.resolve_list(tasklist)
        body: dict[str, Any] = {"title": title, "notes": _with_marker(notes)}
        if due:
            body["due"] = _due_to_rfc3339(due)
        kwargs = {"parent": parent} if parent else {}
        created = self.svc.tasks().insert(tasklist=tl, body=body, **kwargs).execute()
        return simplify(created, tl)

    def update_task(
        self,
        task_id: str,
        tasklist: str | None = None,
        title: str | None = None,
        notes: str | None = None,
        due: str | None = None,
    ) -> dict[str, Any]:
        tl = self.resolve_list(tasklist)
        current = self.svc.tasks().get(tasklist=tl, task=task_id).execute()
        body: dict[str, Any] = {}
        if title is not None:
            body["title"] = title
        if notes is not None:
            # Keep the ownership marker if the task had it.
            body["notes"] = _with_marker(notes) if is_claude_task(current) else notes
        if due is not None:
            body["due"] = _due_to_rfc3339(due) if due else None
        updated = self.svc.tasks().patch(tasklist=tl, task=task_id, body=body).execute()
        return simplify(updated, tl)

    def set_status(
        self,
        task_id: str,
        completed: bool,
        tasklist: str | None = None,
        user_requested: bool = False,
    ) -> dict[str, Any]:
        tl = self.resolve_list(tasklist)
        current = self.svc.tasks().get(tasklist=tl, task=task_id).execute()
        if not user_requested and not is_claude_task(current):
            raise PermissionError(
                f"Task {current.get('title')!r} was not created by Claude. Change its status "
                "only when the user explicitly asks, and then pass user_requested=true."
            )
        body = {"status": "completed" if completed else "needsAction"}
        if not completed:
            body["completed"] = None
        updated = self.svc.tasks().patch(tasklist=tl, task=task_id, body=body).execute()
        return simplify(updated, tl)
