"""Nori.Core.Memory 长期记忆系统。

提供完整的记忆存储、检索、生命周期管理功能:
- models: 核心数据模型 (MemoryItem, MemoryAtom, MemoryContext 等)
- kind: 记忆语义类型 (MemoryKind 枚举)
- store: SQLite 存储层 (MemoryStore 类)
- service: 记忆服务门面 (MemoryService 类)
"""

from nori_core.memory.models import (
    MemoryIndexState,
    MemoryStatus,
    MemoryEmbeddingWorkItem,
    MemoryEmbeddingUpdate,
    MemoryAtom,
    MemorySource,
    RetrievedKnowledge,
    MemoryEcho,
    RetrievalHit,
    RecallDebugTrace,
    MemoryIndexStatus,
    KnowledgeAwareness,
    MemoryContext,
    MemoryItem,
)
from nori_core.memory.kind import MemoryKind
from nori_core.memory.store import MemoryStore, MemorySearchResult

__all__ = [
    # 枚举
    "MemoryIndexState",
    "MemoryStatus",
    "MemoryKind",
    "KnowledgeAwareness",
    # 数据模型
    "MemoryEmbeddingWorkItem",
    "MemoryEmbeddingUpdate",
    "MemoryAtom",
    "MemorySource",
    "RetrievedKnowledge",
    "MemoryEcho",
    "RetrievalHit",
    "RecallDebugTrace",
    "MemoryIndexStatus",
    "MemoryContext",
    "MemoryItem",
    # 存储层
    "MemoryStore",
    "MemorySearchResult",
]
