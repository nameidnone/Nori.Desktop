"""
Nori Core Memory Module - Python 实现

记忆系统数据模型，对应 C# MemoryModels.cs
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List


class MemoryKind(Enum):
    """记忆类型"""
    PERSONAL = "personal"  # 个人记忆
    FACT = "fact"  # 事实记忆
    SKILL = "skill"  # 技能记忆
    PREFERENCE = "preference"  # 偏好记忆
    CONVERSATIONAL = "conversational"  # 对话记忆


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


class MemorySource(Enum):
    """记忆来源"""
    CHAT = "chat"
    USER_INPUT = "user_input"
    SYSTEM = "system"
    EXTRACTED = "extracted"
    IMPORTED = "imported"


@dataclass
class MemoryContent:
    """记忆内容"""
    text: str
    metadata: dict = field(default_factory=dict)


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
class MemorySourceItem:
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
    id: str
    kind: MemoryKind
    status: MemoryStatus
    source: MemorySource
    content: MemoryContent
    embedding: Optional[List[float]] = None
    strength: float = 1.0
    importance: float = 0.5
    frequency: int = 1
    created_at: float = 0.0
    updated_at: float = 0.0
    last_accessed_at: Optional[float] = None
    expires_at: Optional[float] = None
    session_id: Optional[str] = None
    conversation_id: Optional[str] = None
    message_id: Optional[str] = None
    tags: Optional[List[str]] = None
    entities: Optional[List[str]] = None


@dataclass
class RetrievedKnowledge:
    """知识库检索结果"""
    memory_id: str
    content: MemoryContent
    relevance_score: float
    kind: MemoryKind
    created_at: float
    accessed_at: float


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
    memories: list[RetrievedKnowledge] = field(default_factory=list)
    total_tokens: int = 0
    generated_at: float = 0.0
    
    def to_dict(self) -> dict:
        """转换为字典格式，便于序列化"""
        return {
            "memories": [
                {
                    "memory_id": m.memory_id,
                    "content": m.content.text,
                    "relevance_score": m.relevance_score,
                    "kind": m.kind.value,
                }
                for m in self.memories
            ],
            "total_tokens": self.total_tokens,
            "generated_at": self.generated_at,
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
    "MemorySource",
    # Data models
    "MemoryContent",
    "MemoryEmbeddingWorkItem",
    "MemoryEmbeddingUpdate",
    "MemoryAtom",
    "MemorySourceItem",
    "MemoryItem",
    "RetrievedKnowledge",
    "MemoryEcho",
    "RetrievalHit",
    "RecallDebugTrace",
    "MemoryContext",
    "MemoryIndexStatus",
    "MemorySettings",
]
