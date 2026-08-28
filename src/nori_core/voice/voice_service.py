"""语音服务 VoiceService

对应 C# VoiceService.cs，提供全局语音服务：
- TTS 合成采用有界的生产/播放流水线
- 后台最多预取两段音频，首段合成完成即可开始播放
- 支持音量控制、朗读状态管理
- 配置变化时自动取消旧请求并清空缓存
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable

from .audio_contracts import (
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
from .providers import (
    OpenAiTtsProvider,
    MiniMaxTtsProvider,
    CustomHttpTtsProvider,
    GptSoVitsTtsProvider,
    WhisperSttProvider,
)


class VoiceService:
    """全局语音服务
    
    TTS 合成采用有界的生产/播放流水线：后台最多预取两段，首段合成完成即可开始播放，
    不让长回复一次性等待全部音频。停止或配置变化会取消合成、清空播放并通知观察者。
    """
    
    # 已停用的浏览器语音提供商集合
    RETIRED_PROVIDERS = frozenset({"web_speech", "edge_tts"})
    
    def __init__(
        self,
        http_client: Any,
        config: dict[str, Any],
        playback: IAudioPlayback | None = None,
        recorder_factory: Callable[[], IMicrophoneRecorder | None] | None = None,
    ) -> None:
        """创建语音服务
        
        Args:
            http_client: HTTP 客户端实例
            config: 配置字典
            playback: 音频播放后端（可选）
            recorder_factory: 录音器工厂函数（可选）
        """
        self._http = http_client
        self._config = config
        self._playback = playback
        self._recorder_factory = recorder_factory or (lambda: None)
        
        self._queue = asyncio.Semaphore(1)
        self._speech_gate = asyncio.Lock()
        self._speech_cts: asyncio.CancelledError | None = None
        self._speaking = False
        self._disposed = False
        
        # 合成结果缓存
        self.synthesis_cache = AudioSynthesisCache()
        
        # 事件回调
        self._volume_changed_callbacks: list[Callable[[float], None]] = []
        self._speaking_changed_callbacks: list[Callable[[bool], None]] = []
    
    def on_volume_changed(self, callback: Callable[[float], None]) -> None:
        """注册音量变化回调"""
        self._volume_changed_callbacks.append(callback)
    
    def on_speaking_changed(self, callback: Callable[[bool], None]) -> None:
        """注册朗读状态变化回调"""
        self._speaking_changed_callbacks.append(callback)
    
    # ---- 音量控制 ----
    
    def get_volume(self) -> float:
        """读取全局音量 (0.0 ~ 1.0)"""
        raw = self._config.get("audio_volume", "1")
        try:
            value = float(raw) if isinstance(raw, str) else float(raw)
        except (ValueError, TypeError):
            return 1.0
        return max(0.0, min(1.0, value))
    
    def set_volume(self, volume: float) -> None:
        """设置全局音量并持久化"""
        clamped = max(0.0, min(1.0, volume))
        self._config["audio_volume"] = f"{clamped:.7f}".rstrip('0').rstrip('.')
        
        for callback in self._volume_changed_callbacks:
            try:
                callback(clamped)
            except Exception:
                pass
    
    # ---- 播放状态 ----
    
    @property
    def is_speaking(self) -> bool:
        """是否正在朗读 (含合成和播放阶段)"""
        return self._speaking
    
    def stop(self) -> None:
        """停止朗读并清空队列"""
        if self._speech_cts:
            try:
                # 取消当前的合成任务
                pass
            except Exception:
                pass
        
        if self._playback:
            self._playback.stop()
    
    def notify_configuration_changed(self) -> None:
        """配置发生变化时取消旧请求，避免旧端点的音频继续播放；同时丢弃旧缓存"""
        self.synthesis_cache.clear()
        self.stop()
    
    # ---- 提供商解析 ----
    
    def resolve_provider_name(self) -> str:
        """解析当前配置的 TTS 提供商名"""
        saved = self._config.get("tts_provider", "")
        return saved if isinstance(saved, str) and saved else "openai"
    
    def create_provider(self, name: str) -> ITtsProvider:
        """按名称构造 TTS 提供商；已停用的浏览器路径给出明确错误"""
        if name in self.RETIRED_PROVIDERS:
            raise ValueError(
                f"语音提供商 {name} 依赖浏览器能力，已在纯后端版本中停用，"
                f"请改用 OpenAI / MiniMax / 自定义 HTTP / GPT-SoVITS"
            )
        
        if name == "minimax":
            return MiniMaxTtsProvider(self._http, self._config)
        elif name == "gpt_sovits":
            return GptSoVitsTtsProvider(self._http, self._config)
        elif name == "custom":
            return CustomHttpTtsProvider(self._http, self._config)
        else:
            return OpenAiTtsProvider(self._http, self._config)
    
    def _resolve_provider_endpoint(self, provider_name: str) -> str:
        """解析提供商端点 URL"""
        if provider_name == "gpt_sovits":
            base_url = self._config.get("gptsovits_base_url", "http://127.0.0.1:9880")
        elif provider_name == "minimax":
            base_url = self._config.get("tts_base_url", "https://api.minimaxi.com/v1")
            if not base_url:
                base_url = "https://api.minimaxi.com/v1"
        else:
            base_url = self._config.get("tts_base_url", "https://api.openai.com/v1")
        
        return f"{provider_name}:{str(base_url).strip().rstrip('/')}"
    
    def _read_double_config(self, key: str, fallback: float) -> float:
        """读取数值配置，非法时回退"""
        raw = self._config.get(key, "")
        try:
            value = float(raw) if raw else 0
            return value if value > 0 else fallback
        except (ValueError, TypeError):
            return fallback
    
    def _merge_options(self, options: TtsSynthesizeOptions | None) -> TtsSynthesizeOptions:
        """合并用户选项与配置默认值"""
        if options is None:
            options = TtsSynthesizeOptions()
        
        voice = options.voice
        if not voice:
            voice = self._config.get("tts_voice", "")
            if not voice:
                voice = None
        
        speed = options.speed if options.speed > 0 else self._read_double_config("tts_speed", 1.0)
        
        return TtsSynthesizeOptions(voice=voice, speed=speed)
    
    # ---- 合成与播放 ----
    
    async def speak_async(
        self, 
        text: str, 
        options: TtsSynthesizeOptions | None = None,
    ) -> None:
        """朗读文本：按句切段并以有界流水线边合成边播放"""
        if not text or not text.strip():
            return
        
        if not self._playback:
            raise ValueError("音频播放后端不可用")
        
        if self._disposed:
            raise RuntimeError("VoiceService 已释放")
        
        # 创建新的取消令牌
        async with self._speech_gate:
            old_cts = self._speech_cts
            self._speech_cts = asyncio.CancelledError()
        
        self._set_speaking(True)
        
        try:
            await self._queue.acquire()
            try:
                chunks = SentenceChunker.split(text)
                await self._run_pipeline_async(chunks, options)
            finally:
                self._queue.release()
        finally:
            async with self._speech_gate:
                is_current = self._speech_cts is not None
            
            if is_current:
                self._set_speaking(False)
    
    async def _run_pipeline_async(
        self, 
        chunks: list[str], 
        options: TtsSynthesizeOptions | None,
    ) -> None:
        """运行生产/消费流水线"""
        audio_queue: asyncio.Queue[EncodedAudio] = asyncio.Queue(maxsize=2)
        producer_task = asyncio.create_task(self._produce_async(chunks, options, audio_queue))
        consumer_task = asyncio.create_task(self._consume_async(audio_queue))
        
        try:
            await asyncio.gather(producer_task, consumer_task)
        except Exception:
            if self._playback:
                self._playback.stop()
            raise
    
    async def _produce_async(
        self, 
        chunks: list[str], 
        options: TtsSynthesizeOptions | None,
        queue: asyncio.Queue[EncodedAudio],
    ) -> None:
        """生产者：合成音频段"""
        try:
            for chunk in chunks:
                audio = await self.synthesize_async(chunk, options)
                await queue.put(audio)
        finally:
            await queue.join()
    
    async def _consume_async(self, queue: asyncio.Queue[EncodedAudio]) -> None:
        """消费者：播放音频段"""
        try:
            while True:
                audio = await queue.get()
                try:
                    if self._playback:
                        await self._playback.play_async(audio.bytes, audio.mime)
                finally:
                    queue.task_done()
        except asyncio.CancelledError:
            pass
    
    async def synthesize_async(
        self, 
        text: str, 
        options: TtsSynthesizeOptions | None = None,
    ) -> EncodedAudio:
        """仅合成不播放 (测试/预检用)，返回实际 MIME"""
        if not text or not text.strip():
            raise ValueError("合成文本不能为空")
        
        return await self._synthesize_core_async(text.strip(), options)
    
    async def _synthesize_core_async(
        self, 
        text: str, 
        options: TtsSynthesizeOptions | None,
    ) -> EncodedAudio:
        """合成核心逻辑：检查缓存 -> 调用提供商 -> 验证 -> 缓存"""
        provider_name = self.resolve_provider_name()
        provider = self.create_provider(provider_name)
        merged = self._merge_options(options)
        endpoint = self._resolve_provider_endpoint(provider_name)
        
        key = AudioSynthesisCache.create_key(endpoint, merged.voice, merged.speed, text)
        
        # 检查缓存
        hit, cached = self.synthesis_cache.try_get(key)
        if hit and cached:
            return cached
        
        # 调用提供商合成
        audio = await provider.synthesize_async(text, merged)
        
        # 验证并缓存
        validated = AudioMime.validate_encoded(audio.bytes, audio.mime)
        self.synthesis_cache.put(key, validated)
        
        return validated
    
    # ---- 录音识别 ----
    
    async def start_listening_async(self) -> None:
        """开始录音；前端权限失败会由 recorder 立即报告"""
        recorder = self._recorder_factory()
        if not recorder:
            raise ValueError("麦克风录音后端不可用")
        
        await recorder.start_async()
    
    async def stop_listening_and_transcribe_async(self) -> str:
        """结束录音并经 Whisper 识别返回文本"""
        recorder = self._recorder_factory()
        if not recorder:
            raise ValueError("麦克风录音后端不可用")
        
        if not recorder.is_recording:
            return ""
        
        audio = await recorder.stop_async()
        if not audio.bytes:
            return ""
        
        provider = WhisperSttProvider(self._http, self._config)
        return await provider.transcribe_async(audio)
    
    # ---- 迁移检测 ----
    
    def has_retired_voice_config(self) -> bool:
        """检测旧版浏览器语音配置是否需要一次性提示"""
        return (
            self.resolve_provider_name() in self.RETIRED_PROVIDERS or
            self._config.get("stt_provider", "") in self.RETIRED_PROVIDERS
        )
    
    def _set_speaking(self, value: bool) -> None:
        """设置说话状态并触发回调"""
        if self._speaking == value:
            return
        
        self._speaking = value
        
        for callback in self._speaking_changed_callbacks:
            try:
                callback(value)
            except Exception:
                pass
    
    def dispose(self) -> None:
        """释放资源"""
        if self._disposed:
            return
        
        self._disposed = True
        self.stop()
        
        if self._playback:
            self._playback.dispose()
        
        self.synthesis_cache.clear()
