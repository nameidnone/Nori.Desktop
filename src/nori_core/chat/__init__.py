"""
聊天模块导出

对应 C#: Nori.Core.Chat 命名空间
"""

from .chat_contracts import (
    ChatException,
    ChatImagePart,
    ChatMessage,
    ChatMessageInput,
    ChatRole,
    LlmUsageInfo,
    MAX_IMAGE_BYTES,
    MAX_TOTAL_IMAGE_BYTES,
    TIMEOUT_SECONDS,
)

from .llm_provider import (
    LlmProvider,
    get_all_providers,
    is_valid_provider,
)

from .llm_adapter import (
    ILlmAdapter,
    IToolCallingLlmAdapter,
    ToolCall,
    ToolCallResult,
)

from .motion_markers import (
    extract,
    build_hint,
    format_motion_marker,
    validate_motion_name,
    MotionGroup,
)

from .chat_service import (
    ChatService,
    ChatServiceConfig,
    get_system_prompt,
)

__all__ = [
    # 数据契约
    "ChatException",
    "ChatImagePart",
    "ChatMessage",
    "ChatMessageInput",
    "ChatRole",
    "LlmUsageInfo",
    "MAX_IMAGE_BYTES",
    "MAX_TOTAL_IMAGE_BYTES",
    "TIMEOUT_SECONDS",
    
    # 协议类型
    "LlmProvider",
    "get_all_providers",
    "is_valid_provider",
    
    # 适配器接口
    "ILlmAdapter",
    "IToolCallingLlmAdapter",
    "ToolCall",
    "ToolCallResult",
    
    # 动作标记
    "extract",
    "build_hint",
    "format_motion_marker",
    "validate_motion_name",
    "MotionGroup",
    
    # 聊天服务
    "ChatService",
    "ChatServiceConfig",
    "get_system_prompt",
]