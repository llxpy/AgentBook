# -*- coding: utf-8 -*-
"""antnest-web · 配置层（LLM 配置 + API Key 分离存储）。

设计：
- config.json 只存非敏感项（base_url / model / 开关），保持嵌套形状简单。
- API Key 单独存 config.json.key（权限 0600），不进 config.json、不进 git。
- 密码（登录用）由服务启动时从环境变量 AN_AGENT_PASSWORD 读取；若为空则
  首次启动随机生成并写入 state/secret，打印到 stdout 供用户首次登录。
"""
from __future__ import annotations

import os
import json
import secrets

APP_DIR = os.environ.get("AN_WEB_DIR") or os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.environ.get("AN_WEB_CONFIG") or os.path.join(APP_DIR, "config.json")
SECRET_FILE = CONFIG_FILE + ".key"
STATE_DIR = os.path.join(APP_DIR, "state")
KEY_FILE = os.path.join(STATE_DIR, "agent_password")

DEFAULTS = {
    "llm_base_url": "https://api.deepseek.com/v1",
    "llm_model": "deepseek-chat",
    "skip_model_check": True,
    "mock_mode": False,           # 无 API Key 时跑演示循环
}


def _ensure_dirs():
    os.makedirs(STATE_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                cfg.update({k: v for k, v in data.items() if k != "llm_api_key"})
    except Exception:
        pass
    # API Key 优先从独立密钥文件读取
    if os.path.exists(SECRET_FILE):
        try:
            key = open(SECRET_FILE, encoding="utf-8").read().strip()
            if key:
                cfg["llm_api_key"] = key
        except Exception:
            pass
    else:
        cfg.setdefault("llm_api_key", "")
    return cfg


def save_config(cfg: dict) -> None:
    _ensure_dirs()
    key = (cfg.get("llm_api_key") or "").strip()
    core = {k: v for k, v in cfg.items() if k != "llm_api_key"}
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(core, f, ensure_ascii=False, indent=2)
    if key:
        with open(SECRET_FILE, "w", encoding="utf-8") as f:
            f.write(key)
        try:
            os.chmod(SECRET_FILE, 0o600)
        except Exception:
            pass
    else:
        # 清空 key：删除密钥文件
        try:
            if os.path.exists(SECRET_FILE):
                os.remove(SECRET_FILE)
        except Exception:
            pass


def get_password() -> str:
    """返回登录密码；优先环境变量，其次已写入的 state/agent_password，再次随机生成并落盘。"""
    env_pw = os.environ.get("AN_AGENT_PASSWORD", "").strip()
    if env_pw:
        return env_pw
    if os.path.exists(KEY_FILE):
        try:
            return open(KEY_FILE, encoding="utf-8").read().strip()
        except Exception:
            pass
    pw = secrets.token_urlsafe(12)
    _ensure_dirs()
    try:
        with open(KEY_FILE, "w", encoding="utf-8") as f:
            f.write(pw)
        os.chmod(KEY_FILE, 0o600)
    except Exception:
        pass
    return pw


def set_password(pw: str) -> None:
    """在控制台手动设置登录密码，写入 state/agent_password（权限 0600）。

    用法：python3 server.py --set-password <你的密码>
    下次重启服务生效；重启前仍用旧密码。
    """
    pw = (pw or "").strip()
    if not pw:
        raise ValueError("密码不能为空")
    _ensure_dirs()
    with open(KEY_FILE, "w", encoding="utf-8") as f:
        f.write(pw)
    try:
        os.chmod(KEY_FILE, 0o600)
    except Exception:
        pass


def mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "****"
    return key[:4] + "****" + key[-4:]
