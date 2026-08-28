"""
Emotion Manager - Manages character emotion state with persistence and decay.

High Cohesion: Single responsibility for emotion lifecycle
Low Coupling: Depends only on ConfigStore interface
Type Safety: Full type hints with validation
Async Design: Non-blocking I/O with asyncio timers
"""

from __future__ import annotations

import asyncio
from typing import Optional, Callable, Final
from dataclasses import dataclass
from enum import Enum

from ..configuration.config_store import ConfigStore


class EmotionTypes:
    """Eight basic emotion types."""
    
    NEUTRAL: Final[str] = "neutral"
    HAPPY: Final[str] = "happy"
    SAD: Final[str] = "sad"
    ANGRY: Final[str] = "angry"
    SURPRISED: Final[str] = "surprised"
    SHY: Final[str] = "shy"
    SLEEPY: Final[str] = "sleepy"
    FOND: Final[str] = "fond"
    
    ALL: Final[list[str]] = [
        NEUTRAL, HAPPY, SAD, ANGRY, SURPRISED, SHY, SLEEPY, FOND
    ]
    
    @classmethod
    def is_valid(cls, value: str) -> bool:
        """Check if a string is a valid emotion type."""
        return value in cls.ALL


@dataclass
class EmotionState:
    """
    Emotion state description.
    
    Attributes:
        type: Emotion type identifier
        intensity: Intensity level from 0.0 to 1.0
        last_updated: Last update timestamp (milliseconds since epoch)
    """
    type: str
    intensity: float = 0.5
    last_updated: int = 0


class EmotionManager:
    """
    Emotion state manager with persistence and natural decay.
    
    Features:
    - Configurable decay interval (default 20 seconds)
    - Intensity decays by 0.1 per interval
    - Returns to neutral when intensity reaches zero
    - Expression mapping requests for Live2D integration
    - Debounced persistence (400ms)
    
    Events:
        changed: Emitted when emotion state changes
        expression_requested: Emitted to request Live2D expression
    """
    
    # Natural decay interval in seconds (consistent with frontend)
    DECAY_INTERVAL_SECONDS: Final[int] = 20
    
    # Persistence debounce delay in milliseconds
    PERSIST_DEBOUNCE_MS: Final[int] = 400
    
    def __init__(self, config_store: ConfigStore):
        """
        Initialize emotion manager.
        
        Args:
            config_store: Configuration store for persistence
        """
        self._config = config_store
        self._lock = asyncio.Lock()
        
        self._current = EmotionTypes.NEUTRAL
        self._intensity = 0.5
        self._last_updated = 0
        self._initialized = False
        
        self._decay_timer: Optional[asyncio.Task] = None
        self._persist_timer: Optional[asyncio.Task] = None
        self._running = False
        
        # Event callbacks
        self._changed_callbacks: list[Callable[[EmotionState], None]] = []
        self._expression_callbacks: list[Callable[[str], None]] = []
    
    def on_changed(self, callback: Callable[[EmotionState], None]) -> None:
        """Register callback for emotion state changes."""
        self._changed_callbacks.append(callback)
    
    def on_expression_requested(self, callback: Callable[[str], None]) -> None:
        """Register callback for Live2D expression requests."""
        self._expression_callbacks.append(callback)
    
    async def initialize(self) -> None:
        """Restore persisted emotion state from configuration."""
        async with self._lock:
            if self._initialized:
                return
            
            # Load saved emotion state
            saved_type = await self._config.get_string_or("nori_emotion", "")
            saved_intensity_str = await self._config.get_string_or(
                "nori_emotion_intensity", ""
            )
            
            if saved_type and EmotionTypes.is_valid(saved_type):
                self._current = saved_type
            
            try:
                saved_intensity = float(saved_intensity_str)
                if 0.0 <= saved_intensity <= 1.0:
                    self._intensity = saved_intensity
            except (ValueError, TypeError):
                pass
            
            self._last_updated = asyncio.get_event_loop().time() * 1000
            self._initialized = True
            self._running = True
        
        # Start background decay loop
        self._start_decay_loop()
    
    def get_state(self) -> EmotionState:
        """Get current emotion state (thread-safe)."""
        return EmotionState(
            type=self._current,
            intensity=self._intensity,
            last_updated=int(self._last_updated)
        )
    
    @property
    def current_type(self) -> str:
        """Current emotion type for prompt injection."""
        return self.get_state().type
    
    async def set_emotion(self, emotion_type: str, intensity: float = 0.8) -> None:
        """
        Update emotion state with persistence.
        
        Args:
            emotion_type: New emotion type
            intensity: Intensity level (0.0-1.0), defaults to 0.8
            
        Raises:
            ValueError: If emotion_type is not valid
        """
        if not EmotionTypes.is_valid(emotion_type):
            raise ValueError(f"Unknown emotion type: {emotion_type}")
        
        now = asyncio.get_event_loop().time() * 1000
        
        async with self._lock:
            self._current = emotion_type
            self._intensity = max(0.0, min(1.0, intensity))
            self._last_updated = now
        
        # Notify listeners
        state = self.get_state()
        for callback in self._changed_callbacks:
            callback(state)
        
        # Request expression mapping
        self._request_expression(emotion_type)
        
        # Schedule debounced persistence
        self._schedule_persist()
    
    def _request_expression(self, emotion: str) -> None:
        """Map emotion to default Live2D expression."""
        expression_map = {
            EmotionTypes.HAPPY: "Smile",
            EmotionTypes.SAD: "Sad",
            EmotionTypes.ANGRY: "Angry",
            EmotionTypes.SURPRISED: "Surprised",
            EmotionTypes.SHY: "Shy",
            EmotionTypes.SLEEPY: "Sleepy",
            EmotionTypes.FOND: "Smile",
        }
        
        expression = expression_map.get(emotion, "")
        if expression:
            for callback in self._expression_callbacks:
                callback(expression)
    
    def _schedule_persist(self) -> None:
        """Schedule debounced persistence to database (400ms)."""
        # Cancel existing timer
        if self._persist_timer and not self._persist_timer.done():
            self._persist_timer.cancel()
        
        # Create new timer task
        self._persist_timer = asyncio.create_task(self._persist_delayed())
    
    async def _persist_delayed(self) -> None:
        """Wait for debounce delay then persist to database."""
        await asyncio.sleep(self.PERSIST_DEBOUNCE_MS / 1000.0)
        
        try:
            state = self.get_state()
            await self._config.set("nori_emotion", state.type)
            await self._config.set(
                "nori_emotion_intensity",
                f"{state.intensity:.7f}"
            )
        except Exception:
            # Persistence failure only affects next startup recovery
            pass
    
    def _start_decay_loop(self) -> None:
        """Start background decay timer."""
        self._decay_timer = asyncio.create_task(self._decay_worker())
    
    async def _decay_worker(self) -> None:
        """Background worker for natural emotion decay."""
        while self._running:
            await asyncio.sleep(self.DECAY_INTERVAL_SECONDS)
            
            if not self._running:
                break
            
            changed = False
            async with self._lock:
                if self._current == EmotionTypes.NEUTRAL:
                    continue
                
                self._intensity -= 0.1
                if self._intensity <= 0.1:
                    self._current = EmotionTypes.NEUTRAL
                    self._intensity = 0.5
                changed = True
            
            if changed:
                state = self.get_state()
                for callback in self._changed_callbacks:
                    callback(state)
                self._schedule_persist()
    
    def tick_decay_for_tests(self) -> None:
        """Test helper: manually advance one decay step."""
        if self._current == EmotionTypes.NEUTRAL:
            return
        
        self._intensity -= 0.1
        if self._intensity <= 0.1:
            self._current = EmotionTypes.NEUTRAL
            self._intensity = 0.5
    
    async def shutdown(self) -> None:
        """Shutdown emotion manager and cleanup timers."""
        self._running = False
        
        if self._decay_timer and not self._decay_timer.done():
            self._decay_timer.cancel()
            try:
                await self._decay_timer
            except asyncio.CancelledError:
                pass
        
        if self._persist_timer and not self._persist_timer.done():
            self._persist_timer.cancel()
            try:
                await self._persist_timer
            except asyncio.CancelledError:
                pass
