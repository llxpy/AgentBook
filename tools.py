# -*- coding: utf-8 -*-
"""AgentBook · 工具层（自然语言控制 Linux 的能力本体）。

对齐《deb_rpm 安装包修改工具横评》第 7 章白名单动作 + 风险等级：
  L1  package.inspect / system.info         只读
  L2  system.run_cmd / config.apply         受护栏 + 需授权
  L3  pkg.repack_deb / pkg.repack_rpm / pkg.install_test / pkg.rollback  写 / 改包
  L4  package.sign（需要签名密钥，本版留接口，默认拒绝）

所有动作返回结构化 dict，且统一写审计日志（state/audit.log）。
"""
from __future__ import annotations

import os
import re
import json
import time
import shutil
import tempfile
import datetime
import subprocess

from guard import is_allowed

STATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state")
AUDIT_LOG = os.path.join(STATE_DIR, "audit.log")
MAX_OUTPUT = 200_000  # 单命令输出上限（字节）

# 容器感知：Alpine 等宿主机没有 dpkg-dev/rpmrebuild 时，
# 在 disposable 的 Debian/RHEL 容器里执行改包（对齐研究「同版本 disposable 环境」）。
CONTAINER_IMG_DEB = os.environ.get("AN_IMG_DEB", "debian:bookworm")
CONTAINER_IMG_RPM = os.environ.get("AN_IMG_RPM", "rockylinux:9")


def _container_runtime():
    """返回可用的容器运行时 podman/docker，没有则返回 None。"""
    for rt in ("podman", "docker"):
        if shutil.which(rt):
            return rt
    return None


def _audit(tool: str, args: dict, result: dict):
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        line = {
            "t": datetime.datetime.now().isoformat(timespec="seconds"),
            "tool": tool,
            "args": {k: (str(v)[:200] if not isinstance(v, (int, float, bool)) else v)
                     for k, v in (args or {}).items()},
            "status": result.get("status"),
        }
        with open(AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _run(cmd: str, timeout: int = 120, shell: bool = True, cwd=None):
    """执行命令并返回结构化结果。shell=True 由调用方在已通过护栏的前提下使用。"""
    t0 = time.time()
    try:
        proc = subprocess.run(
            cmd, shell=shell, cwd=cwd,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=timeout, text=True, errors="replace",
        )
        out = proc.stdout or ""
        err = proc.stderr or ""
        if len(out) > MAX_OUTPUT:
            out = out[:MAX_OUTPUT] + "\n...[输出截断]"
        if len(err) > MAX_OUTPUT:
            err = err[:MAX_OUTPUT] + "\n...[输出截断]"
        return {
            "status": "ok" if proc.returncode == 0 else "error",
            "rc": proc.returncode,
            "stdout": out,
            "stderr": err,
            "duration": round(time.time() - t0, 2),
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "rc": -1, "stdout": "", "stderr": f"命令超时（>{timeout}s）", "duration": timeout}
    except Exception as e:  # noqa
        return {"status": "error", "rc": -1, "stdout": "", "stderr": str(e), "duration": round(time.time() - t0, 2)}


# ---------------------------------------------------------------- system.run_cmd
def run_cmd(cmd: str, confirm: bool = False, timeout: int = 120):
    allowed, level, reason = is_allowed(cmd, confirm)
    if not allowed:
        res = {"status": "denied" if level == "deny" else "needs_confirm",
               "level": level, "reason": reason, "command": cmd}
        _audit("system_run_cmd", {"cmd": cmd, "confirm": confirm}, res)
        return res
    res = _run(cmd, timeout=timeout)
    res["level"] = level
    _audit("system_run_cmd", {"cmd": cmd, "confirm": confirm}, res)
    return res


# ---------------------------------------------------------------- system.status
def _read_proc(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return ""


def _listening_ports() -> list:
    ports = []
    try:
        for proto in ("tcp", "tcp6"):
            raw = _read_proc(f"/proc/net/{proto}")
            for line in raw.splitlines()[1:]:
                f = line.split()
                if len(f) < 4:
                    continue
                local = f[1]
                st = f[3]
                if st != "0A":  # LISTEN
                    continue
                # local hex: 0100007F:0050
                ip_hex, port_hex = local.split(":")
                port = int(port_hex, 16)
                ports.append({"proto": proto, "port": port})
    except Exception:
        pass
    # 去重
    seen = {}
    for p in ports:
        seen[p["port"]] = p
    return sorted(seen.values(), key=lambda x: x["port"])


def _services() -> list:
    out = []
    try:
        r = _run("rc-status --servicelist 2>/dev/null", shell=True, timeout=10)
        if r["status"] == "ok" and r["stdout"].strip():
            for ln in r["stdout"].splitlines():
                m = re.match(r"\s*(\S+)\s*\[(.*?)\]\s*(.*)", ln)
                if m:
                    out.append({"name": m.group(1), "state": (m.group(3) or "").strip() or m.group(2).strip()})
            if out:
                return out
    except Exception:
        pass
    try:
        r = _run("rc-update show 2>/dev/null", shell=True, timeout=10)
        if r["status"] == "ok":
            for ln in r["stdout"].splitlines():
                parts = ln.split()
                if parts and ("|" in ln or len(parts) >= 1):
                    name = parts[0]
                    out.append({"name": name, "state": "registered"})
    except Exception:
        pass
    return out


def status() -> dict:
    info = {"status": "ok"}
    try:
        un = os.uname()
        info["kernel"] = f"{un.sysname} {un.release} {un.machine}"
        info["nodename"] = un.nodename
    except Exception:
        pass
    up = _read_proc("/proc/uptime")
    if up:
        try:
            info["uptime_sec"] = int(float(up.split()[0]))
        except Exception:
            pass
    la = _read_proc("/proc/loadavg")
    if la:
        info["loadavg"] = la.split()[:3]
    mem = _read_proc("/proc/meminfo")
    if mem:
        d = {}
        for ln in mem.splitlines():
            k, _, v = ln.partition(":")
            d[k.strip()] = v.strip().split()[0] if v.strip() else ""
        try:
            info["mem_total_kb"] = int(d.get("MemTotal", "0").split()[0]) if d.get("MemTotal") else 0
            info["mem_avail_kb"] = int(d.get("MemAvailable", "0").split()[0]) if d.get("MemAvailable") else 0
        except Exception:
            pass
    try:
        du = shutil.disk_usage("/")
        info["disk_total_gb"] = round(du.total / 1e9, 2)
        info["disk_free_gb"] = round(du.free / 1e9, 2)
    except Exception:
        pass
    info["listening_ports"] = _listening_ports()
    info["services"] = _services()
    info["tools"] = {t: bool(shutil.which(t)) for t in
                     ("dpkg-deb", "ar", "tar", "rpm", "rpmrebuild", "rpmbuild",
                      "cpio", "apt-get", "dnf", "lintian", "python3")}
    info["agent_pid"] = os.getpid()
    _audit("system_status", {}, {"status": "ok"})
    return info


# ---------------------------------------------------------------- files
def file_read(path: str, max_bytes: int = 200_000):
    p = os.path.abspath(path)
    if not os.path.isfile(p):
        res = {"status": "error", "error": f"文件不存在: {p}"}
        _audit("files_read", {"path": p}, res)
        return res
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            data = f.read(max_bytes)
        res = {"status": "ok", "path": p, "content": data}
    except Exception as e:
        res = {"status": "error", "error": str(e)}
    _audit("files_read", {"path": p}, res)
    return res


def file_write(path: str, content: str, mode: str = "w"):
    p = os.path.abspath(path)
    # 反写系统关键路径需授权
    if re.search(r"^/(etc|boot|usr/lib|usr/bin|sbin|bin)/", p):
        res = {"status": "needs_confirm", "reason": "写入系统关键路径需确认", "path": p}
        _audit("files_write", {"path": p}, res)
        return res
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, mode, encoding="utf-8") as f:
            f.write(content)
        res = {"status": "ok", "path": p, "bytes": len(content.encode("utf-8"))}
    except Exception as e:
        res = {"status": "error", "error": str(e)}
    _audit("files_write", {"path": p}, res)
    return res


# ---------------------------------------------------------------- pkg.inspect (L1)
def pkg_inspect(src: str) -> dict:
    p = os.path.abspath(src)
    if not os.path.isfile(p):
        return {"status": "error", "error": f"包不存在: {p}"}
    if p.endswith(".deb"):
        if not shutil.which("dpkg-deb"):
            return {"status": "error", "error": "未安装 dpkg-deb（Debian 系工具链）"}
        meta = _run(f"dpkg-deb -I {p!r}", timeout=30)
        files = _run(f"dpkg-deb -c {p!r}", timeout=30)
        res = {"status": "ok", "type": "deb",
               "control": meta.get("stdout", ""), "files": files.get("stdout", ""),
               "meta_rc": meta.get("rc"), "files_rc": files.get("rc")}
    elif p.endswith((".rpm", ".srpm")):
        if not shutil.which("rpm"):
            return {"status": "error", "error": "未安装 rpm（RHEL 系工具链）"}
        meta = _run(f"rpm -qpi {p!r}", timeout=30)
        files = _run(f"rpm -qpl {p!r}", timeout=30)
        scripts = _run(f"rpm -qps {p!r}", timeout=30)
        res = {"status": "ok", "type": "rpm",
               "info": meta.get("stdout", ""), "files": files.get("stdout", ""),
               "scripts": scripts.get("stdout", "")}
    else:
        res = {"status": "error", "error": "未知包类型（仅支持 .deb / .rpm）"}
    _audit("pkg_inspect", {"src": p}, res)
    return res


# ---------------------------------------------------------------- pkg.repack_deb (L3)
def _repack_deb_host(src: str, output: str, patch_dir: str, control_patch: str) -> dict:
    work = tempfile.mkdtemp(prefix="antnest-deb-")
    try:
        sha = _run(f"sha256sum {src!r}", timeout=30)
        orig_sha = sha.get("stdout", "").split()[0] if sha.get("stdout") else ""
        ext = _run(f"dpkg-deb -R {src!r} {work!r}/extract", timeout=60)
        if ext["status"] != "ok":
            return {"status": "error", "error": "解包失败", "stderr": ext.get("stderr")}
        if patch_dir and os.path.isdir(patch_dir):
            _run(f"cp -a {os.path.abspath(patch_dir)!r}/. {work!r}/extract/", timeout=30)
        if control_patch and os.path.isfile(control_patch):
            _run(f"patch -f {work!r}/extract/DEBIAN/control < {os.path.abspath(control_patch)!r}", timeout=30)
        out_dir = os.path.dirname(output) or "."
        os.makedirs(out_dir, exist_ok=True)
        bld = _run(f"dpkg-deb --root-owner-group -b {work!r}/extract {output!r}", timeout=90)
        if bld["status"] != "ok":
            return {"status": "error", "error": "重打包失败", "stderr": bld.get("stderr")}
        return {"status": "ok", "output": output, "original_sha256": orig_sha,
                "env": "host",
                "note": "md5sums 由 dpkg-deb 重建；原 GPG/签名已失效，需重新签名后才视为可信包"}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _repack_deb_container(rt: str, src: str, output: str, patch_dir: str,
                          control_patch: str) -> dict:
    stage = tempfile.mkdtemp(prefix="antnest-deb-")
    try:
        shutil.copy(src, os.path.join(stage, "src.deb"))
        if patch_dir and os.path.isdir(patch_dir):
            _run(f"cp -a {os.path.abspath(patch_dir)!r}/. {stage!r}/patch/", timeout=30)
        if control_patch and os.path.isfile(control_patch):
            shutil.copy(os.path.abspath(control_patch), os.path.join(stage, "control.patch"))
        script = (
            "set -e; apt-get update -qq && apt-get install -y -qq dpkg-dev >/dev/null 2>&1; "
            "dpkg-deb -R /work/src.deb /work/extract; "
            "[ -d /work/patch ] && cp -a /work/patch/. /work/extract/; "
            "[ -f /work/control.patch ] && patch -f /work/extract/DEBIAN/control < /work/control.patch; "
            "dpkg-deb --root-owner-group -b /work/extract /work/out.deb"
        )
        cmd = f"{rt} run --rm -v {stage!r}:/work -w /work {CONTAINER_IMG_DEB} bash -lc {script!r}"
        r = _run(cmd, timeout=300)
        if r["status"] != "ok":
            return {"status": "error", "error": "容器内改包失败", "stderr": r.get("stderr")}
        out_deb = os.path.join(stage, "out.deb")
        if not os.path.isfile(out_deb):
            return {"status": "error", "error": "容器内未产出 out.deb", "stderr": r.get("stderr")}
        os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
        shutil.copy(out_deb, output)
        return {"status": "ok", "output": output, "env": f"container({CONTAINER_IMG_DEB})",
                "note": "在 disposable Debian 容器内改包；原签名已失效，需重新签名"}
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def repack_deb(src: str, output: str, patch_dir: str = "", control_patch: str = "",
               conflict_policy: str = "fail") -> dict:
    src = os.path.abspath(src)
    output = os.path.abspath(output)
    if not os.path.isfile(src):
        return {"status": "error", "error": f"源包不存在: {src}"}
    if shutil.which("dpkg-deb"):
        res = _repack_deb_host(src, output, patch_dir, control_patch)
    else:
        rt = _container_runtime()
        if rt:
            res = _repack_deb_container(rt, src, output, patch_dir, control_patch)
        else:
            res = {"status": "error",
                   "error": "宿主机无 dpkg-deb，且无容器运行时(podman/docker)。"
                            "Alpine 上请 `apk add podman` 后让 Agent 在 Debian 容器内改包，"
                            "或把 AgentBook 直接装到 Debian 系 VM。"}
    _audit("pkg_repack_deb", {"src": src, "output": output, "conflict_policy": conflict_policy}, res)
    return res


# ---------------------------------------------------------------- pkg.repack_rpm (L3)
def _repack_rpm_host(src: str, output: str, spec_patch: str) -> dict:
    if shutil.which("rpmrebuild"):
        cmd = f"rpmrebuild -p {src!r} --output {output!r}"
        if spec_patch and os.path.isfile(spec_patch):
            cmd += f" --change-spec-preamble='cat {os.path.abspath(spec_patch)!r}'"
        r = _run(cmd, timeout=120)
        return {"status": "ok" if r["status"] == "ok" else "error",
                "output": output if r["status"] == "ok" else None,
                "stdout": r.get("stdout"), "stderr": r.get("stderr"),
                "env": "host", "note": "rpmrebuild 路径；原 header 签名已失效，需 rpmsign 重签"}
    return {"status": "error",
            "error": "未安装 rpmrebuild；fallback(rpm2cpio+cpio+rpmbuild)需要可信 spec 模板，本版未内置自动生成"}


def _repack_rpm_container(rt: str, src: str, output: str, spec_patch: str) -> dict:
    stage = tempfile.mkdtemp(prefix="antnest-rpm-")
    try:
        shutil.copy(src, os.path.join(stage, "src.rpm"))
        if spec_patch and os.path.isfile(spec_patch):
            shutil.copy(os.path.abspath(spec_patch), os.path.join(stage, "spec.patch"))
        script = (
            "set -e; dnf install -y -q rpmrebuild rpm-build >/dev/null 2>&1 || "
            "microdnf install -y -q rpmrebuild rpm-build >/dev/null 2>&1; "
            "rpmrebuild -p /work/src.rpm --output /work/out.rpm"
        )
        cmd = f"{rt} run --rm -v {stage!r}:/work -w /work {CONTAINER_IMG_RPM} bash -lc {script!r}"
        r = _run(cmd, timeout=300)
        if r["status"] != "ok":
            return {"status": "error", "error": "容器内改包失败", "stderr": r.get("stderr")}
        out_rpm = os.path.join(stage, "out.rpm")
        if not os.path.isfile(out_rpm):
            return {"status": "error", "error": "容器内未产出 out.rpm", "stderr": r.get("stderr")}
        os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
        shutil.copy(out_rpm, output)
        return {"status": "ok", "output": output, "env": f"container({CONTAINER_IMG_RPM})",
                "note": "在 disposable RHEL 容器内改包；原 header 签名已失效，需 rpmsign 重签"}
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def repack_rpm(src: str, output: str, patch_dir: str = "", spec_patch: str = "",
               conflict_policy: str = "fail") -> dict:
    src = os.path.abspath(src)
    output = os.path.abspath(output)
    if not os.path.isfile(src):
        return {"status": "error", "error": f"源包不存在: {src}"}
    if shutil.which("rpmrebuild"):
        res = _repack_rpm_host(src, output, spec_patch)
    else:
        rt = _container_runtime()
        if rt:
            res = _repack_rpm_container(rt, src, output, spec_patch)
        else:
            res = {"status": "error",
                   "error": "宿主机无 rpmrebuild，且无容器运行时(podman/docker)。"
                            "Alpine 上请 `apk add podman` 后让 Agent 在 RHEL 容器内改包，"
                            "或把 AgentBook 直接装到 RHEL 系 VM。"}
    _audit("pkg_repack_rpm", {"src": src, "output": output, "conflict_policy": conflict_policy}, res)
    return res


# ---------------------------------------------------------------- pkg.install_test (L2)
def install_test(src: str) -> dict:
    p = os.path.abspath(src)
    if not os.path.isfile(p):
        return {"status": "error", "error": f"包不存在: {p}"}
    if p.endswith(".deb"):
        if not shutil.which("dpkg-deb"):
            return {"status": "error", "error": "未安装 dpkg-deb"}
        files = _run(f"dpkg-deb -c {p!r}", timeout=30)
        scripts = _run(f"dpkg-deb -e {p!r} /tmp/antnest-ctl 2>/dev/null; ls /tmp/antnest-ctl 2>/dev/null", timeout=30)
        res = {"status": "ok", "type": "deb", "mode": "dry-run(disposable inspect)",
               "files": files.get("stdout", ""), "scripts_dir": scripts.get("stdout", "")}
    elif p.endswith(".rpm"):
        if not shutil.which("rpm"):
            return {"status": "error", "error": "未安装 rpm"}
        files = _run(f"rpm -qpl {p!r}", timeout=30)
        scripts = _run(f"rpm -qps {p!r}", timeout=30)
        res = {"status": "ok", "type": "rpm", "mode": "dry-run(disposable inspect)",
               "files": files.get("stdout", ""), "scripts": scripts.get("stdout", "")}
    else:
        res = {"status": "error", "error": "未知包类型"}
    _audit("pkg_install_test", {"src": p}, res)
    return res


# ---------------------------------------------------------------- pkg.rollback (L3)
def rollback(package: str, version: str = "", confirm: bool = False, manager: str = "auto") -> dict:
    if not confirm:
        return {"status": "needs_confirm",
                "reason": f"回滚 {package} 将改变系统包状态，需确认",
                "package": package, "version": version}
    if shutil.which("apt-get") and (manager == "auto" or manager == "apt"):
        cmd = f"apt-get install -y {package}={version}" if version else f"apt-get install --reinstall -y {package}"
    elif shutil.which("dnf") and (manager == "auto" or manager == "dnf"):
        cmd = f"dnf install -y {package}-{version}" if version else f"dnf reinstall -y {package}"
    elif shutil.which("rpm"):
        cmd = f"rpm -e --nodeps {package}"  # 受控应急
    else:
        return {"status": "error", "error": "无可用包管理器"}
    r = _run(cmd, timeout=180)
    res = {"status": "ok" if r["status"] == "ok" else "error",
           "rc": r.get("rc"), "stdout": r.get("stdout"), "stderr": r.get("stderr")}
    _audit("pkg_rollback", {"package": package, "version": version, "confirm": confirm}, res)
    return res


# ---------------------------------------------------------------- dispatch 注册表
REGISTRY = {
    "system_run_cmd": run_cmd,
    "system_status": status,
    "files_read": file_read,
    "files_write": file_write,
    "pkg_inspect": pkg_inspect,
    "pkg_repack_deb": repack_deb,
    "pkg_repack_rpm": repack_rpm,
    "pkg_install_test": install_test,
    "pkg_rollback": rollback,
}


def dispatch(name: str, args: dict) -> dict:
    fn = REGISTRY.get(name)
    if not fn:
        return {"status": "error", "error": f"未知工具: {name}"}
    try:
        return fn(**(args or {}))
    except TypeError as e:
        return {"status": "error", "error": f"参数错误: {e}"}
    except Exception as e:  # noqa
        return {"status": "error", "error": str(e)}


# 暴露给 Agent 的工具 schema（OpenAI function-calling 格式）
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "system_run_cmd",
            "description": "在受护栏前提下执行一条 Linux 命令并返回 stdout/stderr/rc。灾难性命令会被拒绝；sudo/rm -rf/格式化/改系统服务等高危命令需带 confirm=true 才会执行。",
            "parameters": {
                "type": "object",
                "properties": {
                    "cmd": {"type": "string", "description": "要执行的完整命令"},
                    "confirm": {"type": "boolean", "default": False, "description": "是否确认执行高危命令"},
                    "timeout": {"type": "integer", "default": 120, "description": "超时秒数"},
                },
                "required": ["cmd"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "system_status",
            "description": "返回虚拟机状态：内核、uptime、负载、内存、磁盘、监听端口、运行中的服务、工具链可用性。只读。",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "files_read",
            "description": "读取一个文本文件内容（最多 200KB）。",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string"}, "max_bytes": {"type": "integer", "default": 200000}},
                "required": ["path"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "files_write",
            "description": "写入/覆盖一个文件（系统关键路径需确认）。",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string"}, "content": {"type": "string"},
                "mode": {"type": "string", "default": "w"}}, "required": ["path", "content"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pkg_inspect",
            "description": "查看 .deb/.rpm 包的控制信息、文件清单与维护脚本。只读（L1）。",
            "parameters": {"type": "object", "properties": {"src": {"type": "string"}}, "required": ["src"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pkg_install_test",
            "description": "在 disposable 环境中预检包的落盘文件与脚本，不真正安装（L2）。",
            "parameters": {"type": "object", "properties": {"src": {"type": "string"}}, "required": ["src"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pkg_repack_deb",
            "description": "基于现有 .deb 重打包：解包→可选 patch_dir 覆盖/control_patch 修改→重打包。原签名失效需重签（L3）。",
            "parameters": {"type": "object", "properties": {
                "src": {"type": "string"}, "output": {"type": "string"},
                "patch_dir": {"type": "string", "default": ""},
                "control_patch": {"type": "string", "default": ""},
                "conflict_policy": {"type": "string", "default": "fail"}}, "required": ["src", "output"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pkg_repack_rpm",
            "description": "基于现有 .rpm 重打包（优先 rpmrebuild）。原 header 签名失效需重签（L3）。",
            "parameters": {"type": "object", "properties": {
                "src": {"type": "string"}, "output": {"type": "string"},
                "patch_dir": {"type": "string", "default": ""},
                "spec_patch": {"type": "string", "default": ""},
                "conflict_policy": {"type": "string", "default": "fail"}}, "required": ["src", "output"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pkg_rollback",
            "description": "回滚/重装一个包到指定版本。高危，需 confirm=true（L3）。",
            "parameters": {"type": "object", "properties": {
                "package": {"type": "string"}, "version": {"type": "string", "default": ""},
                "confirm": {"type": "boolean", "default": False},
                "manager": {"type": "string", "default": "auto"}}, "required": ["package"]},
        },
    },
]
