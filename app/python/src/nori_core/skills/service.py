"""
Nori Core Skills Module - Python 实现

技能系统数据模型和服务，对应 C# SkillRecord.cs, SkillService.cs
"""

from __future__ import annotations
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class SkillRecord:
    """
    技能数据模型 (Nori Skill Definition)
    
    字段名与前端 runtime SkillDto 完全一致 (camelCase JSON)。
    """
    id: str = ""  # 技能唯一 ID (如 "code-reviewer")
    name: str = ""  # 技能显示名称
    description: str = ""  # 技能简要描述
    author: str = ""  # 作者名称
    version: str = "1.0.0"  # 语义化版本号
    icon: str = "sparkles"  # 显示图标
    tags: list[str] = field(default_factory=list)  # 分类标签列表
    category: str = "productivity"  # 所属主分类
    instructions: str = ""  # 注入 Agent System Prompt 的行为指引
    tools: Optional[list[str]] = None  # 该技能依赖或推荐启用的工具名称列表
    enabled: bool = False  # 是否已启用
    source: str = "custom"  # 技能来源：builtin / market / custom / url
    installed_at: int = 0  # 安装时间戳 (毫秒)
    url: Optional[str] = None  # 远程来源 URL (若从网络安装)
    
    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式 (camelCase keys for JSON)"""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "author": self.author,
            "version": self.version,
            "icon": self.icon,
            "tags": self.tags,
            "category": self.category,
            "instructions": self.instructions,
            "tools": self.tools,
            "enabled": self.enabled,
            "source": self.source,
            "installedAt": self.installed_at,
            "url": self.url,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SkillRecord":
        """从字典创建实例"""
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            description=data.get("description", ""),
            author=data.get("author", ""),
            version=data.get("version", "1.0.0"),
            icon=data.get("icon", "sparkles"),
            tags=data.get("tags", []),
            category=data.get("category", "productivity"),
            instructions=data.get("instructions", ""),
            tools=data.get("tools"),
            enabled=data.get("enabled", False),
            source=data.get("source", "custom"),
            installed_at=data.get("installedAt", 0),
            url=data.get("url"),
        )
    
    @staticmethod
    def is_remote_source(source: str) -> bool:
        """判断是否为远程来源"""
        return source in ("market", "url", "custom")


# 敏感信息检测正则 (对应 C# SensitiveRemoteContentPattern)
_SENSITIVE_CONTENT_PATTERN = re.compile(
    r"""(?ix)
        (?:
            ["']?(?:api[_-]?key|access[_-]?token|refresh[_-]?token|authorization|bearer|password|secret|client[_-]?secret|private[_-]?key|cookie|token)["']?
            \s*[:=]\s*["']?[^\s"',;}\]]+
        )
        |
        [?&](?:api[_-]?key|access[_-]?token|refresh[_-]?token|authorization|bearer|password|secret|client[_-]?secret|private[_-]?key|cookie|token)=[^&#\s]+
        |
        -----BEGIN [A-Z0-9 ]*PRIVATE KEY-----
        |
        \b(?:sk-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9_-]{16,}|xox[baprs]-[A-Za-z0-9-]{16,})\b
    """,
    re.IGNORECASE | re.VERBOSE
)


def detect_sensitive_content(content: str) -> bool:
    """检测内容是否包含敏感信息"""
    return bool(_SENSITIVE_CONTENT_PATTERN.search(content))


class SkillService:
    """
    技能管理器服务
    
    支持本地技能、市场安装、URL 网络安装 (SKILL.md / JSON) 与 Prompt 动态注入。
    数据持久化沿用前端写入的 config 键 nori_skills (JSON 数组), 完全兼容既有数据。
    """
    
    CONFIG_KEY = "nori_skills"
    MAX_REMOTE_SIZE = 1024 * 1024  # 1 MB
    
    def __init__(self, config_store: Optional[Any] = None):
        self._config_store = config_store
        self._skills: dict[str, SkillRecord] = {}
        self._initialized = False
        self._lock = threading.Lock()
    
    def ensure_loaded(self) -> None:
        """加载技能列表 (首次缺失时种子内置预设)"""
        with self._lock:
            if self._initialized:
                return
            
            # 加载内置技能
            loaded = self._load_builtin_skills()
            
            # 尝试从配置恢复
            if self._config_store:
                try:
                    saved_data = getattr(self._config_store, 'get', lambda k, d: d)(self.CONFIG_KEY, None)
                    if saved_data:
                        if isinstance(saved_data, str):
                            skill_list = json.loads(saved_data)
                        else:
                            skill_list = saved_data
                        
                        for raw_skill in skill_list:
                            if not raw_skill.get("id"):
                                continue
                            
                            skill_id = raw_skill["id"]
                            if skill_id in loaded:
                                # 只接受旧配置对内置技能的启停修改
                                loaded[skill_id].enabled = raw_skill.get("enabled", False)
                            else:
                                # 添加新技能
                                loaded[skill_id] = SkillRecord.from_dict(raw_skill)
                except Exception:
                    pass
            
            self._skills = loaded
            self._initialized = True
    
    def _load_builtin_skills(self) -> dict[str, SkillRecord]:
        """加载内置技能预设"""
        from .presets import SkillPresets
        skills = {}
        for preset in SkillPresets.ALL:
            skills[preset.id] = SkillRecord(
                id=preset.id,
                name=preset.name,
                description=preset.description,
                instructions=preset.instructions,
                category=preset.category,
                tags=preset.tags,
                icon=preset.icon,
                author=preset.author,
                version=preset.version,
                enabled=True,
                source="builtin",
                installed_at=int(time.time() * 1000),
            )
        return skills
    
    def get_all_skills(self) -> list[SkillRecord]:
        """获取所有技能"""
        self.ensure_loaded()
        with self._lock:
            return list(self._skills.values())
    
    def get_enabled_skills(self) -> list[SkillRecord]:
        """获取已启用的技能"""
        self.ensure_loaded()
        with self._lock:
            return [s for s in self._skills.values() if s.enabled]
    
    def get_skill(self, skill_id: str) -> Optional[SkillRecord]:
        """获取指定技能"""
        self.ensure_loaded()
        with self._lock:
            return self._skills.get(skill_id)
    
    def enable_skill(self, skill_id: str) -> bool:
        """启用技能"""
        self.ensure_loaded()
        with self._lock:
            if skill_id not in self._skills:
                return False
            self._skills[skill_id].enabled = True
            self._save_skills()
            return True
    
    def disable_skill(self, skill_id: str) -> bool:
        """禁用技能"""
        self.ensure_loaded()
        with self._lock:
            if skill_id not in self._skills:
                return False
            self._skills[skill_id].enabled = False
            self._save_skills()
            return True
    
    def add_skill(self, skill: SkillRecord) -> bool:
        """添加新技能"""
        self.ensure_loaded()
        with self._lock:
            if not skill.id:
                return False
            self._skills[skill.id] = skill
            self._save_skills()
            return True
    
    def remove_skill(self, skill_id: str) -> bool:
        """移除技能 (内置技能只能禁用不能删除)"""
        self.ensure_loaded()
        with self._lock:
            if skill_id not in self._skills:
                return False
            if self._skills[skill_id].source == "builtin":
                return False
            del self._skills[skill_id]
            self._save_skills()
            return True
    
    def build_instructions_prompt(self) -> str:
        """构建已启用技能的指令 Prompt"""
        self.ensure_loaded()
        with self._lock:
            enabled = [s for s in self._skills.values() if s.enabled and s.instructions]
            if not enabled:
                return ""
            
            parts = ["## Active Skills"]
            for skill in enabled:
                parts.append(f"\n### {skill.name} ({skill.id})")
                parts.append(skill.instructions)
            
            return "\n".join(parts)
    
    def _save_skills(self) -> None:
        """保存技能列表到配置"""
        if not self._config_store:
            return
        
        try:
            skills_list = [s.to_dict() for s in self._skills.values()]
            json_str = json.dumps(skills_list, ensure_ascii=False)
            if hasattr(self._config_store, 'set'):
                self._config_store.set(self.CONFIG_KEY, json_str)
        except Exception:
            pass


import threading

__all__ = [
    "SkillRecord",
    "SkillService",
    "detect_sensitive_content",
]
