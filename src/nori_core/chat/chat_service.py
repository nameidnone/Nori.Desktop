"""
聊天服务核心实现

对应 C#: ChatService.cs

提供完整的聊天历史管理、LLM 对话请求（普通/流式）、动作标记处理等功能。
"""
from __future__ import annotations

import asyncio
import pkgutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ..configuration.config_store import ConfigStore
from ..data.nori_database import NoriDatabase
from .chat_contracts import (
    ChatException,
    ChatImagePart,
    ChatMessage,
    ChatMessageInput,
    LlmUsageInfo,
    TIMEOUT_SECONDS,
)
from .llm_adapter import ILlmAdapter
from .llm_provider import LlmProvider
from .motion_markers import build_hint, extract


# =============================================================================
# 系统提示词加载
# =============================================================================

def _load_system_prompt() -> str:
    """
    从嵌入资源读取系统提示词
    
    对应 C#: ChatService.LoadSystemPrompt
    
    系统提示词以文件形式打包进程序集，修改 nori-system-prompt.md 后需要重新构建才生效。
    """
    try:
        # 尝试从包内资源读取
        data = pkgutil.get_data(__package__, "nori-system-prompt.md")
        if data:
            return data.decode("utf-8")
    except Exception:
        pass
    
    # 回退到文件系统读取（开发模式）
    prompt_path = Path(__file__).parent / "nori-system-prompt.md"
    if prompt_path.exists():
        return prompt_path.read_text(encoding="utf-8")
    
    raise RuntimeError(f"找不到系统提示词文件：{prompt_path}")


# 懒加载系统提示词
_SYSTEM_PROMPT: str | None = None


def get_system_prompt() -> str:
    """获取系统提示词（懒加载）"""
    global _SYSTEM_PROMPT
    if _SYSTEM_PROMPT is None:
        _SYSTEM_PROMPT = _load_system_prompt()
    return _SYSTEM_PROMPT


# =============================================================================
# 聊天服务
# =============================================================================

@dataclass
class ChatServiceConfig:
    """聊天服务配置"""
    llm_provider: str = "openai"
    base_url: str = ""
    api_key: str = ""
    model: str = ""


class ChatService:
    """
    聊天服务
    
    对应 Rust 版 chat.rs 和 C# ChatService.cs
    
    功能：
    - 聊天历史管理（获取、分页、清空）
    - LLM 对话请求（普通/流式）
    - 动作标记解析与广播
    - 消息持久化
    
    系统提示词以嵌入资源形式编译进程序集，
    修改 nori-system-prompt.md 必须重新构建才生效。
    """
    
    def __init__(
        self,
        http_client: Any,  # aiohttp.ClientSession 或类似
        database: NoriDatabase,
        config: ConfigStore,
    ):
        self._http_client = http_client
        self._database = database
        self._config = config
        
        # 延迟导入 AI 设置存储
        from ..configuration.ai_settings_store import AiSettingsStore
        self._ai_settings = AiSettingsStore(config)
        
        # 配置键常量
        self.KEY_LLM_PROVIDER = "llm_provider"  # AiSettingsStore.KeyLlmProvider
    
    # =========================================================================
    # 聊天历史读取
    # =========================================================================
    
    def get_history(self) -> list[ChatMessage]:
        """
        获取完整聊天历史（按时间正序，永不清除）
        
        对应 C#: ChatService.GetHistory()
        """
        def query(conn):
            cursor = conn.execute(
                "SELECT id, role, content, created_at FROM chat_messages ORDER BY id ASC"
            )
            rows = cursor.fetchall()
            return [
                ChatMessage(
                    id=row[0],
                    role=row[1],
                    content=row[2],
                    created_at=row[3],
                )
                for row in rows
            ]
        
        return self._database.locked(query)
    
    def get_history_paginated(self, limit: int, before_id: int = 0) -> list[ChatMessage]:
        """
        分页读取聊天历史（返回按时间正序）
        
        对应 C#: ChatService.GetHistory(int limit, long beforeId)
        
        chat_messages 随使用无限增长，界面加载必须带 limit，否则每次打开都全量拉取。
        before_id <= 0 表示从最新一条开始；limit <= 0 视为不限制（兼容旧的全量读取）。
        """
        def query(conn):
            sql = "SELECT id, role, content, created_at FROM chat_messages"
            params = []
            
            if before_id > 0:
                sql += " WHERE id < ?"
                params.append(before_id)
            
            # 倒序取最新的 limit 条，读完后反转回时间正序
            sql += " ORDER BY id DESC"
            
            if limit > 0:
                sql += " LIMIT ?"
                params.append(limit)
            
            cursor = conn.execute(sql, params)
            rows = cursor.fetchall()
            
            messages = [
                ChatMessage(
                    id=row[0],
                    role=row[1],
                    content=row[2],
                    created_at=row[3],
                )
                for row in rows
            ]
            
            # 反转回时间正序
            messages.reverse()
            return messages
        
        return self._database.locked(query)
    
    # =========================================================================
    # 对话请求
    # =========================================================================
    
    async def complete_async(
        self,
        provider_str: str | None,
        base_url: str,
        api_key: str,
        model: str,
        messages: list[ChatMessageInput],
        on_motion: Callable[[str], None],
        persist: bool = True,
        cancel_token: Any = None,
    ) -> str:
        """
        发起一次对话
        
        对应 C#: ChatService.CompleteAsync
        
        Args:
            provider_str: LLM 协议类型字符串（可选，为空则读配置）
            base_url: API 基础 URL
            api_key: API Key
            model: 模型名称
            messages: 输入消息列表
            on_motion: 动作回调函数
            persist: 是否持久化消息
            cancel_token: 取消令牌（可选）
        
        Returns:
            剥离动作标记后的回复文本
        """
        # 参数验证
        base_url = base_url.rstrip('/')
        if not base_url:
            raise ChatException("Base URL 不能为空")
        if not api_key:
            raise ChatException("API Key 不能为空")
        if not model:
            raise ChatException("模型不能为空")
        if not messages:
            raise ChatException("消息不能为空")
        
        # 验证图片限制
        ChatMessageInput.validate_image_limits_for_messages(messages)
        
        # 若未指定 provider_str，优先读配置
        if not provider_str or not provider_str.strip():
            ai_settings = self._ai_settings.read()
            provider_str = ai_settings.chat.provider.as_string()
        
        # 解析协议并创建适配器
        provider = LlmProvider.parse(provider_str)
        adapter = self._create_adapter(provider)
        
        # 系统提示词 = 人格 + 当前模型动作列表附录
        model_id = self._config.get_string_or("selected_model", "")
        system_content = get_system_prompt() + build_hint(
            lambda key: self._config.get(key), 
            model_id
        )
        
        # 创建超时取消令牌
        timeout_ctx = asyncio.TimeoutError
        
        try:
            async with asyncio.timeout(TIMEOUT_SECONDS):
                raw = await adapter.complete_async(
                    base_url=base_url,
                    api_key=api_key,
                    model=model,
                    system_prompt=system_content,
                    messages=messages,
                    cancel_token=cancel_token,
                )
        except asyncio.TimeoutError:
            raise ChatException(f"请求超时（>{TIMEOUT_SECONDS}秒）")
        
        # 解析动作标记：剥离标记并广播给桌宠窗口播放
        content, motions = extract(raw)
        for motion in motions:
            on_motion(motion)
        
        # 写入历史：仅保存最后一条输入与回复，避免重复落库
        if persist and messages:
            self.save_message(messages[-1].role, messages[-1].content)
            self.save_message("assistant", content)
        
        return content
    
    async def stream_async(
        self,
        provider_str: str | None,
        base_url: str,
        api_key: str,
        model: str,
        messages: list[ChatMessageInput],
        on_chunk: Callable[[str], None],
        on_motion: Callable[[str], None],
        on_usage: Callable[[LlmUsageInfo], None] | None = None,
        persist: bool = True,
        cancel_token: Any = None,
    ) -> str:
        """
        发起一次流式对话
        
        对应 C#: ChatService.StreamAsync
        
        Args:
            provider_str: LLM 协议类型字符串（可选）
            base_url: API 基础 URL
            api_key: API Key
            model: 模型名称
            messages: 输入消息列表
            on_chunk: 文本分片回调
            on_motion: 动作回调函数
            on_usage: Token 用量回调（可选）
            persist: 是否持久化消息
            cancel_token: 取消令牌（可选）
        
        Returns:
            剥离动作标记后的完整回复文本
        """
        # 参数验证
        base_url = base_url.rstrip('/')
        if not base_url:
            raise ChatException("Base URL 不能为空")
        if not api_key:
            raise ChatException("API Key 不能为空")
        if not model:
            raise ChatException("模型不能为空")
        if not messages:
            raise ChatException("消息不能为空")
        
        ChatMessageInput.validate_image_limits_for_messages(messages)
        
        # 若未指定 provider_str，优先读配置
        if not provider_str or not provider_str.strip():
            ai_settings = self._ai_settings.read()
            provider_str = ai_settings.chat.provider.as_string()
        
        provider = LlmProvider.parse(provider_str)
        adapter = self._create_adapter(provider)
        
        model_id = self._config.get_string_or("selected_model", "")
        system_content = get_system_prompt() + build_hint(
            lambda key: self._config.get(key),
            model_id
        )
        
        try:
            async with asyncio.timeout(TIMEOUT_SECONDS):
                raw = await adapter.stream_async(
                    base_url=base_url,
                    api_key=api_key,
                    model=model,
                    system_prompt=system_content,
                    messages=messages,
                    on_chunk=on_chunk,
                    on_usage=on_usage,
                    cancel_token=cancel_token,
                )
        except asyncio.TimeoutError:
            raise ChatException(f"请求超时（>{TIMEOUT_SECONDS}秒）")
        
        # 解析动作标记
        content, motions = extract(raw)
        for motion in motions:
            on_motion(motion)
        
        # 持久化
        if persist and messages:
            self.save_message(messages[-1].role, messages[-1].content)
            self.save_message("assistant", content)
        
        return content
    
    async def complete_async_compat(
        self,
        base_url: str,
        api_key: str,
        model: str,
        messages: list[ChatMessageInput],
        on_motion: Callable[[str], None],
        cancel_token: Any = None,
    ) -> str:
        """
        兼容老接口（从配置或默认协议发起对话）
        
        对应 C#: ChatService.CompleteAsync (重载)
        """
        return await self.complete_async(
            provider_str=None,
            base_url=base_url,
            api_key=api_key,
            model=model,
            messages=messages,
            on_motion=on_motion,
            cancel_token=cancel_token,
        )
    
    # =========================================================================
    # 消息持久化
    # =========================================================================
    
    def save_message(self, role: str, content: str) -> ChatMessage:
        """
        保存一条聊天消息并返回持久化结果
        
        对应 C#: ChatService.SaveMessage
        """
        def insert(conn):
            created_at = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
            cursor = conn.execute(
                "INSERT INTO chat_messages (role, content, created_at) VALUES (?, ?, ?)",
                (role, content, created_at)
            )
            last_id = cursor.lastrowid
            if last_id is None:
                raise RuntimeError("保存聊天消息失败")
            
            return ChatMessage(
                id=last_id,
                role=role,
                content=content,
                created_at=created_at,
            )
        
        return self._database.locked(insert)
    
    def clear_history(self) -> None:
        """
        清空全部聊天历史
        
        对应 C#: ChatService.ClearHistory
        """
        def delete(conn):
            conn.execute("DELETE FROM chat_messages")
        
        self._database.locked(delete)
    
    # =========================================================================
    # 内部方法
    # =========================================================================
    
    def _create_adapter(self, provider: LlmProvider) -> ILlmAdapter:
        """
        根据协议类型创建对应的适配器
        
        对应 C#: LlmClient.CreateAdapter
        """
        # 延迟导入避免循环依赖
        from .adapters.openai_adapter import OpenAiAdapter
        from .adapters.anthropic_adapter import AnthropicAdapter
        from .adapters.google_adapter import GoogleAdapter
        from .adapters.openai_responses_adapter import OpenAiResponsesAdapter
        
        adapters = {
            LlmProvider.OPENAI: OpenAiAdapter(self._http_client),
            LlmProvider.OPENAI_RESPONSES: OpenAiResponsesAdapter(self._http_client),
            LlmProvider.ANTHROPIC: AnthropicAdapter(self._http_client),
            LlmProvider.GOOGLE: GoogleAdapter(self._http_client),
        }
        
        return adapters.get(provider, OpenAiAdapter(self._http_client))


# =============================================================================
# 异常类（已移至 chat_contracts.py，此处保留别名兼容）
# =============================================================================

__all__ = [
    "ChatService",
    "ChatServiceConfig",
    "get_system_prompt",
    "ChatException",
    "ChatMessage",
    "ChatMessageInput",
    "ChatImagePart",
    "LlmUsageInfo",
]
