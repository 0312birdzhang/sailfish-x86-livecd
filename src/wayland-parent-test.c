/* Exercise a locally loaded Wayland client, as used after GLVND startup. */
#include <wayland-server.h>
#include <dlfcn.h>
#include <stdio.h>

int main(void)
{
    struct wl_display *server = wl_display_create();
    if (!server || wl_display_add_socket(server, "parent") < 0) return 2;
    void *client = dlopen("libwayland-client.so.0", RTLD_NOW | RTLD_LOCAL);
    void *(*connect)(const char *) = dlsym(RTLD_DEFAULT, "wl_display_connect");
    void (*disconnect)(void *) = client ? dlsym(client, "wl_display_disconnect") : 0;
    void *display = connect ? connect(NULL) : NULL;
    printf("Local Wayland client parent connection: %s\n", display ? "PASS" : "FAIL");
    if (display && disconnect) disconnect(display);
    wl_display_destroy(server);
    return display ? 0 : 1;
}
