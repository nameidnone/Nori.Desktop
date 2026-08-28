"""语音服务接口契约

对应 C# IVoiceAudio.cs，定义 TTS 提供商、音频播放和麦克风录音的接口。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class TtsSynthesizeOptions:
    """TTS 合成选项"""
    
    voice: str | None = None
    """朗读音色"""
    
    speed: float = 1.0
    """语速 (1.0 为常速)"""


class ITtsProvider(ABC):
    """TTS 提供商接口
    
    云端合成返回音频字节 (mp3/wav 由端点决定)。
    后端化后仅保留云端/HTTP 路径。
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """提供商名 (对应配置键 tts_provider 的取值)"""
        pass
    
    @abstractmethod
    async def synthesize_async(
        self, 
        text: str, 
        options: TtsSynthesizeOptions,
    ) -> 'EncodedAudio':
        """合成文本并返回带 MIME 的音频数据
        
        Args:
            text: 待合成的文本
            options: 合成选项
            
        Returns:
            EncodedAudio 实例，包含音频字节和 MIME 类型
        """
        pass


class IAudioPlayback(ABC):
    """原生音频播放接口
    
    播放期间通过 VolumeSampled 输出 0~1 音量采样驱动桌宠口型，
    PlayingChanged 通知说话状态变化。
    
    实现已从 NAudio 换成 WebView 内的 WebAudio (三平台一套代码),
    因此这里的语义是"把音频交给播放宿主并等待其播完"。
    """
    
    @property
    @abstractmethod
    def is_playing(self) -> bool:
        """是否正在播放"""
        pass
    
    @abstractmethod
    def on_playing_changed(self, callback) -> None:
        """注册播放状态变化回调"""
        pass
    
    @abstractmethod
    def on_volume_sampled(self, callback) -> None:
        """注册音量采样回调 (0.0 ~ 1.0)"""
        pass
    
    @abstractmethod
    async def play_async(
        self, 
        data: bytes, 
        mime: str | None = None,
    ) -> None:
        """阻塞式播放一段带 MIME 的音频
        
        Args:
            data: 音频字节数据
            mime: MIME 类型（可选）
        """
        pass
    
    @abstractmethod
    def stop(self) -> None:
        """停止当前播放并清空队列"""
        pass
    
    @abstractmethod
    def dispose(self) -> None:
        """释放资源"""
        pass


class IMicrophoneRecorder(ABC):
    """麦克风录音接口
    
    全部异步：WebView 录音需要等前端回传音频，绝不能在 UI 线程上同步阻塞。
    """
    
    @property
    @abstractmethod
    def is_recording(self) -> bool:
        """是否正在录制"""
        pass
    
    @abstractmethod
    async def start_async(self) -> None:
        """开始录制"""
        pass
    
    @abstractmethod
    async def stop_async(self) -> 'RecordedAudio':
        """停止录制并返回 MediaRecorder 的实际 MIME 与文件名
        
        Returns:
            RecordedAudio 实例，包含录音字节、MIME 和文件名
        """
        pass
    
    @abstractmethod
    def dispose(self) -> None:
        """释放资源"""
        pass


# 延迟导入避免循环依赖
def __getattr__(name: str):
    if name == 'EncodedAudio':
        from .audio_contracts import EncodedAudio
        return EncodedAudio
    if name == 'RecordedAudio':
        from .audio_contracts import RecordedAudio
        return RecordedAudio
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
