"""
Nori Core Emotion Module - Python 实现

情绪管理系统，对应 C# EmotionManager.cs
"""

from __future__ import annotations
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional


class EmotionTypes:
    """情绪类型 (8 种基础情绪)"""
    NEUTRAL = "neutral"
    HAPPY = "happy"
    SAD = "sad"
    ANGRY = "angry"
    SURPRISED = "surprised"
    SHY = "shy"
    SLEEPY = "sleepy"
    FOND = "fond"
    
    ALL = [NEUTRAL, HAPPY, SAD, ANGRY, SURPRISED, SHY, SLEEPY, FOND]
    
    @classmethod
    def is_valid(cls, value: str) -> bool:
        return value in cls.ALL
    
    @classmethod
    def get_default_expression(cls, emotion: str) -> Optional[str]:
        """映射情绪到默认 Live2D 表情"""
        mapping = {
            cls.HAPPY: "Smile",
            cls.SAD: "Sad",
            cls.ANGRY: "Angry",
            cls.SURPRISED: "Surprised",
            cls.SHY: "Shy",
            cls.SLEEPY: "Sleepy",
            cls.FOND: "Smile",
        }
        return mapping.get(emotion)


@dataclass
class EmotionState:
    """情绪状态描述"""
    type: str  # 情绪类型
    intensity: float  # 强度 0.0 ~ 1.0
    last_updated: float  # 最后更新时间戳 (秒)
    
    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "intensity": self.intensity,
            "lastUpdated": self.last_updated,
        }


class EmotionManager:
    """
    情绪状态管理器
    
    支持配置持久化与自然衰减：每 DecayIntervalSeconds 秒衰减 0.1, 
    归零后回到 neutral。情绪变化时通过 ExpressionRequested 请求 
    Live2D 默认表情映射。
    """
    
    DECAY_INTERVAL_SECONDS = 20  # 自然衰减周期 (秒)
    PERSIST_DELAY_SECONDS = 0.4  # 防抖保存延迟 (秒)
    
    def __init__(self, config_store: Optional[object] = None):
        self._config_store = config_store
        self._lock = threading.Lock()
        self._decay_timer: Optional[threading.Timer] = None
        self._persist_timer: Optional[threading.Timer] = None
        
        self._current = EmotionTypes.NEUTRAL
        self._intensity = 0.5
        self._last_updated = time.time()
        self._initialized = False
        
        # 回调
        self._changed_callbacks: list[Callable[[EmotionState], None]] = []
        self._expression_callbacks: list[Callable[[str], None]] = []
    
    def on_changed(self, callback: Callable[[EmotionState], None]) -> None:
        """注册情绪变化回调"""
        self._changed_callbacks.append(callback)
    
    def on_expression_requested(self, callback: Callable[[str], None]) -> None:
        """注册表情请求回调"""
        self._expression_callbacks.append(callback)
    
    def initialize(self) -> None:
        """从配置恢复持久化的情绪状态"""
        with self._lock:
            if self._initialized:
                return
            
            if self._config_store:
                try:
                    saved_type = getattr(self._config_store, 'get', lambda k, d: d)("nori_emotion", "")
                    saved_intensity_str = getattr(self._config_store, 'get', lambda k, d: d)("nori_emotion_intensity", "")
                    
                    if saved_type and EmotionTypes.is_valid(saved_type):
                        self._current = saved_type
                    
                    if saved_intensity_str:
                        try:
                            saved_intensity = float(saved_intensity_str)
                            if 0 <= saved_intensity <= 1:
                                self._intensity = saved_intensity
                        except ValueError:
                            pass
                except Exception:
                    # 配置读取失败不影响初始化
                    pass
            
            self._last_updated = time.time()
            self._initialized = True
        
        self._start_decay_loop()
    
    def get_state(self) -> EmotionState:
        """获取当前情绪状态"""
        with self._lock:
            return EmotionState(
                type=self._current,
                intensity=self._intensity,
                last_updated=self._last_updated,
            )
    
    @property
    def current_type(self) -> str:
        """当前情绪类型 (供 Prompt 注入)"""
        return self.get_state().type
    
    @property
    def current_intensity(self) -> float:
        """当前情绪强度"""
        return self.get_state().intensity
    
    def set_emotion(self, emotion_type: str, intensity: float = 0.8) -> None:
        """
        更新情绪状态并持久化 (防抖)
        
        Args:
            emotion_type: 情绪类型
            intensity: 强度 0.0 ~ 1.0
        """
        if not EmotionTypes.is_valid(emotion_type):
            raise ValueError(f"未知的情绪类型：{emotion_type}")
        
        now = time.time()
        
        with self._lock:
            self._current = emotion_type
            self._intensity = max(0.0, min(1.0, intensity))  # Clamp to [0, 1]
            self._last_updated = now
        
        # 触发回调
        state = self.get_state()
        for callback in self._changed_callbacks:
            try:
                callback(state)
            except Exception:
                pass
        
        # 请求表情映射
        self._request_expression(emotion_type)
        
        # 调度持久化
        self._schedule_persist()
    
    def _request_expression(self, emotion: str) -> None:
        """映射情绪到默认 Live2D 表情"""
        expression = EmotionTypes.get_default_expression(emotion)
        if expression:
            for callback in self._expression_callbacks:
                try:
                    callback(expression)
                except Exception:
                    pass
    
    def _schedule_persist(self) -> None:
        """防抖保存情绪状态到配置"""
        with self._lock:
            if self._persist_timer:
                self._persist_timer.cancel()
            
            if not self._config_store:
                return
            
            self._persist_timer = threading.Timer(
                self.PERSIST_DELAY_SECONDS,
                self._do_persist,
            )
            self._persist_timer.start()
    
    def _do_persist(self) -> None:
        """执行持久化"""
        try:
            state = self.get_state()
            if hasattr(self._config_store, 'set'):
                self._config_store.set("nori_emotion", state.type)
                self._config_store.set(
                    "nori_emotion_intensity",
                    f"{state.intensity:.7f}"
                )
        except Exception:
            # 持久化失败只影响下次启动的情绪恢复
            pass
    
    def _start_decay_loop(self) -> None:
        """启动自然衰减循环"""
        with self._lock:
            if self._decay_timer:
                self._decay_timer.cancel()
            
            self._decay_timer = threading.Timer(
                self.DECAY_INTERVAL_SECONDS,
                self._do_decay,
            )
            self._decay_timer.start()
    
    def _do_decay(self) -> None:
        """执行一次衰减"""
        changed = False
        
        with self._lock:
            if self._current == EmotionTypes.NEUTRAL:
                return
            
            self._intensity -= 0.1
            if self._intensity <= 0.1:
                self._current = EmotionTypes.NEUTRAL
                self._intensity = 0.5
            changed = True
        
        if changed:
            state = self.get_state()
            for callback in self._changed_callbacks:
                try:
                    callback(state)
                except Exception:
                    pass
            self._schedule_persist()
        
        # 继续下一轮衰减
        self._start_decay_loop()
    
    def tick_decay_for_tests(self) -> None:
        """测试辅助：手动推进一次衰减"""
        with self._lock:
            if self._current == EmotionTypes.NEUTRAL:
                return
            
            self._intensity -= 0.1
            if self._intensity <= 0.1:
                self._current = EmotionTypes.NEUTRAL
                self._intensity = 0.5
        
        state = self.get_state()
        for callback in self._changed_callbacks:
            try:
                callback(state)
            except Exception:
                pass
    
    def reset_to_neutral(self) -> None:
        """重置为中性情绪"""
        self.set_emotion(EmotionTypes.NEUTRAL, 0.5)
    
    def dispose(self) -> None:
        """释放资源"""
        with self._lock:
            if self._decay_timer:
                self._decay_timer.cancel()
                self._decay_timer = None
            if self._persist_timer:
                self._persist_timer.cancel()
                self._persist_timer = None


__all__ = [
    "EmotionTypes",
    "EmotionState",
    "EmotionManager",
]
