#define _GNU_SOURCE
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES2/gl2.h>
#include <gbm.h>
#include <wayland-client.h>
#include <wayland-server.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static int globals_count;
static void quote(const char *value)
{
    putchar('"');
    for (const unsigned char *p = (const unsigned char *)value; *p; ++p) {
        if (*p == '"' || *p == '\\') printf("\\%c", *p);
        else if (*p < 32) printf("\\u%04x", *p);
        else putchar(*p);
    }
    putchar('"');
}

static void global_added(void *data, struct wl_registry *registry, uint32_t name,
                         const char *interface, uint32_t version)
{
    (void)data; (void)registry; (void)name;
    if (globals_count++) putchar(',');
    printf("{\"name\":"); quote(interface); printf(",\"version\":%u}", version);
}

static void global_removed(void *data, struct wl_registry *registry, uint32_t name)
{
    (void)data; (void)registry; (void)name;
}

static const struct wl_registry_listener listener = {global_added, global_removed};

static void mapped_libraries(void)
{
    char *line = NULL;
    size_t length = 0;
    char paths[128][1024];
    int count = 0;
    FILE *maps = fopen("/proc/self/maps", "r");
    if (!maps) return;
    while (getline(&line, &length, maps) >= 0) {
        char *path = strchr(line, '/');
        if (!path || !(strstr(path, "libEGL") || strstr(path, "libGLES") ||
                      strstr(path, "libgbm") || strstr(path, "libgallium") ||
                      strstr(path, "libGLdispatch"))) continue;
        path[strcspn(path, "\n")] = 0;
        int duplicate = 0;
        for (int i = 0; i < count; ++i) if (!strcmp(paths[i], path)) duplicate = 1;
        if (duplicate || count == 128) continue;
        if (count) putchar(',');
        quote(path);
        snprintf(paths[count++], sizeof(paths[0]), "%s", path);
    }
    free(line);
    fclose(maps);
}

int main(int argc, char **argv)
{
    const char *platform = argc > 1 ? argv[1] : "--wayland";
    struct wl_display *wayland = NULL;
    struct wl_registry *registry = NULL;
    struct gbm_device *gbm = NULL;
    int fd = -1, status = 1;
    void *native = NULL;
    EGLenum kind;
    if (!strcmp(platform, "--wayland")) {
        wayland = wl_display_connect(NULL);
        if (!wayland) { fprintf(stderr, "Could not connect to Wayland\n"); return 1; }
        native = wayland; kind = EGL_PLATFORM_WAYLAND_EXT;
    } else if (!strcmp(platform, "--gbm")) {
        fd = open(argc > 2 ? argv[2] : "/dev/dri/renderD128", O_RDWR | O_CLOEXEC);
        if (fd < 0 || !(gbm = gbm_create_device(fd))) {
            perror("GBM device"); if (fd >= 0) close(fd); return 1;
        }
        native = gbm; kind = EGL_PLATFORM_GBM_KHR;
    } else if (!strcmp(platform, "--surfaceless")) {
        kind = EGL_PLATFORM_SURFACELESS_MESA;
    } else {
        fprintf(stderr, "Usage: %s --wayland | --gbm [render-node] | --surfaceless\n", argv[0]);
        return 2;
    }
    PFNEGLGETPLATFORMDISPLAYEXTPROC get_display =
        (PFNEGLGETPLATFORMDISPLAYEXTPROC)eglGetProcAddress("eglGetPlatformDisplayEXT");
    EGLDisplay display = get_display ? get_display(kind, native, NULL) : EGL_NO_DISPLAY;
    EGLint major, minor;
    EGLContext context = EGL_NO_CONTEXT;
    if (!eglInitialize(display, &major, &minor)) {
        fprintf(stderr, "eglInitialize: %#x\n", eglGetError()); goto cleanup;
    }
    EGLConfig config;
    EGLint count;
    const EGLint attributes[] = {EGL_SURFACE_TYPE, 0, EGL_RENDERABLE_TYPE, EGL_OPENGL_ES2_BIT, EGL_NONE};
    const EGLint context_attributes[] = {EGL_CONTEXT_CLIENT_VERSION, 2, EGL_NONE};
    if (!eglBindAPI(EGL_OPENGL_ES_API) ||
        !eglChooseConfig(display, attributes, &config, 1, &count) || !count ||
        (context = eglCreateContext(display, config, EGL_NO_CONTEXT, context_attributes)) == EGL_NO_CONTEXT ||
        !eglMakeCurrent(display, EGL_NO_SURFACE, EGL_NO_SURFACE, context)) {
        fprintf(stderr, "EGL context: %#x\n", eglGetError()); goto cleanup;
    }
    const char *extensions = eglQueryString(display, EGL_EXTENSIONS);
    int bind_extension = extensions && strstr(extensions, "EGL_WL_bind_wayland_display");
    printf("{\"platform\":"); quote(platform);
    if (wayland) {
        printf(",\"wayland_globals\":[");
        registry = wl_display_get_registry(wayland);
        wl_registry_add_listener(registry, &listener, NULL);
        if (wl_display_roundtrip(wayland) < 0) goto cleanup;
        printf("]");
    }
    printf(",\"egl_version\":\"%d.%d\",\"bind_wayland_display_extension\":%s",
           major, minor, bind_extension ? "true" : "false");
    if (gbm && bind_extension) {
        struct wl_display *server = wl_display_create();
        PFNEGLBINDWAYLANDDISPLAYWLPROC bind = (PFNEGLBINDWAYLANDDISPLAYWLPROC)eglGetProcAddress("eglBindWaylandDisplayWL");
        PFNEGLUNBINDWAYLANDDISPLAYWLPROC unbind = (PFNEGLUNBINDWAYLANDDISPLAYWLPROC)eglGetProcAddress("eglUnbindWaylandDisplayWL");
        int bound = server && bind && unbind && bind(display, server);
        printf(",\"bind_wayland_display_test\":%s", bound ? "true" : "false");
        if (bound) unbind(display, server);
        if (server) wl_display_destroy(server);
    }
    printf(",\"gl_renderer\":"); quote((const char *)glGetString(GL_RENDERER));
    printf(",\"gl_version\":"); quote((const char *)glGetString(GL_VERSION));
    printf(",\"graphics_libraries\":["); mapped_libraries(); printf("]}\n");
    status = 0;
cleanup:
    if (context != EGL_NO_CONTEXT) {
        eglMakeCurrent(display, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT);
        eglDestroyContext(display, context);
    }
    if (display != EGL_NO_DISPLAY) eglTerminate(display);
    if (registry) wl_registry_destroy(registry);
    if (wayland) wl_display_disconnect(wayland);
    if (gbm) gbm_device_destroy(gbm);
    if (fd >= 0) close(fd);
    return status;
}
