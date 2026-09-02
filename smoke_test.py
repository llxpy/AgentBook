# -*- coding: utf-8 -*-
"""antnest-web 端到端冒烟测试。

分两层：
  A. HTTP 层：启动服务 → 登录/会话/SSE 流程（mock 模式，不依赖外部 LLM）。
  B. 工具层（直连 dispatch，真路径）：run_cmd / 护栏 deny / repack 容器感知。

用法：
    export PY=python3
    $PY smoke_test.py
"""
import os
import sys
import json
import time
import socket
import subprocess

PY = os.environ.get("PY", sys.executable)
HERE = os.path.dirname(os.path.abspath(__file__))

import socket as _sock


def free_port():
    s = _sock.socket()
    s.bind(("0.0.0.0", 0))
    p = s.getsockname()[1]
    s.close()
    return p


# 运行时挑空闲端口，避免与残留的旧 server.py 进程（占用固定端口）冲突，
# 旧进程若用 127.0.0.1 会自动开浏览器建 SSE，会抢消费 _updates 导致偶发拿不到更新。
PORT = free_port()
os.environ["AN_WEB_PORT"] = str(PORT)
os.environ["AN_WEB_HOST"] = "0.0.0.0"
os.environ["AN_AGENT_PASSWORD"] = "smoke-test-pass"

passed = []


def ok(name):
    passed.append(name)
    print(f"  [OK] {name}")


def fail(name, err):
    print(f"  [FAIL] {name}: {err}")
    sys.exit(1)


def wait_port(host, port, timeout=15):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def http(method, path, token=None, body=None, cookie=None):
    import urllib.request
    import urllib.error
    url = f"http://127.0.0.1:{PORT}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if cookie:
        req.add_header("Cookie", f"an_token={cookie}")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.headers.get("Set-Cookie", ""), r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Set-Cookie", ""), e.read().decode()


def route(name, data=None, cookie=None):
    """打 PHtmlWin 命名路由，返回 (status, set_cookie, updates_list)。"""
    st, sc, body = http("POST", "/api/route", cookie=cookie,
                        body={"route": name, "data": data or {}})
    try:
        upd = json.loads(body).get("updates", [])
    except Exception:
        upd = []
    return st, sc, upd


def read_sse(raw):
    events = []
    for block in raw.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        ev, data = None, None
        for line in block.splitlines():
            if line.startswith("event:"):
                ev = line[len("event:"):].strip()
            elif line.startswith("data:"):
                chunk = line[len("data:"):].strip()
                data = chunk if data is None else data + chunk
        try:
            events.append((ev, json.loads(data)))
        except Exception:
            events.append((ev, data))  # 保留原始串
    return events


# ------------------------------------------------------------- A. HTTP 层
def test_http():
    print("\n=== A. HTTP 层（PHtmlWin 路由面）===")
    proc = subprocess.Popen([PY, os.path.join(HERE, "server.py")], cwd=HERE, env={**os.environ})
    try:
        if not wait_port("127.0.0.1", PORT, 15):
            fail("server-up", "服务未监听端口")
        ok(f"server up on {PORT}")

        # 页面渲染（新面板布局）
        st, _, html = http("GET", "/")
        st == 200 or fail("page", f"GET / 应 200，得到 {st}")
        ("id=\"dashboard-body\"" in html) or fail("page-dash", "页面缺 #dashboard-body")
        ("系统概览" in html) or fail("page-overview", "页面缺『系统概览』")
        ("login-overlay" in html) or fail("page-login", "页面缺登录遮罩")
        ok("GET / 渲染新面板（含 #dashboard-body / 系统概览 / 登录遮罩）")

        # 未授权访问受保护路由 → 401
        st, _, _ = route("status_refresh")
        st == 401 or fail("status-noauth", f"期望 401，得到 {st}")
        ok("未授权 status_refresh = 401")

        # 错误密码（login 是公开路由，返回 200 但无 Set-Cookie）
        st, sc, _ = route("login", {"value": "wrong"})
        st == 200 or fail("login-wrong", f"错误密码应 200，得到 {st}")
        ("an_token=" not in sc) or fail("login-wrong-cookie", "错误密码不应发 cookie")
        ok("错误密码登录被拒（无 cookie）")

        # 正确密码 → 200 + Set-Cookie an_token
        st, sc, upd = route("login", {"value": "smoke-test-pass"})
        st == 200 or fail("login-ok", f"登录应 200，得到 {st}")
        ("an_token=" in sc) or fail("login-cookie", "未返回 Set-Cookie")
        import re
        m = re.search(r"an_token=([^;]+)", sc)
        tok = m.group(1) if m else ""
        tok or fail("login-token", "无 token")
        ok("登录成功拿到 token")

        # 授权后仪表盘刷新 → 响应 updates 含 #dashboard-body 且为新仪表盘标记
        st, _, upd = route("status_refresh", cookie=tok)
        st == 200 or fail("dash-auth", f"status_refresh 应 200，得到 {st}")
        dash = next((u for u in upd if "#dashboard-body" in u), "")
        dash or fail("dash-sel", "status_refresh 未更新 #dashboard-body")
        ("stat-grid" in dash) or fail("dash-grid", "仪表盘缺 stat-grid")
        ("系统信息" in dash) or fail("dash-info", "仪表盘缺『系统信息』")
        ("监听端口" in dash) or fail("dash-ports", "仪表盘缺『监听端口』")
        ok("授权 status_refresh → 仪表盘刷新（stat-grid / 系统信息 / 监听端口）")

        # 授权后配置抽屉打开 → updates 含 #cfg-base
        st, _, upd = route("cfg_open", cookie=tok)
        st == 200 or fail("cfg-open", f"cfg_open 应 200，得到 {st}")
        any("#cfg-base" in u for u in upd) or fail("cfg-base", "cfg_open 未更新 #cfg-base")
        ok("授权 cfg_open → 配置抽屉就绪")

        # mock 对话（无 Key 走演示闭环）→ updates 含 #chat-msgs
        st, _, upd = route("chat_send", {"value": "查看系统状态"}, cookie=tok)
        st == 200 or fail("chat", f"chat_send 应 200，得到 {st}")
        any("#chat-msgs" in u for u in upd) or fail("chat-msgs", "chat_send 未更新 #chat-msgs")
        ok("mock 对话 chat_send → #chat-msgs 更新")

        # 登出 → 路由 data.value 带 cookie 串（pop 会话）+ Set-Cookie 清 token；
        # 旧 token 再访问受保护路由 → 401
        st, sc, _ = route("logout", data={"value": f"an_token={tok}"}, cookie=tok)
        st == 200 or fail("logout", f"logout 应 200，得到 {st}")
        ("an_token=; " in sc or "an_token=;" in sc) or fail("logout-clear", "登出未清 cookie")
        st, _, _ = route("status_refresh", cookie=tok)
        st == 401 or fail("logout-invalid", f"登出后应 401，得到 {st}")
        ok("登出后 token 失效 = 401")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


# ------------------------------------------------------------- B. 工具层
def test_tools():
    print("\n=== B. 工具层（直连 dispatch）===")
    sys.path.insert(0, HERE)
    import tools
    import guard

    # run_cmd 安全命令
    r = tools.run_cmd("echo smoke-ok-123")
    r.get("status") == "ok" and "smoke-ok-123" in (r.get("stdout") or "") \
        or fail("run_cmd-echo", r)
    ok("run_cmd('echo smoke-ok-123') -> ok")

    # 护栏：灾难性命令 deny
    al, lv, _ = guard.is_allowed("rm -rf /", confirm=False)
    lv == "deny" or fail("guard-deny", f"应为 deny，得到 {lv}")
    r = tools.run_cmd("rm -rf /")
    r.get("status") == "denied" or fail("run_cmd-deny", r)
    ok("run_cmd('rm -rf /') -> denied（灾难性命令拒绝）")

    # 护栏：高危需确认（无 confirm）——用仅命中 PRIV 模式、跨平台可执行的命令
    al, lv, _ = guard.is_allowed("sudo id", confirm=False)
    lv == "privileged" or fail("guard-priv", f"应为 privileged，得到 {lv}")
    ok("guard.is_allowed('sudo id') -> privileged")

    r = tools.run_cmd("sudo id")
    r.get("status") == "needs_confirm" or fail("run_cmd-needconfirm", r)
    ok("run_cmd('sudo id') -> needs_confirm（无 confirm）")

    # 护栏：confirm=True 放行 privileged（用一个在 Git Bash 下真能执行的命令）
    import tempfile
    tf = tempfile.NamedTemporaryFile(delete=False, suffix=".sh")
    tf.write(b"#!/bin/sh\necho hi\n")
    tf.close()
    r = tools.run_cmd(f"chmod +x {tf.name}", confirm=True)
    r.get("status") == "ok" or fail("run_cmd-confirm", r)
    ok("run_cmd('chmod +x <tmp>', confirm=True) -> ok（guard 放行后执行）")
    os.remove(tf.name)

    # repack 容器感知：源不存在
    r = tools.repack_deb("/nope/not-exist.deb", "/nope/out.deb")
    r.get("status") == "error" and "源包不存在" in (r.get("error") or "") \
        or fail("repack-deb-missing", r)
    ok("repack_deb(源不存在) -> error（源包不存在）")

    # repack 容器感知：无工具链 + 无容器运行时 → 明确指引
    r = tools.repack_deb("/nope/x.deb", "/nope/o.deb")  # 文件不存在但先测工具链分支需跳过
    # 用一个确实存在的占位文件走工具链探测
    import tempfile
    tmp = tempfile.NamedTemporaryFile(suffix=".deb", delete=False)
    tmp.write(b"not-a-real-deb")
    tmp.close()
    r = tools.repack_deb(tmp.name, "/nope/o.deb")
    # 本机 Windows 无 dpkg-deb 且无 podman/docker → 进入指引分支
    (r.get("status") == "error" and ("容器运行时" in (r.get("error") or "")
                                     or "dpkg-deb" in (r.get("error") or "")
                                     or "源包" in (r.get("error") or ""))) \
        or fail("repack-deb-noguide", r)
    ok(f"repack_deb(无工具链) -> 明确指引: {r.get('error','')[:40]}...")
    os.remove(tmp.name)

    # inspect 源不存在
    r = tools.pkg_inspect("/nope/x.deb")
    r.get("status") == "error" or fail("inspect-missing", r)
    ok("pkg_inspect(源不存在) -> error")

    # schemas 数量
    len(tools.TOOL_SCHEMAS) == 9 or fail("schemas-count", len(tools.TOOL_SCHEMAS))
    ok("TOOL_SCHEMAS 数量 = 9")

    # dispatch 未知工具
    r = tools.dispatch("no.such.tool", {})
    r.get("status") == "error" or fail("dispatch-unknown", r)
    ok("dispatch(未知工具) -> error")


if __name__ == "__main__":
    print("PY =", PY)
    test_http()
    test_tools()
    print(f"\nALL_SMOKE_OK （共 {len(passed)} 项通过）")
