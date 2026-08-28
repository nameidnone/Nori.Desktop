"""
LLM 协议类型定义

对应 C#: LlmProvider.cs
"""
from __future__ import annotations

from enum import Enum
from typing import Final


class LlmProvider(str, Enum):
    """
    LLM 协议类型
    
    对应 C#: LlmProvider enum
    """
    #: OpenAI Chat Completions 协议 (默认)
    OPENAI = "openai"
    
    #: OpenAI Responses 协议
    OPENAI_RESPONSES = "openai_responses"
    
    #: Anthropic Messages 协议
    ANTHROPIC = "anthropic"
    
    #: Google GenAI (Gemini) 协议
    GOOGLE = "google"
    
    @classmethod
    def parse(cls, value: str | None) -> LlmProvider:
        """
        解析协议类型字符串
        
        对应 C#: LlmProviderExtensions.ParseProvider
        """
        if not value or not value.strip():
            return cls.OPENAI
        
        normalized = value.strip().lower()
        
        if normalized in {"openai_responses", "responses"}:
            return cls.OPENAI_RESPONSES
        elif normalized in {"anthropic", "claude"}:
            return cls.ANTHROPIC
        elif normalized in {"google", "gemini", "google_genai", "googlegenai"}:
            return cls.GOOGLE
        else:
            return cls.OPENAI
    
    def as_string(self) -> str:
        """
        转换为标准配置字符串
        
        对应 C#: LlmProviderExtensions.AsString
        """
        return self.value
    
    def default_base_url(self) -> str:
        """
        获取默认 Base URL
        
        对应 C#: LlmProviderExtensions.DefaultBaseUrl
        """
        _DEFAULT_URLS: Final[dict[LlmProvider, str]] = {
            self.OPENAI: "https://api.openai.com/v1",
            self.OPENAI_RESPONSES: "https://api.openai.com/v1",
            self.ANTHROPIC: "https://api.anthropic.com/v1",
            self.GOOGLE: "https://generativelanguage.googleapis.com/v1beta",
        }
        return _DEFAULT_URLS.get(self, "https://api.openai.com/v1")
    
    @property
    def display_name(self) -> str:
        """获取显示名称"""
        _DISPLAY_NAMES: Final[dict[LlmProvider, str]] = {
            self.OPENAI: "OpenAI",
            self.OPENAI_RESPONSES: "OpenAI Responses",
            self.ANTHROPIC: "Anthropic",
            self.GOOGLE: "Google GenAI",
        }
        return _DISPLAY_NAMES.get(self, "Unknown")


# =============================================================================
# 工具函数
# =============================================================================

def get_all_providers() -> list[LlmProvider]:
    """获取所有支持的协议类型"""
    return list(LlmProvider)


def is_valid_provider(value: str) -> bool:
    """检查是否为有效的协议类型字符串"""
    try:
        LlmProvider.parse(value)
        return True
    except ValueError:
        return False
