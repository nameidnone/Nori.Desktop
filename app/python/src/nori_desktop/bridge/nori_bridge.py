"""
Nori Bridge - 前端 ↔ Python 宿主桥接内核

完全复刻原 C# NoriBridge.cs 的功能：
- 处理页面发来的 invoke 和 emit 消息
- 请求/响应关联管理
- 事件广播到所有窗口
- 错误处理和遥测上报

通信协议保持与原 JSON Envelope 100% 兼容
"""

import json
import asyncio
from typing import Optional, Any, Dict, Set
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor

from PyQt6.QtCore import QObject, pyqtSignal, QMetaObject, Qt


@dataclass
class BridgeMessage:
    """桥接消息数据结构"""
    kind: str  # "invoke" | "emit" | "resolve" | "reject" | "event"
    id: Optional[int] = None
    cmd: Optional[str] = None
    args: Optional[Dict[str, Any]] = None
    event: Optional[str] = None
    payload: Any = None
    value: Any = None
    error: Optional[str] = None


class NoriBridge(QObject):
    """
    前端 ↔ Python 宿主桥接核心
    
    对应原 C# NoriBridge 类
    """
    
    # Qt 信号用于跨线程通信
    message_received = pyqtSignal(str)  # 原始 JSON 消息
    event_to_emit = pyqtSignal(str, object)  # 事件名，负载
    
    def __init__(self, services):
        super().__init__()
        self._services = services
        self._shutdown_cs = asyncio.Event()
        self._pending_invokes: Dict[int, asyncio.Future] = {}
        self._pending_tasks: Set[asyncio.Task] = set()
        self._disposed = False
        self._seq = 0
        
        # 连接信号
        self.message_received.connect(self._handle_message)
        self.event_to_emit.connect(self._broadcast_event)
    
    def handle_message(self, source_window, raw_json: str):
        """
        处理页面发来的一条消息
        
        Args:
            source_window: 发送消息的窗口对象
            raw_json: 原始 JSON 字符串
        """
        if self._disposed:
            return
        
        try:
            message_dict = json.loads(raw_json)
            message = BridgeMessage(**message_dict)
        except json.JSONDecodeError as e:
            self._services.logger.write(
                "backend", "warn", f"桥接消息解析失败：{e}"
            )
            return
        
        if message.kind == "invoke":
            self._track_invoke(source_window, message)
        elif message.kind == "emit":
            # 前端 emit 与 Tauri 一致：全局广播给所有窗口
            if message.event:
                payload = message.payload if message.payload is not None else None
                # 切到 UI 线程广播
                QMetaObject.invokeMethod(
                    self,
                    lambda e=message.event, p=payload: self._services.windows.broadcast(e, p),
                    Qt.ConnectionType.QueuedConnection
                )
        else:
            self._services.logger.write(
                "backend", "warn", f"未知的桥接消息种类：{message.kind}"
            )
    
    def _track_invoke(self, source_window, message: BridgeMessage):
        """跟踪一个 invoke 调用"""
        # WebView 消息回调在 UI 线程，必须切到后台处理
        loop = asyncio.get_event_loop()
        task = loop.create_task(
            self._handle_invoke_observed_async(source_window, message)
        )
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)
    
    async def _handle_invoke_observed_async(self, source_window, message: BridgeMessage):
        """带错误处理的 invoke 处理器"""
        try:
            await self._handle_invoke_async(source_window, message)
        except asyncio.CancelledError:
            pass  # 关闭时忽略取消
        except Exception as e:
            try:
                self._services.telemetry.capture_exception(e, "bridge.invoke")
                from nori_core.security.sensitive_data_redactor import SensitiveDataRedactor
                self._services.logger.write(
                    "backend", "error",
                    f"桥接调用后台任务失败：{SensitiveDataRedactor.exception_summary(e)}"
                )
            except Exception:
                # 关闭时可能已经释放了日志/遥测依赖
                pass
    
    async def _handle_invoke_async(self, source_window, message: BridgeMessage):
        """
        执行一次命令调用并把结果回给页面
        
        对应原 C# HandleInvokeAsync
        """
        cmd = message.cmd or ""
        
        with self._services.telemetry.start_transaction(f"bridge.{cmd}"):
            try:
                # 调用命令处理器
                result = await self._services.commands.invoke_async(
                    source_window,
                    cmd,
                    message.args or {},
                )
                
                # 返回成功结果
                source_window.post_result(message.id, result, None)
                
            except asyncio.CancelledError:
                # 应用退出时不再向已关闭的 WebView 回写结果
                raise
            except Exception as e:
                self._services.telemetry.capture_exception(e, f"bridge.{cmd}")
                from nori_core.security.sensitive_data_redactor import SensitiveDataRedactor
                
                self._services.logger.write(
                    "backend", "error",
                    f"命令执行失败：{cmd}: {SensitiveDataRedactor.exception_summary(e)}"
                )
                
                # 命令错误以可读字符串回给前端，与 Rust 版 Result<T, String> 等价
                source_window.post_result(
                    message.id,
                    None,
                    SensitiveDataRedactor.redact(str(e))
                )
    
    def post_result(self, window, message_id: int, value: Any, error: Optional[str]):
        """
        向后端发送结果 (resolve/reject)
        
        Args:
            window: 目标窗口
            message_id: 消息 ID
            value: 返回值 (成功时)
            error: 错误信息 (失败时)
        """
        if error is not None:
            response = {
                "kind": "reject",
                "id": message_id,
                "error": error
            }
        else:
            response = {
                "kind": "resolve",
                "id": message_id,
                "value": value
            }
        
        window.dispatch(json.dumps(response, ensure_ascii=False))
    
    def _broadcast_event(self, event_name: str, payload: Any):
        """广播事件到所有窗口"""
        try:
            self._services.windows.broadcast(event_name, payload)
        except Exception:
            # 关闭窗口时不能抛出异常
            pass
    
    async def dispose_async(self):
        """异步清理资源"""
        if self._disposed:
            return
        self._disposed = True
        
        self._shutdown_cs.set()
        
        if self._pending_tasks:
            # 等待最多 2 秒让 pending 任务完成
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._pending_tasks, return_exceptions=True),
                    timeout=2.0
                )
            except asyncio.TimeoutError:
                pass
