#!/bin/sh
# antnest-web · VMware 首次启动一键装机脚本（在 Alpine live ISO 控制台里执行一次）
#
# 用法（VM 首次开机、停在 login: 时）：
#   login: 直接回车以 root 进入 live 环境，然后：
#     sh /media/cdrom1/FIRSTBOO.SH        # 路径不对就试 /dev/sr1 或 /dev/cdrom1
#
# 本脚本会：① 把基础系统装到 /dev/sda；② 拷入应用；③ chroot 内装 python3 +
# 注册 antnest-web 开机自启服务；④ 关机。重启后从磁盘启动，浏览器即可访问。
#
# 分级幂等：若磁盘上已检测到基础系统（/etc/os-release）则跳过 setup-disk，
# 只补拷应用+注册服务；若应用已完整（server.py 存在）则直接关机，避免重复清盘。
set -e

echo "[firstboot] 正在定位配置（配置光盘 / HTTP 二选一）…"
MNT="$(mktemp -d)"
CFG=""
for dev in /dev/sr0 /dev/sr1 /dev/cdrom /dev/cdrom0 /dev/cdrom1; do
  if mount -t iso9660 -o ro "$dev" "$MNT" 2>/dev/null; then
    if [ -f "$MNT/FIRSTBOO.SH" ] || [ -f "$MNT/ANTNEST.TGZ" ]; then CFG="$MNT"; break; fi
    umount "$MNT" 2>/dev/null || true
  fi
done
if [ -z "$CFG" ]; then
  echo "[firstboot] 尝试软盘兜底…"
  modprobe floppy 2>/dev/null || true
  if mount -t vfat -o ro /dev/fd0 "$MNT" 2>/dev/null && [ -f "$MNT/ANTNEST.TGZ" ]; then CFG="$MNT"; fi
fi
# HTTP 兜底：用法  sh firstboot.sh http://<宿主IP>:8000
if [ -z "$CFG" ] && [ -n "$1" ]; then
  echo "[firstboot] 从 HTTP 拉取应用包: $1"
  mkdir -p /tmp/cfg
  if wget -q "$1/ANTNEST.TGZ" -O /tmp/cfg/ANTNEST.TGZ 2>/dev/null && [ -f /tmp/cfg/ANTNEST.TGZ ]; then
    CFG=/tmp/cfg
  else
    echo "[firstboot] HTTP 拉取失败，检查地址/网络"
  fi
fi
[ -n "$CFG" ] || { echo "[firstboot] 未找到配置（光盘未挂载且未给 HTTP 地址）。"; echo "   用法: sh firstboot.sh http://<宿主IP>:8000"; exit 1; }
echo "[firstboot] 配置来源: $CFG"

# ---------- 分级状态探测 ----------
mkdir -p /mnt/probe /mnt/new
NEWROOT=""
APP_DONE=0
for p in sda1 sda2 sda3 sda4; do
  if mount -t ext4 -o ro /dev/$p /mnt/probe 2>/dev/null; then
    if [ -f /mnt/probe/etc/os-release ]; then
      NEWROOT="$p"
      if [ -f /mnt/probe/opt/antnest-web/server.py ]; then APP_DONE=1; fi
    fi
    umount /mnt/probe 2>/dev/null || true
    [ -n "$NEWROOT" ] && break
  fi
done

# 应用已完整 → 直接关机，避免重复清盘
if [ "$APP_DONE" = "1" ]; then
  echo "[firstboot] 应用已安装完整，无需重装。即将关机。"
  echo "  下一步：VMware『虚拟机设置』移除两张 ISO，开机后浏览器访问 http://<VM的IP>:8080/"
  echo "  首次登录密码见 VM 内 /var/log/antnest-web.log"
  sleep 3
  poweroff
fi

# 磁盘已有基础系统但缺应用 → 跳过 setup-disk
if [ -n "$NEWROOT" ]; then
  echo "[firstboot] 检测到磁盘上已有基础系统($NEWROOT)，跳过 setup-disk，仅补装应用+服务。"
else
  echo "[firstboot] ① 安装基础系统到 /dev/sda（sys 模式）…"
  echo "[firstboot]    配置 live 环境网络仓库（setup-disk 需要 syslinux）…"
  echo 'http://dl-cdn.alpinelinux.org/alpine/v3.24/main' > /etc/apk/repositories
  echo 'http://dl-cdn.alpinelinux.org/alpine/v3.24/community' >> /etc/apk/repositories
  apk update || true
  yes | setup-disk -m sys /dev/sda
  # 重探测新根
  for p in sda1 sda2 sda3 sda4; do
    if mount -t ext4 -o ro /dev/$p /mnt/probe 2>/dev/null; then
      if [ -f /mnt/probe/etc/os-release ]; then NEWROOT="$p"; fi
      umount /mnt/probe 2>/dev/null || true
      [ -n "$NEWROOT" ] && break
    fi
  done
fi
[ -n "$NEWROOT" ] || { echo "[firstboot] 找不到新根分区，安装失败，请检查 /dev/sda"; exit 1; }

echo "[firstboot] ② 挂载新根分区 /dev/$NEWROOT → /mnt/new"
umount /mnt/new 2>/dev/null || true
mount -t ext4 /dev/$NEWROOT /mnt/new

echo "[firstboot] ③ 拷贝应用 → /mnt/new/opt/antnest-web"
mkdir -p /mnt/new/opt/antnest-web
tar xzf "$CFG/ANTNEST.TGZ" -C /mnt/new/opt/antnest-web

echo "[firstboot] ④ chroot 内装依赖 + 注册开机自启服务"
cp /etc/resolv.conf /mnt/new/etc/resolv.conf 2>/dev/null || true
mount -t proc proc /mnt/new/proc
mount -t sysfs sys /mnt/new/sys
mount -o bind /dev /mnt/new/dev
chroot /mnt/new /bin/sh -c "
  echo 'http://dl-cdn.alpinelinux.org/alpine/v3.24/main' > /etc/apk/repositories
  echo 'http://dl-cdn.alpinelinux.org/alpine/v3.24/community' >> /etc/apk/repositories
  apk update || true
  apk add --no-cache python3
  cp /opt/antnest-web/service/antnest-web /etc/init.d/antnest-web
  chmod +x /etc/init.d/antnest-web
  rc-update add antnest-web default
  echo antnest-web > /etc/hostname
  # 写入网卡配置：Alpine 安装后默认 /etc/network/interfaces 可能为空，
  # 导致 OpenRC networking 解析失败，antnest-web 因 need net 起不来。
  mkdir -p /etc/network
  cat > /etc/network/interfaces <<'EOF'
auto lo
iface lo inet loopback

auto eth0
iface eth0 inet dhcp
EOF
  rc-update add networking boot 2>/dev/null || true
"
umount /mnt/new/dev /mnt/new/sys /mnt/new/proc 2>/dev/null || true
umount /mnt/new 2>/dev/null || true

# python3 必须存在，否则服务起不来
if [ ! -x /mnt/new/usr/bin/python3 ]; then
  echo "[firstboot] ❌ 关键依赖 python3 未装上（chroot 内 apk 失败）。"
  echo "   请确认 VM 联网后重跑本脚本；不要移除 ISO，脚本会补装。"
  exit 1
fi

echo ""
echo "==================================================================="
echo "  ✅ antnest-web 安装完成！"
echo "  本脚本将在 5 秒后自动关机（这是正常收尾，不是崩溃）。"
echo "  下一步："
echo "    1) VMware『虚拟机设置』里移除两张 ISO（或断开连接）"
echo "    2) 重新开机 → 从磁盘启动，自动拉起 antnest-web 服务"
echo "    3) 浏览器访问 http://<VM的IP>:8080/"
echo "    4) 首次登录密码见 VM 内 /var/log/antnest-web.log"
echo "==================================================================="
sleep 5
poweroff
