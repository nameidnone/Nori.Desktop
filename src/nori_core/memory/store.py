"""Nori.Core.Memory 存储层实现。

SQLite 记忆存储兼容层，提供:
- MemoryItem: 记忆数据模型
- MemorySearchResult: 语义检索匹配结果  
- MemoryStore: SQLite 记忆存储核心类
"""

from __future__ import annotations
import sqlite3
import threading
import math
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING
from collections import OrderedDict

if TYPE_CHECKING:
    from nori_core.data.database_manager import NoriDatabase
    from nori_core.memory.models import (
        MemoryAtom, MemorySource, MemoryEmbeddingWorkItem, MemoryEmbeddingUpdate
    )
    from nori_core.memory.kind import MemoryKind


@dataclass(frozen=True)
class MemoryItem:
    """记忆数据模型。"""
    id: int
    type: str
    content: str
    importance: float
    source: str
    created_at: str
    updated_at: str
    tags: Optional[str] = None
    embedding: Optional[str] = None
    embedding_blob: Optional[bytes] = None
    kind: str = "general"
    canonical_summary: Optional[str] = None
    persona_summary: Optional[str] = None
    confidence: float = 0.8
    status: str = "active"
    access_count: int = 0
    reinforcement_count: int = 0
    last_accessed_at: Optional[str] = None
    last_reinforced_at: Optional[str] = None
    ttl_days: Optional[float] = None
    expires_at: Optional[str] = None
    superseded_by: Optional[int] = None
    embedding_fingerprint: Optional[str] = None

    def get_vector(self) -> Optional[list[float]]:
        """解析 BLOB 或旧 JSON 向量数组。"""
        # TODO: 实现 embedding vector 解码
        if self.embedding_blob:
            # 假设 blob 是 float32 little-endian
            import struct
            if len(self.embedding_blob) % 4 == 0:
                count = len(self.embedding_blob) // 4
                return list(struct.unpack('<' + 'f' * count, self.embedding_blob))
        return None


@dataclass(frozen=True)
class MemorySearchResult:
    """语义检索匹配结果。"""
    item: MemoryItem
    similarity: float
    score: float


class MemoryStore:
    """
    SQLite 记忆存储兼容层。
    
    旧的 MemoryStore API 保留给桥接和插件；所有新增聚合写入在这里统一维护 Atom、Source 与 FTS。
    """
    
    DEFAULT_SEMANTIC_CANDIDATE_LIMIT = 100000
    DEFAULT_VECTOR_CACHE_CAPACITY = 512
    
    def __init__(
        self,
        database: 'NoriDatabase',
        semantic_candidate_limit: int = DEFAULT_SEMANTIC_CANDIDATE_LIMIT,
        vector_cache_capacity: int = DEFAULT_VECTOR_CACHE_CAPACITY
    ):
        if semantic_candidate_limit <= 0:
            raise ValueError(f"semantic_candidate_limit must be > 0, got {semantic_candidate_limit}")
        if vector_cache_capacity <= 0:
            raise ValueError(f"vector_cache_capacity must be > 0, got {vector_cache_capacity}")
        
        self._database = database
        self._semantic_candidate_limit = semantic_candidate_limit
        self._vector_cache_capacity = vector_cache_capacity
        self._vector_cache_gate = threading.Lock()
        # OrderedDict 用于 LRU 淘汰
        self._vector_cache: OrderedDict[int, tuple[str, list[float]]] = OrderedDict()
        self._fts_available = False
        self._initialize_fts()
    
    @property
    def is_fts_available(self) -> bool:
        """当前 SQLite 是否提供可用的 FTS5 索引。"""
        return self._fts_available
    
    def _vector_of(self, item: MemoryItem) -> Optional[list[float]]:
        """获取向量，使用缓存。"""
        if not item.embedding and not item.embedding_blob:
            return None
        
        with self._vector_cache_gate:
            # 检查缓存
            if item.id in self._vector_cache:
                cached_updated_at, cached_vector = self._vector_cache[item.id]
                if cached_updated_at == item.updated_at:
                    # 移到末尾 (最近使用)
                    self._vector_cache.move_to_end(item.id)
                    return cached_vector
            
            # 未命中，从 item 解析
            vector = item.get_vector()
            if vector is None:
                return None
            
            # LRU 淘汰
            if len(self._vector_cache) >= self._vector_cache_capacity:
                # 删除最旧的
                self._vector_cache.popitem(last=False)
            
            # 存入缓存
            self._vector_cache[item.id] = (item.updated_at, vector)
            return vector
    
    def _evict_vector(self, id: int) -> None:
        """从缓存中删除向量。"""
        with self._vector_cache_gate:
            self._vector_cache.pop(id, None)
    
    def _initialize_fts(self) -> None:
        """初始化 FTS5 全文索引。"""
        # TODO: 实现 FTS 初始化逻辑
        try:
            # 检查 FTS5 是否可用
            conn = self._database.get_connection()
            cursor = conn.execute("SELECT fts5()")
            cursor.fetchone()
            self._fts_available = True
        except Exception:
            self._fts_available = False
    
    @staticmethod
    def cosine_similarity(a: list[float], b: list[float]) -> float:
        """计算余弦相似度。"""
        if len(a) != len(b) or len(a) == 0:
            return 0.0
        
        dot_product = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        
        if norm_a == 0 or norm_b == 0:
            return 0.0
        
        return dot_product / (norm_a * norm_b)
    
    @staticmethod
    def fuse_rrf(rankings: list[list[tuple[int, float]]], k: int = 60) -> dict[int, float]:
        """
        融合多个排序列表使用 Reciprocal Rank Fusion (RRF)。
        
        Args:
            rankings: 多个排序列表，每个元素为 (id, score) 元组
            k: RRF 常量，默认 60
        
        Returns:
            融合后的分数映射 {id: score}
        """
        fused_scores: dict[int, float] = {}
        
        for ranking in rankings:
            for rank, (item_id, _) in enumerate(ranking, start=1):
                fused_scores[item_id] = fused_scores.get(item_id, 0.0) + 1.0 / (k + rank)
        
        return fused_scores
    
    def add(
        self,
        type: str,
        content: str,
        importance: float = 0.5,
        source: str = "chat",
        tags: Optional[str] = None,
        embedding: Optional[str] = None,
        kind: 'MemoryKind' | None = None,
        canonical_summary: Optional[str] = None,
        persona_summary: Optional[str] = None,
        confidence: float = 0.8,
        ttl_days: Optional[float] = None,
        expires_at: Optional[str] = None,
        embedding_fingerprint: Optional[str] = None,
    ) -> MemoryItem:
        """添加一条记忆，并初始化 v4 聚合字段。"""
        from nori_core.memory.kind import MemoryKind
        
        # 验证分数范围
        if not (0 <= importance <= 1):
            raise ValueError(f"importance must be between 0 and 1, got {importance}")
        if not (0 <= confidence <= 1):
            raise ValueError(f"confidence must be between 0 and 1, got {confidence}")
        
        import datetime
        now = datetime.datetime.utcnow().isoformat()
        
        # 确定 kind
        storage_kind = kind.to_storage() if kind else MemoryKind.General.to_storage()
        
        # 准备 embedding 存储
        embedding_blob: Optional[bytes] = None
        if embedding:
            # TODO: 实现 embedding 编码
            pass
        
        # 插入数据库
        def _insert(conn: sqlite3.Connection) -> int:
            cursor = conn.execute("""
                INSERT INTO memories
                    (type, content, importance, source, tags, embedding, embedding_blob, 
                     created_at, updated_at, kind, canonical_summary, persona_summary, 
                     confidence, status, ttl_days, expires_at, embedding_fingerprint)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
            """, (
                type, content, importance, source, tags, embedding, embedding_blob,
                now, now, storage_kind, canonical_summary or content, 
                persona_summary or content, confidence, ttl_days, expires_at, embedding_fingerprint
            ))
            return cursor.lastrowid
        
        memory_id = self._database.locked(_insert)
        
        # 刷新索引
        # TODO: 实现索引刷新
        
        return MemoryItem(
            id=memory_id,
            type=type,
            content=content,
            importance=importance,
            source=source,
            tags=tags,
            embedding=embedding,
            embedding_blob=embedding_blob,
            created_at=now,
            updated_at=now,
            kind=storage_kind,
            canonical_summary=canonical_summary or content,
            persona_summary=persona_summary or content,
            confidence=confidence,
            status="active",
            ttl_days=ttl_days,
            expires_at=expires_at,
            embedding_fingerprint=embedding_fingerprint,
        )
    
    def get(self, id: int) -> Optional[MemoryItem]:
        """根据 ID 获取记忆。"""
        def _get(conn: sqlite3.Connection) -> Optional[MemoryItem]:
            cursor = conn.execute("""
                SELECT id, type, content, importance, source, tags, embedding, 
                       embedding_blob, created_at, updated_at, kind, canonical_summary, 
                       persona_summary, confidence, status, access_count, 
                       reinforcement_count, last_accessed_at, last_reinforced_at, 
                       ttl_days, expires_at, superseded_by, embedding_fingerprint
                FROM memories WHERE id = ?
            """, (id,))
            row = cursor.fetchone()
            if not row:
                return None
            
            return MemoryItem(
                id=row[0], type=row[1], content=row[2], importance=row[3],
                source=row[4], tags=row[5], embedding=row[6], embedding_blob=row[7],
                created_at=row[8], updated_at=row[9], kind=row[10],
                canonical_summary=row[11], persona_summary=row[12], confidence=row[13],
                status=row[14], access_count=row[15], reinforcement_count=row[16],
                last_accessed_at=row[17], last_reinforced_at=row[18],
                ttl_days=row[19], expires_at=row[20], superseded_by=row[21],
                embedding_fingerprint=row[22],
            )
        
        return self._database.locked(_get)
    
    def get_all(self, limit: int = 100) -> list[MemoryItem]:
        """获取所有记忆（限制数量）。"""
        def _get_all(conn: sqlite3.Connection) -> list[MemoryItem]:
            cursor = conn.execute("""
                SELECT id, type, content, importance, source, tags, embedding, 
                       embedding_blob, created_at, updated_at, kind, canonical_summary, 
                       persona_summary, confidence, status, access_count, 
                       reinforcement_count, last_accessed_at, last_reinforced_at, 
                       ttl_days, expires_at, superseded_by, embedding_fingerprint
                FROM memories ORDER BY id DESC LIMIT ?
            """, (limit,))
            
            items = []
            for row in cursor.fetchall():
                items.append(MemoryItem(
                    id=row[0], type=row[1], content=row[2], importance=row[3],
                    source=row[4], tags=row[5], embedding=row[6], embedding_blob=row[7],
                    created_at=row[8], updated_at=row[9], kind=row[10],
                    canonical_summary=row[11], persona_summary=row[12], confidence=row[13],
                    status=row[14], access_count=row[15], reinforcement_count=row[16],
                    last_accessed_at=row[17], last_reinforced_at=row[18],
                    ttl_days=row[19], expires_at=row[20], superseded_by=row[21],
                    embedding_fingerprint=row[22],
                ))
            return items
        
        return self._database.locked(_get_all)
    
    def search_keyword(self, keyword: str, limit: int = 20) -> list[tuple[int, float]]:
        """关键词搜索，返回 (id, score) 列表。"""
        if not self._fts_available:
            # FTS 不可用时降级到 LIKE 查询
            def _search_like(conn: sqlite3.Connection) -> list[tuple[int, float]]:
                cursor = conn.execute("""
                    SELECT id, 1.0 as score FROM memories 
                    WHERE content LIKE ? OR canonical_summary LIKE ?
                    ORDER BY id DESC LIMIT ?
                """, (f"%{keyword}%", f"%{keyword}%", limit))
                return [(row[0], row[1]) for row in cursor.fetchall()]
            return self._database.locked(_search_like)
        
        # FTS5 查询
        def _search_fts(conn: sqlite3.Connection) -> list[tuple[int, float]]:
            cursor = conn.execute("""
                SELECT memories.id, bm25(memory_fts) as score 
                FROM memory_fts JOIN memories ON memory_fts.rowid = memories.rowid
                WHERE memory_fts MATCH ?
                ORDER BY score LIMIT ?
            """, (keyword, limit))
            return [(row[0], row[1]) for row in cursor.fetchall()]
        
        try:
            return self._database.locked(_search_fts)
        except Exception:
            # FTS 失败时降级
            return self.search_keyword(keyword, limit)
    
    def update(
        self,
        id: int,
        content: Optional[str] = None,
        importance: Optional[float] = None,
        tags: Optional[str] = None,
        canonical_summary: Optional[str] = None,
        persona_summary: Optional[str] = None,
        confidence: Optional[float] = None,
        ttl_days: Optional[float] = None,
        expires_at: Optional[str] = None,
    ) -> bool:
        """更新记忆字段。"""
        updates = []
        params = []
        
        if content is not None:
            updates.append("content = ?")
            params.append(content)
        if importance is not None:
            if not (0 <= importance <= 1):
                raise ValueError(f"importance must be between 0 and 1, got {importance}")
            updates.append("importance = ?")
            params.append(importance)
        if tags is not None:
            updates.append("tags = ?")
            params.append(tags)
        if canonical_summary is not None:
            updates.append("canonical_summary = ?")
            params.append(canonical_summary)
        if persona_summary is not None:
            updates.append("persona_summary = ?")
            params.append(persona_summary)
        if confidence is not None:
            if not (0 <= confidence <= 1):
                raise ValueError(f"confidence must be between 0 and 1, got {confidence}")
            updates.append("confidence = ?")
            params.append(confidence)
        if ttl_days is not None:
            updates.append("ttl_days = ?")
            params.append(ttl_days)
        if expires_at is not None:
            updates.append("expires_at = ?")
            params.append(expires_at)
        
        if not updates:
            return False
        
        updates.append("updated_at = ?")
        import datetime
        params.append(datetime.datetime.utcnow().isoformat())
        params.append(id)
        
        def _update(conn: sqlite3.Connection) -> bool:
            cursor = conn.execute(f"""
                UPDATE memories SET {', '.join(updates)} WHERE id = ?
            """, params)
            return cursor.rowcount > 0
        
        return self._database.locked(_update)
    
    def set_status(self, id: int, status: str, superseded_by: Optional[int] = None) -> bool:
        """设置记忆状态。"""
        import datetime
        now = datetime.datetime.utcnow().isoformat()
        
        def _set_status(conn: sqlite3.Connection) -> bool:
            if superseded_by is not None:
                cursor = conn.execute("""
                    UPDATE memories SET status = ?, superseded_by = ?, updated_at = ?
                    WHERE id = ?
                """, (status, superseded_by, now, id))
            else:
                cursor = conn.execute("""
                    UPDATE memories SET status = ?, updated_at = ? WHERE id = ?
                """, (status, now, id))
            return cursor.rowcount > 0
        
        return self._database.locked(_set_status)
    
    def archive(self, id: int) -> bool:
        """归档记忆。"""
        return self.set_status(id, "archived")
    
    def restore(self, id: int) -> bool:
        """恢复已归档的记忆。"""
        def _restore(conn: sqlite3.Connection) -> bool:
            import datetime
            now = datetime.datetime.utcnow().isoformat()
            cursor = conn.execute("""
                UPDATE memories SET status = 'active', superseded_by = NULL, updated_at = ?
                WHERE id = ?
            """, (now, id))
            return cursor.rowcount > 0
        
        return self._database.locked(_restore)
    
    def delete(self, id: int) -> bool:
        """删除记忆。"""
        def _delete(conn: sqlite3.Connection) -> bool:
            # 先删除关联的 atoms 和 sources
            conn.execute("DELETE FROM memory_atoms WHERE parent_memory_id = ?", (id,))
            conn.execute("DELETE FROM memory_sources WHERE memory_id = ?", (id,))
            # 删除记忆本身
            cursor = conn.execute("DELETE FROM memories WHERE id = ?", (id,))
            # 从向量缓存中移除
            self._evict_vector(id)
            return cursor.rowcount > 0
        
        return self._database.locked(_delete)
    
    def mark_accessed(self, ids: list[int]) -> None:
        """标记记忆为已访问。"""
        import datetime
        now = datetime.datetime.utcnow().isoformat()
        
        def _mark(conn: sqlite3.Connection) -> None:
            for id in ids:
                conn.execute("""
                    UPDATE memories 
                    SET access_count = access_count + 1, last_accessed_at = ?
                    WHERE id = ?
                """, (now, id))
        
        self._database.locked(_mark)
    
    def reinforce(self, id: int, importance_increment: float = 0.02) -> bool:
        """强化记忆（增加重要性和强化计数）。"""
        import datetime
        now = datetime.datetime.utcnow().isoformat()
        
        def _reinforce(conn: sqlite3.Connection) -> bool:
            cursor = conn.execute("""
                UPDATE memories 
                SET importance = MIN(1.0, importance + ?),
                    reinforcement_count = reinforcement_count + 1,
                    last_reinforced_at = ?,
                    updated_at = ?
                WHERE id = ?
            """, (importance_increment, now, now, id))
            return cursor.rowcount > 0
        
        return self._database.locked(_reinforce)
    
    def get_engine_state(self, key: str) -> Optional[str]:
        """获取引擎状态值。"""
        def _get(conn: sqlite3.Connection) -> Optional[str]:
            cursor = conn.execute(
                "SELECT value FROM memory_engine_state WHERE key = ?", (key,)
            )
            row = cursor.fetchone()
            return row[0] if row else None
        
        return self._database.locked(_get)
    
    def set_engine_state(self, key: str, value: str) -> None:
        """设置引擎状态值。"""
        import datetime
        now = datetime.datetime.utcnow().isoformat()
        
        def _set(conn: sqlite3.Connection) -> None:
            conn.execute("""
                INSERT OR REPLACE INTO memory_engine_state (key, value, updated_at)
                VALUES (?, ?, ?)
            """, (key, value, now))
        
        self._database.locked(_set)
    
    def get_overview(self) -> tuple[int, int, int, int]:
        """获取记忆概览统计。
        
        Returns:
            (active_count, atom_count, archived_count, total_count)
        """
        def _overview(conn: sqlite3.Connection) -> tuple[int, int, int, int]:
            # 活跃记忆数
            cursor = conn.execute(
                "SELECT COUNT(*) FROM memories WHERE status = 'active'"
            )
            active = cursor.fetchone()[0]
            
            # Atom 总数
            cursor = conn.execute("SELECT COUNT(*) FROM memory_atoms")
            atoms = cursor.fetchone()[0]
            
            # 归档记忆数
            cursor = conn.execute(
                "SELECT COUNT(*) FROM memories WHERE status = 'archived'"
            )
            archived = cursor.fetchone()[0]
            
            # 总数
            cursor = conn.execute("SELECT COUNT(*) FROM memories")
            total = cursor.fetchone()[0]
            
            return (active, atoms, archived, total)
        
        return self._database.locked(_overview)
    
    def clear(self) -> None:
        """清空所有记忆数据。"""
        def _clear(conn: sqlite3.Connection) -> None:
            conn.execute("DELETE FROM memory_sources")
            conn.execute("DELETE FROM memory_atoms")
            conn.execute("DELETE FROM memories")
            conn.execute("DELETE FROM memory_engine_state")
            self._vector_cache.clear()
        
        self._database.locked(_clear)
