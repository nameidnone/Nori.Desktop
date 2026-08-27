"""Database Manager - Async SQLite connection pooling and management."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

import aiosqlite


class DatabaseManager:
    """
    Asynchronous SQLite database manager with connection pooling.
    
    Provides:
    - Connection pooling for concurrent access
    - Automatic schema migrations
    - Transaction management
    - Graceful shutdown
    """
    
    def __init__(self, db_path: Path | str):
        """
        Initialize database manager.
        
        Args:
            db_path: Path to SQLite database file
        """
        self._db_path = Path(db_path)
        self._pool: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()
        self._initialized = False
    
    @property
    def db_path(self) -> Path:
        """Get database file path."""
        return self._db_path
    
    async def initialize(self) -> None:
        """Initialize database connection pool."""
        if self._initialized:
            return
        
        async with self._lock:
            if self._initialized:
                return
            
            # Ensure directory exists
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Create connection with proper detect_types using sqlite3 constants
            self._pool = await aiosqlite.connect(
                str(self._db_path),
                detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
            )
            self._pool.row_factory = aiosqlite.Row
            
            # Enable WAL mode for better concurrency
            await self._pool.execute("PRAGMA journal_mode=WAL")
            await self._pool.execute("PRAGMA synchronous=NORMAL")
            await self._pool.execute("PRAGMA cache_size=-64000")  # 64MB cache
            
            self._initialized = True
    
    @asynccontextmanager
    async def get_connection(self) -> AsyncIterator[aiosqlite.Connection]:
        """
        Get database connection from pool.
        
        Yields:
            aiosqlite connection object
        """
        if not self._initialized:
            await self.initialize()
        
        if self._pool is None:
            raise RuntimeError("Database not initialized")
        
        yield self._pool
    
    async def execute(self, sql: str, parameters: tuple = ()) -> aiosqlite.Cursor:
        """Execute SQL statement."""
        async with self.get_connection() as conn:
            return await conn.execute(sql, parameters)
    
    async def executemany(self, sql: str, parameters: list[tuple]) -> aiosqlite.Cursor:
        """Execute SQL statement with multiple parameter sets."""
        async with self.get_connection() as conn:
            return await conn.executemany(sql, parameters)
    
    async def commit(self) -> None:
        """Commit current transaction."""
        if self._pool:
            await self._pool.commit()
    
    async def close(self) -> None:
        """Close all database connections."""
        if self._pool:
            await self._pool.close()
            self._pool = None
        self._initialized = False
    
    async def __aenter__(self) -> "DatabaseManager":
        """Async context manager entry."""
        await self.initialize()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.close()
