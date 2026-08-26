"""
Application - Main PyQt6 Application Class

Migrated from C# Nori.Desktop.App with equivalent lifecycle:
- Initialize: Setup Qt application and styles
- OnFrameworkInitializationCompleted: Setup desktop lifetime
- StartAsync: Core startup flow
- ShutdownAsync: Graceful cleanup
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Optional, Any

import structlog
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QObject, pyqtSignal, QThread
from PyQt6.QtGui import QPalette, QColor

from .bridge.nori_bridge import NoriBridge
from .windows.window_manager import WindowManager
from .services.app_services import AppServices
from ..nori_core.data.database_manager import DatabaseManager
from ..nori_core.configuration.config_store import ConfigStore

logger = structlog.get_logger()


class Application(QObject):
    """
    Main application class managing lifecycle and services.
    
    Equivalent to C# Nori.Desktop.App class.
    """
    
    # Signals for async operations
    initialized = pyqtSignal()
    shutdown_requested = pyqtSignal()
    
    def __init__(self):
        """Initialize application."""
        super().__init__()
        
        self._services: Optional[AppServices] = None
        self._bridge: Optional[NoriBridge] = None
        self._window_manager: Optional[WindowManager] = None
        
        self._shutdown_event = asyncio.Event()
        self._is_initialized = False
        self._is_shutting_down = False
    
    async def initialize(self) -> None:
        """
        Initialize application components.
        
        Startup sequence:
        1. Ensure directories
        2. Initialize logging
        3. Open database
        4. Load configuration
        5. Start resource server
        6. Create services
        7. Setup bridge
        8. Create windows
        9. Start runtime
        """
        if self._is_initialized:
            return
        
        logger.info("Initializing application")
        
        try:
            # 1. Ensure application directories
            await self._ensure_directories()
            
            # 2. Database initialization
            db_manager = await self._initialize_database()
            
            # 3. Configuration store
            config_store = ConfigStore(db_manager)
            await config_store.initialize()
            
            # 4. Create core services
            self._services = await self._create_services(db_manager, config_store)
            
            # 5. Create bridge
            self._bridge = NoriBridge(self._services)
            self._services.bridge = self._bridge
            
            # 6. Create window manager
            self._window_manager = WindowManager(self._services)
            self._services.windows = self._window_manager
            
            # 7. Create all windows
            self._window_manager.create_all(self._bridge, self._services)
            
            # 8. Install tray menu (optional on Linux)
            tray_available = await self._install_tray()
            self._services.tray_available = tray_available
            
            # 9. Show appropriate window based on first-run state
            await self._show_initial_window(config_store)
            
            self._is_initialized = True
            self.initialized.emit()
            
            logger.info("Application initialized successfully")
            
        except Exception as e:
            logger.exception("Failed to initialize application", error=str(e))
            raise
    
    async def _ensure_directories(self) -> None:
        """Ensure application directories exist."""
        from .utils.app_paths import AppPaths
        AppPaths.ensure_created()
    
    async def _initialize_database(self) -> DatabaseManager:
        """Initialize SQLite database."""
        from .utils.app_paths import AppPaths
        
        db_path = AppPaths.user_data_dir / "nori.db"
        db_manager = DatabaseManager(db_path)
        await db_manager.initialize()
        
        logger.info("Database initialized", path=str(db_path))
        return db_manager
    
    async def _create_services(
        self,
        db_manager: DatabaseManager,
        config_store: ConfigStore
    ) -> AppServices:
        """Create and configure core services."""
        services = AppServices(
            database=db_manager,
            config=config_store,
        )
        
        # Additional service initialization will be added in Phase 4
        # Including: Chat, Memory, LLM, MCP, Assets, etc.
        
        return services
    
    async def _install_tray(self) -> bool:
        """Install system tray menu."""
        try:
            from .tray.tray_menu import TrayMenu
            return TrayMenu.install(self)
        except Exception as e:
            logger.warning("Failed to install tray menu", error=str(e))
            return False
    
    async def _show_initial_window(self, config: ConfigStore) -> None:
        """Show initial window based on application state."""
        if not self._window_manager:
            raise RuntimeError("Window manager not initialized")
        
        if config.is_first_run():
            logger.info("First run - showing first run wizard")
            self._window_manager.show("first_run")
        else:
            logger.info("Showing initialization window")
            self._window_manager.show("init")
    
    async def run(self) -> int:
        """
        Run application main loop.
        
        Returns:
            Exit code
        """
        if not self._is_initialized:
            await self.initialize()
        
        logger.info("Starting application main loop")
        
        # Wait for shutdown signal
        await self._shutdown_event.wait()
        
        return 0
    
    async def shutdown(self) -> None:
        """Gracefully shutdown application."""
        if self._is_shutting_down:
            return
        
        self._is_shutting_down = True
        logger.info("Shutting down application")
        
        try:
            # Shutdown runtime
            if self._services and self._services.runtime:
                await self._services.runtime.shutdown()
            
            # Dispose services
            if self._services:
                await self._services.dispose()
            
            # Close database
            if self._services and self._services.database:
                await self._services.database.close()
            
            logger.info("Application shutdown complete")
            
        except Exception as e:
            logger.exception("Error during shutdown", error=str(e))
            raise
        finally:
            self._is_shutting_down = False
    
    def request_shutdown(self) -> None:
        """Request application shutdown."""
        logger.info("Shutdown requested")
        self._shutdown_event.set()
    
    @property
    def services(self) -> Optional[AppServices]:
        """Get application services."""
        return self._services
    
    @property
    def bridge(self) -> Optional[NoriBridge]:
        """Get Nori bridge."""
        return self._bridge
    
    @property
    def is_initialized(self) -> bool:
        """Check if application is initialized."""
        return self._is_initialized
    
    @property
    def is_shutting_down(self) -> bool:
        """Check if application is shutting down."""
        return self._is_shutting_down
