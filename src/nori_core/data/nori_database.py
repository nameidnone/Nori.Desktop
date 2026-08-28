"""
NoriDatabase - 同步 SQLite 数据库管理

对应 C#: Nori.Core.Data.NoriDatabase

提供：
- 单连接线程安全访问（带锁）
- 自动建表和迁移
- 配置默认值初始化
- 数据库结构版本校验
"""
from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path
from typing import Any, Callable, TypeVar

# =============================================================================
# 常量定义
# =============================================================================

#: 当前数据库结构版本
DATABASE_SCHEMA_VERSION: int = 7

#: 迁移备份最大大小 (64 MiB)
MIGRATION_BACKUP_MAX_BYTES: int = 64 * 1024 * 1024

#: 最多保留的迁移前备份数
MIGRATION_BACKUP_COUNT: int = 3

#: 迁移备份标记前缀
MIGRATION_BACKUP_MARKER: str = ".pre-migration-"

#: 建表语句（与 Rust 版 SCHEMA 完全一致）
SCHEMA: str = """
CREATE TABLE IF NOT EXISTS config (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    role       TEXT NOT NULL,
    content    TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    type        TEXT NOT NULL,
    content     TEXT NOT NULL,
    importance  REAL NOT NULL DEFAULT 0.5,
    source      TEXT NOT NULL DEFAULT 'chat',
    tags        TEXT,
    embedding   TEXT,
    embedding_blob BLOB,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(importance DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_chat_messages_created ON chat_messages(created_at, id);
CREATE TABLE IF NOT EXISTS automation_audit (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT NOT NULL,
    task_id     TEXT,
    task_kind   TEXT NOT NULL,
    event_category TEXT NOT NULL,
    outcome     TEXT NOT NULL,
    failure_code TEXT,
    duration_ms INTEGER
);
CREATE INDEX IF NOT EXISTS idx_automation_audit_timestamp ON automation_audit(timestamp DESC, id DESC);
"""

T = TypeVar('T')


class NoriDatabase:
    """
    同步 SQLite 数据库管理类
    
    对应 C#: Nori.Core.Data.NoriDatabase
    
    功能：
    - 打开或创建 nori.db
    - 建表、补默认配置、校验结构版本
    - 用同一把锁保持线程安全（等价于 C# 的 Lock 和 Rust 的 Mutex<Connection>）
    """
    
    def __init__(self, connection: sqlite3.Connection, database_path: str):
        self._connection = connection
        self._database_path = database_path
        self._lock = threading.Lock()
        self._migration_backup_attempted = False
        
        # 启用外键约束
        self._execute("PRAGMA foreign_keys=ON")
        # WAL 模式：写不阻塞读
        self._execute("PRAGMA journal_mode=WAL")
        # NORMAL 在 WAL 下仍保持崩溃一致性
        self._execute("PRAGMA synchronous=NORMAL")
        # 由应用在可控的维护点主动 checkpoint
        self._execute("PRAGMA wal_autocheckpoint=1000")
        # 多线程争用单连接时等锁而不是立刻抛 "database is locked"
        self._execute("PRAGMA busy_timeout=5000")
        
        # 建表
        self._execute(SCHEMA)
        
        # 迁移 schema
        self._migrate_schema()
        
        # 初始化默认配置
        self._ensure_default_config()
    
    @classmethod
    def open(cls, database_path: str | None = None) -> "NoriDatabase":
        """
        打开数据库文件
        
        Args:
            database_path: 数据库路径，传 None 走默认数据目录
        
        Returns:
            NoriDatabase 实例
        
        对应 C#: NoriDatabase.Open
        """
        if database_path is None:
            # 默认数据目录（可根据实际项目结构调整）
            from ..configuration.app_paths import AppPaths
            path = AppPaths.database_path
        else:
            path = database_path
        
        database_existed = os.path.exists(path)
        
        # 确保目录存在
        os.makedirs(os.path.dirname(path), exist_ok=True)
        
        # 创建连接
        connection = sqlite3.connect(
            path,
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
        )
        connection.row_factory = sqlite3.Row
        
        database = cls(connection, path)
        
        # 如果数据库之前不存在，执行初始迁移
        if not database_existed:
            database._run_initial_migration()
        
        return database
    
    def close(self) -> None:
        """关闭数据库连接"""
        try:
            self._connection.close()
        except Exception:
            pass
    
    def locked(self, action: Callable[[sqlite3.Connection], T]) -> T:
        """
        在锁保护下执行数据库操作
        
        Args:
            action: 接受连接并返回结果的可调用对象
        
        Returns:
            action 的返回值
        
        对应 C#: NoriDatabase.Locked<T>(Func<SqliteConnection, T> action)
        """
        with self._lock:
            return action(self._connection)
    
    def locked_void(self, action: Callable[[sqlite3.Connection], None]) -> None:
        """
        在锁保护下执行无返回值的数据库操作
        
        对应 C#: NoriDatabase.Locked(Action<SqliteConnection> action)
        """
        with self._lock:
            action(self._connection)
    
    def _execute(self, sql: str) -> None:
        """
        执行 SQL 语句（无参数）
        
        对应 C#: NoriDatabase.Execute
        """
        self.locked_void(lambda conn: conn.execute(sql))
    
    def execute_scalar(self, sql: str, parameters: tuple = ()) -> Any:
        """
        执行 SQL 并返回标量结果
        
        Args:
            sql: SQL 语句
            parameters: 参数元组
        
        Returns:
            查询结果的第一列第一行
        """
        def query(conn):
            cursor = conn.execute(sql, parameters)
            row = cursor.fetchone()
            return row[0] if row else None
        
        return self.locked(query)
    
    def _migrate_schema(self) -> None:
        """
        迁移数据库结构到最新版本
        
        对应 C#: NoriDatabase.MigrateSchema
        """
        def migrate(conn):
            # 读取或创建用户_version 记录
            cursor = conn.execute(
                "SELECT value FROM config WHERE key = 'user_version'"
            )
            row = cursor.fetchone()
            
            if row is None:
                version = 0
                conn.execute(
                    "INSERT INTO config (key, value) VALUES ('user_version', '0')"
                )
            else:
                version = int(row[0])
            
            # 如果已经是最新版本，无需迁移
            if version >= DATABASE_SCHEMA_VERSION:
                return
            
            # 执行迁移逻辑（根据版本号逐步升级）
            # 这里简化处理，实际需要根据具体版本差异编写迁移代码
            if version < DATABASE_SCHEMA_VERSION:
                # 更新版本号
                conn.execute(
                    "UPDATE config SET value = ? WHERE key = 'user_version'",
                    (str(DATABASE_SCHEMA_VERSION),)
                )
        
        self.locked_void(migrate)
    
    def _ensure_default_config(self) -> None:
        """
        确保默认配置存在
        
        对应 C#: NoriDatabase.EnsureDefaultConfig
        """
        defaults = {
            "ui_theme": "dark",
            "ui_language": "zh-CN",
            "voice_enabled": "true",
            "llm_provider": "openai",
        }
        
        def insert_defaults(conn):
            for key, value in defaults.items():
                conn.execute(
                    "INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)",
                    (key, value)
                )
        
        self.locked_void(insert_defaults)
    
    def _run_initial_migration(self) -> None:
        """
        新数据库的初始迁移
        """
        # 设置初始版本号
        self.locked_void(lambda conn: conn.execute(
            "INSERT OR REPLACE INTO config (key, value) VALUES ('user_version', ?)",
            (str(DATABASE_SCHEMA_VERSION),)
        ))
    
    @property
    def database_path(self) -> str:
        """获取数据库文件路径"""
        return self._database_path
    
    @property
    def schema_version(self) -> int:
        """获取当前数据库结构版本"""
        return self.execute_scalar(
            "SELECT CAST(value AS INTEGER) FROM config WHERE key = 'user_version'"
        ) or 0


# =============================================================================
# 上下文管理器支持
# =============================================================================

class DatabaseContext:
    """数据库上下文管理器（用于 with 语句）"""
    
    def __init__(self, db_path: str | None = None):
        self._db_path = db_path
        self._db: NoriDatabase | None = None
    
    def __enter__(self) -> NoriDatabase:
        self._db = NoriDatabase.open(self._db_path)
        return self._db
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._db:
            self._db.close()
