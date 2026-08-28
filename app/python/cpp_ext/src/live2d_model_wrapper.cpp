/**
 * Live2D 模型封装器实现
 * 
 * 封装 Live2D Cubism Core API，提供简洁的 C++ 接口
 */

#include "live2d_model_wrapper.h"
#include "live2d_texture_manager.h"

#include <fstream>
#include <sstream>
#include <cstring>

// Live2D Cubism Core 头文件（需要 SDK）
#ifdef HAVE_LIVE2D_CORE
#include <CubismFramework.hpp>
#include <Model/CubismModel.hpp>
#include <Rendering/CubismRenderer.hpp>
#endif

namespace {
    // 辅助函数：读取文件到内存
    std::vector<uint8_t> readFile(const std::string& path) {
        std::ifstream file(path, std::ios::binary | std::ios::ate);
        if (!file.is_open()) {
            return {};
        }
        
        auto size = file.tellg();
        file.seekg(0, std::ios::beg);
        
        std::vector<uint8_t> buffer(static_cast<size_t>(size));
        if (!file.read(reinterpret_cast<char*>(buffer.data()), size)) {
            return {};
        }
        
        return buffer;
    }
    
    // 辅助函数：读取 JSON 文件
    std::string readJsonFile(const std::string& path) {
        auto data = readFile(path);
        if (data.empty()) {
            return "";
        }
        return std::string(data.begin(), data.end());
    }
}

// ============================================================================
// Live2DModelWrapper::Impl - PIMPL 模式隐藏实现细节
// ============================================================================

struct Live2DModelWrapper::Impl {
#ifdef HAVE_LIVE2D_CORE
    Csm::CubismModel* model = nullptr;
    Csm::CubismRenderer* renderer = nullptr;
    bool is_loaded = false;
#endif
    
    std::string model_path;
    std::vector<uint32_t> texture_ids;
    int parameter_count = 0;
    int drawable_count = 0;
    
    ~Impl() {
        release();
    }
    
    void release() {
#ifdef HAVE_LIVE2D_CORE
        if (renderer) {
            delete renderer;
            renderer = nullptr;
        }
        if (model) {
            delete model;
            model = nullptr;
        }
#endif
        is_loaded = false;
        texture_ids.clear();
        parameter_count = 0;
        drawable_count = 0;
    }
};

// ============================================================================
// Live2DModelWrapper 实现
// ============================================================================

Live2DModelWrapper::Live2DModelWrapper() 
    : impl_(std::make_unique<Impl>()) {
}

Live2DModelWrapper::~Live2DModelWrapper() = default;

bool Live2DModelWrapper::load(const std::string& model_path, Live2DTextureManager* texture_manager) {
    if (!texture_manager) {
        return false;
    }
    
    impl_->release();
    impl_->model_path = model_path;
    
    // 读取 model3.json
    std::string model_json_path = model_path + "/model3.json";
    std::string model_json = readJsonFile(model_json_path);
    
    if (model_json.empty()) {
        // 尝试 .model3.json 后缀
        model_json_path = model_path + ".model3.json";
        model_json = readJsonFile(model_json_path);
        
        if (model_json.empty()) {
            return false;
        }
    }
    
#ifdef HAVE_LIVE2D_CORE
    // 使用 Live2D Cubism Core SDK 加载模型
    // 这里简化处理，实际需要完整的 Cubism SDK 集成
    
    // 加载 Moc 文件
    // 加载纹理
    // 创建 Model 和 Renderer
    
    impl_->is_loaded = true;
#else
    // 没有 SDK 时的模拟实现（用于开发测试）
    impl_->parameter_count = 50;  // 典型值
    impl_->drawable_count = 20;   // 典型值
    impl_->is_loaded = true;
#endif
    
    return impl_->is_loaded;
}

void Live2DModelWrapper::update(double delta_time) {
#ifdef HAVE_LIVE2D_CORE
    if (impl_->model && impl_->is_loaded) {
        impl_->model->Update(delta_time);
    }
#else
    // 模拟更新逻辑
    (void)delta_time;
#endif
}

void Live2DModelWrapper::render(float* projection_matrix) {
#ifdef HAVE_LIVE2D_CORE
    if (impl_->renderer && impl_->model && impl_->is_loaded) {
        // 设置投影矩阵
        // 执行渲染
    }
#else
    // 模拟渲染
    (void)projection_matrix;
#endif
}

void Live2DModelWrapper::setParameterValue(const std::string& param_id, float value) {
#ifdef HAVE_LIVE2D_CORE
    if (impl_->model && impl_->is_loaded) {
        // 查找参数索引并设置值
        int index = impl_->model->GetParameterIndex(param_id.c_str());
        if (index >= 0) {
            impl_->model->SetParameterValue(index, value);
        }
    }
#else
    // 模拟实现
    (void)param_id;
    (void)value;
#endif
}

bool Live2DModelWrapper::startMotion(const std::string& motion_group, int motion_index) {
#ifdef HAVE_LIVE2D_CORE
    if (!impl_->model || !impl_->is_loaded) {
        return false;
    }
    
    // 加载并启动动作
    // 需要从 model3.json 中解析动作文件路径
    
    // 简化实现：返回成功
    return true;
#else
    (void)motion_group;
    (void)motion_index;
    return true;  // 模拟成功
#endif
}

int Live2DModelWrapper::getParameterCount() const {
    return impl_->parameter_count;
}

int Live2DModelWrapper::getDrawableCount() const {
    return impl_->drawable_count;
}

void Live2DModelWrapper::release() {
    impl_->release();
}

// ============================================================================
// Cubism Core 工具函数
// ============================================================================

const char* cubism_core_get_version() {
#ifdef HAVE_LIVE2D_CORE
    return Csm::CubismFramework::GetVersionString();
#else
    return "mock-1.0.0";
#endif
}

bool cubism_core_init() {
#ifdef HAVE_LIVE2D_CORE
    Csm::CubismFramework::StartUp();
    Csm::CubismFramework::Initialize();
    return true;
#else
    return true;  // 模拟成功
#endif
}
