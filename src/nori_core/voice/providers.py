"""TTS 提供商实现

对应 C# VoiceProviders.cs，提供多种 TTS 和 STT 提供商的 HTTP 适配器：
- OpenAiTtsProvider: OpenAI 兼容 TTS (/v1/audio/speech)
- MiniMaxTtsProvider: MiniMax 同步 T2A HTTP 适配器 (/v1/t2a_v2)
- CustomHttpTtsProvider: 自定义 HTTP TTS 适配器
- GptSoVitsTtsProvider: GPT-SoVITS API 适配器 (本地端点)
- WhisperSttProvider: OpenAI Whisper 录音识别 (/v1/audio/transcriptions)
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .voice_contracts import TtsSynthesizeOptions, EncodedAudio, RecordedAudio


@dataclass
class _ProviderConfig:
    """提供商配置读取辅助类"""
    config: dict[str, Any]
    
    def get_string(self, key: str, default: str = "") -> str:
        """获取字符串配置值"""
        value = self.config.get(key, default)
        return value if isinstance(value, str) else default
    
    def get_float(self, key: str, default: float) -> float:
        """获取浮点数配置值"""
        value = self.config.get(key, default)
        try:
            return float(value) if value else default
        except (ValueError, TypeError):
            return default


class OpenAiTtsProvider:
    """OpenAI 兼容 TTS 适配器 (/v1/audio/speech)"""
    
    def __init__(self, http_client: Any, config: dict[str, Any]) -> None:
        self._http = http_client
        self._config = _ProviderConfig(config)
    
    @property
    def name(self) -> str:
        return "openai"
    
    async def synthesize_async(
        self, 
        text: str, 
        options: 'TtsSynthesizeOptions',
    ) -> 'EncodedAudio':
        """合成文本并返回带 MIME 的音频数据"""
        from .audio_contracts import AudioMime
        
        base_url = self._config.get_string("tts_base_url", "https://api.openai.com/v1").strip().rstrip('/')
        api_key = self._config.get_string("tts_api_key", "")
        
        if not base_url.endswith("/audio/speech"):
            base_url += "/audio/speech"
        
        payload = {
            "model": "tts-1",
            "input": text,
            "voice": options.voice or "nova",
            "speed": options.speed,
        }
        
        # 模拟 HTTP 请求（实际需要 aiohttp 或 httpx）
        # response = await self._http.post(base_url, json=payload, headers={"Authorization": f"Bearer {api_key}"})
        # return await AudioMime.validate_encoded_from_response(response)
        
        # 占位实现
        raise NotImplementedError("OpenAiTtsProvider 需要 HTTP 客户端实现")


class MiniMaxTtsProvider:
    """MiniMax 同步 T2A HTTP 适配器 (/v1/t2a_v2)"""
    
    DEFAULT_BASE_URL = "https://api.minimaxi.com/v1"
    DEFAULT_MODEL = "speech-2.8-turbo"
    DEFAULT_VOICE = "male-qn-qingse"
    
    def __init__(self, http_client: Any, config: dict[str, Any]) -> None:
        self._http = http_client
        self._config = _ProviderConfig(config)
    
    @property
    def name(self) -> str:
        return "minimax"
    
    @staticmethod
    def _format_endpoint(base_url: str) -> str:
        """格式化端点 URL"""
        if not base_url:
            raise ValueError("MiniMax TTS Base URL 不能为空")
        
        if base_url.endswith("/t2a_v2"):
            return base_url
        elif base_url.endswith("/v1"):
            return f"{base_url}/t2a_v2"
        else:
            return f"{base_url}/v1/t2a_v2"
    
    @staticmethod
    def _read_status_code(body: dict[str, Any]) -> int:
        """读取响应状态码"""
        base_resp = body.get("base_resp", {})
        status_code = base_resp.get("status_code", 0)
        if isinstance(status_code, int):
            return status_code
        try:
            return int(status_code)
        except (ValueError, TypeError):
            return -1
    
    @staticmethod
    def _diagnostic_suffix(body: dict[str, Any] | None, raw: str) -> str:
        """生成诊断信息后缀"""
        details = []
        
        if body:
            status_msg = body.get("base_resp", {}).get("status_msg")
            trace_id = body.get("trace_id")
            
            if status_msg:
                details.append(f"message={status_msg}")
            if trace_id:
                details.append(f"trace_id={trace_id}")
        
        if not details and raw:
            compact = raw.replace('\r', ' ').replace('\n', ' ').strip()
            details.append(compact[:200] if len(compact) > 200 else compact)
        
        return "" if not details else f", {', '.join(details)}"
    
    async def synthesize_async(
        self, 
        text: str, 
        options: 'TtsSynthesizeOptions',
    ) -> 'EncodedAudio':
        """合成文本并返回带 MIME 的音频数据"""
        from .audio_contracts import AudioMime, VoiceAudioLimits
        
        base_url = self._config.get_string("tts_base_url", self.DEFAULT_BASE_URL).strip().rstrip('/')
        endpoint = self._format_endpoint(base_url)
        api_key = self._config.get_string("tts_api_key", "")
        
        if not api_key:
            raise ValueError("未配置 MiniMax TTS API Key")
        
        voice_id = options.voice if options.voice else self.DEFAULT_VOICE
        
        payload = {
            "model": self.DEFAULT_MODEL,
            "text": text,
            "stream": False,
            "voice_setting": {
                "voice_id": voice_id,
                "speed": options.speed,
            },
            "audio_setting": {
                "format": "mp3",
            },
            "output_format": "hex",
        }
        
        # 模拟 HTTP 请求
        # response = await self._http.post(endpoint, json=payload, headers={"Authorization": f"Bearer {api_key}"})
        # response_bytes = await response.read()
        # body = json.loads(response_bytes)
        
        # 占位实现
        raise NotImplementedError("MiniMaxTtsProvider 需要 HTTP 客户端实现")


class CustomHttpTtsProvider:
    """自定义 HTTP TTS 适配器
    
    POST tts_base_url, 请求体 {text, voice, speed}, 响应为带 Content-Type 的音频字节。
    """
    
    def __init__(self, http_client: Any, config: dict[str, Any]) -> None:
        self._http = http_client
        self._config = _ProviderConfig(config)
    
    @property
    def name(self) -> str:
        return "custom"
    
    async def synthesize_async(
        self, 
        text: str, 
        options: 'TtsSynthesizeOptions',
    ) -> 'EncodedAudio':
        """合成文本并返回带 MIME 的音频数据"""
        endpoint = self._config.get_string("tts_base_url", "").strip()
        
        if not endpoint:
            raise ValueError("未配置自定义 TTS 请求端点 URL")
        
        payload = {
            "text": text,
            "voice": options.voice,
            "speed": options.speed,
        }
        
        # 模拟 HTTP 请求
        # response = await self._http.post(endpoint, json=payload)
        # return await AudioMime.validate_encoded_from_response(response)
        
        raise NotImplementedError("CustomHttpTtsProvider 需要 HTTP 客户端实现")


class GptSoVitsTtsProvider:
    """GPT-SoVITS API 适配器 (官方 FastAPI /tts 端点; 本地端点显式允许私网)"""
    
    def __init__(self, http_client: Any, config: dict[str, Any]) -> None:
        self._http = http_client
        self._config = _ProviderConfig(config)
    
    @property
    def name(self) -> str:
        return "gpt_sovits"
    
    async def synthesize_async(
        self, 
        text: str, 
        options: 'TtsSynthesizeOptions',
    ) -> 'EncodedAudio':
        """合成文本并返回带 MIME 的音频数据"""
        base_url = self._config.get_string("gptsovits_base_url", "http://127.0.0.1:9880").strip().rstrip('/')
        ref_audio = self._config.get_string("gptsovits_ref_audio", "")
        prompt_text = self._config.get_string("gptsovits_prompt_text", "")
        prompt_lang = self._config.get_string("gptsovits_prompt_lang", "zh")
        
        url = base_url if base_url.endswith("/tts") else f"{base_url}/tts"
        
        payload = {
            "text": text,
            "text_lang": "zh",
            "ref_audio_path": ref_audio,
            "prompt_text": prompt_text,
            "prompt_lang": prompt_lang,
            "speed_factor": options.speed,
        }
        
        # 先尝试 POST，失败则降级到 GET
        # post_result = await self._post_async(url, payload)
        # if post_result:
        #     return post_result
        # return await self._get_async(url, text, ref_audio, prompt_text, prompt_lang, options.speed)
        
        raise NotImplementedError("GptSoVitsTtsProvider 需要 HTTP 客户端实现")


class WhisperSttProvider:
    """OpenAI Whisper 录音识别 (/v1/audio/transcriptions)"""
    
    def __init__(self, http_client: Any, config: dict[str, Any]) -> None:
        self._http = http_client
        self._config = _ProviderConfig(config)
    
    async def transcribe_async(
        self, 
        audio: 'RecordedAudio',
    ) -> str:
        """识别一段录音，保留 MediaRecorder 的 MIME 与文件名
        
        Args:
            audio: 录音数据
            
        Returns:
            识别的文本内容
        """
        from .audio_contracts import AudioMime
        
        # 验证录音
        validated = AudioMime.validate_recorded(audio.bytes, audio.mime, audio.file_name)
        
        base_url = self._config.get_string("stt_base_url", "https://api.openai.com/v1").strip().rstrip('/')
        if not base_url.endswith("/audio/transcriptions"):
            base_url += "/audio/transcriptions"
        
        api_key = self._config.get_string("stt_api_key", "")
        
        # 构建 multipart/form-data 请求
        # form_data = FormData()
        # form_data.add_field("file", validated.bytes, filename=validated.file_name, content_type=validated.mime)
        # form_data.add_field("model", "whisper-1")
        # form_data.add_field("language", "zh")
        # 
        # response = await self._http.post(base_url, data=form_data, headers={"Authorization": f"Bearer {api_key}"})
        # body = await response.json()
        # return body.get("text", "")
        
        raise NotImplementedError("WhisperSttProvider 需要 HTTP 客户端实现")
