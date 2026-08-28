"""Nori.Core.Voice - 语音服务模块

提供 TTS 文本转语音、STT 语音转文本、音频缓存和媒体交换功能。
支持多种 TTS 提供商：OpenAI、MiniMax、GPT-SoVITS、自定义 HTTP。
"""

from .audio_contracts import (
    VoiceAudioLimits,
    EncodedAudio,
    RecordedAudio,
    AudioMime,
    SentenceChunker,
    AudioSynthesisCache,
)
from .voice_contracts import (
    TtsSynthesizeOptions,
    ITtsProvider,
    IAudioPlayback,
    IMicrophoneRecorder,
)
from .voice_service import VoiceService
from .media_exchange import MediaExchange
from .providers import (
    OpenAiTtsProvider,
    MiniMaxTtsProvider,
    CustomHttpTtsProvider,
    GptSoVitsTtsProvider,
    WhisperSttProvider,
)

__all__ = [
    # 限制与数据类
    "VoiceAudioLimits",
    "EncodedAudio",
    "RecordedAudio",
    "AudioMime",
    "SentenceChunker",
    "AudioSynthesisCache",
    # 接口
    "TtsSynthesizeOptions",
    "ITtsProvider",
    "IAudioPlayback",
    "IMicrophoneRecorder",
    # 核心服务
    "VoiceService",
    "MediaExchange",
    # 提供商实现
    "OpenAiTtsProvider",
    "MiniMaxTtsProvider",
    "CustomHttpTtsProvider",
    "GptSoVitsTtsProvider",
    "WhisperSttProvider",
]