"""
应用路径管理

对应 C#: Nori.Core.Data.AppPaths

必须与 Tauri 版的 app_data_dir() 完全一致，否则老用户的 nori.db 与本地模型会"丢失":
- Windows: %APPDATA%/<应用标识>/data
- macOS:   ~/Library/Application Support/<应用标识>/data
- Linux:   $XDG_DATA_HOME/<应用标识>/data (缺省 ~/.local/share/<应用标识>/data)
"""
from __future__ import annotations

import os
import platform
from pathlib import Path
from typing import Optional

# =============================================================================
# 常量定义
# =============================================================================

#: 应用标识，与 tauri.conf.json 的 identifier 保持一致
APP_IDENTIFIER: str = "cn.erhio.noriDesktopPet"

#: 数据库文件名
DATABASE_FILE_NAME: str = "nori.db"

#: 资源根目录名
RESOURCES_DIR_NAME: str = "resources"


# =============================================================================
# 全局状态
# =============================================================================

_diagnostic_profile: Optional[str] = None


# =============================================================================
# 路径计算函数
# =============================================================================

def _app_data_root() -> Path:
    """
    获取平台数据根目录
    
    Returns:
        平台数据根目录路径
    """
    system = platform.system()
    
    if system == "Windows":
        # Windows: %APPDATA%
        appdata = os.environ.get("APPDATA")
        if not appdata:
            raise RuntimeError("APPDATA 环境变量未设置")
        return Path(appdata)
    
    elif system == "Darwin":
        # macOS: ~/Library/Application Support
        home = Path.home()
        return home / "Library" / "Application Support"
    
    else:
        # Linux/Other: $XDG_DATA_HOME or ~/.local/share
        xdg_data = os.environ.get("XDG_DATA_HOME")
        if xdg_data:
            return Path(xdg_data)
        home = Path.home()
        return home / ".local" / "share"


def data_dir() -> Path:
    """
    获取应用数据目录：<平台数据目录>/<应用标识>/data
    
    Returns:
        应用数据目录路径
    
    对应 C#: AppPaths.DataDir
    """
    global _diagnostic_profile
    
    if _diagnostic_profile:
        return Path(_diagnostic_profile) / "data"
    
    return _app_data_root() / APP_IDENTIFIER / "data"


def database_path() -> Path:
    """
    获取 SQLite 数据库文件路径
    
    Returns:
        数据库文件完整路径
    
    对应 C#: AppPaths.DatabasePath
    """
    return data_dir() / DATABASE_FILE_NAME


def resources_dir() -> Path:
    """
    获取资源根目录：<data>/resources
    
    Returns:
        资源目录路径
    
    对应 C#: AppPaths.ResourcesDir
    """
    return data_dir() / RESOURCES_DIR_NAME


def log_dir() -> Path:
    """
    获取日志目录：<data>/log
    
    Returns:
        日志目录路径
    
    对应 C#: AppPaths.LogDir
    """
    return data_dir() / "log"


def knowledge_dir() -> Path:
    """
    获取 ARG 知识库目录：<data>/knowledge
    
    Returns:
        知识库目录路径
    
    对应 C#: AppPaths.KnowledgeDir
    """
    return data_dir() / "knowledge"


def memory_markdown_path() -> Path:
    """
    获取运行时可编辑的 ARG 知识文件路径
    
    Returns:
        Memory.md 文件路径
    
    对应 C#: AppPaths.MemoryMarkdownPath
    """
    return knowledge_dir() / "Memory.md"


# =============================================================================
# 诊断模式
# =============================================================================

def use_diagnostic_profile(profile: str) -> None:
    """
    为隔离的启动冒烟模式设置 profile
    
    普通启动不会调用此方法，真实用户目录因此保持不变。
    
    Args:
        profile: 诊断配置文件路径
    
    Raises:
        ValueError: profile 为空或是文件系统根目录
        RuntimeError: profile 已被设置过
    
    对应 C#: AppPaths.UseDiagnosticProfile
    """
    global _diagnostic_profile
    
    if not profile or not profile.strip():
        raise ValueError("profile 不能为空")
    
    full_path = os.path.abspath(profile)
    path_root = os.path.splitdrive(full_path)[0] or "/"
    
    if full_path == path_root:
        raise ValueError("profile 不能是文件系统根目录")
    
    if _diagnostic_profile is not None and _diagnostic_profile != full_path:
        raise RuntimeError("profile 只能设置一次")
    
    _diagnostic_profile = full_path


def clear_diagnostic_profile() -> None:
    """清除诊断模式（仅用于测试）"""
    global _diagnostic_profile
    _diagnostic_profile = None


def is_diagnostic_mode() -> bool:
    """检查是否处于诊断模式"""
    return _diagnostic_profile is not None


# =============================================================================
# 目录创建
# =============================================================================

def ensure_created() -> None:
    """
    创建数据目录与各子目录（启动时调用，幂等）
    
    对应 C#: AppPaths.EnsureCreated
    """
    dirs = [
        data_dir(),
        resources_dir(),
        log_dir(),
        knowledge_dir(),
    ]
    
    for dir_path in dirs:
        dir_path.mkdir(parents=True, exist_ok=True)


# =============================================================================
# AppPaths 类（兼容接口）
# =============================================================================

class AppPaths:
    """
    应用路径静态类（兼容 C# 风格接口）
    
    提供属性访问方式的路径获取
    """
    
    #: 应用标识
    Identifier: str = APP_IDENTIFIER
    
    #: 数据库文件名
    DatabaseFileName: str = DATABASE_FILE_NAME
    
    #: 资源根目录名
    ResourcesDirName: str = RESOURCES_DIR_NAME
    
    @classmethod
    def data_dir(cls) -> Path:
        """应用数据目录"""
        return data_dir()
    
    @classmethod
    def database_path(cls) -> Path:
        """SQLite 数据库文件路径"""
        return database_path()
    
    @classmethod
    def resources_dir(cls) -> Path:
        """资源根目录"""
        return resources_dir()
    
    @classmethod
    def log_dir(cls) -> Path:
        """日志目录"""
        return log_dir()
    
    @classmethod
    def knowledge_dir(cls) -> Path:
        """ARG 知识库目录"""
        return knowledge_dir()
    
    @classmethod
    def memory_markdown_path(cls) -> Path:
        """运行时可编辑的 ARG 知识文件路径"""
        return memory_markdown_path()
    
    @staticmethod
    def use_diagnostic_profile(profile: str) -> None:
        """设置诊断模式 profile"""
        use_diagnostic_profile(profile)
    
    @staticmethod
    def ensure_created() -> None:
        """创建数据目录"""
        ensure_created()


# 模块级属性别名（方便直接访问）
DataDir = data_dir
DatabasePath = database_path
ResourcesDir = resources_dir
LogDir = log_dir
KnowledgeDir = knowledge_dir
MemoryMarkdownPath = memory_markdown_path
EnsureCreated = ensure_created
