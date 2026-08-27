"""
Test suite for nori_core lazy loading mechanism.
Tests only the implemented modules (config_store and database_manager).
Other modules are planned for Phase 2 implementation.
"""

import pytest
import sys


class TestLazyLoading:
    """Test cases for lazy loading of implemented nori_core modules."""
    
    def test_config_store_lazy_load(self):
        """Test ConfigStore is loaded on demand."""
        # Ensure module is not loaded yet
        if 'src.nori_core.configuration.config_store' in sys.modules:
            del sys.modules['src.nori_core.configuration.config_store']
        
        import src.nori_core as nc
        
        # Access should trigger loading
        config_store_class = nc.ConfigStore
        assert config_store_class.__name__ == 'ConfigStore'
        assert 'src.nori_core.configuration.config_store' in sys.modules
    
    def test_database_manager_lazy_load(self):
        """Test DatabaseManager is loaded on demand."""
        if 'src.nori_core.data.database_manager' in sys.modules:
            del sys.modules['src.nori_core.data.database_manager']
        
        import src.nori_core as nc
        
        db_manager_class = nc.DatabaseManager
        assert db_manager_class.__name__ == 'DatabaseManager'
        assert 'src.nori_core.data.database_manager' in sys.modules
    
    def test_getattr_invalid_attribute(self):
        """Test that accessing invalid attribute raises AttributeError."""
        import src.nori_core as nc
        
        with pytest.raises(AttributeError, match="module 'src.nori_core' has no attribute 'InvalidAttribute'"):
            _ = nc.InvalidAttribute
    
    def test_implemented_exports_accessible(self):
        """Test that implemented exports are accessible."""
        import src.nori_core as nc
        
        # Only test actually implemented modules
        implemented = ['ConfigStore', 'DatabaseManager']
        for export in implemented:
            assert hasattr(nc, export), f"{export} should be accessible"
            attr = getattr(nc, export)
            assert attr is not None, f"{export} should not be None"


class TestModuleMetadata:
    """Test module metadata and configuration."""
    
    def test_version_format(self):
        """Test version follows semantic versioning pattern."""
        import src.nori_core as nc
        
        version = nc.__version__
        parts = version.split('.')
        assert len(parts) >= 2, "Version should have at least major.minor"
        assert all(part.isdigit() for part in parts[:2]), "Major and minor should be numeric"
    
    def test_author_not_empty(self):
        """Test author metadata is not empty."""
        import src.nori_core as nc
        
        assert len(nc.__author__) > 0, "Author should not be empty"
    
    def test_all_is_list(self):
        """Test __all__ is a list."""
        import src.nori_core as nc
        
        assert isinstance(nc.__all__, list), "__all__ should be a list"
        assert len(nc.__all__) > 0, "__all__ should not be empty"
    
    def test_no_duplicates_in_all(self):
        """Test __all__ has no duplicate entries."""
        import src.nori_core as nc
        
        all_exports = nc.__all__
        assert len(all_exports) == len(set(all_exports)), "__all__ should have no duplicates"
    
    def test_all_exports_unique_names(self):
        """Test all exports have unique names."""
        import src.nori_core as nc
        
        export_names = [name for name in nc.__all__]
        assert len(export_names) == len(set(export_names)), "All export names should be unique"
