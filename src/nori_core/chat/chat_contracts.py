"""
聊天服务数据契约

对应 C#: ChatService.cs 中的 ChatImagePart, ChatMessageInput, ChatMessage, ChatException
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Final

# =============================================================================
# 常量定义
# =============================================================================

#: 单张图片大小上限 (4 MiB)
MAX_IMAGE_BYTES: Final[int] = 4 * 1024 * 1024

#: 消息图片总大小上限 (8 MiB)
MAX_TOTAL_IMAGE_BYTES: Final[int] = 8 * 1024 * 1024

#: 支持的 MIME 类型集合
SUPPORTED_MIME_TYPES: Final[set[str]] = {"image/png", "image/jpeg", "image/webp"}

#: 聊天请求超时 (秒)
TIMEOUT_SECONDS: Final[int] = 120


# =============================================================================
# 角色枚举
# =============================================================================

class ChatRole(str, Enum):
    """聊天消息角色"""
    USER = "user"
    ASSISTANT = "assistant"
    
    @classmethod
    def is_valid(cls, role: str) -> bool:
        """检查角色是否有效"""
        return role in {cls.USER.value, cls.ASSISTANT.value}


# =============================================================================
# 数据类
# =============================================================================

@dataclass(frozen=True)
class ChatImagePart:
    """
    聊天消息中的图片部分
    
    图片只在请求生命周期内由调用方和适配器持有，不参与聊天历史持久化。
    构造时复制字节，因此调用方之后修改原数组不会影响请求内容。
    """
    bytes_data: bytes
    mime_type: str
    
    def __post_init__(self) -> None:
        """验证图片数据"""
        if not self.bytes_data or len(self.bytes_data) == 0:
            raise ChatException("图片不能为空")
        
        if len(self.bytes_data) > MAX_IMAGE_BYTES:
            raise ChatException(f"单张图片不能超过 {MAX_IMAGE_BYTES // (1024 * 1024)} MiB")
        
        # 规范化 MIME 类型
        normalized_mime = self._normalize_mime_type(self.mime_type)
        object.__setattr__(self, 'mime_type', normalized_mime)
    
    @staticmethod
    def _normalize_mime_type(mime_type: str) -> str:
        """规范化 MIME 类型"""
        if not mime_type or not mime_type.strip():
            raise ChatException("图片 MIME 类型不能为空")
        
        normalized = mime_type.strip().lower()
        if normalized not in SUPPORTED_MIME_TYPES:
            raise ChatException("不支持的图片 MIME 类型")
        
        return normalized
    
    @property
    def size(self) -> int:
        """图片字节大小"""
        return len(self.bytes_data)
    
    def to_base64(self) -> str:
        """转换为 base64 编码字符串（用于 API 传输）"""
        import base64
        return base64.b64encode(self.bytes_data).decode('ascii')
    
    def get_data_uri(self) -> str:
        """获取 Data URI 格式"""
        return f"data:{self.mime_type};base64,{self.to_base64()}"


@dataclass
class ChatMessageInput:
    """
    聊天消息 (输入)
    
    前端格式：{role: "user" | "assistant", content: "..."}
    """
    role: str = ""
    content: str = ""
    image_parts: list[ChatImagePart] = field(default_factory=list)
    
    def __post_init__(self) -> None:
        """验证消息数据"""
        if not ChatRole.is_valid(self.role):
            raise ChatException(f"无效的消息角色：{self.role}")
        
        # 验证图片总大小
        self._validate_image_limits()
    
    def _validate_image_limits(self) -> None:
        """验证图片总大小限制"""
        total_bytes = sum(img.size for img in self.image_parts)
        if total_bytes > MAX_TOTAL_IMAGE_BYTES:
            raise ChatException(f"图片总大小不能超过 {MAX_TOTAL_IMAGE_BYTES // (1024 * 1024)} MiB")
    
    @classmethod
    def validate_image_limits_for_messages(cls, messages: list[ChatMessageInput]) -> None:
        """
        校验一次请求中的图片总大小，防止多条消息绕过总上限
        """
        total_bytes = sum(
            img.size 
            for msg in messages 
            for img in msg.image_parts
        )
        if total_bytes > MAX_TOTAL_IMAGE_BYTES:
            raise ChatException(f"图片总大小不能超过 {MAX_TOTAL_IMAGE_BYTES // (1024 * 1024)} MiB")
    
    @classmethod
    def create_user_message(
        cls, 
        content: str, 
        images: list[bytes] | None = None,
        mime_types: list[str] | None = None
    ) -> ChatMessageInput:
        """创建用户消息"""
        image_parts = []
        if images and mime_types:
            if len(images) != len(mime_types):
                raise ChatException("图片数量和 MIME 类型数量不匹配")
            for img_bytes, mime in zip(images, mime_types):
                image_parts.append(ChatImagePart(bytes_data=img_bytes, mime_type=mime))
        
        return cls(role=ChatRole.USER.value, content=content, image_parts=image_parts)
    
    @classmethod
    def create_assistant_message(cls, content: str) -> ChatMessageInput:
        """创建助手消息"""
        return cls(role=ChatRole.ASSISTANT.value, content=content)


@dataclass
class ChatMessage:
    """
    聊天消息 (存储 / 输出)
    
    前端格式：{id, role, content, createdAt}
    """
    id: int
    role: str
    content: str
    created_at: str  # RFC3339 格式
    
    @classmethod
    def create(cls, role: str, content: str) -> ChatMessage:
        """创建新消息（带当前时间戳）"""
        return cls(
            id=0,  # 待数据库分配
            role=role,
            content=content,
            created_at=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        )
    
    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式"""
        return {
            "id": self.id,
            "role": self.role,
            "content": self.content,
            "createdAt": self.created_at
        }


@dataclass
class LlmUsageInfo:
    """
    LLM 对话 Token 用量与缓存命中统计信息
    
    对应 C#: LlmUsageInfo
    """
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0
    duration_ms: int = 0
    model: str | None = None
    
    @property
    def cache_hit_rate(self) -> float:
        """缓存命中率百分比 (0.0 ~ 100.0)"""
        if self.prompt_tokens == 0:
            return 0.0
        return round((self.cached_tokens / self.prompt_tokens) * 100.0, 1)
    
    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式"""
        return {
            "promptTokens": self.prompt_tokens,
            "completionTokens": self.completion_tokens,
            "totalTokens": self.total_tokens,
            "cachedTokens": self.cached_tokens,
            "cacheHitRate": self.cache_hit_rate,
            "durationMs": self.duration_ms,
            "model": self.model
        }


# =============================================================================
# 异常类
# =============================================================================

class ChatException(Exception):
    """
    聊天相关异常，消息直接展示给用户
    
    对应 C#: ChatException
    """
    def __init__(self, message: str, inner: Exception | None = None):
        super().__init__(message)
        self.inner = inner
    
    def __str__(self) -> str:
        if self.inner:
            return f"{super().__str__()} (内部错误：{self.inner})"
        return super().__str__()


# =============================================================================
# 工具函数
# =============================================================================

def normalize_role(role: str) -> str:
    """规范化角色字符串"""
    role_lower = role.strip().lower()
    if role_lower in {"user", "assistant"}:
        return role_lower
    raise ChatException(f"无效的消息角色：{role}")


def validate_messages(messages: list[ChatMessageInput]) -> None:
    """验证消息列表"""
    if not messages:
        raise ChatException("消息不能为空")
    
    for msg in messages:
        if not msg.content and not msg.image_parts:
            raise ChatException("消息内容或图片不能为空")
    
    ChatMessageInput.validate_image_limits_for_messages(messages)
