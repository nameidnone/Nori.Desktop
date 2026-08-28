"""
Nori Core Chat Module - Python 实现

聊天服务核心逻辑，对应 C# ChatService.cs
"""

from __future__ import annotations
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional
import json


@dataclass
class ChatImagePart:
    """聊天消息中的图片部分"""
    bytes_data: bytes
    mime_type: str
    
    MAX_BYTES = 4 * 1024 * 1024  # 4 MiB per image
    SUPPORTED_MIME_TYPES = {"image/png", "image/jpeg", "image/webp"}
    
    def __post_init__(self):
        if not self.bytes_data or len(self.bytes_data) == 0:
            raise ChatException("图片不能为空")
        if len(self.bytes_data) > self.MAX_BYTES:
            raise ChatException("单张图片不能超过 4 MiB")
        
        normalized_mime = self.mime_type.strip().lower()
        if normalized_mime not in self.SUPPORTED_MIME_TYPES:
            raise ChatException("不支持的图片 MIME 类型")
        self.mime_type = normalized_mime


@dataclass
class ChatMessageInput:
    """聊天消息 (输入)"""
    role: str  # "user" or "assistant"
    content: str
    image_parts: list[ChatImagePart] = field(default_factory=list)
    
    MAX_TOTAL_IMAGE_BYTES = 8 * 1024 * 1024  # 8 MiB total
    
    def __post_init__(self):
        if self.role not in ("user", "assistant"):
            raise ChatException("角色必须是 user 或 assistant")
        
        total_bytes = sum(len(img.bytes_data) for img in self.image_parts)
        if total_bytes > self.MAX_TOTAL_IMAGE_BYTES:
            raise ChatException("图片总大小不能超过 8 MiB")
    
    @classmethod
    def validate_image_limits(cls, messages: list["ChatMessageInput"]) -> None:
        """校验一次请求中的图片总大小"""
        total_bytes = sum(
            len(img.bytes_data)
            for msg in messages
            for img in msg.image_parts
        )
        if total_bytes > cls.MAX_TOTAL_IMAGE_BYTES:
            raise ChatException("图片总大小不能超过 8 MiB")


@dataclass
class ChatMessage:
    """聊天消息 (存储/输出)"""
    id: int
    role: str
    content: str
    created_at: str  # RFC3339 format


@dataclass
class LlmUsageInfo:
    """LLM 使用量信息"""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatException(Exception):
    """聊天相关异常，消息直接展示给用户"""
    pass


class ChatService:
    """
    聊天服务
    
    负责：
    - 聊天历史持久化 (SQLite)
    - LLM 适配器调用
    - 动作标记解析
    - 流式/非流式对话
    """
    
    TIMEOUT_SECONDS = 120  # 聊天请求超时
    
    def __init__(self, db_path: str, http_client: Optional[Any] = None):
        self.db_path = db_path
        self.http_client = http_client
        self._init_database()
    
    def _init_database(self) -> None:
        """初始化数据库表"""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            conn.commit()
        finally:
            conn.close()
    
    def get_history(self, limit: int = 0, before_id: int = 0) -> list[ChatMessage]:
        """
        分页读取聊天历史 (返回按时间正序)
        
        Args:
            limit: 返回数量限制，<=0 表示不限制
            before_id: 在此 ID 之前的消息，<=0 表示从最新开始
        """
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            
            sql = "SELECT id, role, content, created_at FROM chat_messages"
            params = []
            
            if before_id > 0:
                sql += " WHERE id < ?"
                params.append(before_id)
            
            sql += " ORDER BY id DESC"
            
            if limit > 0:
                sql += " LIMIT ?"
                params.append(limit)
            
            cursor.execute(sql, params)
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
            
            # 反转为时间正序
            messages.reverse()
            return messages
        finally:
            conn.close()
    
    def get_all_history(self) -> list[ChatMessage]:
        """获取完整聊天历史 (按时间正序)"""
        return self.get_history(limit=0, before_id=0)
    
    async def complete_async(
        self,
        provider: str,
        base_url: str,
        api_key: str,
        model: str,
        messages: list[ChatMessageInput],
        on_motion: Callable[[str], None],
        persist: bool = True,
    ) -> str:
        """
        发起一次对话（非流式）
        
        Returns:
            剥离动作标记后的回复文本
        """
        base_url = base_url.rstrip("/")
        
        if not base_url:
            raise ChatException("Base URL 不能为空")
        if not api_key:
            raise ChatException("API Key 不能为空")
        if not model:
            raise ChatException("模型不能为空")
        if not messages:
            raise ChatException("消息不能为空")
        
        ChatMessageInput.validate_image_limits(messages)
        
        # TODO: 创建 LLM 适配器并调用
        # adapter = LlmClient.create_adapter(provider, self.http_client)
        # raw = await adapter.complete_async(...)
        
        # 模拟响应
        raw = await self._mock_complete(provider, base_url, api_key, model, messages)
        
        # 解析动作标记
        content, motions = self._extract_motion_markers(raw)
        for motion in motions:
            on_motion(motion)
        
        # 持久化
        if persist:
            if messages:
                self._save_message(messages[-1].role, messages[-1].content)
            self._save_message("assistant", content)
        
        return content
    
    async def stream_async(
        self,
        provider: str,
        base_url: str,
        api_key: str,
        model: str,
        messages: list[ChatMessageInput],
        on_chunk: Callable[[str], None],
        on_motion: Callable[[str], None],
        on_usage: Optional[Callable[[LlmUsageInfo], None]] = None,
        persist: bool = True,
    ) -> str:
        """
        发起一次流式对话
        
        Returns:
            剥离动作标记后的完整回复文本
        """
        base_url = base_url.rstrip("/")
        
        if not base_url:
            raise ChatException("Base URL 不能为空")
        if not api_key:
            raise ChatException("API Key 不能为空")
        if not model:
            raise ChatException("模型不能为空")
        if not messages:
            raise ChatException("消息不能为空")
        
        ChatMessageInput.validate_image_limits(messages)
        
        # TODO: 创建 LLM 适配器并调用流式接口
        # adapter = LlmClient.create_adapter(provider, self.http_client)
        # raw = await adapter.stream_async(...)
        
        # 模拟流式响应
        raw = await self._mock_stream(provider, base_url, api_key, model, messages, on_chunk)
        
        # 解析动作标记
        content, motions = self._extract_motion_markers(raw)
        for motion in motions:
            on_motion(motion)
        
        # 持久化
        if persist:
            if messages:
                self._save_message(messages[-1].role, messages[-1].content)
            self._save_message("assistant", content)
        
        return content
    
    def _save_message(self, role: str, content: str) -> ChatMessage:
        """保存一条聊天消息"""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            created_at = datetime.now(timezone.utc).isoformat()
            
            cursor.execute(
                "INSERT INTO chat_messages (role, content, created_at) VALUES (?, ?, ?)",
                (role, content, created_at),
            )
            
            message_id = cursor.lastrowid
            conn.commit()
            
            return ChatMessage(
                id=message_id,
                role=role,
                content=content,
                created_at=created_at,
            )
        finally:
            conn.close()
    
    def clear_history(self) -> None:
        """清空全部聊天历史"""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("DELETE FROM chat_messages")
            conn.commit()
        finally:
            conn.close()
    
    @staticmethod
    def _extract_motion_markers(text: str) -> tuple[str, list[str]]:
        """
        提取并移除动作标记 [motion:name]
        
        Returns:
            (清理后的文本，动作名列表)
        """
        import re
        motions = []
        
        def replace_motion(match):
            motions.append(match.group(1))
            return ""
        
        cleaned = re.sub(r"\[motion:(\w+)\]", replace_motion, text)
        return cleaned.strip(), motions
    
    async def _mock_complete(
        self,
        provider: str,
        base_url: str,
        api_key: str,
        model: str,
        messages: list[ChatMessageInput],
    ) -> str:
        """模拟非流式完成（用于测试）"""
        last_user_msg = next(
            (m.content for m in reversed(messages) if m.role == "user"),
            "你好"
        )
        return f"这是模拟回复：{last_user_msg} [motion:wave]"
    
    async def _mock_stream(
        self,
        provider: str,
        base_url: str,
        api_key: str,
        model: str,
        messages: list[ChatMessageInput],
        on_chunk: Callable[[str], None],
    ) -> str:
        """模拟流式完成（用于测试）"""
        response = "这是模拟流式回复 [motion:wave]"
        for char in response:
            on_chunk(char)
            await asyncio.sleep(0.01)
        return response


# 需要导入 asyncio 用于模拟
import asyncio

__all__ = [
    "ChatImagePart",
    "ChatMessageInput",
    "ChatMessage",
    "LlmUsageInfo",
    "ChatService",
    "ChatException",
]
