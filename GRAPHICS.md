# Sailfish 5.2.0.22 图形适配

应用、Lipstick 和宿主 Weston 共用显卡的 DMA-BUF 缓冲区。Mesa 25.2.8 启用
`legacy-wayland=bind-wayland-display`，让 QtWayland 5.6 能通过 `wl_drm` v2
注册、共享和导入 GPU 缓冲区。整个显示路径仍为应用 → Lipstick → Weston 9 → Xorg。

| 使用者 | 架构 | 图形库目录 |
| --- | --- | --- |
| 应用与 Lipstick | i386 / i486 用户空间 | `/usr/lib/sailfish-live/mesa` |
| 宿主 Weston 9 | amd64 | `/opt/sailfish-graphics/lib` |

两套 Mesa 包含 iris、crocus、radeonsi、nouveau、virgl、svga 和 llvmpipe/softpipe。
Vulkan 与视频解码前端未启用。GLVND 前端及其依赖由 Ubuntu Noble 的构建 SDK
提供，glibc 与 Wayland 库保留目标系统自身的版本。

## 启动和库加载

宿主先通过 GBM 检查渲染器及 Wayland 绑定，再启动 Weston 的 GL renderer，并
检查其 `wl_drm` 与 EGL 客户端渲染器。检查失败或启动参数含 `nomodeset` /
`sfos.graphics=software` 时，Weston 使用 Pixman，桌面和应用使用 llvmpipe。
选定模式通过 `/run/sailfish-graphics/95-live-graphics.conf` 同时传给桌面与应用会话。

图形 SONAME 链接位于私有 Mesa 目录的 `graphics/` 子目录，并优先进入
`ld.so.cache`，让 setgid 应用预加载器在读取应用环境之前也能加载正确的图形库。
依赖使用私有库目录的绝对 RPATH，避免相对路径以库缓存链接目录为基准。

GLVND 不再将 Wayland 客户端放入初始全局库范围。`wayland-parent.c` 的连接
拦截器在 `RTLD_NEXT` 查找失败时使用显式客户端库句柄，确保 Lipstick 连接到
外层 Weston，同时保留自己的应用 Wayland socket。局部加载客户端的回归测试
随图形组件构建运行。

容器绑定 `/dev/dri` 并允许 DRM 设备读写。构建时将 Sailfish 的 audio、video、
render 组号对齐到 Ubuntu；占用这些组号的其他组移到空闲组号，同时更新用户
和文件归属并保留文件模式。Sailjail 与正常预加载器保持启用。

## 构建

```bash
./build.sh
```

目标版本取自 `config/release.json`。官方 SDK 5.1.0.11 是固定的初始输入，首次
构建通过官方 5.2.0.22 软件源升级用户空间。版本缓存分别保存为
`SFOS_WORK/build/sailfish-root-版本号`，最终产物为
`dist/sailfish-live-5.2.0.22-amd64.iso`。

Mesa 源码与 Wayland 协议源码均校验固定 SHA256。图形构建 SDK、Python 环境、
源码、目标文件和依赖位于 `SFOS_WORK/build/graphics*`。构建产物校验值与包版本
保存在 `dist/graphics-*.json` 和 `dist/graphics-sdk-packages.tsv`。

## 在启动后的系统检查

Ubuntu 控制台可以查看选择的模式及宿主探测结果：

```bash
cat /run/sailfish-graphics/mode /run/sailfish-graphics/reason
sudo cat /run/sailfish-graphics/host-gbm.json
sudo cat /run/sailfish-graphics/host-wayland.json
```

应用端探测应使用图形用户：

```bash
leader=$(machinectl show sailfish -p Leader --value)
sudo nsenter -t "$leader" --mount --pid --root \
    /usr/sbin/runuser -u defaultuser -- env \
    XDG_RUNTIME_DIR=/run/user/100000 WAYLAND_DISPLAY=/run/display/wayland-0 \
    /usr/local/bin/sailfish-graphics-probe --wayland
```

GPU 模式应包含 `wl_drm` v2，renderer 应为相应显卡驱动，图形库应来自私有
Mesa 目录。软件模式的 renderer 为 llvmpipe。

## 虚拟机验证

提供 libvirt QEMU 虚拟机测试，使用独立 RAM rootfs、4 vCPU、4 GiB 内存，测试结束
销毁临时虚拟机。GPU 测试需要宿主可用的 3D render node；标准 VGA 用于软件回退。

```bash
python3 scripts/test-graphics-vm.py \
    --iso dist/sailfish-live-5.2.0.22-amd64.iso --graphics gpu \
    --directory /path/to/gpu-test
python3 scripts/test-graphics-vm.py \
    --iso dist/sailfish-live-5.2.0.22-amd64.iso --graphics software \
    --directory /path/to/software-test
```

测试检查系统版本、应用 EGL renderer、Wayland globals、正常设置应用的库映射与
GPU 设备访问，并保存截图和 Qt Quick 滚动诊断结果。TCG 的 CPU 模拟、首次 shader
编译和 QML 事件调度都会影响统计；这些结果不能作为实机 60 FPS 的保证。

2026-11-24 的 5.2.0.22 镜像已在 VirGL 虚拟机确认应用 renderer 为 `virgl`、
Lipstick 提供 `wl_drm` v2，图形库全部来自修正后的私有目录。使用者在启用 3D
加速的 VMware 环境实测约 50 FPS；该数值为使用者测试结果。

同一构建也通过标准 VGA 的 llvmpipe 软件回退、正常设置应用与沙箱计算器的
私有图形库/DRM 设备检查。SSH 测试模拟设置应用的 privileged 有效组，确认
密码管理服务能开启 `sshd.socket`，经宿主端口 2222 完成密码登录，并再次关闭。
