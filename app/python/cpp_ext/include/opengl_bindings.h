/**
 * OpenGL 函数绑定头文件
 * 
 * 提供跨平台 OpenGL ES 2.0 函数加载和绑定
 */

#ifndef OPENGL_BINDINGS_H
#define OPENGL_BINDINGS_H

#ifdef _WIN32
    #define WIN32_LEAN_AND_MEAN
    #include <windows.h>
    #include <GL/gl.h>
#elif defined(__APPLE__)
    #include <OpenGL/gl3.h>
#else
    #define GL_GLEXT_PROTOTYPES
    #include <GL/gl.h>
    #include <GL/glext.h>
#endif

/**
 * 加载 OpenGL 函数指针
 * @param context OpenGL 上下文句柄 (平台相关)
 * @return 是否成功
 */
bool loadOpenGLFunctions(void* context);

/**
 * OpenGL ES 2.0 核心函数声明
 * 这些函数在运行时动态加载
 */
extern PFNGLCLEARPROC glClearPtr;
extern PFNGLCLEARCOLORPROC glClearColorPtr;
extern PFNGLVIEWPORTPROC glViewportPtr;
extern PFNGLACTIVETEXTUREPROC glActiveTexturePtr;
extern PFNGLBINDTEXTUREPROC glBindTexturePtr;
extern PFNGLGENTEXTURESPROC glGenTexturesPtr;
extern PFNGLDELETETEXTURESPROC glDeleteTexturesPtr;
extern PFNGLTEXIMAGE2DPROC glTexImage2DPtr;
extern PFNGLTEXPARAMETERIPROC glTexParameteriPtr;
extern PFNGLCREATESHADERPROC glCreateShaderPtr;
extern PFNGLSHADERSOURCEPROC glShaderSourcePtr;
extern PFNGLCOMPILESHADERPROC glCompileShaderPtr;
extern PFNGLGETSHADERIVPROC glGetShaderivPtr;
extern PFNGLGETSHADERINFOLOGPROC glGetShaderInfoLogPtr;
extern PFNGLCREATEPROGRAMPROC glCreateProgramPtr;
extern PFNGLATTACHSHADERPROC glAttachShaderPtr;
extern PFNGLLINKPROGRAMPROC glLinkProgramPtr;
extern PFNGLGETPROGRAMIVPROC glGetProgramivPtr;
extern PFNGLGETPROGRAMINFOLOGPROC glGetProgramInfoLogPtr;
extern PFNGLUSEPROGRAMPROC glUseProgramPtr;
extern PFNGLGETATTRIBLOCATIONPROC glGetAttribLocationPtr;
extern PFNGLGETUNIFORMLOCATIONPROC glGetUniformLocationPtr;
extern PFNGLUNIFORM1FPROC glUniform1fPtr;
extern PFNGLUNIFORM2FPROC glUniform2fPtr;
extern PFNGLUNIFORM4FPROC glUniform4fPtr;
extern PFNGLUNIFORMMATRIX4FVPROC glUniformMatrix4fvPtr;
extern PFNGLENABLEVERTEXATTRIBARRAYPROC glEnableVertexAttribArrayPtr;
extern PFNGLDISABLEVERTEXATTRIBARRAYPROC glDisableVertexAttribArrayPtr;
extern PFNGLVERTEXATTRIBPOINTERPROC glVertexAttribPointerPtr;
extern PFNGLBINDATTRIBLOCATIONPROC glBindAttribLocationPtr;
extern PFNGLBLENDFUNCPROC glBlendFuncPtr;
extern PFNGLENABLEPROC glEnablePtr;
extern PFNGLDISABLEPROC glDisablePtr;
extern PFNGLPIXELSTOREIPROC glPixelStoreiPtr;

// 内联包装函数，使用更安全的调用方式
inline void glClearWrapper(GLbitfield mask) {
    if (glClearPtr) glClearPtr(mask);
}

inline void glClearColorWrapper(GLfloat r, GLfloat g, GLfloat b, GLfloat a) {
    if (glClearColorPtr) glClearColorPtr(r, g, b, a);
}

inline void glViewportWrapper(GLint x, GLint y, GLsizei w, GLsizei h) {
    if (glViewportPtr) glViewportPtr(x, y, w, h);
}

inline void glActiveTextureWrapper(GLenum texture) {
    if (glActiveTexturePtr) glActiveTexturePtr(texture);
}

inline void glBindTextureWrapper(GLenum target, GLuint texture) {
    if (glBindTexturePtr) glBindTexturePtr(target, texture);
}

inline void glGenTexturesWrapper(GLsizei n, GLuint* textures) {
    if (glGenTexturesPtr) glGenTexturesPtr(n, textures);
}

inline void glDeleteTexturesWrapper(GLsizei n, const GLuint* textures) {
    if (glDeleteTexturesPtr) glDeleteTexturesPtr(n, textures);
}

#endif // OPENGL_BINDINGS_H
