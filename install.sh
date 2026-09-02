#!/bin/sh
# AgentBook · 通用 Linux 安装器（云服务器 / 裸机 / Alpine 通用）
#
# 用法：
#   sudo ./install.sh                          # 装 python3 + 注册开机自启服务 + 启动，绑 0.0.0.0:8080
#   sudo ./install.sh --password 你的密码       # 指定首次登录密码（非交互部署用）
#   AN_AGENT_PASSWORD=xxx sudo -E ./install.sh  # 同上，用环境变量
#
# 特性：
#   - 纯标准库运行，零 pip 依赖；只会按需安装 python3 本体。
#   - 自动识别包管理器：apt / dnf / yum / apk / pacman。
#   - 自动识别 init 系统：systemd（首选）→ OpenRC（Alpine）→ nohup 兜底。
#   - 服务 Restart=always（systemd）/ 默认级（OpenRC），崩溃自动拉起。
set -e

SRC="$(cd "$(dirname "$0")" && pwd)"
DEST=/opt/agentbook
PORT="${AN_WEB_PORT:-8080}"

echo "=================================================="
echo "  AgentBook · 通用安装器"
echo "  源目录: $SRC"
echo "  目标目录: $DEST"
echo "=================================================="

# 1) root 检查
if [ "$(id -u)" -ne 0 ]; then
  echo "❌ 请使用 root 运行：  sudo ./install.sh" >&2
  exit 1
fi

# 2) 检测包管理器
PKG_MGR="none"
if command -v apt-get >/dev/null 2>&1; then PKG_MGR=apt
elif command -v dnf    >/dev/null 2>&1; then PKG_MGR=dnf
elif command -v yum    >/dev/null 2>&1; then PKG_MGR=yum
elif command -v apk    >/dev/null 2>&1; then PKG_MGR=apk
elif command -v pacman >/dev/null 2>&1; then PKG_MGR=pacman
fi
echo "[1/6] 包管理器: $PKG_MGR"

# 3) 安装 python3（纯标准库，无 pip 依赖）
if ! command -v python3 >/dev/null 2>&1; then
  echo "[2/6] 安装 python3 …"
  case "$PKG_MGR" in
    apt)    apt-get update -y && apt-get install -y python3 ;;
    dnf)    dnf install -y python3 ;;
    yum)    yum install -y python3 ;;
    apk)    apk add --no-cache python3 ;;
    pacman) pacman -S --noconfirm python3 ;;
    *) echo "❌ 未识别到包管理器，请先手动安装 python3 再运行" >&2; exit 1 ;;
  esac
else
  echo "[2/6] python3 已存在，跳过安装"
fi
PY="$(command -v python3)"
echo "      使用 python3: $PY"

# 4) 拷贝应用
echo "[3/6] 拷贝应用到 $DEST …"
rm -rf "$DEST"
mkdir -p "$DEST"
(cd "$SRC" && tar cf - server.py config.py guard.py tools.py agent.py phtmlwin.py panel.py i18n.py service) \
  | tar xf - -C "$DEST"
mkdir -p "$DEST/state"

# 5) 设置密码（如提供）
PW="${AN_AGENT_PASSWORD:-}"
if [ "$1" = "--password" ] && [ -n "$2" ]; then
  PW="$2"
fi
if [ -n "$PW" ]; then
  echo "[4/6] 写入登录密码 …"
  (cd "$DEST" && "$PY" server.py --set-password "$PW")
else
  echo "[4/6] 未指定密码，首次启动随机生成（见服务日志）"
fi

# 6) 注册并启动系统服务
echo "[5/6] 注册系统服务 …"
SVC="unknown"
if [ -d /run/systemd/system ] || (command -v systemctl >/dev/null 2>&1 && [ -d /etc/systemd ]); then
  # ---- systemd（Debian/Ubuntu/RHEL 系云服务器首选）----
  cat >/etc/systemd/system/agentbook.service <<EOF
[Unit]
Description=AntNest Web · Linux 运维 Agent 控制服务
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=$PY -u $DEST/server.py
WorkingDirectory=$DEST
Restart=always
RestartSec=3
StandardOutput=append:/var/log/agentbook.log
StandardError=append:/var/log/agentbook.err
# 可选覆盖（取消注释后用 systemctl daemon-reload + restart 生效）：
# Environment=AN_WEB_PORT=8080
# Environment=AN_WEB_HOST=0.0.0.0
# Environment=AN_AGENT_PASSWORD=你的密码

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  if systemctl enable --now agentbook 2>/dev/null; then
    SVC="systemd"
  else
    systemctl enable agentbook 2>/dev/null || true
    SVC="systemd(需手动 start)"
  fi
elif command -v rc-update >/dev/null 2>&1; then
  # ---- OpenRC（Alpine）----
  cp "$DEST/service/agentbook" /etc/init.d/agentbook
  chmod +x /etc/init.d/agentbook
  rc-update add agentbook default
  rc-service agentbook start || true
  SVC="openrc"
else
  # ---- 兜底：nohup 后台（不注册开机自启）----
  echo "      未识别到 systemd/OpenRC，改用 nohup 后台启动"
  (cd "$DEST" && nohup "$PY" server.py >/var/log/agentbook.log 2>&1 &)
  SVC="nohup"
fi
echo "      服务方式: $SVC"

# 7) 访问信息
sleep 1
IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
if [ -z "$IP" ]; then
  IP="$(ip -4 addr show 2>/dev/null | grep -o 'inet [0-9.]*' | grep -v '127.0.0.1' | head -1 | awk '{print $2}')"
fi
echo ""
echo "=================================================="
echo "  ✅ AgentBook 面板 · 在暗面构建  安装完成"
echo "  监听: 0.0.0.0:$PORT  (本机 / 同网 / 公网均可)"
echo "  本机 IP: ${IP:-<未知>}"
echo "  浏览器打开: http://${IP:-<本机或公网IP>}:$PORT/"
if [ -n "$PW" ]; then
  echo "  首次登录密码: $PW"
else
  echo "  首次登录密码：见日志 tail -n 20 /var/log/agentbook.log"
fi
echo "--------------------------------------------------"
echo "  ⚠️ 云服务器：请在安全组/防火墙放行 $PORT 入站。"
echo "  ⚠️ 公网暴露建议前置反向代理 + TLS（见 README）。"
echo "  管理命令："
echo "    systemd: systemctl restart|status agentbook"
echo "    openrc : rc-service agentbook restart"
echo "=================================================="
