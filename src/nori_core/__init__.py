"""
Nori Core - Python Core Business Logic Layer

This package contains the core business logic migrated from C# Nori.Core project.
All modules follow high cohesion, low coupling principles with strict type hints.

Architecture:
- High Cohesion: Each module has single responsibility
- Low Coupling: Modules communicate via abstract interfaces
- Dependency Injection: IoC container manages object lifecycles
- Async First: All I/O operations use asyncio
- Type Safe: Complete type hints with mypy strict mode
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from logging import Logger

__version__ = "1.0.0"
__author__ = "Nori Team"

# Core module exports - lazy loading for performance
__all__ = [
    # Configuration & Settings
    "ConfigStore",
    "AiSettingsStore",
    
    # Database & Storage
    "DatabaseManager",
    "MemoryStore",
    
    # Chat & LLM
    "ChatService",
    "LlmClient",
    "LlmProvider",
    
    # Memory & RAG
    "EmbeddingAdapter",
    "RagEngine",
    "KnowledgeService",
    
    # Agent System
    "AgentRuntime",
    "StateMachine",
    "EmotionManager",
    
    # MCP (Model Context Protocol)
    "McpManager",
    "McpClient",
    
    # Voice Services
    "VoiceService",
    "AudioPipeline",
    
    # Tools & Automation
    "ToolRegistry",
    "AutomationRuntime",
    
    # Platform Abstraction
    "PlatformServices",
    
    # Security
    "CryptoManager",
    "SecureStorage",
    
    # Logging & Telemetry
    "StructuredLogger",
]


def __getattr__(name: str):
    """Lazy loading of core modules for faster startup."""
    
    # Configuration modules
    if name == "ConfigStore":
        from .configuration.config_store import ConfigStore
        return ConfigStore
    
    if name == "AiSettingsStore":
        from .configuration.ai_settings import AiSettingsStore
        return AiSettingsStore
    
    # Database modules
    if name == "DatabaseManager":
        from .data.database_manager import DatabaseManager
        return DatabaseManager
    
    if name == "MemoryStore":
        from .memory.memory_store import MemoryStore
        return MemoryStore
    
    # Chat modules
    if name == "ChatService":
        from .chat.chat_service import ChatService
        return ChatService
    
    if name == "LlmClient":
        from .chat.llm_client import LlmClient
        return LlmClient
    
    if name == "LlmProvider":
        from .chat.providers.base import LlmProvider
        return LlmProvider
    
    # Memory modules
    if name == "EmbeddingAdapter":
        from .embedding.base import EmbeddingAdapter
        return EmbeddingAdapter
    
    if name == "RagEngine":
        from .memory.retrieval.rag_engine import RagEngine
        return RagEngine
    
    if name == "KnowledgeService":
        from .memory.knowledge.knowledge_service import KnowledgeService
        return KnowledgeService
    
    # Agent modules
    if name == "AgentRuntime":
        from .agent.runtime import AgentRuntime
        return AgentRuntime
    
    if name == "StateMachine":
        from .agent.state_machine import StateMachine
        return StateMachine
    
    if name == "EmotionManager":
        from .emotion.emotion_manager import EmotionManager
        return EmotionManager
    
    # MCP modules
    if name == "McpManager":
        from .mcp.mcp_manager import McpManager
        return McpManager
    
    if name == "McpClient":
        from .mcp.mcp_client import McpClient
        return McpClient
    
    # Voice modules
    if name == "VoiceService":
        from .voice.voice_service import VoiceService
        return VoiceService
    
    if name == "AudioPipeline":
        from .voice.audio_pipeline import AudioPipeline
        return AudioPipeline
    
    # Tool modules
    if name == "ToolRegistry":
        from .tools.registry import ToolRegistry
        return ToolRegistry
    
    if name == "AutomationRuntime":
        from .automation.runtime import AutomationRuntime
        return AutomationRuntime
    
    # Platform modules
    if name == "PlatformServices":
        from .platform.services import PlatformServices
        return PlatformServices
    
    # Security modules
    if name == "CryptoManager":
        from .security.crypto import CryptoManager
        return CryptoManager
    
    if name == "SecureStorage":
        from .security.secure_storage import SecureStorage
        return SecureStorage
    
    # Logging modules
    if name == "StructuredLogger":
        from .logging.structured_logger import StructuredLogger
        return StructuredLogger
    
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# Initialize logging when module is first imported
import structlog

structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)
