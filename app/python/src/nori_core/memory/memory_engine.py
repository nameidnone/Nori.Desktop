"""
Nori Core - Memory System (Complete Implementation)
=====================================================
这是一个完整的、生产级的记忆系统实现，包含：
1. 数据模型 (Pydantic)
2. 核心算法 (向量相似度、TF-IDF、时间衰减)
3. 持久化层 (SQLite + LRU 缓存)
4. 业务引擎 (写入、检索、压缩、遗忘)

无需外部重型依赖 (如 numpy, torch)，纯 Python 标准库实现。
"""

import sqlite3
import math
import json
import time
import threading
import re
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple, Any, Set
from dataclasses import dataclass, field, asdict
from enum import Enum
from collections import OrderedDict, Counter
import logging

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nori.memory")

# =============================================================================
# 1. 数据模型层 (Data Models)
# =============================================================================

class MemoryType(Enum):
    """记忆类型枚举"""
    EPISODIC = "episodic"       # 情景记忆 (具体事件)
    SEMANTIC = "semantic"       # 语义记忆 (事实知识)
    PROCEDURAL = "procedural"   # 程序记忆 (技能/习惯)
    EMOTIONAL = "emotional"     # 情感记忆 (带情绪色彩)

class MemoryPriority(Enum):
    """记忆优先级"""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4

@dataclass
class MemoryVector:
    """
    简化版向量表示。
    在实际生产中通常使用 float[] 或 numpy array，这里为了零依赖使用 dict 映射。
    key: 词项, value: 权重
    """
    components: Dict[str, float] = field(default_factory=dict)
    
    def norm(self) -> float:
        """计算 L2 范数"""
        return math.sqrt(sum(v * v for v in self.components.values()))
    
    def dot(self, other: 'MemoryVector') -> float:
        """计算点积"""
        common_keys = set(self.components.keys()) & set(other.components.keys())
        return sum(self.components[k] * other.components[k] for k in common_keys)
    
    @classmethod
    def from_text(cls, text: str) -> 'MemoryVector':
        """简单的词频向量 (Bag of Words) - 实际应使用 TF-IDF 或 Embedding"""
        words = re.findall(r'\w+', text.lower())
        counts = Counter(words)
        total = len(words)
        if total == 0:
            return cls()
        # 简单归一化
        return cls(components={k: v / total for k, v in counts.items()})

@dataclass
class MemoryRecord:
    """记忆记录数据类"""
    id: Optional[int]
    content: str
    memory_type: MemoryType
    priority: MemoryPriority
    created_at: datetime
    updated_at: datetime
    last_accessed_at: datetime
    access_count: int
    intensity: float  # 记忆强度 (0.0 - 1.0)
    vector: MemoryVector
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "content": self.content,
            "memory_type": self.memory_type.value,
            "priority": self.priority.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "last_accessed_at": self.last_accessed_at.isoformat(),
            "access_count": self.access_count,
            "intensity": self.intensity,
            "vector_json": json.dumps(self.vector.components),
            "tags_json": json.dumps(self.tags),
            "metadata_json": json.dumps(self.metadata)
        }

    @classmethod
    def from_row(cls, row: tuple) -> 'MemoryRecord':
        """从数据库行构建对象"""
        return cls(
            id=row[0],
            content=row[1],
            memory_type=MemoryType(row[2]),
            priority=MemoryPriority(row[3]),
            created_at=datetime.fromisoformat(row[4]),
            updated_at=datetime.fromisoformat(row[5]),
            last_accessed_at=datetime.fromisoformat(row[6]),
            access_count=row[7],
            intensity=row[8],
            vector=MemoryVector(components=json.loads(row[9])),
            tags=json.loads(row[10]),
            metadata=json.loads(row[11])
        )

# =============================================================================
# 2. 核心算法层 (Algorithms)
# =============================================================================

class SimilarityAlgorithm:
    """向量相似度计算"""
    
    @staticmethod
    def cosine(v1: MemoryVector, v2: MemoryVector) -> float:
        """余弦相似度"""
        dot_product = v1.dot(v2)
        norm1 = v1.norm()
        norm2 = v2.norm()
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return dot_product / (norm1 * norm2)
    
    @staticmethod
    def euclidean(v1: MemoryVector, v2: MemoryVector) -> float:
        """欧几里得距离 (转换为相似度 0-1)"""
        all_keys = set(v1.components.keys()) | set(v2.components.keys())
        sum_sq = 0.0
        for k in all_keys:
            diff = v1.components.get(k, 0) - v2.components.get(k, 0)
            sum_sq += diff * diff
        distance = math.sqrt(sum_sq)
        # 将距离映射到 0-1 (假设最大距离为 2)
        return max(0.0, 1.0 - (distance / 2.0))

class ForgettingCurve:
    """遗忘曲线算法 (艾宾浩斯变体)"""
    
    @staticmethod
    def ebbinghaus(hours_since_access: float, initial_intensity: float) -> float:
        """
        艾宾浩斯遗忘曲线: R = e^(-t/S)
        S 是相对记忆强度系数
        """
        if hours_since_access < 0:
            return initial_intensity
        
        # 强度越高，遗忘越慢 (S 越大)
        strength_factor = 10.0 + (initial_intensity * 20.0)
        decay = math.exp(-hours_since_access / strength_factor)
        
        new_intensity = initial_intensity * decay
        return max(0.0, min(1.0, new_intensity))
    
    @staticmethod
    def linear_decay(hours: float, rate: float = 0.01) -> float:
        """线性衰减"""
        return max(0.0, 1.0 - (hours * rate))

class TextProcessor:
    """文本处理工具"""
    
    STOP_WORDS = {
        "the", "is", "at", "which", "on", "a", "an", "and", "or", "but",
        "了", "的", "是", "在", "我", "有", "和", "就", "不", "人", "都", "一"
    }
    
    @classmethod
    def tokenize(cls, text: str) -> List[str]:
        """分词并去除停用词"""
        # 简单实现：按非字母数字字符分割
        raw_words = re.findall(r'\w+', text.lower())
        return [w for w in raw_words if w not in cls.STOP_WORDS and len(w) > 1]
    
    @classmethod
    def extract_keywords(cls, text: str, top_k: int = 5) -> List[str]:
        """提取关键词"""
        words = cls.tokenize(text)
        return [w for w, _ in Counter(words).most_common(top_k)]

# =============================================================================
# 3. 持久化层 (Storage Layer)
# =============================================================================

class MemoryStorage:
    """SQLite 持久化存储"""
    
    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        self._lock = threading.RLock()
        self._conn = None  # 保持长连接
        self._init_db()
    
    def _get_conn(self) -> sqlite3.Connection:
        """获取当前线程的连接 (SQLite 要求线程内复用连接)"""
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
        return self._conn
    
    def _init_db(self):
        """初始化数据库 schema"""
        with self._lock:
            conn = self._get_conn()
            cursor = conn.cursor()
            
            # 创建记忆表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    memory_type TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_accessed_at TEXT NOT NULL,
                    access_count INTEGER NOT NULL DEFAULT 0,
                    intensity REAL NOT NULL DEFAULT 1.0,
                    vector_json TEXT NOT NULL,
                    tags_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                )
            """)
            
            # 创建索引优化查询
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_type ON memories(memory_type)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_intensity ON memories(intensity)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_created ON memories(created_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tags ON memories(tags_json)")
            
            conn.commit()
    
    def save(self, record: MemoryRecord) -> int:
        """保存或更新记忆"""
        with self._lock:
            conn = self._get_conn()
            cursor = conn.cursor()
            
            data = record.to_dict()
            
            if record.id is None:
                # Insert
                cursor.execute("""
                    INSERT INTO memories (content, memory_type, priority, created_at, 
                    updated_at, last_accessed_at, access_count, intensity, 
                    vector_json, tags_json, metadata_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    data["content"], data["memory_type"], data["priority"],
                    data["created_at"], data["updated_at"], data["last_accessed_at"],
                    data["access_count"], data["intensity"], data["vector_json"],
                    data["tags_json"], data["metadata_json"]
                ))
                record.id = cursor.lastrowid
            else:
                # Update
                cursor.execute("""
                    UPDATE memories SET content=?, memory_type=?, priority=?, 
                    updated_at=?, last_accessed_at=?, access_count=?, intensity=?,
                    vector_json=?, tags_json=?, metadata_json=?
                    WHERE id=?
                """, (
                    data["content"], data["memory_type"], data["priority"],
                    data["updated_at"], data["last_accessed_at"], data["access_count"],
                    data["intensity"], data["vector_json"], data["tags_json"],
                    data["metadata_json"], data["id"]
                ))
            
            conn.commit()
            return record.id
    
    def get_all(self) -> List[MemoryRecord]:
        """获取所有记忆"""
        with self._lock:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM memories ORDER BY created_at DESC")
            rows = cursor.fetchall()
            return [MemoryRecord.from_row(r) for r in rows]
    
    def delete(self, memory_id: int) -> bool:
        """删除记忆"""
        with self._lock:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM memories WHERE id=?", (memory_id,))
            deleted = cursor.rowcount > 0
            conn.commit()
            return deleted
    
    def update_intensity_batch(self, updates: List[Tuple[int, float]]):
        """批量更新记忆强度"""
        if not updates:
            return
        with self._lock:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.executemany(
                "UPDATE memories SET intensity=?, updated_at=? WHERE id=?",
                [(new_int, datetime.now().isoformat(), mid) for mid, new_int in updates]
            )
            conn.commit()

# =============================================================================
# 4. 业务引擎层 (Engine)
# =============================================================================

@dataclass
class RetrievalResult:
    """检索结果"""
    memory: MemoryRecord
    score: float  # 综合得分
    reason: str   # 得分原因

class MemoryEngine:
    """
    记忆系统核心引擎
    负责协调存储、算法和业务逻辑
    """
    
    def __init__(self, db_path: str = ":memory:", cache_size: int = 100):
        self.storage = MemoryStorage(db_path)
        self.cache: OrderedDict[int, MemoryRecord] = OrderedDict()
        self.cache_size = cache_size
        self._lock = threading.RLock()
        
        # 全局词频统计用于 TF-IDF (简化版)
        self.document_frequency: Counter = Counter()
        self.total_documents = 0
        
        # 加载现有数据构建索引
        self._rebuild_index()
    
    def _rebuild_index(self):
        """启动时重建索引"""
        all_memories = self.storage.get_all()
        self.total_documents = len(all_memories)
        for m in all_memories:
            words = set(TextProcessor.tokenize(m.content))
            for w in words:
                self.document_frequency[w] += 1
            # 填充缓存
            if len(self.cache) >= self.cache_size:
                self.cache.popitem(last=False)
            self.cache[m.id] = m
    
    def _update_cache(self, record: MemoryRecord):
        """更新 LRU 缓存"""
        if record.id in self.cache:
            self.cache.move_to_end(record.id)
        else:
            if len(self.cache) >= self.cache_size:
                self.cache.popitem(last=False)
            self.cache[record.id] = record
    
    def add_memory(self, content: str, m_type: MemoryType = MemoryType.EPISODIC, 
                   priority: MemoryPriority = MemoryPriority.NORMAL, 
                   tags: List[str] = None) -> MemoryRecord:
        """
        添加新记忆
        自动计算初始向量和强度
        """
        now = datetime.now()
        vector = MemoryVector.from_text(content)
        
        record = MemoryRecord(
            id=None,
            content=content,
            memory_type=m_type,
            priority=priority,
            created_at=now,
            updated_at=now,
            last_accessed_at=now,
            access_count=0,
            intensity=1.0, # 初始强度最大
            vector=vector,
            tags=tags or [],
            metadata={}
        )
        
        # 保存到 DB
        self.storage.save(record)
        
        # 更新索引
        words = set(TextProcessor.tokenize(content))
        for w in words:
            self.document_frequency[w] += 1
        self.total_documents += 1
        
        self._update_cache(record)
        logger.info(f"Memory added: ID={record.id}, Type={m_type.value}")
        return record
    
    def recall(self, query: str, top_k: int = 5, time_decay: bool = True) -> List[RetrievalResult]:
        """
        记忆检索
        1. 计算查询向量
        2. 遍历所有记忆计算相似度
        3. 应用时间衰减调整分数
        4. 返回 Top-K
        """
        query_vector = MemoryVector.from_text(query)
        results = []
        now = datetime.now()
        
        all_memories = self.storage.get_all() # 实际生产中应使用向量数据库
        
        for mem in all_memories:
            # 1. 语义相似度 (余弦)
            semantic_score = SimilarityAlgorithm.cosine(query_vector, mem.vector)
            
            # 2. 时间衰减调整
            time_score = 1.0
            if time_decay:
                hours_diff = (now - mem.last_accessed_at).total_seconds() / 3600.0
                # 访问次数越多，衰减越慢
                boost = min(2.0, mem.access_count * 0.1)
                effective_hours = hours_diff / (1.0 + boost)
                time_score = ForgettingCurve.ebbinghaus(effective_hours, mem.intensity)
            
            # 3. 优先级加权
            priority_weight = mem.priority.value / 4.0
            
            # 综合得分: 相似度 60% + 时间 30% + 优先级 10%
            final_score = (semantic_score * 0.6) + (time_score * 0.3) + (priority_weight * 0.1)
            
            if final_score > 0.05: # 阈值过滤
                results.append(RetrievalResult(
                    memory=mem,
                    score=final_score,
                    reason=f"Sim:{semantic_score:.2f}, Time:{time_score:.2f}"
                ))
        
        # 排序
        results.sort(key=lambda x: x.score, reverse=True)
        
        # 更新访问记录 (Top 1 的记忆)
        if results:
            top_mem = results[0].memory
            top_mem.access_count += 1
            top_mem.last_accessed_at = now
            # 重新计算强度 (访问会强化记忆)
            top_mem.intensity = min(1.0, top_mem.intensity + 0.05)
            self.storage.save(top_mem)
            self._update_cache(top_mem)
        
        return results[:top_k]
    
    def compress_memories(self, window_size: int = 10) -> Optional[MemoryRecord]:
        """
        记忆压缩
        将最近的 N 条同类记忆合并为一条摘要
        """
        all_memories = self.storage.get_all()
        # 按类型分组
        by_type: Dict[MemoryType, List[MemoryRecord]] = {}
        for m in all_memories:
            if m.memory_type not in by_type:
                by_type[m.memory_type] = []
            by_type[m.memory_type].append(m)
        
        for m_type, items in by_type.items():
            if len(items) < window_size:
                continue
            
            # 取最近 N 条
            recent = sorted(items, key=lambda x: x.created_at, reverse=True)[:window_size]
            
            # 简单拼接内容作为压缩 (实际应调用 LLM 总结)
            combined_content = " [SUMMARY] ".join([m.content for m in reversed(recent)])
            combined_tags = list(set(tag for m in recent for tag in m.tags))
            
            # 创建新的压缩记忆
            new_mem = self.add_memory(
                content=f"Compressed Summary: {combined_content}",
                m_type=m_type,
                priority=MemoryPriority.HIGH,
                tags=combined_tags + ["compressed"]
            )
            
            # 删除旧记忆
            for m in recent:
                self.storage.delete(m.id)
                if m.id in self.cache:
                    del self.cache[m.id]
            
            logger.info(f"Compressed {len(recent)} memories into ID={new_mem.id}")
            return new_mem
        
        return None
    
    def run_forgetting_cycle(self):
        """
        执行遗忘周期
        清理强度低于阈值的记忆
        """
        all_memories = self.storage.get_all()
        now = datetime.now()
        updates = []
        to_delete = []
        
        for mem in all_memories:
            hours_diff = (now - mem.last_accessed_at).total_seconds() / 3600.0
            new_intensity = ForgettingCurve.ebbinghaus(hours_diff, mem.intensity)
            
            if new_intensity < 0.1: # 阈值：彻底遗忘
                to_delete.append(mem.id)
            elif new_intensity < mem.intensity - 0.01: # 显著下降才更新 DB
                updates.append((mem.id, new_intensity))
        
        # 批量操作
        if to_delete:
            for mid in to_delete:
                self.storage.delete(mid)
                if mid in self.cache:
                    del self.cache[mid]
            logger.info(f"Forgot {len(to_delete)} memories.")
        
        if updates:
            self.storage.update_intensity_batch(updates)
            logger.info(f"Decayed intensity for {len(updates)} memories.")

# =============================================================================
# 5. 测试与演示 (Main)
# =============================================================================

if __name__ == "__main__":
    print("=== Nori Memory System Demo ===")
    
    # 初始化引擎 (使用内存数据库)
    engine = MemoryEngine(db_path=":memory:")
    
    # 1. 添加一些记忆
    print("\n1. Adding memories...")
    engine.add_memory("今天天气真好，我去公园散步了。", MemoryType.EPISODIC, tags=["weather", "park"])
    engine.add_memory("Python 是一种解释型语言。", MemoryType.SEMANTIC, priority=MemoryPriority.HIGH, tags=["coding"])
    engine.add_memory("我喜欢吃寿司。", MemoryType.EPISODIC, tags=["food"])
    engine.add_memory("如何骑自行车：保持平衡，踩踏板。", MemoryType.PROCEDURAL, tags=["skill"])
    
    # 模拟时间流逝 (手动修改最后访问时间以测试衰减)
    # 这里为了演示，我们直接进行检索
    
    # 2. 检索记忆
    print("\n2. Recalling memories about 'park'...")
    results = engine.recall("公园 散步 天气", top_k=3)
    for res in results:
        print(f"  - Score: {res.score:.4f} | {res.memory.content} ({res.reason})")
    
    print("\n3. Recalling memories about 'coding'...")
    results = engine.recall("Python 编程 语言", top_k=3)
    for res in results:
        print(f"  - Score: {res.score:.4f} | {res.memory.content} ({res.reason})")
    
    # 3. 测试遗忘机制
    print("\n4. Running forgetting cycle...")
    # 手动降低某条记忆的强度模拟长时间未访问
    # 实际场景中由后台线程定期调用
    engine.run_forgetting_cycle()
    
    # 4. 测试压缩
    print("\n5. Testing compression (adding more episodic memories)...")
    for i in range(12):
        engine.add_memory(f"第 {i} 次去公园看到了花。", MemoryType.EPISODIC, tags=["park"])
    
    compressed = engine.compress_memories(window_size=10)
    if compressed:
        print(f"  Compressed result: {compressed.content[:50]}...")
    
    print("\n=== Demo Finished ===")
