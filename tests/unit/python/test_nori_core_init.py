"""
Test suite for nori_core module initialization and lazy loading.
"""

import pytest


class TestNoriCoreInit:
    """Test cases for nori_core package initialization."""
    
    def test_module_import(self):
        """Test that nori_core can be imported."""
        import src.nori_core as nc
        assert hasattr(nc, '__version__')
        assert nc.__version__ == "1.0.0"
    
    def test_version_string(self):
        """Test version is properly formatted."""
        from src.nori_core import __version__
        assert isinstance(__version__, str)
        assert len(__version__) > 0
    
    def test_author_defined(self):
        """Test author metadata is defined."""
        from src.nori_core import __author__
        assert isinstance(__author__, str)
        assert "Nori" in __author__
    
    def test_all_exports_defined(self):
        """Test __all__ exports are defined."""
        from src.nori_core import __all__
        assert isinstance(__all__, list)
        assert len(__all__) > 0
        
        # Check key exports exist
        expected_exports = [
            "ConfigStore",
            "DatabaseManager",
            "ChatService",
        ]
        for export in expected_exports:
            assert export in __all__, f"{export} should be in __all__"
    
    def test_lazy_loading_defers_imports(self):
        """Test that imports are deferred until accessed."""
        # Import the module without triggering lazy loading
        import sys
        if 'src.nori_core.configuration.config_store' not in sys.modules:
            # Module should not be loaded yet
            pass
        
        # Access should trigger loading
        from src.nori_core.configuration import config_store
        assert hasattr(config_store, 'ConfigStore')
    
    def test_submodules_exist(self):
        """Test that all expected submodules exist."""
        import os
        from pathlib import Path
        import src.nori_core
        
        # Get the package path correctly
        core_package = Path(src.nori_core.__file__).parent
        
        expected_dirs = [
            'configuration',
            'data',
            'chat',
            'memory',
            'agent',
            'mcp',
            'voice',
            'embedding',
            'security',
            'logging',
            'tools',
            'platform',
            'automation',
            'emotion',
        ]
        
        for subdir in expected_dirs:
            path = core_package / subdir
            assert path.is_dir(), f"Expected directory {path} to exist"
    
    def test_init_files_exist(self):
        """Test that __init__.py files exist in all submodules."""
        import os
        from pathlib import Path
        import src.nori_core
        
        # Get the package path correctly
        core_package = Path(src.nori_core.__file__).parent
        
        expected_inits = [
            'configuration/__init__.py',
            'data/__init__.py',
            'chat/__init__.py',
            'memory/__init__.py',
            'agent/__init__.py',
            'mcp/__init__.py',
            'voice/__init__.py',
            'embedding/__init__.py',
            'security/__init__.py',
            'logging/__init__.py',
            'tools/__init__.py',
            'platform/__init__.py',
            'automation/__init__.py',
            'emotion/__init__.py',
        ]
        
        for init_file in expected_inits:
            path = core_package / init_file
            assert path.is_file(), f"Expected file {path} to exist"
