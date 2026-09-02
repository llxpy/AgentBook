# -*- coding: utf-8 -*-
"""AgentBook · 启动器（PHtmlWin 通用面板）。

- AgentPanel 用 ui.* DSL 描述界面、@route 绑定事件、app.update 实时刷新，
  与 AntNest 面板同款写法。
- 服务由 PHtmlWin 托管：浏览器模式绑 0.0.0.0:8080，供主机（或同网）浏览器访问。
  （Alpine VM 内无 pywebview/无图形浏览器，自动走浏览器回退模式。）

用法：
  python3 server.py                        # 起服务（0.0.0.0:8080）
  python3 server.py --set-password 你的密码  # 控制台改登录密码（重启生效）
"""
from __future__ import annotations

import os
import sys

import config as config_mod
from panel import AgentPanel


def main():
    # 控制台改密码：python3 server.py --set-password <你的密码>
    if len(sys.argv) > 1 and sys.argv[1] == "--set-password":
        new_pw = sys.argv[2] if len(sys.argv) > 2 else ""
        try:
            config_mod.set_password(new_pw)
            print(f"✅ 登录密码已更新为：{new_pw}")
            print("   重启服务后生效：rc-service agentbook restart")
        except Exception as e:  # noqa
            print(f"❌ 设置失败：{e}")
            sys.exit(1)
        sys.exit(0)

    pw = config_mod.get_password()
    panel = AgentPanel()
    app = panel.build_app()

    host = os.environ.get("AN_WEB_HOST", "0.0.0.0")
    port = int(os.environ.get("AN_WEB_PORT", "8080"))
    app._host = host
    app._port = port

    print("=" * 64, flush=True)
    print("  AgentBook 面板 · 在暗面构建", flush=True)
    print(f"  监听: http://{host}:{port}/", flush=True)
    print(f"  首次登录密码: {pw}", flush=True)
    print("  配置 LLM API 后即可用自然语言控制这台 Linux。", flush=True)
    print("  想自定义密码？控制台执行：", flush=True)
    print("    python3 /opt/agentbook/server.py --set-password 你的密码", flush=True)
    print("=" * 64, flush=True)
    app.run()


if __name__ == "__main__":
    main()
