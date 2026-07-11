"""所有 MiniMax HTTP API 函数封装。

注意:
- 所有函数都不接 Rich UI(用 typer.secho / print 写日志是可接受的,但避免渲染逻辑)
- 大小写:do not care about caching invalidation;返回 raw dict / bytes
"""
from __future__ import annotations

import mimetypes
import time
from pathlib import Path
from typing import Any, Callable, Optional

import requests
import typer

from .config import (
    BASE_URL, MAX_UPLOAD_BYTES, SUPPORTED_UPLOAD_EXTS,
    DEFAULT_POLL_INTERVAL, DEFAULT_POLL_TIMEOUT,
    auth_headers, check_base_resp,
)

# ============================================================
# 端点分类常量(给 CLI 做 option 校验用)
# ============================================================
VOICE_TYPES_ALL = ("system", "voice_cloning", "voice_generation", "all")
VOICE_TYPES_DELETABLE = ("voice_cloning", "voice_generation")
FILE_PURPOSES = ("voice_clone", "prompt_audio", "t2a_async_input")
FILE_PURPOSES_DELETE = (
    "voice_clone", "prompt_audio", "t2a_async",
    "t2a_async_input", "video_generation",
)


# ============================================================
# Upload + Audio normalize
# ============================================================
def normalize_audio_for_upload(audio_path: Path) -> Path:
    """若文件不在 MiniMax 上传支持格式内,临时转一份 WAV,返回新路径。"""
    if audio_path.suffix.lower() in SUPPORTED_UPLOAD_EXTS:
        return audio_path
    if audio_path.suffix.lower() != ".flac":
        typer.secho(
            f"⚠️  未识别的扩展名 {audio_path.suffix},尝试以 FLAC 流程处理",
            fg=typer.colors.YELLOW,
        )
    import shutil
    import subprocess

    if not shutil.which("ffmpeg"):
        raise RuntimeError(
            "上传需要 mp3/m4a/wav,本机没找到 ffmpeg,无法自动转码。\n"
            "请先用 ffmpeg 把音频转成 wav 后再跑,例如:\n"
            f"  ffmpeg -i {audio_path} -c:a pcm_s16le out.wav"
        )
    converted = audio_path.with_name(audio_path.stem + "_converted.wav")
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", str(audio_path),
            "-c:a", "pcm_s16le",
            str(converted),
        ],
        check=True,
    )
    typer.secho(
        f"  🔄 检测到 {audio_path.suffix},已自动转为 {converted.name}",
        fg=typer.colors.YELLOW,
    )
    return converted


def upload_audio(api_key: str, audio_path: Path) -> str:
    """POST /v1/files/upload  purpose=voice_clone — 返回 file_id"""
    url = f"{BASE_URL}/v1/files/upload"
    headers = {"Authorization": f"Bearer {api_key}"}
    mime, _ = mimetypes.guess_type(audio_path.name)
    mime = mime or "audio/mpeg"
    with open(audio_path, "rb") as f:
        files = {"file": (audio_path.name, f, mime)}
        data = {"purpose": "voice_clone"}
        r = requests.post(url, headers=headers, files=files, data=data, timeout=120)
    r.raise_for_status()
    j = check_base_resp(r.json(), "上传")
    file_id = j["file"]["file_id"]
    typer.secho(
        f"  ✅ 上传成功 ({mime}), file_id = {file_id}",
        fg=typer.colors.GREEN,
    )
    return file_id


# ============================================================
# Clone
# ============================================================
def clone_voice(
    api_key: str,
    file_id: str,
    voice_id: str,
    *,
    model: str = "speech-2.8-hd",
    text: str = "This is a test sentence for voice cloning.",
    accuracy: float = 0.7,
    need_noise_reduction: bool = False,
    need_volume_normalization: bool = False,
    aigc_watermark: bool = False,
) -> str:
    """POST /v1/voice_clone"""
    url = f"{BASE_URL}/v1/voice_clone"
    payload = {
        "file_id": int(file_id),
        "voice_id": voice_id,
        "model": model,
        "text": text,
        "accuracy": accuracy,
        "need_noise_reduction": need_noise_reduction,
        "need_volume_normalization": need_volume_normalization,
        "aigc_watermark": aigc_watermark,
    }
    r = requests.post(url, headers=auth_headers(api_key),
                      json=payload, timeout=300)
    r.raise_for_status()
    j = check_base_resp(r.json(), "复刻")
    typer.secho(f"  ✅ 音色复刻成功, voice_id = {voice_id}", fg=typer.colors.GREEN)
    typer.secho(
        "  ⏰ 注意: 该音色 7 天内必须正式合成调用一次,否则会被自动删除",
        fg=typer.colors.YELLOW,
    )
    demo = (j.get("demo_audio") or "").strip()
    if demo:
        typer.secho(f"  🎧 试听音频: {demo}", fg=typer.colors.CYAN)
    return voice_id


# ============================================================
# Sync TTS
# ============================================================
def tts_synthesize(
    api_key: str,
    voice_id: str,
    text: str,
    out_path: Path,
    *,
    model: str,
    emotion: str,
    speed: float,
    pitch: int,
    volume: float,
    response_format: str,
    sample_rate: int,
    bitrate: int,
    channel: int,
    language_boost: Optional[str] = None,
    aigc_watermark: bool = False,
    quiet: bool = False,
) -> Path:
    """POST /v1/t2a_v2 — 同步合成。响应 data.audio 是 hex。"""
    url = f"{BASE_URL}/v1/t2a_v2"
    payload: dict[str, Any] = {
        "model": model,
        "text": text,
        "stream": False,
        "voice_setting": {
            "voice_id": voice_id,
            "speed": speed,
            "vol": volume,
            "pitch": pitch,
            "emotion": emotion,
        },
        "audio_setting": {
            "sample_rate": sample_rate,
            "bitrate": bitrate,
            "format": response_format,
            "channel": channel,
        },
    }
    if language_boost:
        payload["language_boost"] = language_boost
    if aigc_watermark:
        payload["aigc_watermark"] = True

    r = requests.post(url, headers=auth_headers(api_key),
                      json=payload, timeout=300)
    r.raise_for_status()
    j = check_base_resp(r.json(), "合成")
    data = j.get("data") or {}
    audio_hex = data.get("audio")
    if not audio_hex:
        raise RuntimeError(f"合成响应无 data.audio: {j}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(bytes.fromhex(audio_hex))
    if not quiet:
        extra = j.get("extra_info") or {}
        size_kb = extra.get("audio_size", len(audio_hex) // 2) / 1024
        length_s = extra.get("audio_length", 0) / 1000
        typer.secho(
            f"  ✅ 合成完成:{out_path} "
            f"({size_kb:.1f} KB,{length_s:.2f}s, "
            f"{extra.get('audio_format', response_format)} "
            f"{extra.get('audio_sample_rate', sample_rate)}Hz)",
            fg=typer.colors.GREEN,
        )
    return out_path


# ============================================================
# Voice design + management
# ============================================================
def voice_design(
    api_key: str,
    prompt: str,
    preview_text: str,
    *,
    voice_id: Optional[str] = None,
    aigc_watermark: bool = False,
) -> dict:
    """POST /v1/voice_design

    返回 {voice_id, trial_audio(hex), base_resp}
    """
    if not preview_text or len(preview_text) > 500:
        raise RuntimeError("preview_text 必须是 1~500 字符")
    url = f"{BASE_URL}/v1/voice_design"
    payload: dict[str, Any] = {
        "prompt": prompt,
        "preview_text": preview_text,
        "aigc_watermark": aigc_watermark,
    }
    if voice_id:
        payload["voice_id"] = voice_id
    r = requests.post(url, headers=auth_headers(api_key),
                      json=payload, timeout=300)
    r.raise_for_status()
    return check_base_resp(r.json(), "音色设计")


def list_voices(api_key: str, voice_type: str) -> dict:
    """POST /v1/get_voice"""
    url = f"{BASE_URL}/v1/get_voice"
    r = requests.post(url, headers=auth_headers(api_key),
                      json={"voice_type": voice_type}, timeout=60)
    r.raise_for_status()
    return check_base_resp(r.json(), "列音色")


def delete_voice(api_key: str, voice_type: str, voice_id: str) -> None:
    """POST /v1/delete_voice  — 只能删 voice_cloning / voice_generation"""
    if voice_type not in VOICE_TYPES_DELETABLE:
        typer.secho(
            f"❌ 只能删 voice_cloning / voice_generation 类型,当前 {voice_type}",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)
    url = f"{BASE_URL}/v1/delete_voice"
    r = requests.post(url, headers=auth_headers(api_key),
                      json={"voice_type": voice_type, "voice_id": voice_id},
                      timeout=60)
    r.raise_for_status()
    check_base_resp(r.json(), "删音色")


# ============================================================
# Async TTS
# ============================================================
def submit_tts_async(
    api_key: str,
    text: str,
    voice_id: str,
    *,
    model: str,
    emotion: str, speed: float, pitch: int, volume: float,
    sample_rate: int, bitrate: int, response_format: str, channel: int,
    language_boost: Optional[str] = None,
    aigc_watermark: bool = False,
) -> dict:
    """POST /v1/t2a_async_v2 — 提交长文本异步合成。

    返回 task_id 等。文件 / file_id 自创建起 9 小时内有效。
    """
    url = f"{BASE_URL}/v1/t2a_async_v2"
    payload: dict[str, Any] = {
        "model": model,
        "text": text,
        "voice_setting": {
            "voice_id": voice_id,
            "speed": speed, "vol": volume, "pitch": pitch, "emotion": emotion,
        },
        "audio_setting": {
            "sample_rate": sample_rate, "bitrate": bitrate,
            "format": response_format, "channel": channel,
        },
    }
    if language_boost:
        payload["language_boost"] = language_boost
    if aigc_watermark:
        payload["aigc_watermark"] = True
    r = requests.post(url, headers=auth_headers(api_key),
                      json=payload, timeout=120)
    r.raise_for_status()
    return check_base_resp(r.json(), "提交异步合成")


def query_tts_async(api_key: str, task_id: int | str) -> dict:
    """GET /v1/query/t2a_async_query_v2?task_id=..."""
    url = f"{BASE_URL}/v1/query/t2a_async_query_v2"
    r = requests.get(url, headers=auth_headers(api_key),
                     params={"task_id": task_id}, timeout=60)
    r.raise_for_status()
    return check_base_resp(r.json(), f"查询异步任务 {task_id}")


def download_file_content(api_key: str, file_id: int | str) -> bytes:
    """GET /v1/files/retrieve_content?file_id=... — 返回原始音频字节

    (文件 9 小时内有效)
    """
    url = f"{BASE_URL}/v1/files/retrieve_content"
    r = requests.get(url, headers=auth_headers(api_key),
                     params={"file_id": file_id}, timeout=300)
    r.raise_for_status()
    return r.content


def run_tts_async(
    api_key: str, *,
    text: str, voice_id: str,
    model: str, emotion: str, speed: float, pitch: int, volume: float,
    sample_rate: int, bitrate: int, response_format: str, channel: int,
    output: Path,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    timeout: float = DEFAULT_POLL_TIMEOUT,
    on_poll: Optional[Callable[[dict, float], None]] = None,
) -> Path:
    """提交 → 轮询 → 下载(完整流程)。"""
    sub = submit_tts_async(
        api_key, text, voice_id,
        model=model, emotion=emotion, speed=speed, pitch=pitch, volume=volume,
        sample_rate=sample_rate, bitrate=bitrate,
        response_format=response_format, channel=channel,
    )
    task_id = sub["task_id"]
    typer.secho(
        f"  ⏳ 已提交异步任务,task_id = {task_id}",
        fg=typer.colors.CYAN,
    )

    deadline = time.monotonic() + timeout
    status = "processing"
    while True:
        q = query_tts_async(api_key, task_id)
        status = (q.get("status") or "processing").lower()
        if on_poll:
            on_poll(q, max(0.0, deadline - time.monotonic()))
        if status in ("success", "failed", "expired"):
            break
        if time.monotonic() >= deadline:
            raise TimeoutError(f"轮询 {timeout:.0f}s 超时,最后状态 = {status}")
        time.sleep(poll_interval)

    if status != "success":
        raise RuntimeError(f"异步合成最终状态 = {status}: {q}")
    file_id = q.get("file_id")
    if not file_id:
        raise RuntimeError(f"异步合成 success 但响应无 file_id: {q}")
    audio = download_file_content(api_key, file_id)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(audio)
    typer.secho(
        f"  ✅ 异步合成完成:{output} ({len(audio)/1024:.1f} KB)",
        fg=typer.colors.GREEN,
    )
    return output


# ============================================================
# File management
# ============================================================
def list_files(api_key: str, purpose: str) -> list[dict]:
    """GET /v1/files/list?purpose=..."""
    url = f"{BASE_URL}/v1/files/list"
    r = requests.get(url, headers=auth_headers(api_key),
                     params={"purpose": purpose}, timeout=60)
    r.raise_for_status()
    j = check_base_resp(r.json(), f"列文件 (purpose={purpose})")
    return j.get("files") or []


def retrieve_file_meta(api_key: str, file_id: int | str) -> dict:
    """GET /v1/files/retrieve?file_id=..."""
    url = f"{BASE_URL}/v1/files/retrieve"
    r = requests.get(url, headers=auth_headers(api_key),
                     params={"file_id": file_id}, timeout=60)
    r.raise_for_status()
    j = check_base_resp(r.json(), f"查文件 {file_id}")
    return j.get("file") or {}


def delete_file(api_key: str, file_id: int | str, purpose: str) -> None:
    """POST /v1/files/delete body={file_id, purpose}"""
    url = f"{BASE_URL}/v1/files/delete"
    r = requests.post(url, headers=auth_headers(api_key),
                      json={"file_id": file_id, "purpose": purpose}, timeout=60)
    r.raise_for_status()
    check_base_resp(r.json(), f"删文件 {file_id}")
