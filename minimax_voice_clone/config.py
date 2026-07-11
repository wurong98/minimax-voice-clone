"""常量 + auth + 校验 + 本地默认参数缓存。

这一模块不依赖 api/ui,只暴露其它模块需要的纯 helper 和常量。
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Optional

import typer

# ============================================================
# 常量
# ============================================================
BASE_URL = "https://api.minimaxi.com"

ALLOWED_EMOTIONS = {
    "happy", "sad", "angry", "fearful",
    "disgusted", "surprised", "neutral", "fluent",
}

# 官方枚举 8 个 TTS 模型
ALLOWED_MODELS = frozenset({
    "speech-2.8-hd", "speech-2.8-turbo",
    "speech-2.6-hd", "speech-2.6-turbo",
    "speech-02-hd", "speech-02-turbo",
    "speech-01-hd", "speech-01-turbo",
})

# voice_id 规则:首字符字母,后续只能字母/数字/-/_,长度 8~256,末位不能是 - 或 _
_VOICE_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{6,254}[A-Za-z0-9]$")
MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20MB

# voice_clone 上传用途只接受 mp3 / m4a / wav(FLAC 会被 2013 拒)
SUPPORTED_UPLOAD_EXTS = {".mp3", ".m4a", ".wav"}

# 异步轮询默认
DEFAULT_POLL_INTERVAL = 3.0    # 秒
DEFAULT_POLL_TIMEOUT = 600.0   # 秒

# 本地默认参数缓存(XDG 风格,Linux/Mac)
CONFIG_DIR = Path.home() / ".config" / "clone-voice"
CONFIG_FILE = CONFIG_DIR / "config.json"

# 内置 fallback 默认值(合成参数)
INTERNAL_DEFAULTS: dict[str, Any] = {
    "voice_id": None,
    "model": "speech-2.8-hd",
    "emotion": "neutral",
    "speed": 1.0,
    "pitch": 0,
    "volume": 1.0,
    "sample_rate": 32000,
    "bitrate": 128000,
    "channel": 1,
    "response_format": "mp3",
}


# ============================================================
# Auth
# ============================================================
def resolve_api_key(api_key: Optional[str]) -> str:
    """优先用 --api-key 传进来的,其次用环境变量 MINIMAX_API_KEY"""
    key = api_key or os.getenv("MINIMAX_API_KEY")
    if not key:
        typer.secho(
            "❌ 找不到 API_KEY。请用 --api-key 传入,或在环境变量里设置 MINIMAX_API_KEY",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)
    return key


def auth_headers(api_key: str) -> dict[str, str]:
    """所有 JSON 接口的统一头"""
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


# ============================================================
# 校验器(失败直接 typer.Exit)
# ============================================================
def validate_voice_id(voice_id: str) -> None:
    if not _VOICE_ID_RE.match(voice_id):
        typer.secho(
            "❌ voice_id 不合法。规则:\n"
            "   - 长度 8~256\n"
            "   - 仅允许 A-Z / a-z / 0-9 / - / _\n"
            "   - 首字符必须是英文字母\n"
            "   - 末位不能是 '-' 或 '_'",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)


def validate_emotion(emotion: str) -> None:
    if emotion not in ALLOWED_EMOTIONS:
        typer.secho(
            f"❌ --emotion 取值非法,允许: {sorted(ALLOWED_EMOTIONS)}",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)


def validate_model(model: str) -> None:
    if model not in ALLOWED_MODELS:
        typer.secho(
            "❌ --model 取值非法。允许:\n  " + "\n  ".join(sorted(ALLOWED_MODELS)),
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)


def check_base_resp(j: dict, op_name: str) -> dict:
    """统一检查 MiniMax base_resp.status_code == 0;失败抛 RuntimeError。"""
    base = j.get("base_resp") or {}
    code = base.get("status_code")
    if code != 0:
        raise RuntimeError(
            f"{op_name}失败: status_code={code} "
            f"msg={base.get('status_msg')} body={j}"
        )
    return j


# ============================================================
# 本地默认参数缓存 (~/.config/clone-voice/config.json)
# ============================================================
def load_config() -> dict[str, Any]:
    """读本地 config.json;文件不存在或损坏时返回 {}。"""
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def save_config(cfg: dict[str, Any]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2, sort_keys=True)


def update_config(updates: dict[str, Any]) -> None:
    """merge 写入本地缓存,只覆盖非 None 值。"""
    cur = load_config()
    for k, v in updates.items():
        if v is not None:
            cur[k] = v
    save_config(cur)


def resolve_with_config(user_provided: Optional[Any], key: str) -> tuple[Any, bool]:
    """如果用户没传(None),从 config 取;返回 (最终值, 是否从 config 取的 bool)。"""
    if user_provided is not None:
        return user_provided, False
    cfg = load_config()
    val = cfg.get(key)
    if val is not None:
        return val, True
    return INTERNAL_DEFAULTS.get(key), False
