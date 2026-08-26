#!/usr/bin/env python3
"""
Nori Desktop Pet - Application Entry Point

Migrated from C# Nori.Desktop.App with equivalent startup flow:
1. Directory initialization
2. Logging setup
3. Database opening
4. Resource server start
5. Window creation
6. Tray menu installation
7. Runtime start
"""

import sys
import asyncio
import signal
from pathlib import Path
from typing import Optional

import structlog
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QCoreApplication

from .startup.app import Application
from ..nori_core.data.database_manager import DatabaseManager
from ..nori_core.configuration.config_store import ConfigStore

logger = structlog.get_logger()


def setup_signal_handlers():
    """Setup Unix signal handlers for graceful shutdown."""
    def handle_signal(signum, frame):
        logger.info("Received signal", signal=signum)
        QCoreApplication.quit()
    
    # Only on Unix systems
    if sys.platform != "win32":
        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)


def enable_high_dpi():
    """Enable high DPI scaling for modern displays."""
    # Qt6 handles high DPI automatically, but we ensure compatibility
    QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QCoreApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)


async def main_async() -> int:
    """
    Async main entry point.
    
    Returns:
        Exit code
    """
    # Initialize structured logging
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
    )
    
    logger.info("Starting Nori Desktop Pet", version="1.0.0")
    
    # Setup signal handlers
    setup_signal_handlers()
    
    # Enable high DPI
    enable_high_dpi()
    
    # Create Qt application
    app = QApplication(sys.argv)
    app.setApplicationName("Nori Desktop Pet")
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("Nori")
    
    # Set application style
    app.setStyle("Fusion")
    
    try:
        # Create and initialize main application
        nori_app = Application()
        await nori_app.initialize()
        
        # Run event loop
        exit_code = await nori_app.run()
        
        # Cleanup
        await nori_app.shutdown()
        
        return exit_code
        
    except Exception as e:
        logger.exception("Fatal error during startup", error=str(e))
        return 1


def main() -> int:
    """
    Synchronous entry point wrapper.
    
    Returns:
        Exit code
    """
    try:
        # Run async main
        return asyncio.run(main_async())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 0
    except Exception as e:
        logger.exception("Unhandled exception", error=str(e))
        return 1


if __name__ == "__main__":
    sys.exit(main())
