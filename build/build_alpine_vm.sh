#!/usr/bin/env bash
# AgentBook · 烧录脚本（best-effort，需在本机有虚拟化的 Linux 上运行）
#
# 作用：把 AgentBook 应用烧进 alpine-virt ISO，产出一块可启动 qcow2 磁盘。
# 两块磁盘 = 两个阶段：
#   阶段1  boot live ISO  →  setup-alpine 装到磁盘
#   阶段2  boot 磁盘      →  拉取 app.tgz + 跑 install.sh（开机自启服务）
#
# 前置：qemu-system-x86_64、python3、能跑虚拟化的内核。
# 用法： bash build/build_alpine_vm.sh /path/to/alpine-virt-3.24.1-x86_64.iso [vm名]
#
# 说明：QEMU 用户态网络下，VM 访问宿主机用网关 10.0.2.2。
#       本脚本用 serial(stdio) 喂安装命令；若你的 live 镜像不自动以 root 登录控制台，
#       请在出现 login 提示时手动输入 root，再粘贴剩下的命令。完成后磁盘即为成品。
set -e

ISO="${1:-alpine-virt-3.24.1-x86_64.iso}"
NAME="${2:-agentbook-vm}"
DISK="${NAME}.qcow2"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RAM=1024
PORT=8000
QEMU="${QEMU:-qemu-system-x86_64}"

[ -f "$ISO" ] || { echo "用法: $0 <alpine-virt.iso> [vm名]"; exit 1; }
command -v "$QEMU" >/dev/null 2>&1 || { echo "未找到 $QEMU，请先安装 QEMU。"; exit 1; }

echo "[build] 打包应用 → app.tgz"
TMP="$(mktemp -d)"
tar czf "$TMP/app.tgz" -C "$ROOT" server.py config.py guard.py tools.py agent.py phtmlwin.py panel.py i18n.py install.sh service

echo "[build] 创建磁盘 $DISK (8G)"
qemu-img create -f qcow2 "$DISK" 8G >/dev/null

# ---- 阶段1：live ISO 安装到磁盘 ----
echo "[build] 阶段1：setup-alpine 装到 $DISK"
cat > "$TMP/phase1.txt" <<'EOF'
sleep 1
cat > /tmp/ans.cfg <<'ANS'
KEYMAPOPTS="us us"
HOSTNAMEOPTS="agentbook"
INTERFACESOPTS="auto lo
iface lo inet loopback

auto eth0
iface eth0 inet dhcp
"
DNSOPTS=""
TIMEZONEOPTS="UTC"
PROXYOPTS="none"
APKREPOSITORYOPTS="http://dl-cdn.alpinelinux.org/alpine/v3.24/main http://dl-cdn.alpinelinux.org/alpine/v3.24/community"
SSHDOPTS="none"
NTPOPTS="none"
DISKOPTS="--install /dev/vda"
USEROPTS="--disabled"
GUIOPTS="none"
ANS
setup-alpine -c /tmp/ans.cfg
poweroff
EOF
"$QEMU" -m "$RAM" -nographic -cdrom "$ISO" -hda "$DISK" -boot d \
  -netdev user,id=n0 -device virtio-net-pci,netdev=n0 \
  < "$TMP/phase1.txt" >/dev/null 2>&1 || echo "[build] 阶段1 结束（或需手动确认）"

# ---- 阶段2：boot 磁盘，拉 app + 安装 ----
echo "[build] 阶段2：拉取 app + 注册服务（启动临时 HTTP 服务）"
python3 -m http.server -d "$TMP" "$PORT" >/dev/null 2>&1 &
HTTP_PID=$!
sleep 1
cat > "$TMP/phase2.txt" <<EOF
root
sleep 2
apk add --no-cache python3 wget
wget -q http://10.0.2.2:$PORT/app.tgz -O /tmp/app.tgz
mkdir -p /opt/agentbook && tar xzf /tmp/app.tgz -C /opt/agentbook
sh /opt/agentbook/install.sh
poweroff
EOF
"$QEMU" -m "$RAM" -nographic -hda "$DISK" -boot c \
  -netdev user,id=n0 -device virtio-net-pci,netdev=n0 \
  < "$TMP/phase2.txt" >/dev/null 2>&1 || echo "[build] 阶段2 结束（或需手动确认）"
kill "$HTTP_PID" 2>/dev/null || true

rm -rf "$TMP"
echo ""
echo "✅ 成品磁盘: $(pwd)/$DISK"
echo "   启动: $QEMU -m $RAM -nographic -hda $DISK -netdev user,id=n0 -device virtio-net-pci,netdev=n0"
echo "   启动后浏览器访问 http://<VM的IP>:8080/ ，首次登录密码见 /var/log/agentbook.log"
