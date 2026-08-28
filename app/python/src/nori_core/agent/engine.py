"""
Nori Core Agent Module - Python 实现

Agent 引擎核心逻辑，对应 C# AgentEngine.cs
"""

from __future__ import annotations
import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable, Optional

from .protocol import (
    AgentRunState,
    AgentTrace,
    ProtocolEvent,
    ProtocolItem,
    ProtocolMessage,
    ProtocolToolCall,
    ToolApprovalRequest,
)


class AgentException(Exception):
    """Agent 相关异常"""
    pass


class AgentEngine:
    """
    Agent 引擎 - 核心推理与执行循环
    
    负责：
    - 管理 Agent 会话状态
    - 处理流式响应
    - 工具调用协调
    - 情绪/表情/动作提取
    """
    
    def __init__(
        self,
        llm_client: Any,
        tool_registry: Optional[Any] = None,
        require_approval_for_dangerous: bool = True,
    ):
        self.llm_client = llm_client
        self.tool_registry = tool_registry
        self.require_approval_for_dangerous = require_approval_for_dangerous
        self._sessions: dict[str, AgentSession] = {}
    
    def create_session(self, session_id: Optional[str] = None) -> "AgentSession":
        """创建新的 Agent 会话"""
        if session_id is None:
            session_id = str(uuid.uuid4())
        
        session = AgentSession(
            session_id=session_id,
            engine=self,
        )
        self._sessions[session_id] = session
        return session
    
    def get_session(self, session_id: str) -> Optional["AgentSession"]:
        """获取现有会话"""
        return self._sessions.get(session_id)
    
    def remove_session(self, session_id: str) -> bool:
        """移除会话"""
        if session_id in self._sessions:
            del self._sessions[session_id]
            return True
        return False


class AgentSession:
    """
    Agent 会话 - 单次对话的生命周期管理
    
    对应 C# AgentSessionCoordinator
    """
    
    def __init__(self, session_id: str, engine: AgentEngine):
        self.session_id = session_id
        self.engine = engine
        self.trace = AgentTrace(
            trace_id=str(uuid.uuid4()),
            session_id=session_id,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self.state = AgentRunState.IDLE
        self._context_messages: list[dict[str, Any]] = []
        self._pending_tool_calls: dict[str, dict[str, Any]] = {}
    
    @property
    def is_active(self) -> bool:
        """会话是否处于活跃状态"""
        return self.state not in (AgentRunState.IDLE, AgentRunState.ERROR)
    
    def add_user_message(self, content: str, images: Optional[list[Any]] = None) -> None:
        """添加用户消息到上下文"""
        message = {"role": "user", "content": content}
        if images:
            message["images"] = images
        self._context_messages.append(message)
    
    async def run_async(
        self,
        user_input: str,
        on_chunk: Optional[Callable[[str], None]] = None,
        on_motion: Optional[Callable[[str], None]] = None,
        on_emotion: Optional[Callable[[str], None]] = None,
        on_expression: Optional[Callable[[str], None]] = None,
        on_tool_call: Optional[Callable[[ToolApprovalRequest], bool]] = None,
        images: Optional[list[Any]] = None,
    ) -> str:
        """
        运行一次完整的 Agent 推理循环
        
        Args:
            user_input: 用户输入文本
            on_chunk: 流式文本块回调
            on_motion: 动作回调
            on_emotion: 情绪回调
            on_expression: 表情回调
            on_tool_call: 工具调用审批回调 (返回 True 表示批准)
            images: 可选的图片列表
            
        Returns:
            完整的回复文本（剥离动作标记后）
        """
        self.state = AgentRunState.THINKING
        self.trace.updated_at = datetime.now(timezone.utc).isoformat()
        
        # 添加用户消息
        self.add_user_message(user_input, images)
        
        try:
            # 构建完整上下文
            messages = self._build_context()
            
            # 执行流式推理
            full_response = await self._stream_completion(
                messages=messages,
                on_chunk=on_chunk,
                on_motion=on_motion,
                on_emotion=on_emotion,
                on_expression=on_expression,
                on_tool_call=on_tool_call,
            )
            
            # 添加助手回复到上下文
            self._context_messages.append({
                "role": "assistant",
                "content": full_response,
            })
            
            self.state = AgentRunState.IDLE
            self.trace.updated_at = datetime.now(timezone.utc).isoformat()
            
            return full_response
            
        except Exception as e:
            self.state = AgentRunState.ERROR
            self.trace.updated_at = datetime.now(timezone.utc).isoformat()
            raise AgentException(f"Agent 执行失败：{e}") from e
    
    def _build_context(self) -> list[dict[str, Any]]:
        """构建 LLM 上下文消息列表"""
        # TODO: 添加系统提示词
        # TODO: 添加记忆检索结果
        # TODO: 添加工具描述
        return self._context_messages.copy()
    
    async def _stream_completion(
        self,
        messages: list[dict[str, Any]],
        on_chunk: Optional[Callable[[str], None]] = None,
        on_motion: Optional[Callable[[str], None]] = None,
        on_emotion: Optional[Callable[[str], None]] = None,
        on_expression: Optional[Callable[[str], None]] = None,
        on_tool_call: Optional[Callable[[ToolApprovalRequest], bool]] = None,
    ) -> str:
        """流式完成 LLM 调用"""
        self.state = AgentRunState.STREAMING
        
        chunks: list[str] = []
        buffer = ""
        
        # 模拟流式响应（实际应调用 LLM client）
        # TODO: 替换为真实的 LLM 调用
        async for chunk in self._mock_stream(messages):
            chunks.append(chunk)
            buffer += chunk
            
            if on_chunk:
                on_chunk(chunk)
            
            # 检测并提取动作标记 [motion:name]
            while "[motion:" in buffer:
                start = buffer.index("[motion:")
                end = buffer.index("]", start)
                motion_name = buffer[start + 8:end]
                buffer = buffer[:start] + buffer[end + 1:]
                
                if on_motion:
                    on_motion(motion_name)
                
                # 记录到 trace
                self.trace.add_message(ProtocolEvent(
                    name="motion",
                    payload={"motion": motion_name},
                ))
            
            # 检测情绪标记 {emotion:name}
            while "{emotion:" in buffer:
                start = buffer.index("{emotion:")
                end = buffer.index("}", start)
                emotion_name = buffer[start + 9:end]
                buffer = buffer[:start] + buffer[end + 1:]
                
                if on_emotion:
                    on_emotion(emotion_name)
                
                self.trace.add_message(ProtocolEvent(
                    name="emotion",
                    payload={"emotion": emotion_name},
                ))
            
            # 检测表情标记 <expr:name>
            while "<expr:" in buffer:
                start = buffer.index("<expr:")
                end = buffer.index(">", start)
                expr_name = buffer[start + 6:end]
                buffer = buffer[:start] + buffer[end + 1:]
                
                if on_expression:
                    on_expression(expr_name)
                
                self.trace.add_message(ProtocolEvent(
                    name="expression",
                    payload={"expression": expr_name},
                ))
        
        # 清理后的纯文本
        clean_text = buffer.strip()
        
        # 记录最终消息
        self.trace.add_message(ProtocolMessage(
            text=clean_text,
        ))
        
        return clean_text
    
    async def _mock_stream(self, messages: list[dict[str, Any]]) -> AsyncIterator[str]:
        """模拟流式响应（用于测试）"""
        # TODO: 替换为真实 LLM 调用
        response_text = "这是一个模拟回复 [motion:wave] {emotion:happy}"
        for char in response_text:
            yield char
            await asyncio.sleep(0.01)
    
    def get_trace(self) -> AgentTrace:
        """获取当前会话的追踪记录"""
        return self.trace
    
    def clear_history(self) -> None:
        """清空会话历史"""
        self._context_messages.clear()
        self._pending_tool_calls.clear()


__all__ = ["AgentEngine", "AgentSession", "AgentException"]
