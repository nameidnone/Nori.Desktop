"""
Memory Algorithms - 记忆核心算法

包含：
- 向量相似度计算 (余弦相似度、点积)
- 时间衰减函数 (艾宾浩斯遗忘曲线、指数衰减)
- 文本处理 (TF-IDF、分词、特征提取)
"""

import math
import re
import time
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from collections import Counter


@dataclass
class VectorSimilarityResult:
    """向量相似度计算结果"""
    score: float
    method: str
    dimension: int
    computation_time_ms: float


class SimilarityCalculator:
    """
    向量相似度计算器
    
    支持多种相似度算法：
    - Cosine: 余弦相似度，最常用，范围 [-1, 1]
    - DotProduct: 点积，适用于归一化向量
    - Euclidean: 欧几里得距离转换的相似度
    - Manhattan: 曼哈顿距离转换的相似度
    """
    
    @staticmethod
    def cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
        """
        计算余弦相似度
        
        Args:
            vec_a: 向量 A
            vec_b: 向量 B
            
        Returns:
            相似度分数 [-1, 1]，1 表示完全相同
        """
        if len(vec_a) != len(vec_b):
            raise ValueError(f"向量维度不匹配：{len(vec_a)} vs {len(vec_b)}")
        
        if not vec_a:
            return 0.0
        
        dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
        norm_a = math.sqrt(sum(x * x for x in vec_a))
        norm_b = math.sqrt(sum(x * x for x in vec_b))
        
        if norm_a == 0 or norm_b == 0:
            return 0.0
        
        return dot_product / (norm_a * norm_b)
    
    @staticmethod
    def dot_product(vec_a: List[float], vec_b: List[float]) -> float:
        """计算点积相似度"""
        if len(vec_a) != len(vec_b):
            raise ValueError("向量维度不匹配")
        return sum(a * b for a, b in zip(vec_a, vec_b))
    
    @staticmethod
    def euclidean_similarity(vec_a: List[float], vec_b: List[float]) -> float:
        """
        基于欧几里得距离的相似度
        
        返回 [0, 1] 范围，1 表示完全相同
        """
        if len(vec_a) != len(vec_b):
            raise ValueError("向量维度不匹配")
        
        squared_diff = sum((a - b) ** 2 for a, b in zip(vec_a, vec_b))
        distance = math.sqrt(squared_diff)
        
        # 转换为相似度：1 / (1 + distance)
        return 1.0 / (1.0 + distance)
    
    @staticmethod
    def manhattan_similarity(vec_a: List[float], vec_b: List[float]) -> float:
        """
        基于曼哈顿距离的相似度
        
        返回 [0, 1] 范围，1 表示完全相同
        """
        if len(vec_a) != len(vec_b):
            raise ValueError("向量维度不匹配")
        
        distance = sum(abs(a - b) for a, b in zip(vec_a, vec_b))
        return 1.0 / (1.0 + distance)
    
    @classmethod
    def calculate(cls, vec_a: List[float], vec_b: List[float], 
                  method: str = "cosine") -> VectorSimilarityResult:
        """
        统一接口计算相似度
        
        Args:
            vec_a: 向量 A
            vec_b: 向量 B
            method: 算法名称 (cosine/dot/euclidean/manhattan)
            
        Returns:
            VectorSimilarityResult 包含分数和元数据
        """
        start_time = time.perf_counter()
        
        methods = {
            "cosine": cls.cosine_similarity,
            "dot": cls.dot_product,
            "euclidean": cls.euclidean_similarity,
            "manhattan": cls.manhattan_similarity,
        }
        
        if method not in methods:
            raise ValueError(f"未知的相似度方法：{method}")
        
        score = methods[method](vec_a, vec_b)
        
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        
        return VectorSimilarityResult(
            score=score,
            method=method,
            dimension=len(vec_a),
            computation_time_ms=elapsed_ms
        )


@dataclass
class DecayResult:
    """时间衰减计算结果"""
    original_strength: float
    decayed_strength: float
    decay_factor: float
    age_hours: float
    curve_type: str


class TimeDecay:
    """
    时间衰减计算器
    
    实现多种遗忘曲线模型：
    - Ebbinghaus: 艾宾浩斯遗忘曲线
    - Exponential: 指数衰减
    - Linear: 线性衰减
    - Logarithmic: 对数衰减
    """
    
    # 艾宾浩斯遗忘曲线关键时间点（小时）和保留率
    EBBINGHAUS_POINTS = {
        0: 1.0,      # 刚学习完
        0.33: 0.58,  # 20 分钟后
        1: 0.44,     # 1 小时后
        9: 0.36,     # 9 小时后
        24: 0.33,    # 1 天后
        48: 0.28,    # 2 天后
        144: 0.25,   # 6 天后
    }
    
    @staticmethod
    def ebbinghaus(hours_elapsed: float) -> float:
        """
        艾宾浩斯遗忘曲线
        
        基于实验数据的插值计算
        """
        if hours_elapsed <= 0:
            return 1.0
        
        # 找到相邻的关键点
        times = sorted(TimeDecay.EBBINGHAUS_POINTS.keys())
        
        if hours_elapsed >= times[-1]:
            return TimeDecay.EBBINGHAUS_POINTS[times[-1]]
        
        # 线性插值
        for i in range(len(times) - 1):
            t1, t2 = times[i], times[i + 1]
            if t1 <= hours_elapsed <= t2:
                v1 = TimeDecay.EBBINGHAUS_POINTS[t1]
                v2 = TimeDecay.EBBINGHAUS_POINTS[t2]
                ratio = (hours_elapsed - t1) / (t2 - t1)
                return v1 + ratio * (v2 - v1)
        
        return 0.25  # 默认最小值
    
    @staticmethod
    def exponential(hours_elapsed: float, half_life: float = 24.0) -> float:
        """
        指数衰减
        
        Args:
            hours_elapsed: 经过的小时数
            half_life: 半衰期（小时），默认 24 小时
        """
        if hours_elapsed <= 0:
            return 1.0
        
        return math.pow(0.5, hours_elapsed / half_life)
    
    @staticmethod
    def linear(hours_elapsed: float, total_decay_hours: float = 168.0) -> float:
        """
        线性衰减
        
        Args:
            hours_elapsed: 经过的小时数
            total_decay_hours: 完全衰减所需时间（小时），默认 7 天
        """
        if hours_elapsed <= 0:
            return 1.0
        
        if hours_elapsed >= total_decay_hours:
            return 0.0
        
        return 1.0 - (hours_elapsed / total_decay_hours)
    
    @staticmethod
    def logarithmic(hours_elapsed: float, scale: float = 24.0) -> float:
        """
        对数衰减
        
        初期衰减快，后期衰减慢
        """
        if hours_elapsed <= 0:
            return 1.0
        
        # log(1 + x) 保证 x=0 时为 0
        decay = math.log(1 + hours_elapsed / scale) / math.log(1 + 168.0 / scale)
        return max(0.0, 1.0 - decay)
    
    @classmethod
    def calculate(cls, original_strength: float, created_at: float,
                  current_time: Optional[float] = None,
                  curve_type: str = "ebbinghaus") -> DecayResult:
        """
        统一接口计算时间衰减
        
        Args:
            original_strength: 原始强度 [0, 1]
            created_at: 创建时间戳（秒）
            current_time: 当前时间戳（秒），默认使用 time.time()
            curve_type: 曲线类型 (ebbinghaus/exponential/linear/logarithmic)
            
        Returns:
            DecayResult 包含详细衰减信息
        """
        if current_time is None:
            current_time = time.time()
        
        hours_elapsed = (current_time - created_at) / 3600.0
        
        curves = {
            "ebbinghaus": cls.ebbinghaus,
            "exponential": cls.exponential,
            "linear": cls.linear,
            "logarithmic": cls.logarithmic,
        }
        
        if curve_type not in curves:
            raise ValueError(f"未知的衰减曲线类型：{curve_type}")
        
        decay_factor = curves[curve_type](hours_elapsed)
        decayed_strength = original_strength * decay_factor
        
        return DecayResult(
            original_strength=original_strength,
            decayed_strength=decayed_strength,
            decay_factor=decay_factor,
            age_hours=hours_elapsed,
            curve_type=curve_type
        )


@dataclass
class TextFeatures:
    """文本特征提取结果"""
    word_count: int
    char_count: int
    sentence_count: int
    unique_words: int
    tfidf_vector: Dict[str, float]
    keywords: List[Tuple[str, float]]


class TextProcessor:
    """
    文本处理器
    
    提供：
    - 文本清洗和标准化
    - 分词（支持中英文）
    - TF-IDF 特征提取
    - 关键词抽取
    """
    
    # 中文标点符号
    CHINESE_PUNCTUATION = "，。！？；：、""''（）《》【】…—·"
    # 英文标点符号
    ENGLISH_PUNCTUATION = ",.!?;:'\"()[]{}<>..."
    # 停用词表（简化版）
    STOP_WORDS = {
        "的", "了", "在", "是", "我", "有", "和", "就", "不", "人",
        "都", "一", "一个", "上", "也", "很", "到", "说", "要", "去",
        "你", "会", "着", "没有", "看", "好", "自己", "这",
        "the", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would",
        "could", "should", "may", "might", "must", "shall",
        "a", "an", "and", "or", "but", "if", "then", "else",
        "when", "at", "by", "for", "with", "about", "against",
        "between", "into", "through", "during", "before", "after",
        "above", "below", "to", "from", "up", "down", "in", "out",
        "on", "off", "over", "under", "again", "further",
    }
    
    def __init__(self, corpus: Optional[List[str]] = None):
        """
        初始化文本处理器
        
        Args:
            corpus: 可选的语料库，用于计算 IDF
        """
        self.document_frequency: Dict[str, int] = Counter()
        self.total_documents = 0
        
        if corpus:
            self.build_corpus(corpus)
    
    def build_corpus(self, documents: List[str]) -> None:
        """
        构建语料库索引
        
        Args:
            documents: 文档列表
        """
        self.document_frequency.clear()
        self.total_documents = len(documents)
        
        for doc in documents:
            words = set(self.tokenize(doc))
            for word in words:
                self.document_frequency[word] += 1
    
    def clean_text(self, text: str) -> str:
        """
        清洗文本
        
        - 移除多余空白
        - 标准化标点
        - 移除特殊字符
        """
        # 移除控制字符
        text = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', text)
        
        # 标准化空白
        text = re.sub(r'\s+', ' ', text).strip()
        
        # 移除 URL
        text = re.sub(r'http[s]?://\S+', '', text)
        
        # 移除 @提及
        text = re.sub(r'@\w+', '', text)
        
        # 移除 #标签（保留文字）
        text = re.sub(r'#(\w+)', r'\1', text)
        
        return text
    
    def tokenize(self, text: str) -> List[str]:
        """
        分词
        
        简单实现：
        - 英文：按空格和标点分割
        - 中文：按字符分割（可替换为 jieba）
        """
        text = self.clean_text(text).lower()
        
        # 检测是否主要为中文
        chinese_ratio = sum(1 for c in text if '\u4e00' <= c <= '\u9fff') / max(len(text), 1)
        
        if chinese_ratio > 0.5:
            # 中文分词：简单按字符分割，过滤标点和停用词
            words = []
            for char in text:
                if char not in self.CHINESE_PUNCTUATION and \
                   char not in self.ENGLISH_PUNCTUATION and \
                   char.strip() and \
                   char not in self.STOP_WORDS:
                    words.append(char)
            return words
        else:
            # 英文分词：按非字母数字字符分割
            words = re.findall(r'\b[a-z0-9]+\b', text)
            return [w for w in words if w not in self.STOP_WORDS]
    
    def compute_tf(self, tokens: List[str]) -> Dict[str, float]:
        """
        计算词频 (Term Frequency)
        
        TF(t) = t 在文档中出现的次数 / 文档总词数
        """
        if not tokens:
            return {}
        
        word_count = Counter(tokens)
        total_words = len(tokens)
        
        return {word: count / total_words for word, count in word_count.items()}
    
    def compute_idf(self, word: str) -> float:
        """
        计算逆文档频率 (Inverse Document Frequency)
        
        IDF(t) = log(总文档数 / 包含 t 的文档数)
        """
        if self.total_documents == 0:
            return 0.0
        
        df = self.document_frequency.get(word, 0)
        if df == 0:
            return 0.0
        
        return math.log(self.total_documents / df)
    
    def compute_tfidf(self, text: str) -> Dict[str, float]:
        """
        计算 TF-IDF 向量
        
        TF-IDF(t) = TF(t) * IDF(t)
        """
        tokens = self.tokenize(text)
        tf = self.compute_tf(tokens)
        
        tfidf = {}
        for word, tf_score in tf.items():
            idf_score = self.compute_idf(word)
            tfidf[word] = tf_score * idf_score
        
        return tfidf
    
    def extract_keywords(self, text: str, top_k: int = 10) -> List[Tuple[str, float]]:
        """
        提取关键词
        
        Args:
            text: 输入文本
            top_k: 返回前 K 个关键词
            
        Returns:
            [(keyword, score), ...] 按分数降序排列
        """
        tfidf = self.compute_tfidf(text)
        
        # 排序并取 top_k
        sorted_words = sorted(tfidf.items(), key=lambda x: x[1], reverse=True)
        return sorted_words[:top_k]
    
    def extract_features(self, text: str) -> TextFeatures:
        """
        提取完整文本特征
        
        Returns:
            TextFeatures 包含所有特征
        """
        cleaned = self.clean_text(text)
        tokens = self.tokenize(text)
        tfidf = self.compute_tfidf(text)
        keywords = self.extract_keywords(text)
        
        # 计算句子数（简单按标点分割）
        sentences = re.split(r'[.!?。！？]', text)
        sentences = [s for s in sentences if s.strip()]
        
        return TextFeatures(
            word_count=len(tokens),
            char_count=len(cleaned),
            sentence_count=len(sentences),
            unique_words=len(set(tokens)),
            tfidf_vector=tfidf,
            keywords=keywords
        )
    
    @staticmethod
    def similarity_by_tfidf(text_a: str, text_b: str, 
                            processor: Optional['TextProcessor'] = None) -> float:
        """
        基于 TF-IDF 的文本相似度
        
        使用余弦相似度计算两个 TF-IDF 向量的相似度
        """
        if processor is None:
            processor = TextProcessor([text_a, text_b])
        
        tfidf_a = processor.compute_tfidf(text_a)
        tfidf_b = processor.compute_tfidf(text_b)
        
        # 获取所有词汇
        all_words = set(tfidf_a.keys()) | set(tfidf_b.keys())
        
        if not all_words:
            return 0.0
        
        # 构建向量
        vec_a = [tfidf_a.get(w, 0.0) for w in all_words]
        vec_b = [tfidf_b.get(w, 0.0) for w in all_words]
        
        return SimilarityCalculator.cosine_similarity(vec_a, vec_b)
