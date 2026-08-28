"""
Agent Protocol - Defines communication protocol between Agent and UI.

High Cohesion: Single responsibility for protocol message types
Low Coupling: No dependencies on external services
Type Safety: Full type hints with dataclass validation
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class AgentRunState(Enum):
    """Agent runtime state machine."""
    IDLE = "idle"
    THINKING = "thinking"
    STREAMING = "streaming"
    TOOL_EXECUTING = "tool_executing"
    WAITING_APPROVAL = "waiting_approval"
    SPEAKING = "speaking"
    ERROR = "error"


@dataclass
class AgentProtocolItem:
    """Base class for all agent protocol items."""
    pass


@dataclass
class ProtocolMessage(AgentProtocolItem):
    """
    Text reply message with emotion, expression, and action linkage.
    
    Attributes:
        text: Message text content
        emotion: Emotion identifier (e.g., "happy", "sad")
        expression: Facial expression ID
        action: Body action/motion ID
    """
    text: str
    emotion: Optional[str] = None
    expression: Optional[str] = None
    action: Optional[str] = None


@dataclass
class ProtocolToolCall(AgentProtocolItem):
    """
    Tool invocation request from the Agent.
    
    Attributes:
        id: Unique tool call identifier
        name: Tool function name
        arguments: Tool call arguments as JSON-compatible dict
    """
    id: str
    name: str
    arguments: Optional[dict[str, Any]] = None


@dataclass
class ProtocolEvent(AgentProtocolItem):
    """
    System and environment event notification.
    
    Attributes:
        name: Event name identifier
        payload: Event-specific data payload
    """
    name: str
    payload: Optional[dict[str, Any]] = None


@dataclass
class ToolApprovalRequest:
    """
    Tool authorization request for UI display.
    
    Attributes:
        request_id: Unique request identifier for UI callback
        tool_name: Name of the tool requesting execution
        arguments: Tool call arguments
        description: Human-readable tool description
        permission_level: Authorization level ("confirm" or "dangerous")
        category: Tool category classification
    """
    request_id: str
    tool_name: str
    arguments: Optional[dict[str, Any]] = None
    description: Optional[str] = None
    permission_level: str = "confirm"
    category: Optional[str] = None
    
    def __post_init__(self):
        """Validate permission level."""
        if self.permission_level not in ("confirm", "dangerous"):
            raise ValueError(
                f"Invalid permission_level: {self.permission_level}. "
                f"Must be 'confirm' or 'dangerous'"
            )
