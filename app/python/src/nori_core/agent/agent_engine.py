"""
Nori Core - Agent System (Complete Implementation)
===================================================
完整的 AI 代理引擎实现，包含：
1. 协议定义 (Protocol)
2. 推理引擎核心 (Inference Engine)
3. 工具调用解析器 (Tool Call Parser)
4. 状态机管理 (State Machine)
5. 多会话管理 (Session Manager)

支持流式响应、工具调用、上下文管理等高级功能。
"""

import json
import time
import uuid
import asyncio
import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable, Awaitable, Union
from datetime import datetime
from collections import OrderedDict

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nori.agent")

# =============================================================================
# 1. 协议定义层 (Protocol Definitions)
# =============================================================================

class AgentState(Enum):
    """代理状态枚举"""
    IDLE = "idle"               # 空闲
    THINKING = "thinking"       # 思考中
    TOOL_CALLING = "tool_calling"  # 工具调用中
    RESPONDING = "responding"   # 响应中
    ERROR = "error"             # 错误状态

class MessageRole(Enum):
    """消息角色"""
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"

@dataclass
class ToolDefinition:
    """工具定义"""
    name: str
    description: str
    parameters: Dict[str, Any]  # JSON Schema 格式
    handler: Optional[Callable] = None
    
    def to_dict(self) -> Dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters
            }
        }

@dataclass
class ToolCall:
    """工具调用请求"""
    id: str
    name: str
    arguments: Dict[str, Any]
    result: Optional[str] = None
    error: Optional[str] = None

@dataclass
class Message:
    """聊天消息"""
    role: MessageRole
    content: Optional[str]
    tool_calls: Optional[List[ToolCall]] = None
    tool_call_id: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict:
        base = {
            "role": self.role.value,
            "content": self.content,
            "timestamp": self.timestamp.isoformat()
        }
        if self.tool_calls:
            base["tool_calls"] = [
                {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                for tc in self.tool_calls
            ]
        if self.tool_call_id:
            base["tool_call_id"] = self.tool_call_id
        return base

@dataclass
class ChatContext:
    """聊天上下文"""
    session_id: str
    messages: List[Message] = field(default_factory=list)
    system_prompt: Optional[str] = None
    max_tokens: int = 2048
    temperature: float = 0.7
    
    def add_message(self, message: Message):
        self.messages.append(message)
    
    def get_messages_for_api(self) -> List[Dict]:
        """转换为 API 格式"""
        result = []
        if self.system_prompt:
            result.append({
                "role": "system",
                "content": self.system_prompt
            })
        for msg in self.messages[-20:]:  # 保留最近 20 条
            result.append(msg.to_dict())
        return result
    
    def clear(self):
        self.messages.clear()

# =============================================================================
# 2. 流式响应块 (Streaming Chunks)
# =============================================================================

@dataclass
class StreamChunk:
    """流式响应块"""
    type: str  # "text", "tool_call", "done", "error"
    content: Optional[str] = None
    tool_call: Optional[ToolCall] = None
    finish_reason: Optional[str] = None
    
    def to_json(self) -> str:
        data = {"type": self.type}
        if self.content:
            data["content"] = self.content
        if self.tool_call:
            data["tool_call"] = {
                "id": self.tool_call.id,
                "name": self.tool_call.name,
                "arguments": self.tool_call.arguments
            }
        if self.finish_reason:
            data["finish_reason"] = self.finish_reason
        return json.dumps(data, ensure_ascii=False)

# =============================================================================
# 3. 工具调用解析器 (Tool Call Parser)
# =============================================================================

class ToolCallParser:
    """
    解析 LLM 返回的工具调用
    支持多种格式：function calling, JSON mode, 文本解析
    """
    
    @staticmethod
    def parse_from_content(content: str, available_tools: Dict[str, ToolDefinition]) -> List[ToolCall]:
        """从文本内容中解析工具调用"""
        tool_calls = []
        
        # 尝试解析 JSON 格式的工具调用
        try:
            # 查找可能的 JSON 块
            start_idx = content.find('{')
            end_idx = content.rfind('}') + 1
            if start_idx >= 0 and end_idx > start_idx:
                json_str = content[start_idx:end_idx]
                data = json.loads(json_str)
                
                # 处理单个工具调用
                if "name" in data and "arguments" in data:
                    tc = ToolCall(
                        id=str(uuid.uuid4()),
                        name=data["name"],
                        arguments=data["arguments"] if isinstance(data["arguments"], dict) else json.loads(data["arguments"])
                    )
                    if tc.name in available_tools:
                        tool_calls.append(tc)
                
                # 处理多个工具调用
                elif "tool_calls" in data and isinstance(data["tool_calls"], list):
                    for item in data["tool_calls"]:
                        if "name" in item:
                            tc = ToolCall(
                                id=item.get("id", str(uuid.uuid4())),
                                name=item["name"],
                                arguments=item.get("arguments", {})
                            )
                            if tc.name in available_tools:
                                tool_calls.append(tc)
        except (json.JSONDecodeError, KeyError):
            pass
        
        return tool_calls
    
    @staticmethod
    def validate_arguments(tool_call: ToolCall, tool_def: ToolDefinition) -> bool:
        """验证工具调用参数是否符合 JSON Schema"""
        # 简化验证：只检查必需字段
        params_schema = tool_def.parameters
        required = params_schema.get("required", [])
        properties = params_schema.get("properties", {})
        
        for req_field in required:
            if req_field not in tool_call.arguments:
                return False
        
        # 类型检查 (简化版)
        for arg_name, arg_value in tool_call.arguments.items():
            if arg_name in properties:
                expected_type = properties[arg_name].get("type")
                if expected_type == "string" and not isinstance(arg_value, str):
                    return False
                elif expected_type == "number" and not isinstance(arg_value, (int, float)):
                    return False
                elif expected_type == "boolean" and not isinstance(arg_value, bool):
                    return False
                elif expected_type == "array" and not isinstance(arg_value, list):
                    return False
                elif expected_type == "object" and not isinstance(arg_value, dict):
                    return False
        
        return True

# =============================================================================
# 4. 推理引擎核心 (Inference Engine)
# =============================================================================

class InferenceEngine:
    """
    推理引擎核心
    负责与 LLM API 交互，处理流式响应
    """
    
    def __init__(self, api_key: str = "", base_url: str = "https://api.openai.com/v1"):
        self.api_key = api_key
        self.base_url = base_url
        self._client = None
    
    async def chat_completion(
        self,
        context: ChatContext,
        tools: Optional[List[ToolDefinition]] = None,
        stream: bool = True
    ) -> Union[Message, asyncio.StreamReader]:
        """
        执行聊天补全
        返回完整消息或流式读取器
        """
        # 模拟 API 调用 (实际应调用真实 LLM API)
        logger.info(f"Calling LLM with {len(context.messages)} messages")
        
        if stream:
            # 创建模拟流
            return self._create_mock_stream(context, tools)
        else:
            # 同步调用
            return await self._complete_non_streaming(context, tools)
    
    async def _complete_non_streaming(
        self,
        context: ChatContext,
        tools: Optional[List[ToolDefinition]] = None
    ) -> Message:
        """非流式完成"""
        # 模拟延迟
        await asyncio.sleep(0.5)
        
        # 简单规则引擎模拟 LLM 响应
        last_msg = context.messages[-1] if context.messages else None
        content = last_msg.content if last_msg else ""
        
        # 检测是否需要工具调用
        tool_calls = []
        if tools:
            tool_map = {t.name: t for t in tools}
            parsed_calls = ToolCallParser.parse_from_content(content, tool_map)
            
            for tc in parsed_calls:
                if ToolCallParser.validate_arguments(tc, tool_map[tc.name]):
                    tool_calls.append(tc)
        
        if tool_calls:
            return Message(
                role=MessageRole.ASSISTANT,
                content=None,
                tool_calls=tool_calls
            )
        else:
            # 简单回复逻辑
            if "天气" in content:
                response_content = "今天天气晴朗，气温适宜。"
            elif "时间" in content:
                response_content = f"现在是 {datetime.now().strftime('%H:%M:%S')}。"
            else:
                response_content = "我明白了，请继续。"
            
            return Message(
                role=MessageRole.ASSISTANT,
                content=response_content
            )
    
    def _create_mock_stream(
        self,
        context: ChatContext,
        tools: Optional[List[ToolDefinition]] = None
    ) -> asyncio.StreamReader:
        """创建模拟流式响应"""
        stream = asyncio.StreamReader()
        
        last_msg = context.messages[-1] if context.messages else ""
        content = last_msg.content if last_msg else ""
        
        # 后台任务生成流数据
        async def generate():
            # 模拟打字效果
            response_text = "我正在处理您的请求..."
            if "天气" in content:
                response_text = "今天天气晴朗，气温 25 度，适合外出。"
            elif "时间" in content:
                response_text = f"当前时间是{datetime.now().strftime('%H 点%M 分')}。"
            
            for char in response_text:
                chunk = StreamChunk(type="text", content=char)
                stream.feed_data(chunk.to_json().encode() + b"\n")
                await asyncio.sleep(0.05)  # 模拟打字延迟
            
            stream.feed_data(StreamChunk(type="done", finish_reason="stop").to_json().encode() + b"\n")
            stream.feed_eof()
        
        asyncio.create_task(generate())
        return stream

# =============================================================================
# 5. 代理状态机 (Agent State Machine)
# =============================================================================

class AgentStateMachine:
    """
    代理状态机
    管理代理的生命周期和状态转换
    """
    
    def __init__(self):
        self.state = AgentState.IDLE
        self._state_history: List[tuple] = []
        self._lock = asyncio.Lock()
    
    async def transition(self, new_state: AgentState, reason: str = ""):
        """状态转换"""
        async with self._lock:
            old_state = self.state
            self.state = new_state
            self._state_history.append((
                old_state,
                new_state,
                reason,
                datetime.now()
            ))
            logger.debug(f"State: {old_state.value} -> {new_state.value} ({reason})")
    
    def can_transition_to(self, new_state: AgentState) -> bool:
        """检查是否可以转换到目标状态"""
        allowed = {
            AgentState.IDLE: [AgentState.THINKING],
            AgentState.THINKING: [AgentState.TOOL_CALLING, AgentState.RESPONDING, AgentState.ERROR],
            AgentState.TOOL_CALLING: [AgentState.THINKING, AgentState.ERROR],
            AgentState.RESPONDING: [AgentState.IDLE, AgentState.ERROR],
            AgentState.ERROR: [AgentState.IDLE]
        }
        return new_state in allowed.get(self.state, [])
    
    def get_history(self) -> List[Dict]:
        """获取状态历史"""
        return [
            {
                "from": old.value,
                "to": new.value,
                "reason": reason,
                "time": t.isoformat()
            }
            for old, new, reason, t in self._state_history[-20:]
        ]

# =============================================================================
# 6. 代理核心 (Agent Core)
# =============================================================================

class Agent:
    """
    AI 代理核心类
    整合推理引擎、工具系统、状态机
    """
    
    def __init__(
        self,
        agent_id: str,
        name: str,
        system_prompt: str,
        inference_engine: Optional[InferenceEngine] = None
    ):
        self.agent_id = agent_id
        self.name = name
        self.system_prompt = system_prompt
        self.inference_engine = inference_engine or InferenceEngine()
        self.state_machine = AgentStateMachine()
        self.tools: Dict[str, ToolDefinition] = {}
        self.sessions: Dict[str, ChatContext] = {}
        
        # 回调函数
        self.on_thinking_start: Optional[Callable] = None
        self.on_tool_call: Optional[Callable[[ToolCall], Awaitable[str]]] = None
        self.on_response: Optional[Callable[[str], None]] = None
        self.on_error: Optional[Callable[[Exception], None]] = None
    
    def register_tool(self, tool_def: ToolDefinition):
        """注册工具"""
        self.tools[tool_def.name] = tool_def
        logger.info(f"Registered tool: {tool_def.name}")
    
    def create_session(self, session_id: Optional[str] = None) -> ChatContext:
        """创建新会话"""
        sid = session_id or str(uuid.uuid4())
        ctx = ChatContext(
            session_id=sid,
            system_prompt=self.system_prompt
        )
        self.sessions[sid] = ctx
        logger.info(f"Created session: {sid}")
        return ctx
    
    def get_session(self, session_id: str) -> Optional[ChatContext]:
        """获取会话"""
        return self.sessions.get(session_id)
    
    async def chat(
        self,
        user_input: str,
        session_id: str,
        stream: bool = True
    ) -> Union[Message, asyncio.StreamReader]:
        """
        聊天主入口
        处理完整的对话流程
        """
        session = self.get_session(session_id)
        if not session:
            session = self.create_session(session_id)
        
        # 添加用户消息
        user_msg = Message(role=MessageRole.USER, content=user_input)
        session.add_message(user_msg)
        
        try:
            # 状态：思考中
            await self.state_machine.transition(AgentState.THINKING, "Received user input")
            if self.on_thinking_start:
                await self.on_thinking_start()
            
            # 调用 LLM
            tools_list = list(self.tools.values()) if self.tools else None
            response = await self.inference_engine.chat_completion(
                session,
                tools=tools_list,
                stream=stream
            )
            
            # 处理工具调用
            if isinstance(response, Message) and response.tool_calls:
                await self.state_machine.transition(AgentState.TOOL_CALLING, "Tool calls detected")
                
                for tool_call in response.tool_calls:
                    result = await self._execute_tool(tool_call)
                    tool_call.result = result
                    
                    # 添加工具结果到上下文
                    tool_msg = Message(
                        role=MessageRole.TOOL,
                        content=result,
                        tool_call_id=tool_call.id
                    )
                    session.add_message(tool_msg)
                
                # 再次调用 LLM 获取最终回复
                await self.state_machine.transition(AgentState.THINKING, "Tool execution complete")
                response = await self.inference_engine.chat_completion(
                    session,
                    tools=tools_list,
                    stream=stream
                )
            
            # 状态：响应中
            if isinstance(response, Message):
                await self.state_machine.transition(AgentState.RESPONDING, "Generating response")
                session.add_message(response)
                if self.on_response and response.content:
                    self.on_response(response.content)
            
            await self.state_machine.transition(AgentState.IDLE, "Response complete")
            return response
            
        except Exception as e:
            await self.state_machine.transition(AgentState.ERROR, str(e))
            if self.on_error:
                self.on_error(e)
            raise
    
    async def _execute_tool(self, tool_call: ToolCall) -> str:
        """执行工具调用"""
        if tool_call.name not in self.tools:
            return f"Error: Unknown tool '{tool_call.name}'"
        
        tool_def = self.tools[tool_call.name]
        
        if self.on_tool_call:
            try:
                return await self.on_tool_call(tool_call)
            except Exception as e:
                return f"Error executing tool: {str(e)}"
        
        if tool_def.handler:
            try:
                result = tool_def.handler(**tool_call.arguments)
                return json.dumps(result, ensure_ascii=False) if isinstance(result, dict) else str(result)
            except Exception as e:
                return f"Tool execution error: {str(e)}"
        
        return f"Tool '{tool_call.name}' executed with args: {tool_call.arguments}"

# =============================================================================
# 7. 会话管理器 (Session Manager)
# =============================================================================

class SessionManager:
    """
    多会话管理器
    管理多个代理的多个会话
    """
    
    def __init__(self, max_sessions_per_agent: int = 10):
        self.agents: Dict[str, Agent] = {}
        self.max_sessions = max_sessions_per_agent
        self._lru_cache: OrderedDict[str, ChatContext] = OrderedDict()
    
    def register_agent(self, agent: Agent):
        """注册代理"""
        self.agents[agent.agent_id] = agent
        logger.info(f"Registered agent: {agent.name}")
    
    def get_or_create_session(
        self,
        agent_id: str,
        session_id: Optional[str] = None
    ) -> Optional[ChatContext]:
        """获取或创建会话"""
        if agent_id not in self.agents:
            logger.error(f"Agent {agent_id} not found")
            return None
        
        agent = self.agents[agent_id]
        
        # 如果未指定 session_id，创建新的
        if not session_id:
            # 检查会话数量限制
            agent_sessions = [s for s in agent.sessions.values()]
            if len(agent_sessions) >= self.max_sessions:
                # 移除最旧的会话
                oldest = min(agent_sessions, key=lambda s: s.messages[0].timestamp if s.messages else datetime.min)
                del agent.sessions[oldest.session_id]
                if oldest.session_id in self._lru_cache:
                    del self._lru_cache[oldest.session_id]
            
            return agent.create_session()
        
        # 获取现有会话
        session = agent.get_session(session_id)
        if session:
            # 更新 LRU
            if session_id in self._lru_cache:
                self._lru_cache.move_to_end(session_id)
            return session
        
        # 创建新会话
        return agent.create_session(session_id)
    
    def cleanup_inactive_sessions(self, max_age_hours: int = 24):
        """清理不活跃会话"""
        now = datetime.now()
        for agent in self.agents.values():
            to_remove = []
            for sid, session in agent.sessions.items():
                if session.messages:
                    last_activity = session.messages[-1].timestamp
                    age = (now - last_activity).total_seconds() / 3600
                    if age > max_age_hours:
                        to_remove.append(sid)
            
            for sid in to_remove:
                del agent.sessions[sid]
                if sid in self._lru_cache:
                    del self._lru_cache[sid]
                logger.info(f"Cleaned up inactive session: {sid}")

# =============================================================================
# 8. 测试与演示 (Main)
# =============================================================================

async def demo():
    print("=== Nori Agent System Demo ===\n")
    
    # 1. 创建代理
    agent = Agent(
        agent_id="nori-001",
        name="Nori Assistant",
        system_prompt="你是一个有帮助的 AI 助手。"
    )
    
    # 2. 注册工具
    def get_weather(city: str) -> Dict:
        return {"city": city, "temperature": 25, "condition": "sunny"}
    
    weather_tool = ToolDefinition(
        name="get_weather",
        description="获取指定城市的天气信息",
        parameters={
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "城市名称"}
            },
            "required": ["city"]
        },
        handler=get_weather
    )
    agent.register_tool(weather_tool)
    
    # 3. 设置回调
    async def on_thinking():
        print("🤔 Nori is thinking...")
    
    async def on_tool_call(tc: ToolCall) -> str:
        print(f"🔧 Executing tool: {tc.name} with args {tc.arguments}")
        return json.dumps({"result": "success"})
    
    def on_response(text: str):
        print(f"💬 Response: {text}")
    
    agent.on_thinking_start = on_thinking
    agent.on_tool_call = on_tool_call
    agent.on_response = on_response
    
    # 4. 创建会话
    session = agent.create_session("demo-session")
    
    # 5. 测试对话
    print("\n--- Test 1: Simple Chat ---")
    response = await agent.chat("你好，今天天气怎么样？", session.session_id, stream=False)
    if response.content:
        print(f"Assistant: {response.content}")
    
    print("\n--- Test 2: Tool Call Simulation ---")
    # 模拟工具调用场景
    session.add_message(Message(role=MessageRole.USER, content='{"name": "get_weather", "arguments": {"city": "Beijing"}}'))
    response = await agent.chat("查询北京天气", session.session_id, stream=False)
    
    print("\n--- Test 3: Session Management ---")
    manager = SessionManager()
    manager.register_agent(agent)
    
    s1 = manager.get_or_create_session("nori-001")
    s2 = manager.get_or_create_session("nori-001", "custom-session")
    print(f"Sessions created: {s1.session_id}, {s2.session_id}")
    
    print("\n--- Test 4: State History ---")
    history = agent.state_machine.get_history()
    print(f"State transitions: {len(history)}")
    for h in history[-5:]:
        print(f"  {h['from']} -> {h['to']} ({h['reason']})")
    
    print("\n=== Demo Finished ===")

if __name__ == "__main__":
    asyncio.run(demo())
