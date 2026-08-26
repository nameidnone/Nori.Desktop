"""
Nori 应用主类 - PyQt6 实现

完全复刻原 C# App.cs 的启动流程：
1. 目录初始化
2. 日志系统
3. 数据库打开和迁移
4. 遥测配置 (需用户同意)
5. WebView 运行时检测
6. HTTP 客户端创建
7. 资源服务启动
8. MCP 管理器初始化
9. 聊天服务创建
10. 所有服务装配
11. 窗口创建
12. 托盘菜单安装
13. 首次启动判断和窗口调度

UI 保证：使用 PyQt6 + QSS 样式精确还原原 Avalonia UI
"""

import sys
import asyncio
from pathlib import Path
from typing import Optional, Any

from PyQt6.QtWidgets import QApplication, QSplashScreen
from PyQt6.QtCore import Qt, QTranslator, QLocale
from PyQt6.QtGui import QFont, QIcon

from nori_core.data.app_paths import AppPaths
from nori_core.logging.file_logger import FileLogger
from nori_core.telemetry.sentry_telemetry import SentryTelemetry
from nori_desktop.diagnostics.crash_reporter import CrashReporter
from nori_desktop.startup.single_instance_guard import SingleInstanceGuard
from nori_desktop.windows.window_manager import WindowManager
from nori_desktop.bridge.app_services import AppServices
from nori_desktop.tray.tray_menu import TrayMenu
from nori_desktop.runtime.app_runtime import AppRuntime


class NoriApplication:
    """Nori 桌面应用主类"""
    
    def __init__(
        self,
        safe_mode: bool = False,
        smoke_test: Optional[str] = None,
    ):
        self.safe_mode = safe_mode
        self.smoke_test = smoke_test
        self.app: Optional[QApplication] = None
        self.services: Optional[AppServices] = None
        self.logger: Optional[FileLogger] = None
        self.telemetry: Optional[SentryTelemetry] = None
        self._shutdown_started = False
    
    def run(self) -> int:
        """运行应用主循环"""
        try:
            # 创建 Qt 应用实例
            self.app = QApplication(sys.argv)
            self.app.setApplicationName("Nori Desktop Pet")
            self.app.setApplicationVersion("1.0.0")
            self.app.setOrganizationName("Nori Team")
            
            # 设置全局字体 (匹配原 UI)
            font = QFont("Microsoft YaHei UI", 9)
            font.setStyleHint(QFont.StyleHint.SansSerif)
            self.app.setFont(font)
            
            # 启动异步初始化
            asyncio.run(self._start_async())
            
            # 进入 Qt 事件循环
            return self.app.exec()
            
        except Exception as e:
            CrashReporter.report_startup_fatal(
                "应用启动失败",
                str(e)
            )
            return 1
        finally:
            self._cleanup()
    
    async def _start_async(self):
        """异步启动流程"""
        # 1. 确保目录存在
        AppPaths.ensure_created()
        
        # 2. 初始化日志系统
        self.logger = FileLogger()
        self.logger.initialize()
        self.logger.write("backend", "info", "日志系统初始化完成")
        
        # 3. 注册崩溃处理器
        CrashReporter.register(self.app)
        CrashReporter.attach_logger(self.logger)
        
        # 4. 单实例检查
        if not self.smoke_test:
            guard = SingleInstanceGuard.try_acquire(self._activate_main_window)
            if guard is None and sys.platform == "win32" and not self.safe_mode:
                print("Nori 已有一个实例正在运行", file=sys.stderr)
                return
        
        # 5. 初始化遥测 (保持关闭，等待用户同意)
        self.telemetry = SentryTelemetry(
            dsn="https://...@sentry.io/...",  # 实际 DSN
            release="1.0.0",
            environment="production"
        )
        CrashReporter.attach_telemetry(self.telemetry)
        
        # 6. WebView 运行时检测 (PyQt6-WebEngine 基于 Chromium)
        webview_ok = self._check_webview_runtime()
        if not webview_ok:
            CrashReporter.report_startup_fatal(
                "缺少 WebEngine 运行时",
                "请确保 PyQt6-WebEngine 正确安装"
            )
            return
        
        # 7. 打开数据库
        from nori_core.data.nori_database import NoriDatabase
        try:
            database = NoriDatabase.open()
        except Exception as e:
            self.logger.write("backend", "error", f"数据库打开失败：{e}")
            CrashReporter.report_startup_fatal("数据库打开失败", str(e))
            return
        
        # 8. 配置存储
        from nori_core.config.config_store import ConfigStore
        config = ConfigStore(database)
        config.init_defaults("1.0.0")
        config.ensure_schema_version()
        
        # 9. 根据用户同意状态初始化遥测
        consent = config.get_telemetry_consent()
        self.telemetry.configure(enabled=(consent == "granted"))
        
        # 10. 创建 HTTP 客户端
        from nori_core.network.http_clients import NoriHttpClients
        insecure_tls = config.get_string_or("allow_insecure_tls", "").lower() in ("1", "true")
        http_clients = NoriHttpClients.create(
            insecure_tls=insecure_tls,
            timeout_seconds=40  # chat timeout + 10
        )
        
        if insecure_tls:
            self.logger.write("backend", "warn", "已启用 allow_insecure_tls")
        
        # 11. 启动资源服务
        from nori_core.assets.asset_server import AssetServer
        dev_mode = os.environ.get("NORI_DEV") == "1"
        assets = await AssetServer.start_async({
            "app_root": str(AppPaths.wwwroot_dir),
            "resources_root": str(AppPaths.resources_dir),
            "dev_mode": dev_mode,
        })
        
        self.logger.write("backend", "info", f"资源服务已启动：{assets.origin}")
        
        # 12. 创建所有核心服务
        self.services = AppServices(
            database=database,
            config=config,
            logger=self.logger,
            telemetry=self.telemetry,
            http=http_clients.local,
            public_http=http_clients.public,
            assets=assets,
            safe_mode=self.safe_mode,
        )
        
        # 13. 初始化服务组件
        await self.services.initialize()
        
        # 14. 创建窗口管理器
        self.services.windows = WindowManager(assets, self.app)
        
        # 15. 创建桥接命令处理器
        from nori_desktop.bridge.bridge_commands import BridgeCommands
        self.services.commands = BridgeCommands(self.services)
        
        # 16. 创建桥接核心
        from nori_desktop.bridge.nori_bridge import NoriBridge
        bridge = NoriBridge(self.services)
        self.services.bridge = bridge
        
        # 17. 创建所有窗口
        self.services.windows.create_all(bridge, self.services)
        
        # 18. 启动运行时 (Agent/技能/情绪/提醒/语音)
        runtime = AppRuntime(self.services)
        self.services.runtime = runtime
        runtime.start()
        
        # 19. 安装托盘菜单
        runtime.tray_available = TrayMenu.install(self.app, self.services)
        
        # 20. 判断首次启动并显示对应窗口
        first_run = config.is_first_run()
        self.logger.write("backend", "info", "首次启动应用" if first_run else "应用启动完成")
        
        if first_run:
            self.services.windows.show("first_run")
        else:
            self.services.windows.show("init")
        
        # 冒烟测试就绪标记
        if self.smoke_test:
            from nori_desktop.diagnostics.smoke_test import SmokeTestRuntime
            SmokeTestRuntime.write_ready(self.smoke_test, first_run, self.safe_mode)
    
    def _check_webview_runtime(self) -> bool:
        """检查 PyQt6-WebEngine 是否可用"""
        try:
            from PyQt6.QtWebEngineWidgets import QWebEngineView
            return True
        except ImportError:
            return False
    
    def _activate_main_window(self):
        """激活主窗口 (第二个实例请求)"""
        if self.services and self.services.windows:
            self.services.windows.show("main")
    
    def _cleanup(self):
        """清理资源"""
        if self._shutdown_started:
            return
        self._shutdown_started = True
        
        try:
            if self.services:
                asyncio.run(self.services.dispose_async())
        except Exception:
            pass
        
        if self.telemetry:
            try:
                asyncio.run(self.telemetry.flush_async(timeout=1.0))
            except Exception:
                pass
            self.telemetry = None
