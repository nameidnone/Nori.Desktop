"""
Nori Core Memory Module - Python 实现

记忆系统数据模型，对应 C# MemoryModels.cs
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class MemoryKind(Enum):
    """记忆类型"""
    PERSONAL = "personal"  # 个人记忆
    FACT = "fact"  # 事实记忆
    SKILL = "skill"  # 技能记忆
    PREFERENCE = "preference"  # 偏好记忆


class MemoryStatus(Enum):
    """记忆状态"""
    ACTIVE = "active"
    ARCHIVED = "archived"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"


class KnowledgeAwareness(Enum):
    """知识库感知级别"""
    PUBLIC = "public"
    PRIVATE = "private"
    INTERNAL = "internal"


class MemoryIndexState(Enum):
    """记忆索引状态"""
    READY = "ready"
    INDEXING = "indexing"
    ERROR = "error"
    MAINTENANCE = "maintenance"


@dataclass
class MemoryEmbeddingWorkItem:
    """待后台批量生成向量的轻量记录"""
    id: int
    updated_at: str
    text: str


@dataclass
class MemoryEmbeddingUpdate:
    """待写回数据库的向量"""
    id: int
    updated_at: str
    vector: list[float]


@dataclass
class MemoryAtom:
    """记忆事实原子"""
    id: int
    parent_memory_id: int
    atom_type: str
    content: str
    importance: float
    confidence: float
    status: MemoryStatus
    created_at: str
    last_accessed_at: Optional[str] = None
    last_reinforced_at: Optional[str] = None
    ttl_days: Optional[float] = None
    expires_at: Optional[str] = None
    reinforcement_count: int = 0
    superseded_by: Optional[int] = None
    decay_type: str = "exponential"
    entities: Optional[str] = None


@dataclass
class MemorySource:
    """重要记忆保留的原始来源消息"""
    id: int
    memory_id: int
    role: str
    content: str
    message_time: Optional[str] = None
    sequence: int = 0


@dataclass
class MemoryItem:
    """记忆条目"""
    id: int
    kind: MemoryKind
    summary: str
    details: Optional[str] = None
    importance: float = 0.5
    confidence: float = 0.5
    status: MemoryStatus = MemoryStatus.ACTIVE
    created_at: str = ""
    updated_at: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    atom_count: int = 0
    source_count: int = 0


@dataclass
class RetrievedKnowledge:
    """知识库检索结果"""
    id: int
    heading: str
    content: str
    awareness: KnowledgeAwareness
    score: float
    subheading: Optional[str] = None
    knowledge_type: Optional[str] = None


@dataclass
class MemoryEcho:
    """由 ARG 残响生成的安全短提示"""
    content: str
    score: float


@dataclass
class RetrievalHit:
    """检索命中的统一记录"""
    memory_id: int
    score: float
    rank: int


@dataclass
class RecallDebugTrace:
    """Recall Debugger 展示的检索过程"""
    query: str
    expanded_query: str
    keyword_hits: list[RetrievalHit] = field(default_factory=list)
    vector_hits: list[RetrievalHit] = field(default_factory=list)
    atom_hits: list[RetrievalHit] = field(default_factory=list)
    rrf_hits: list[RetrievalHit] = field(default_factory=list)
    filtered_ids: list[int] = field(default_factory=list)
    injected_ids: list[int] = field(default_factory=list)


@dataclass
class MemoryContext:
    """注入 Agent 的完整记忆上下文"""
    personal: list[MemoryItem] = field(default_factory=list)
    atoms: list[MemoryAtom] = field(default_factory=list)
    knowledge: list[RetrievedKnowledge] = field(default_factory=list)
    echoes: list[MemoryEcho] = field(default_factory=list)
    debug: Optional[RecallDebugTrace] = None
    
    def to_dict(self) -> dict:
        """转换为字典格式，便于序列化"""
        return {
            "personal": [
                {
                    "id": p.id,
                    "kind": p.kind.value,
                    "summary": p.summary,
                    "details": p.details,
                    "importance": p.importance,
                    "confidence": p.confidence,
                    "tags": p.tags,
                }
                for p in self.personal
            ],
            "atoms": [
                {
                    "id": a.id,
                    "atomType": a.atom_type,
                    "content": a.content,
                    "importance": a.importance,
                    "confidence": a.confidence,
                }
                for a in self.atoms
            ],
            "knowledge": [
                {
                    "id": k.id,
                    "heading": k.heading,
                    "subheading": k.subheading,
                    "content": k.content,
                    "score": k.score,
                }
                for k in self.knowledge
            ],
            "echoes": [
                {"content": e.content, "score": e.score}
                for e in self.echoes
            ],
            "debug": self.debug.__dict__ if self.debug else None,
        }


@dataclass
class MemoryIndexStatus:
    """索引状态摘要"""
    state: MemoryIndexState = MemoryIndexState.READY
    processed: int = 0
    total: int = 0
    last_error: Optional[str] = None
    last_maintenance_at: Optional[str] = None
    last_reflection_at: Optional[str] = None


@dataclass
class MemorySettings:
    """记忆设置的领域 DTO"""
    enabled: bool = True
    reflection_enabled: bool = True
    reflection_rounds: int = 8
    reflection_min_chars: int = 2500
    recall_top_k: int = 6
    keyword_top_k: int = 20
    vector_top_k: int = 20
    rrf_k: int = 60
    min_similarity: float = 0.25
    decay_enabled: bool = True
    archive_enabled: bool = True
    source_retention_threshold: float = 0.75
    archive_threshold: float = 0.15
    knowledge_enabled: bool = True
    knowledge_watch: bool = True
    debug_retrieval: bool = False
    
    def to_dict(self) -> dict:
        """转换为字典格式"""
        return {
            "enabled": self.enabled,
            "reflectionEnabled": self.reflection_enabled,
            "reflectionRounds": self.reflection_rounds,
            "reflectionMinChars": self.reflection_min_chars,
            "recallTopK": self.recall_top_k,
            "keywordTopK": self.keyword_top_k,
            "vectorTopK": self.vector_top_k,
            "rrfK": self.rrf_k,
            "minSimilarity": self.min_similarity,
            "decayEnabled": self.decay_enabled,
            "archiveEnabled": self.archive_enabled,
            "sourceRetentionThreshold": self.source_retention_threshold,
            "archiveThreshold": self.archive_threshold,
            "knowledgeEnabled": self.knowledge_enabled,
            "knowledgeWatch": self.knowledge_watch,
            "debugRetrieval": self.debug_retrieval,
        }


__all__ = [
    # Enums
    "MemoryKind",
    "MemoryStatus",
    "KnowledgeAwareness",
    "MemoryIndexState",
    # Data models
    "MemoryEmbeddingWorkItem",
    "MemoryEmbeddingUpdate",
    "MemoryAtom",
    "MemorySource",
    "MemoryItem",
    "RetrievedKnowledge",
    "MemoryEcho",
    "RetrievalHit",
    "RecallDebugTrace",
    "MemoryContext",
    "MemoryIndexStatus",
    "MemorySettings",
]
