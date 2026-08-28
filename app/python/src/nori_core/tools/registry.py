"""
Nori Core Tools Module - Python 实现

工具注册表和内置工具，对应 C# ToolRegistry.cs, BuiltinTools.cs
"""

from __future__ import annotations
import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional
import platform


@dataclass
class RegisteredTool:
    """工具定义与执行体"""
    name: str  # 工具名 (注入 Prompt 与协议调用的标识)
    description: str  # 面向模型的中文描述
    parameters: dict[str, Any]  # 参数 JSON Schema
    permission_level: str  # 权限级别：safe / confirm / dangerous
    category: str = "builtin"  # 分类：builtin / mcp / custom
    enabled: bool = True  # 是否启用
    execute: Optional[Callable[[dict[str, Any], Any], Any]] = None  # 执行体
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "permissionLevel": self.permission_level,
            "category": self.category,
            "enabled": self.enabled,
        }


@dataclass
class ToolResult:
    """工具执行结果"""
    result: Any = None
    error: Optional[str] = None
    
    @property
    def is_success(self) -> bool:
        return self.error is None
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "result": self.result,
            "error": self.error,
            "isSuccess": self.is_success,
        }


class ToolRegistry:
    """
    工具注册表与管理器
    
    负责注册/注销/启停与带权限校验的统一执行入口:
    safe 工具直接运行; confirm/dangerous 工具必须经逐调用授权,
    授权回调缺失、会话取消或用户拒绝时一律 fail-closed 返回可序列化错误。
    """
    
    def __init__(self):
        self._tools: dict[str, RegisteredTool] = {}
        self._disabled: set[str] = set()
        self._lock = asyncio.Lock()
    
    def register(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        permission_level: str,
        execute: Callable[[dict[str, Any], Any], Any],
        category: str = "builtin",
    ) -> None:
        """注册一个工具"""
        tool = RegisteredTool(
            name=name,
            description=description,
            parameters=parameters,
            permission_level=permission_level,
            category=category,
            execute=execute,
            enabled=name not in self._disabled,
        )
        self._tools[name] = tool
    
    def unregister(self, name: str) -> bool:
        """注销工具"""
        if name in self._tools:
            del self._tools[name]
            return True
        return False
    
    def enable(self, name: str) -> bool:
        """启用工具"""
        if name in self._tools:
            self._tools[name].enabled = True
            self._disabled.discard(name)
            return True
        return False
    
    def disable(self, name: str) -> bool:
        """禁用工具"""
        if name in self._tools:
            self._tools[name].enabled = False
            self._disabled.add(name)
            return True
        return False
    
    def get_tool(self, name: str) -> Optional[RegisteredTool]:
        """获取工具定义"""
        return self._tools.get(name)
    
    def get_all_tools(self) -> list[RegisteredTool]:
        """获取所有工具"""
        return list(self._tools.values())
    
    def get_enabled_tools(self) -> list[RegisteredTool]:
        """获取已启用的工具"""
        return [t for t in self._tools.values() if t.enabled]
    
    async def execute(
        self,
        name: str,
        args: dict[str, Any],
        context: Any = None,
        approval_callback: Optional[Callable[[str, dict[str, Any]], bool]] = None,
    ) -> ToolResult:
        """
        执行工具
        
        Args:
            name: 工具名称
            args: 工具参数
            context: 执行上下文
            approval_callback: 审批回调 (用于 confirm/dangerous 级别)
            
        Returns:
            工具执行结果
        """
        tool = self._tools.get(name)
        if not tool:
            return ToolResult(error=f"未知工具：{name}")
        
        if not tool.enabled:
            return ToolResult(error=f"工具已禁用：{name}")
        
        if tool.execute is None:
            return ToolResult(error=f"工具未实现执行逻辑：{name}")
        
        # 权限检查
        if tool.permission_level in ("confirm", "dangerous"):
            if not approval_callback:
                return ToolResult(error=f"工具需要授权：{name}")
            
            try:
                if not approval_callback(name, args):
                    return ToolResult(error=f"用户拒绝了工具调用：{name}")
            except Exception as e:
                return ToolResult(error=f"授权检查失败：{e}")
        
        # 执行工具
        try:
            result = tool.execute(args, context)
            if asyncio.iscoroutine(result):
                result = await result
            return ToolResult(result=result)
        except Exception as e:
            return ToolResult(error=str(e))
    
    def build_prompt_description(self) -> str:
        """构建工具的 Prompt 描述"""
        enabled = self.get_enabled_tools()
        if not enabled:
            return ""
        
        parts = ["## Available Tools"]
        for tool in enabled:
            params_desc = self._format_params(tool.parameters)
            parts.append(f"\n### {tool.name}")
            parts.append(f"**描述**: {tool.description}")
            if params_desc:
                parts.append(f"**参数**: {params_desc}")
            parts.append(f"**权限**: {tool.permission_level}")
        
        return "\n".join(parts)
    
    @staticmethod
    def _format_params(params: dict[str, Any]) -> str:
        """格式化参数描述"""
        if not params:
            return "无参数"
        
        prop_list = []
        properties = params.get("properties", {})
        required = params.get("required", [])
        
        for prop_name, prop_def in properties.items():
            req_mark = "*" if prop_name in required else ""
            desc = prop_def.get("description", "")
            prop_list.append(f"{req_mark}{prop_name}: {desc}")
        
        return ", ".join(prop_list) if prop_list else "无参数"


def register_builtin_tools(registry: ToolRegistry, deps: Optional[Any] = None) -> None:
    """注册全部内置工具"""
    
    # 1. 获取当前时间
    registry.register(
        name="getTime",
        description="获取当前系统的本地时间 (时：分：秒) 与时区信息",
        parameters={"type": "object", "properties": {}, "required": []},
        permission_level="safe",
        execute=lambda args, ctx: {
            "time": datetime.now().strftime("%H:%M:%S"),
            "timezone": datetime.now().astimezone().tzinfo.tzname(datetime.now()),
            "timestamp": int(time.time() * 1000),
        },
    )
    
    # 2. 获取当前日期
    registry.register(
        name="getDate",
        description="获取当前系统的公历日期与星期几",
        parameters={"type": "object", "properties": {}, "required": []},
        permission_level="safe",
        execute=lambda args, ctx: {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "year": datetime.now().year,
            "month": datetime.now().month,
            "day": datetime.now().day,
            "dayOfWeek": ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"][datetime.now().weekday()],
        },
    )
    
    # 3. 获取系统运行环境
    registry.register(
        name="getSystemInfo",
        description="获取宿主计算机的操作系统类型、语言与运行状态",
        parameters={"type": "object", "properties": {}, "required": []},
        permission_level="safe",
        execute=lambda args, ctx: {
            "os": platform.system(),
            "osVersion": platform.version(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "pythonVersion": platform.python_version(),
        },
    )
    
    # 4. 控制 Live2D 播放指定动作
    def play_motion(args: dict[str, Any], ctx: Any) -> dict[str, Any]:
        name = args.get("name", "")
        if not name:
            raise ValueError("缺少参数：name")
        
        if deps and hasattr(deps, 'pet') and deps.pet:
            played = deps.pet.play_motion_by_name(name)
            return {
                "success": played,
                "played": name if played else None,
                "available": None if played else getattr(deps.pet, 'motion_names', []),
            }
        return {"success": False, "error": "桌宠尚未加载"}
    
    registry.register(
        name="playMotion",
        description="让桌宠 Nori 做出指定的 Live2D 动作 (如打招呼、开心、思考等)",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "动作名称 (motion3.json 文件名，如 smile, wave, think)"}
            },
            "required": ["name"],
        },
        permission_level="safe",
        execute=play_motion,
    )
    
    # 5. 控制 Live2D 切换表情
    def set_expression(args: dict[str, Any], ctx: Any) -> dict[str, Any]:
        name = args.get("name", "")
        if not name:
            raise ValueError("缺少参数：name")
        
        if deps and hasattr(deps, 'pet') and deps.pet:
            played = deps.pet.play_expression(name)
            return {
                "success": played,
                "expression": name if played else None,
                "available": None if played else getattr(deps.pet, 'expression_names', []),
            }
        return {"success": False, "error": "桌宠尚未加载"}
    
    registry.register(
        name="setExpression",
        description="改变桌宠 Nori 的脸部表情",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "表情名称 (如 Smile, Shy, Angry, Surprised)"}
            },
            "required": ["name"],
        },
        permission_level="safe",
        execute=set_expression,
    )
    
    # 6. 记住重要事实
    def remember(args: dict[str, Any], ctx: Any) -> dict[str, Any]:
        content = args.get("content", "")
        if not content:
            raise ValueError("缺少参数：content")
        
        if deps and hasattr(deps, 'memory') and deps.memory:
            # TODO: 调用记忆服务
            return {"success": True, "content": content}
        return {"success": False, "error": "记忆服务未初始化"}
    
    registry.register(
        name="remember",
        description="记住一条重要的事实或偏好",
        parameters={
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "要记住的内容"}
            },
            "required": ["content"],
        },
        permission_level="safe",
        execute=remember,
    )
    
    # 别名
    registry.register(
        name="addMemory",
        description="添加一条长期记忆到记忆库 (remember 的别名)",
        parameters={
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "要记住的内容"}
            },
            "required": ["content"],
        },
        permission_level="safe",
        execute=remember,
    )


@dataclass
class BuiltinToolDeps:
    """内置工具依赖注入"""
    pet: Optional[Any] = None  # 桌宠实例
    memory: Optional[Any] = None  # 记忆服务
    emotion: Optional[Any] = None  # 情绪管理器
    proactive: Optional[Any] = None  # 主动交互服务


__all__ = [
    "RegisteredTool",
    "ToolResult",
    "ToolRegistry",
    "register_builtin_tools",
    "BuiltinToolDeps",
]
