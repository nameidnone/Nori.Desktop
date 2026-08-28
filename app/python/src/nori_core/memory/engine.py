"""
Memory Engine - 记忆引擎核心

提供：
- 记忆写入策略（强度计算、去重）
- 智能检索（多路召回、融合排序）
- 记忆压缩（滑动窗口、聚类合并）
- 遗忘机制（定期清理低强度记忆）
- 上下文构建（动态 Top-K 相关记忆）
"""

import time
import uuid
import threading
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass
from collections import defaultdict

from .models import (
    MemoryItem, MemoryKind, MemoryStatus, MemorySource,
    MemoryContent, MemoryContext, RetrievedKnowledge
)
from .storage import MemoryStorage
from .algorithms import SimilarityCalculator, TimeDecay, TextProcessor


@dataclass
class WriteResult:
    """记忆写入结果"""
    success: bool
    memory_id: str
    is_new: bool
    merged_with: Optional[str] = None
    strength_delta: float = 0.0


@dataclass
class RetrievalResult:
    """检索结果"""
    memories: List[RetrievedKnowledge]
    total_found: int
    query_time_ms: float
    debug_info: Optional[Dict[str, Any]] = None


@dataclass
class CompressionReport:
    """压缩报告"""
    original_count: int
    compressed_count: int
    compression_ratio: float
    merged_pairs: int
    discarded_count: int


class MemoryEngine:
    """
    记忆引擎
    
    核心功能：
    1. 记忆写入：强度计算、去重、合并
    2. 智能检索：多路召回、融合排序
    3. 记忆压缩：滑动窗口、聚类合并
    4. 遗忘机制：定期清理
    5. 上下文构建：动态 Top-K
    """
    
    def __init__(self, storage: MemoryStorage,
                 default_strength: float = 0.8,
                 decay_curve: str = "ebbinghaus",
                 enable_compression: bool = True,
                 compression_threshold: int = 100):
        """
        Args:
            storage: 存储层实例
            default_strength: 默认初始强度
            decay_curve: 时间衰减曲线类型
            enable_compression: 启用记忆压缩
            compression_threshold: 触发压缩的记忆数量阈值
        """
        self.storage = storage
        self.default_strength = default_strength
        self.decay_curve = decay_curve
        self.enable_compression = enable_compression
        self.compression_threshold = compression_threshold
        
        self.text_processor = TextProcessor()
        self._write_lock = threading.Lock()
        self._compression_lock = threading.Lock()
        
        # 统计信息
        self._stats = {
            "total_writes": 0,
            "total_reads": 0,
            "total_deletions": 0,
            "compressions_run": 0,
        }
    
    def write(self, content: str, kind: MemoryKind = MemoryKind.CONVERSATIONAL,
              source: MemorySource = MemorySource.CHAT,
              session_id: Optional[str] = None,
              conversation_id: Optional[str] = None,
              message_id: Optional[str] = None,
              tags: Optional[List[str]] = None,
              entities: Optional[List[str]] = None,
              importance: float = 0.5,
              embedding: Optional[List[float]] = None) -> WriteResult:
        """
        写入一条新记忆
        
        流程：
        1. 检查是否重复
        2. 计算初始强度
        3. 创建记忆对象
        4. 保存到存储层
        5. 触发压缩检查
        """
        with self._write_lock:
            now = time.time()
            
            # 生成 ID
            memory_id = str(uuid.uuid4())
            
            # 检查重复（基于内容相似度）
            existing = self._find_similar(content, threshold=0.95)
            if existing:
                # 找到重复，更新现有记忆
                existing_mem = self.storage.load(existing.id)
                if existing_mem:
                    # 增加强度和频率
                    new_strength = min(1.0, existing_mem.strength + 0.1)
                    self.storage.update_strength(existing.id, new_strength)
                    self.storage.increment_frequency(existing.id)
                    
                    return WriteResult(
                        success=True,
                        memory_id=existing.id,
                        is_new=False,
                        merged_with=existing.id,
                        strength_delta=new_strength - existing_mem.strength
                    )
            
            # 创建记忆内容
            memory_content = MemoryContent(
                text=content,
                metadata={}
            )
            
            # 计算初始强度（考虑重要性）
            initial_strength = self.default_strength * (0.5 + importance)
            
            # 创建记忆对象
            memory = MemoryItem(
                id=memory_id,
                kind=kind,
                status=MemoryStatus.Active,
                source=source,
                content=memory_content,
                embedding=embedding,
                strength=initial_strength,
                importance=importance,
                frequency=1,
                created_at=now,
                updated_at=now,
                last_accessed_at=None,
                expires_at=None,
                session_id=session_id,
                conversation_id=conversation_id,
                message_id=message_id,
                tags=tags,
                entities=entities,
            )
            
            # 保存
            self.storage.save(memory)
            self._stats["total_writes"] += 1
            
            # 检查是否需要压缩
            if self.enable_compression:
                stats = self.storage.get_statistics()
                if stats.get("total_count", 0) >= self.compression_threshold:
                    self._trigger_compression()
            
            return WriteResult(
                success=True,
                memory_id=memory_id,
                is_new=True,
                strength_delta=initial_strength
            )
    
    def retrieve(self, query: str, top_k: int = 10,
                 kind_filter: Optional[List[MemoryKind]] = None,
                 min_strength: float = 0.3,
                 include_debug: bool = False) -> RetrievalResult:
        """
        检索相关记忆
        
        策略：
        1. 文本相似度召回（TF-IDF）
        2. 向量相似度召回（如果有 embedding）
        3. 元数据过滤
        4. 时间衰减调整
        5. 融合排序
        """
        start_time = time.perf_counter()
        
        all_candidates: Dict[str, Tuple[MemoryItem, float]] = {}
        debug_info: Dict[str, Any] = {} if include_debug else None
        
        # 1. 文本相似度召回
        text_results = self._retrieve_by_text(query, top_k * 2)
        for mem, score in text_results:
            if mem.id not in all_candidates:
                all_candidates[mem.id] = (mem, score)
            else:
                # 融合分数
                _, old_score = all_candidates[mem.id]
                all_candidates[mem.id] = (mem, (old_score + score) / 2)
        
        if include_debug and debug_info is not None:
            debug_info["text_recall_count"] = len(text_results)
        
        # 2. 向量相似度召回（如果有 query embedding）
        # 这里简化处理，实际应该有专门的 embedding 模型
        
        # 3. 应用过滤器
        filtered = []
        for mem_id, (mem, score) in all_candidates.items():
            # 强度过滤
            if mem.strength < min_strength:
                continue
            
            # 类型过滤
            if kind_filter and mem.kind not in kind_filter:
                continue
            
            # 状态过滤
            if mem.status != MemoryStatus.Active:
                continue
            
            # 应用时间衰减
            decay_result = TimeDecay.calculate(
                original_strength=score,
                created_at=mem.created_at,
                curve_type=self.decay_curve
            )
            
            # 考虑频率加成
            frequency_bonus = min(0.3, mem.frequency * 0.05)
            final_score = min(1.0, decay_result.decayed_strength + frequency_bonus)
            
            filtered.append((mem, final_score))
        
        if include_debug and debug_info is not None:
            debug_info["filtered_count"] = len(filtered)
        
        # 4. 排序并取 top_k
        filtered.sort(key=lambda x: x[1], reverse=True)
        top_results = filtered[:top_k]
        
        # 5. 转换为 RetrievedKnowledge
        knowledge_list = []
        for mem, score in top_results:
            # 增加访问频率
            self.storage.increment_frequency(mem.id)
            
            knowledge = RetrievedKnowledge(
                memory_id=mem.id,
                content=mem.content,
                relevance_score=score,
                kind=mem.kind,
                created_at=mem.created_at,
                accessed_at=time.time()
            )
            knowledge_list.append(knowledge)
        
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        self._stats["total_reads"] += 1
        
        return RetrievalResult(
            memories=knowledge_list,
            total_found=len(knowledge_list),
            query_time_ms=elapsed_ms,
            debug_info=debug_info
        )
    
    def build_context(self, query: str, max_tokens: int = 2000,
                      top_k: int = 5) -> MemoryContext:
        """
        构建对话上下文
        
        自动检索相关记忆并格式化为上下文
        """
        result = self.retrieve(query, top_k=top_k)
        
        # 估算 token 数（简单按字符数/4 计算）
        total_tokens = 0
        selected_memories = []
        
        for knowledge in result.memories:
            # 估算这条记忆的 token 数
            text_len = len(knowledge.content.text)
            tokens = text_len // 4
            
            if total_tokens + tokens <= max_tokens:
                selected_memories.append(knowledge)
                total_tokens += tokens
        
        return MemoryContext(
            memories=selected_memories,
            total_tokens=total_tokens,
            generated_at=time.time()
        )
    
    def compress(self, strategy: str = "sliding_window") -> CompressionReport:
        """
        执行记忆压缩
        
        策略：
        - sliding_window: 滑动窗口合并相邻记忆
        - clustering: 聚类合并相似记忆
        - summary: 生成摘要替换原始记忆
        """
        with self._compression_lock:
            start_time = time.time()
            
            if strategy == "sliding_window":
                return self._compress_sliding_window()
            elif strategy == "clustering":
                return self._compress_clustering()
            else:
                raise ValueError(f"未知的压缩策略：{strategy}")
    
    def _compress_sliding_window(self) -> CompressionReport:
        """滑动窗口压缩"""
        # 获取所有会话记忆
        stats = self.storage.get_statistics()
        original_count = stats.get("total_count", 0)
        
        if original_count < 10:
            return CompressionReport(
                original_count=original_count,
                compressed_count=original_count,
                compression_ratio=1.0,
                merged_pairs=0,
                discarded_count=0
            )
        
        # 按会话分组
        sessions: Dict[str, List[MemoryItem]] = defaultdict(list)
        
        # 简化处理：查询所有记忆
        all_memories = self.storage.query(limit=1000)
        
        for mem in all_memories:
            if mem.conversation_id:
                sessions[mem.conversation_id].append(mem)
        
        merged_pairs = 0
        discarded_count = 0
        
        for session_id, memories in sessions.items():
            if len(memories) < 3:
                continue
            
            # 按时间排序
            memories.sort(key=lambda m: m.created_at)
            
            # 滑动窗口合并（每 3 条合并为 1 条）
            i = 0
            while i < len(memories) - 2:
                window = memories[i:i+3]
                
                # 检查是否可以合并（时间接近、类型相同）
                time_span = window[-1].created_at - window[0].created_at
                if time_span < 3600:  # 1 小时内
                    same_kind = all(m.kind == window[0].kind for m in window)
                    
                    if same_kind:
                        # 合并内容
                        combined_text = " ".join(m.content.text for m in window)
                        
                        # 创建新的合并记忆
                        self.write(
                            content=combined_text,
                            kind=window[0].kind,
                            source=window[0].source,
                            conversation_id=session_id,
                            importance=max(m.importance for m in window),
                        )
                        
                        # 删除原始记忆
                        for mem in window:
                            self.storage.delete(mem.id)
                            discarded_count += 1
                        
                        merged_pairs += 1
                        i += 3
                        continue
                
                i += 1
        
        new_count = original_count - discarded_count + merged_pairs
        
        return CompressionReport(
            original_count=original_count,
            compressed_count=new_count,
            compression_ratio=new_count / max(original_count, 1),
            merged_pairs=merged_pairs,
            discarded_count=discarded_count
        )
    
    def _compress_clustering(self) -> CompressionReport:
        """聚类压缩（简化版）"""
        # TODO: 实现基于向量聚类的压缩
        return CompressionReport(
            original_count=0,
            compressed_count=0,
            compression_ratio=1.0,
            merged_pairs=0,
            discarded_count=0
        )
    
    def forget(self, threshold: float = 0.1, dry_run: bool = False) -> int:
        """
        执行遗忘机制
        
        删除强度低于阈值的陈旧记忆
        """
        # 查询所有低强度记忆
        weak_memories = self.storage.query(min_strength=0.0, limit=1000)
        
        to_delete = []
        for mem in weak_memories:
            # 计算当前强度（考虑时间衰减）
            decay = TimeDecay.calculate(
                original_strength=mem.strength,
                created_at=mem.created_at,
                curve_type=self.decay_curve
            )
            
            if decay.decayed_strength < threshold:
                to_delete.append(mem.id)
        
        if dry_run:
            return len(to_delete)
        
        # 执行删除
        for memory_id in to_delete:
            self.storage.delete(memory_id)
        
        self._stats["total_deletions"] += len(to_delete)
        
        return len(to_delete)
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取引擎统计信息"""
        storage_stats = self.storage.get_statistics()
        
        return {
            **self._stats,
            "storage": storage_stats,
            "config": {
                "default_strength": self.default_strength,
                "decay_curve": self.decay_curve,
                "compression_enabled": self.enable_compression,
                "compression_threshold": self.compression_threshold,
            }
        }
    
    def _find_similar(self, content: str, threshold: float = 0.9) -> Optional[MemoryItem]:
        """查找相似记忆"""
        # 使用 TF-IDF 相似度
        all_memories = self.storage.query(limit=100, min_strength=0.5)
        
        for mem in all_memories:
            similarity = TextProcessor.similarity_by_tfidf(
                content, mem.content.text, self.text_processor
            )
            
            if similarity >= threshold:
                return mem
        
        return None
    
    def _retrieve_by_text(self, query: str, top_k: int) -> List[Tuple[MemoryItem, float]]:
        """基于文本相似度检索"""
        all_memories = self.storage.query(limit=200, min_strength=0.3)
        
        results = []
        for mem in all_memories:
            similarity = TextProcessor.similarity_by_tfidf(
                query, mem.content.text, self.text_processor
            )
            
            if similarity > 0.1:  # 最低相似度阈值
                results.append((mem, similarity))
        
        # 排序
        results.sort(key=lambda x: x[1], reverse=True)
        
        return results[:top_k]
    
    def _trigger_compression(self) -> None:
        """触发压缩（异步）"""
        # 简化实现：直接同步执行
        try:
            self.compress()
            self._stats["compressions_run"] += 1
        except Exception as e:
            print(f"Compression failed: {e}")
    
    def close(self) -> None:
        """关闭引擎"""
        self.storage.close()
