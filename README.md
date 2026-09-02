# AgentBook · Linux 运维 Agent 控制服务

一台**独立 Linux VM**，开机自启一个服务；Win 浏览器用 `IP:端口` 登录后，看到
**对话页 + 状态页**，配好 API 后用自然语言直接控制这台 Linux。与本地 AntNest 无关，
完全独立。

> 来源：把《deb_rpm 安装包修改工具横评与预置配置免交互部署方案》里的 9 类白名单动作
> 变成了这个 Agent 的「工具集」——你说"把 foo.deb 预置配置后重打包"，它就调 `pkg.repack_deb`。

## 能力

- **对话页**：自然语言 → Agent → 工具调用 → 结果。支持 OpenAI 兼容端点（DeepSeek / 本地 vLLM / Ollama）。
- **状态页**：实时显示内核 / uptime / 负载 / 内存 / 磁盘 / 监听端口 / 运行服务 / 工具链可用性。
- **工具集**（受护栏）：
  - `system.run_cmd` — 执行命令（灾难性命令拒绝；sudo/rm -rf/格式化/改系统服务需界面确认）
  - `system.status` — 只读状态
  - `files.read` / `files.write` — 文件读写（系统关键路径需确认）
  - `pkg.inspect` — 查看 .deb/.rpm 控件/文件/脚本
  - `pkg.install_test` — disposable 预检（不真装）
  - `pkg.repack_deb` / `pkg.repack_rpm` — 基于现有包重打包（**原签名失效，需重签**）
  - `pkg.rollback` — 回滚/重装（L3，需确认）
- **登录**：首次启动随机生成密码，打印到服务日志；支持 token 会话。

## 通用 Linux 安装（推荐：云服务器 / 裸机）

别人（或你自己）**下载 GitHub 仓库后一条命令就能装好并起服务**：
纯标准库运行、零 pip 依赖，安装器自动识别包管理器（apt/dnf/yum/apk/pacman）
和 init 系统（systemd / OpenRC），注册开机自启服务、崩溃自动拉起，绑
`0.0.0.0:8080`，浏览器用 `IP:端口` 直接进。

```bash
git clone <你的仓库地址> AgentBook
cd AgentBook
sudo ./install.sh                          # 装 python3 + 注册开机自启 + 启动
# 想非交互指定首次登录密码：
sudo ./install.sh --password 你的密码
# 或用环境变量（CI / 脚本部署）：
AN_AGENT_PASSWORD=你的密码 sudo -E ./install.sh
```

装完会打印本机 IP 和访问地址。云服务器记得在**安全组/防火墙放行 8080 入站**；
公网暴露建议前置反向代理 + TLS（见文末安全边界）。

> 安装器 `service/install.sh` 是发行版无关的——在 Debian/Ubuntu/RHEL 系（systemd）、
> Alpine（OpenRC）、以及 Arch（pacman）上都能跑；识别不到 init 时会自动回退为
> `nohup` 后台进程（不注册开机自启）。

## 本地开发运行（任意有 Python3 的机器）

```bash
cd AgentBook
python3 server.py
# 打开 http://127.0.0.1:8080/ ；未配 API Key 时自动进入演示模式
```

配置 LLM：登录后点「API 配置」填 Base URL / 模型 / Key，或在环境变量里给：
`AN_AGENT_PASSWORD`（登录密码）、`AN_WEB_HOST`、`AN_WEB_PORT`（默认 0.0.0.0:8080）。

## 嵌入 Alpine VM（目标：alpine-virt ISO）

### 方式 A：手动（最可靠）

1. 用 `alpine-virt` ISO 起 VM，`setup-alpine` 选 `sys` 安装到磁盘。
2. 把本项目拷进 VM（U 盘 / scp / HTTP）。
3. 在 VM 内运行：`sh service/install.sh`
4. 浏览器开 `http://<VM的IP>:8080/`，密码见 `tail -n 20 /var/log/agentbook.log`。

`install.sh` 是通用安装器（见上方「通用 Linux 安装」），在 Alpine 上自动识别
`apk` + OpenRC：装 python3、把应用放到 `/opt/agentbook`、注册 OpenRC 服务
`agentbook`（开机自启）、立即启动。

### 方式 B：一键烧录（需本机有虚拟化）

```bash
bash build/build_alpine_vm.sh /path/to/alpine-virt-3.24.1-x86_64.iso agentbook-vm
# 产出 agentbook-vm.qcow2，启动：
qemu-system-x86_64 -m 1024 -nographic -hda agentbook-vm.qcow2 \
  -netdev user,id=n0 -device virtio-net-pci,netdev=n0
```
> 烧录脚本用 serial 喂安装命令（best-effort）。若 live 镜像不自动 root 登录，按提示手动补命令即可。

### 方式 C：VMware（无需 QEMU，推荐 VMware 用户）

```bash
bash build/vmware/build_vmware_vm.sh /path/to/alpine-virt-3.24.1-x86_64.iso agentbook-vm
# 产出 build/vmware/agentbook-vm/ ：
#   agentbook-vm.vmx        VMware 打开这个
#   agentbook-vm.vmdk       虚拟磁盘（本机有 qemu-img/vmware-vdiskmanager 则自动建；否则 VMware 里点一下「添加硬盘」）
#   agentbook-config.iso    配置光盘（answerfile + firstboot + 应用包），已挂在 ide1:1
```

**使用步骤**：
1. VMware 打开 `agentbook-vm.vmx`（提示升级/转换按默认）。
2. 首次开机：空磁盘回落到 CD-ROM 启动 Alpine live；没自动进就在开机瞬间按 ESC 选 CD-ROM。
   live 环境 `login:` 直接回车进 root。
3. 控制台执行一次（自动装系统 + 拷应用 + 注册开机自启服务，然后关机）：
   ```sh
   sh /media/cdrom1/FIRSTBOO.SH     # 路径不对就试 /dev/sr1、/dev/cdrom1、/media/cdrom
   ```
4. 关机后，VMware「虚拟机设置」里移除两张 ISO（或断开连接）。
5. 重新开机 → 从磁盘启动，浏览器开 `http://<VM的IP>:8080/`，首次密码见 VM 内 `/var/log/agentbook.log`。

> 配置光盘是**纯 Python 生成的 ISO9660**（`build/vmware/mkiso.py`，零三方依赖），
> 内装 `FIRSTBOO.SH`（一键装机脚本）、`ANSWER.TXT`（手动 `setup-alpine` 应答文件）、`AGENTBOOK.TGZ`（应用包）。

**配置盘挂不上时的可靠兜底（HTTP）**：VMware 对第二张 IDE 光驱识别有时不稳定，
可改用宿主 HTTP 把文件喂进 VM（`FIRSTBOO.SH` / `AGENTBOOK.TGZ` 已落盘到 VM 目录）：
1. 宿主（Win）起服务：
   ```bat
   cd E:\Linux_Agent\AgentBook\build\vmware\agentbook-vm
   python3 -m http.server 8000
   ```
2. VM 里先确认有网（VMware NAT 下自动拿 DHCP）；没有就 `udhcpc -i eth0`，再 `ip route` 看网关即宿主 IP。
3. VM 控制台：
   ```sh
   wget http://<宿主IP>:8000/FIRSTBOO.SH -O /tmp/fb.sh
   sh /tmp/fb.sh http://<宿主IP>:8000      # 脚本会从此地址拉 AGENTBOOK.TGZ
   ```
   后续同方式 C 步骤 4–5（移除 ISO、重启、浏览器访问）。

## 关于"改包工具链"的重要说明

Alpine **仓库没有** `dpkg-dev` / `rpmrebuild`。Agent 仍能在 Alpine 上跑命令、看状态、
读文件；但真正的 `.deb` / `.rpm` 重打包需要 Debian / RHEL 系工具链。

`pkg.repack_deb` / `pkg.repack_rpm` 是**容器感知**的，按以下顺序自动决策：

1. **宿主机有工具链**（`dpkg-deb` / `rpmrebuild`）→ 直接在本机改包（最快、最干净）。
2. **宿主机没有，但装了 `podman` / `docker`** → 自动在 disposable 的
   `debian:bookworm` / `rockylinux:9` 容器内改包（对应研究里的"同版本 disposable 环境"）：
   容器里 `apt-get install dpkg-dev` / `dnf install rpmrebuild`，改完把产物拷回宿主机，
   容器 `--rm` 即焚。原签名在两种路径下都会失效，需重签才视为可信包。
3. **两者都无** → 返回明确中文指引（"请 `apk add podman` 或把服务装到 Debian 系 VM"），
   **绝不静默失败**。

容器镜像可用环境变量覆盖：`AN_IMG_DEB`（默认 `debian:bookworm`）、
`AN_IMG_RPM`（默认 `rockylinux:9`）。

> 推荐落地：Alpine VM 里 `apk add podman` 一次，后续所有改包都走路径 2，无需换发行版。
> 若图省事，直接把 AgentBook 装进 Debian / RHEL 系 VM，走路径 1。

## 安全边界（对齐研究第 9 章）

- 不拼自由 Shell：命令由 Agent 显式构造，护栏先分类（deny / privileged / ok）。
- 灾难性命令（删根、格式化、写设备、关机）直接拒绝。
- 高危命令需用户在前端点「确认」才执行（`needs_confirm`）。
- 所有动作写审计日志 `state/audit.log`。
- 登录密码随机生成、独立存储；生产环境建议前置反向代理 + TLS。

## 公网暴露：nginx 反向代理 + TLS（标准 include）

仓库里已放好**可直接 include / symlink** 的 nginx 配置，不用自己手敲、不会因漏配踩坑：

```
deploy/nginx/agentbook.conf        # 标准 vhost：80 → 301 跳 HTTPS + 443 TLS 反代
deploy/nginx/agentbook-http.conf   # 纯 HTTP（内网 / 已有 TLS 终止时用，勿公网直暴露）
```

**用法（装完 AgentBook 后）：**

```bash
# 1) 软链启用（Debian/Ubuntu/RHEL 系 nginx 默认扫 /etc/nginx/sites-enabled/）
sudo ln -s /opt/agentbook/deploy/nginx/agentbook.conf /etc/nginx/sites-enabled/agentbook.conf

# 2) 把配置里两处 server_name 改成你的域名，ssl_certificate* 改成你的证书路径
#    （有域名且走 certbot，直接一步到位，它会自动改好证书路径：
#     sudo certbot --nginx -d 你的域名）

# 3) 校验 + 重载
sudo nginx -t && sudo systemctl reload nginx
```

配置已处理好的关键细节（新手最容易漏的坑）：

- **SSE 实时推送**（`/api/events`）必须 `proxy_buffering off`，否则仪表盘自动刷新 /
  对话流式 token 会被缓冲卡死——这份配置已默认关掉缓冲、拉长 `proxy_read_timeout`。
- **Cookie 鉴权**（`an_token`）由后端 `Set-Cookie` 自动透传，nginx 无需任何额外配置。
- 透传 `X-Real-IP` / `X-Forwarded-For` / `X-Forwarded-Proto`，后端能拿到真实客户端信息。
- TLS 用 Mozilla 中间档（TLS1.2/1.3 + 现代 cipher + OCSP 装订 + HSTS），`nginx -t` 干净。

> 前置 nginx 后，云服务器安全组只需放行 **80/443**，原 8080 可只留本机
> （AgentBook 仍绑 `0.0.0.0:8080`，若要只听本机可设 `AN_WEB_HOST=127.0.0.1`）。

## Docker 一键分发

不想碰系统安装器、只想一条命令起服务的场景（NAS / 云主机 / 本地 Docker）：

```bash
# （可选）先设首次登录密码，避免随机密码
echo "AN_AGENT_PASSWORD=你的密码" > .env
docker compose up -d --build
# 浏览器开 http://<本机IP>:8080/
```

- 镜像基于 `python:3-slim`，**零 pip 依赖**，构建快、体积小。
- 密码 / API Key / 配置全部落在命名卷 `agentbook-data`（容器内 `/data`），
  重建容器不丢；**镜像本身不含任何密钥**。
- `restart: always`：崩溃 / 宿主机重启自动拉起。
- 没设 `AN_AGENT_PASSWORD` 时，首次启动随机生成密码并写入卷，
  用 `docker logs agentbook` 看一眼即可（之后稳定不变）。
- 公网暴露同样建议前置 nginx + TLS（见上节），安全组只放行 80/443。

> 涉及 `.deb/.rpm` 重打包时，容器内可 `apk add podman` 或用宿主机 docker
> （`AN_IMG_DEB` / `AN_IMG_RPM` 覆盖镜像），走研究里的「disposable 容器改包」路径。

## 文件结构

```
AgentBook/
  server.py        HTTP 服务启动器（PHtmlWin 通用面板，绑 0.0.0.0:8080）
  agent.py         Agent 循环 + OpenAI 兼容 LLM 客户端（含 mock 模式）
  tools.py         工具集 + 护栏注册表 + OpenAI function schema
  guard.py         命令护栏（禁用/需授权模式）
  config.py        LLM 配置 + Key / 密码分离存储
  panel.py         AgentPanel（ui.* DSL 描述界面 + @route 绑定事件，暗面构建主题）
  phtmlwin.py      PHtmlWin（vendored：浏览器回退模式，零三方依赖）
  service/install.sh        通用安装器（apt/dnf/yum/apk/pacman + systemd/OpenRC）
  service/agentbook       OpenRC 服务单元（Alpine 用）
  build/build_alpine_vm.sh  烧录脚本（QEMU，ISO → qcow2）
  build/vmware/         VMware 构建套件（无需 QEMU）：
    build_vmware_vm.sh  生成 .vmx + 配置 ISO（+ 自动建 vmdk）
    mkiso.py            纯 Python ISO9660 生成器（零依赖）
    firstboot.sh        VM 内一键装机脚本（挂在配置光盘里）
    answerfile          setup-alpine 手动应答文件
  deploy/nginx/         nginx 反向代理配置（标准 include / symlink 即用）：
    agentbook.conf      80→HTTPS 跳转 + 443 TLS 反代（SSE 已关缓冲）
    agentbook-http.conf 纯 HTTP 版（内网 / 已有 TLS 终止时用）
  deploy/docker/Dockerfile   Docker 镜像定义（python:3-slim，零三方依赖）
  docker-compose.yml         Docker 一键起服务（命名卷持久化 / restart:always）
  .dockerignore              构建时排除密钥与构建产物
  smoke_test.py         端到端冒烟测试（HTTP 层 + 工具层，mock 模式免 Key）
```
> systemd 单元 `/etc/systemd/system/agentbook.service` 由 `install.sh` 运行时生成
> （写入解析后的 python3 绝对路径），不进仓库，避免路径漂移。

## 自测

```bash
export PY=python3
$PY smoke_test.py          # 启动服务→登录/SSE→工具层（护栏/repack/dispatch）共 18 项
```

无需外部 LLM Key：对话走 mock 模式（`system.status` / `system.run_cmd` 演示闭环），
但登录鉴权、SSE 流式、护栏 deny/needs_confirm、repack 容器感知指引、dispatch 路由都是真路径。
