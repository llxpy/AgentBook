# -*- coding: utf-8 -*-
"""AgentBook · Agent 循环 + OpenAI 兼容 LLM 客户端。

- 支持任意 OpenAI 兼容端点（DeepSeek / 本地 vLLM / Ollama 等）。
- 工具调用循环：assistant 返回 tool_calls → 执行 → 回灌 → 继续，直到给出最终答案。
- mock 模式：无 API Key 时跑一个演示循环（调用 system_status / system_run_cmd 再总结），
  方便用户不配置 Key 也能立刻看到「对话 → 工具 → 结果」的闭环。
"""
from __future__ import annotations

import json
import urllib.request
import urllib.error

import tools as tools_mod

SYSTEM_PROMPT = (
    "你是一个运行在 Linux 虚拟机上的运维 Agent，用户通过浏览器与你对话，"
    "用自然语言让你控制这台 Linux 系统。\n"
    "规则：\n"
    "1. 优先用工具完成任务：system_run_cmd 执行命令、system_status 看状态、"
    "files_read/files_write 读写文件、pkg_inspect/pkg_repack_deb/pkg_repack_rpm/pkg_install_test/pkg_rollback 处理安装包。\n"
    "2. 只回答与当前 Linux 系统相关的事；不要编造你没执行的命令的结果。\n"
    "3. 危险命令（sudo、rm -rf、格式化、改系统等）system_run_cmd 会返回 needs_confirm，"
    "此时你在回复里明确告诉用户「这条命令需要确认，请在界面点确认后重试」，不要自己硬来。\n"
    "4. 回答简洁、用中文、给可验证的证据（命令输出片段）。\n"
    "5. 涉及改包（repack）时提醒用户：原签名会失效，需重新签名后才可信。"
)

MAX_TOOL_RESULT = 4000


def _llm_chat_stream(cfg: dict, messages: list, emit, assistant_msg: dict):
    """stream:True 调用：逐块 emit('token', piece) 并原地写入 assistant_msg['content']；
    返回完整 assistant message（含跨 chunk 聚合后的 tool_calls）。异常向上抛，由 run_chat 统一处理。"""
    base = (cfg.get("llm_base_url") or "").rstrip("/")
    key = cfg.get("llm_api_key") or ""
    if not base or "://" not in base:
        raise ValueError("LLM base_url 未配置")
    url = f"{base}/chat/completions"
    body = {
        "model": cfg.get("llm_model") or "deepseek-chat",
        "messages": messages,
        "tools": tools_mod.TOOL_SCHEMAS,
        "tool_choice": "auto",
        "stream": True,
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}",
                 "User-Agent": "agentbook",
                 "Accept": "text/event-stream"},
    )
    tool_acc = {}  # index -> {id, name, arguments}（流式工具调用需跨 chunk 聚合）
    with urllib.request.urlopen(req, timeout=120) as resp:
        for raw in resp:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                obj = json.loads(payload)
            except Exception:
                continue
            choices = obj.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            piece = delta.get("content") or ""
            if piece:
                assistant_msg["content"] += piece
                emit("token", piece)
            for tc in (delta.get("tool_calls") or []):
                idx = tc.get("index", 0)
                slot = tool_acc.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                if tc.get("id"):
                    slot["id"] = tc["id"]
                fn = tc.get("function") or {}
                if fn.get("name"):
                    slot["name"] += fn["name"]
                if fn.get("arguments"):
                    slot["arguments"] += fn["arguments"]
    tool_calls = []
    if tool_acc:
        for idx in sorted(tool_acc):
            slot = tool_acc[idx]
            tool_calls.append({
                "id": slot["id"] or f"call_{idx}",
                "type": "function",
                "function": {"name": slot["name"], "arguments": slot["arguments"]},
            })
    return {"role": "assistant", "content": assistant_msg["content"], "tool_calls": tool_calls}


def _truncate(s: str, n: int = MAX_TOOL_RESULT) -> str:
    s = s or ""
    return s if len(s) <= n else s[:n] + f"\n...[截断，共 {len(s)} 字]"


def _llm_get(cfg: dict, path: str, timeout: int = 20):
    """GET OpenAI 兼容端点（如 /models），返回解析后的 dict。"""
    base = (cfg.get("llm_base_url") or "").rstrip("/")
    key = cfg.get("llm_api_key") or ""
    if not base or "://" not in base:
        raise ValueError("LLM base_url 未配置")
    url = f"{base}/{path.lstrip('/')}"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {key}", "User-Agent": "agentbook"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def list_models(cfg: dict) -> list:
    """返回可用模型 id 列表（OpenAI 兼容 /models）；失败返回空列表。"""
    try:
        data = _llm_get(cfg, "models")
        return [m.get("id") for m in (data.get("data") or []) if m.get("id")]
    except Exception:
        return []


def test_connection(cfg: dict) -> dict:
    """检测 LLM 连接是否可用。

    先尝试拉 /models（多数 OpenAI 兼容端点支持，且能顺便拿到模型列表）；
    若 /models 不可用（如本地 Ollama），再退化为一次最小 chat 探活。
    返回 {ok, error, models}。
    """
    # 优先用 /models 探活并拿模型列表
    try:
        models = list_models(cfg)
        if models:
            return {"ok": True, "error": "", "models": models}
    except Exception:
        pass

    base = (cfg.get("llm_base_url") or "").rstrip("/")
    key = cfg.get("llm_api_key") or ""
    if not base or "://" not in base:
        return {"ok": False, "error": "Base URL 未配置", "models": []}
    if not key:
        return {"ok": False, "error": "API Key 未配置", "models": []}

    # 退化探活：最小 chat 请求
    url = f"{base}/chat/completions"
    body = {
        "model": cfg.get("llm_model") or "deepseek-chat",
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
        "stream": False,
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}",
                 "User-Agent": "agentbook"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            json.loads(resp.read().decode("utf-8", errors="replace"))
        return {"ok": True, "error": "", "models": []}
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", errors="replace")[:240]
        except Exception:
            pass
        return {"ok": False, "error": f"HTTP {e.code}: {detail}", "models": []}
    except Exception as e:  # noqa
        return {"ok": False, "error": str(e), "models": []}


def _mock_run(messages: list, emit):
    """无 Key 演示循环：根据最后一条用户消息选一个工具，再给总结。

    直接原地修改 messages（追加 tool / assistant），emit 仅负责渲染。
    """
    last_user = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            last_user = m["content"]
            break
    text = (last_user or "").lower()
    if any(k in text for k in ("状态", "status", "端口", "port", "服务", "service", "监控")):
        res = tools_mod.status()
        messages.append({"role": "tool", "tool_call_id": "system_status",
                         "name": "system_status", "args": {}, "status": "ok",
                         "result": _truncate(json.dumps(res, ensure_ascii=False))})
        emit("tool", {"name": "system_status", "args": {}, "result": _truncate(json.dumps(res, ensure_ascii=False)), "status": "ok"})
        answer = ("【演示模式·未配置 API Key】当前虚拟机状态：\n"
                  f"- 内核：{res.get('kernel')}\n"
                  f"- 已运行：{res.get('uptime_sec')} 秒\n"
                  f"- 负载：{res.get('loadavg')}\n"
                  f"- 监听端口：{[p['port'] for p in res.get('listening_ports', [])] or '无'}\n"
                  f"- 运行服务：{[s['name'] for s in res.get('services', [])][:10] or '无'}\n"
                  "配置 API Key 后即可由大模型自然语言驱动，无需演示逻辑。")
    else:
        res = tools_mod.run_cmd("uname -a && uptime")
        messages.append({"role": "tool", "tool_call_id": "system_run_cmd",
                         "name": "system_run_cmd", "args": {"cmd": "uname -a && uptime"},
                         "status": res.get("status"),
                         "result": _truncate(res.get("stdout", ""))})
        emit("tool", {"name": "system_run_cmd", "args": {"cmd": "uname -a && uptime"},
                      "result": _truncate(res.get("stdout", "")), "status": res.get("status")})
        answer = ("【演示模式·未配置 API Key】我已替你执行了 `uname -a && uptime`：\n"
                  f"{res.get('stdout', '')}\n"
                  "配置 API Key 后，我可以用自然语言把任意合法运维操作转成工具调用。")
    messages.append({"role": "assistant", "content": answer})
    emit("token", answer)
    emit("done", {"answer": answer})
    return messages


def run_chat(messages: list, cfg: dict, emit):
    """主循环。emit(event, payload) 实时回调前端。

    event: 'token' | 'tool' | 'done' | 'error'
    """
    if not cfg.get("llm_api_key") or cfg.get("mock_mode"):
        return _mock_run(messages, emit)

    if messages and messages[0].get("role") == "system":
        conv = messages
    else:
        messages.insert(0, {"role": "system", "content": SYSTEM_PROMPT})
        conv = messages

    # 流式：先放一个 assistant 占位，流式过程中原地填充内容并逐 token 渲染
    assistant_msg = {"role": "assistant", "content": ""}
    conv.append(assistant_msg)
    try:
        for _ in range(8):  # 最多 8 轮工具调用
            acc = _llm_chat_stream(cfg, conv, emit, assistant_msg)
            tool_calls = acc.get("tool_calls") or []
            if not tool_calls:
                emit("done", {"answer": assistant_msg["content"]})
                return conv

            assistant_msg["tool_calls"] = tool_calls
            for tc in tool_calls:
                fn = tc.get("function", {})
                name = fn.get("name", "")
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except Exception:
                    args = {}
                res = tools_mod.dispatch(name, args)
                conv.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id"),
                    "content": json.dumps(res, ensure_ascii=False),
                })
                emit("tool", {"name": name, "args": args,
                              "result": _truncate(json.dumps(res, ensure_ascii=False)),
                              "status": res.get("status")})
            # 下一轮：新建 assistant 占位（承接下一轮文本/工具）
            assistant_msg = {"role": "assistant", "content": ""}
            conv.append(assistant_msg)
        # 工具循环超限，强制收尾
        emit("token", "（工具调用次数已达上限，停止以免失控）")
        emit("done", {"answer": "（工具调用次数已达上限，停止以免失控）"})
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            pass
        emit("error", {"message": f"LLM HTTP {e.code}: {detail}"})
    except Exception as e:  # noqa
        emit("error", {"message": str(e)})
    return conv
