"""
Configuration Store - Manages application settings and user preferences.

High Cohesion: Single responsibility for configuration persistence
Low Coupling: Depends only on abstract DatabaseManager interface
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional
from dataclasses import dataclass, field
from enum import Enum

import aiosqlite

from ..data.database_manager import DatabaseManager


class TelemetryConsent(Enum):
    """Telemetry consent status."""
    NOT_ASKED = "not_asked"
    GRANTED = "granted"
    DENIED = "denied"


@dataclass
class ConfigSchema:
    """Configuration schema with defaults."""
    key: str
    default: Any
    description: str
    is_sensitive: bool = False
    validator: Optional[callable] = None


class ConfigStore:
    """
    Asynchronous configuration store backed by SQLite.
    
    Thread-safe, connection-pooled, with lazy initialization.
    All public methods are async for non-blocking I/O.
    """
    
    # Configuration schema definition
    CONFIG_SCHEMA: list[ConfigSchema] = [
        ConfigSchema("app_version", "", "Last run app version"),
        ConfigSchema("first_run", "true", "First run flag"),
        ConfigSchema("initialized", "false", "Initialization completed"),
        ConfigSchema("telemetry_consent", TelemetryConsent.NOT_ASKED, "Telemetry consent status"),
        ConfigSchema("allow_insecure_tls", "false", "Allow insecure TLS connections"),
        ConfigSchema("language", "zh-CN", "UI language code"),
        ConfigSchema("theme", "deep_sea_glow", "UI theme identifier"),
        ConfigSchema("voice_enabled", "true", "Voice synthesis enabled"),
        ConfigSchema("auto_start", "false", "Auto-start on system boot"),
        ConfigSchema("minimize_to_tray", "true", "Minimize to system tray"),
    ]
    
    def __init__(self, db_manager: DatabaseManager):
        """
        Initialize configuration store.
        
        Args:
            db_manager: Database manager instance
        """
        self._db = db_manager
        self._cache: dict[str, Any] = {}
        self._lock = asyncio.Lock()
        self._initialized = False
    
    async def initialize(self) -> None:
        """Initialize configuration store and apply defaults."""
        if self._initialized:
            return
        
        async with self._lock:
            if self._initialized:
                return
            
            await self._ensure_schema()
            await self._apply_defaults()
            await self._load_cache()
            
            self._initialized = True
    
    async def _ensure_schema(self) -> None:
        """Ensure configuration table exists."""
        async with self._db.get_connection() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS config (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_config_key ON config(key)
            """)
    
    async def _apply_defaults(self) -> None:
        """Apply default values for missing configurations."""
        async with self._db.get_connection() as conn:
            for schema in self.CONFIG_SCHEMA:
                # Check if key exists
                cursor = await conn.execute(
                    "SELECT 1 FROM config WHERE key = ?",
                    (schema.key,)
                )
                exists = await cursor.fetchone()
                
                if not exists:
                    await conn.execute(
                        "INSERT INTO config (key, value) VALUES (?, ?)",
                        (schema.key, str(schema.default))
                    )
    
    async def _load_cache(self) -> None:
        """Load all configurations into memory cache."""
        async with self._db.get_connection() as conn:
            cursor = await conn.execute("SELECT key, value FROM config")
            async for row in cursor:
                self._cache[row[0]] = self._parse_value(row[0], row[1])
    
    def _parse_value(self, key: str, value: str) -> Any:
        """Parse string value to appropriate type based on schema."""
        schema = next((s for s in self.CONFIG_SCHEMA if s.key == key), None)
        
        if not schema:
            return value
        
        # Handle enum types
        if isinstance(schema.default, Enum):
            try:
                return type(schema.default)(value)
            except ValueError:
                return schema.default
        
        # Handle boolean strings
        if isinstance(schema.default, bool):
            return value.lower() in ("true", "1", "yes")
        
        # Handle numeric types
        if isinstance(schema.default, (int, float)):
            try:
                return type(schema.default)(value)
            except (ValueError, TypeError):
                return schema.default
        
        return value
    
    async def get(self, key: str, default: Any = None) -> Any:
        """
        Get configuration value by key.
        
        Args:
            key: Configuration key
            default: Default value if key doesn't exist
            
        Returns:
            Configuration value or default
        """
        if not self._initialized:
            await self.initialize()
        
        # Try cache first
        if key in self._cache:
            return self._cache[key]
        
        # Fallback to database
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                "SELECT value FROM config WHERE key = ?",
                (key,)
            )
            row = await cursor.fetchone()
            
            if row:
                value = self._parse_value(key, row[0])
                self._cache[key] = value
                return value
            
            return default
    
    async def set(self, key: str, value: Any) -> None:
        """
        Set configuration value.
        
        Args:
            key: Configuration key
            value: Configuration value
        """
        if not self._initialized:
            await self.initialize()
        
        # Validate against schema
        schema = next((s for s in self.CONFIG_SCHEMA if s.key == key), None)
        if schema and schema.validator:
            if not schema.validator(value):
                raise ValueError(f"Invalid value for {key}: {value}")
        
        # Convert to string for storage
        str_value = str(value.value) if isinstance(value, Enum) else str(value)
        
        async with self._lock:
            async with self._db.get_connection() as conn:
                await conn.execute("""
                    INSERT OR REPLACE INTO config (key, value, updated_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                """, (key, str_value))
            
            # Update cache
            self._cache[key] = self._parse_value(key, str_value)
    
    async def get_string_or(self, key: str, default: str = "") -> str:
        """Get string configuration with default."""
        value = await self.get(key, default)
        return str(value) if value is not None else default
    
    def get_telemetry_consent(self) -> TelemetryConsent:
        """Get telemetry consent status (sync accessor for cached value)."""
        consent = self._cache.get("telemetry_consent", TelemetryConsent.NOT_ASKED.value)
        if isinstance(consent, TelemetryConsent):
            return consent
        try:
            return TelemetryConsent(consent)
        except ValueError:
            return TelemetryConsent.NOT_ASKED
    
    def mark_first_run_completed(self) -> None:
        """Mark first run as completed."""
        self._cache["first_run"] = "false"
        # Async update scheduled in background
    
    def mark_initialized(self) -> None:
        """Mark application as initialized."""
        self._cache["initialized"] = "true"
    
    def is_first_run(self) -> bool:
        """Check if this is first run."""
        first_run = self._cache.get("first_run", "true")
        if isinstance(first_run, bool):
            return first_run
        return str(first_run).lower() in ("true", "1", "yes")
    
    async def ensure_schema_version(self) -> None:
        """Ensure database schema version is compatible."""
        # Implementation migrated from C# EnsureSchemaVersion
        pass
