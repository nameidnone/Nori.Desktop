"""
Nori Desktop - Python 桌面应用层

此模块包含 PyQt6 桌面应用的实现：
- 主窗口和托盘
- WebView 集成 (PyQt6-WebEngine)
- OpenGL Live2D 渲染
- 音频后端
- 自动化运行时
- 桥接命令处理
- 启动和关闭管理
- 遥测上报
- 系统托盘菜单
- 窗口管理器
"""

__version__ = "1.0.0"
__author__ = "Nori Team"

from . import (
    audio,
    automation,
    bridge,
    live2d,
    runtime,
    startup,
    telemetry,
    tray,
    windows,
)

__all__ = [
    "audio",
    "automation",
    "bridge",
    "live2d",
    "runtime",
    "startup",
    "telemetry",
    "tray",
    "windows",
]
