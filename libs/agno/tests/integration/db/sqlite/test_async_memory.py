"""Integration tests for AsyncSqliteDb memory methods.

Regression tests for https://github.com/agno-agi/agno/issues/11349 (defect 1):
upserting into a fresh AsyncSqliteDb used to be silently discarded because the
memory write paths resolved the memories table without creating it.
"""

from agno.db.schemas.memory import UserMemory
from agno.db.sqlite import AsyncSqliteDb


async def test_upsert_user_memory_creates_table_on_fresh_db():
    """A single write on a fresh db must create the memories table and persist."""
    db = AsyncSqliteDb(db_url="sqlite+aiosqlite:///:memory:")
    try:
        saved = await db.upsert_user_memory(UserMemory(memory_id="m1", memory="Likes tea", user_id="u1"))
        assert saved is not None

        memories = await db.get_user_memories(user_id="u1")
        assert len(memories) == 1
        assert memories[0].memory_id == "m1"
        assert memories[0].memory == "Likes tea"
    finally:
        await db.close()


async def test_upsert_memories_bulk_creates_table_on_fresh_db():
    """A bulk write on a fresh db must create the memories table and persist every row."""
    db = AsyncSqliteDb(db_url="sqlite+aiosqlite:///:memory:")
    try:
        results = await db.upsert_memories(
            [
                UserMemory(memory_id="m2", memory="Likes coffee", user_id="u1"),
                UserMemory(memory_id="m3", memory="Likes tea", user_id="u2"),
            ]
        )
        assert len(results) == 2

        assert len(await db.get_user_memories(user_id="u1")) == 1
        assert len(await db.get_user_memories(user_id="u2")) == 1
    finally:
        await db.close()
