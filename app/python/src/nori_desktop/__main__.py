#!/usr/bin/env python3
"""
Nori Desktop Pet - 主入口

技术栈:
- GUI: PyQt6 + PyQt6-WebEngine (100% UI 还原)
- 核心业务：Python 3.12+
- 性能模块：C++20 + pybind11 (Live2D 渲染、音频处理)
- 前端：Vue 3 + TypeScript (零修改)
- 打包：Nuitka + PyInstaller

用法:
    python -m nori_desktop [--safe-mode] [--smoke-test]
"""

import sys
import os

# 添加 src 到路径，支持开发模式直接运行
src_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "src")
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)


def main():
    """应用入口点"""
    from nori_desktop.startup.app import NoriApplication
    
    # 解析命令行参数
    safe_mode = "--safe-mode" in sys.argv
    smoke_test = None
    if "--smoke-test" in sys.argv:
        smoke_test = "default"  # 使用默认冒烟配置
    
    # 创建并运行应用
    app = NoriApplication(safe_mode=safe_mode, smoke_test=smoke_test)
    exit_code = app.run()
    
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
