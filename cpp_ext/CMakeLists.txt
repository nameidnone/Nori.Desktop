cmake_minimum_required(VERSION 3.28)
project(nori_core_cpp VERSION 1.0.0 LANGUAGES CXX)

# C++20 standard requirement
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Build type
if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release)
endif()

# Compiler flags for performance
if(CMAKE_CXX_COMPILER_ID MATCHES "MSVC")
    add_compile_options(/O2 /W4 /permissive- /Zc:__cplusplus)
    add_definitions(-DNOMINMAX -DWIN32_LEAN_AND_MEAN)
else()
    add_compile_options(-O3 -Wall -Wextra -Wpedantic -fvisibility=hidden)
endif()

# Find required packages
find_package(Python3 COMPONENTS Interpreter Development.Module REQUIRED)
find_package(pybind11 CONFIG REQUIRED)

# Live2D Cubism Core native library paths
set(LIVE2D_CORE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/third_party/Live2DCubismCore")

# Platform-specific Live2D Core library
if(WIN32)
    set(LIVE2D_CORE_LIB "${LIVE2D_CORE_DIR}/win-x64/Live2DCubism.lib")
    set(LIVE2D_CORE_DLL "${LIVE2D_CORE_DIR}/win-x64/Live2DCubismCore.dll")
elseif(APPLE)
    set(LIVE2D_CORE_LIB "${LIVE2D_CORE_DIR}/macos/libLive2DCubismCore.a")
else()
    set(LIVE2D_CORE_LIB "${LIVE2D_CORE_DIR}/linux-x64/libLive2DCubismCore.a")
endif()

# OpenGL finding (required for Live2D rendering)
find_package(OpenGL REQUIRED)

# Source files
set(LIVE2D_SOURCES
    src/live2d_renderer.cpp
    src/live2d_model.cpp
    src/live2d_texture_manager.cpp
    src/opengl_context.cpp
)

set(LIVE2D_HEADERS
    include/live2d_renderer.h
    include/live2d_model.h
    include/live2d_texture_manager.h
    include/opengl_context.h
)

# Create pybind11 module
pybind11_add_module(nori_core_ext ${LIVE2D_SOURCES} ${LIVE2D_HEADERS})

# Include directories
target_include_directories(nori_core_ext PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${OPENGL_INCLUDE_DIR}
)

# Link libraries
target_link_libraries(nori_core_ext PRIVATE
    ${LIVE2D_CORE_LIB}
    ${OPENGL_LIBRARIES}
)

# Platform-specific adjustments
if(WIN32)
    target_compile_definitions(nori_core_ext PRIVATE _CRT_SECURE_NO_WARNINGS)
elseif(APPLE)
    target_link_libraries(nori_core_ext PRIVATE "-framework Cocoa" "-framework IOKit")
else()
    target_link_libraries(nori_core_ext PRIVATE pthread dl)
endif()

# Set output directory to match Python package structure
set_target_properties(nori_core_ext PROPERTIES
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/../src/nori_core/_ext"
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/../src/nori_core/_ext"
)

# Copy Live2D Core DLL on Windows
if(WIN32)
    add_custom_command(TARGET nori_core_ext POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
            "${LIVE2D_CORE_DLL}"
            "$<TARGET_FILE_DIR:nori_core_ext>"
    )
endif()

# Installation rules
install(TARGETS nori_core_ext
    LIBRARY DESTINATION nori_core/_ext
    RUNTIME DESTINATION nori_core/_ext
)

# Testing
option(BUILD_TESTING "Build tests" OFF)
if(BUILD_TESTING)
    enable_testing()
    add_subdirectory(tests)
endif()
