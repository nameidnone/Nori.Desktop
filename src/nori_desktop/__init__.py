"""Nori Desktop - PyQt6 GUI Layer"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QApplication

__version__ = "1.0.0"
__author__ = "Nori Team"

__all__ = [
    "Application",
    "MainWindow",
    "WebViewWindow",
    "BridgeCommands",
    "WindowManager",
]


def __getattr__(name: str):
    """Lazy loading for faster startup."""
    
    if name == "Application":
        from .startup.app import Application
        return Application
    
    if name == "MainWindow":
        from .windows.main_window import MainWindow
        return MainWindow
    
    if name == "WebViewWindow":
        from .windows.webview_window import WebViewWindow
        return WebViewWindow
    
    if name == "BridgeCommands":
        from .bridge.commands import BridgeCommands
        return BridgeCommands
    
    if name == "WindowManager":
        from .windows.window_manager import WindowManager
        return WindowManager
    
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
