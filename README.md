# AgentBook · 用自然语言控制一台 Linux 的运维 Agent

**一句话**：把一台 Linux 变成"能听懂人话的运维助手"——你在浏览器里用中文（或英文）下指令，
它调工具去**真的执行、查状态、改包**，结果实时回给你。

它不是聊天机器人玩具：底层是 9 类白名单工具 + 命令护栏，灾难性操作直接拒、高危操作要你点确认。

---

## 这个项目解决什么

- 你有一台 Linux（云服务器 / 内网 VM / 树莓派），想随时用自然语言查状态、跑命令、改配置，又不想每次 SSH。
- 你想把"给 `.deb` 预置配置后重打包"这类重复运维动作，变成一句话触发。
- 你要的是**独立、自托管、数据在自己机器上**的 Agent，不依赖任何第三方云服务账号。

> 来源：把《deb_rpm 安装包修改工具横评与预置配置免交互部署方案》里的 9 类白名单动作
> 做成了 Agent 的「工具集」——你说"把 foo.deb 预置配置后重打包"，它就调 `pkg_repack_deb`。

**形态**：一台独立 Linux 上开机自启一个服务，Win / Mac 浏览器用 `IP:端口` 登录，看到
**对话页 + 状态页**。与本地 AntNest 无关，完全独立。

---

## 怎么用（五步上手）

### 1. 跑起来
选一种方式（命令见下方「部署方式」），服务都会绑 `0.0.0.0:8080`：
- 最省事（有 Docker）：`docker compose up -d --build`
- 通用 Linux 一条命令：`sudo ./install.sh`
- 本机随便试：`python3 server.py`

### 2. 登录
浏览器开 `http://<机器IP>:8080/`。
首次登录密码是服务启动时**随机生成**的，去这几处看一眼：
- 通用安装 / VM：`tail -n 20 /var/log/agentbook.log`
- Docker：`docker logs agentbook`
- 想自己定密码：起服务前设 `AN_AGENT_PASSWORD=你的密码`，或控制台 `python3 server.py --set-password 你的密码`（重启生效）

### 3. 跟着向导配好 LLM
登录后自动弹出**新手引导**，三步带你配好：
1. 选供应商预设：`DeepSeek` / `OpenAI` / `Ollama` / `自定义`——选完自动带出 Base URL 和模型。
2. 贴你的 API Key（Key 单独存，不进仓库、不进镜像）。
3. 点示例提示直接试：`查看系统状态` / `执行 uname -a` / `列出监听端口`。

> 没配 Key 也能进**演示模式**（mock，不真调 LLM），先看交互长啥样。

### 4. 直接说话
在对话框里用大白话下指令，比如：
- "查看系统状态" → 调 `system_status`，右侧仪表盘实时刷新
- "执行 uname -a" → 调 `system_run_cmd`，结果**流式**回显（字一个个蹦）
- "把 foo.deb 预置配置后重打包" → 调 `pkg_repack_deb`

回复是**真流式**的；工具调用显示在左侧「操作日志」里（名称 + 状态 + 参数/结果），不是糊成一团 JSON。
仪表盘每 5 秒自动刷新系统指标（负载 / 内存 / 磁盘 / 端口 / 服务 / 工具链）。

### 5. 想深配就开「API 配置」
右上角抽屉里：换预设、点「**检测连接**」验证端点（不通会明确报错，不静默卡死）、自动拉模型列表、切中 / 英语言。
选择都会保存，重启也保持。

---

## 能做什么

- **对话页**：自然语言 → Agent → 工具调用 → 结果，**真流式逐 token 输出**。支持 OpenAI 兼容端点（DeepSeek / 本地 vLLM / Ollama）。
- **状态页**：实时显示内核 / uptime / 负载 / 内存 / 磁盘 / 监听端口 / 运行服务 / 工具链可用性。
- **工具集**（受护栏，工具名均为下划线）：
  - `system_run_cmd` — 执行命令（灾难性命令拒绝；sudo/rm -rf/格式化/改系统服务需界面确认）
  - `system_status` — 只读状态
  - `files_read` / `files_write` — 文件读写（系统关键路径需确认）
  - `pkg_inspect` — 查看 .deb/.rpm 控件/文件/脚本
  - `pkg_install_test` — disposable 预检（不真装）
  - `pkg_repack_deb` / `pkg_repack_rpm` — 基于现有包重打包（**原签名失效，需重签**）
  - `pkg_rollback` — 回滚/重装（L3，需确认）
- **登录**：首次随机生成密码打印到日志；token 会话。
- **多语言**：面板内置中文 / English 切换（顶栏下拉），选择持久化。
- **新手引导**：首次登录弹三步向导（预设 → 填 Key → 示例），小白零门槛。

---

## 部署方式（从零开始，给别人看）

### 开始前你需要

- 一台 **Linux 机器**（云服务器 / 本地 VM / 树莓派都行），能用 SSH 或控制台登进去。
- **root 或 sudo 权限**（通用安装 / VM 方式需要）。
- 走 Docker 方式则本机已装好 **Docker + docker compose 插件**。
- 一个 **LLM API Key**（DeepSeek / OpenAI / 任意 OpenAI 兼容端点）。不配也能跑演示模式，但没法真调 LLM。

### 我该选哪种？

| 你的场景 | 选这个 |
|---|---|
| 有台独立 Linux，想要开机自启、长期用 | **通用 Linux 安装**（推荐） |
| 本机 / NAS 已有 Docker，想一条命令起 | **Docker 一键分发** |
| 只想在自己电脑上 5 分钟试一下 | **本地开发运行** |
| 想烧一台专属 Alpine VM 镜像 | **嵌入 Alpine VM**（进阶） |

---

### 通用 Linux 安装（推荐）

```bash
# 1. 拉代码
git clone https://github.com/llxpy/AgentBook.git
cd AgentBook

# 2. 一条命令安装并启动（自动装 python3、注册开机自启服务、立刻起服务）
sudo ./install.sh
#    想一开始就定好登录密码，加 --password：
sudo ./install.sh --password 你的密码
```

装完脚本会打印：**监听地址、本机 IP、访问地址、首次密码来源**。

下一步：
1. 云服务器：去**安全组 / 防火墙放行 8080 端口（TCP 入站）**。
2. 浏览器打开 `http://<上面打印的IP>:8080/`。
3. 首次密码：脚本已打印；也可 `sudo tail -n 20 /var/log/agentbook.log` 再看。
4. 公网暴露建议前置 nginx + TLS（见下方「公网暴露」）。

> 安装器发行版无关：Debian/Ubuntu/RHEL（systemd）、Alpine（OpenRC）、Arch（pacman）都能跑；
> 识别不到 init 系统时自动回退为 `nohup` 后台进程（不注册开机自启）。

### Docker 一键分发

前置：先装好 Docker 与 docker compose 插件（官方文档：https://docs.docker.com/get-docker/）。

```bash
# 1. 拉代码
git clone https://github.com/llxpy/AgentBook.git
cd AgentBook

# 2. （可选）设首次登录密码；不设则随机生成
echo "AN_AGENT_PASSWORD=你的密码" > .env

# 3. 起服务
docker compose up -d --build
```

下一步：
1. 浏览器打开 `http://<这台机器的IP>:8080/`（本机就是 `http://127.0.0.1:8080/`）。
2. 忘了随机密码：`docker logs agentbook` 看启动日志里的「首次登录密码」。
3. 数据（密码 / Key / 配置）存在命名卷 `agentbook-data`，重建容器不丢；**镜像本身不含任何密钥**。
4. `restart: always`：崩溃或宿主机重启自动拉起。

### 本地开发运行

适合在自己电脑上快速试，不需要 root、不需要 Docker。

```bash
cd AgentBook
python3 server.py        # 打开 http://127.0.0.1:8080/ ；未配 Key 自动演示模式
```

可用环境变量：`AN_AGENT_PASSWORD`（登录密码）、`AN_WEB_HOST`、`AN_WEB_PORT`（默认 0.0.0.0:8080）。
改密码：`python3 server.py --set-password 你的密码`（重启生效）。

### 嵌入 Alpine VM（进阶）

把 AgentBook 烧进一台独立 Alpine VM，开机即从磁盘起、自动跑服务。
**方式 A 手动**：alpine-virt ISO 起 VM → `setup-alpine` 装到磁盘 → 拷项目进 VM → `sh service/install.sh`。
**方式 B 一键烧录**（需本机有 QEMU）：`bash build/build_alpine_vm.sh <alpine-virt.iso> agentbook-vm`，产出 qcow2。
**方式 C VMware**（无需 QEMU）：`bash build/vmware/build_vmware_vm.sh <alpine-virt.iso> agentbook-vm`，
产出 `.vmx` + 配置 ISO；VMware 打开 `.vmx` → 首启从 CD-ROM 进 live → `sh /media/cdrom1/FIRSTBOO.SH` 一键装机 →
移除两张 ISO 重启。配置盘挂不上时用 HTTP 兜底：宿主在 `build/vmware/agentbook-vm` 起
`python3 -m http.server 8000`，VM 内 `wget http://<宿主IP>:8000/FIRSTBOO.SH` 拉取重跑。

---

## 关于"改包工具链"的重要说明

Alpine **仓库没有** `dpkg-dev` / `rpmrebuild`。Agent 仍能在 Alpine 跑命令/看状态/读文件；
但真 `.deb`/`.rpm` 重打包需 Debian/RHEL 工具链。`pkg_repack_*` 是**容器感知**的，三级决策：
1. 宿主机有工具链（`dpkg-deb`/`rpmrebuild`）→ 本机改；
2. 无工具链但有 `podman`/`docker` → 自动在 disposable `debian:bookworm`/`rockylinux:9` 容器内改，`--rm` 即焚；
3. 两者皆无 → 明确中文指引，**绝不静默失败**。

镜像可用 `AN_IMG_DEB`（默认 `debian:bookworm`）/ `AN_IMG_RPM`（默认 `rockylinux:9`）覆盖。
推荐：Alpine VM 里 `apk add podman` 一次，后续改包全走路径 2。

---

## 公网暴露：nginx 反向代理 + TLS

仓库放了可直接 `include`/`symlink` 的配置文件（`deploy/nginx/agentbook.conf` 带 TLS，
`agentbook-http.conf` 纯 HTTP 内网用）：
```bash
sudo ln -s /opt/agentbook/deploy/nginx/agentbook.conf /etc/nginx/sites-enabled/agentbook.conf
# 改两处 server_name + ssl_certificate* 路径（有域名直接 sudo certbot --nginx -d 你的域名）
sudo nginx -t && sudo systemctl reload nginx
```
关键细节（已默认处理好）：SSE `/api/events` 必须 `proxy_buffering off`（否则流式/仪表盘卡死）；
`an_token` Cookie 由后端自动透传；透传 `X-Real-IP`/`X-Forwarded-*`。前置后安全组只放行 80/443，
AgentBook 可设 `AN_WEB_HOST=127.0.0.1` 只听本机。

---

## 安全边界

- 不拼自由 Shell：命令由 Agent 显式构造，护栏先分类（deny / privileged / ok）。
- 灾难性命令（删根、格式化、写设备、关机）直接拒绝。
- 高危命令需用户在前端点「确认」才执行。
- 所有动作写审计日志 `state/audit.log`。
- 登录密码随机生成、独立存储；**明文 HTTP 下密码以 Cookie 明文传输**，生产务必前置 TLS。

---

## 常见问题

**忘了登录密码？** 控制台 `python3 server.py --set-password 你的密码`（重启生效）；或读服务机 `state/agent_password`（0600，首次自动生成）。

**流式输出卡住 / 不动？** 直连 `<IP>:8080` 正常、走 nginx 才卡 → 反代缓冲问题，确认 nginx 配了 `proxy_buffering off`（仓库配置已默认关）。

**配了 API 但对话报 HTTP 400？** 检查 Base URL 是否带 `/v1`；点「检测连接」先验证端点/Key。

**改包提示"无工具链"？** Alpine 没有 `dpkg-dev`/`rpmrebuild`，VM 里 `apk add podman`（走容器内改包），或装到 Debian/RHEL VM。

**8080 被占用？** 起服务前设 `AN_WEB_PORT=9000`（Docker 改 `ports:` 映射）。

**只想本机访问、前置 nginx？** 设 `AN_WEB_HOST=127.0.0.1`。

**重置配置？** 删 `config.json` + `state/`（保留 `state/agent_password` 可不改密码），重启回到默认 + 向导。

---

## 文件结构

```
AgentBook/
  server.py        HTTP 服务启动器（PHtmlWin 通用面板，绑 0.0.0.0:8080）
  agent.py         Agent 循环 + OpenAI 兼容 LLM 客户端（真流式 SSE + mock 模式）
  tools.py         工具集 + 护栏注册表 + OpenAI function schema（工具名下划线）
  guard.py         命令护栏（禁用/需授权模式）
  config.py        LLM 配置 + Key / 密码分离存储（ui_lang 持久化）
  panel.py         AgentPanel（ui.* DSL 描述界面 + @route 绑定事件，暗面构建主题）
  i18n.py          中英双语字典（69 key 对齐）+ 供应商预设 + 示例提示
  phtmlwin.py      PHtmlWin（vendored：浏览器回退模式，零三方依赖）
  service/install.sh        通用安装器（apt/dnf/yum/apk/pacman + systemd/OpenRC）
  service/agentbook       OpenRC 服务单元（Alpine 用）
  build/build_alpine_vm.sh  烧录脚本（QEMU，ISO → qcow2）
  build/vmware/         VMware 构建套件（无需 QEMU）：build_vmware_vm.sh / mkiso.py / firstboot.sh / answerfile
  deploy/nginx/         nginx 反向代理配置（标准 include / symlink 即用）
  deploy/docker/Dockerfile   Docker 镜像定义（python:3-slim，零三方依赖）
  docker-compose.yml         Docker 一键起服务（命名卷持久化 / restart:always）
  .dockerignore              构建时排除密钥与构建产物
  smoke_test.py         端到端冒烟测试（HTTP 层 + 工具层，mock 模式免 Key）
```
> systemd 单元 `/etc/systemd/system/agentbook.service` 由 `install.sh` 运行时生成（写入解析后的 python3 绝对路径），不进仓库。

## 自测

```bash
export PY=python3
$PY smoke_test.py          # 启动服务→登录/SSE→工具层（护栏/repack/dispatch）共 19 项
```
无需外部 LLM Key：走 mock 模式演示闭环，但登录鉴权、SSE 流式、护栏 deny/needs_confirm、repack 容器感知指引、dispatch 路由都是真路径。
