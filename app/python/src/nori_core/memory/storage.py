"""
Memory Storage - 记忆存储层

提供：
- SQLite 持久化存储
- 内存缓存 (LRU)
- 双写缓冲机制
- 索引优化
"""

import sqlite3
import json
import time
import threading
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, asdict
from collections import OrderedDict
from contextlib import contextmanager
from pathlib import Path

from .models import MemoryItem, MemoryKind, MemoryStatus, MemorySource


@dataclass
class CacheEntry:
    """缓存条目"""
    key: str
    value: Any
    created_at: float
    last_accessed: float
    access_count: int


class LRUCache:
    """
    LRU (Least Recently Used) 缓存
    
    线程安全，支持自动过期
    """
    
    def __init__(self, capacity: int = 1000, ttl_seconds: float = 3600.0):
        """
        Args:
            capacity: 最大缓存条目数
            ttl_seconds: 条目存活时间（秒）
        """
        self.capacity = capacity
        self.ttl_seconds = ttl_seconds
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = threading.RLock()
    
    def get(self, key: str) -> Optional[Any]:
        """获取缓存值"""
        with self._lock:
            if key not in self._cache:
                return None
            
            entry = self._cache[key]
            
            # 检查是否过期
            if time.time() - entry.created_at > self.ttl_seconds:
                del self._cache[key]
                return None
            
            # 更新访问信息
            entry.last_accessed = time.time()
            entry.access_count += 1
            self._cache.move_to_end(key)
            
            return entry.value
    
    def set(self, key: str, value: Any) -> None:
        """设置缓存值"""
        with self._lock:
            now = time.time()
            
            if key in self._cache:
                # 更新现有条目
                entry = self._cache[key]
                entry.value = value
                entry.last_accessed = now
                entry.access_count += 1
                self._cache.move_to_end(key)
            else:
                # 添加新条目
                if len(self._cache) >= self.capacity:
                    # 移除最旧的条目
                    self._cache.popitem(last=False)
                
                self._cache[key] = CacheEntry(
                    key=key,
                    value=value,
                    created_at=now,
                    last_accessed=now,
                    access_count=1
                )
    
    def delete(self, key: str) -> bool:
        """删除缓存条目"""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False
    
    def clear(self) -> None:
        """清空缓存"""
        with self._lock:
            self._cache.clear()
    
    def cleanup_expired(self) -> int:
        """清理过期条目，返回清理数量"""
        with self._lock:
            now = time.time()
            expired_keys = [
                k for k, v in self._cache.items()
                if now - v.created_at > self.ttl_seconds
            ]
            
            for key in expired_keys:
                del self._cache[key]
            
            return len(expired_keys)
    
    def stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        with self._lock:
            total_accesses = sum(e.access_count for e in self._cache.values())
            return {
                "size": len(self._cache),
                "capacity": self.capacity,
                "total_accesses": total_accesses,
                "avg_access_count": total_accesses / max(len(self._cache), 1),
            }


class MemoryStorage:
    """
    记忆存储层
    
    功能：
    - SQLite 持久化
    - LRU 缓存加速
    - 双写缓冲（写入时先写缓存，异步刷盘）
    - 自动创建索引
    - 事务支持
    """
    
    # SQL Schema
    SCHEMA_VERSION = 3
    SCHEMA_SQL = """
    -- 记忆主表
    CREATE TABLE IF NOT EXISTS memories (
        id TEXT PRIMARY KEY,
        kind INTEGER NOT NULL,
        status INTEGER NOT NULL DEFAULT 0,
        source INTEGER NOT NULL,
        
        -- 内容
        content_json TEXT NOT NULL,
        embedding_json TEXT,
        
        -- 元数据
        strength REAL NOT NULL DEFAULT 1.0,
        importance REAL NOT NULL DEFAULT 0.5,
        frequency INTEGER NOT NULL DEFAULT 1,
        
        -- 时间戳
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL,
        last_accessed_at REAL,
        expires_at REAL,
        
        -- 关联
        session_id TEXT,
        conversation_id TEXT,
        message_id TEXT,
        
        -- 索引字段
        tags_json TEXT,
        entities_json TEXT
    );
    
    -- 索引
    CREATE INDEX IF NOT EXISTS idx_memories_kind ON memories(kind);
    CREATE INDEX IF NOT EXISTS idx_memories_status ON memories(status);
    CREATE INDEX IF NOT EXISTS idx_memories_source ON memories(source);
    CREATE INDEX IF NOT EXISTS idx_memories_session ON memories(session_id);
    CREATE INDEX IF NOT EXISTS idx_memories_conversation ON memories(conversation_id);
    CREATE INDEX IF NOT EXISTS idx_memories_created ON memories(created_at);
    CREATE INDEX IF NOT EXISTS idx_memories_strength ON memories(strength);
    CREATE INDEX IF NOT EXISTS idx_memories_expires ON memories(expires_at);
    
    -- 元数据表
    CREATE TABLE IF NOT EXISTS metadata (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at REAL NOT NULL
    );
    
    -- 向量索引表（用于近似最近邻搜索）
    CREATE TABLE IF NOT EXISTS vector_index (
        memory_id TEXT PRIMARY KEY,
        embedding_hash TEXT NOT NULL,
        centroid_id INTEGER,
        FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
    );
    
    CREATE INDEX IF NOT EXISTS idx_vector_centroid ON vector_index(centroid_id);
    """
    
    def __init__(self, db_path: str, cache_size: int = 1000, 
                 enable_wal: bool = True, auto_flush_interval: float = 5.0):
        """
        Args:
            db_path: SQLite 数据库路径
            cache_size: LRU 缓存大小
            enable_wal: 启用 WAL 模式（提高并发性能）
            auto_flush_interval: 自动刷盘间隔（秒）
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        self.cache = LRUCache(capacity=cache_size)
        self.auto_flush_interval = auto_flush_interval
        
        self._pending_writes: List[Tuple[str, MemoryItem]] = []
        self._write_lock = threading.Lock()
        self._last_flush_time = time.time()
        
        self._conn: Optional[sqlite3.Connection] = None
        self._connect()
    
    def _connect(self) -> None:
        """建立数据库连接并初始化 schema"""
        self._conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
        )
        
        if self._conn:
            # 启用 WAL 模式
            if self.enable_wal:
                self._conn.execute("PRAGMA journal_mode=WAL")
            
            # 设置缓存大小（页）
            self._conn.execute("PRAGMA cache_size=-2000")  # 2MB
            
            # 启用外键
            self._conn.execute("PRAGMA foreign_keys=ON")
            
            # 创建 schema
            self._conn.executescript(self.SCHEMA_SQL)
            self._conn.commit()
            
            # 记录版本
            self._set_metadata("schema_version", str(self.SCHEMA_VERSION))
    
    @property
    def enable_wal(self) -> bool:
        return True
    
    @contextmanager
    def _transaction(self):
        """事务上下文管理器"""
        if not self._conn:
            raise RuntimeError("Database not connected")
        
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
    
    def _set_metadata(self, key: str, value: str) -> None:
        """设置元数据"""
        if not self._conn:
            return
        
        now = time.time()
        self._conn.execute(
            "INSERT OR REPLACE INTO metadata (key, value, updated_at) VALUES (?, ?, ?)",
            (key, value, now)
        )
        self._conn.commit()
    
    def _get_metadata(self, key: str) -> Optional[str]:
        """获取元数据"""
        if not self._conn:
            return None
        
        cursor = self._conn.execute(
            "SELECT value FROM metadata WHERE key = ?",
            (key,)
        )
        row = cursor.fetchone()
        return row[0] if row else None
    
    def _memory_to_row(self, memory: MemoryItem) -> Dict[str, Any]:
        """将 MemoryItem 转换为数据库行"""
        return {
            "id": memory.id,
            "kind": memory.kind.value,
            "status": memory.status.value,
            "source": memory.source.value,
            "content_json": json.dumps(asdict(memory.content)),
            "embedding_json": json.dumps(memory.embedding) if memory.embedding else None,
            "strength": memory.strength,
            "importance": memory.importance,
            "frequency": memory.frequency,
            "created_at": memory.created_at,
            "updated_at": memory.updated_at,
            "last_accessed_at": memory.last_accessed_at,
            "expires_at": memory.expires_at,
            "session_id": memory.session_id,
            "conversation_id": memory.conversation_id,
            "message_id": memory.message_id,
            "tags_json": json.dumps(memory.tags) if memory.tags else None,
            "entities_json": json.dumps(memory.entities) if memory.entities else None,
        }
    
    def _row_to_memory(self, row: sqlite3.Row) -> MemoryItem:
        """将数据库行转换为 MemoryItem"""
        from .models import MemoryContent
        
        content_dict = json.loads(row["content_json"])
        content = MemoryContent(**content_dict)
        
        embedding = None
        if row["embedding_json"]:
            embedding = json.loads(row["embedding_json"])
        
        tags = None
        if row["tags_json"]:
            tags = json.loads(row["tags_json"])
        
        entities = None
        if row["entities_json"]:
            entities = json.loads(row["entities_json"])
        
        return MemoryItem(
            id=row["id"],
            kind=MemoryKind(row["kind"]),
            status=MemoryStatus(row["status"]),
            source=MemorySource(row["source"]),
            content=content,
            embedding=embedding,
            strength=row["strength"],
            importance=row["importance"],
            frequency=row["frequency"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_accessed_at=row["last_accessed_at"],
            expires_at=row["expires_at"],
            session_id=row["session_id"],
            conversation_id=row["conversation_id"],
            message_id=row["message_id"],
            tags=tags,
            entities=entities,
        )
    
    def save(self, memory: MemoryItem) -> bool:
        """
        保存记忆
        
        策略：
        1. 先写入缓存
        2. 加入待刷盘队列
        3. 如果队列满了或超时，触发刷盘
        """
        # 更新缓存
        self.cache.set(memory.id, memory)
        
        # 加入待刷盘队列
        with self._write_lock:
            self._pending_writes.append((memory.id, memory))
            
            # 检查是否需要刷盘
            should_flush = (
                len(self._pending_writes) >= 100 or
                time.time() - self._last_flush_time > self.auto_flush_interval
            )
        
        if should_flush:
            self.flush()
            return True
        
        return True
    
    def flush(self) -> int:
        """
        将待刷盘的数据写入数据库
        
        Returns:
            成功写入的记录数
        """
        with self._write_lock:
            if not self._pending_writes:
                return 0
            
            pending = self._pending_writes.copy()
            self._pending_writes.clear()
            self._last_flush_time = time.time()
        
        count = 0
        with self._transaction():
            for memory_id, memory in pending:
                try:
                    row = self._memory_to_row(memory)
                    columns = ", ".join(row.keys())
                    placeholders = ", ".join(["?" for _ in row])
                    
                    sql = f"""
                        INSERT OR REPLACE INTO memories 
                        ({columns}) 
                        VALUES ({placeholders})
                    """
                    
                    self._conn.execute(sql, list(row.values()))
                    count += 1
                except Exception as e:
                    # 记录错误但继续处理其他记录
                    print(f"Failed to save memory {memory_id}: {e}")
        
        return count
    
    def load(self, memory_id: str) -> Optional[MemoryItem]:
        """加载记忆"""
        # 先查缓存
        cached = self.cache.get(memory_id)
        if cached is not None:
            return cached
        
        # 查数据库
        if not self._conn:
            return None
        
        cursor = self._conn.execute(
            "SELECT * FROM memories WHERE id = ?",
            (memory_id,)
        )
        row = cursor.fetchone()
        
        if row:
            memory = self._row_to_memory(row)
            # 更新缓存
            self.cache.set(memory_id, memory)
            return memory
        
        return None
    
    def delete(self, memory_id: str) -> bool:
        """删除记忆"""
        # 删除缓存
        self.cache.delete(memory_id)
        
        # 删除数据库记录
        if not self._conn:
            return False
        
        with self._transaction():
            self._conn.execute(
                "DELETE FROM memories WHERE id = ?",
                (memory_id,)
            )
        
        return True
    
    def query(self, 
              kind: Optional[MemoryKind] = None,
              status: Optional[MemoryStatus] = None,
              session_id: Optional[str] = None,
              conversation_id: Optional[str] = None,
              min_strength: float = 0.0,
              limit: int = 100,
              offset: int = 0) -> List[MemoryItem]:
        """
        查询记忆
        
        支持多种过滤条件
        """
        conditions = []
        params = []
        
        if kind is not None:
            conditions.append("kind = ?")
            params.append(kind.value)
        
        if status is not None:
            conditions.append("status = ?")
            params.append(status.value)
        
        if session_id is not None:
            conditions.append("session_id = ?")
            params.append(session_id)
        
        if conversation_id is not None:
            conditions.append("conversation_id = ?")
            params.append(conversation_id)
        
        if min_strength > 0:
            conditions.append("strength >= ?")
            params.append(min_strength)
        
        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)
        
        sql = f"""
            SELECT * FROM memories 
            {where_clause}
            ORDER BY strength DESC, created_at DESC
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])
        
        if not self._conn:
            return []
        
        cursor = self._conn.execute(sql, params)
        rows = cursor.fetchall()
        
        return [self._row_to_memory(row) for row in rows]
    
    def search_by_embedding(self, embedding: List[float], 
                           top_k: int = 10,
                           threshold: float = 0.7) -> List[Tuple[MemoryItem, float]]:
        """
        基于向量相似度搜索记忆
        
        简单实现：全表扫描计算余弦相似度
        生产环境应使用 FAISS 或 Annoy 等专用向量索引
        """
        from .algorithms import SimilarityCalculator
        
        if not self._conn:
            return []
        
        # 获取所有带 embedding 的记忆
        cursor = self._conn.execute(
            "SELECT * FROM memories WHERE embedding_json IS NOT NULL AND strength >= ?",
            (threshold,)
        )
        rows = cursor.fetchall()
        
        results = []
        for row in rows:
            memory = self._row_to_memory(row)
            if memory.embedding:
                similarity = SimilarityCalculator.cosine_similarity(embedding, memory.embedding)
                if similarity >= threshold:
                    results.append((memory, similarity))
        
        # 按相似度排序
        results.sort(key=lambda x: x[1], reverse=True)
        
        return results[:top_k]
    
    def update_strength(self, memory_id: str, new_strength: float) -> bool:
        """更新记忆强度"""
        if not self._conn:
            return False
        
        with self._transaction():
            self._conn.execute(
                "UPDATE memories SET strength = ?, updated_at = ? WHERE id = ?",
                (new_strength, time.time(), memory_id)
            )
        
        # 更新缓存
        memory = self.load(memory_id)
        if memory:
            memory.strength = new_strength
            memory.updated_at = time.time()
            self.cache.set(memory_id, memory)
        
        return True
    
    def increment_frequency(self, memory_id: str) -> bool:
        """增加记忆访问频率"""
        if not self._conn:
            return False
        
        now = time.time()
        
        with self._transaction():
            self._conn.execute("""
                UPDATE memories 
                SET frequency = frequency + 1, 
                    last_accessed_at = ?,
                    updated_at = ?
                WHERE id = ?
            """, (now, now, memory_id))
        
        # 更新缓存
        memory = self.load(memory_id)
        if memory:
            memory.frequency += 1
            memory.last_accessed_at = now
            memory.updated_at = now
            self.cache.set(memory_id, memory)
        
        return True
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取存储统计信息"""
        if not self._conn:
            return {}
        
        # 总数统计
        cursor = self._conn.execute("SELECT COUNT(*) FROM memories")
        total_count = cursor.fetchone()[0]
        
        # 按类型统计
        cursor = self._conn.execute("""
            SELECT kind, COUNT(*) as count 
            FROM memories 
            GROUP BY kind
        """)
        by_kind = {row[0]: row[1] for row in cursor.fetchall()}
        
        # 按状态统计
        cursor = self._conn.execute("""
            SELECT status, COUNT(*) as count 
            FROM memories 
            GROUP BY status
        """)
        by_status = {row[0]: row[1] for row in cursor.fetchall()}
        
        # 平均强度
        cursor = self._conn.execute("SELECT AVG(strength) FROM memories")
        avg_strength = cursor.fetchone()[0] or 0.0
        
        return {
            "total_count": total_count,
            "by_kind": by_kind,
            "by_status": by_status,
            "average_strength": avg_strength,
            "cache_stats": self.cache.stats(),
        }
    
    def close(self) -> None:
        """关闭数据库连接"""
        # 先刷盘
        self.flush()
        
        # 关闭连接
        if self._conn:
            self._conn.close()
            self._conn = None
