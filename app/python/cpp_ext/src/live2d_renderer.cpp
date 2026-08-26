/**
 * Live2D 渲染器 C++ 扩展 - pybind11 绑定入口
 * 
 * 性能关键部分：Live2D 模型加载、更新、渲染
 * 使用 OpenGL ES 2.0 进行硬件加速渲染
 * 通过 pybind11 暴露给 Python，零开销抽象
 */

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/numpy.h>

#include "live2d_model_wrapper.h"
#include "live2d_texture_manager.h"
#include "opengl_bindings.h"

namespace py = pybind11;

/**
 * Live2D 渲染器主类
 * 管理多个 Live2D 模型的生命周期和渲染
 */
class Live2DRenderer {
public:
    Live2DRenderer() : initialized_(false), gl_context_valid_(false) {}
    
    ~Live2DRenderer() {
        release();
    }
    
    /**
     * 初始化渲染器
     * @param gl_context OpenGL 上下文句柄 (由 PyQt6 QOpenGLWidget 提供)
     */
    bool initialize(void* gl_context) {
        if (initialized_) return true;
        
        // 初始化 OpenGL 函数指针
        if (!loadOpenGLFunctions(gl_context)) {
            return false;
        }
        
        // 初始化 Live2D Cubism Core
        if (!cubism_core_init()) {
            return false;
        }
        
        texture_manager_ = std::make_unique<Live2DTextureManager>();
        initialized_ = true;
        return true;
    }
    
    /**
     * 加载 Live2D 模型
     * @param model_path 模型目录路径 (.model3.json 所在目录)
     * @return 模型 ID，失败返回 -1
     */
    int loadModel(const std::string& model_path) {
        if (!initialized_) {
            throw std::runtime_error("Renderer not initialized");
        }
        
        auto model = std::make_unique<Live2DModelWrapper>();
        int model_id = next_model_id_++;
        
        if (!model->load(model_path, texture_manager_.get())) {
            return -1;
        }
        
        models_[model_id] = std::move(model);
        return model_id;
    }
    
    /**
     * 卸载模型
     * @param model_id 模型 ID
     */
    void unloadModel(int model_id) {
        models_.erase(model_id);
    }
    
    /**
     * 更新模型状态
     * @param model_id 模型 ID
     * @param delta_time 距离上一帧的时间 (秒)
     */
    void update(int model_id, double delta_time) {
        auto it = models_.find(model_id);
        if (it != models_.end()) {
            it->second->update(delta_time);
        }
    }
    
    /**
     * 渲染模型
     * @param model_id 模型 ID
     * @param matrix 投影矩阵 (4x4)
     */
    void render(int model_id, py::array_t<float>& matrix) {
        auto it = models_.find(model_id);
        if (it == models_.end()) return;
        
        auto buf = matrix.request();
        if (buf.ndim != 2 || buf.shape[0] != 4 || buf.shape[1] != 4) {
            throw std::invalid_argument("Matrix must be 4x4");
        }
        
        float* mat_ptr = static_cast<float*>(buf.ptr);
        it->second->render(mat_ptr);
    }
    
    /**
     * 设置模型参数
     * @param model_id 模型 ID
     * @param param_id 参数 ID (如 "ParamAngleX")
     * @param value 参数值 (-1.0 到 1.0)
     */
    void setParameterValue(int model_id, const std::string& param_id, float value) {
        auto it = models_.find(model_id);
        if (it != models_.end()) {
            it->second->setParameterValue(param_id, value);
        }
    }
    
    /**
     * 触发动作
     * @param model_id 模型 ID
     * @param motion_group 动作组 (如 "Idle", "TapBody")
     * @param motion_index 动作索引
     * @return 是否成功触发
     */
    bool startMotion(int model_id, const std::string& motion_group, int motion_index) {
        auto it = models_.find(model_id);
        if (it == models_.end()) return false;
        return it->second->startMotion(motion_group, motion_index);
    }
    
    /**
     * 获取模型信息
     * @param model_id 模型 ID
     * @return 模型元数据字典
     */
    py::dict getModelInfo(int model_id) {
        auto it = models_.find(model_id);
        if (it == models_.end()) {
            return py::dict();
        }
        
        py::dict info;
        info["id"] = model_id;
        info["loaded"] = true;
        info["parameter_count"] = it->second->getParameterCount();
        info["drawable_count"] = it->second->getDrawableCount();
        return info;
    }
    
    /**
     * 释放所有资源
     */
    void release() {
        models_.clear();
        texture_manager_.reset();
        initialized_ = false;
    }
    
    /**
     * 获取 OpenGL 纹理管理器
     */
    Live2DTextureManager* getTextureManager() {
        return texture_manager_.get();
    }

private:
    bool initialized_;
    bool gl_context_valid_;
    int next_model_id_ = 0;
    std::map<int, std::unique_ptr<Live2DModelWrapper>> models_;
    std::unique_ptr<Live2DTextureManager> texture_manager_;
};

/**
 * pybind11 模块定义
 */
PYBIND11_MODULE(live2d_core, m) {
    m.doc() = "Live2D Cubism Renderer - High Performance C++ Extension";
    
    py::class_<Live2DRenderer>(m, "Live2DRenderer")
        .def(py::init<>())
        .def("initialize", &Live2DRenderer::initialize, 
             py::call_guard<py::gil_scoped_release>(),
             "Initialize the renderer with OpenGL context")
        .def("load_model", &Live2DRenderer::loadModel,
             py::call_guard<py::gil_scoped_release>(),
             "Load a Live2D model from path")
        .def("unload_model", &Live2DRenderer::unloadModel,
             "Unload a Live2D model")
        .def("update", &Live2DRenderer::update,
             py::call_guard<py::gil_scoped_release>(),
             "Update model state")
        .def("render", &Live2DRenderer::render,
             py::call_guard<py::gil_scoped_release>(),
             "Render the model")
        .def("set_parameter_value", &Live2DRenderer::setParameterValue,
             "Set model parameter value")
        .def("start_motion", &Live2DRenderer::startMotion,
             py::call_guard<py::gil_scoped_release>(),
             "Start a motion animation")
        .def("get_model_info", &Live2DRenderer::getModelInfo,
             "Get model metadata")
        .def("release", &Live2DRenderer::release,
             "Release all resources");
    
    // 导出工具函数
    m.def("get_version", []() {
        return std::string("1.0.0");
    }, "Get Live2D renderer version");
    
    m.def("cubism_core_version", []() {
        return cubism_core_get_version();
    }, "Get Cubism Core version");
}
