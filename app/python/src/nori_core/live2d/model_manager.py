"""
Live2D Model Manager - High-level Python API for Live2D model management

This module provides a convenient Python interface for managing Live2D models,
wrapping the low-level C++ extension with additional features:
- Automatic resource management
- Parameter animation helpers
- Motion blending
- Expression system integration
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from . import Live2DRenderer, _CORE_AVAILABLE

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass
class ModelInfo:
    """Information about a loaded Live2D model."""
    
    id: int
    path: str
    loaded: bool = True
    parameter_count: int = 0
    drawable_count: int = 0
    current_motion_group: str | None = None
    is_moving: bool = False


@dataclass
class ParameterAnimation:
    """Represents an animated parameter transition."""
    
    param_id: str
    target_value: float
    duration: float
    start_value: float = 0.0
    start_time: float = field(default_factory=time.time)
    easing: str = "linear"  # linear, ease_in, ease_out, ease_in_out
    
    def get_current_value(self) -> float:
        """Get the current interpolated value."""
        elapsed = time.time() - self.start_time
        progress = min(elapsed / self.duration, 1.0)
        
        if self.easing == "ease_in":
            progress = progress * progress
        elif self.easing == "ease_out":
            progress = 1 - (1 - progress) * (1 - progress)
        elif self.easing == "ease_in_out":
            if progress < 0.5:
                progress = 2 * progress * progress
            else:
                progress = 1 - (-2 * progress + 2) ** 2 / 2
        
        return self.start_value + (self.target_value - self.start_value) * progress
    
    def is_finished(self) -> bool:
        """Check if animation is complete."""
        return time.time() - self.start_time >= self.duration


class Live2DModelManager:
    """
    High-level manager for Live2D models.
    
    Provides convenient methods for:
    - Loading and unloading models
    - Parameter manipulation with animation
    - Motion playback and blending
    - Automatic update loops
    """
    
    def __init__(self):
        self._renderer = Live2DRenderer()
        self._models: dict[int, ModelInfo] = {}
        self._animations: dict[int, list[ParameterAnimation]] = {}
        self._initialized = False
        self._gl_context: object | None = None
        
    @property
    def is_initialized(self) -> bool:
        """Check if the renderer is initialized."""
        return self._initialized
    
    @property
    def core_available(self) -> bool:
        """Check if native C++ extension is available."""
        return _CORE_AVAILABLE
    
    def initialize(self, gl_context: object = None) -> bool:
        """
        Initialize the Live2D renderer.
        
        Args:
            gl_context: OpenGL context handle from PyQt6 QOpenGLWidget
            
        Returns:
            True if initialization succeeded
        """
        if self._initialized:
            return True
            
        self._gl_context = gl_context
        self._initialized = self._renderer.initialize(gl_context)
        
        if self._initialized:
            print(f"Live2D Renderer initialized (core: {'native' if _CORE_AVAILABLE else 'mock'})")
            
        return self._initialized
    
    def load_model(self, model_path: str) -> int:
        """
        Load a Live2D model from disk.
        
        Args:
            model_path: Path to model directory (containing .model3.json)
            
        Returns:
            Model ID (>= 0) on success, -1 on failure
        """
        if not self._initialized:
            raise RuntimeError("Renderer not initialized. Call initialize() first.")
            
        model_id = self._renderer.load_model(model_path)
        
        if model_id >= 0:
            info = self._renderer.get_model_info(model_id)
            self._models[model_id] = ModelInfo(
                id=model_id,
                path=model_path,
                loaded=info.get("loaded", False),
                parameter_count=info.get("parameter_count", 0),
                drawable_count=info.get("drawable_count", 0),
            )
            self._animations[model_id] = []
            print(f"Loaded model {model_id} from {model_path}")
        else:
            print(f"Failed to load model from {model_path}")
            
        return model_id
    
    def unload_model(self, model_id: int) -> None:
        """Unload a model and free its resources."""
        self._renderer.unload_model(model_id)
        self._models.pop(model_id, None)
        self._animations.pop(model_id, None)
        
    def get_model(self, model_id: int) -> ModelInfo | None:
        """Get information about a loaded model."""
        return self._models.get(model_id)
    
    def get_all_models(self) -> list[ModelInfo]:
        """Get all loaded models."""
        return list(self._models.values())
    
    def set_parameter(self, model_id: int, param_id: str, value: float) -> None:
        """
        Set a model parameter value immediately.
        
        Args:
            model_id: Model ID
            param_id: Parameter ID (e.g., "ParamAngleX")
            value: Parameter value (-1.0 to 1.0)
        """
        if model_id not in self._models:
            return
        self._renderer.set_parameter_value(model_id, param_id, value)
        
    def animate_parameter(
        self,
        model_id: int,
        param_id: str,
        target_value: float,
        duration: float = 0.5,
        easing: str = "linear",
    ) -> None:
        """
        Animate a parameter to a target value over time.
        
        Args:
            model_id: Model ID
            param_id: Parameter ID
            target_value: Target value (-1.0 to 1.0)
            duration: Animation duration in seconds
            easing: Easing function (linear, ease_in, ease_out, ease_in_out)
        """
        if model_id not in self._models:
            return
            
        # Remove existing animation for same parameter
        animations = self._animations[model_id]
        self._animations[model_id] = [
            a for a in animations if a.param_id != param_id
        ]
        
        # Get current value as start value
        # (In a real implementation, we'd query the current value from the model)
        animation = ParameterAnimation(
            param_id=param_id,
            target_value=target_value,
            duration=duration,
            start_value=0.0,  # Should query actual current value
            easing=easing,
        )
        self._animations[model_id].append(animation)
        
    def update(self, model_id: int, delta_time: float) -> None:
        """
        Update model state and process animations.
        
        Args:
            model_id: Model ID
            delta_time: Time since last update in seconds
        """
        if model_id not in self._models:
            return
            
        # Process parameter animations
        animations = self._animations.get(model_id, [])
        finished = []
        
        for anim in animations:
            if anim.is_finished():
                # Apply final value
                self._renderer.set_parameter_value(
                    model_id, anim.param_id, anim.target_value
                )
                finished.append(anim)
            else:
                # Apply interpolated value
                value = anim.get_current_value()
                self._renderer.set_parameter_value(model_id, anim.param_id, value)
                
        # Remove finished animations
        for anim in finished:
            animations.remove(anim)
            
        # Update model physics and internal state
        self._renderer.update(model_id, delta_time)
        
    def start_motion(
        self,
        model_id: int,
        motion_group: str,
        motion_index: int = 0,
        priority: int = 0,
    ) -> bool:
        """
        Start playing a motion animation.
        
        Args:
            model_id: Model ID
            motion_group: Motion group name (e.g., "Idle", "TapBody")
            motion_index: Index within the group
            priority: Priority level (higher overrides lower)
            
        Returns:
            True if motion started successfully
        """
        if model_id not in self._models:
            return False
            
        success = self._renderer.start_motion(model_id, motion_group, motion_index)
        
        if success:
            model = self._models[model_id]
            model.current_motion_group = motion_group
            model.is_moving = True
            
        return success
    
    def render(self, model_id: int, projection_matrix: list[list[float]]) -> None:
        """
        Render a model with the given projection matrix.
        
        Args:
            model_id: Model ID
            projection_matrix: 4x4 projection matrix
        """
        if model_id not in self._models:
            return
        self._renderer.render(model_id, projection_matrix)
        
    def release(self) -> None:
        """Release all resources and shutdown the renderer."""
        for model_id in list(self._models.keys()):
            self.unload_model(model_id)
        self._renderer.release()
        self._initialized = False
        self._gl_context = None


__all__ = [
    "Live2DModelManager",
    "ModelInfo",
    "ParameterAnimation",
]
