# -*- coding: utf-8 -*-
"""AgentBook · 命令护栏（自然语言控制 Linux 的安全边界）。

原则（对齐《deb_rpm 安装包修改工具横评》第 9 章）：
- 绝不允许"裸 Shell 自由拼接"执行未知命令：命令由 Agent 显式构造为完整字符串，
  护栏先分类再决定是否放行。
- 灾难性模式（删根、格式化、写设备、关机等）直接拒绝。
- 提权 / 破坏性模式（sudo、rm -rf、mkfs、iptables、改系统服务等）需要用户显式
  confirm=true 才执行，否则返回 needs_confirm 让前端弹确认按钮。
- 所有执行留结构化审计（见 tools 层日志）。
"""
from __future__ import annotations

import re

# 命中即拒绝（灾难性 / 不可逆）
DENY_PATTERNS = [
    (r"\brm\s+-rf\s+/|rm\s+-rf\s+--no-preserve-root", "删除根文件系统"),
    (r":\(\)\s*\{.*\}\s*;:", "fork 炸弹"),
    (r"\bmkfs\.(ext\d|xfs|vfat|btrfs)", "格式化文件系统"),
    (r"\bdd\s+if=.*of=/dev/\S+", "向设备直写（dd）"),
    (r">\s*/dev/sd[a-z]", "向块设备重定向"),
    (r"\bchmod\s+-R\s+0\d{3}\s", "递归清零权限"),
    (r"\bshutdown\b|\breboot\b|\bhalt\b|\bpoweroff\b|\binit\s+0\b", "关机/重启"),
    (r"\bmv\s+/\s", "移动根目录"),
    (r"\b(chown|chmod)\s+-R\s+.*\s+/(bin|etc|usr|lib|sbin)\b", "递归改系统核心目录属主/权限"),
]

# 需要授权（高危但合法）的模式
PRIV_PATTERNS = [
    (r"\bsudo\b|\bsu\b", "提权"),
    (r"\brm\s+-rf?\b", "递归删除"),
    (r"\bmkfs\b", "格式化"),
    (r"\buserdel\b|\bgroupdel\b|\buseradd\b|\busermod\b", "账号管理"),
    (r"\bpasswd\b|\bvisudo\b", "凭据/ sudoers"),
    (r"\bmount\b|\bumount\b", "挂载"),
    (r"\biptables\b|\bnft\b|\bnftables\b", "防火墙"),
    (r"\bchown\b|\bchmod\b", "改属主/权限"),
    (r"\bsystemctl\b|\brc-service\b|\brc-update\b|\bservice\b", "系统服务"),
    (r"\bapk\s+(del|add)\b", "包管理变更"),
    (r"\bapt-(get|key)\b|\bdpkg\b|\brpm\b|\bdnf\b|\byum\b", "包管理器"),
    (r">\s*/etc/|>>\s*/etc/", "写系统配置"),
]


def classify(cmd: str):
    """返回 (level, reason)。

    level: 'ok' | 'privileged' | 'deny'
    """
    cmd = (cmd or "").strip()
    for pat, desc in DENY_PATTERNS:
        if re.search(pat, cmd):
            return "deny", f"命令命中禁用模式（{desc}），已拒绝执行"
    for pat, desc in PRIV_PATTERNS:
        if re.search(pat, cmd):
            return "privileged", desc
    return "ok", None


def is_allowed(cmd: str, confirm: bool):
    """返回 (allowed, level, reason)。confirm=True 可放行 privileged。"""
    level, reason = classify(cmd)
    if level == "deny":
        return False, level, reason
    if level == "privileged" and not confirm:
        return False, level, reason
    return True, level, reason
