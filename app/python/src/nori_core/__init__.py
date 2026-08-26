"""
Nori Core - Python 核心业务逻辑

此模块包含所有核心业务逻辑的 Python 实现：
- Agent 系统
- 聊天服务
- 记忆系统
- MCP (Model Context Protocol)
- 语音服务
- 自动化
- 资源配置
- 数据存储
- 嵌入模型
- 情感系统
- 日志系统
- 网络通信
- 平台适配
- 主动交互
- 安全保护
- 技能系统
- 遥测监控
- 工具系统
"""

__version__ = "1.0.0"
__author__ = "Nori Team"

from . import (
    agent,
    chat,
    memory,
    mcp,
    voice,
    automation,
    assets,
    config,
    data,
    embedding,
    emotion,
    live2d,
    logging,
    network,
    platform,
    proactive,
    security,
    skills,
    telemetry,
    tools,
)

__all__ = [
    "agent",
    "chat",
    "memory",
    "mcp",
    "voice",
    "automation",
    "assets",
    "config",
    "data",
    "embedding",
    "emotion",
    "live2d",
    "logging",
    "network",
    "platform",
    "proactive",
    "security",
    "skills",
    "telemetry",
    "tools",
]
