"""
Nori Core Agent Module - Python 实现

Agent 系统核心协议和数据结构，对应 C# AgentProtocol.cs
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional
import json


class AgentRunState(Enum):
    """Agent 运行状态"""
    IDLE = "idle"
    THINKING = "thinking"
    STREAMING = "streaming"
    TOOL_EXECUTING = "tool_executing"
    WAITING_APPROVAL = "waiting_approval"
    SPEAKING = "speaking"
    ERROR = "error"


@dataclass
class ProtocolMessage:
    """文本回复消息 (带情绪、表情、动作联动)"""
    text: str
    emotion: Optional[str] = None
    expression: Optional[str] = None
    action: Optional[str] = None
    
    def to_dict(self) -> dict:
        return {
            "type": "message",
            "text": self.text,
            "emotion": self.emotion,
            "expression": self.expression,
            "action": self.action,
        }


@dataclass
class ProtocolToolCall:
    """工具调用请求"""
    id: str
    name: str
    arguments: Optional[dict[str, Any]] = None
    
    def to_dict(self) -> dict:
        return {
            "type": "tool_call",
            "id": self.id,
            "name": self.name,
            "arguments": self.arguments,
        }


@dataclass
class ProtocolEvent:
    """系统与环境事件"""
    name: str
    payload: Optional[dict[str, Any]] = None
    
    def to_dict(self) -> dict:
        return {
            "type": "event",
            "name": self.name,
            "payload": self.payload,
        }


# Union type for protocol items
ProtocolItem = ProtocolMessage | ProtocolToolCall | ProtocolEvent


@dataclass
class ToolApprovalRequest:
    """工具授权请求 (逐次授权 UI 展示用)"""
    request_id: str
    tool_name: str
    arguments: Optional[dict[str, Any]] = None
    description: Optional[str] = None
    permission_level: str = "confirm"  # "confirm" or "dangerous"
    category: Optional[str] = None
    
    def to_dict(self) -> dict:
        return {
            "requestId": self.request_id,
            "toolName": self.tool_name,
            "arguments": self.arguments,
            "description": self.description,
            "permissionLevel": self.permission_level,
            "category": self.category,
        }


@dataclass
class AgentTrace:
    """Agent 执行追踪记录"""
    trace_id: str
    session_id: str
    messages: list[ProtocolItem] = field(default_factory=list)
    tool_calls: list[ProtocolToolCall] = field(default_factory=list)
    state: AgentRunState = AgentRunState.IDLE
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    
    def add_message(self, item: ProtocolItem) -> None:
        self.messages.append(item)
        if isinstance(item, ProtocolToolCall):
            self.tool_calls.append(item)
    
    def to_dict(self) -> dict:
        return {
            "traceId": self.trace_id,
            "sessionId": self.session_id,
            "messages": [m.to_dict() for m in self.messages],
            "toolCalls": [t.to_dict() for t in self.tool_calls],
            "state": self.state.value,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }


__all__ = [
    "AgentRunState",
    "ProtocolMessage",
    "ProtocolToolCall",
    "ProtocolEvent",
    "ProtocolItem",
    "ToolApprovalRequest",
    "AgentTrace",
]
