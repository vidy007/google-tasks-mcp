import datetime as dt
import itertools

import pytest

from google_tasks_mcp.tasks import CLAUDE_MARKER, TasksService


class _Call:
    def __init__(self, fn):
        self.fn = fn

    def execute(self):
        return self.fn()


class FakeGoogleTasks:
    """In-memory stand-in for googleapiclient's tasks v1 resource."""

    def __init__(self):
        self.lists = {"L1": {"id": "L1", "title": "Мои задачи"}, "L2": {"id": "L2", "title": "Работа"}}
        self.items = {"L1": {}, "L2": {}}
        self.ids = (f"t{i}" for i in itertools.count())
        self.items["@default"] = self.items["L1"]

    def add(self, tl, **task):
        tid = next(self.ids)
        self.items[tl][tid] = {"id": tid, "status": "needsAction", **task}
        return tid

    def tasklists(self):
        fake = self

        class R:
            def list(self, **kw):
                return _Call(lambda: {"items": list(fake.lists.values())})

        return R()

    def tasks(self):
        fake = self

        class R:
            def list(self, tasklist, showCompleted, **kw):
                return _Call(lambda: {"items": [
                    t for t in fake.items[tasklist].values()
                    if showCompleted or t["status"] != "completed"
                ]})

            def get(self, tasklist, task):
                return _Call(lambda: dict(fake.items[tasklist][task]))

            def insert(self, tasklist, body, **kw):
                def run():
                    tid = fake.add(tasklist, **body, **kw)
                    return dict(fake.items[tasklist][tid])
                return _Call(run)

            def patch(self, tasklist, task, body):
                def run():
                    t = fake.items[tasklist][task]
                    for k, v in body.items():
                        if v is None:
                            t.pop(k, None)
                        else:
                            t[k] = v
                    return dict(t)
                return _Call(run)

        return R()


@pytest.fixture
def fake():
    return FakeGoogleTasks()


@pytest.fixture
def svc(fake):
    return TasksService(fake)


def test_create_marks_task_and_hides_marker(svc, fake):
    t = svc.create_task("Позвонить", notes="про отчёт", due="2026-10-25", tasklist="работа")
    stored = fake.items["L2"][t["id"]]
    assert stored["notes"].endswith(CLAUDE_MARKER)
    assert stored["due"] == "2026-10-25T00:00:00.000Z"
    assert t == {"id": t["id"], "tasklist_id": "L2", "title": "Позвонить", "status": "needsAction",
                 "created_by_claude": True, "notes": "про отчёт", "due": "2026-10-25"}


def test_complete_own_task_automatically(svc):
    t = svc.create_task("Сделать черновик")
    assert svc.set_status(t["id"], True)["status"] == "completed"
    assert svc.set_status(t["id"], False)["status"] == "needsAction"


def test_user_task_needs_explicit_request(svc, fake):
    tid = fake.add("L1", title="Купить молоко")
    with pytest.raises(PermissionError):
        svc.set_status(tid, True)
    assert svc.set_status(tid, True, user_requested=True)["status"] == "completed"


def test_update_keeps_marker(svc, fake):
    t = svc.create_task("A", notes="x")
    svc.update_task(t["id"], notes="y")
    assert fake.items["L1"][t["id"]]["notes"] == f"y\n\n{CLAUDE_MARKER}"


def test_context_groups(svc, fake):
    fake.add("L1", title="old", due="2026-10-01T00:00:00.000Z")
    fake.add("L2", title="soon", due="2026-10-24T00:00:00.000Z")
    fake.add("L2", title="far", due="2027-01-01T00:00:00.000Z")
    fake.add("L1", title="whenever")
    fake.add("L1", title="done", status="completed")
    svc.create_task("mine")
    ctx = svc.context(today=dt.date(2026, 10, 22))
    titles = {k: [t["title"] for t in v] for k, v in ctx.items() if isinstance(v, list)}
    assert titles == {
        "overdue": ["old"],
        "due_soon": ["soon"],
        "no_due_date": ["whenever", "mine"],
        "later": ["far"],
        "open_tasks_created_by_claude": ["mine"],
    }
    assert ctx["due_soon"][0]["tasklist"] == "Работа"


def test_list_filters(svc, fake):
    fake.add("L1", title="Отчёт за квартал", due="2026-10-30T00:00:00.000Z")
    fake.add("L1", title="Спортзал")
    svc.create_task("Отчёт: проверить цифры")
    assert [t["title"] for t in svc.list_tasks(query="отчёт")] == ["Отчёт за квартал", "Отчёт: проверить цифры"]
    assert [t["title"] for t in svc.list_tasks(due_before="2026-10-31")] == ["Отчёт за квартал"]
    assert [t["title"] for t in svc.list_tasks(only_claude=True)] == ["Отчёт: проверить цифры"]


def test_unknown_list(svc):
    with pytest.raises(ValueError, match="Работа"):
        svc.list_tasks(tasklist="Нет такого")
