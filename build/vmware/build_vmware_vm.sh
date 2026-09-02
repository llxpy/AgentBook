#!/usr/bin/env bash
# AgentBook · VMware 构建脚本（无需 QEMU）
#
# 产出：一个可直接用 VMware Workstation/Player 打开的虚拟机目录，内含
#   - <name>.vmx              虚拟机定义
#   - <name>.vmdk             虚拟磁盘（若本机有 qemu-img / vmware-vdiskmanager 则自动建；否则给指引）
#   - agentbook-config.iso  配置光盘（answerfile + firstboot + 应用包），VM 内挂载即用
#
# 前置（尽量自动探测）：
#   - bash / python3（生成 ISO，纯标准库）
#   - tar（打包应用）
#   - 可选 qemu-img 或 vmware-vdiskmanager（建 vmdk；都没有也能跑，会告诉你怎么在 VMware 里点一下）
#
# 用法：
#   bash build/vmware/build_vmware_vm.sh /path/to/alpine-virt-3.24.1-x86_64.iso [vm名]
#
set -e

ISO="${1:-alpine-virt-3.24.1-x86_64.iso}"
NAME="${2:-agentbook-vm}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"     # agentbook/
HERE="$(cd "$(dirname "$0")" && pwd)"           # build/vmware/
OUT="$HERE/$NAME"
VMDK="$OUT/$NAME.vmdk"
VMX="$OUT/$NAME.vmx"
CONFIG_ISO="$OUT/agentbook-config.iso"
DISKSIZE=8G
PY="${PY:-python3}"

[ -f "$ISO" ] || { echo "用法: $0 <alpine-virt.iso> [vm名]"; exit 1; }

echo "[vmware] 输出目录: $OUT"
mkdir -p "$OUT"

echo "[vmware] 打包应用 → AGENTBOOK.TGZ"
TMP="$OUT/.build-tmp"            # 放 POSIX 路径下，避免 mktemp 返回 C: 盘符导致 tar 误判为远程归档
rm -rf "$TMP"; mkdir -p "$TMP"
tar czf "$TMP/AGENTBOOK.TGZ" -C "$ROOT" server.py config.py guard.py tools.py agent.py phtmlwin.py panel.py service

echo "[vmware] 组装配置光盘内容"
STAGING="$TMP/staging"
mkdir -p "$STAGING"
cp "$HERE/answerfile"   "$STAGING/ANSWER.TXT"
cp "$HERE/firstboot.sh" "$STAGING/FIRSTBOO.SH"
cp "$TMP/AGENTBOOK.TGZ"   "$STAGING/AGENTBOOK.TGZ"

# 同时把 FIRSTBOO.SH 与 AGENTBOOK.TGZ 落盘到 VM 目录，方便用 HTTP 兜底喂进 VM
cp "$HERE/firstboot.sh" "$OUT/FIRSTBOO.SH"
cp "$TMP/AGENTBOOK.TGZ"   "$OUT/AGENTBOOK.TGZ"

echo "[vmware] 生成配置 ISO（纯 Python ISO9660）"
# 调 native Python 时把 POSIX 路径转成 Windows 路径（避免 /e/... 被当成相对盘符）
winpath() { cygpath -w "$1" 2>/dev/null || echo "$1"; }
"$PY" "$(winpath "$HERE/mkiso.py")" "$(winpath "$CONFIG_ISO")" "$(winpath "$STAGING")"

echo "[vmware] 准备虚拟磁盘 $VMDK"
# 探测可用的建盘工具：qemu-img > PATH 上的 vmware-vdiskmanager > 常见 VMware 安装路径
VMDKTOOL=""
if command -v qemu-img >/dev/null 2>&1; then
  VMDKTOOL="qemu-img"
elif command -v vmware-vdiskmanager >/dev/null 2>&1; then
  VMDKTOOL="vmware-vdiskmanager"
else
  for p in \
    "/c/Program Files (x86)/VMware/VMware Workstation/vmware-vdiskmanager.exe" \
    "/c/Program Files/VMware/VMware Workstation/vmware-vdiskmanager.exe" \
    "/c/Program Files (x86)/VMware/VMware Player/vmware-vdiskmanager.exe" \
    "/c/Program Files/VMware/VMware Player/vmware-vdiskmanager.exe"; do
    [ -x "$p" ] && VMDKTOOL="$p" && break
  done
fi

if [ -n "$VMDKTOOL" ]; then
  case "$(basename "$VMDKTOOL")" in
    qemu-img*)
      qemu-img create -f vmdk "$VMDK" "$DISKSIZE" >/dev/null
      echo "[vmware]   用 qemu-img 创建 vmdk"
      ;;
    *)
      "$VMDKTOOL" -c -t 0 -s "$DISKSIZE" -a lsilogic "$VMDK" >/dev/null
      echo "[vmware]   用 vmware-vdiskmanager 创建 vmdk"
      ;;
  esac
else
  echo "[vmware]   未找到 qemu-img / vmware-vdiskmanager，跳过建盘。"
  echo "          VMware 里『编辑虚拟机设置 → 添加 → 硬盘 → 8 GB』，"
  echo "          VMware 会自动生成同名 vmdk（$NAME.vmdk），无需改名。"
fi

echo "[vmware] 写虚拟机定义 $VMX"
# 取 ISO 绝对路径（VMware 是 Windows 程序，需要 Windows 风格路径）
ISO_ABS="$(cygpath -w "$(cd "$(dirname "$ISO")" && pwd)/$(basename "$ISO")" 2>/dev/null || echo "$ISO")"
# VMware Workstation 16 Pro 最高支持 virtualHW.version 18；默认用 18。
VHW="${AN_VHW:-18}"
cat > "$VMX" <<EOF
.encoding = "UTF-8"
config.version = "8"
virtualHW.version = "$VHW"
memsize = "1024"
numvcpus = "1"
cpuid.coresPerSocket = "1"
guestOS = "other4xlinux"
scsi0.present = "TRUE"
scsi0.virtualDev = "lsilogic"
scsi0:0.present = "TRUE"
scsi0:0.fileName = "$NAME.vmdk"
scsi0:0.deviceType = "disk"
scsi0:0.redo = ""
ide1:0.present = "TRUE"
ide1:0.fileName = "$ISO_ABS"
ide1:0.deviceType = "cdrom-image"
ide1:1.present = "TRUE"
ide1:1.fileName = "agentbook-config.iso"
ide1:1.deviceType = "cdrom-image"
ethernet0.present = "TRUE"
ethernet0.connectionType = "nat"
ethernet0.virtualDev = "e1000"
ethernet0.addressType = "generated"
floppy0.present = "FALSE"
usb.present = "TRUE"
sound.present = "FALSE"
svga.autodetect = "TRUE"
pciBridge0.present = "TRUE"
pciBridge4.present = "TRUE"
hpet0.present = "TRUE"
bios.bootOrder = "hdd,cdrom"
tools.syncTime = "TRUE"
EOF

rm -rf "$TMP"
echo ""
echo "✅ 成品目录: $OUT"
echo "   ├─ $NAME.vmx               （VMware 打开这个）"
echo "   ├─ $NAME.vmdk              （虚拟磁盘，若上面跳过了请手动建）"
echo "   └─ agentbook-config.iso  （配置光盘，已挂在 ide1:1）"
echo ""
echo "=== 使用步骤 ==="
echo "1) VMware 打开 $VMX（若提示升级/转换，按默认即可）。"
echo "2) 首次开机：空磁盘会回落到 CD-ROM 启动 Alpine live；若没自动进，"
echo "   开机瞬间按 ESC 选择『CD-ROM』。到 login: 直接回车进 root。"
echo "3) 在控制台执行一次："
echo "     sh /media/cdrom1/FIRSTBOO.SH"
echo "   （路径不对就试 /dev/sr1、/dev/cdrom1、/media/cdrom）"
echo "   脚本会自动装系统 + 拷应用 + 注册开机自启服务，然后关机。"
echo "4) 关机后，VMware『虚拟机设置』里移除两张 ISO（或断开连接）。"
echo "5) 重新开机 → 从磁盘启动，浏览器开 http://<VM的IP>:8080/"
echo "   首次登录密码见 VM 内 /var/log/agentbook.log"
