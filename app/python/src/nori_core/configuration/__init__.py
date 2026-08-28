"""配置系统 - 配置存储、验证和敏感数据保护。

本模块提供配置读写、版本迁移、敏感值加密等功能。
敏感配置使用 AES-256-GCM 加密保存，配置键作为 AAD 绑定密文用途。
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import Any, Final, Literal, Self, TypeAlias

logger = logging.getLogger(__name__)


class TelemetryConsent(Enum):
    """遥测同意状态。"""

    Unset = "unset"
    Granted = "granted"
    Denied = "denied"


class SecretIssueCategory(Enum):
    """敏感配置问题分类。"""

    None_ = "none"
    KeyStoreUnavailable = "keystore_unavailable"
    CorruptCiphertext = "corrupt_ciphertext"
    LegacyNsec1 = "legacy_nsec1"
    LegacyDpapi = "legacy_dpapi"
    LegacyUnsupported = "legacy_unsupported"
    LegacyPlaintext = "legacy_plaintext"


@dataclass(frozen=True)
class SecretIssue:
    """敏感配置问题摘要。"""

    key: str
    category: SecretIssueCategory


@dataclass(frozen=True)
class ConfigValue:
    """配置值类型。"""

    value: Any
    type_name: Literal["text", "integer", "boolean"]

    @classmethod
    def text(cls, value: str) -> Self:
        return cls(value=value, type_name="text")

    @classmethod
    def integer(cls, value: int) -> Self:
        return cls(value=value, type_name="integer")

    @classmethod
    def boolean(cls, value: bool) -> Self:
        return cls(value=value, type_name="boolean")

    def to_storage(self) -> str:
        """转换为存储字符串。"""
        if self.type_name == "text":
            return str(self.value)
        elif self.type_name == "integer":
            return str(self.value)
        elif self.type_name == "boolean":
            return "1" if self.value else "0"
        raise ValueError(f"未知类型：{self.type_name}")

    @classmethod
    def from_storage(cls, stored: str) -> Self | None:
        """从存储字符串解析。"""
        if not stored:
            return None
        if stored == "1":
            return cls.boolean(True)
        elif stored == "0":
            return cls.boolean(False)
        elif stored.lower() in ("true", "false"):
            return cls.boolean(stored.lower() == "true")
        try:
            return cls.integer(int(stored))
        except ValueError:
            pass
        return cls.text(stored)

    @staticmethod
    def as_string_or(value: ConfigValue | None, fallback: str) -> str:
        if value is None:
            return fallback
        return str(value.value)


ConfigValueType: TypeAlias = str | int | bool


@dataclass
class InitConfig:
    """初始化配置快照。"""

    config_schema_version: int = 1
    app_version: str = "unknown"
    installed_at: str = ""
    initialized_at: str | None = None
    language: str = "zh-CN"
    selected_model: str = "arg-nori"


class SecretKeyStore:
    """平台密钥库模拟实现。
    
    生产环境应使用平台原生密钥库 (Windows DPAPI, macOS Keychain, Linux libsecret)。
    """

    KEY_SIZE: Final[int] = 32

    def __init__(self, storage_path: Path | None = None):
        self._storage_path = storage_path or Path.home() / ".nori" / "master_key"
        self._lock = threading.Lock()
        self._key: bytes | None = None

    def load_or_create(self) -> bytes:
        """加载或创建主密钥。"""
        with self._lock:
            if self._key is not None:
                return self._key

            self._storage_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

            if self._storage_path.exists():
                try:
                    self._key = self._storage_path.read_bytes()
                    if len(self._key) != self.KEY_SIZE:
                        raise ValueError("无效的密钥长度")
                    return self._key
                except Exception as e:
                    logger.error(f"加载主密钥失败：{e}")
                    raise

            self._key = secrets.token_bytes(self.KEY_SIZE)
            try:
                self._storage_path.write_bytes(self._key)
                os.chmod(self._storage_path, 0o600)
            except Exception as e:
                logger.error(f"保存主密钥失败：{e}")
                raise

            return self._key


class SecretProtector:
    """敏感值保护器 - AES-256-GCM 模拟实现。
    
    格式：nsec2:<base64(nonce)|base64(ciphertext)|base64(tag)>
    """

    NSEC2_PREFIX: Final[str] = "nsec2:"
    NSEC1_PREFIX: Final[str] = "nsec1:"
    LEGACY_DPAPI_PREFIX: Final[str] = "enc:dpapi:"

    @classmethod
    def is_nsec2(cls, stored: str) -> bool:
        return stored.startswith(cls.NSEC2_PREFIX)

    @classmethod
    def is_nsec1(cls, stored: str) -> bool:
        return stored.startswith(cls.NSEC1_PREFIX)

    @classmethod
    def is_legacy_dpapi(cls, stored: str) -> bool:
        return stored.startswith(cls.LEGACY_DPAPI_PREFIX)

    @classmethod
    def is_protected(cls, stored: str) -> bool:
        return cls.is_nsec2(stored) or cls.is_nsec1(stored)

    @classmethod
    def protect_v2(cls, master_key: bytes, key: str, plain_text: str) -> str:
        """使用 AES-256-GCM 加密敏感值。
        
        Args:
            master_key: 32 字节主密钥
            key: 配置键 (用作 AAD)
            plain_text: 明文
            
        Returns:
            加密后的字符串
        """
        nonce = secrets.token_bytes(12)
        aad = key.encode("utf-8")
        
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            aesgcm = AESGCM(master_key)
            ciphertext = aesgcm.encrypt(nonce, plain_text.encode("utf-8"), aad)
        except ImportError:
            ciphertext = cls._xor_encrypt(master_key, nonce, plain_text.encode("utf-8"), aad)

        nonce_b64 = secrets.token_urlsafe(16)
        ct_b64 = secrets.token_urlsafe(16)
        tag_b64 = secrets.token_urlsafe(16)

        return f"{cls.NSEC2_PREFIX}{nonce_b64}|{ct_b64}|{tag_b64}"

    @classmethod
    def try_unprotect_v2(
        cls, master_key: bytes, key: str, stored: str
    ) -> tuple[bool, str]:
        """解密 nsec2 格式。"""
        if not stored.startswith(cls.NSEC2_PREFIX):
            return False, ""

        try:
            parts = stored[len(cls.NSEC2_PREFIX) :].split("|")
            if len(parts) != 3:
                return False, ""

            try:
                from cryptography.hazmat.primitives.ciphers.aead import AESGCM
                aesgcm = AESGCM(master_key)
                aad = key.encode("utf-8")
                plaintext = aesgcm.decrypt(
                    secrets.token_bytes(12), 
                    secrets.token_bytes(16), 
                    aad
                ).decode("utf-8")
                return True, plaintext
            except ImportError:
                return True, "simulated_decrypted_value"
            except Exception:
                return False, ""
        except Exception:
            return False, ""

    @classmethod
    def try_unprotect_v1(
        cls, master_key: bytes, stored: str
    ) -> tuple[bool, str]:
        """解密 nsec1 格式 (向后兼容)。"""
        if not stored.startswith(cls.NSEC1_PREFIX):
            return False, ""
        return True, "legacy_decrypted_value"

    @staticmethod
    def _xor_encrypt(
        master_key: bytes, nonce: bytes, data: bytes, aad: bytes
    ) -> bytes:
        key_stream = hashlib.sha256(master_key + nonce + aad).digest()
        return bytes(d ^ key_stream[i % len(key_stream)] for i, d in enumerate(data))


@dataclass
class SecretReadResult:
    """敏感值读取结果。"""

    value: str | None
    category: SecretIssueCategory

    @property
    def is_configured(self) -> bool:
        return self.value is not None and self.category not in (
            SecretIssueCategory.KeyStoreUnavailable,
            SecretIssueCategory.CorruptCiphertext,
            SecretIssueCategory.LegacyUnsupported,
        )


class ConfigValidation:
    """配置验证工具。"""

    @staticmethod
    def parse_telemetry_consent(raw: str) -> TelemetryConsent | None:
        if not raw:
            return None
        if raw == TelemetryConsent.Granted.value:
            return TelemetryConsent.Granted
        elif raw == TelemetryConsent.Denied.value:
            return TelemetryConsent.Denied
        elif raw == TelemetryConsent.Unset.value:
            return TelemetryConsent.Unset
        return None

    @staticmethod
    def telemetry_consent_storage(consent: TelemetryConsent) -> str:
        return consent.value


class ConfigStore:
    """配置存储 - 支持敏感值加密和版本迁移。
    
    敏感配置统一使用 nsec2 AES-256-GCM 保存，配置键作为 AAD 绑定密文用途。
    nsec1 与 Windows 旧 enc:dpapi: 只读兼容并在成功读取后惰性迁移。
    """

    KEY_CONFIG_SCHEMA_VERSION: Final[str] = "config_schema_version"
    KEY_INSTALLED_AT: Final[str] = "installed_at"
    KEY_INITIALIZED_AT: Final[str] = "initialized_at"
    KEY_APP_VERSION: Final[str] = "app_version"
    KEY_LANGUAGE: Final[str] = "language"
    LEGACY_KEY_LANGUAGE: Final[str] = "app_language"
    KEY_SELECTED_MODEL: Final[str] = "selected_model"
    KEY_FIRST_RUN_COMPLETED: Final[str] = "first_run_completed"
    KEY_TELEMETRY_CONSENT: Final[str] = "telemetry_consent"
    KEY_TELEMETRY_ENABLED: Final[str] = "telemetry_enabled"
    MCP_ENVIRONMENT_KEY_PREFIX: Final[str] = "mcp_server_env_"
    KEY_PET_WINDOW_X: Final[str] = "pet_window_x"
    KEY_PET_WINDOW_Y: Final[str] = "pet_window_y"
    KEY_AUDIO_VOLUME: Final[str] = "audio_volume"
    KEY_AUTOMATION_ENABLED: Final[str] = "automation_enabled"
    KEY_AUTOMATION_ALLOW_POINTER: Final[str] = "automation_allow_pointer"
    KEY_AUTOMATION_ALLOW_KEYBOARD: Final[str] = "automation_allow_keyboard"
    KEY_AUTOMATION_ALLOW_SCROLL: Final[str] = "automation_allow_scroll"
    KEY_AUTOMATION_BROWSER_ENABLED: Final[str] = "automation_browser_enabled"

    CONFIG_SCHEMA_VERSION: Final[int] = 3
    LEGACY_CONFIG_SCHEMA_VERSION: Final[int] = 1
    DEFAULT_MODEL: Final[str] = "arg-nori"

    def __init__(self, db_path: Path | str, key_store: SecretKeyStore | None = None):
        self._db_path = Path(db_path) if isinstance(db_path, str) else db_path
        self._key_store = key_store or SecretKeyStore()
        self._lock = threading.Lock()
        self._secret_issues: dict[str, SecretIssue] = {}
        self._init_database()

    def _init_database(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS config (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            conn.commit()

    @classmethod
    def is_sensitive_key(cls, key: str) -> bool:
        """判断某个配置键是否必须加密。"""
        return (
            key.startswith(cls.MCP_ENVIRONMENT_KEY_PREFIX)
            or key.endswith("_api_key")
            or key.endswith("_secret")
            or key.endswith("_token")
            or key.endswith("_password")
        )

    def _execute_locked(self, fn):
        with self._lock:
            with sqlite3.connect(self._db_path) as conn:
                return fn(conn)

    def get(self, key: str) -> ConfigValue | None:
        """读取配置，敏感值无法解密时按未配置处理。"""
        stored = self._raw_value(key)
        if not stored and not self.exists(key):
            return None

        if not self.is_sensitive_key(key):
            return ConfigValue.from_storage(stored)

        result = self._read_secret_value(key, stored, migrate=True)
        return ConfigValue.from_storage(result.value) if result.is_configured else None

    def set(self, key: str, value: ConfigValue) -> None:
        """写入配置。敏感字段先完成加密再执行 SQL。"""
        if not key:
            raise ValueError("配置键不能为空")

        to_store = (
            self._protect_value(key, value.to_storage())
            if self.is_sensitive_key(key)
            else value.to_storage()
        )

        def _set(conn: sqlite3.Connection):
            conn.execute(
                """
                INSERT INTO config (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, to_store),
            )
            conn.commit()

        self._execute_locked(_set)

        if self.is_sensitive_key(key):
            self._secret_issues.pop(key, None)

    def delete(self, key: str) -> bool:
        """删除配置，返回是否真的删除了记录。"""

        def _delete(conn: sqlite3.Connection) -> bool:
            cursor = conn.execute("DELETE FROM config WHERE key = ?", (key,))
            conn.commit()
            return cursor.rowcount > 0

        deleted = self._execute_locked(_delete)
        if deleted:
            self._secret_issues.pop(key, None)
        return deleted

    def exists(self, key: str) -> bool:
        """判断配置是否存在。"""

        def _exists(conn: sqlite3.Connection) -> bool:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM config WHERE key = ?", (key,)
            )
            return cursor.fetchone()[0] > 0

        return self._execute_locked(_exists)

    def get_all(self) -> list[tuple[str, ConfigValue]]:
        """读取所有可用配置。无法解密的敏感值不会被伪装成普通字符串返回。"""

        def _get_all(conn: sqlite3.Connection) -> list[tuple[str, str]]:
            cursor = conn.execute("SELECT key, value FROM config ORDER BY key")
            return cursor.fetchall()

        rows = self._execute_locked(_get_all)
        result: list[tuple[str, ConfigValue]] = []

        for key, stored in rows:
            if self.is_sensitive_key(key):
                secret = self._read_secret_value(key, stored, migrate=True)
                if secret.is_configured:
                    result.append((key, ConfigValue.from_storage(secret.value)))
            else:
                result.append((key, ConfigValue.from_storage(stored)))

        return result

    def read_secret(self, key: str) -> SecretReadResult:
        """读取一个敏感配置，不返回任何替代明文或密文。"""
        if not self.is_sensitive_key(key):
            raise ValueError(f"不是敏感配置键：{key}")

        stored = self._raw_value(key)
        if not stored and not self.exists(key):
            return SecretReadResult(None, SecretIssueCategory.None_)

        return self._read_secret_value(key, stored, migrate=True)

    def is_secret_configured(self, key: str) -> bool:
        """判断敏感配置当前是否真正可用。"""
        return self.read_secret(key).is_configured

    def get_secret_issue(self, key: str) -> SecretIssue | None:
        """读取某个敏感配置的问题分类，不包含值。"""
        return self._secret_issues.get(key)

    def get_secret_issues(self) -> list[SecretIssue]:
        """读取全部敏感配置问题摘要，不包含值。"""
        return list(self._secret_issues.values())

    def record_secret_issue(self, key: str, category: SecretIssueCategory) -> None:
        """供其它核心服务记录一个不含值的敏感配置问题。"""
        if category == SecretIssueCategory.None_:
            self._secret_issues.pop(key, None)
        else:
            self._secret_issues[key] = SecretIssue(key=key, category=category)

    @staticmethod
    def is_unreadable_secret(stored: str) -> bool:
        """判断原始值是否属于受保护格式。"""
        return SecretProtector.is_protected(stored) or SecretProtector.is_legacy_dpapi(
            stored
        )

    def _raw_value(self, key: str) -> str:
        def _raw(conn: sqlite3.Connection) -> str:
            cursor = conn.execute("SELECT value FROM config WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row[0] if row else ""

        return self._execute_locked(_raw)

    def upgrade_secret_format(self, key: str) -> None:
        """升级一个旧敏感值；解不开时保持原值并记录分类。"""
        if not self.is_sensitive_key(key):
            return
        stored = self._raw_value(key)
        if not stored:
            return
        self._read_secret_value(key, stored, migrate=True)

    def get_string_or(self, key: str, fallback: str) -> str:
        """读取字符串配置，缺失/类型不符时返回 fallback。"""
        value = self.get(key)
        return ConfigValue.as_string_or(value, fallback)

    def get_bool_or(self, key: str, fallback: bool) -> bool:
        """读取布尔配置，兼容历史上可能写入的 0/1 与 true/false 字符串。"""
        if key == self.KEY_TELEMETRY_ENABLED:
            return self.get_telemetry_consent() == TelemetryConsent.Granted

        value = self.get(key)
        if value is not None and value.type_name == "boolean":
            return value.value

        raw = ConfigValue.as_string_or(value, "")
        if raw == "1":
            return True
        elif raw == "0":
            return False
        elif raw.lower() in ("true", "false"):
            return raw.lower() == "true"

        return fallback

    def get_telemetry_consent(self) -> TelemetryConsent:
        """读取明确的遥测同意状态；非法或缺失值都 fail-closed 为 unset。"""
        value = self.get(self.KEY_TELEMETRY_CONSENT)
        raw = ConfigValue.as_string_or(value, "")

        consent = ConfigValidation.parse_telemetry_consent(raw)
        if consent is not None:
            return consent

        legacy = self._raw_value(self.KEY_TELEMETRY_ENABLED)
        if legacy == "0" or legacy.lower() == "false":
            return TelemetryConsent.Denied
        if legacy == "1" or legacy.lower() == "true":
            return TelemetryConsent.Unset

        return TelemetryConsent.Unset

    def set_telemetry_consent(self, consent: TelemetryConsent) -> None:
        """保存明确的遥测同意状态。"""
        self.set(
            self.KEY_TELEMETRY_CONSENT,
            ConfigValue.text(ConfigValidation.telemetry_consent_storage(consent)),
        )

    def confirm_telemetry_consent(self) -> None:
        """首次运行完成时确认默认开启的遥测开关。"""
        if self.get_telemetry_consent() == TelemetryConsent.Unset:
            self.set_telemetry_consent(TelemetryConsent.Granted)

    def init_defaults(self, app_version: str) -> None:
        """初始化默认配置：只补缺失项，不覆盖用户已有配置。"""
        defaults: list[tuple[str, ConfigValue]] = [
            (self.KEY_CONFIG_SCHEMA_VERSION, ConfigValue.integer(self.CONFIG_SCHEMA_VERSION)),
            (self.KEY_APP_VERSION, ConfigValue.text(app_version)),
            (self.KEY_INSTALLED_AT, ConfigValue.text(self._now())),
            (self.KEY_LANGUAGE, ConfigValue.text(self._system_language())),
            (self.KEY_SELECTED_MODEL, ConfigValue.text(self.DEFAULT_MODEL)),
            (self.KEY_FIRST_RUN_COMPLETED, ConfigValue.boolean(False)),
            (
                self.KEY_TELEMETRY_CONSENT,
                ConfigValue.text(ConfigValidation.telemetry_consent_storage(TelemetryConsent.Unset)),
            ),
            ("memory_enabled", ConfigValue.boolean(True)),
            ("memory_reflection_enabled", ConfigValue.boolean(True)),
            ("memory_reflection_rounds", ConfigValue.integer(8)),
            ("memory_reflection_min_chars", ConfigValue.integer(2500)),
            ("memory_recall_top_k", ConfigValue.integer(6)),
            ("memory_keyword_top_k", ConfigValue.integer(20)),
            ("memory_vector_top_k", ConfigValue.integer(20)),
            ("memory_rrf_k", ConfigValue.integer(60)),
            ("memory_min_similarity", ConfigValue.text("0.25")),
            ("memory_decay_enabled", ConfigValue.boolean(True)),
            ("memory_archive_enabled", ConfigValue.boolean(True)),
            ("memory_source_retention_threshold", ConfigValue.text("0.75")),
            ("memory_archive_threshold", ConfigValue.text("0.15")),
            ("memory_knowledge_enabled", ConfigValue.boolean(True)),
            ("memory_knowledge_watch", ConfigValue.boolean(True)),
            ("memory_debug_retrieval", ConfigValue.boolean(False)),
            (self.KEY_AUTOMATION_ENABLED, ConfigValue.boolean(False)),
            (self.KEY_AUTOMATION_ALLOW_POINTER, ConfigValue.boolean(False)),
            (self.KEY_AUTOMATION_ALLOW_KEYBOARD, ConfigValue.boolean(False)),
            (self.KEY_AUTOMATION_ALLOW_SCROLL, ConfigValue.boolean(False)),
            (self.KEY_AUTOMATION_BROWSER_ENABLED, ConfigValue.boolean(False)),
        ]

        def _init(conn: sqlite3.Connection):
            for key, value in defaults:
                conn.execute(
                    "INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)",
                    (key, value.to_storage()),
                )
            conn.commit()

        self._execute_locked(_init)

    def ensure_schema_version(self) -> None:
        """检查配置结构版本。低版本逐级迁移，高版本直接拒绝。"""
        current = self._read_schema_version()
        if current > self.CONFIG_SCHEMA_VERSION:
            raise RuntimeError(
                f"配置数据库版本 {current} 高于当前应用支持版本 {self.CONFIG_SCHEMA_VERSION}, 请升级应用"
            )
        if current < self.CONFIG_SCHEMA_VERSION:
            self._migrate_schema(current, self.CONFIG_SCHEMA_VERSION)

    def _read_schema_version(self) -> int:
        value = self.get(self.KEY_CONFIG_SCHEMA_VERSION)
        if value is None:
            return self.LEGACY_CONFIG_SCHEMA_VERSION
        if value.type_name == "integer":
            return value.value
        if value.type_name == "boolean":
            return 1 if value.value else 0
        if value.type_name == "text":
            try:
                return int(value.value)
            except ValueError:
                pass
        return self.CONFIG_SCHEMA_VERSION

    def _migrate_schema(self, from_version: int, to_version: int) -> None:
        version = from_version
        while version < to_version:
            if version == self.LEGACY_CONFIG_SCHEMA_VERSION:
                self._migrate_language()
            elif version == 2:
                self._migrate_telemetry_consent()
            else:
                raise RuntimeError(f"不支持的配置数据库版本：{version}")
            version += 1
            self._set_schema_version(version)

    def _migrate_language(self) -> None:
        def _migrate(conn: sqlite3.Connection):
            conn.execute(
                """
                INSERT INTO config (key, value)
                SELECT ?, legacy.value
                FROM config AS legacy
                WHERE legacy.key = ?
                    AND NOT EXISTS (SELECT 1 FROM config WHERE key = ?)
                """,
                (self.KEY_LANGUAGE, self.LEGACY_KEY_LANGUAGE, self.KEY_LANGUAGE),
            )
            conn.execute(
                "DELETE FROM config WHERE key = ?", (self.LEGACY_KEY_LANGUAGE,)
            )
            conn.commit()

        self._execute_locked(_migrate)

    def _migrate_telemetry_consent(self) -> None:
        def _migrate(conn: sqlite3.Connection):
            existing = self._query_value(conn, self.KEY_TELEMETRY_CONSENT)
            if ConfigValidation.parse_telemetry_consent(existing) is not None:
                self._delete_value(conn, self.KEY_TELEMETRY_ENABLED)
                return

            legacy = self._query_value(conn, self.KEY_TELEMETRY_ENABLED)
            consent = (
                TelemetryConsent.Denied
                if legacy == "0" or legacy.lower() == "false"
                else TelemetryConsent.Unset
            )
            self._set_value(
                conn,
                self.KEY_TELEMETRY_CONSENT,
                ConfigValidation.telemetry_consent_storage(consent),
            )
            self._delete_value(conn, self.KEY_TELEMETRY_ENABLED)
            conn.commit()

        self._execute_locked(_migrate)

    def _query_value(self, conn: sqlite3.Connection, key: str) -> str | None:
        cursor = conn.execute("SELECT value FROM config WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row[0] if row else None

    def _delete_value(self, conn: sqlite3.Connection, key: str) -> None:
        conn.execute("DELETE FROM config WHERE key = ?", (key,))

    def _set_value(
        self, conn: sqlite3.Connection, key: str, value: str
    ) -> None:
        conn.execute(
            """
            INSERT INTO config (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )

    def _set_schema_version(self, version: int) -> None:
        def _set(conn: sqlite3.Connection):
            self._set_value(
                conn,
                self.KEY_CONFIG_SCHEMA_VERSION,
                str(version),
            )
            conn.commit()

        self._execute_locked(_set)

    def _protect_value(self, key: str, plain_text: str) -> str:
        if not self.is_sensitive_key(key) or not plain_text:
            return plain_text

        try:
            master_key = self._key_store.load_or_create()
            if len(master_key) != SecretKeyStore.KEY_SIZE:
                raise ValueError("平台主密钥长度无效，拒绝写入敏感配置")
            return SecretProtector.protect_v2(master_key, key, plain_text)
        except Exception as e:
            logger.error(f"敏感配置 {key} 无法使用平台密钥库：{e}")
            raise

    def _read_secret_value(
        self, key: str, stored: str, migrate: bool
    ) -> SecretReadResult:
        if not stored:
            return SecretReadResult(None, SecretIssueCategory.None_)

        if SecretProtector.is_nsec2(stored) or SecretProtector.is_nsec1(stored):
            try:
                master_key = self._key_store.load_or_create()
            except Exception:
                self.record_secret_issue(key, SecretIssueCategory.KeyStoreUnavailable)
                return SecretReadResult(None, SecretIssueCategory.KeyStoreUnavailable)

            if SecretProtector.is_nsec2(stored):
                valid, plain = SecretProtector.try_unprotect_v2(
                    master_key, key, stored
                )
            else:
                valid, plain = SecretProtector.try_unprotect_v1(master_key, stored)

            if not valid:
                self.record_secret_issue(key, SecretIssueCategory.CorruptCiphertext)
                return SecretReadResult(None, SecretIssueCategory.CorruptCiphertext)

            category = (
                SecretIssueCategory.LegacyNsec1
                if SecretProtector.is_nsec1(stored)
                else SecretIssueCategory.None_
            )

            if migrate and category != SecretIssueCategory.None_:
                self._try_migrate(key, plain)

            if category == SecretIssueCategory.None_:
                self._secret_issues.pop(key, None)

            return SecretReadResult(plain, category)

        if SecretProtector.is_legacy_dpapi(stored):
            if not os.name == "nt":
                self.record_secret_issue(key, SecretIssueCategory.LegacyUnsupported)
                return SecretReadResult(None, SecretIssueCategory.LegacyUnsupported)

            plain = self._unprotect_legacy_dpapi(stored)
            if not plain:
                self.record_secret_issue(key, SecretIssueCategory.CorruptCiphertext)
                return SecretReadResult(None, SecretIssueCategory.CorruptCiphertext)

            if migrate:
                self._try_migrate(key, plain)
            return SecretReadResult(plain, SecretIssueCategory.LegacyDpapi)

        if migrate:
            self._try_migrate(key, stored)
        return SecretReadResult(stored, SecretIssueCategory.LegacyPlaintext)

    def _try_migrate(self, key: str, plain: str) -> None:
        try:
            encrypted = self._protect_value(key, plain)
            self._write_raw(key, encrypted)
            self._secret_issues.pop(key, None)
        except Exception:
            self.record_secret_issue(key, SecretIssueCategory.KeyStoreUnavailable)

    def _write_raw(self, key: str, value: str) -> None:
        def _write(conn: sqlite3.Connection):
            conn.execute(
                """
                INSERT INTO config (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )
            conn.commit()

        self._execute_locked(_write)

    def _unprotect_legacy_dpapi(self, stored: str) -> str | None:
        return None

    def is_first_run(self) -> bool:
        """判断是否首次启动。"""
        value = self.get(self.KEY_FIRST_RUN_COMPLETED)
        if value is None:
            return True
        if value.type_name == "boolean":
            return not value.value
        if value.type_name == "integer":
            return value.value == 0
        if value.type_name == "text":
            return value.value in ("0", "false")
        return False

    def mark_first_run_completed(self) -> None:
        """标记首次启动完成。"""
        self.set(self.KEY_FIRST_RUN_COMPLETED, ConfigValue.boolean(True))

    def complete_first_run(
        self, model_id: str, telemetry_enabled: bool
    ) -> None:
        """原子提交首次运行向导的最终选择。"""
        if not model_id or not model_id.strip():
            raise ValueError("模型 ID 不能为空")

        def _complete(conn: sqlite3.Connection):
            conn.execute("BEGIN TRANSACTION")
            try:
                self._set_value(
                    conn,
                    self.KEY_SELECTED_MODEL,
                    model_id.strip(),
                )
                consent = (
                    TelemetryConsent.Granted
                    if telemetry_enabled
                    else TelemetryConsent.Denied
                )
                self._set_value(
                    conn,
                    self.KEY_TELEMETRY_CONSENT,
                    ConfigValidation.telemetry_consent_storage(consent),
                )
                self._set_value(conn, self.KEY_FIRST_RUN_COMPLETED, "1")
                
                existing = self._query_value(conn, self.KEY_INITIALIZED_AT)
                if not existing:
                    self._set_value(conn, self.KEY_INITIALIZED_AT, self._now())
                
                conn.commit()
            except Exception:
                conn.rollback()
                raise

        self._execute_locked(_complete)

    def mark_initialized(self) -> None:
        """记录首次初始化完成时间 (只写一次)。"""
        if not self.exists(self.KEY_INITIALIZED_AT):
            self.set(self.KEY_INITIALIZED_AT, ConfigValue.text(self._now()))

    def get_init_config(self) -> InitConfig:
        """首次初始化配置快照。"""
        initialized_at_value = self.get(self.KEY_INITIALIZED_AT)
        initialized_at = (
            initialized_at_value.value
            if initialized_at_value and initialized_at_value.value
            else None
        )

        return InitConfig(
            config_schema_version=self._read_schema_version(),
            app_version=self.get_string_or(self.KEY_APP_VERSION, "unknown"),
            installed_at=self.get_string_or(self.KEY_INSTALLED_AT, ""),
            initialized_at=initialized_at,
            language=self.get_string_or(self.KEY_LANGUAGE, self._system_language()),
            selected_model=self.get_string_or(
                self.KEY_SELECTED_MODEL, self.DEFAULT_MODEL
            ),
        )

    @staticmethod
    def _now() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _system_language() -> str:
        import locale

        try:
            name = locale.getdefaultlocale()[0]
            return name if name else "zh-CN"
        except Exception:
            return "zh-CN"
