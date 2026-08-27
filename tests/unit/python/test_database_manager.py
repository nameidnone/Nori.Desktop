"""
Test suite for DatabaseManager - Async SQLite connection pooling.
"""

import pytest
import tempfile
from pathlib import Path

from src.nori_core.data.database_manager import DatabaseManager


@pytest.fixture
async def db_manager():
    """Create a temporary database manager for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    
    manager = DatabaseManager(db_path)
    await manager.initialize()
    
    yield manager
    
    await manager.close()
    db_path.unlink(missing_ok=True)


class TestDatabaseManager:
    """Test cases for DatabaseManager."""
    
    @pytest.mark.asyncio
    async def test_initialization(self, db_manager):
        """Test database manager initializes correctly."""
        assert db_manager._initialized is True
        assert db_manager._pool is not None
    
    @pytest.mark.asyncio
    async def test_db_path_property(self, db_manager):
        """Test db_path returns correct Path object."""
        assert isinstance(db_manager.db_path, Path)
        assert db_manager.db_path.suffix == ".db"
    
    @pytest.mark.asyncio
    async def test_get_connection(self, db_manager):
        """Test getting connection from pool."""
        async with db_manager.get_connection() as conn:
            assert conn is not None
            # Test basic query
            cursor = await conn.execute("SELECT 1")
            result = await cursor.fetchone()
            assert result[0] == 1
    
    @pytest.mark.asyncio
    async def test_execute_statement(self, db_manager):
        """Test executing SQL statements."""
        # Create table
        await db_manager.execute("""
            CREATE TABLE IF NOT EXISTS test_table (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL
            )
        """)
        
        # Insert data
        await db_manager.execute(
            "INSERT INTO test_table (name) VALUES (?)",
            ("test_name",)
        )
        
        # Query data
        cursor = await db_manager.execute(
            "SELECT name FROM test_table WHERE id = 1"
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "test_name"
    
    @pytest.mark.asyncio
    async def test_executemany(self, db_manager):
        """Test executing with multiple parameter sets."""
        await db_manager.execute("""
            CREATE TABLE IF NOT EXISTS batch_table (
                id INTEGER PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        
        # Batch insert
        params = [
            ("value1",),
            ("value2",),
            ("value3",),
        ]
        await db_manager.executemany(
            "INSERT INTO batch_table (value) VALUES (?)",
            params
        )
        
        # Verify count
        cursor = await db_manager.execute("SELECT COUNT(*) FROM batch_table")
        row = await cursor.fetchone()
        assert row[0] == 3
    
    @pytest.mark.asyncio
    async def test_commit(self, db_manager):
        """Test transaction commit."""
        await db_manager.execute("""
            CREATE TABLE IF NOT EXISTS commit_test (
                id INTEGER PRIMARY KEY
            )
        """)
        
        await db_manager.execute("INSERT INTO commit_test (id) VALUES (1)")
        await db_manager.commit()
        
        # Verify data persisted
        cursor = await db_manager.execute("SELECT COUNT(*) FROM commit_test")
        row = await cursor.fetchone()
        assert row[0] == 1
    
    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test async context manager protocol."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)
        
        try:
            async with DatabaseManager(db_path) as manager:
                assert manager._initialized is True
                await manager.execute("SELECT 1")
            
            # After context exit, should be closed
            assert manager._initialized is False
        finally:
            db_path.unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_double_initialization(self, db_manager):
        """Test that double initialization is safe."""
        initial_pool = db_manager._pool
        await db_manager.initialize()
        assert db_manager._pool is initial_pool
    
    @pytest.mark.asyncio
    async def test_close_and_reopen(self):
        """Test closing and reopening database."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)
        
        try:
            manager = DatabaseManager(db_path)
            await manager.initialize()
            assert manager._initialized is True
            
            await manager.close()
            assert manager._initialized is False
            
            # Reopen
            await manager.initialize()
            assert manager._initialized is True
            
            await manager.close()
        finally:
            db_path.unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_wal_mode_enabled(self, db_manager):
        """Test that WAL mode is enabled for better concurrency."""
        async with db_manager.get_connection() as conn:
            cursor = await conn.execute("PRAGMA journal_mode")
            row = await cursor.fetchone()
            assert row[0] == "wal"
    
    @pytest.mark.asyncio
    async def test_synchronous_normal(self, db_manager):
        """Test synchronous mode is set to NORMAL."""
        async with db_manager.get_connection() as conn:
            cursor = await conn.execute("PRAGMA synchronous")
            row = await cursor.fetchone()
            assert row[0] == 1  # NORMAL mode
    
    @pytest.mark.asyncio
    async def test_initialize_already_initialized(self):
        """Test initialize returns early when already initialized (covers line 49)."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)
        
        try:
            manager = DatabaseManager(db_path)
            await manager.initialize()
            initial_pool = manager._pool
            
            # Call initialize again - should return early
            await manager.initialize()
            
            # Pool should be the same object
            assert manager._pool is initial_pool
        finally:
            await manager.close()
            db_path.unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_get_connection_triggers_initialize(self):
        """Test get_connection triggers initialization if needed (covers line 77)."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)
        
        try:
            manager = DatabaseManager(db_path)
            # Don't call initialize explicitly
            
            # get_connection should trigger initialization
            async with manager.get_connection() as conn:
                assert manager._initialized is True
                cursor = await conn.execute("SELECT 1")
                result = await cursor.fetchone()
                assert result[0] == 1
        finally:
            await manager.close()
            db_path.unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_get_connection_not_initialized_error(self):
        """Test get_connection raises error when pool is None (covers line 80)."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)
        
        try:
            manager = DatabaseManager(db_path)
            # Set initialized but keep pool None to simulate error state
            manager._initialized = True
            manager._pool = None
            
            with pytest.raises(RuntimeError, match="Database not initialized"):
                async with manager.get_connection():
                    pass
        finally:
            db_path.unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_commit_without_pool(self):
        """Test commit handles None pool gracefully (covers line 96->exit)."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)
        
        try:
            manager = DatabaseManager(db_path)
            # Don't initialize - pool is None
            
            # Should not raise, just do nothing
            await manager.commit()
        finally:
            db_path.unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_close_sets_initialized_false(self):
        """Test close sets _initialized to False (covers line 104)."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)
        
        try:
            manager = DatabaseManager(db_path)
            await manager.initialize()
            assert manager._initialized is True
            
            await manager.close()
            assert manager._initialized is False
            assert manager._pool is None
        finally:
            db_path.unlink(missing_ok=True)

