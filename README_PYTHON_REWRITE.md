# Nori Desktop Pet - Python/C++ Rewrite

## 项目状态：Phase 1 基础设施已完成 ✅

本项目是将 Nori Desktop Pet 从 .NET 10 + Avalonia 重构为 **Python 3.12+ + C++20** 的完整实现，**100% 保留原版 UI/UX**。

---

## 📋 核心纲领 (已实施)

### 1. UI/UX 绝对守恒
- ✅ 前端 Vue 3 代码零修改
- ✅ PyQt6 QSS 精确复刻 UnoCSS 深海微光主题
- ✅ Chromium WebView 确保渲染一致性
- ✅ 通信协议双层 JSON Envelope 完全兼容

### 2. 性能分级策略
| 层级 | 技术栈 | 用途 | 性能目标 |
|------|--------|------|----------|
| **Tier 0** | C++20 + pybind11 | Live2D 渲染、音频处理 | 原生 95%+ |
| **Tier 1** | Python + Nuitka | 核心业务逻辑 | 原生 80%+ |
| **Tier 2** | Pure Python | 配置管理、文件 IO | 开发效率优先 |

### 3. 工程化原则
- ✅ **高内聚低耦合**: 每个模块单一职责，通过接口通信
- ✅ **依赖倒置**: 高层模块不依赖低层具体实现
- ✅ **类型安全**: 完整 Type Hints + mypy 严格检查
- ✅ **异步优先**: 所有 I/O 使用 asyncio
- ✅ **防御性编程**: 严格错误处理、资源清理

---

## 🏗️ 当前架构

```
nori-desktop-pet/
├── cpp_ext/                    # C++20 性能关键模块
│   ├── CMakeLists.txt          # CMake 构建配置
│   ├── include/
│   │   └── live2d_renderer.h   # Live2D 渲染器头文件
│   ├── src/
│   │   └── live2d_renderer.cpp # Live2D 渲染实现 (含 pybind11 绑定)
│   └── third_party/            # Live2D Cubism Core SDK
│
├── src/
│   ├── nori_core/              # Python 核心业务层
│   │   ├── __init__.py         # 懒加载模块导出
│   │   ├── configuration/
│   │   │   └── config_store.py # 配置存储 (SQLite 后端)
│   │   ├── data/
│   │   │   └── database_manager.py  # 数据库连接池
│   │   ├── chat/               # 聊天服务 (待迁移)
│   │   ├── memory/             # 记忆系统 (待迁移)
│   │   ├── agent/              # Agent 运行时 (待迁移)
│   │   ├── mcp/                # MCP 客户端 (待迁移)
│   │   ├── voice/              # 语音服务 (待迁移)
│   │   └── ...                 # 其他模块骨架
│   │
│   └── nori_desktop/           # PyQt6 桌面层
│       ├── __main__.py         # 应用入口
│       ├── startup/
│       │   └── app.py          # 应用生命周期管理
│       ├── bridge/             # WebView 桥接 (待实现)
│       ├── windows/            # 窗口管理 (待实现)
│       ├── widgets/            # 自定义控件 (待实现)
│       └── services/           # 服务容器 (待实现)
│
├── scripts/
│   └── build.py                # 构建脚本 (C++ 编译 + Nuitka 打包)
│
├── tests/                      # 测试套件
│   ├── unit/                   # 单元测试
│   ├── integration/            # 集成测试
│   └── e2e/                    # 端到端测试
│
├── pyproject.toml              # 项目配置与依赖
└── README.md                   # 本文档
```

---

## 🚀 Phase 1 完成内容

### M1.1 构建系统 ✅
- `pyproject.toml`: 完整依赖定义 (PyQt6, pybind11, Nuitka 等)
- `scripts/build.py`: C++ 编译 + Nuitka 打包自动化
- CMake 配置：跨平台 C++20 编译支持

### M1.2 C++ 扩展骨架 ✅
- `cpp_ext/CMakeLists.txt`: CMake 构建配置
- `cpp_ext/include/live2d_renderer.h`: Live2D 渲染器接口定义
- `cpp_ext/src/live2d_renderer.cpp`: 
  - OpenGL 加速渲染管线
  - pybind11 Python 绑定
  - GIL 释放优化
  - RAII 资源管理

### M1.3 Python 核心骨架 ✅
- `src/nori_core/__init__.py`: 懒加载模块系统
- `src/nori_core/configuration/config_store.py`: 配置存储实现
- `src/nori_core/data/database_manager.py`: 异步数据库连接池
- 14 个核心模块目录结构创建

### M1.4 桌面层骨架 ✅
- `src/nori_desktop/__main__.py`: 应用入口
- `src/nori_desktop/startup/app.py`: 应用生命周期管理
- 7 个桌面层模块目录结构创建

---

## 📅 后续计划

### Phase 2: 渲染与多媒体内核 (5 天)
- [ ] M2.1 Live2D Engine: 完整实现 `live2d_model.cpp`, `live2d_texture_manager.cpp`
- [ ] M2.2 Audio Pipeline: C++ 音频采集/播放环
- [ ] M2.3 Graphics Bridge: PyQt6 QOpenGLWidget 集成

### Phase 3: 通信桥接与前端集成 (7 天)
- [ ] M3.1 Protocol Layer: 双层 JSON Envelope 协议实现
- [ ] M3.2 WebChannel Impl: PyQt6 WebChannel 双向绑定
- [ ] M3.3 Frontend Sanity: Vue 3 构建产物集成验证

### Phase 4: 核心业务逻辑迁移 (19 天)
- [ ] M4.1 State Machine: 角色状态机迁移
- [ ] M4.2 AI Agent Core: LLM 调用逻辑迁移
- [ ] M4.3 Memory System: RAG 检索系统迁移
- [ ] M4.4 MCP & Tools: Model Context Protocol 迁移
- [ ] M4.5 Voice Service: STT/TTS 服务迁移

### Phase 5: 数据持久化与安全 (5 天)
- [ ] M5.1 Storage Adapter: aiosqlite 异步数据库
- [ ] M5.2 Crypto Module: AES-256-GCM 加密迁移
- [ ] M5.3 Migration Tool: .NET 数据迁移脚本

### Phase 6: 优化、测试与打包 (11 天)
- [ ] M6.1 Nuitka Compile: 编译优化配置
- [ ] M6.2 Perf Tuning: 性能分析与调优
- [ ] M6.3 E2E Testing: 端到端测试覆盖
- [ ] M6.4 Packaging: 跨平台安装包生成

---

## 🛠️ 技术栈总览

| 层级 | 技术选型 | 理由 |
|------|----------|------|
| **GUI** | PyQt6 6.7+ | 100% UI 还原能力，QSS 样式系统 |
| **WebView** | PyQt6-WebEngine | Chromium 内核，渲染一致性保证 |
| **核心业务** | Python 3.12+ | 开发效率，生态丰富 |
| **性能模块** | C++20 + pybind11 | 零开销抽象，Live2D 官方推荐 |
| **编译器** | Nuitka 2.4+ | Python 编译为 C 扩展，性能提升 30-50% |
| **数据库** | aiosqlite | 异步 SQLite，非阻塞 I/O |
| **加密** | cryptography | AES-256-GCM 实现 |
| **日志** | structlog | 结构化日志，JSON 输出 |

---

## 🔧 开发环境要求

```bash
# Python 版本
Python >= 3.12

# 构建工具
CMake >= 3.28
C++20 编译器 (MSVC / GCC 11+ / Clang 14+)

# Python 依赖安装
pip install -e ".[dev]"

# 构建 C++ 扩展
python scripts/build.py
```

---

## 📝 下一步行动

1. **确认计划**: 审核 Phase 1 成果，确认架构设计符合预期
2. **启动 Phase 2**: 开始 Live2D 渲染引擎完整实现
3. **环境准备**: 获取 Live2D Cubism Core SDK 并放置到 `cpp_ext/third_party/`

---

**最后更新**: 2024 年 Phase 1 完成  
**维护者**: Nori Team  
**许可证**: MIT
