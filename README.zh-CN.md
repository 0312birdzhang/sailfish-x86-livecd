# Sailfish OS x86_64 Live

[English](README.md) | 简体中文

镜像使用 Ubuntu Base 24.04.5 amd64 和 Ubuntu 通用内核承载 Sailfish OS 5.2.0.22 i486 用户空间。基础 rootfs 来自官方 5.1.0.11 SDK 模拟器，并通过官方 5.2.0.22 软件源升级。锁屏与桌面默认横屏。常规启动尝试 GPU 渲染；显卡或缓冲共享检查失败时自动使用软件渲染，basic graphics 模式强制使用软件渲染。

## 构成

- GRUB 提供 BIOS 和 x86_64 UEFI 引导。
- casper 从 SquashFS 启动 Ubuntu，将更改写入 `writable` 持久化卷；没有该卷时使用 RAM Overlay。
- systemd-nspawn 启动独立的 Sailfish 系统和用户会话。
- 容器提供 `CAP_SYS_TIME`，供 Sailfish 时钟服务调整系统时间。
- Xorg 与 Weston 9 接收 Lipstick 的嵌套 Wayland 输出。Weston 9 提供 Qt 5.6 使用的旧版 `wl_shell` 协议。
- Mesa 25.2.8 从固定源码构建为 amd64 和 i386 两套，启用 Qt 5.6 所需的 `EGL_WL_bind_wayland_display` / `wl_drm`。前者供 Weston 使用，后者供 Lipstick 与应用使用。
- `src/wayland-parent.c` 处理 Lipstick 服务端与客户端共用 `WAYLAND_DISPLAY` 的兼容问题，也支持 GLVND 延迟加载的 Wayland 客户端。启动脚本通过 `sg` 保留 Lipstick 的 privileged 组身份。
- 容器接入 `/dev/dri`，Sailfish 硬件组号与 Ubuntu 对齐，图形库缓存让应用预加载器与普通应用加载同一套 Mesa。
- Ubuntu NetworkManager 管理物理网络，Sailfish ConnMan 通过虚拟以太网自动连接。systemd.path 将上游 DNS 同步到 root 拥有的副本，供 Sailfish 和应用沙箱读取。
- 容器有线接口在 ConnMan 启动前命名为 `wlan0`，通过有线 DHCP 获取地址，开发者设置读取该接口的实际 IPv4 地址。
- systemd-networkd 管理独立网桥 `sfos0` 的自动地址池、DHCP 和 NAT，容器重连期间保留网关地址。

## 使用 GitHub Actions 打包

1. 在仓库中打开 [Actions → Build Sailfish LiveCD](https://github.com/0312birdzhang/sailfish-x86-livecd/actions/workflows/build-livecd.yml)。
2. 点击 **Run workflow**，选择要打包的分支，然后确认运行。
3. 构建成功后，打开对应的运行记录，在 **Artifacts** 中下载 **sailfish-live-amd64**。压缩包包含可启动的 ISO、16 GiB VMware 持久化磁盘、校验文件和构建清单，最长保留 7 天。

解压后，在解压目录中校验 ISO 和持久化磁盘：

```bash
sha256sum -c SHA256SUMS sailfish-persistence-16G.vmdk.sha256
```

## 本地制作

在本工作目录执行以下命令。

```bash
./build.sh
```

下载、缓存、展开文件和日志默认保存到 `/home/bird/data/tmp/sfos-live`，输出镜像保存到 `dist`。可以通过 `SFOS_WORK` 调整构建目录。

```bash
SFOS_WORK=/home/bird/data/tmp/sfos-live ./build.sh
```

构建使用用户命名空间和子 UID/GID 映射。本机已具备所需权限和工具，依赖包含 `lxc-usernsexec`、`unshare`、GCC、Python 3、QEMU、7-Zip、rsync、SquashFS 工具。脚本在数据盘本地展开 fuse2fs，并在 Ubuntu 根文件系统内部安装制镜工具。

基础输入固定版本并校验 SHA256。Ubuntu 软件包由 noble 软件源安装，实际版本记录在 `dist/ubuntu-packages.tsv`，Sailfish 软件包记录在 `dist/sailfish-packages.tsv`，下载输入记录在 `dist/inputs.json`。目标版本由 `config/release.json` 统一控制，各版本 rootfs 使用独立构建缓存。

Mesa 编译依赖在 `SFOS_WORK/build/graphics-sdk` 中安装，包含 amd64 和 i386 开发库。图形源码、构建参数与安装文件校验值记录在 `dist/graphics-amd64.json` 和 `dist/graphics-i386.json`；SDK 包版本记录在 `dist/graphics-sdk-packages.tsv`。首次构建需要下载编译依赖并完成两套 Mesa 编译。

当前镜像使用 SDK 原有软件包集合，额外软件安装已停用。

2026-11-24 的 5.2.0.22 构建已验证 GPU 与软件回退启动、正常设置应用、沙箱
计算器的 GPU 访问，以及开发者模式 SSH 开启、经宿主端口 2222 的密码登录和关闭。
使用者在启用 3D 加速的 VMware 环境实测约 50 FPS。

## 启动

将 `dist/sailfish-live-5.2.0.22-amd64.iso` 写入 U 盘，从 BIOS 或 UEFI 启动菜单选择该 U 盘。自建 GRUB 使用关闭 Secure Boot 的 UEFI 环境。

启动菜单默认进入 `persistent` 模式，并提供持久化/临时会话各自的 basic graphics
选项。basic graphics 携带 `nomodeset`，临时会话携带 `nopersistent`。

## Live 持久化

持久化需要两部分：ISO 以 `persistent` 参数启动，以及一个标签为 `writable`
的 ext4 分区。没有持久化卷时，casper 会回退到 RAM，重启会丢失更改。

VMware 可直接使用 `dist/sailfish-persistence-16G.vmdk`。关闭虚拟机，在硬件设置中
添加硬盘，选择“使用现有虚拟磁盘”，挂载该文件；继续挂载 Live ISO，并选择
`Sailfish OS Live (persistent)` 启动。磁盘虚拟容量为 16 GiB，初始文件很小，随
写入增长。正常关机后保留这块磁盘，下次启动沿用同一块。

也可以在构建主机创建不同容量的磁盘文件：

```bash
python3 scripts/create-persistence-disk.py /path/to/sailfish-data.vmdk --size 32G
```

脚本只创建新的 VMDK 文件，包含 GPT 和 `writable` ext4 分区，不操作物理磁盘，
也不覆盖已有输出文件。

启动后在 Ubuntu 控制台检查：

```bash
cat /run/sailfish-persistence/mode
cat /run/sailfish-persistence/filesystem
```

模式为 `persistent`、文件系统为 `ext4` 时持久化有效；模式为 `temporary` 时仍是临时会话。启动日志也会报告
实际使用的模式。持久化覆盖 Ubuntu 配置及 `/opt/sailfish/rootfs`，因此 Sailfish
应用、用户文件、设置、开发者密码和 SSH 开关都会保留。`/run` 等运行时目录仍
由系统在每次启动时创建。

持久化已通过 QEMU 两次完整启动与正常关机验证：Ubuntu 系统及用户文件、
Sailfish 系统及用户文件、Sailfish 用户文件属主和 SSH 启用状态均在重启后保留。
验证结果见 `dist/persistence-validation.json`。测试使用独立磁盘，交付的
`sailfish-persistence-16G.vmdk` 保持初始状态。

可使用独立测试盘重复验证（需要可访问的 `qemu:///system` libvirt 服务）：

```bash
python3 scripts/create-persistence-disk.py /path/to/test-data.vmdk --size 2G
python3 scripts/test-persistence-vm.py \
  --iso dist/sailfish-live-5.2.0.22-amd64.iso \
  --disk /path/to/test-data.vmdk --directory /path/to/new-test-results
```

现有镜像也可在 GRUB 菜单按 `e`，在 `linux` 行追加 `persistent`，按 `Ctrl+X`
启动。这只改变本次启动参数；新版 ISO 已自带相应启动项。

鼠标按住后水平拖动可解锁，按住屏幕底部向上拖动可打开应用列表。应用中从左侧或右侧边缘向内拖动可返回主屏幕。

纯 TCG 模拟下，首次图形初始化需要等待。Sailfish 显示进入空闲状态后，移动鼠标可以唤醒界面。

## 控制台和网络

Ubuntu 控制台用户为 `live`，支持免密 sudo。Sailfish 用户为 `defaultuser`，密码为 `live`。

Sailfish SSH 默认关闭，可在开发者设置中启用远程登录。

在“设置 → 开发者模式”开启“允许远程连接”并设置登录密码后，通过 Ubuntu
宿主的 IP 和端口 2222 连接 Sailfish：

```bash
ssh -p 2222 defaultuser@你的Ubuntu宿主IP
```

宿主 socket 将连接转发到 Sailfish 容器的端口 22。关闭远程连接开关后，Sailfish
停止 SSH 服务。图形用户加入 `sailfish-system` 组，允许设置页调用密码管理服务；
SSH 使用该服务管理的原生配置。

可以通过 `Ctrl+Alt+F2` 进入 Ubuntu 控制台，使用 NetworkManager 配置无线网络。

```bash
nmcli device
nmcli device wifi list
sudo nmcli --ask device wifi connect "你的SSID"
```

查看启动日志和容器状态可以使用以下命令。

```bash
sudo journalctl -u sailfish-live.service -b
sudo machinectl list
sudo journalctl -M sailfish -b
```

## 已知适配范围

本版本采用 64 位 Ubuntu 与 32 位 Sailfish 的混合架构。实机显卡、无线网卡、音频和触控兼容性仍需测试。Sailfish 的无线网络界面需要进一步适配到宿主 NetworkManager。

商店下载需要登录 Jolla 账号，账号登录和应用下载尚未验证。

## 验证

早期镜像使用 QEMU 6.2、4 vCPU、4 GiB 内存和 TCG 模拟器取得以下验证记录。当前 5.2.0.22 图形改动通过 GPU 与软件渲染启动测试另行验证，流程见[图形构建和测试说明](GRAPHICS.md)。

| 项目 | 结果 |
| --- | --- |
| BIOS 从 ISO 引导并显示 Sailfish 锁屏 | 通过 |
| UEFI 从 ISO 引导并显示 Sailfish 锁屏 | 通过 |
| 标准 VGA 与 nomodeset 图形输出 | 通过，使用生成的 kernel/initramfs 直接引导 |
| 鼠标解锁、应用列表与设置应用 | 通过 |
| 横屏锁屏、主屏幕与应用列表 | 通过 |
| 浏览器加载 HTTPS 网页、商店启动与开发者模式设置页 | 通过 |
| DNS 副本动态更新及应用沙箱启动 | 通过 |
| timed 时钟服务 | 通过 |
| 容器 DHCP、DNS 和 HTTPS 访问 | 通过 |
| ConnMan 重启后的子网与联网状态 | 通过 |
| 整个 Sailfish 会话重启后的网关与联网状态 | 通过 |
| Sailfish 音频播放 | 通过，QEMU WAV 后端捕获到非零 PCM 数据 |
| ISO SHA256 校验 | 通过 |

界面截图保存在 `dist/sailfish-live.png`。

基础镜像和兼容组件来自官方发布目录。[Ubuntu Base](https://cdimage.ubuntu.com/ubuntu-base/releases/24.04/release/)、[Sailfish SDK 模拟器](https://releases.sailfishos.org/sdk/emulators/)、[Ubuntu Weston 软件包](https://archive.ubuntu.com/ubuntu/pool/universe/w/weston/)
