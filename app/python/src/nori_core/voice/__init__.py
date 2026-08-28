"""语音服务 - TTS 合成、音频播放和录音管理。

本模块提供全局语音服务，包括：
- TTS 合成（支持多种提供商）
- 音频播放控制
- 录音管理
- 音量控制
- 句子切分和音频缓存
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, Callable, Final, Protocol, Self, runtime_checkable

logger = logging.getLogger(__name__)


class VoiceAudioLimits:
    """语音请求和媒体交换共用的音频大小上限。"""

    MAX_BYTES: Final[int] = 32 * 1024 * 1024  # 32MiB
    SYNTHESIS_QUEUE_CAPACITY: Final[int] = 2
    CACHE_ITEM_LIMIT: Final[int] = 16


@dataclass(frozen=True)
class EncodedAudio:
    """已编码的音频数据。"""

    bytes: bytes
    mime: str

    @property
    def length(self) -> int:
        return len(self.bytes)


@dataclass(frozen=True)
class RecordedAudio:
    """MediaRecorder 产生的原始录音及其格式信息。"""

    bytes: bytes
    mime: str
    file_name: str

    @property
    def length(self) -> int:
        return len(self.bytes)


class AudioMime:
    """音频 MIME 校验与录音文件名辅助。"""

    SUPPORTED_TYPES: Final[set[str]] = {
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
    }

    @classmethod
    def validate(cls, mime: str | None) -> str:
        """校验并规范 MIME 的主类型，同时保留 codecs 等参数。"""
        if not mime or not mime.strip():
            raise ValueError("音频 MIME 类型不能为空")

        value = mime.strip()
        separator = value.find(";")
        media_type = value[:separator].strip() if separator >= 0 else value.strip()

        if "/" not in media_type or media_type.lower() not in cls.SUPPORTED_TYPES:
            raise ValueError(f"不支持的音频 MIME 类型：{mime}")

        parameters = value[separator:].strip() if separator >= 0 else ""
        return media_type.lower() + parameters

    @classmethod
    def is_supported(cls, mime: str | None) -> bool:
        """判断 MIME 是否是受支持的音频类型。"""
        try:
            cls.validate(mime)
            return True
        except ValueError:
            return False

    @classmethod
    def file_name_for(cls, mime: str) -> str:
        """根据 MIME 选择安全的录音文件名。"""
        media_type = cls.validate(mime).split(";", 1)[0]
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
    def validate_encoded(cls, bytes_: bytes, mime: str | None) -> EncodedAudio:
        """校验音频字节、MIME 与大小，并返回不可变语义的编码对象。"""
        if not bytes_ or len(bytes_) == 0:
            raise ValueError("音频内容不能为空")
        if len(bytes_) > VoiceAudioLimits.MAX_BYTES:
            raise ValueError("音频内容超过 32MiB 限制")
        return EncodedAudio(bytes=bytes_, mime=cls.validate(mime))

    @classmethod
    def validate_recorded(
        cls, bytes_: bytes, mime: str | None, file_name: str | None
    ) -> RecordedAudio:
        """校验录音的字节、MIME 与文件名。"""
        if not bytes_ or len(bytes_) == 0:
            raise ValueError("录音内容不能为空")
        if len(bytes_) > VoiceAudioLimits.MAX_BYTES:
            raise ValueError("录音内容超过 32MiB 限制")

        normalized_mime = cls.validate(mime)
        safe_name = cls._sanitize_file_name(file_name, normalized_mime)
        return RecordedAudio(bytes=bytes_, mime=normalized_mime, file_name=safe_name)

    @staticmethod
    def _sanitize_file_name(file_name: str | None, mime: str) -> str:
        if not file_name or not file_name.strip():
            return AudioMime.file_name_for(mime)

        value = file_name.strip()
        if len(value) > 128 or any(c.isspace() or ord(c) < 32 for c in value):
            return AudioMime.file_name_for(mime)

        name = Path(value).name
        if not name or name in (".", ".."):
            return AudioMime.file_name_for(mime)

        return name


class SentenceChunker:
    """按句末标点拆分 TTS 文本，保证单段不会无限增长。"""

    MAX_CHUNK_LENGTH: Final[int] = 120
    SENTENCE_TERMINATORS: Final[set[str]] = {"。", "！", "？", "!", "?", "；", ";", "\n", "\r"}
    SOFT_TERMINATORS: Final[set[str]] = {"，", ",", "、", ":", ":"}

    @classmethod
    def split(cls, text: str | None, max_chunk_length: int = MAX_CHUNK_LENGTH) -> list[str]:
        """拆分文本并去掉空段。"""
        if not text or not text.strip():
            return []

        limit = max(1, max_chunk_length)
        normalized = text.strip()
        result: list[str] = []
        current: list[str] = []

        for char in normalized:
            current.append(char)
            current_str = "".join(current)

            if char in cls.SENTENCE_TERMINATORS:
                flushed = current_str.strip()
                if flushed:
                    result.append(flushed)
                current = []
            elif len(current_str) >= limit and char in cls.SOFT_TERMINATORS:
                flushed = current_str.strip()
                if flushed:
                    result.append(flushed)
                current = []
            elif len(current_str) >= limit:
                split_point = cls._find_split_point(current_str, limit)
                flushed = current_str[:split_point].strip()
                if flushed:
                    result.append(flushed)
                current = [char for char in current_str[split_point:]]

        final = "".join(current).strip()
        if final:
            result.append(final)

        return result

    @staticmethod
    def _find_split_point(text: str, limit: int) -> int:
        start = min(limit, len(text))
        for index in range(start, 0, -1):
            if text[index - 1] in SentenceChunker.SOFT_TERMINATORS or text[
                index - 1
            ].isspace():
                return index
        return start


@dataclass
class CacheEntry:
    """缓存条目。"""

    key: str
    audio: EncodedAudio
    size: int
    last_access: float = field(default_factory=time.time)


class AudioSynthesisCache:
    """按最近最少使用策略保存合成音频。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._entries: OrderedDict[str, CacheEntry] = OrderedDict()
        self._bytes: int = 0

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._entries)

    @property
    def bytes(self) -> int:
        with self._lock:
            return self._bytes

    @staticmethod
    def create_key(provider_endpoint: str, voice: str | None, speed: float, text: str) -> str:
        """按提供商端点、音色、语速和文本哈希生成稳定键。"""
        hash_bytes = hashlib.sha256(text.encode("utf-8")).digest()
        hash_hex = hash_bytes.hex()
        return f"{provider_endpoint.strip()}\n{voice.strip() if voice else ''}\n{speed}\n{hash_hex}"

    def try_get(self, key: str) -> EncodedAudio | None:
        """读取缓存并更新最近使用顺序。"""
        with self._lock:
            if key not in self._entries:
                return None

            entry = self._entries[key]
            self._entries.move_to_end(key)
            entry.last_access = time.time
            return entry.audio

    def put(self, key: str, audio: EncodedAudio) -> None:
        """写入缓存，超出条目或总字节上限时淘汰最旧条目。"""
        if not audio.bytes or len(audio.bytes) == 0:
            return
        if len(audio.bytes) > VoiceAudioLimits.MAX_BYTES:
            return

        with self._lock:
            if key in self._entries:
                old_entry = self._entries.pop(key)
                self._bytes -= old_entry.size

            entry = CacheEntry(key=key, audio=audio, size=len(audio.bytes))
            self._entries[key] = entry
            self._bytes += entry.size

            while len(self._entries) > VoiceAudioLimits.CACHE_ITEM_LIMIT or self._bytes > VoiceAudioLimits.MAX_BYTES:
                _, oldest = self._entries.popitem(last=False)
                self._bytes -= oldest.size

    def clear(self) -> None:
        """清空缓存。"""
        with self._lock:
            self._entries.clear()
            self._bytes = 0


@runtime_checkable
class IAudioPlayback(Protocol):
    """音频播放后端接口。"""

    def play(self, audio: EncodedAudio) -> None:
        """播放音频。"""
        ...

    def stop(self) -> None:
        """停止播放。"""
        ...

    @property
    def is_playing(self) -> bool:
        """是否正在播放。"""
        ...


@runtime_checkable
class IMicrophoneRecorder(Protocol):
    """麦克风录音接口。"""

    def start_recording(self) -> None:
        """开始录音。"""
        ...

    def stop_recording(self) -> RecordedAudio | None:
        """停止录音并返回录音数据。"""
        ...

    @property
    def is_recording(self) -> bool:
        """是否正在录音。"""
        ...


@dataclass
class TtsSynthesizeOptions:
    """TTS 合成选项。"""

    voice: str | None = None
    speed: float = 1.0
    provider: str | None = None


class VoiceServiceState(Enum):
    """语音服务状态。"""

    Idle = auto()
    Synthesizing = auto()
    Playing = auto()
    Stopped = auto()


class VoiceService:
    """全局语音服务。

    TTS 合成采用有界的生产/播放流水线：后台最多预取两段，首段合成完成即可开始播放，
    不让长回复一次性等待全部音频。停止或配置变化会取消合成、清空播放并通知观察者。
    """

    RETIRED_PROVIDERS: Final[set[str]] = {"web_speech", "edge_tts"}

    def __init__(
        self,
        config_store: Any,
        playback: IAudioPlayback | None = None,
        recorder_factory: Callable[[], IMicrophoneRecorder | None] | None = None,
    ):
        self._config = config_store
        self._playback = playback
        self._recorder_factory = recorder_factory
        self._synthesis_cache = AudioSynthesisCache()
        self._queue_lock = threading.Semaphore(1)
        self._speech_gate = threading.Lock()
        self._speech_cancellation: threading.Event | None = None
        self._speaking = False
        self._disposed = False

        self._volume_changed_callbacks: list[Callable[[float], None]] = []
        self._speaking_changed_callbacks: list[Callable[[bool], None]] = []

    @property
    def synthesis_cache(self) -> AudioSynthesisCache:
        return self._synthesis_cache

    def add_volume_changed_listener(self, callback: Callable[[float], None]) -> None:
        self._volume_changed_callbacks.append(callback)

    def add_speaking_changed_listener(
        self, callback: Callable[[bool], None]
    ) -> None:
        self._speaking_changed_callbacks.append(callback)

    def _notify_volume_changed(self, volume: float) -> None:
        for callback in self._volume_changed_callbacks:
            try:
                callback(volume)
            except Exception as e:
                logger.error(f"音量变化回调失败：{e}")

    def _notify_speaking_changed(self, speaking: bool) -> None:
        for callback in self._speaking_changed_callbacks:
            try:
                callback(speaking)
            except Exception as e:
                logger.error(f"朗读状态变化回调失败：{e}")

    def get_volume(self) -> float:
        """读取全局音量 (0.0 ~ 1.0)。"""
        raw = self._config.get_string_or("audio_volume", "1")
        try:
            value = float(raw)
            return max(0.0, min(1.0, value))
        except (ValueError, TypeError):
            return 1.0

    def set_volume(self, volume: float) -> None:
        """设置全局音量并持久化。"""
        clamped = max(0.0, min(1.0, volume))
        self._config.set("audio_volume", clamped)
        self._notify_volume_changed(clamped)

    @property
    def is_speaking(self) -> bool:
        """是否正在朗读 (含合成和播放阶段)。"""
        return self._speaking

    def stop(self) -> None:
        """停止朗读并清空队列。"""
        with self._speech_gate:
            if self._speech_cancellation:
                self._speech_cancellation.set()
                self._speech_cancellation = None

        if self._playback:
            self._playback.stop()

    def notify_configuration_changed(self) -> None:
        """配置发生变化时取消旧请求，避免旧端点的音频继续播放；同时丢弃旧缓存。"""
        self._synthesis_cache.clear()
        self.stop()

    def resolve_provider_name(self) -> str:
        """解析当前配置的 TTS 提供商名。"""
        saved = self._config.get_string_or("tts_provider", "")
        return saved if saved else "openai"

    async def speak_async(
        self,
        text: str,
        options: TtsSynthesizeOptions | None = None,
        cancellation_token: threading.Event | None = None,
    ) -> None:
        """朗读文本：按句切段并以有界流水线边合成边播放。"""
        if not text or not text.strip():
            return

        if not self._playback:
            raise RuntimeError("音频播放后端不可用")

        self._throw_if_disposed()

        speech_cancellation = threading.Event()
        previous_cancellation: threading.Event | None

        with self._speech_gate:
            previous_cancellation = self._speech_cancellation
            self._speech_cancellation = speech_cancellation

        if previous_cancellation:
            try:
                previous_cancellation.set()
            except Exception:
                pass

        self._set_speaking(True)

        try:
            acquired = self._queue_lock.acquire(timeout=30)
            if not acquired:
                raise TimeoutError("获取合成队列超时")

            try:
                chunks = SentenceChunker.split(text)
                await self._run_pipeline_async(
                    self._playback, chunks, options, speech_cancellation
                )
            finally:
                self._queue_lock.release()
        finally:
            is_current = False
            with self._speech_gate:
                is_current = self._speech_cancellation is speech_cancellation
                if is_current:
                    self._speech_cancellation = None

            if is_current:
                self._set_speaking(False)

    async def _run_pipeline_async(
        self,
        player: IAudioPlayback,
        chunks: list[str],
        options: TtsSynthesizeOptions | None,
        cancellation: threading.Event,
    ) -> None:
        """运行合成 - 播放流水线。"""
        for i, chunk in enumerate(chunks):
            if cancellation.is_set():
                logger.debug(f"合成被取消，剩余 {len(chunks) - i} 段未处理")
                break

            try:
                audio = await self._synthesize_chunk_async(chunk, options, cancellation)
                if audio and not cancellation.is_set():
                    player.play(audio)
            except Exception as e:
                logger.error(f"合成第 {i + 1} 段失败：{e}")
                if cancellation.is_set():
                    break

    async def _synthesize_chunk_async(
        self,
        chunk: str,
        options: TtsSynthesizeOptions | None,
        cancellation: threading.Event,
    ) -> EncodedAudio | None:
        """合成单个文本段。"""
        provider_name = options.provider if options and options.provider else self.resolve_provider_name()

        if provider_name in self.RETIRED_PROVIDERS:
            raise ValueError(f"已停用的 TTS 提供商：{provider_name}")

        voice = options.voice if options else None
        speed = options.speed if options else 1.0

        cache_key = AudioSynthesisCache.create_key(
            provider_name, voice, speed, chunk
        )

        cached = self._synthesis_cache.try_get(cache_key)
        if cached:
            logger.debug(f"缓存命中：{cache_key[:20]}...")
            return cached

        try:
            audio = await self._call_tts_provider_async(
                provider_name, chunk, voice, speed, cancellation
            )
            if audio:
                self._synthesis_cache.put(cache_key, audio)
            return audio
        except Exception as e:
            logger.error(f"TTS 合成失败：{e}")
            raise

    async def _call_tts_provider_async(
        self,
        provider: str,
        text: str,
        voice: str | None,
        speed: float,
        cancellation: threading.Event,
    ) -> EncodedAudio | None:
        """调用 TTS 提供商 API。具体实现由子类或外部注入。"""
        logger.debug(f"调用 TTS 提供商 {provider}: {text[:30]}...")
        await asyncio.sleep(0.1)
        return None

    def _set_speaking(self, speaking: bool) -> None:
        self._speaking = speaking
        self._notify_speaking_changed(speaking)

    def _throw_if_disposed(self) -> None:
        if self._disposed:
            raise RuntimeError("VoiceService 已释放")

    def dispose(self) -> None:
        """释放资源。"""
        if self._disposed:
            return

        self.stop()
        self._disposed = True
        logger.debug("VoiceService 已释放")


import asyncio

__all__ = [
    "VoiceAudioLimits",
    "EncodedAudio",
    "RecordedAudio",
    "AudioMime",
    "SentenceChunker",
    "AudioSynthesisCache",
    "IAudioPlayback",
    "IMicrophoneRecorder",
    "TtsSynthesizeOptions",
    "VoiceServiceState",
    "VoiceService",
]
