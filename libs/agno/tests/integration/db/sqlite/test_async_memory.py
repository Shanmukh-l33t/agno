"""Regression tests for the Memory pagination of the AsyncSqliteDb class (issue #11499)."""

from pathlib import Path

from agno.db.schemas.memory import UserMemory
from agno.db.sqlite import AsyncSqliteDb


async def test_async_get_user_memories_empty_page_keeps_total_count(tmp_path: Path):
    """An empty requested page must still report the filtered total count (issue #11499)."""
    db = AsyncSqliteDb(db_file=str(tmp_path / "async_memories.db"))
    await db._create_all_tables()
    try:
        for i in range(3):
            await db.upsert_user_memory(
                UserMemory(memory_id=f"m{i}", memory=f"Synthetic memory {i}", user_id="alice"), deserialize=True
            )

        rows, total = await db.get_user_memories(
            user_id="alice", limit=2, page=3, sort_by="memory_id", sort_order="asc", deserialize=False
        )
        assert len(rows) == 0
        assert total == 3  # page 3 is empty but three memories match the filter

        # Deleting the only item on the last page must not zero the reported total.
        await db.delete_user_memory("m2", user_id="alice")
        rows, total = await db.get_user_memories(
            user_id="alice", limit=2, page=2, sort_by="memory_id", sort_order="asc", deserialize=False
        )
        assert len(rows) == 0
        assert total == 2
    finally:
        await db.close()
