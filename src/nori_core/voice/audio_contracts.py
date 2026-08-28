"""音频数据契约与工具类

对应 C# AudioContracts.cs，提供音频限制、编码音频、录音数据结构、
MIME 验证、句子分块和 LRU 缓存功能。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Final


@dataclass(frozen=True)
class VoiceAudioLimits:
    """语音请求和媒体交换共用的音频大小上限"""
    
    # 单段音频、录音上传和 TTS 响应的最大字节数 (32 MiB)
    MaxBytes: Final[int] = 32 * 1024 * 1024
    
    # 合成队列最多预取的音频段数
    SynthesisQueueCapacity: Final[int] = 2
    
    # 合成缓存最多保存的条目数
    CacheItemLimit: Final[int] = 16


@dataclass(frozen=True)
class EncodedAudio:
    """已编码的音频数据
    
    MIME 是数据的一部分，不能在送入播放端时再猜测。
    """
    bytes: bytes
    mime: str
    
    @property
    def length(self) -> int:
        """音频字节数"""
        return len(self.bytes)


@dataclass(frozen=True)
class RecordedAudio:
    """MediaRecorder 产生的原始录音及其格式信息"""
    bytes: bytes
    mime: str
    file_name: str
    
    @property
    def length(self) -> int:
        """录音字节数"""
        return len(self.bytes)


class AudioMime:
    """音频 MIME 校验与录音文件名辅助"""
    
    SUPPORTED_TYPES: Final[frozenset[str]] = frozenset({
        "audio/aac",
        "audio/flac",
        "audio/mp4",
        "audio/mpeg",
        "audio/mp3",
        "audio/ogg",
        "audio/opus",
        "audio/wav",
        "audio/wave",
        "audio/webm",
        "audio/x-wav",
    })
    
    @classmethod
    def validate(cls, mime: str | None) -> str:
        """校验并规范 MIME 的主类型，同时保留 codecs 等参数
        
        Args:
            mime: MIME 类型字符串
            
        Returns:
            规范化后的 MIME 类型
            
        Raises:
            ValueError: 当 MIME 类型不支持或为空时
        """
        if not mime or not mime.strip():
            raise ValueError("音频 MIME 类型不能为空")
        
        value = mime.strip()
        separator = value.find(';')
        media_type = value[:separator].strip() if separator >= 0 else value.strip()
        
        if '/' not in media_type or media_type.lower() not in cls.SUPPORTED_TYPES:
            raise ValueError(f"不支持的音频 MIME 类型：{mime}")
        
        parameters = value[separator:].strip() if separator >= 0 else ""
        return media_type.lower() + parameters
    
    @classmethod
    def is_supported(cls, mime: str | None) -> bool:
        """判断 MIME 是否是受支持的音频类型"""
        try:
            cls.validate(mime)
            return True
        except ValueError:
            return False
    
    @classmethod
    def file_name_for(cls, mime: str) -> str:
        """根据 MIME 选择安全的录音文件名"""
        media_type = cls.validate(mime).split(';', 1)[0]
        
        extension_map = {
            "audio/mpeg": "mp3",
            "audio/mp3": "mp3",
            "audio/wav": "wav",
            "audio/wave": "wav",
            "audio/x-wav": "wav",
            "audio/ogg": "ogg",
            "audio/opus": "ogg",
            "audio/mp4": "m4a",
            "audio/aac": "aac",
            "audio/flac": "flac",
        }
        
        extension = extension_map.get(media_type, "webm")
        return f"speech.{extension}"
    
    @classmethod
    def validate_encoded(cls, bytes_data: bytes, mime: str | None) -> EncodedAudio:
        """校验音频字节、MIME 与大小，并返回不可变语义的编码对象
        
        Args:
            bytes_data: 音频字节数据
            mime: MIME 类型
            
        Returns:
            EncodedAudio 实例
            
        Raises:
            ValueError: 当数据为空、超过大小限制或 MIME 无效时
        """
        if not bytes_data or len(bytes_data) == 0:
            raise ValueError("音频内容不能为空")
        
        if len(bytes_data) > VoiceAudioLimits.MaxBytes:
            raise ValueError(f"音频内容超过 {VoiceAudioLimits.MaxBytes // (1024 * 1024)}MiB 限制")
        
        return EncodedAudio(bytes=bytes_data, mime=cls.validate(mime))
    
    @classmethod
    def validate_recorded(
        cls, 
        bytes_data: bytes, 
        mime: str | None, 
        file_name: str | None
    ) -> RecordedAudio:
        """校验录音的字节、MIME 与文件名
        
        Args:
            bytes_data: 录音字节数据
            mime: MIME 类型
            file_name: 文件名
            
        Returns:
            RecordedAudio 实例
            
        Raises:
            ValueError: 当数据为空、超过大小限制或 MIME 无效时
        """
        if not bytes_data or len(bytes_data) == 0:
            raise ValueError("录音内容不能为空")
        
        if len(bytes_data) > VoiceAudioLimits.MaxBytes:
            raise ValueError(f"录音内容超过 {VoiceAudioLimits.MaxBytes // (1024 * 1024)}MiB 限制")
        
        normalized_mime = cls.validate(mime)
        safe_name = cls._sanitize_file_name(file_name, normalized_mime)
        return RecordedAudio(bytes=bytes_data, mime=normalized_mime, file_name=safe_name)
    
    @staticmethod
    def _sanitize_file_name(file_name: str | None, mime: str) -> str:
        """清理文件名，防止路径遍历攻击"""
        if not file_name or not file_name.strip():
            return AudioMime.file_name_for(mime)
        
        value = file_name.strip()
        if len(value) > 128 or any(ord(c) < 32 for c in value):
            return AudioMime.file_name_for(mime)
        
        # 获取基本文件名
        name = file_name.split('/')[-1].split('\\')[-1]
        if not name or name in ('.', '..'):
            return AudioMime.file_name_for(mime)
        
        return name


class SentenceChunker:
    """按句末标点拆分 TTS 文本，保证单段不会无限增长"""
    
    # 单个合成段的长度上限
    MAX_CHUNK_LENGTH: Final[int] = 120
    
    SENTENCE_TERMINATORS: Final[frozenset[str]] = frozenset({'。', '！', '？', '!', '?', '；', ';', '\n', '\r'})
    SOFT_TERMINATORS: Final[frozenset[str]] = frozenset({'，', ',', '、', ':', ':'})
    
    @classmethod
    def split(cls, text: str | None, max_chunk_length: int = MAX_CHUNK_LENGTH) -> list[str]:
        """拆分文本并去掉空段
        
        Args:
            text: 待拆分的文本
            max_chunk_length: 单个分块的最大长度
            
        Returns:
            拆分后的文本列表
        """
        if not text or not text.strip():
            return []
        
        limit = max(1, max_chunk_length)
        normalized = text.strip()
        result: list[str] = []
        current: list[str] = []
        
        for char in normalized:
            current.append(char)
            
            if char in cls.SENTENCE_TERMINATORS:
                cls._flush(result, current)
            elif len(current) >= limit and char in cls.SOFT_TERMINATORS:
                cls._flush(result, current)
            elif len(current) >= limit:
                cls._flush_by_limit(result, current, limit)
        
        cls._flush(result, current)
        return result
    
    @classmethod
    def _flush(cls, result: list[str], current: list[str]) -> None:
        """将当前缓冲区的文本添加到结果中"""
        value = ''.join(current).strip()
        if value:
            result.append(value)
        current.clear()
    
    @classmethod
    def _flush_by_limit(cls, result: list[str], current: list[str], limit: int) -> None:
        """按长度限制强制分块"""
        while len(current) >= limit:
            split_at = cls._find_split_point(current, limit)
            result.append(''.join(current[:split_at]).strip())
            current = current[split_at:]
    
    @staticmethod
    def _find_split_point(current: list[str], limit: int) -> int:
        """查找合适的分割点（优先在软终止符或空白处分割）"""
        start = min(limit, len(current))
        for index in range(start, 0, -1):
            if current[index - 1] in SentenceChunker.SOFT_TERMINATORS or current[index - 1].isspace():
                return index
        return start


class AudioSynthesisCache:
    """按最近最少使用 (LRU) 策略保存合成音频"""
    
    def __init__(self) -> None:
        self._entries: dict[str, tuple[EncodedAudio, int]] = {}
        self._lru_order: list[str] = []
        self._bytes: int = 0
        self._lock: object = object()  # 简化版，实际应使用 threading.Lock
    
    @property
    def count(self) -> int:
        """当前缓存条目数"""
        return len(self._entries)
    
    @property
    def bytes(self) -> int:
        """当前缓存占用字节数"""
        return self._bytes
    
    @staticmethod
    def create_key(provider_endpoint: str, voice: str | None, speed: float, text: str) -> str:
        """按提供商端点、音色、语速和文本哈希生成稳定键"""
        hash_bytes = hashlib.sha256(text.encode('utf-8')).digest()
        hex_hash = hash_bytes.hex().upper()
        speed_str = repr(speed)
        return f"{provider_endpoint.strip()}\n{voice.strip() if voice else ''}\n{speed_str}\n{hex_hash}"
    
    def try_get(self, key: str) -> tuple[bool, EncodedAudio | None]:
        """读取缓存并更新最近使用顺序
        
        Returns:
            (是否命中，音频数据或 None)
        """
        if key not in self._entries:
            return False, None
        
        audio, size = self._entries[key]
        # 更新 LRU 顺序
        self._lru_order.remove(key)
        self._lru_order.insert(0, key)
        
        return True, audio
    
    def put(self, key: str, audio: EncodedAudio) -> None:
        """写入缓存，超出条目或总字节上限时淘汰最旧条目"""
        if not audio.bytes or len(audio.bytes) == 0:
            return
        if len(audio.bytes) > VoiceAudioLimits.MaxBytes:
            return
        
        # 如果已存在，先移除旧条目
        if key in self._entries:
            old_size = self._entries[key][1]
            del self._entries[key]
            self._lru_order.remove(key)
            self._bytes -= old_size
        
        # 添加新条目
        self._entries[key] = (audio, len(audio.bytes))
        self._lru_order.insert(0, key)
        self._bytes += len(audio.bytes)
        
        # 淘汰最旧条目直到满足限制
        while (len(self._entries) > VoiceAudioLimits.CacheItemLimit or 
               self._bytes > VoiceAudioLimits.MaxBytes):
            if not self._lru_order:
                break
            oldest_key = self._lru_order.pop()
            if oldest_key in self._entries:
                _, old_size = self._entries[oldest_key]
                del self._entries[oldest_key]
                self._bytes -= old_size
    
    def clear(self) -> None:
        """清空缓存"""
        self._entries.clear()
        self._lru_order.clear()
        self._bytes = 0
