cmake_minimum_required(VERSION 3.20)
project(live2d_renderer LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

# pybind11 配置
find_package(pybind11 CONFIG REQUIRED)

# Live2D Cubism Core 原生库路径
set(LIVE2D_CORE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../Live2D/native")

# 根据平台设置 Live2D Core 库
if(WIN32)
    set(LIVE2D_CORE_LIB "${LIVE2D_CORE_DIR}/win-x64/Live2DCubismCore.lib")
    set(LIVE2D_CORE_DLL "${LIVE2D_CORE_DIR}/win-x64/Live2DCubismCore.dll")
elseif(APPLE)
    set(LIVE2D_CORE_LIB "${LIVE2D_CORE_DIR}/macos/Live2DCubismCore.framework/Live2DCubismCore")
else()
    set(LIVE2D_CORE_LIB "${LIVE2D_CORE_DIR}/linux-x64/libLive2DCubismCore.so")
endif()

# Live2D 渲染器源文件
set(LIVE2D_RENDERER_SOURCES
    src/live2d_renderer.cpp
    src/live2d_model_wrapper.cpp
    src/live2d_texture_manager.cpp
    src/opengl_bindings.cpp
)

# 创建 Python 扩展模块
pybind11_add_module(live2d_core ${LIVE2D_RENDERER_SOURCES})

# 链接 Live2D Core 库
target_link_libraries(live2d_core PRIVATE ${LIVE2D_CORE_LIB})

# 包含目录
target_include_directories(live2d_core PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${LIVE2D_CORE_DIR}/include
)

# 编译选项
if(MSVC)
    target_compile_options(live2d_core PRIVATE /W4 /O2 /std:c++20)
else()
    target_compile_options(live2d_core PRIVATE -Wall -Wextra -O3 -std=c++20)
endif()

# 安装目标
install(TARGETS live2d_core LIBRARY DESTINATION nori_core/live2d)

# Windows 下复制 DLL
if(WIN32)
    add_custom_command(TARGET live2d_core POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
        "${LIVE2D_CORE_DLL}"
        $<TARGET_FILE_DIR:live2d_core>/Live2DCubismCore.dll
    )
endif()
