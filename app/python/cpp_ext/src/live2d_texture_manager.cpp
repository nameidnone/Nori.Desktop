/**
 * Live2D 纹理管理器实现
 * 
 * 管理 OpenGL 纹理的加载、缓存和释放
 */

#include "live2d_texture_manager.h"

#ifdef _WIN32
    #define WIN32_LEAN_AND_MEAN
    #include <windows.h>
    #include <GL/gl.h>
#elif defined(__APPLE__)
    #include <OpenGL/gl3.h>
#else
    #define GL_GLEXT_PROTOTYPES
    #include <GL/gl.h>
#endif

#include <stb_image.h>  // 图像加载库
#include <cstring>

namespace {
    // 辅助函数：从文件加载纹理
    GLuint loadTextureFromFile(const std::string& path, int* out_width, int* out_height) {
        if (!out_width || !out_height) {
            return 0;
        }
        
        int width, height, channels;
        // 使用 stb_image 加载图像（支持 PNG, JPG 等格式）
        unsigned char* image_data = stbi_load(path.c_str(), &width, &height, &channels, 4);
        
        if (!image_data) {
            return 0;
        }
        
        *out_width = width;
        *out_height = height;
        
        // 创建 OpenGL 纹理
        GLuint texture_id;
        glGenTextures(1, &texture_id);
        glBindTexture(GL_TEXTURE_2D, texture_id);
        
        // 设置纹理参数
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
        
        // 上传纹理数据
        glTexImage2D(
            GL_TEXTURE_2D,
            0,
            GL_RGBA,
            width,
            height,
            0,
            GL_RGBA,
            GL_UNSIGNED_BYTE,
            image_data
        );
        
        // 生成 Mipmap
        glGenerateMipmap(GL_TEXTURE_2D);
        
        // 释放图像数据
        stbi_image_free(image_data);
        
        return texture_id;
    }
}

// ============================================================================
// Live2DTextureManager::Impl - PIMPL 模式隐藏实现细节
// ============================================================================

struct Live2DTextureManager::Impl {
    std::map<uint32_t, TextureInfo> textures;
    uint32_t next_texture_id = 1;
    
    ~Impl() {
        releaseAll();
    }
    
    void releaseAll() {
        for (auto& [id, info] : textures) {
            if (info.texture_id != 0) {
                glDeleteTextures(1, &info.texture_id);
            }
        }
        textures.clear();
    }
};

// ============================================================================
// Live2DTextureManager 实现
// ============================================================================

Live2DTextureManager::Live2DTextureManager()
    : impl_(std::make_unique<Impl>()) {
}

Live2DTextureManager::~Live2DTextureManager() = default;

uint32_t Live2DTextureManager::loadTexture(const std::string& path) {
    if (path.empty()) {
        return 0;
    }
    
    // 检查是否已加载
    for (const auto& [id, info] : impl_->textures) {
        if (info.path == path) {
            return id;
        }
    }
    
    // 加载纹理
    int width = 0, height = 0;
    GLuint gl_texture_id = loadTextureFromFile(path, &width, &height);
    
    if (gl_texture_id == 0) {
        return 0;  // 加载失败
    }
    
    // 创建纹理信息
    uint32_t texture_id = impl_->next_texture_id++;
    
    TextureInfo info;
    info.texture_id = gl_texture_id;
    info.width = width;
    info.height = height;
    info.path = path;
    
    impl_->textures[texture_id] = info;
    
    return texture_id;
}

const TextureInfo* Live2DTextureManager::getTextureInfo(uint32_t texture_id) const {
    auto it = impl_->textures.find(texture_id);
    if (it == impl_->textures.end()) {
        return nullptr;
    }
    return &it->second;
}

void Live2DTextureManager::releaseTexture(uint32_t texture_id) {
    auto it = impl_->textures.find(texture_id);
    if (it != impl_->textures.end()) {
        if (it->second.texture_id != 0) {
            glDeleteTextures(1, &it->second.texture_id);
        }
        impl_->textures.erase(it);
    }
}

void Live2DTextureManager::releaseAll() {
    impl_->releaseAll();
}

size_t Live2DTextureManager::getTextureCount() const {
    return impl_->textures.size();
}
