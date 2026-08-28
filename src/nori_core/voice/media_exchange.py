"""媒体交换所 MediaExchange

对应 C# MediaExchange.cs，提供一次性 token 机制用于音频文件的临时交换。
TTS 字节在这里登记一次性 token，前端拿着 `/{prefix}/media/{token}` 直接下载播放；
麦克风录音反向走同一套 token 上传。
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable


@dataclass
class _DownloadEntry:
    """下载条目：存储音频和过期时间"""
    audio: 'EncodedAudio'
    expires_at: datetime


@dataclass
class _UploadEntry:
    """上传条目：存储完成器和过期时间"""
    completion: asyncio.Future['RecordedAudio']
    expires_at: datetime


class MediaExchange:
    """一次性媒体交换所
    
    音频不走 JSON 桥：TTS 字节在这里登记一次性 token，前端拿着
    `/{prefix}/media/{token}` 直接下载播放；麦克风录音反向走同一套 token 上传。
    """
    
    # token 有效期（2 分钟）
    TTL = timedelta(minutes=2)
    
    def __init__(self, ttl: timedelta | None = None) -> None:
        """创建媒体交换所
        
        Args:
            ttl: token 有效期，默认 2 分钟
            
        Raises:
            ValueError: 当 ttl <= 0 时
        """
        if ttl is not None and ttl.total_seconds() <= 0:
            raise ValueError("ttl 必须为正数")
        
        self._ttl = ttl or self.TTL
        self._downloads: dict[str, _DownloadEntry] = {}
        self._uploads: dict[str, _UploadEntry] = {}
    
    @staticmethod
    def _new_token() -> str:
        """生成新的随机 token（16 字节 hex，小写）"""
        return secrets.token_hex(16)
    
    def _prune(self) -> None:
        """清理过期的下载和上传条目"""
        now = datetime.now(timezone.utc)
        
        # 清理过期下载
        expired_downloads = [
            key for key, entry in self._downloads.items()
            if entry.expires_at < now
        ]
        for key in expired_downloads:
            del self._downloads[key]
        
        # 清理过期上传
        expired_uploads = [
            key for key, entry in self._uploads.items()
            if entry.expires_at < now
        ]
        for key in expired_uploads:
            entry = self._uploads.pop(key)
            if not entry.completion.done():
                entry.completion.cancel()
    
    def publish_audio(self, audio: 'EncodedAudio') -> str:
        """登记一段待播放音频，返回一次性 token
        
        Args:
            audio: 已编码的音频数据
            
        Returns:
            一次性 token 字符串
        """
        from .audio_contracts import AudioMime
        
        # 验证音频
        validated = AudioMime.validate_encoded(audio.bytes, audio.mime)
        
        self._prune()
        token = self._new_token()
        self._downloads[token] = _DownloadEntry(
            audio=validated,
            expires_at=datetime.now(timezone.utc) + self._ttl
        )
        return token
    
    def publish_audio_bytes(self, data: bytes, mime: str) -> str:
        """兼容调用方登记带 MIME 的音频
        
        Args:
            data: 音频字节数据
            mime: MIME 类型
            
        Returns:
            一次性 token 字符串
        """
        from .audio_contracts import AudioMime, EncodedAudio
        return self.publish_audio(AudioMime.validate_encoded(data, mime))
    
    def try_take_audio(self, token: str) -> tuple[bool, bytes | None, str | None]:
        """取走音频 (取走即删)；token 无效或已过期返回 false
        
        Args:
            token: 一次性 token
            
        Returns:
            (是否成功，音频字节或 None, MIME 或 None)
        """
        entry = self._downloads.pop(token, None)
        if entry is None:
            return False, None, None
        
        if entry.expires_at < datetime.now(timezone.utc):
            return False, None, None
        
        return True, entry.audio.bytes, entry.audio.mime
    
    def create_upload_ticket(self) -> str:
        """开一张上传票据 (给前端录音用)，返回 token
        
        Returns:
            上传 token 字符串
        """
        self._prune()
        token = self._new_token()
        
        # 延迟导入避免循环依赖
        import asyncio
        loop = asyncio.get_event_loop()
        future: asyncio.Future['RecordedAudio'] = loop.create_future()
        
        self._uploads[token] = _UploadEntry(
            completion=future,
            expires_at=datetime.now(timezone.utc) + self._ttl
        )
        return token
    
    def try_complete_upload(self, token: str, audio: 'RecordedAudio') -> bool:
        """完成一次带 MIME 的录音上传；token 无效或内容无效返回 false
        
        Args:
            token: 上传 token
            audio: 录音数据
            
        Returns:
            是否成功完成上传
        """
        from .audio_contracts import AudioMime
        
        entry = self._uploads.get(token)
        if entry is None:
            return False
        
        if entry.expires_at < datetime.now(timezone.utc):
            self._uploads.pop(token, None)
            return False
        
        try:
            # 验证录音
            validated = AudioMime.validate_recorded(
                audio.bytes, 
                audio.mime, 
                audio.file_name
            )
            if not entry.completion.done():
                entry.completion.set_result(validated)
            return True
        except ValueError:
            # 由 HTTP 层通过 TryFailUpload 把原因立即通知等待方
            return False
    
    def try_complete_upload_bytes(self, token: str, data: bytes) -> bool:
        """兼容旧测试与内部调用的字节上传入口
        
        Args:
            token: 上传 token
            data: 录音字节数据
            
        Returns:
            是否成功完成上传
        """
        from .audio_contracts import AudioMime, RecordedAudio
        
        recorded = RecordedAudio(
            bytes=data,
            mime="audio/wav",
            file_name=AudioMime.file_name_for("audio/wav")
        )
        return self.try_complete_upload(token, recorded)
    
    def try_fail_upload(self, token: str, error: str) -> bool:
        """让等待方立即收到前端权限或上传失败，而不是等超时
        
        Args:
            token: 上传 token
            error: 错误信息
            
        Returns:
            是否成功设置失败
        """
        entry = self._uploads.get(token)
        if entry is None:
            return False
        
        error_msg = error.strip() if error else "前端录音上传失败"
        if not error.strip():
            error_msg = "前端录音上传失败"
        else:
            error_msg = f"前端录音上传失败：{error}"
        
        if not entry.completion.done():
            entry.completion.set_exception(ValueError(error_msg))
        return True
    
    def cancel_upload(self, token: str) -> None:
        """放弃一张票据 (录音失败/取消)
        
        Args:
            token: 上传 token
        """
        entry = self._uploads.pop(token, None)
        if entry and not entry.completion.done():
            entry.completion.cancel()
    
    async def wait_for_recorded_upload_async(
        self, 
        token: str, 
        timeout: timedelta,
    ) -> 'RecordedAudio':
        """等待带 MIME 的录音上传结果
        
        Args:
            token: 上传 token
            timeout: 等待超时时间
            
        Returns:
            录音数据
            
        Raises:
            ValueError: 当上传票据不存在或已过期时
            TimeoutError: 当等待超时时
        """
        import asyncio
        
        entry = self._uploads.get(token)
        if entry is None:
            raise ValueError("上传票据不存在或已失效")
        
        if entry.expires_at < datetime.now(timezone.utc):
            self._uploads.pop(token, None)
            raise ValueError("上传票据已过期")
        
        try:
            result = await asyncio.wait_for(entry.completion, timeout.total_seconds())
            return result
        except asyncio.TimeoutError:
            raise TimeoutError("等待前端上传录音超时")
        finally:
            self._uploads.pop(token, None)
    
    async def wait_for_upload_async(
        self, 
        token: str, 
        timeout: timedelta,
    ) -> bytes:
        """兼容旧调用方，仅取回录音字节
        
        Args:
            token: 上传 token
            timeout: 等待超时时间
            
        Returns:
            录音字节数据
        """
        recorded = await self.wait_for_recorded_upload_async(token, timeout)
        return recorded.bytes


# 延迟导入避免循环依赖
def __getattr__(name: str):
    if name == 'EncodedAudio':
        from .audio_contracts import EncodedAudio
        return EncodedAudio
    if name == 'RecordedAudio':
        from .audio_contracts import RecordedAudio
        return RecordedAudio
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
