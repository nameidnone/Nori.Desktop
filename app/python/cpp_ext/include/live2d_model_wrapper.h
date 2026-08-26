/**
 * Live2D 模型封装器头文件
 * 
 * 封装 Live2D Cubism Core API，提供简洁的 C++ 接口
 */

#ifndef LIVE2D_MODEL_WRAPPER_H
#define LIVE2D_MODEL_WRAPPER_H

#include <string>
#include <vector>
#include <memory>
#include <map>

// 前向声明
struct CubismModel;
struct CubismMotion;
class Live2DTextureManager;

/**
 * Live2D 模型包装器
 * 管理单个 Live2D 模型的生命周期、更新和渲染
 */
class Live2DModelWrapper {
public:
    Live2DModelWrapper();
    ~Live2DModelWrapper();
    
    /**
     * 加载模型
     * @param model_path 模型目录路径
     * @param texture_manager 纹理管理器
     * @return 是否成功
     */
    bool load(const std::string& model_path, Live2DTextureManager* texture_manager);
    
    /**
     * 更新模型状态
     * @param delta_time 时间增量 (秒)
     */
    void update(double delta_time);
    
    /**
     * 渲染模型
     * @param projection_matrix 4x4 投影矩阵
     */
    void render(float* projection_matrix);
    
    /**
     * 设置参数值
     * @param param_id 参数 ID
     * @param value 参数值 (-1.0 到 1.0)
     */
    void setParameterValue(const std::string& param_id, float value);
    
    /**
     * 触发动作
     * @param motion_group 动作组
     * @param motion_index 动作索引
     * @return 是否成功
     */
    bool startMotion(const std::string& motion_group, int motion_index);
    
    /**
     * 获取参数数量
     */
    int getParameterCount() const;
    
    /**
     * 获取可绘制对象数量
     */
    int getDrawableCount() const;
    
    /**
     * 释放资源
     */
    void release();

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

/**
 * 获取 Cubism Core 版本字符串
 */
const char* cubism_core_get_version();

/**
 * 初始化 Cubism Core
 */
bool cubism_core_init();

#endif // LIVE2D_MODEL_WRAPPER_H
