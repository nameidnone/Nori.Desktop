"""Nori.Core.Memory 记忆类型定义。

长期记忆的语义类型分类。
"""

from enum import Enum


class MemoryKind(Enum):
    """长期记忆的语义类型。"""
    General = "general"
    Episodic = "episodic"
    Factual = "factual"
    Preference = "preference"
    Relational = "relational"
    Planned = "planned"
    Identity = "identity"

    def to_storage(self) -> str:
        """转换为数据库存储格式。"""
        return self.value

    @classmethod
    def parse(cls, value: str | None) -> 'MemoryKind':
        """从数据库文本值解析。"""
        if value is None:
            return cls.General
        
        normalized = value.strip().lower()
        mapping = {
            "episodic": cls.Episodic,
            "event": cls.Episodic,
            "factual": cls.Factual,
            "fact": cls.Factual,
            "preference": cls.Preference,
            "prefer": cls.Preference,
            "relational": cls.Relational,
            "relationship": cls.Relational,
            "planned": cls.Planned,
            "plan": cls.Planned,
            "identity": cls.Identity,
            "name": cls.Identity,
        }
        return mapping.get(normalized, cls.General)
