# Jetson 本地决策助手

在 Jetson 上用 **Laya 决策模型 + Qwen 文本模型** 操作真实浏览器、连续编辑白板。

[English](README.md) · [安装说明](docs/installation.md) · [完整用法](docs/usage.md) · [排错](docs/troubleshooting.md)

Qwen 解析自然语言和生成必要文字；Laya 根据最新文字状态、合法候选选择操作与目标；
Playwright 通过鼠标键盘执行；程序独立核对实际结果。工具、布局和站点适配由代码实现，
模型不直接观看截图，也不保证任意网站或任意绘图任务都能完成。

## 三步开始

已验证设备为 **reComputer Industrial J4012 / Orin NX 16GB**。需要 Ubuntu22.04、
JetPack6.1/6.2（L4T R36.4.x）、CUDA12.6、系统 Python3.10，以及已登录的 X11 桌面。
建议至少预留20GiB磁盘空间。Mac/x86可阅读代码和运行无模型测试，不能运行板端安装器。

```bash
git clone https://github.com/zibochen6/jetson-browser-assistant.git
cd jetson-browser-assistant
./setup.sh
```

以普通桌面用户运行，不要给整个脚本加 sudo。脚本会检查设备、下载并校验 ARM64
PyTorch、用 uv 创建独立环境、安装浏览器、获取固定权重、构建 CUDA llama.cpp，并预加载服务。
只有系统库安装需要 sudo。不会升级 JetPack、修改系统 Python、桌面语言或分辨率。

网络中断后可以重跑，已验证文件会复用。如果 wheel 下载受限，可使用：

```bash
./setup.sh --torch-wheel /path/to/torch-2.7.0-cp310-cp310-linux_aarch64.whl
```

匹配文件来自 [Seeed PyTorch 教程](https://github.com/Seeed-Projects/reComputer-Jetson-for-Beginners/tree/main/3-Basic-Tools-and-Getting-Started/3.5-Pytorch)，
仍须通过项目固定校验值。其他安装选项见[安装说明](docs/installation.md)。

## 先体验白板

```bash
./launch-whiteboard.sh --open examples/whiteboard/blank.excalidraw
```

`--open` 会替换当前画布，已有任务导出保留。出现 `Models ready` 和 `Task>` 后，
只粘贴以下英文任务并回车，不要复制 `Task>`：

```text
Draw three labeled boxes: Camera on the left, Jetson in the center, and Display on the right. Connect Camera to Jetson and Jetson to Display with arrows.
```

完成后继续输入，沿用同一画布：

```text
Make Jetson green. Add a box labeled Robot Arm below Jetson and connect Jetson to Robot Arm. Keep everything else.
```

之后还可以逐条尝试：

```text
Rename Display to Monitor. Keep everything else.
```

```text
Delete Robot Arm. Keep everything else.
```

再次启动时，`./launch-whiteboard.sh` 会继续已有画布。首版支持少量未旋转矩形、文字、
绑定箭头及有限颜色和网格布局；不支持任意自由绘图。可编辑文件、PNG、截图、模型请求和
核对结果保存在 `whiteboard-runs/`。[白板指南](docs/whiteboard.md)还包括手动移动后的恢复。

## 体验查票

先完成或取消白板中的任务，再切换入口：

```bash
.venv/bin/jetson-browser whiteboard stop
./launch.sh
```

在 `Task>` 输入下面的英文任务，日期请替换成有效的未来 `YYYY-MM-DD`：

```text
Find one-way flights from Shenzhen to Shanghai on 2026-11-13 for 1 adult in economy. Nonstop only, lowest price first. Show up to 3 options and open the fare options for one matching flight.
```

默认打开真实网站与只读流程窗口。希望简化桌面可以运行 `./launch.sh --no-visualize`。
模型推理在本地完成，Trip.com需要联网；只打开票价选项，不下单、不支付。验证码或登录由用户处理。
结果和查询证据保存在 `runs/`，价格以网站当时显示为准。

## 日常控制

| 需求 | 操作 |
| --- | --- |
| 检查主机兼容性，不安装 | `./setup.sh --check` |
| 查看模型和执行服务状态，不加载模型 | `./status.sh` |
| 执行中取消本条任务 | Ctrl+C，清理后返回 `Task>` |
| 退出终端，保留模型和浏览器 | 空闲提示处输入 `exit` / `quit`，或按 Ctrl+C/Ctrl+D |
| 仅关闭白板 | `.venv/bin/jetson-browser whiteboard stop` |
| 停止整个项目的服务、模型及两个场景 | `./stop.sh` |

计时从任务回车开始，包含解析、必要导航、推理、动作、等待、核对与保存；预加载、预热、
输入等待不计入。人工等待计入总耗时并单列。每条任务独立记录，最终耗时冻结。两个入口均不自动录屏。

## 能力、配置和开发

目前验收范围为 Trip.com 限定任务族和小规模白板。Laya只能从合法候选中选择；选中候选不等于正确完成，
因此保留独立核对、过期目标检查、有限重试及任务预算。尚无同条件脚本基线，不能宣称比脚本更快或维护更简单。
[实测摘要](docs/validation-summary.md)区分历史验收、小样本性能比较与安装器验证。

16GB为CPU/GPU共享内存，其他浏览器和swap会影响体验。默认端口仅监听本机回环：
8790航班、8791 Laya、8792 Qwen、8793白板。不同副本不能同时占用端口；发现冲突会报错，不停止无关进程。

可创建不进入Git的 `config.local.json` 覆盖动作预算、超时或录像选项；示例见英文README。
桌面变量继承当前会话，不固定用户名或UID。版本、权重revision与校验值均已固定。
扩展站点/工具前，请阅读[架构](docs/architecture.md)及[贡献指南](CONTRIBUTING.md)。

项目自有代码采用 [Apache-2.0](LICENSE)。模型与第三方组件保留各自授权，见[第三方说明](THIRD_PARTY.md)。
本案例的硬件入口：[reComputer Industrial J4012](https://www.seeedstudio.com/reComputer-Industrial-J4012-p-5684.html)；
其他型号尚未直接验证，不能承诺相同表现。
