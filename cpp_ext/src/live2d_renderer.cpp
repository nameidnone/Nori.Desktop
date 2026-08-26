/**
 * @file live2d_renderer.cpp
 * @brief Live2D Renderer Implementation
 * 
 * Implements hardware-accelerated Live2D rendering with:
 * - OpenGL texture management
 * - Cubism Core integration
 * - Motion interpolation
 * - Expression blending
 * 
 * Performance targets:
 * - 60 FPS at 1080p with single model
 * - <5ms frame time including physics simulation
 * - Zero heap allocations during render loop
 */

#include "live2d_renderer.h"
#include "live2d_model.h"
#include "live2d_texture_manager.h"
#include "opengl_context.h"

#include <CubismFramework.hpp>
#include <Model/CubismModel.hpp>
#include <Rendering/OpenGL/CubismRenderer_OpenGL_ES2.hpp>

#include <chrono>
#include <stdexcept>

namespace py = pybind11;

namespace nori::live2d {

// Static initialization flag
static bool g_cubism_initialized = false;

// ============================================================================
// Static Methods
// ============================================================================

bool Live2DRenderer::initialize() {
    if (g_cubism_initialized) {
        return true;
    }
    
    // Initialize Cubism Framework
    Csm::CubismFramework::StartUp();
    Csm::CubismFramework::Initialize();
    
    g_cubism_initialized = true;
    return true;
}

void Live2DRenderer::shutdown() {
    if (!g_cubism_initialized) {
        return;
    }
    
    Csm::CubismFramework::Dispose();
    Csm::CubismFramework::CleanUp();
    
    g_cubism_initialized = false;
}

// ============================================================================
// Constructor/Destructor
// ============================================================================

Live2DRenderer::Live2DRenderer(std::shared_ptr<OpenGLContext> context)
    : context_(std::move(context))
    , is_initialized_(false) {
    
    if (!context_) {
        throw std::invalid_argument("OpenGL context cannot be null");
    }
    
    if (!g_cubism_initialized) {
        throw std::runtime_error("Cubism SDK not initialized. Call Live2DRenderer::initialize() first.");
    }
    
    texture_manager_ = std::make_unique<TextureManager>();
    is_initialized_ = true;
}

Live2DRenderer::~Live2DRenderer() {
    unloadModel();
    texture_manager_.reset();
}

// ============================================================================
// Model Management
// ============================================================================

bool Live2DRenderer::loadModel(const std::string& model_path) {
    if (!is_initialized_) {
        return false;
    }
    
    // Unload existing model first
    unloadModel();
    
    try {
        current_model_ = std::make_unique<Live2DModel>(model_path, texture_manager_.get());
        
        if (!current_model_->isValid()) {
            current_model_.reset();
            return false;
        }
        
        return true;
    } catch (const std::exception& e) {
        current_model_.reset();
        return false;
    }
}

void Live2DRenderer::unloadModel() {
    if (current_model_) {
        current_model_.reset();
    }
    if (texture_manager_) {
        texture_manager_->clear();
    }
}

bool Live2DRenderer::hasModel() const noexcept {
    return current_model_ != nullptr && current_model_->isValid();
}

// ============================================================================
// Update & Render Loop
// ============================================================================

void Live2DRenderer::update(const RenderParams& params, float delta_time) {
    if (!current_model_) {
        return;
    }
    
    // Release GIL for potentially long-running operations
    py::gil_scoped_release release;
    
    // Apply transformation parameters
    auto* cubism_model = current_model_->getCubismModel();
    if (!cubism_model) {
        return;
    }
    
    // Set opacity
    cubism_model->SetOpacity(params.opacity);
    
    // Build transformation matrix
    Csm::CubismMatrix44 matrix;
    matrix.Scale(params.scale_x, params.scale_y);
    matrix.RotateDegrees(params.rotation);
    matrix.Translate(params.offset_x, params.offset_y);
    
    if (params.flip_horizontal) {
        matrix.Scale(-1.0f, 1.0f);
    }
    if (params.flip_vertical) {
        matrix.Scale(1.0f, -1.0f);
    }
    
    // Apply custom matrix if provided
    if (params.matrix[0] != 0.0f || params.matrix[5] != 0.0f) {
        Csm::CubismMatrix44 custom_matrix;
        custom_matrix.SetMatrix(params.matrix.data());
        matrix.MultiplyByMatrix(custom_matrix);
    }
    
    current_model_->setModelMatrix(matrix);
    
    // Update model physics and dynamics
    current_model_->update(delta_time);
}

bool Live2DRenderer::render(const ViewportConfig& viewport) {
    if (!current_model_) {
        return false;
    }
    
    // Release GIL during rendering
    py::gil_scoped_release release;
    
    // Setup OpenGL viewport
    glViewport(0, 0, viewport.width, viewport.height);
    glClearColor(0.0f, 0.0f, 0.0f, 0.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    
    // Enable alpha blending
    glEnable(GL_BLEND);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
    
    // Setup projection matrix
    Csm::CubismProjectionMatrix projection_matrix;
    projection_matrix.PerspectiveOrthographic(
        viewport.left, viewport.right,
        viewport.bottom, viewport.top
    );
    
    // Render the model
    auto renderer = current_model_->getRenderer();
    if (!renderer) {
        return false;
    }
    
    renderer->SetMvpMatrix(&projection_matrix);
    renderer->Draw();
    
    return true;
}

// ============================================================================
// Motion & Expression Control
// ============================================================================

bool Live2DRenderer::setMotion(const std::string& motion_group, int motion_index) {
    if (!current_model_) {
        return false;
    }
    
    return current_model_->startMotion(motion_group, motion_index);
}

bool Live2DRenderer::setExpression(const std::string& expression_id) {
    if (!current_model_) {
        return false;
    }
    
    return current_model_->setExpression(expression_id);
}

void Live2DRenderer::setLipSync(float volume) {
    if (!current_model_) {
        return;
    }
    
    current_model_->setLipSync(volume);
}

void Live2DRenderer::setEyeTracking(float x, float y) {
    if (!current_model_) {
        return;
    }
    
    current_model_->setEyeTracking(x, y);
}

// ============================================================================
// Query Methods
// ============================================================================

std::vector<std::string> Live2DRenderer::getMotionGroups() const {
    if (!current_model_) {
        return {};
    }
    
    return current_model_->getAvailableMotionGroups();
}

std::pair<float, float> Live2DRenderer::getModelDimensions() const {
    if (!current_model_) {
        return {0.0f, 0.0f};
    }
    
    return current_model_->getDimensions();
}

// ============================================================================
// Python Bindings
// ============================================================================

void bind_live2d_renderer(py::module& m) {
    // Create submodule
    auto live2d = m.def_submodule("live2d", "Live2D Cubism Rendering Engine");
    
    // Expose RenderParams struct
    py::class_<RenderParams>(live2d, "RenderParams")
        .def(py::init<>())
        .def_readwrite("opacity", &RenderParams::opacity)
        .def_readwrite("scale_x", &RenderParams::scale_x)
        .def_readwrite("scale_y", &RenderParams::scale_y)
        .def_readwrite("offset_x", &RenderParams::offset_x)
        .def_readwrite("offset_y", &RenderParams::offset_y)
        .def_readwrite("rotation", &RenderParams::rotation)
        .def_readwrite("flip_horizontal", &RenderParams::flip_horizontal)
        .def_readwrite("flip_vertical", &RenderParams::flip_vertical)
        .def_readwrite("matrix", &RenderParams::matrix)
        .def("__repr__", [](const RenderParams& p) {
            return "<RenderParams opacity=" + std::to_string(p.opacity) + ">";
        });
    
    // Expose ViewportConfig struct
    py::class_<ViewportConfig>(live2d, "ViewportConfig")
        .def(py::init<>())
        .def_readwrite("width", &ViewportConfig::width)
        .def_readwrite("height", &ViewportConfig::height)
        .def_readwrite("left", &ViewportConfig::left)
        .def_readwrite("right", &ViewportConfig::right)
        .def_readwrite("bottom", &ViewportConfig::bottom)
        .def_readwrite("top", &ViewportConfig::top)
        .def("__repr__", [](const ViewportConfig& v) {
            return "<ViewportConfig " + std::to_string(v.width) + "x" + std::to_string(v.height) + ">";
        });
    
    // Expose Live2DRenderer class
    py::class_<Live2DRenderer, std::shared_ptr<Live2DRenderer>>(live2d, "Renderer")
        .def_static("initialize", &Live2DRenderer::initialize,
            "Initialize Cubism SDK (call once at startup)")
        .def_static("shutdown", &Live2DRenderer::shutdown,
            "Shutdown Cubism SDK (call once at exit)")
        .def(py::init<std::shared_ptr<OpenGLContext>>(),
            py::arg("context"),
            "Create renderer with OpenGL context")
        .def("load_model", &Live2DRenderer::loadModel,
            py::arg("model_path"),
            "Load Live2D model from .model3.json file")
        .def("unload_model", &Live2DRenderer::unloadModel,
            "Unload current model and free resources")
        .def("has_model", &Live2DRenderer::hasModel,
            "Check if model is loaded")
        .def("update", &Live2DRenderer::update,
            py::arg("params"),
            py::arg("delta_time"),
            "Update model state")
        .def("render", &Live2DRenderer::render,
            py::arg("viewport"),
            "Render current frame")
        .def("set_motion", &Live2DRenderer::setMotion,
            py::arg("motion_group"),
            py::arg("motion_index"),
            "Set animation motion")
        .def("set_expression", &Live2DRenderer::setExpression,
            py::arg("expression_id"),
            "Set facial expression")
        .def("set_lip_sync", &Live2DRenderer::setLipSync,
            py::arg("volume"),
            "Enable lip sync with audio volume")
        .def("set_eye_tracking", &Live2DRenderer::setEyeTracking,
            py::arg("x"),
            py::arg("y"),
            "Track eye position")
        .def("get_motion_groups", &Live2DRenderer::getMotionGroups,
            "Get available motion groups")
        .def("get_model_dimensions", &Live2DRenderer::getModelDimensions,
            "Get natural model dimensions");
}

} // namespace nori::live2d
