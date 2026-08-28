/**
 * OpenGL 函数绑定实现
 * 
 * 提供跨平台 OpenGL ES 2.0 函数加载和绑定
 */

#include "opengl_bindings.h"

// 全局 OpenGL 函数指针
PFNGLCLEARPROC glClearPtr = nullptr;
PFNGLCLEARCOLORPROC glClearColorPtr = nullptr;
PFNGLVIEWPORTPROC glViewportPtr = nullptr;
PFNGLACTIVETEXTUREPROC glActiveTexturePtr = nullptr;
PFNGLBINDTEXTUREPROC glBindTexturePtr = nullptr;
PFNGLGENTEXTURESPROC glGenTexturesPtr = nullptr;
PFNGLDELETETEXTURESPROC glDeleteTexturesPtr = nullptr;
PFNGLTEXIMAGE2DPROC glTexImage2DPtr = nullptr;
PFNGLTEXPARAMETERIPROC glTexParameteriPtr = nullptr;
PFNGLCREATESHADERPROC glCreateShaderPtr = nullptr;
PFNGLSHADERSOURCEPROC glShaderSourcePtr = nullptr;
PFNGLCOMPILESHADERPROC glCompileShaderPtr = nullptr;
PFNGLGETSHADERIVPROC glGetShaderivPtr = nullptr;
PFNGLGETSHADERINFOLOGPROC glGetShaderInfoLogPtr = nullptr;
PFNGLCREATEPROGRAMPROC glCreateProgramPtr = nullptr;
PFNGLATTACHSHADERPROC glAttachShaderPtr = nullptr;
PFNGLLINKPROGRAMPROC glLinkProgramPtr = nullptr;
PFNGLGETPROGRAMIVPROC glGetProgramivPtr = nullptr;
PFNGLGETPROGRAMINFOLOGPROC glGetProgramInfoLogPtr = nullptr;
PFNGLUSEPROGRAMPROC glUseProgramPtr = nullptr;
PFNGLGETATTRIBLOCATIONPROC glGetAttribLocationPtr = nullptr;
PFNGLGETUNIFORMLOCATIONPROC glGetUniformLocationPtr = nullptr;
PFNGLUNIFORM1FPROC glUniform1fPtr = nullptr;
PFNGLUNIFORM2FPROC glUniform2fPtr = nullptr;
PFNGLUNIFORM4FPROC glUniform4fPtr = nullptr;
PFNGLUNIFORMMATRIX4FVPROC glUniformMatrix4fvPtr = nullptr;
PFNGLENABLEVERTEXATTRIBARRAYPROC glEnableVertexAttribArrayPtr = nullptr;
PFNGLDISABLEVERTEXATTRIBARRAYPROC glDisableVertexAttribArrayPtr = nullptr;
PFNGLVERTEXATTRIBPOINTERPROC glVertexAttribPointerPtr = nullptr;
PFNGLBINDATTRIBLOCATIONPROC glBindAttribLocationPtr = nullptr;
PFNGLBLENDFUNCPROC glBlendFuncPtr = nullptr;
PFNGLENABLEPROC glEnablePtr = nullptr;
PFNGLDISABLEPROC glDisablePtr = nullptr;
PFNGLPIXELSTOREIPROC glPixelStoreiPtr = nullptr;

#ifdef _WIN32
    // Windows 平台：使用 wglGetProcAddress 加载扩展函数
    #include <windows.h>
    
    typedef const GLubyte* (APIENTRY *PFNGLGETSTRINGPROC)(GLenum name);
    
    static void* getProcAddress(const char* name) {
        void* proc = (void*)wglGetProcAddress(name);
        if (!proc) {
            // 如果 wglGetProcAddress 失败，尝试从 opengl32.dll 获取
            static HMODULE gl_module = LoadLibraryA("opengl32.dll");
            if (gl_module) {
                proc = (void*)GetProcAddress(gl_module, name);
            }
        }
        return proc;
    }
    
#elif defined(__APPLE__)
    // macOS: 使用 NSAddressOfSymbol 或直接链接
    #include <dlfcn.h>
    
    static void* getProcAddress(const char* name) {
        // macOS OpenGL 框架已链接核心函数
        return dlsym(RTLD_DEFAULT, name);
    }
    
#else
    // Linux/Unix: 使用 glXGetProcAddress 或 dlsym
    #include <GL/glx.h>
    #include <dlfcn.h>
    
    static void* getProcAddress(const char* name) {
        Display* display = XOpenDisplay(nullptr);
        if (display) {
            void* proc = (void*)glXGetProcAddress((const GLubyte*)name);
            XCloseDisplay(display);
            if (proc) return proc;
        }
        return dlsym(RTLD_DEFAULT, name);
    }
#endif

bool loadOpenGLFunctions(void* context) {
    (void)context;  // 某些平台可能需要上下文句柄
    
    // 加载核心 OpenGL 函数
    // 注意：在大多数平台上，核心函数已经链接，不需要动态加载
    // 这里主要是为了跨平台一致性
    
    #ifdef GL_VERSION_1_1
        // OpenGL 1.1+ 核心函数（通常已链接）
        glClearPtr = glClear;
        glClearColorPtr = glClearColor;
        glViewportPtr = glViewport;
        glBlendFuncPtr = glBlendFunc;
        glEnablePtr = glEnable;
        glDisablePtr = glDisable;
        glPixelStoreiPtr = glPixelStorei;
        glGenTexturesPtr = glGenTextures;
        glDeleteTexturesPtr = glDeleteTextures;
        glBindTexturePtr = glBindTexture;
        glTexImage2DPtr = glTexImage2D;
        glTexParameteriPtr = glTexParameteri;
    #endif
    
    #ifdef GL_VERSION_2_0
        // OpenGL 2.0+ 核心函数（着色器相关）
        glCreateShaderPtr = glCreateShader;
        glShaderSourcePtr = glShaderSource;
        glCompileShaderPtr = glCompileShader;
        glGetShaderivPtr = glGetShaderiv;
        glGetShaderInfoLogPtr = glGetShaderInfoLog;
        glCreateProgramPtr = glCreateProgram;
        glAttachShaderPtr = glAttachShader;
        glLinkProgramPtr = glLinkProgram;
        glGetProgramivPtr = glGetProgramiv;
        glGetProgramInfoLogPtr = glGetProgramInfoLog;
        glUseProgramPtr = glUseProgram;
        glGetAttribLocationPtr = glGetAttribLocation;
        glGetUniformLocationPtr = glGetUniformLocation;
        glUniform1fPtr = glUniform1f;
        glUniform2fPtr = glUniform2f;
        glUniform4fPtr = glUniform4f;
        glUniformMatrix4fvPtr = glUniformMatrix4fv;
        glEnableVertexAttribArrayPtr = glEnableVertexAttribArray;
        glDisableVertexAttribArrayPtr = glDisableVertexAttribArray;
        glVertexAttribPointerPtr = glVertexAttribPointer;
        glBindAttribLocationPtr = glBindAttribLocation;
    #endif
    
    #ifdef GL_VERSION_1_3
        // OpenGL 1.3+ 核心函数
        glActiveTexturePtr = glActiveTexture;
    #endif
    
    // 检查关键函数是否加载成功
    if (!glClearPtr || !glClearColorPtr || !glViewportPtr) {
        return false;
    }
    
    return true;
}
