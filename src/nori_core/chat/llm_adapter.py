"""
LLM 协议适配器接口

对应 C#: ILlmAdapter.cs, IToolCallingLlmAdapter.cs
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, Protocol

from .chat_contracts import (
    ChatMessageInput,
    LlmUsageInfo,
)


class ILlmAdapter(Protocol):
    """
    LLM 协议适配器接口
    
    对应 C#: ILlmAdapter
    """
    
    @abstractmethod
    async def complete_async(
        self,
        base_url: str,
        api_key: str,
        model: str,
        system_prompt: str,
        messages: list[ChatMessageInput],
        cancel_token: object | None = None,  # CancellationToken 模拟
    ) -> str:
        """
        发起单次对话请求并返回原始文本
        
        Args:
            base_url: API 基础 URL
            api_key: API Key
            model: 模型名称
            system_prompt: 系统提示词
            messages: 消息列表
            cancel_token: 取消令牌（可选）
        
        Returns:
            完整回复文本
        """
        pass
    
    @abstractmethod
    async def stream_async(
        self,
        base_url: str,
        api_key: str,
        model: str,
        system_prompt: str,
        messages: list[ChatMessageInput],
        on_chunk: Callable[[str], None],
        on_usage: Callable[[LlmUsageInfo], None] | None = None,
        cancel_token: object | None = None,
    ) -> str:
        """
        发起流式对话请求，逐分片回调产出文本并回调用量指标
        
        Args:
            base_url: API 基础 URL
            api_key: API Key
            model: 模型名称
            system_prompt: 系统提示词
            messages: 消息列表
            on_chunk: 文本分片回调
            on_usage: Token 用量回调（可选）
            cancel_token: 取消令牌（可选）
        
        Returns:
            完整回复文本
        """
        pass
    
    @abstractmethod
    async def fetch_models_async(
        self,
        base_url: str,
        api_key: str,
        cancel_token: object | None = None,
    ) -> list[str]:
        """
        获取支持的模型列表
        
        Args:
            base_url: API 基础 URL
            api_key: API Key
            cancel_token: 取消令牌（可选）
        
        Returns:
            模型名称列表
        """
        pass


class IToolCallingLlmAdapter(ILlmAdapter, Protocol):
    """
    支持工具调用的 LLM 适配器接口
    
    对应 C#: IToolCallingLlmAdapter
    """
    
    @abstractmethod
    async def complete_with_tools_async(
        self,
        base_url: str,
        api_key: str,
        model: str,
        system_prompt: str,
        messages: list[ChatMessageInput],
        tools: list[dict],  # JSON Schema 格式的工具定义
        tool_choice: str | dict | None = None,
        cancel_token: object | None = None,
    ) -> ToolCallResult:
        """
        发起带工具调用的对话请求
        
        Args:
            base_url: API 基础 URL
            api_key: API Key
            model: 模型名称
            system_prompt: 系统提示词
            messages: 消息列表
            tools: 工具定义列表（JSON Schema 格式）
            tool_choice: 工具选择策略（"auto", "none", "required", 或指定工具）
            cancel_token: 取消令牌（可选）
        
        Returns:
            工具调用结果
        """
        pass


class ToolCallResult:
    """
    工具调用结果
    
    封装 LLM 返回的文本回复和工具调用请求
    """
    def __init__(
        self,
        content: str,
        tool_calls: list[ToolCall] | None = None,
        usage: LlmUsageInfo | None = None,
    ):
        self.content = content
        self.tool_calls = tool_calls or []
        self.usage = usage
    
    @property
    def has_tool_calls(self) -> bool:
        """是否有工具调用"""
        return len(self.tool_calls) > 0
    
    def to_dict(self) -> dict:
        """转换为字典格式"""
        return {
            "content": self.content,
            "toolCalls": [tc.to_dict() for tc in self.tool_calls],
            "usage": self.usage.to_dict() if self.usage else None,
        }


class ToolCall:
    """
    工具调用请求
    
    对应 LLM 返回的工具调用结构
    """
    def __init__(
        self,
        id: str,
        name: str,
        arguments: dict,
    ):
        self.id = id
        self.name = name
        self.arguments = arguments
    
    def to_dict(self) -> dict:
        """转换为字典格式"""
        return {
            "id": self.id,
            "name": self.name,
            "arguments": self.arguments,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> ToolCall:
        """从字典创建"""
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            arguments=data.get("arguments", {}),
        )
