"""
Live2D OpenGL Widget - PyQt6 integration for Live2D rendering

This module provides a QOpenGLWidget subclass that renders Live2D models
with proper OpenGL context management and frame timing.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from .model_manager import Live2DModelManager, ModelInfo

if TYPE_CHECKING:
    from PyQt6.QtGui import QMouseEvent
    from PyQt6.QtCore import QPointF


class Live2DWidgetBase:
    """
    Base class for Live2D rendering widgets.
    
    This is a pure Python implementation that can be used with:
    - PyQt6 QOpenGLWidget (desktop)
    - Any other OpenGL context provider
    
    Example usage with PyQt6:
    
        class Live2DOpenGLWidget(QOpenGLWidget, Live2DWidgetBase):
            def initializeGL(self):
                super().initializeGL()
                self.initialize_live2d()
                
            def paintGL(self):
                self.render_live2d()
                
            def mousePressEvent(self, event):
                self.handle_touch(event.pos())
    """
    
    def __init__(self):
        self._model_manager = Live2DModelManager()
        self._last_frame_time = time.time()
        self._delta_time = 0.0
        self._touch_position: tuple[float, float] | None = None
        self._is_dragging = False
        
        # Callbacks
        self.on_model_loaded: callable | None = None
        self.on_motion_finished: callable | None = None
        self.on_tap: callable | None = None
        
    @property
    def model_manager(self) -> Live2DModelManager:
        """Get the underlying model manager."""
        return self._model_manager
    
    @property
    def delta_time(self) -> float:
        """Get time since last frame in seconds."""
        return self._delta_time
    
    def initialize_live2d(self, gl_context: object = None) -> bool:
        """
        Initialize Live2D renderer.
        
        Args:
            gl_context: OpenGL context (usually self in QOpenGLWidget)
            
        Returns:
            True if initialization succeeded
        """
        return self._model_manager.initialize(gl_context)
    
    def load_model(self, model_path: str) -> int:
        """
        Load a Live2D model.
        
        Args:
            model_path: Path to model directory
            
        Returns:
            Model ID or -1 on failure
        """
        model_id = self._model_manager.load_model(model_path)
        
        if model_id >= 0 and self.on_model_loaded:
            self.on_model_loaded(model_id)
            
        return model_id
    
    def unload_model(self, model_id: int) -> None:
        """Unload a model."""
        self._model_manager.unload_model(model_id)
        
    def update_frame(self) -> None:
        """
        Update all models for one frame.
        Call this from your render loop.
        """
        current_time = time.time()
        self._delta_time = current_time - self._last_frame_time
        self._last_frame_time = current_time
        
        for model_info in self._model_manager.get_all_models():
            self._model_manager.update(model_info.id, self._delta_time)
            
            # Check if motion finished
            if model_info.is_moving and model_info.current_motion_group:
                # In a real implementation, we'd check actual motion state
                # For now, just mark as not moving after some time
                pass
                
    def render_frame(self, projection_matrix: list[list[float]]) -> None:
        """
        Render all loaded models.
        
        Args:
            projection_matrix: 4x4 projection matrix
        """
        for model_info in self._model_manager.get_all_models():
            self._model_manager.render(model_info.id, projection_matrix)
            
    def handle_touch(self, x: float, y: float, is_press: bool = True) -> None:
        """
        Handle touch/click interaction.
        
        Args:
            x: X coordinate (normalized -1 to 1)
            y: Y coordinate (normalized -1 to 1)
            is_press: True for press, False for release
        """
        if is_press:
            self._touch_position = (x, y)
            self._is_dragging = True
            
            # Check for tap on each model
            for model_info in self._model_manager.get_all_models():
                # Simple bounding box check (should be improved)
                if self._is_point_in_model(x, y, model_info):
                    if self.on_tap:
                        self.on_tap(model_info.id, x, y)
                    # Trigger tap motion
                    self._model_manager.start_motion(model_info.id, "TapBody", 0)
        else:
            self._is_dragging = False
            self._touch_position = None
            
    def handle_drag(self, x: float, y: float) -> None:
        """
        Handle drag interaction.
        
        Args:
            x: X coordinate (normalized -1 to 1)
            y: Y coordinate (normalized -1 to 1)
        """
        if not self._is_dragging:
            return
            
        dx = x - (self._touch_position[0] if self._touch_position else 0)
        dy = y - (self._touch_position[1] if self._touch_position else 0)
        
        # Update eye and head parameters based on drag
        for model_info in self._model_manager.get_all_models():
            self._model_manager.set_parameter(model_info.id, "ParamAngleX", dx * 30)
            self._model_manager.set_parameter(model_info.id, "ParamAngleY", dy * 30)
            self._model_manager.set_parameter(model_info.id, "ParamEyeBallX", dx)
            self._model_manager.set_parameter(model_info.id, "ParamEyeBallY", dy)
            
    def _is_point_in_model(self, x: float, y: float, model_info: ModelInfo) -> bool:
        """
        Check if a point is within the model's bounds.
        
        This is a simplified implementation. A real implementation would
        use the model's actual canvas bounds from model3.json.
        """
        # Default bounds: -1 to 1 in both axes
        return -1 <= x <= 1 and -1 <= y <= 1
    
    def set_parameter(self, model_id: int, param_id: str, value: float) -> None:
        """Set a model parameter directly."""
        self._model_manager.set_parameter(model_id, param_id, value)
        
    def start_motion(
        self,
        model_id: int,
        motion_group: str,
        motion_index: int = 0,
    ) -> bool:
        """Start a motion animation."""
        return self._model_manager.start_motion(model_id, motion_group, motion_index)
        
    def get_projection_matrix(
        self,
        width: int,
        height: int,
        left: float = -1.0,
        right: float = 1.0,
        bottom: float = -1.0,
        top: float = 1.0,
    ) -> list[list[float]]:
        """
        Create an orthographic projection matrix.
        
        Args:
            width: Viewport width
            height: Viewport height
            left: Left plane
            right: Right plane
            bottom: Bottom plane
            top: Top plane
            
        Returns:
            4x4 projection matrix as nested lists
        """
        # Orthographic projection matrix
        return [
            [2.0 / (right - left), 0, 0, -(right + left) / (right - left)],
            [0, 2.0 / (top - bottom), 0, -(top + bottom) / (top - bottom)],
            [0, 0, -2.0 / (1.0 - 0.0), -(1.0 + 0.0) / (1.0 - 0.0)],
            [0, 0, 0, 1],
        ]
        
    def cleanup(self) -> None:
        """Release all resources."""
        self._model_manager.release()


__all__ = ["Live2DWidgetBase"]
