/**
 * @file live2d_renderer.h
 * @brief Live2D Cubism Renderer - High Performance C++ Implementation
 * 
 * This module provides hardware-accelerated Live2D rendering using OpenGL,
 * exposed to Python via pybind11 with zero-overhead abstractions.
 * 
 * Design Principles:
 * - High Cohesion: Single responsibility for rendering pipeline
 * - Low Coupling: Abstract interfaces for model/texture management
 * - RAII: Automatic resource management for OpenGL objects
 * - Thread Safety: GIL release during long-running render operations
 */

#pragma once

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/numpy.h>

#include <memory>
#include <vector>
#include <string>
#include <optional>

namespace nori::live2d {

// Forward declarations
class Live2DModel;
class TextureManager;
class OpenGLContext;

/**
 * @brief Rendering parameters for Live2D models
 */
struct RenderParams {
    float opacity = 1.0f;           // Model opacity (0.0-1.0)
    float scale_x = 1.0f;           // Horizontal scale
    float scale_y = 1.0f;           // Vertical scale
    float offset_x = 0.0f;          // Horizontal offset
    float offset_y = 0.0f;          // Vertical offset
    float rotation = 0.0f;          // Rotation in degrees
    bool flip_horizontal = false;   // Mirror horizontally
    bool flip_vertical = false;     // Mirror vertically
    
    // Matrix for advanced transformations
    std::array<float, 16> matrix{}; // 4x4 column-major matrix
};

/**
 * @brief Viewport configuration
 */
struct ViewportConfig {
    int width = 0;
    int height = 0;
    float left = -1.0f;
    float right = 1.0f;
    float bottom = -1.0f;
    float top = 1.0f;
};

/**
 * @brief Main Live2D renderer class
 * 
 * Manages the complete rendering pipeline including:
 * - Model loading and lifecycle
 * - Texture management
 * - OpenGL state management
 * - Frame rendering with parameter interpolation
 */
class Live2DRenderer {
public:
    /**
     * @brief Construct a new Live2D Renderer
     * @param context Shared OpenGL context
     */
    explicit Live2DRenderer(std::shared_ptr<OpenGLContext> context);
    
    /**
     * @brief Destructor - ensures proper cleanup of GPU resources
     */
    ~Live2DRenderer();
    
    // Non-copyable, movable
    Live2DRenderer(const Live2DRenderer&) = delete;
    Live2DRenderer& operator=(const Live2DRenderer&) = delete;
    Live2DRenderer(Live2DRenderer&&) noexcept = default;
    Live2DRenderer& operator=(Live2DRenderer&&) noexcept = default;
    
    /**
     * @brief Load a Live2D model from file
     * @param model_path Path to .model3.json file
     * @return true if loading succeeded
     */
    bool loadModel(const std::string& model_path);
    
    /**
     * @brief Unload current model and free resources
     */
    void unloadModel();
    
    /**
     * @brief Check if a model is currently loaded
     */
    bool hasModel() const noexcept;
    
    /**
     * @brief Update model state with new parameters
     * @param params Rendering parameters
     * @param delta_time Time since last update in seconds
     */
    void update(const RenderParams& params, float delta_time);
    
    /**
     * @brief Render the current model frame
     * @param viewport Viewport configuration
     * @return true if rendering succeeded
     */
    bool render(const ViewportConfig& viewport);
    
    /**
     * @brief Set model motion by name
     * @param motion_group Motion group (e.g., "Idle", "Tap")
     * @param motion_index Index within the group
     * @return true if motion was set successfully
     */
    bool setMotion(const std::string& motion_group, int motion_index);
    
    /**
     * @brief Set facial expression
     * @param expression_id Expression identifier
     * @return true if expression was set successfully
     */
    bool setExpression(const std::string& expression_id);
    
    /**
     * @brief Trigger lip sync for voice playback
     * @param volume Audio volume level (0.0-1.0)
     */
    void setLipSync(float volume);
    
    /**
     * @brief Set eye tracking target
     * @param x Normalized X coordinate (-1.0 to 1.0)
     * @param y Normalized Y coordinate (-1.0 to 1.0)
     */
    void setEyeTracking(float x, float y);
    
    /**
     * @brief Get available motion groups
     * @return Vector of motion group names
     */
    std::vector<std::string> getMotionGroups() const;
    
    /**
     * @brief Get model natural dimensions
     * @return Pair of {width, height} in model coordinates
     */
    std::pair<float, float> getModelDimensions() const;
    
    /**
     * @brief Initialize Cubism SDK (call once at application start)
     * @return true if initialization succeeded
     */
    static bool initialize();
    
    /**
     * @brief Shutdown Cubism SDK (call once at application exit)
     */
    static void shutdown();

private:
    std::shared_ptr<OpenGLContext> context_;
    std::unique_ptr<Live2DModel> current_model_;
    std::unique_ptr<TextureManager> texture_manager_;
    bool is_initialized_ = false;
};

/**
 * @brief Python binding function
 */
void bind_live2d_renderer(pybind11::module& m);

} // namespace nori::live2d
