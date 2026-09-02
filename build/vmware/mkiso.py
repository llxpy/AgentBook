# -*- coding: utf-8 -*-
"""mkiso.py · 纯 Python 生成 ISO9660 Level 1 光盘镜像（零三方依赖）。

仅放扁平文件（8.3 文件名，无 Rock Ridge），足够给 Alpine live 当配置光盘用：
挂载后能看到 ANSWER.TXT / FIRSTBOO.SH / AGENTBOOK.TGZ。

用法：
    python3 mkiso.py <输出.iso> <源目录>
源目录里的文件会被打包（子目录不递归，保持扁平）。
"""
from __future__ import annotations

import os
import sys

BLOCK = 2048


def iso_name(name: str) -> str:
    """把文件名转成 ISO9660 8.3（大写，11 字节，点隐式在中部）。"""
    base, dot, ext = name.upper().partition(".")
    base = base[:8].ljust(8)
    ext = ext[:3].ljust(3)
    return base + ext


def dir_record(extent: int, size: int, is_dir: bool, ident: bytes) -> bytes:
    """构造一条目录记录（Directory Record）。ident: 文件用 11 字节 8.3；
    '.' 用 b'\\x00'；'..' 用 b'\\x01'。"""
    rec = bytearray()
    rec.append(0)                      # 0: 记录长度（稍后填）
    rec.append(0)                      # 1: 扩展属性长度
    rec += extent.to_bytes(4, "little") + extent.to_bytes(4, "big")   # 2-9: extent
    rec += size.to_bytes(4, "little") + size.to_bytes(4, "big")       # 10-17: 数据长度
    rec += b"\x00" * 7                 # 18-24: 录制时间（置零）
    rec.append(0x02 if is_dir else 0x00)  # 25: 标志位
    rec.append(0)                      # 26: 文件单元大小
    rec.append(0)                      # 27: 交错间隔
    rec += (1).to_bytes(2, "little") + (1).to_bytes(2, "big")          # 28-31: 卷序
    rec.append(len(ident))             # 32: 标识符长度
    rec += ident                       # 33..: 标识符
    if len(rec) % 2 == 1:
        rec.append(0)                  # 补齐偶数
    rec[0] = len(rec)
    return bytes(rec)


def build_iso(files: dict, out_path: str):
    """files: {真实文件名: bytes 内容}。生成 ISO 并写出。"""
    # 计算布局（扇区）
    PATH_TABLE_SECTOR = 18
    ROOT_SECTOR = 19
    sector = 20
    layout = {}
    for name, data in files.items():
        size = len(data)
        nsec = (size + BLOCK - 1) // BLOCK
        layout[name] = {"data": data, "size": size, "extent": sector, "nsec": max(nsec, 1)}
        sector += max(nsec, 1)
    total_sectors = sector

    # 根目录内容：'.' '..' 与每个文件各一条记录
    root_records = bytearray()
    root_records += dir_record(ROOT_SECTOR, 0, True, b"\x00")   # '.'
    root_records += dir_record(ROOT_SECTOR, 0, True, b"\x01")   # '..'
    for name in files:
        rec = dir_record(layout[name]["extent"], layout[name]["size"], False,
                          iso_name(name).encode("ascii"))
        root_records += rec
    root_dir_size = len(root_records)
    # 根目录占满一个扇区
    root_dir_bytes = root_records + b"\x00" * (BLOCK - len(root_records))

    # 路径表（Type L，小端；仅根一项）
    path_entry = bytearray()
    path_entry.append(1)                       # 目录标识符长度（根=1）
    path_entry.append(0)                       # 扩展属性长度
    path_entry += ROOT_SECTOR.to_bytes(4, "little")   # extent（LE）
    path_entry += (1).to_bytes(2, "little")           # 父目录号（根=1）
    path_entry += b"\x00"                            # 根名（1 字节 0x00）
    if len(path_entry) % 2 == 1:
        path_entry.append(0)
    path_table = bytes(path_entry) + b"\x00" * (BLOCK - len(path_entry))
    path_table_size = len(path_entry)

    # ---- PVD（主卷描述符）----
    pvd = bytearray(BLOCK)
    pvd[0] = 0x01
    pvd[1:6] = b"CD001"
    pvd[6] = 0x01
    pvd[7] = 0x00
    pvd[8:40] = b"AGENTBOOK" + b" " * 24      # 系统标识符
    pvd[40:72] = b"AGENTBOOK" + b" " * 24     # 卷标识符
    # 72:8 保留
    pvd[80:84] = total_sectors.to_bytes(4, "little")   # 卷空间大小 LE
    pvd[84:88] = total_sectors.to_bytes(4, "big")      # 卷空间大小 BE
    # 88:32 保留
    pvd[120:122] = (1).to_bytes(2, "little")   # 卷集大小 LE
    pvd[122:124] = (1).to_bytes(2, "big")
    pvd[124:126] = (1).to_bytes(2, "little")   # 卷序号 LE
    pvd[126:128] = (1).to_bytes(2, "big")
    pvd[128:130] = BLOCK.to_bytes(2, "little")  # 逻辑块大小 LE
    pvd[130:132] = BLOCK.to_bytes(2, "big")
    pvd[132:136] = path_table_size.to_bytes(4, "little")   # 路径表大小 LE
    pvd[136:140] = path_table_size.to_bytes(4, "big")
    pvd[140:144] = PATH_TABLE_SECTOR.to_bytes(4, "little")  # L 路径表位置 LE
    pvd[148:152] = PATH_TABLE_SECTOR.to_bytes(4, "big")     # M 路径表位置 BE
    # 156:34 根目录记录
    root_rec = dir_record(ROOT_SECTOR, root_dir_size, True, b"\x00")
    pvd[156:156 + len(root_rec)] = root_rec
    # 190 起：各字符串字段（留空格）
    pvd[190:318] = b" " * 128   # 卷集标识
    pvd[318:446] = b" " * 128   # 出版者
    pvd[446:574] = b" " * 128   # 数据准备者
    pvd[574:611] = b" " * 37    # 应用
    pvd[611:648] = b" " * 37    # 版权
    pvd[648:685] = b" " * 37    # 摘要
    pvd[685:722] = b" " * 37    # 文献
    # 其余保持零
    pvd[822:839] = b" " * 17    # 卷创建时间占位（可选）

    # ---- 卷描述符集终结符 ----
    term = bytearray(BLOCK)
    term[0] = 0xFF
    term[1:6] = b"CD001"
    term[6] = 0x01

    # ---- 组装整盘 ----
    img = bytearray(total_sectors * BLOCK)
    # 0..15 系统区留零
    img[16 * BLOCK: 17 * BLOCK] = pvd
    img[17 * BLOCK: 18 * BLOCK] = term
    img[PATH_TABLE_SECTOR * BLOCK: (PATH_TABLE_SECTOR + 1) * BLOCK] = path_table
    img[ROOT_SECTOR * BLOCK: (ROOT_SECTOR + 1) * BLOCK] = root_dir_bytes
    for name, info in layout.items():
        start = info["extent"] * BLOCK
        chunk = info["data"] + b"\x00" * (info["nsec"] * BLOCK - len(info["data"]))
        img[start: start + len(chunk)] = chunk

    with open(out_path, "wb") as f:
        f.write(img)
    return total_sectors


def main():
    if len(sys.argv) != 3:
        print("用法: python3 mkiso.py <输出.iso> <源目录>")
        sys.exit(1)
    out_path, src = sys.argv[1], sys.argv[2]
    if not os.path.isdir(src):
        print(f"源目录不存在: {src}")
        sys.exit(1)
    files = {}
    for fn in sorted(os.listdir(src)):
        p = os.path.join(src, fn)
        if os.path.isfile(p):
            with open(p, "rb") as f:
                files[fn] = f.read()
    if not files:
        print("源目录为空")
        sys.exit(1)
    build_iso(files, out_path)
    print(f"已生成 {out_path}（{len(files)} 个文件，{os.path.getsize(out_path)} 字节）")


if __name__ == "__main__":
    main()
