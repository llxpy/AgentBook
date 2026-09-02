# -*- coding: utf-8 -*-
"""AgentBook · AgentPanel（PHtmlWin 通用面板组件）。

和 AntNest 的面板同款写法：ui.* DSL 描述界面 + @app.route 绑定事件 +
app.update(selector, html) 实时刷新。暗面构建设计 token 内联，VM 自包含、零三方依赖。
所有 UI 文案走 i18n（i18n.t），支持中/英切换；含新手引导、服务商预设、示例指令。

可独立运行（server.py 起 0.0.0.0:8080 浏览器模式），也可 mount 进任意 Win：
    panel = AgentPanel()
    app = panel.build_app()
    app.run()
"""
from __future__ import annotations

import html as _html
import json
import secrets
import time

from phtmlwin import ui, Win

import config as config_mod
import agent as agent_mod
import tools as tools_mod
import i18n as i18n_mod

# 当前语言（进程内全局；单用户面板足够，切换后经 location.reload() 生效）
LANG = "zh"


def T(key: str) -> str:
    """按当前 LANG 取文案。"""
    return i18n_mod.t(key, LANG)


# 浏览器模式登录会话：token -> {"created": ts}
SESSIONS = {}


def _esc(s: str) -> str:
    return _html.escape(str(s or ""))


def _fmt_uptime(sec) -> str:
    try:
        sec = int(sec)
    except Exception:
        return "—"
    d, r = divmod(sec, 86400)
    h, r = divmod(r, 3600)
    m, _ = divmod(r, 60)
    if d:
        return f"{d}天{h}时"
    if h:
        return f"{h}时{m}分"
    return f"{m}分"


def _bar_color(p: int) -> str:
    return "err" if p >= 85 else ("warn" if p >= 70 else "")


def _lang_select():
    sel = (
        '<select id="lang-sel" class="lang-sel" '
        f'onchange="PHW.route(\'set_lang\',{{value:this.value}})">'
        f'<option value="zh"{" selected" if LANG == "zh" else ""}>中文</option>'
        f'<option value="en"{" selected" if LANG == "en" else ""}>English</option>'
        '</select>'
    )
    return ui.raw(sel)


def _preset_select():
    sel = (
        '<select id="cfg-preset" class="preset-sel" '
        f'onchange="PHW.route(\'preset_apply\',{{value:this.value}})">'
        f'<option value="custom">{_esc(T("preset_custom"))}</option>'
        f'<option value="openai">{_esc(T("preset_openai"))}</option>'
        f'<option value="deepseek">{_esc(T("preset_deepseek"))}</option>'
        f'<option value="ollama">{_esc(T("preset_ollama"))}</option>'
        '</select>'
    )
    return ui.raw(sel)


# --------------------------------------------------------------------------
# 暗面构建设计 token（内联，VM 自包含）—— 管理面板语言
# --------------------------------------------------------------------------
CSS = """
:root{
  --bg-top:#0a1120; --bg-bottom:#05080f;
  --card:rgba(17,25,40,0.72);
  --card-solid:#0c1322;
  --border:rgba(255,255,255,0.09);
  --border-strong:rgba(255,255,255,0.16);
  --text:#e6f1ff; --sub:#8892a4;
  --accent:#4CC9F0; --accent-30:rgba(76,201,240,0.28);
  --accent-12:rgba(76,201,240,0.12);
  --ok:#3ddc97; --err:#ff6b6b; --warn:#ffd166;
  --radius:12px;
  --shadow:0 8px 28px rgba(0,0,0,0.35);
  --mono:ui-monospace,SFMono-Regular,Consolas,"Liberation Mono",monospace;
}
*{box-sizing:border-box}
html,body{margin:0;height:100%}
body{
  font-family:-apple-system,"Segoe UI",Roboto,"PingFang SC","Microsoft YaHei",sans-serif;
  color:var(--text);
  background:linear-gradient(180deg,var(--bg-top),var(--bg-bottom));
  background-attachment:fixed;
  font-size:14px; line-height:1.5;
  -webkit-font-smoothing:antialiased;
}
body::before{
  content:"";position:fixed;inset:0;pointer-events:none;z-index:0;
  background-image:linear-gradient(rgba(255,255,255,0.02) 1px,transparent 1px),
                   linear-gradient(90deg,rgba(255,255,255,0.02) 1px,transparent 1px);
  background-size:34px 34px;
  -webkit-mask-image:radial-gradient(circle at 50% 0%,#000,transparent 75%);
          mask-image:radial-gradient(circle at 50% 0%,#000,transparent 75%);
}
.app-shell{position:relative;z-index:1;display:flex;flex-direction:column;height:100vh}

/* ---- topbar ---- */
.topbar{
  display:flex;align-items:center;justify-content:space-between;
  padding:0 20px;height:58px;flex:none;
  background:rgba(8,13,24,0.7);backdrop-filter:blur(10px);
  border-bottom:1px solid var(--border);
}
.brand{display:flex;align-items:center;gap:12px}
.brand .logo{
  width:34px;height:34px;display:grid;place-items:center;border-radius:9px;
  background:var(--accent-12);border:1px solid var(--accent-30);font-size:18px;
}
.brand h1{font-size:16px;margin:0;letter-spacing:.4px;font-weight:650}
.brand small{display:block;color:var(--sub);font-size:11.5px;margin-top:1px;letter-spacing:.3px}
.top-actions{display:flex;align-items:center;gap:10px}
.lang-sel{width:auto;padding:5px 8px;font-size:12px}
.status-pill{
  display:inline-flex;align-items:center;gap:7px;font-size:12px;color:var(--sub);
  padding:6px 12px;border-radius:20px;border:1px solid var(--border);background:rgba(255,255,255,0.03);
}
.status-pill .dot{width:7px;height:7px;border-radius:50%;background:var(--sub)}
.status-pill:not(.off) .dot{background:var(--ok);box-shadow:0 0 8px var(--ok)}

/* ---- layout ---- */
.layout{flex:1;display:flex;min-height:0}
.panel-head{
  display:flex;align-items:center;gap:8px;padding:13px 16px;
  border-bottom:1px solid var(--border);font-size:12px;color:var(--sub);
  letter-spacing:.5px;text-transform:uppercase;flex:none;
}
.panel-head .tick{width:6px;height:6px;border-radius:50%;background:var(--accent);box-shadow:0 0 8px var(--accent)}

/* console (left) */
.console{flex:1;display:flex;flex-direction:column;min-width:0;border-right:1px solid var(--border)}
.chat-msgs{flex:1;overflow-y:auto;padding:18px 18px 8px;display:flex;flex-direction:column;gap:14px}
.muted{color:var(--sub);font-size:13px}
.muted.center{text-align:center;margin:auto;max-width:420px;line-height:1.7}
.composer{padding:12px 16px 14px;border-top:1px solid var(--border);display:flex;gap:10px;align-items:flex-end;background:rgba(8,13,24,0.4)}
.chat-input{
  flex:1;resize:none;min-height:46px;max-height:160px;
  background:rgba(5,8,15,0.7);color:var(--text);
  border:1px solid var(--border);border-radius:10px;padding:12px 14px;font-size:14px;outline:none;
  transition:border-color .15s,box-shadow .15s;
}
.chat-input:focus{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-12)}
.agent-status{font-size:12px;color:var(--sub);padding:0 16px 6px;display:flex;align-items:center;gap:7px}
.agent-status .dot{width:6px;height:6px;border-radius:50%;background:var(--accent);box-shadow:0 0 8px var(--accent)}

/* 对话气泡 */
.bubble{max-width:88%;padding:11px 14px;border-radius:12px;line-height:1.55;font-size:14px;white-space:pre-wrap;word-break:break-word}
.bubble .who{font-size:11px;color:var(--sub);margin-bottom:5px;letter-spacing:.3px}
.bubble.user{align-self:flex-end;background:linear-gradient(180deg,#16384f,#0e2438);border:1px solid var(--accent-30);border-bottom-right-radius:4px}
.bubble.user .who{color:#9fd9ef}
.bubble.ai{align-self:flex-start;background:var(--card);border:1px solid var(--border);border-top-left-radius:4px}
.bubble.err{align-self:flex-start;background:rgba(255,107,107,0.12);border:1px solid var(--err);color:#ffd5d5}

/* 操作日志条目（工具调用） */
.op{align-self:flex-start;width:92%;display:flex;gap:11px;padding:11px 0;border-bottom:1px solid rgba(255,255,255,0.06)}
.op:last-child{border-bottom:none}
.op .rail{width:3px;border-radius:3px;background:var(--accent);flex:none;align-self:stretch;opacity:.85}
.op.err .rail{background:var(--err)} .op.warn .rail{background:var(--warn)}
.op .body{flex:1;min-width:0}
.op .top{display:flex;align-items:center;gap:8px}
.op .name{font-weight:600;font-size:13px;font-family:var(--mono)}
.op .tag{margin-left:auto;font-size:10.5px;padding:2px 8px;border-radius:20px;letter-spacing:.3px;text-transform:uppercase;
  background:rgba(61,220,151,0.12);color:var(--ok);border:1px solid rgba(61,220,151,0.35)}
.op.err .tag{background:rgba(255,107,107,0.12);color:var(--err);border-color:rgba(255,107,107,0.35)}
.op.warn .tag{background:rgba(255,209,102,0.12);color:var(--warn);border-color:rgba(255,209,102,0.35)}
.op .args{font-size:11.5px;color:var(--sub);margin-top:4px;font-family:var(--mono);white-space:pre-wrap;word-break:break-all}
.op .res{margin-top:7px;font-family:var(--mono);font-size:12px;color:#cfe3f5;white-space:pre-wrap;
  background:rgba(5,8,15,0.55);border:1px solid var(--border);border-radius:8px;padding:9px 11px;max-height:200px;overflow:auto}

/* dashboard (right) */
.dashboard{width:372px;flex:none;display:flex;flex-direction:column;min-height:0}
.dash-body{flex:1;overflow-y:auto;padding:14px;display:flex;flex-direction:column;gap:14px}
.dash-foot{padding:0 14px 14px;flex:none}
.stat-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.stat{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:12px 13px;position:relative;overflow:hidden}
.stat::after{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--accent);opacity:.7}
.stat .label{font-size:10.5px;color:var(--sub);letter-spacing:.6px;text-transform:uppercase}
.stat .value{font-size:19px;font-weight:650;margin-top:5px;font-variant-numeric:tabular-nums;line-height:1.2}
.stat .value small{font-size:12px;color:var(--sub);font-weight:400;margin-left:3px}
.stat .bar{height:5px;border-radius:4px;background:rgba(255,255,255,0.08);margin-top:9px;overflow:hidden}
.stat .bar > i{display:block;height:100%;background:var(--accent);border-radius:4px;transition:width .3s}
.stat .bar.warn > i{background:var(--warn)} .stat .bar.err > i{background:var(--err)}

.card{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:13px 14px}
.card h3{margin:0 0 11px;font-size:13px;font-weight:600;display:flex;align-items:center;gap:8px;color:var(--text)}
.card h3::before{content:"";width:3px;height:13px;border-radius:2px;background:var(--accent)}
.card h3 .mini{margin-left:auto;font-size:11.5px;padding:3px 9px}

.info-grid{display:grid;grid-template-columns:auto 1fr;gap:7px 14px;font-size:12.5px}
.info-grid .k{color:var(--sub)} .info-grid .v{color:var(--text);text-align:right;word-break:break-all;font-family:var(--mono);font-size:12px}

.chips{display:flex;flex-wrap:wrap;gap:6px}
.chip{font-size:11.5px;padding:3px 9px;border-radius:20px;background:var(--accent-12);border:1px solid var(--accent-30);color:#bfe9f7;font-family:var(--mono)}
.chip.dim{background:rgba(255,255,255,0.04);border-color:var(--border);color:var(--sub)}

.pills{display:flex;flex-wrap:wrap;gap:6px}
.pill{display:inline-flex;align-items:center;gap:6px;font-size:11.5px;padding:3px 9px;border-radius:20px;border:1px solid var(--border);color:var(--sub)}
.pill .dot{width:6px;height:6px;border-radius:50%;background:currentColor}
.pill.ok{color:var(--ok);border-color:rgba(61,220,151,0.4);background:rgba(61,220,151,0.08)}
.pill.ok .dot{background:var(--ok);box-shadow:0 0 6px var(--ok)}
.pill.off{color:var(--sub);background:rgba(255,255,255,0.03)}

.caps{display:flex;flex-direction:column;gap:8px;font-size:12.5px}
.caps .cap{display:flex;gap:9px;align-items:baseline}
.caps .cap b{color:var(--accent);font-weight:600;font-family:var(--mono);font-size:12px;min-width:124px}
.caps .cap span{color:var(--sub);line-height:1.4}

/* buttons */
button{font-family:inherit;cursor:pointer;border-radius:9px;border:1px solid var(--border);
  background:rgba(255,255,255,0.04);color:var(--text);padding:8px 14px;font-size:13px;transition:.15s}
button:hover{border-color:var(--accent);color:#fff}
button.primary{background:var(--accent);color:#04121c;border-color:var(--accent);font-weight:600}
button.primary:hover{filter:brightness(1.08)}
button.ghost{background:transparent}
button.send{padding:10px 18px}
button.mini{padding:3px 10px;font-size:12px}

/* form */
input,select{width:100%;background:rgba(5,8,15,0.7);color:var(--text);
  border:1px solid var(--border);border-radius:9px;padding:9px 11px;font-size:13px;outline:none;transition:.15s}
input:focus,select:focus{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-12)}
label{display:block;font-size:12px;color:var(--sub);margin:12px 0 5px}
label.chk{display:flex;align-items:center;gap:8px;color:var(--text);margin-top:12px}
label.chk input{width:auto}

/* drawer */
.drawer{position:fixed;top:0;right:0;height:100vh;width:390px;max-width:92vw;z-index:30;
  background:var(--card-solid);border-left:1px solid var(--border-strong);
  box-shadow:-20px 0 60px rgba(0,0,0,0.55);padding:18px 18px 24px;overflow-y:auto;
  transform:translateX(0);transition:transform .22s ease}
.drawer.hidden{transform:translateX(105%)}
.drawer-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:4px}
.drawer-actions{display:flex;gap:10px;margin-top:16px}
.drawer-actions button{flex:1}
.cfg-msg{margin-top:10px;font-size:13px}
.cfg-msg .ok{color:var(--ok)} .cfg-msg .err{color:var(--err)}
.hint{margin-top:16px;padding:11px 13px;font-size:12px;color:var(--sub);
  background:var(--accent-12);border:1px solid var(--accent-30);border-radius:10px;line-height:1.65;font-family:var(--mono)}
.preset-sel{margin-top:6px}
.example-chip{font-size:12px;padding:5px 10px;border-radius:20px;background:var(--accent-12);
  border:1px solid var(--accent-30);color:#bfe9f7;cursor:pointer;font-family:var(--mono)}
.example-chip:hover{border-color:var(--accent);color:#fff}

/* login / wizard */
.overlay{position:fixed;inset:0;z-index:50;display:flex;align-items:center;justify-content:center;
  background:rgba(5,8,15,0.85);backdrop-filter:blur(6px)}
.overlay.hidden{display:none}
.login-card{width:360px;background:var(--card-solid);border:1px solid var(--border-strong);
  border-radius:16px;padding:28px 26px;text-align:center;box-shadow:var(--shadow)}
.login-card .lk{width:46px;height:46px;margin:0 auto 14px;display:grid;place-items:center;border-radius:12px;
  background:var(--accent-12);border:1px solid var(--accent-30);font-size:22px}
.login-card h2{margin:0 0 6px;font-size:19px;font-weight:650}
.login-card p{color:var(--sub);font-size:13px;margin:0 0 18px}
.login-card input{margin-bottom:14px;text-align:center;letter-spacing:1px}
.wiz-step{margin:12px 0;font-size:13px;line-height:1.6}
.wiz-step .muted{margin-top:3px}
.wiz-step b{color:var(--accent)}

/* scrollbars */
::-webkit-scrollbar{width:9px;height:9px}
::-webkit-scrollbar-thumb{background:rgba(255,255,255,0.12);border-radius:6px}
::-webkit-scrollbar-thumb:hover{background:rgba(255,255,255,0.2)}
::-webkit-scrollbar-track{background:transparent}

@media (max-width:860px){
  .layout{flex-direction:column}
  .dashboard{width:auto;border-top:1px solid var(--border)}
  .console{border-right:none}
}
"""


class AgentPanelApp(Win):
    """Win 子类：每次 render 用当前语言重建 body，使语言切换（reload 后）真生效。"""

    def render(self):
        self._body_children = []
        self.body(self._panel._layout())
        return super().render()


class AgentPanel:
    """可复用的 Agent 面板组件（与 AntNest 面板同款写法）。"""

    def __init__(self) -> None:
        self.APP = None
        self.API_HISTORY = []      # 对话（system/user/assistant/tool/error），供 LLM 与渲染共用
        self.CFG_DRAFT = {}        # 配置抽屉临时草稿
        self.busy = False

    # ============================================================ 聊天
    def chat_send(self, data: dict):
        if self.busy:
            return
        text = (data.get("value") or "").strip()
        if not text:
            return
        self.API_HISTORY.append({"role": "user", "content": text})
        self.APP.run_js("var i=document.querySelector('#chat-input'); if(i) i.value='';")
        self._render_chat()
        self.APP.update("#agent-status", '<span class="dot"></span>' + T("thinking"))
        self.busy = True
        try:
            cfg = config_mod.load_config()
            agent_mod.run_chat(self.API_HISTORY, cfg, self._on_event)
        except Exception as e:  # noqa
            self._on_event("error", {"message": str(e)})
        finally:
            self.busy = False
            self.APP.update("#agent-status", '<span class="dot"></span>' + T("standby"))

    def _on_event(self, event: str, payload: dict):
        if event == "error":
            self.API_HISTORY.append({"role": "error", "content": payload.get("message", "")})
        # tool / token / done 的渲染数据已由 run_chat 原地写入 API_HISTORY
        self._render_chat()

    def _render_chat(self):
        items = [m for m in self.API_HISTORY if m.get("role") != "system"]
        if not items:
            self.APP.update(
                "#chat-msgs",
                '<div class="muted center">' + _esc(T("empty_hint")) + '</div>')
            return
        parts = []
        for m in items:
            role = m.get("role")
            if role == "user":
                parts.append('<div class="bubble user"><div class="who">' + _esc(T("role_user"))
                             + '</div><div class="txt">' + _esc(m.get("content", "")) + '</div></div>')
            elif role == "assistant":
                c = m.get("content") or ""
                if c.strip():
                    parts.append('<div class="bubble ai"><div class="who">' + _esc(T("role_agent"))
                                 + '</div><div class="txt">' + _esc(c) + '</div></div>')
            elif role == "tool":
                name = _esc(m.get("name", ""))
                status = m.get("status", "ok")
                badge = ("ok" if status in ("ok",) else
                         "err" if status in ("error", "denied", "needs_confirm") else "warn")
                cls = "" if badge == "ok" else badge
                args = m.get("args") or {}
                res = m.get("result", "")
                args_s = _esc(json.dumps(args, ensure_ascii=False)) if args else ""
                res_s = _esc(res) if res else ""
                parts.append(
                    f'<div class="op {cls}"><div class="rail"></div><div class="body">'
                    f'<div class="top"><span class="name">⚙ {name}</span>'
                    f'<span class="tag">{_esc(status)}</span></div>'
                    + (f'<div class="args">{args_s}</div>' if args_s else '')
                    + (f'<pre class="res">{res_s}</pre>' if res_s else '')
                    + '</div></div>')
            elif role == "error":
                parts.append('<div class="bubble err"><div class="who">' + _esc(T("role_error"))
                             + '</div><div class="txt">' + _esc(m.get("content", "")) + '</div></div>')
        self.APP.update("#chat-msgs", "\n".join(parts))
        self.APP.run_js(
            "var e=document.querySelector('#chat-msgs'); if(e) e.scrollTop=e.scrollHeight;")

    # ============================================================ 状态仪表盘
    def status_refresh(self, data: dict):
        try:
            res = tools_mod.status()
            self.APP.update("#dashboard-body", self._dashboard_html(res))
        except Exception as e:  # noqa
            self.APP.update(
                "#dashboard-body",
                f'<div class="muted center">' + _esc(T("status_fail").format(_esc(e))) + '</div>')

    def _dashboard_html(self, res: dict) -> str:
        # 内存
        mem_tot = (res.get("mem_total_kb", 0) or 0) // 1024 // 1024
        mem_av = (res.get("mem_avail_kb", 0) or 0) // 1024 // 1024
        mem_used = max(0, mem_tot - mem_av)
        mem_pct = int(mem_used / mem_tot * 100) if mem_tot else 0
        # 磁盘
        disk_tot = res.get("disk_total_gb", 0) or 0
        disk_free = res.get("disk_free_gb", 0) or 0
        disk_used = max(0, disk_tot - disk_free)
        disk_pct = int(disk_used / disk_tot * 100) if disk_tot else 0
        # 其余
        load = " ".join(res.get("loadavg") or []) or "—"
        up_s = _fmt_uptime(res.get("uptime_sec"))
        ports = [str(p.get("port", "")) for p in res.get("listening_ports", [])]
        svcs = [s.get("name", "") for s in res.get("services", [])][:14]
        tools_d = res.get("tools") or {}

        parts = []
        # 指标卡
        parts.append(f"""
        <div class="stat-grid">
          <div class="stat"><div class="label">{_esc(T("stat_load"))}</div><div class="value">{_esc(load)}</div></div>
          <div class="stat"><div class="label">{_esc(T("stat_uptime"))}</div><div class="value">{_esc(up_s)}</div></div>
          <div class="stat"><div class="label">{_esc(T("stat_mem"))}</div><div class="value">{mem_av}<small>/{mem_tot} GB</small></div>
            <div class="bar {_bar_color(mem_pct)}"><i style="width:{mem_pct}%"></i></div></div>
          <div class="stat"><div class="label">{_esc(T("stat_disk"))}</div><div class="value">{disk_free}<small>/{disk_tot} GB</small></div>
            <div class="bar {_bar_color(disk_pct)}"><i style="width:{disk_pct}%"></i></div></div>
        </div>""")
        # 系统信息
        parts.append(f"""
        <div class="card"><h3>{_esc(T("sysinfo"))}</h3>
          <div class="info-grid">
            <span class="k">{_esc(T("kernel"))}</span><span class="v">{_esc(res.get('kernel', '—'))}</span>
            <span class="k">{_esc(T("hostname"))}</span><span class="v">{_esc(res.get('nodename', '—'))}</span>
            <span class="k">{_esc(T("uptime"))}</span><span class="v">{_esc(up_s)}</span>
          </div></div>""")
        # 监听端口
        port_chips = "".join(f'<span class="chip">{_esc(p)}</span>' for p in ports) or \
            '<span class="chip dim">—</span>'
        parts.append(
            f'<div class="card"><h3>{_esc(T("ports"))} <span class="mini muted">{len(ports)}</span></h3>'
            f'<div class="chips">{port_chips}</div></div>')
        # 运行服务
        svc_chips = "".join(f'<span class="chip">{_esc(s)}</span>' for s in svcs) or \
            '<span class="chip dim">—</span>'
        parts.append(
            f'<div class="card"><h3>{_esc(T("services"))} <span class="mini muted">{len(svcs)}</span></h3>'
            f'<div class="chips">{svc_chips}</div></div>')
        # 工具链可用性
        if tools_d:
            pills = []
            for k, v in tools_d.items():
                cls = "ok" if v else "off"
                label = _esc(T("available")) if v else _esc(T("missing"))
                pills.append(f'<span class="pill {cls}"><span class="dot"></span>{_esc(k)} · {label}</span>')
            parts.append(
                f'<div class="card"><h3>{_esc(T("toolchain"))}</h3><div class="pills">{"".join(pills)}</div></div>')
        return "\n".join(parts)

    # ============================================================ 配置
    def cfg_open(self, data: dict):
        cfg = config_mod.load_config()
        self.CFG_DRAFT = {k: cfg.get(k) for k in
                         ("llm_base_url", "llm_model", "llm_api_key", "mock_mode", "skip_model_check")}
        self.APP.run_js("var e=document.querySelector('#cfg-base'); if(e) e.value="
                        + json.dumps(cfg.get("llm_base_url", "")) + ";")
        self.APP.run_js("var e=document.querySelector('#cfg-key'); if(e) e.value="
                        + json.dumps(cfg.get("llm_api_key", "")) + ";")
        self.APP.run_js("var e=document.querySelector('#cfg-model'); if(e) e.value="
                        + json.dumps(cfg.get("llm_model", "")) + ";")
        self.APP.run_js("var e=document.querySelector('#cfg-mock'); if(e) e.checked="
                        + json.dumps(bool(cfg.get("mock_mode"))) + ";")
        self.APP.run_js("document.querySelector('#cfg-drawer').classList.remove('hidden');")
        self._fill_models(cfg)

    def cfg_base(self, d):
        self.CFG_DRAFT["llm_base_url"] = (d.get("value") or "").strip()

    def cfg_key(self, d):
        self.CFG_DRAFT["llm_api_key"] = (d.get("value") or "")

    def cfg_model(self, d):
        self.CFG_DRAFT["llm_model"] = (d.get("value") or "").strip()

    def cfg_mock(self, d):
        self.CFG_DRAFT["mock_mode"] = bool(d.get("value"))

    def preset_apply(self, d):
        name = (d.get("value") or "custom")
        p = i18n_mod.PROVIDER_PRESETS.get(name)
        if not p:
            return
        self.CFG_DRAFT["llm_base_url"] = p["base"]
        self.CFG_DRAFT["llm_model"] = p["model"]
        self.APP.run_js("var e=document.querySelector('#cfg-base'); if(e) e.value="
                        + json.dumps(p["base"]) + ";")
        self.APP.run_js("var e=document.querySelector('#cfg-model'); if(e) e.value="
                        + json.dumps(p["model"]) + ";")

    def cfg_test(self, d):
        cfg = dict(self.CFG_DRAFT)
        try:
            r = agent_mod.test_connection(cfg)
        except Exception as e:  # noqa
            self.APP.update("#cfg-msg", f'<div class="err">❌ {_esc(e)}</div>')
            return
        if r.get("ok"):
            self._fill_models(cfg)
            extra = T("cfg_models").format(len(r.get("models", []))) if r.get("models") else ""
            self.APP.update("#cfg-msg", '<div class="ok">' + _esc(T("cfg_ok")) + _esc(extra) + '</div>')
        else:
            self.APP.update("#cfg-msg", '<div class="err">' + _esc(T("cfg_err").format(_esc(r.get("error", "")))) + '</div>')

    def _fill_models(self, cfg: dict):
        try:
            models = agent_mod.list_models(cfg)
        except Exception:
            models = []
        if models:
            opts = "\n".join(f'<option value="{_esc(m)}"></option>' for m in models)
            self.APP.update("#models-list", opts)

    def cfg_save(self, d):
        cfg = config_mod.load_config()
        for k in ("llm_base_url", "llm_model", "mock_mode", "skip_model_check"):
            if k in self.CFG_DRAFT:
                cfg[k] = self.CFG_DRAFT[k]
        if "llm_api_key" in self.CFG_DRAFT:
            cfg["llm_api_key"] = self.CFG_DRAFT["llm_api_key"]
        try:
            config_mod.save_config(cfg)
            self.APP.update("#cfg-msg", '<div class="ok">' + _esc(T("cfg_saved")) + '</div>')
        except Exception as e:  # noqa
            self.APP.update("#cfg-msg", '<div class="err">' + _esc(T("cfg_save_err").format(_esc(e))) + '</div>')

    def cfg_close(self, d):
        self.APP.run_js("document.querySelector('#cfg-drawer').classList.add('hidden');")

    # ============================================================ 语言 / 新手引导
    def set_lang(self, d):
        global LANG
        lang = (d.get("value") or "zh")
        if lang not in i18n_mod.I18N:
            lang = "zh"
        LANG = lang
        try:
            cfg = config_mod.load_config()
            cfg["ui_lang"] = lang
            config_mod.save_config(cfg)
        except Exception:
            pass
        # 前端随后 location.reload()

    def wizard_open(self, d):
        self.APP.run_js("document.querySelector('#wizard-overlay').classList.remove('hidden');")

    def wizard_close(self, d):
        self.APP.run_js("document.querySelector('#wizard-overlay').classList.add('hidden');")

    # ============================================================ 登录
    def login(self, d):
        pw = (d.get("value") or "").strip()
        if pw and secrets.compare_digest(pw, config_mod.get_password()):
            tok = secrets.token_urlsafe(24)
            SESSIONS[tok] = {"created": time.time()}
            self.APP.set_cookie(tok)
            self.APP.run_js("document.querySelector('#login-overlay').classList.add('hidden');")
            self.APP.run_js(
                "var p=document.querySelector('#conn-pill');"
                "if(p){p.classList.remove('off');"
                "p.innerHTML='<span class=\"dot\"></span> " + _esc(T("online")) + "';}")
            # 登录后启动仪表盘自动刷新（5s）
            self.APP.run_js(
                "if(window.__dash)clearInterval(window.__dash);"
                "window.__dash=setInterval(function(){PHW.route('status_refresh',{});},5000);")
            self.status_refresh({})
            self.cfg_open({})
            # 首次进入弹出新手引导
            self.APP.run_js("document.querySelector('#wizard-overlay').classList.remove('hidden');")
        else:
            self.APP.update("#login-msg", '<div class="err">' + _esc(T("login_err")) + '</div>')

    def logout(self, d):
        cookie = d.get("value") or ""
        for part in cookie.split(";"):
            part = part.strip()
            if part.startswith("an_token="):
                SESSIONS.pop(part.split("=", 1)[1].strip().strip('"'), None)
        self.APP.clear_cookie()
        self.APP.run_js(
            "if(window.__dash)clearInterval(window.__dash);"
            "var p=document.querySelector('#conn-pill');"
            "if(p){p.classList.add('off');p.innerHTML='<span class=\"dot\"></span> " + _esc(T("standby")) + "';}"
            "document.querySelector('#login-overlay').classList.remove('hidden');")

    # ============================================================ 构建
    def build_app(self) -> Win:
        global LANG
        LANG = (config_mod.load_config().get("ui_lang") or "zh")
        if LANG not in i18n_mod.I18N:
            LANG = "zh"
        app = AgentPanelApp(title=T("login_title") + " · 在暗面构建", width=1180, height=780,
                            backend="browser", host="0.0.0.0", port=8080)
        self.APP = app
        app._panel = self
        app.css(CSS)
        self._register_routes(app)
        # 浏览器模式鉴权：仅 login/logout/set_lang 公开
        app._public_routes = {"login", "logout", "set_lang"}
        app._auth_check = lambda name, cookies: cookies.get("an_token", "") in SESSIONS
        return app

    def _register_routes(self, app: Win):
        for name in ("chat_send", "status_refresh", "cfg_open", "cfg_base", "cfg_key",
                     "cfg_model", "cfg_mock", "cfg_test", "cfg_save", "cfg_close",
                     "preset_apply", "set_lang", "wizard_open", "wizard_close",
                     "login", "logout"):
            app.route(name)(getattr(self, name))

    def _layout(self):
        return ui.div(cls="app-shell")[
            ui.header(cls="topbar")[
                ui.div(cls="brand")[
                    ui.span("🐜", cls="logo"),
                    ui.div()[
                        ui.h1(T("login_title")),
                        ui.small(T("brand_sub")),
                    ],
                ],
                ui.div(cls="top-actions")[
                    _lang_select(),
                    ui.button("📖", cls="ghost", onclick="wizard_open",
                              title=_esc(T("wizard_title"))),
                    ui.span(id="conn-pill", cls="status-pill off")[
                        ui.span(cls="dot"), T("standby")],
                    ui.button(T("btn_config"), cls="ghost", onclick="cfg_open"),
                    ui.button(T("btn_logout"), cls="ghost",
                              onclick="PHW.route('logout',{value:document.cookie})"),
                ],
            ],
            ui.main(cls="layout")[
                # 左侧：指令控制台
                ui.section(cls="console")[
                    ui.div(cls="panel-head")[ui.span(cls="tick"), T("console_title")],
                    ui.div(id="chat-msgs", cls="chat-msgs"),
                    ui.div(id="agent-status", cls="agent-status")[
                        ui.span(cls="dot"), T("standby")],
                    ui.div(cls="composer")[
                        ui.input(id="chat-input", cls="chat-input",
                                 placeholder=T("placeholder")),
                        ui.button("发送", cls="send",
                                  onclick="PHW.route('chat_send',{value:document.querySelector('#chat-input').value})"),
                    ],
                ],
                # 右侧：系统概览仪表盘
                ui.aside(cls="dashboard")[
                    ui.div(cls="panel-head")[ui.span(cls="tick"), T("dash_title")],
                    ui.div(id="dashboard-body", cls="dash-body")[
                        ui.raw('<div class="muted center">' + _esc(T("dash_title")) + '…</div>')],
                    ui.div(cls="dash-foot")[
                        ui.div(cls="card")[
                            ui.h3(T("cap_title")),
                            ui.div(cls="caps")[
                                ui.div(cls="cap")[ui.strong("system_run_cmd"),
                                                 ui.span(T("cap_run_cmd"))],
                                ui.div(cls="cap")[ui.strong("system_status"),
                                                 ui.span(T("cap_status"))],
                                ui.div(cls="cap")[ui.strong("files_read/write"),
                                                 ui.span(T("cap_files"))],
                                ui.div(cls="cap")[ui.strong("pkg_inspect"),
                                                 ui.span(T("cap_inspect"))],
                                ui.div(cls="cap")[ui.strong("pkg_repack_*"),
                                                 ui.span(T("cap_repack"))],
                                ui.div(cls="cap")[ui.strong("pkg_rollback"),
                                                 ui.span(T("cap_rollback"))],
                            ],
                        ],
                    ],
                ],
            ],
            # 配置抽屉
            ui.div(id="cfg-drawer", cls="drawer hidden")[
                ui.div(cls="drawer-head")[
                    ui.h3(T("cfg_title")),
                    ui.button("✕", cls="ghost", onclick="cfg_close"),
                ],
                ui.label(T("preset_label")),
                _preset_select(),
                ui.label(T("lbl_base")),
                ui.input(id="cfg-base", placeholder="https://api.deepseek.com/v1", oninput="cfg_base"),
                ui.label(T("lbl_key")),
                ui.input(id="cfg-key", type="password", placeholder="sk-...", oninput="cfg_key"),
                ui.label(T("lbl_model")),
                ui.input(id="cfg-model", list="models-list", placeholder="deepseek-chat", oninput="cfg_model"),
                ui.datalist(id="models-list"),
                ui.label(cls="chk")[
                    ui.input(id="cfg-mock", type="checkbox",
                             onclick="PHW.route('cfg_mock',{value:document.querySelector('#cfg-mock').checked})"),
                    T("lbl_mock"),
                ],
                ui.div(cls="drawer-actions")[
                    ui.button(T("btn_test"), onclick="cfg_test"),
                    ui.button(T("btn_save"), cls="primary", onclick="cfg_save"),
                ],
                ui.div(id="cfg-msg", cls="cfg-msg"),
                ui.div(cls="hint")[
                    _esc(T("hint_title")), ui.br(),
                    ui.pre(cls="res", style="margin-top:6px")[T("hint_cmd")], ui.br(),
                    _esc(T("hint_restart")),
                ],
            ],
            # 新手引导
            ui.div(id="wizard-overlay", cls="overlay hidden")[
                ui.div(cls="login-card", style="width:430px;text-align:left")[
                    ui.h2(T("wizard_title")),
                    ui.div(cls="wiz-step")[
                        ui.strong(T("wizard_step1")),
                        ui.div(cls="muted")[
                            _esc(T("wizard_pw")),
                            ui.pre(cls="res", style="margin-top:6px")[T("hint_cmd")],
                        ],
                    ],
                    ui.div(cls="wiz-step")[
                        ui.strong(T("wizard_step2")),
                        ui.div(cls="muted")[T("wizard_api")],
                    ],
                    ui.div(cls="wiz-step")[
                        ui.strong(T("wizard_step3")),
                        ui.div(cls="chips", style="margin-top:8px")[
                            "".join(
                                f'<button class="example-chip" onclick="PHW.route(\'chat_send\',{{value:{json.dumps(p)}}})">{_esc(p)}</button>'
                                for p in i18n_mod.EXAMPLE_PROMPTS)
                        ],
                    ],
                    ui.button(T("wizard_close"), cls="primary",
                              style="width:100%;margin-top:14px", onclick="wizard_close"),
                ],
            ],
            # 登录遮罩
            ui.div(id="login-overlay", cls="overlay")[
                ui.div(cls="login-card")[
                    ui.div(cls="lk")["🐜"],
                    ui.h2(T("login_title")),
                    ui.p(T("login_prompt")),
                    ui.input(id="login-pw", type="password", placeholder=T("login_pw")),
                    ui.button(T("login_btn"), cls="primary",
                              onclick="PHW.route('login',{value:document.querySelector('#login-pw').value})"),
                    ui.div(id="login-msg", cls="cfg-msg"),
                ],
            ],
        ]
