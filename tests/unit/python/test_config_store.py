"""
Test suite for ConfigStore - Configuration management with SQLite backend.
"""

import pytest
import tempfile
from pathlib import Path

from src.nori_core.data.database_manager import DatabaseManager
from src.nori_core.configuration.config_store import (
    ConfigStore,
    TelemetryConsent,
    ConfigSchema,
)


@pytest.fixture
async def config_store():
    """Create a temporary config store for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    
    db_manager = DatabaseManager(db_path)
    await db_manager.initialize()
    
    store = ConfigStore(db_manager)
    await store.initialize()
    
    yield store
    
    await db_manager.close()
    db_path.unlink(missing_ok=True)


class TestConfigStore:
    """Test cases for ConfigStore."""
    
    @pytest.mark.asyncio
    async def test_initialization(self, config_store):
        """Test config store initializes correctly."""
        assert config_store._initialized is True
        assert len(config_store._cache) > 0
    
    @pytest.mark.asyncio
    async def test_get_default_value(self, config_store):
        """Test getting default configuration values."""
        version = await config_store.get("app_version")
        assert version == ""
        
        first_run = await config_store.get("first_run")
        assert first_run == "true"
        
        language = await config_store.get("language")
        assert language == "zh-CN"
    
    @pytest.mark.asyncio
    async def test_set_and_get_value(self, config_store):
        """Test setting and retrieving configuration values."""
        await config_store.set("language", "en-US")
        
        value = await config_store.get("language")
        assert value == "en-US"
    
    @pytest.mark.asyncio
    async def test_get_string_or(self, config_store):
        """Test get_string_or method."""
        await config_store.set("theme", "dark_mode")
        
        theme = await config_store.get_string_or("theme", "default")
        assert theme == "dark_mode"
        
        # Non-existent key with default
        missing = await config_store.get_string_or("nonexistent", "fallback")
        assert missing == "fallback"
    
    @pytest.mark.asyncio
    async def test_telemetry_consent_enum(self, config_store):
        """Test telemetry consent enum handling."""
        # Default should be NOT_ASKED
        consent = config_store.get_telemetry_consent()
        assert consent == TelemetryConsent.NOT_ASKED
        
        # Set to GRANTED
        await config_store.set("telemetry_consent", TelemetryConsent.GRANTED)
        consent = config_store.get_telemetry_consent()
        assert consent == TelemetryConsent.GRANTED
        
        # Set to DENIED
        await config_store.set("telemetry_consent", TelemetryConsent.DENIED)
        consent = config_store.get_telemetry_consent()
        assert consent == TelemetryConsent.DENIED
    
    @pytest.mark.asyncio
    async def test_mark_first_run_completed(self, config_store):
        """Test marking first run as completed."""
        assert config_store.is_first_run() is True
        
        config_store.mark_first_run_completed()
        
        # Cache should be updated immediately
        assert config_store._cache["first_run"] == "false"
    
    @pytest.mark.asyncio
    async def test_mark_initialized(self, config_store):
        """Test marking application as initialized."""
        config_store.mark_initialized()
        assert config_store._cache["initialized"] == "true"
    
    @pytest.mark.asyncio
    async def test_is_first_run_boolean(self, config_store):
        """Test is_first_run with boolean values."""
        await config_store.set("first_run", "false")
        assert config_store.is_first_run() is False
        
        await config_store.set("first_run", "true")
        assert config_store.is_first_run() is True
    
    @pytest.mark.asyncio
    async def test_cache_hit(self, config_store):
        """Test that cache is used for subsequent reads."""
        # First read loads into cache
        await config_store.get("language")
        
        # Modify cache directly to simulate cached value
        config_store._cache["language"] = "cached_value"
        
        # Should return cached value without DB lookup
        value = await config_store.get("language")
        assert value == "cached_value"
    
    @pytest.mark.asyncio
    async def test_set_with_enum(self, config_store):
        """Test setting enum values."""
        await config_store.set("telemetry_consent", TelemetryConsent.GRANTED)
        
        # Verify stored as Enum instance (now that default is Enum type)
        raw_value = await config_store.get("telemetry_consent")
        assert raw_value == TelemetryConsent.GRANTED or raw_value.value == "granted"
    
    @pytest.mark.asyncio
    async def test_double_initialization(self, config_store):
        """Test that double initialization is safe."""
        initial_cache_size = len(config_store._cache)
        await config_store.initialize()
        assert len(config_store._cache) == initial_cache_size
    
    @pytest.mark.asyncio
    async def test_get_nonexistent_key(self, config_store):
        """Test getting a non-existent key returns None or default."""
        value = await config_store.get("nonexistent_key")
        assert value is None
        
        # With custom default
        value_with_default = await config_store.get("nonexistent_key", "default_val")
        assert value_with_default == "default_val"
    
    @pytest.mark.asyncio
    async def test_config_schema_structure(self):
        """Test CONFIG_SCHEMA structure."""
        schema = ConfigStore.CONFIG_SCHEMA
        
        # Should have defined schemas
        assert len(schema) > 0
        
        # Each schema should have required fields
        for s in schema:
            assert isinstance(s.key, str)
            assert s.default is not None
            assert isinstance(s.description, str)
            assert isinstance(s.is_sensitive, bool)
    
    @pytest.mark.asyncio
    async def test_voice_enabled_default(self, config_store):
        """Test voice_enabled default value."""
        value = await config_store.get("voice_enabled")
        assert value == "true"
    
    @pytest.mark.asyncio
    async def test_auto_start_default(self, config_store):
        """Test auto_start default value."""
        value = await config_store.get("auto_start")
        assert value == "false"
    
    @pytest.mark.asyncio
    async def test_minimize_to_tray_default(self, config_store):
        """Test minimize_to_tray default value."""
        value = await config_store.get("minimize_to_tray")
        assert value == "true"
    
    @pytest.mark.asyncio
    async def test_theme_default(self, config_store):
        """Test theme default value."""
        value = await config_store.get("theme")
        assert value == "deep_sea_glow"
    
    @pytest.mark.asyncio
    async def test_allow_insecure_tls_default(self, config_store):
        """Test allow_insecure_tls default value."""
        value = await config_store.get("allow_insecure_tls")
        assert value == "false"


class TestConfigStoreEdgeCases:
    """Edge case tests for ConfigStore."""
    
    @pytest.mark.asyncio
    async def test_empty_string_value(self):
        """Test handling empty string values."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)
        
        try:
            db_manager = DatabaseManager(db_path)
            await db_manager.initialize()
            store = ConfigStore(db_manager)
            await store.initialize()
            
            await store.set("app_version", "")
            value = await store.get("app_version")
            assert value == ""
        finally:
            await db_manager.close()
            db_path.unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_unicode_value(self):
        """Test handling Unicode values."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)
        
        try:
            db_manager = DatabaseManager(db_path)
            await db_manager.initialize()
            store = ConfigStore(db_manager)
            await store.initialize()
            
            await store.set("language", "日本語")
            value = await store.get("language")
            assert value == "日本語"
        finally:
            await db_manager.close()
            db_path.unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_long_string_value(self):
        """Test handling very long string values."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)
        
        try:
            db_manager = DatabaseManager(db_path)
            await db_manager.initialize()
            store = ConfigStore(db_manager)
            await store.initialize()
            
            long_value = "x" * 10000
            await store.set("app_version", long_value)
            value = await store.get("app_version")
            assert value == long_value
        finally:
            await db_manager.close()
            db_path.unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_validator_rejection(self):
        """Test that validator rejects invalid values."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)
        
        try:
            db_manager = DatabaseManager(db_path)
            await db_manager.initialize()
            store = ConfigStore(db_manager)
            await store.initialize()
            
            # Add a schema with validator
            schema_with_validator = ConfigSchema(
                key="test_validated_key",
                default="default",
                description="Test key with validator",
                validator=lambda v: isinstance(v, str) and len(v) > 0
            )
            original_schema = list(store.CONFIG_SCHEMA)
            store.CONFIG_SCHEMA.append(schema_with_validator)
            
            # Valid value should work
            await store.set("test_validated_key", "valid")
            value = await store.get("test_validated_key")
            assert value == "valid"
            
            # Invalid value should raise ValueError
            with pytest.raises(ValueError):
                await store.set("test_validated_key", "")
            
            # Restore original schema
            store.CONFIG_SCHEMA = original_schema
        finally:
            await db_manager.close()
            db_path.unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_parse_value_with_invalid_numeric(self):
        """Test _parse_value handles invalid numeric conversions."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)
        
        try:
            db_manager = DatabaseManager(db_path)
            await db_manager.initialize()
            store = ConfigStore(db_manager)
            await store.initialize()
            
            # Test with a non-numeric string for numeric type
            # This tests the fallback to default in _parse_value
            result = store._parse_value("nonexistent_numeric", "not_a_number")
            assert result is not None  # Should return something reasonable
        finally:
            await db_manager.close()
            db_path.unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_concurrent_access(self):
        """Test thread-safe concurrent access."""
        import asyncio
        
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)
        
        try:
            db_manager = DatabaseManager(db_path)
            await db_manager.initialize()
            store = ConfigStore(db_manager)
            await store.initialize()
            
            async def set_value(i):
                await store.set("concurrent_key", f"value_{i}")
                await asyncio.sleep(0.001)
            
            # Run multiple concurrent writes
            await asyncio.gather(*[set_value(i) for i in range(10)])
            
            # Final value should be one of the written values
            final_value = await store.get("concurrent_key")
            assert final_value.startswith("value_")
        finally:
            await db_manager.close()
            db_path.unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_initialize_during_get(self):
        """Test that get() triggers initialization if not initialized."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)
        
        try:
            db_manager = DatabaseManager(db_path)
            await db_manager.initialize()
            store = ConfigStore(db_manager)
            # Don't initialize explicitly
            
            # get() should trigger initialization
            value = await store.get("language")
            assert value == "zh-CN"
            assert store._initialized is True
        finally:
            await db_manager.close()
            db_path.unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_initialize_during_set(self):
        """Test that set() triggers initialization if not initialized."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)
        
        try:
            db_manager = DatabaseManager(db_path)
            await db_manager.initialize()
            store = ConfigStore(db_manager)
            # Don't initialize explicitly
            
            # set() should trigger initialization
            await store.set("theme", "custom_theme")
            assert store._initialized is True
            
            value = await store.get("theme")
            assert value == "custom_theme"
        finally:
            await db_manager.close()
            db_path.unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_double_initialization_concurrent(self):
        """Test concurrent double initialization is safe (covers line 78)."""
        import asyncio
        
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)
        
        try:
            db_manager = DatabaseManager(db_path)
            await db_manager.initialize()
            store = ConfigStore(db_manager)
            
            # Simulate concurrent initialization calls
            async def init_call():
                await store.initialize()
            
            await asyncio.gather(*[init_call() for _ in range(5)])
            assert store._initialized is True
        finally:
            await db_manager.close()
            db_path.unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_parse_value_enum_invalid(self):
        """Test _parse_value handles invalid enum values (covers lines 133-136)."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)
        
        try:
            db_manager = DatabaseManager(db_path)
            await db_manager.initialize()
            store = ConfigStore(db_manager)
            await store.initialize()
            
            # Manually insert invalid enum value into DB
            async with store._db.get_connection() as conn:
                await conn.execute(
                    "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
                    ("telemetry_consent", "invalid_value")
                )
            
            # Clear cache to force reload
            store._cache.clear()
            
            # Should fallback to default when parsing invalid enum
            # The _parse_value method returns schema.default (the Enum instance) on error
            consent = await store.get("telemetry_consent")
            # After get(), the cache will have the default Enum value
            cached_consent = store._cache.get("telemetry_consent")
            assert cached_consent == TelemetryConsent.NOT_ASKED
        finally:
            await db_manager.close()
            db_path.unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_parse_value_boolean_false_string(self):
        """Test _parse_value handles boolean string 'false' (covers line 140)."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)
        
        try:
            db_manager = DatabaseManager(db_path)
            await db_manager.initialize()
            store = ConfigStore(db_manager)
            await store.initialize()
            
            # Manually insert boolean value
            async with store._db.get_connection() as conn:
                await conn.execute(
                    "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
                    ("first_run", "false")
                )
            
            # Clear cache to force reload
            store._cache.clear()
            
            # Should parse as boolean
            value = await store.get("first_run")
            assert value is False or value == "false"
        finally:
            await db_manager.close()
            db_path.unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_get_from_database_not_cache(self):
        """Test get() fetches from DB when not in cache (covers lines 178-180)."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)
        
        try:
            db_manager = DatabaseManager(db_path)
            await db_manager.initialize()
            store = ConfigStore(db_manager)
            await store.initialize()
            
            # Set a value
            await store.set("theme", "test_theme")
            
            # Clear cache to force DB lookup
            store._cache.clear()
            
            # Get should fetch from DB and update cache
            value = await store.get("theme")
            assert value == "test_theme"
            assert "theme" in store._cache
        finally:
            await db_manager.close()
            db_path.unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_get_telemetry_consent_cached_enum(self):
        """Test get_telemetry_consent with cached Enum value (covers line 223)."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)
        
        try:
            db_manager = DatabaseManager(db_path)
            await db_manager.initialize()
            store = ConfigStore(db_manager)
            await store.initialize()
            
            # Directly set cached value as Enum instance
            store._cache["telemetry_consent"] = TelemetryConsent.GRANTED
            
            # Should return the cached Enum directly
            consent = store.get_telemetry_consent()
            assert consent == TelemetryConsent.GRANTED
            assert isinstance(consent, TelemetryConsent)
        finally:
            await db_manager.close()
            db_path.unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_get_telemetry_consent_invalid_cached_value(self):
        """Test get_telemetry_consent with invalid cached value (covers lines 226-227)."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)
        
        try:
            db_manager = DatabaseManager(db_path)
            await db_manager.initialize()
            store = ConfigStore(db_manager)
            await store.initialize()
            
            # Set invalid cached value
            store._cache["telemetry_consent"] = "invalid_consent_value"
            
            # Should fallback to NOT_ASKED
            consent = store.get_telemetry_consent()
            assert consent == TelemetryConsent.NOT_ASKED
        finally:
            await db_manager.close()
            db_path.unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_is_first_run_with_boolean_true(self):
        """Test is_first_run with boolean True in cache (covers line 242)."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)
        
        try:
            db_manager = DatabaseManager(db_path)
            await db_manager.initialize()
            store = ConfigStore(db_manager)
            await store.initialize()
            
            # Directly set boolean in cache
            store._cache["first_run"] = True
            
            # Should handle boolean directly
            assert store.is_first_run() is True
        finally:
            await db_manager.close()
            db_path.unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_ensure_schema_version(self):
        """Test ensure_schema_version method (covers line 248)."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)
        
        try:
            db_manager = DatabaseManager(db_path)
            await db_manager.initialize()
            store = ConfigStore(db_manager)
            await store.initialize()
            
            # Should not raise
            await store.ensure_schema_version()
        finally:
            await db_manager.close()
            db_path.unlink(missing_ok=True)
