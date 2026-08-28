"""
Nori Core Live2D Module - Python bindings for Live2D Cubism Renderer

This module provides Python interfaces to the Live2D C++ extension:
- Model loading and management
- Parameter manipulation
- Motion playback
- Rendering integration with OpenGL/PyQt6
"""

from __future__ import annotations

try:
    from .live2d_core import (
        Live2DRenderer,
        get_version,
        cubism_core_version,
    )
    _CORE_AVAILABLE = True
except ImportError:
    _CORE_AVAILABLE = False
    
    class Live2DRenderer:
        """Mock Live2DRenderer for development without compiled extension."""
        
        def __init__(self):
            self._models = {}
            self._initialized = False
            
        def initialize(self, gl_context: object = None) -> bool:
            """Initialize the renderer with OpenGL context."""
            self._initialized = True
            return True
            
        def load_model(self, model_path: str) -> int:
            """Load a Live2D model from path. Returns model ID or -1 on failure."""
            if not self._initialized:
                raise RuntimeError("Renderer not initialized")
            model_id = len(self._models)
            self._models[model_id] = {
                "path": model_path,
                "loaded": True,
                "parameter_count": 50,
                "drawable_count": 20,
            }
            return model_id
            
        def unload_model(self, model_id: int) -> None:
            """Unload a Live2D model."""
            self._models.pop(model_id, None)
            
        def update(self, model_id: int, delta_time: float) -> None:
            """Update model state."""
            pass
            
        def render(self, model_id: int, matrix: list[list[float]]) -> None:
            """Render the model with projection matrix."""
            pass
            
        def set_parameter_value(self, model_id: int, param_id: str, value: float) -> None:
            """Set model parameter value (-1.0 to 1.0)."""
            pass
            
        def start_motion(self, model_id: int, motion_group: str, motion_index: int) -> bool:
            """Start a motion animation. Returns True on success."""
            return True
            
        def get_model_info(self, model_id: int) -> dict:
            """Get model metadata."""
            return self._models.get(model_id, {})
            
        def release(self) -> None:
            """Release all resources."""
            self._models.clear()
            self._initialized = False
    
    def get_version() -> str:
        return "1.0.0-mock"
    
    def cubism_core_version() -> str:
        return "mock-1.0.0"


__all__ = [
    "Live2DRenderer",
    "get_version",
    "cubism_core_version",
    "_CORE_AVAILABLE",
]

__version__ = "1.0.0"
