"""Nori.Core.Memory 数据模型定义。

长期记忆系统的核心数据契约，包括:
- MemoryEmbeddingWorkItem: 待批量生成向量的轻量记录
- MemoryEmbeddingUpdate: 待写回数据库的向量
- MemoryAtom: 记忆事实原子
- MemorySource: 重要记忆保留的原始来源消息
- RetrievedKnowledge: 知识库检索结果
- MemoryEcho: 由 ARG 残响生成的安全短提示
- MemoryContext: 注入 Agent 的完整记忆上下文
- RetrievalHit: 检索命中的统一记录
- RecallDebugTrace: Recall Debugger 展示的检索过程
- MemoryIndexStatus: 索引状态摘要
"""

from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING
from enum import Enum

if TYPE_CHECKING:
    from nori_core.memory.knowledge import KnowledgeAwareness
    from nori_core.memory.models import MemoryItem


class MemoryIndexState(Enum):
    """记忆索引状态。"""
    Ready = "ready"
    Building = "building"
    Rebuilding = "rebuilding"
    Degraded = "degraded"
    Failed = "failed"


class MemoryStatus(Enum):
    """记忆状态。"""
    Active = "active"
    Archived = "archived"
    Decayed = "decayed"
    Superseded = "superseded"
    Pending = "pending"


@dataclass(frozen=True)
class MemoryEmbeddingWorkItem:
    """待后台批量生成向量的轻量记录。"""
    id: int
    updated_at: str
    text: str


@dataclass(frozen=True)
class MemoryEmbeddingUpdate:
    """待写回数据库的向量。"""
    id: int
    updated_at: str
    vector: list[float]


@dataclass(frozen=True)
class MemoryAtom:
    """记忆事实原子。"""
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


@dataclass(frozen=True)
class MemorySource:
    """重要记忆保留的原始来源消息。"""
    id: int
    memory_id: int
    role: str
    content: str
    message_time: Optional[str] = None
    sequence: int = 0


@dataclass(frozen=True)
class RetrievedKnowledge:
    """知识库检索结果。"""
    id: int
    heading: str
    subheading: Optional[str]
    content: str
    awareness: 'KnowledgeAwareness'
    knowledge_type: Optional[str] = None
    score: float = 0.0


@dataclass(frozen=True)
class MemoryEcho:
    """由 ARG 残响生成的安全短提示。"""
    content: str
    score: float


@dataclass(frozen=True)
class RetrievalHit:
    """检索命中的统一记录。"""
    memory_id: int
    score: float
    rank: int


@dataclass(frozen=True)
class RecallDebugTrace:
    """Recall Debugger 展示的检索过程。"""
    query: str
    expanded_query: str
    keyword_hits: tuple[RetrievalHit, ...] = field(default_factory=tuple)
    vector_hits: tuple[RetrievalHit, ...] = field(default_factory=tuple)
    atom_hits: tuple[RetrievalHit, ...] = field(default_factory=tuple)
    rrf_hits: tuple[RetrievalHit, ...] = field(default_factory=tuple)
    filtered_ids: tuple[int, ...] = field(default_factory=tuple)
    injected_ids: tuple[int, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class MemoryIndexStatus:
    """索引状态摘要。"""
    state: MemoryIndexState = MemoryIndexState.Ready
    processed: int = 0
    total: int = 0
    last_updated_at: Optional[str] = None
    error_message: Optional[str] = None


"""Nori.Core.Memory 知识感知级别定义。

ARG 知识对当前 Nori 的认知可见性。
"""

from enum import Enum


class KnowledgeAwareness(Enum):
    """ARG 知识对当前 Nori 的认知可见性。"""
    WorldFact = "world_fact"
    ArchiveRecord = "archive_record"
    Inference = "inference"
    Unresolved = "unresolved"
    NoriKnows = "nori_knows"
    NoriEcho = "nori_echo"
    NoriUnknown = "nori_unknown"
    Recovered = "recovered"
    UserSharedMemory = "user_shared_memory"

    def to_storage(self) -> str:
        """转换为数据库存储格式。"""
        return self.value

    @classmethod
    def parse(cls, value: str | None) -> 'KnowledgeAwareness':
        """从数据库文本值解析。"""
        if value is None:
            return cls.WorldFact
        
        normalized = value.strip().lower()
        mapping = {
            "archive_record": cls.ArchiveRecord,
            "archive": cls.ArchiveRecord,
            "inference": cls.Inference,
            "high_confidence_inference": cls.Inference,
            "unresolved": cls.Unresolved,
            "nori_knows": cls.NoriKnows,
            "knows": cls.NoriKnows,
            "nori_echo": cls.NoriEcho,
            "echo": cls.NoriEcho,
            "nori_unknown": cls.NoriUnknown,
            "unknown": cls.NoriUnknown,
            "recovered": cls.Recovered,
            "recovered_memory": cls.Recovered,
            "user_shared_memory": cls.UserSharedMemory,
        }
        return mapping.get(normalized, cls.WorldFact)


@dataclass(frozen=True)
class MemoryContext:
    """注入 Agent 的完整记忆上下文。"""
    personal: tuple['MemoryItem', ...] = field(default_factory=tuple)
    atoms: tuple[MemoryAtom, ...] = field(default_factory=tuple)
    knowledge: tuple['RetrievedKnowledge', ...] = field(default_factory=tuple)
    echoes: tuple[MemoryEcho, ...] = field(default_factory=tuple)
    debug: Optional['RecallDebugTrace'] = None


# 前向引用解决 MemoryItem - 在文件末尾定义
@dataclass(frozen=True)
class MemoryItem:
    """长期记忆项目。"""
    id: int
    content: str
    status: MemoryStatus = MemoryStatus.Active
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    embedding_status: str = "pending"  # pending, embedded, failed
    ttl_days: Optional[float] = None
    expires_at: Optional[str] = None
    source_count: int = 0
    atom_count: int = 0
