#!/home/wurong/miniconda3/bin/python3
"""
MiniMax 音色克隆 + 文字转语音 CLI
=================================
流程:
  1) 上传你的音频文件 -> 拿到 file_id
  2) 调用 /v1/voice_clone 用 file_id 克隆音色 -> 拿到 voice_id
  3) 用 voice_id 调 /v1/audio/speech 把任意文字转成 mp3

使用前请先:
  - 完成 MiniMax 平台个人/企业认证
  - 在 https://platform.minimaxi.com/user-center/basic-information/interface-key 拿到 API_KEY
  - 准备好一段 10秒~5分钟 的参考音频 (mp3/m4a/wav/flac, <20MB)

环境变量:
  MINIMAX_API_KEY    也可以把 API_KEY 放到环境变量里,就不用每次 --api-key 了

示例:
  # 完整流程:上传 -> 克隆 -> 合成
  python minimax_voice_clone.py my_voice.wav \
      --voice-id MyCustomVoice001 \
      --text "你好,这是克隆的声音" \
      --api-key sk-xxx

  # 音色已经克隆过,只想换一段文字重新合成
  python minimax_voice_clone.py my_voice.wav \
      --voice-id MyCustomVoice001 \
      --text "第二句话" \
      --skip-clone
"""

from __future__ import annotations

import mimetypes
import os
import re
from pathlib import Path
from typing import Optional

import requests
import typer

# ============================================================
# 常量 —— 一般不用动
# ============================================================
BASE_URL = "https://api.minimaxi.com"

ALLOWED_EMOTIONS = {
    "happy", "sad", "angry", "fearful",
    "disgusted", "surprised", "neutral", "fluent",
}

# voice_id 规则:首字符字母,后续只能字母/数字/-/_,长度 8~256,末位不能是 - 或 _
_VOICE_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{6,254}[A-Za-z0-9]$")
MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20MB

# ============================================================
# Typer app
# ============================================================
app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="MiniMax 音色克隆 + 文字转语音 CLI",
)


def _resolve_api_key(api_key: Optional[str]) -> str:
    """优先用 --api-key 传进来的,其次用环境变量 MINIMAX_API_KEY"""
    key = api_key or os.getenv("MINIMAX_API_KEY")
    if not key:
        typer.secho(
            "❌ 找不到 API_KEY。请用 --api-key 传入,或在环境变量里设置 MINIMAX_API_KEY",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)
    return key


def _validate_voice_id(voice_id: str) -> None:
    """voice_id 规则:8~256 字符,首字符英文,末位不能是 - 或 _,其余仅允许 [A-Za-z0-9_-]"""
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


# ============================================================
# API 调用函数
# ============================================================
def upload_audio(api_key: str, audio_path: Path) -> str:
    """上传音频文件,返回 file_id"""
    url = f"{BASE_URL}/v1/files/upload"
    headers = {"Authorization": f"Bearer {api_key}"}
    # 按扩展名推断 MIME,默认 audio/mpeg
    mime, _ = mimetypes.guess_type(audio_path.name)
    mime = mime or "audio/mpeg"
    with open(audio_path, "rb") as f:
        files = {"file": (audio_path.name, f, mime)}
        data = {"purpose": "voice_clone"}
        r = requests.post(url, headers=headers, files=files, data=data, timeout=120)
    r.raise_for_status()
    j = r.json()
    if j.get("base_resp", {}).get("status_code") != 0:
        raise RuntimeError(f"上传失败: {j}")
    file_id = j["file"]["file_id"]
    typer.secho(
        f"  ✅ 上传成功 ({mime}), file_id = {file_id}",
        fg=typer.colors.GREEN,
    )
    return file_id


# MiniMax 上传 voice_clone 用途只接受 mp3 / m4a / wav,FLAC 会被拒绝 (status_code 2013)
# 如果用户给的是 FLAC,自动用 ffmpeg 转一份 WAV(pcm_s16le,保持原采样率 / 通道数)
SUPPORTED_UPLOAD_EXTS = {".mp3", ".m4a", ".wav"}


def normalize_audio_for_upload(audio_path: Path) -> Path:
    """若文件不在 MiniMax 上传支持格式内,临时转一份 WAV,返回新路径。

    原文件不会被改动。
    """
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


def clone_voice(api_key: str, file_id: str, voice_id: str) -> str:
    """调用 voice_clone 接口复刻音色"""
    url = f"{BASE_URL}/v1/voice_clone"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "file_id": int(file_id),  # 接口要求 int64
        "voice_id": voice_id,
        "model": "speech-2.8-hd",
        "text": "This is a test sentence for voice cloning.",
        "accuracy": 0.7,
        "need_noise_reduction": False,
        "need_volume_normalization": False,
        "aigc_watermark": False,
    }
    r = requests.post(url, headers=headers, json=payload, timeout=300)
    r.raise_for_status()
    j = r.json()
    if j.get("base_resp", {}).get("status_code") != 0:
        raise RuntimeError(f"复刻失败: {j}")
    typer.secho(f"  ✅ 音色复刻成功, voice_id = {voice_id}", fg=typer.colors.GREEN)
    typer.secho(
        "  ⏰ 注意: 该音色 7 天内必须正式合成调用一次,否则会被自动删除",
        fg=typer.colors.YELLOW,
    )
    return voice_id


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
) -> Path:
    """用复刻出来的 voice_id 把文字转成 mp3 (T2A v2 接口)

    端点: POST /v1/t2a_v2
    响应: data.audio 是 hex 编码的音频字节
    """
    url = f"{BASE_URL}/v1/t2a_v2"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
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
    r = requests.post(url, headers=headers, json=payload, timeout=300)
    r.raise_for_status()
    j = r.json()
    if j.get("base_resp", {}).get("status_code") != 0:
        raise RuntimeError(f"合成失败: {j}")
    data = j.get("data") or {}
    audio_hex = data.get("audio")
    if not audio_hex:
        raise RuntimeError(f"合成响应无 data.audio: {j}")
    out_path.write_bytes(bytes.fromhex(audio_hex))
    extra = j.get("extra_info", {})
    size_kb = extra.get("audio_size", len(audio_hex) // 2) / 1024
    length_s = extra.get("audio_length", 0) / 1000
    typer.secho(
        f"  ✅ 合成完成:{out_path} "
        f"({size_kb:.1f} KB,{length_s:.2f}s, "
        f"{extra.get('audio_format',response_format)} "
        f"{extra.get('audio_sample_rate',sample_rate)}Hz)",
        fg=typer.colors.GREEN,
    )
    return out_path


# ============================================================
# CLI 命令
# ============================================================
@app.command()
def run(
    audio_path: Path = typer.Argument(
        ...,
        help="本地参考音频路径 (mp3 / m4a / wav / flac, <20MB, 10秒~5分钟)",
        exists=True,
        readable=True,
    ),
    voice_id: str = typer.Option(
        ...,
        "--voice-id", "-v",
        help="自定义音色ID,8~256 字符,首字符英文,末位不能是 - 或 _,仅允许 [A-Za-z0-9_-]",
    ),
    text: str = typer.Option(
        ...,
        "--text", "-t",
        help="要转成语音的文字",
    ),
    output: Path = typer.Option(
        Path("output_speech.mp3"),
        "--output", "-o",
        help="合成结果保存路径",
    ),
    api_key: Optional[str] = typer.Option(
        None,
        "--api-key", "-k",
        help="MiniMax API_KEY (也可设环境变量 MINIMAX_API_KEY)",
        envvar="MINIMAX_API_KEY",
    ),
    skip_clone: bool = typer.Option(
        False,
        "--skip-clone", "-s",
        help="跳过上传和克隆,直接用 --voice-id 合成 (音色必须已经克隆过)",
    ),
    model: str = typer.Option(
        "speech-2.8-hd", "--model", "-m", help="合成模型",
    ),
    emotion: str = typer.Option(
        "neutral", "--emotion", "-e",
        help="情绪: happy / sad / angry / fearful / disgusted / surprised / neutral / fluent",
    ),
    speed: float = typer.Option(1.0, "--speed", help="语速,0.5 ~ 2.0", min=0.5, max=2.0),
    pitch: int = typer.Option(0, "--pitch", help="音调,-12 ~ 12", min=-12, max=12),
    volume: float = typer.Option(1.0, "--volume", help="音量,0 ~ 10", min=0.0, max=10.0),
    response_format: str = typer.Option(
        "mp3", "--format", "-f", help="输出格式: mp3 / wav / flac / pcm",
    ),
    sample_rate: int = typer.Option(
        32000, "--sample-rate", "-r", help="采样率 (Hz)",
    ),
    bitrate: int = typer.Option(
        128000, "--bitrate", "-b", help="比特率 (bps),如 64000/128000/256000",
    ),
    channel: int = typer.Option(
        1, "--channel", "-c", help="声道数: 1 单声道 / 2 双声道",
    ),
):
    """一条命令跑完:上传 -> 克隆 -> 合成"""
    key = _resolve_api_key(api_key)
    _validate_voice_id(voice_id)

    if emotion not in ALLOWED_EMOTIONS:
        typer.secho(
            f"❌ --emotion 取值非法,允许: {sorted(ALLOWED_EMOTIONS)}",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)

    if not skip_clone:
        size = audio_path.stat().st_size
        if size > MAX_UPLOAD_BYTES:
            typer.secho(
                f"❌ 参考音频 {size/1024/1024:.1f}MB 超过 20MB 限制",
                fg=typer.colors.RED,
            )
            raise typer.Exit(code=1)

    # 1) 上传 + 克隆
    if not skip_clone:
        typer.secho("\n[1/3] 上传参考音频...", bold=True)
        # FLAC 等不支持的格式,先转 WAV(其它情况原样返回)
        upload_path = normalize_audio_for_upload(audio_path)
        file_id = upload_audio(key, upload_path)

        typer.secho("\n[2/3] 复刻音色...", bold=True)
        clone_voice(key, file_id, voice_id)
    else:
        typer.secho(
            f"[skip-clone] 跳过上传/克隆,直接使用 voice_id = {voice_id}",
            fg=typer.colors.CYAN,
        )

    # 2) 合成
    step = "[3/3]" if not skip_clone else "[1/1]"
    typer.secho(f"\n{step} 用克隆音色合成文字:「{text}」", bold=True)
    tts_synthesize(
        key, voice_id, text, output,
        model=model,
        emotion=emotion,
        speed=speed,
        pitch=pitch,
        volume=volume,
        response_format=response_format,
        sample_rate=sample_rate,
        bitrate=bitrate,
        channel=channel,
    )

    typer.secho(
        f"\n🎉 全流程跑通!去听一下 {output} 吧~",
        fg=typer.colors.MAGENTA, bold=True,
    )


if __name__ == "__main__":
    app()
