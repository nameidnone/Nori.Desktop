/**
 * Live2D 纹理管理器头文件
 * 
 * 管理 OpenGL 纹理的加载、缓存和释放
 */

#ifndef LIVE2D_TEXTURE_MANAGER_H
#define LIVE2D_TEXTURE_MANAGER_H

#include <string>
#include <vector>
#include <map>
#include <cstdint>

/**
 * OpenGL 纹理信息
 */
struct TextureInfo {
    uint32_t texture_id;      // OpenGL 纹理 ID
    int width;                // 纹理宽度
    int height;               // 纹理高度
    std::string path;         // 原始路径
};

/**
 * Live2D 纹理管理器
 * 
 * 负责：
 * - 从磁盘加载纹理图像
 * - 创建 OpenGL 纹理对象
 * - 纹理缓存管理
 * - 资源释放
 */
class Live2DTextureManager {
public:
    Live2DTextureManager();
    ~Live2DTextureManager();
    
    /**
     * 加载纹理
     * @param path 纹理文件路径
     * @return 纹理 ID (OpenGL texture ID)，失败返回 0
     */
    uint32_t loadTexture(const std::string& path);
    
    /**
     * 获取纹理信息
     * @param texture_id OpenGL 纹理 ID
     * @return 纹理信息，不存在返回 nullptr
     */
    const TextureInfo* getTextureInfo(uint32_t texture_id) const;
    
    /**
     * 释放单个纹理
     * @param texture_id OpenGL 纹理 ID
     */
    void releaseTexture(uint32_t texture_id);
    
    /**
     * 释放所有纹理
     */
    void releaseAll();
    
    /**
     * 获取已加载纹理数量
     */
    size_t getTextureCount() const;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

#endif // LIVE2D_TEXTURE_MANAGER_H
