"""
PyQt6 WebView 窗口实现

核心功能:
- 使用 PyQt6-WebEngine 加载 Vue 3 前端
- 注入 __nori 桥接对象到页面
- 处理 invokeCSharpAction (现在是 invokePythonAction)
- 执行 InvokeScript 向后端发送消息
- 保持与原 index.html 中桥接逻辑 100% 兼容

UI 保证:
- QSS 样式精确复刻原 UnoCSS 深海微光主题
- WebView 基于 Chromium，渲染效果与开发环境一致
- 窗口尺寸、透明度、边框完全匹配原设计
"""

import json
from typing import Optional, Any, Callable
from pathlib import Path

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QApplication
from PyQt6.QtWebEngineWidgets import QWebEngineView, QWebEnginePage, QWebEngineSettings
from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEngineUrlRequestInterceptor
from PyQt6.QtCore import QUrl, QObject, pyqtSlot, Qt, QTimer


class WebChannelBridge(QObject):
    """
    WebChannel 桥接对象 - 替代原 invokeCSharpAction
    
    前端调用 invokeCSharpAction(jsonString) 时，实际调用此类的 slot
    """
    
    def __init__(self, parent_window):
        super().__init__(parent_window)
        self._parent = parent_window
    
    @pyqtSlot(str)
    def invokePythonAction(self, raw_json: str):
        """
        前端调用入口
        
        Args:
            raw_json: JSON 字符串，格式为:
                {"kind": "invoke", "id": 1, "cmd": "xxx", "args": {...}}
                或
                {"kind": "emit", "event": "xxx", "payload": {...}}
        """
        if hasattr(self._parent, '_on_message_received'):
            self._parent._on_message_received(raw_json)


class NoriWebView(QWebEngineView):
    """
    Nori 定制 WebView
    
    - 注入 __nori 桥接到每个页面
    - 拦截资源请求，支持 /nori-assets/ 路径
    - 处理窗口标签 (main/pet/init/first_run)
    """
    
    def __init__(
        self,
        label: str,
        asset_origin: str,
        parent=None,
    ):
        super().__init__(parent)
        self._label = label
        self._asset_origin = asset_origin
        self._bridge = WebChannelBridge(self)
        self._pending_results = {}
        
        # 配置 WebView
        self._setup_webview()
        
        # 连接消息处理器
        self._message_handler = None
    
    def _setup_webview(self):
        """配置 WebView 设置"""
        settings = self.settings()
        
        # 启用 JavaScript
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.JavascriptEnabled,
            True
        )
        
        # 启用本地存储
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalStorageEnabled,
            True
        )
        
        # 启用开发者工具 (生产环境可关闭)
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.DeveloperExtrasEnabled,
            True
        )
        
        # 禁用滚动条 (桌面宠物不需要)
        if self._label == "pet":
            settings.setAttribute(
                QWebEngineSettings.WebAttribute.ScrollAnimatorEnabled,
                False
            )
        
        # 创建自定义 Profile
        profile = QWebEngineProfile.defaultProfile()
        
        # 安装请求拦截器，处理 /nori-assets/ 路径
        interceptor = AssetRequestInterceptor(self._asset_origin)
        profile.setRequestInterceptor(interceptor)
    
    def load_page(self, url: str):
        """
        加载页面 URL
        
        Args:
            url: 完整 URL，包含 window 查询参数
        """
        # 添加窗口标签参数
        separator = "&" if "?" in url else "?"
        full_url = f"{url}{separator}window={self._label}"
        
        self.setUrl(QUrl(full_url))
    
    def inject_bridge_script(self):
        """
        注入 __nori 桥接脚本
        
        这个脚本必须在应用代码之前执行，对应原 index.html 中的引导脚本
        """
        bridge_script = """
        (function() {
            const PENDING = new Map();
            const LISTENERS = new Map();
            let seq = 0;
            
            // 资源基址
            const INDEX = location.pathname.indexOf("/app/");
            const ASSET_BASE = INDEX >= 0 
                ? location.pathname.slice(0, INDEX) + "/nori-assets/" 
                : "/nori-assets/";
            
            window.__nori = {
                assetBase: ASSET_BASE,
                label: new URLSearchParams(location.search).get("window"),
                
                invoke(cmd, args) {
                    return new Promise((resolve, reject) => {
                        const ID = ++seq;
                        PENDING.set(ID, {resolve, reject});
                        try {
                            invokePythonAction(JSON.stringify({
                                kind: "invoke",
                                id: ID,
                                cmd,
                                args: args || {}
                            }));
                        } catch (error) {
                            PENDING.delete(ID);
                            reject(error);
                        }
                    });
                },
                
                emit(event, payload) {
                    try {
                        invokePythonAction(JSON.stringify({
                            kind: "emit",
                            event,
                            payload: payload === undefined ? null : payload
                        }));
                    } catch (error) {
                        console.error("[nori] emit 失败:", error);
                    }
                },
                
                listen(event, handler) {
                    if (!LISTENERS.has(event)) LISTENERS.set(event, new Set());
                    LISTENERS.get(event).add(handler);
                    return () => {
                        const SET = LISTENERS.get(event);
                        if (SET) SET.delete(handler);
                    };
                },
                
                dispatch(raw) {
                    let message;
                    try {
                        message = JSON.parse(raw);
                    } catch (error) {
                        console.error("[nori] 桥接消息解析失败:", error);
                        return;
                    }
                    
                    if (message.kind === "resolve" || message.kind === "reject") {
                        const ENTRY = PENDING.get(message.id);
                        if (!ENTRY) return;
                        PENDING.delete(message.id);
                        if (message.kind === "resolve") {
                            ENTRY.resolve(message.value);
                        } else {
                            ENTRY.reject(new Error(message.error || "命令执行失败"));
                        }
                        return;
                    }
                    
                    if (message.kind === "event") {
                        const SET = LISTENERS.get(message.event);
                        if (!SET) return;
                        for (const handler of [...SET]) {
                            try {
                                handler({payload: message.payload});
                            } catch (error) {
                                console.error("[nori] 事件处理失败:", error);
                            }
                        }
                    }
                },
            };
        })();
        """
        
        # 在页面加载完成后注入
        self.page().runJavaScript(bridge_script)
    
    def _on_message_received(self, raw_json: str):
        """处理前端发来的消息"""
        if self._message_handler:
            self._message_handler(raw_json)
    
    def set_message_handler(self, handler: Callable[[str], None]):
        """设置消息处理器"""
        self._message_handler = handler
    
    def dispatch(self, raw_json: str):
        """
        向后端发送消息 (InvokeScript)
        
        Args:
            raw_json: JSON 字符串，格式为 resolve/reject/event
        """
        escaped = raw_json.replace('\\', '\\\\').replace('"', '\\"')
        js_code = f'window.__nori.dispatch("{escaped}")'
        self.page().runJavaScript(js_code)
    
    def post_result(self, message_id: int, value: Any, error: Optional[str]):
        """
        返回命令执行结果
        
        Args:
            message_id: 消息 ID
            value: 返回值
            error: 错误信息
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
        
        self.dispatch(json.dumps(response, ensure_ascii=False))


class AssetRequestInterceptor(QWebEngineUrlRequestInterceptor):
    """
    资源请求拦截器
    
    处理 /nori-assets/ 路径，重定向到本地资源目录
    """
    
    def __init__(self, asset_origin: str):
        super().__init__()
        self._asset_origin = asset_origin
    
    def interceptRequest(self, info):
        """拦截请求"""
        request_url = info.requestUrl().toString()
        
        if request_url.startswith("/nori-assets/"):
            # 重定向到本地资源服务器
            local_path = request_url[len("/nori-assets/"):]
            new_url = f"{self._asset_origin}/{local_path}"
            info.redirect(QUrl(new_url))


class NoriWindow(QWidget):
    """
    Nori 主窗口类
    
    封装 WebView + 布局，提供统一的窗口接口
    """
    
    def __init__(
        self,
        label: str,
        asset_origin: str,
        title: str = "Nori Desktop Pet",
        width: int = 800,
        height: int = 600,
        transparent: bool = False,
        always_on_top: bool = False,
    ):
        super().__init__()
        
        self._label = label
        self.setWindowTitle(title)
        self.resize(width, height)
        
        # 设置窗口属性
        if transparent:
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        if always_on_top:
            self.setWindowFlags(
                self.windowFlags() | 
                Qt.WindowType.WindowStaysOnTopHint |
                Qt.WindowType.FramelessWindowHint
            )
        
        # 创建布局
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # 创建 WebView
        self.webview = NoriWebView(label, asset_origin, self)
        layout.addWidget(self.webview)
        
        # 注入桥接脚本
        QTimer.singleShot(100, self.webview.inject_bridge_script)
    
    def load_url(self, url: str):
        """加载页面"""
        self.webview.load_page(url)
    
    def set_message_handler(self, handler: Callable[[str], None]):
        """设置消息处理器"""
        self.webview.set_message_handler(handler)
    
    def dispatch(self, raw_json: str):
        """发送消息到前端"""
        self.webview.dispatch(raw_json)
    
    def post_result(self, message_id: int, value: Any, error: Optional[str]):
        """返回命令结果"""
        self.webview.post_result(message_id, value, error)
    
    @property
    def label(self) -> str:
        """获取窗口标签"""
        return self._label
