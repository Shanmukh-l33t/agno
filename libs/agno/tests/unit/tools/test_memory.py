"""Regression tests for concurrent MemoryTools tool calls (issue #11772)."""

import json
import threading
import time

from agno.db.in_memory import InMemoryDb
from agno.db.schemas import UserMemory
from agno.run.base import RunContext
from agno.tools.memory import MemoryTools

MEMORY_ID = "mem-1"


class _SlowReadInMemoryDb(InMemoryDb):
    """Keeps a read open long enough for a second thread to read the same snapshot."""

    def __init__(self, read_delay_s: float = 0.2):
        super().__init__()
        self.read_delay_s = read_delay_s
        self.first_read_done = threading.Event()
        self.slow_reads = False

    def get_user_memory(self, memory_id, deserialize=True, user_id=None):
        result = super().get_user_memory(memory_id, deserialize=deserialize, user_id=user_id)
        if self.slow_reads:
            self.first_read_done.set()
            time.sleep(self.read_delay_s)
        return result


def _make_tools(db: InMemoryDb) -> MemoryTools:
    return MemoryTools(
        db=db,
        enable_get_memories=False,
        enable_add_memory=False,
        enable_delete_memory=False,
        enable_analyze=False,
        enable_think=False,
        add_instructions=False,
    )


def _run_context() -> RunContext:
    return RunContext(run_id="run-1", session_id="session-1", user_id="u1", session_state={})


def _seed(db: InMemoryDb, memory_id: str, memory: str, topics) -> None:
    db.upsert_user_memory(UserMemory(memory_id=memory_id, user_id="u1", memory=memory, topics=topics))


def test_concurrent_updates_to_same_memory_keep_both_fields():
    """Two update_memory calls for one memory_id in one turn must not overwrite each other."""
    db = _SlowReadInMemoryDb()
    _seed(db, MEMORY_ID, "Initial note", ["initial"])
    tools = _make_tools(db)
    run_context = _run_context()
    db.slow_reads = True

    def update_topics():
        # Enter the tool only after the other call has read the pre-update snapshot.
        assert db.first_read_done.wait(2.0)
        result = json.loads(tools.update_memory(run_context, memory_id=MEMORY_ID, topics=["preferences", "editor"]))
        assert result["success"] is True

    thread = threading.Thread(target=update_topics)
    thread.start()
    result = json.loads(tools.update_memory(run_context, memory_id=MEMORY_ID, memory="Prefers dark mode and Vim"))
    assert result["success"] is True
    thread.join(timeout=5)
    assert not thread.is_alive()

    db.slow_reads = False
    stored = db.get_user_memory(memory_id=MEMORY_ID)
    assert isinstance(stored, UserMemory)
    assert stored.memory == "Prefers dark mode and Vim"
    assert stored.topics == ["preferences", "editor"]
    # Both calls are recorded even though they raced on the shared session state list.
    assert run_context.session_state is not None
    assert [op["operation"] for op in run_context.session_state["memory_operations"]] == [
        "update_memory",
        "update_memory",
    ]


def test_updates_to_different_memories_are_not_serialised():
    """The per-memory lock must not turn into a global lock over the toolkit."""
    db = _SlowReadInMemoryDb(read_delay_s=0.3)
    _seed(db, "mem-a", "Note A", ["a"])
    _seed(db, "mem-b", "Note B", ["b"])
    tools = _make_tools(db)
    db.slow_reads = True

    def update(memory_id: str, memory: str):
        ctx = _run_context()
        assert json.loads(tools.update_memory(ctx, memory_id=memory_id, memory=memory))["success"] is True

    threads = [
        threading.Thread(target=update, args=("mem-a", "Note A updated")),
        threading.Thread(target=update, args=("mem-b", "Note B updated")),
    ]
    started = time.monotonic()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    elapsed = time.monotonic() - started

    assert elapsed < 0.45  # 0.3 s each: two serialised reads would need 0.6 s
    for memory_id, expected in (("mem-a", "Note A updated"), ("mem-b", "Note B updated")):
        stored = db.get_user_memory(memory_id=memory_id)
        assert isinstance(stored, UserMemory)
        assert stored.memory == expected


def test_all_tools_record_their_session_state_entries():
    """Locking and setdefault must leave every tool's session state bookkeeping intact."""
    db = InMemoryDb()
    tools = MemoryTools(db=db, add_instructions=False)
    run_context = _run_context()

    assert "Memory Thoughts" in tools.think(run_context, "look up preferences")
    assert tools.get_memories(run_context) == "[]"
    created = json.loads(tools.add_memory(run_context, memory="Likes Vim", topics=["editor"]))
    memory_id = created["memory"]["memory_id"]
    assert json.loads(tools.update_memory(run_context, memory_id=memory_id, topics=["editor", "tools"]))["success"]
    assert json.loads(tools.delete_memory(run_context, memory_id=memory_id))["success"]
    assert json.loads(tools.delete_memory(run_context, memory_id=memory_id))["success"] is False
    assert "Memory Analysis" in tools.analyze(run_context, "all good")

    assert run_context.session_state is not None
    assert [op["operation"] for op in run_context.session_state["memory_operations"]] == [
        "get_memories",
        "add_memory",
        "update_memory",
        "delete_memory",
    ]
    assert run_context.session_state["memory_thoughts"] == ["look up preferences"]
    assert run_context.session_state["memory_analysis"] == ["all good"]
