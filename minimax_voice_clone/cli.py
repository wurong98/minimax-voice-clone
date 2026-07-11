"""所有 Typer 命令 + app / sub-app 定义。

只 import config / api / ui —— 不直接 import requests 等。
"""
from __future__ import annotations

import csv
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Optional

import typer
from rich.console import Group
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn, BarColumn, MofNCompleteColumn

from .config import (
    MAX_UPLOAD_BYTES,
    DEFAULT_POLL_INTERVAL, DEFAULT_POLL_TIMEOUT,
    CONFIG_FILE, INTERNAL_DEFAULTS, ALLOWED_EMOTIONS,
    resolve_api_key, validate_voice_id, validate_emotion, validate_model,
    load_config, save_config, update_config, resolve_with_config,
)
from .api import (
    VOICE_TYPES_ALL, VOICE_TYPES_DELETABLE, FILE_PURPOSES,
    normalize_audio_for_upload, upload_audio, clone_voice, tts_synthesize,
    list_voices, delete_voice, voice_design,
    submit_tts_async, query_tts_async, download_file_content, run_tts_async,
    list_files, retrieve_file_meta, delete_file,
)
from .ui import (
    console, confirm_destructive,
    render_voices_table, render_files_table, render_file_meta,
)


# ============================================================
# Typer app + sub-apps
# ============================================================
app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="MiniMax 音色克隆 + 文字转语音 CLI",
)
voices_app = typer.Typer(
    help="管理 voice_id:列音色 / 删音色。",
    no_args_is_help=True,
)
files_app = typer.Typer(
    help="管理已上传的音频文件:列 / 查 / 删 / 下载。",
    no_args_is_help=True,
)
app.add_typer(voices_app, name="voices")
app.add_typer(files_app, name="files")


@app.callback()
def _main_callback(
    ctx: typer.Context,
    show_banner: bool = typer.Option(
        False, "--banner", help="在 stderr 顶部打印 Rich banner",
    ),
) -> None:
    if show_banner:
        console.print(
            Panel.fit(
                "[bold]MiniMax Voice Clone CLI[/bold]\n"
                "上传·克隆·合成·管理 (Rich 驱动)",
                border_style="cyan",
            )
        )


# ============================================================
# Pipeline: run (legacy, 100% 兼容旧版)
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
        ..., "--voice-id", "-v",
        help="自定义音色ID,8~256 字符,首字符英文,末位不能是 - 或 _,仅允许 [A-Za-z0-9_-]",
    ),
    text: str = typer.Option(..., "--text", "-t", help="要转成语音的文字"),
    output: Path = typer.Option(
        Path("output_speech.mp3"), "--output", "-o",
        help="合成结果保存路径",
    ),
    api_key: Optional[str] = typer.Option(
        None, "--api-key", "-k",
        help="MiniMax API_KEY (也可设环境变量 MINIMAX_API_KEY)",
        envvar="MINIMAX_API_KEY",
    ),
    skip_clone: bool = typer.Option(
        False, "--skip-clone", "-s",
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
        128000, "--bitrate", "-b", help="比特率 (bps)",
    ),
    channel: int = typer.Option(
        1, "--channel", "-c", help="声道数: 1 单声道 / 2 双声道",
    ),
):
    """一条命令跑完:上传 -> 克隆 -> 合成 (与旧版本完全兼容)"""
    key = resolve_api_key(api_key)
    validate_voice_id(voice_id)
    validate_emotion(emotion)

    if not skip_clone:
        size = audio_path.stat().st_size
        if size > MAX_UPLOAD_BYTES:
            typer.secho(
                f"❌ 参考音频 {size/1024/1024:.1f}MB 超过 20MB 限制",
                fg=typer.colors.RED,
            )
            raise typer.Exit(code=1)

    if not skip_clone:
        typer.secho("\n[1/3] 上传参考音频...", bold=True)
        upload_path = normalize_audio_for_upload(audio_path)
        file_id = upload_audio(key, upload_path)

        typer.secho("\n[2/3] 复刻音色...", bold=True)
        clone_voice(key, file_id, voice_id)
    else:
        typer.secho(
            f"[skip-clone] 跳过上传/克隆,直接使用 voice_id = {voice_id}",
            fg=typer.colors.CYAN,
        )

    step = "[3/3]" if not skip_clone else "[1/1]"
    typer.secho(f"\n{step} 用克隆音色合成文字:「{text}」", bold=True)
    tts_synthesize(
        key, voice_id, text, output,
        model=model, emotion=emotion, speed=speed, pitch=pitch, volume=volume,
        response_format=response_format, sample_rate=sample_rate,
        bitrate=bitrate, channel=channel,
    )
    typer.secho(
        f"\n🎉 全流程跑通!去听一下 {output} 吧~",
        fg=typer.colors.MAGENTA, bold=True,
    )


# ============================================================
# 单一子命令: tts / clone / design
# ============================================================
@app.command("tts")
def tts_sub(
    text: str = typer.Option(..., "--text", "-t", help="要合成的文字"),
    voice_id: Optional[str] = typer.Option(
        None, "--voice-id", "-v",
        help="音色 ID。省略时从 ~/.config/clone-voice/config.json 读",
    ),
    output: Path = typer.Option(
        Path("output_speech.mp3"), "--output", "-o",
        help="合成结果保存路径",
    ),
    model: Optional[str] = typer.Option(None, "--model", "-m"),
    emotion: Optional[str] = typer.Option(None, "--emotion", "-e"),
    speed: Optional[float] = typer.Option(None, "--speed", min=0.5, max=2.0),
    pitch: Optional[int] = typer.Option(None, "--pitch", min=-12, max=12),
    volume: Optional[float] = typer.Option(None, "--volume", min=0.0, max=10.0),
    response_format: Optional[str] = typer.Option(None, "--format", "-f"),
    sample_rate: Optional[int] = typer.Option(None, "--sample-rate", "-r"),
    bitrate: Optional[int] = typer.Option(None, "--bitrate", "-b"),
    channel: Optional[int] = typer.Option(None, "--channel", "-c"),
    language_boost: Optional[str] = typer.Option(None, "--lang"),
    api_key: Optional[str] = typer.Option(
        None, "--api-key", "-k", envvar="MINIMAX_API_KEY",
    ),
):
    """只做同步 TTS。省略的参数从本地缓存读,再 fallback 到内置默认。"""
    key = resolve_api_key(api_key)
    vid, _ = resolve_with_config(voice_id, "voice_id")
    if not vid:
        typer.secho(
            "❌ 没有 voice_id。请 --voice-id,或先 `config set voice_id=YourVoice`",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)
    validate_voice_id(vid)

    model_v, _ = resolve_with_config(model, "model");           validate_model(model_v)
    emo_v,    _ = resolve_with_config(emotion, "emotion");      validate_emotion(emo_v)
    spd_v,    _ = resolve_with_config(speed, "speed")
    ptc_v,    _ = resolve_with_config(pitch, "pitch")
    vol_v,    _ = resolve_with_config(volume, "volume")
    fmt_v,    _ = resolve_with_config(response_format, "response_format")
    sr_v,     _ = resolve_with_config(sample_rate, "sample_rate")
    br_v,     _ = resolve_with_config(bitrate, "bitrate")
    ch_v,     _ = resolve_with_config(channel, "channel")

    tts_synthesize(
        key, vid, text, output,
        model=model_v, emotion=emo_v, speed=spd_v, pitch=ptc_v, volume=vol_v,
        response_format=fmt_v, sample_rate=sr_v, bitrate=br_v, channel=ch_v,
        language_boost=language_boost,
    )
    update_config({
        "voice_id": vid, "model": model_v, "emotion": emo_v,
        "speed": spd_v, "pitch": ptc_v, "volume": vol_v,
        "response_format": fmt_v, "sample_rate": sr_v,
        "bitrate": br_v, "channel": ch_v,
    })


@app.command("clone")
def clone_sub(
    audio_path: Path = typer.Argument(
        ..., exists=True, readable=True,
        help="本地参考音频 (mp3/m4a/wav/flac, <20MB, 10秒~5分钟;FLAC 自动转 WAV)",
    ),
    voice_id: str = typer.Option(
        ..., "--voice-id", "-v",
        help="自定义音色ID,8~256 字符",
    ),
    model: str = typer.Option(
        "speech-2.8-hd", "--model", "-m",
        help="试听合成模型",
    ),
    preview_text: Optional[str] = typer.Option(
        None, "--preview-text", "-t",
        help="试听文本;不传则后端默认用一句英文",
    ),
    accuracy: float = typer.Option(0.7, "--accuracy", min=0.0, max=1.0),
    noise_reduction: bool = typer.Option(False, "--noise-reduction"),
    volume_norm: bool = typer.Option(False, "--volume-normalization"),
    aigc_watermark: bool = typer.Option(False, "--watermark"),
    api_key: Optional[str] = typer.Option(
        None, "--api-key", "-k", envvar="MINIMAX_API_KEY",
    ),
):
    """只做上传 + 克隆。可选 --preview-text 让后端生成一份试听音频。"""
    key = resolve_api_key(api_key)
    validate_voice_id(voice_id)
    validate_model(model)

    size = audio_path.stat().st_size
    if size > MAX_UPLOAD_BYTES:
        typer.secho(f"❌ 参考音频 {size/1024/1024:.1f}MB 超过 20MB 限制", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    upload_path = normalize_audio_for_upload(audio_path)
    file_id = upload_audio(key, upload_path)
    clone_voice(
        key, file_id, voice_id,
        model=model,
        text=preview_text or "This is a test sentence for voice cloning.",
        accuracy=accuracy,
        need_noise_reduction=noise_reduction,
        need_volume_normalization=volume_norm,
        aigc_watermark=aigc_watermark,
    )
    update_config({"voice_id": voice_id, "model": model})


@app.command("design")
def design_sub(
    prompt: str = typer.Option(
        ..., "--prompt", "-p", help="音色描述",
    ),
    preview_text: str = typer.Option(
        ..., "--preview-text", "-t", help="试听文本,1~500 字符",
    ),
    voice_id: Optional[str] = typer.Option(
        None, "--voice-id", "-v", help="自定义 voice_id;省略则自动生成",
    ),
    output: Path = typer.Option(
        Path("design_preview.mp3"), "--output", "-o", help="试听音频保存路径",
    ),
    api_key: Optional[str] = typer.Option(
        None, "--api-key", "-k", envvar="MINIMAX_API_KEY",
    ),
):
    """用文字描述生成音色(/v1/voice_design)。会下载试听音频到本地。"""
    key = resolve_api_key(api_key)
    if voice_id is not None:
        validate_voice_id(voice_id)

    j = voice_design(key, prompt, preview_text, voice_id=voice_id)
    new_voice_id = j.get("voice_id", "")
    trial_hex = (j.get("trial_audio") or "").strip()
    if not new_voice_id:
        raise RuntimeError(f"音色设计成功但响应无 voice_id:{j}")
    if trial_hex:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(bytes.fromhex(trial_hex))
        typer.secho(
            f"  🎧 试听音频已存:{output} ({len(trial_hex)//2/1024:.1f} KB)",
            fg=typer.colors.CYAN,
        )
    typer.secho(f"  ✅ 音色已生成: voice_id = {new_voice_id}", fg=typer.colors.GREEN)
    update_config({"voice_id": new_voice_id})


# ============================================================
# 异步合成
# ============================================================
@app.command("tts-async")
def tts_async_sub(
    text: Optional[str] = typer.Option(
        None, "--text", "-t",
        help="要合成的长文本(>3000 字符推荐用异步)",
    ),
    output: Path = typer.Option(
        Path("output_speech.mp3"), "--output", "-o",
    ),
    voice_id: Optional[str] = typer.Option(None, "--voice-id", "-v"),
    model: Optional[str] = typer.Option(None, "--model", "-m"),
    emotion: Optional[str] = typer.Option(None, "--emotion", "-e"),
    speed: Optional[float] = typer.Option(None, "--speed", min=0.5, max=2.0),
    pitch: Optional[int] = typer.Option(None, "--pitch", min=-12, max=12),
    volume: Optional[float] = typer.Option(None, "--volume", min=0.0, max=10.0),
    response_format: Optional[str] = typer.Option(None, "--format", "-f"),
    sample_rate: Optional[int] = typer.Option(None, "--sample-rate", "-r"),
    bitrate: Optional[int] = typer.Option(None, "--bitrate", "-b"),
    channel: Optional[int] = typer.Option(None, "--channel", "-c"),
    language_boost: Optional[str] = typer.Option(None, "--lang"),
    poll_interval: float = typer.Option(
        DEFAULT_POLL_INTERVAL, "--poll-interval", help="轮询间隔(秒)",
    ),
    timeout: float = typer.Option(
        DEFAULT_POLL_TIMEOUT, "--timeout", help="最长等待(秒)",
    ),
    task_id: Optional[int] = typer.Option(
        None, "--task-id", help="只查询/下载已有任务",
    ),
    api_key: Optional[str] = typer.Option(
        None, "--api-key", "-k", envvar="MINIMAX_API_KEY",
    ),
):
    """异步合成长文本(>3000 字符)。自动轮询 + 下载产物。可续查已有 task-id。"""
    key = resolve_api_key(api_key)

    # 模式 B: 只查询 / 下载已有任务
    if task_id is not None:
        q = query_tts_async(key, task_id)
        status = (q.get("status") or "?").lower()
        file_id = q.get("file_id")
        typer.secho(f"  task_id={task_id} status={status} file_id={file_id}", fg=typer.colors.CYAN)
        if status == "success" and file_id and output:
            audio = download_file_content(key, file_id)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(audio)
            typer.secho(
                f"  ✅ 已下载到 {output} ({len(audio)/1024:.1f} KB)",
                fg=typer.colors.GREEN,
            )
        elif status != "success":
            raise typer.Exit(code=1)
        return

    # 模式 A: 完整提交 + 轮询 + 下载
    if not text:
        typer.secho("❌ 没传 --text。提供文本,或 --task-id 续查。", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    vid, _ = resolve_with_config(voice_id, "voice_id")
    if not vid:
        typer.secho("❌ 没有 voice_id。请 --voice-id,或 config set voice_id=...", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    validate_voice_id(vid)
    model_v, _ = resolve_with_config(model, "model");        validate_model(model_v)
    emo_v,    _ = resolve_with_config(emotion, "emotion");   validate_emotion(emo_v)
    spd_v,    _ = resolve_with_config(speed, "speed")
    ptc_v,    _ = resolve_with_config(pitch, "pitch")
    vol_v,    _ = resolve_with_config(volume, "volume")
    fmt_v,    _ = resolve_with_config(response_format, "response_format")
    sr_v,     _ = resolve_with_config(sample_rate, "sample_rate")
    br_v,     _ = resolve_with_config(bitrate, "bitrate")
    ch_v,     _ = resolve_with_config(channel, "channel")

    with Progress(
        SpinnerColumn(),
        TextColumn("[cyan]异步合成中[/cyan]"),
        TextColumn("{task.fields[status]}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("wait", status="提交任务…", total=None)

        def _on_poll(q: dict, remaining_s: float) -> None:
            st = (q.get("status") or "?").lower()
            fid = q.get("file_id")
            label = (
                f"status={st}" + (f" file_id={fid}" if fid else "")
                + f"  (剩余 {remaining_s:.0f}s)"
            )
            progress.update(task, status=label)

        run_tts_async(
            key, text=text, voice_id=vid,
            model=model_v, emotion=emo_v, speed=spd_v, pitch=ptc_v, volume=vol_v,
            sample_rate=sr_v, bitrate=br_v,
            response_format=fmt_v, channel=ch_v,
            language_boost=language_boost,
            output=output, poll_interval=poll_interval, timeout=timeout,
            on_poll=_on_poll,
        )
    update_config({
        "voice_id": vid, "model": model_v, "emotion": emo_v,
        "speed": spd_v, "pitch": ptc_v, "volume": vol_v,
        "response_format": fmt_v, "sample_rate": sr_v,
        "bitrate": br_v, "channel": ch_v,
    })


# ============================================================
# Voices sub-app
# ============================================================
@voices_app.command("list")
def voices_list(
    voice_type: str = typer.Option(
        "all", "--type", "-t",
        help="system / voice_cloning / voice_generation / all",
    ),
    api_key: Optional[str] = typer.Option(
        None, "--api-key", "-k", envvar="MINIMAX_API_KEY",
    ),
):
    """列出当前账号下的 voice_id"""
    key = resolve_api_key(api_key)
    if voice_type not in VOICE_TYPES_ALL:
        typer.secho(
            f"❌ --type 必须 ∈ {list(VOICE_TYPES_ALL)}", fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)
    data = list_voices(key, voice_type)
    render_voices_table(data)


@voices_app.command("delete")
def voices_delete(
    voice_id: str = typer.Argument(..., help="要删的 voice_id"),
    voice_type: str = typer.Option(
        "voice_cloning", "--type", "-t",
        help="voice_cloning=克隆 / voice_generation=文生",
    ),
    api_key: Optional[str] = typer.Option(
        None, "--api-key", "-k", envvar="MINIMAX_API_KEY",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="跳过交互式确认"),
):
    """删除一个 voice_id(系统音色不可删)"""
    key = resolve_api_key(api_key)
    if voice_type not in VOICE_TYPES_DELETABLE:
        typer.secho(
            f"❌ delete 只支持 {list(VOICE_TYPES_DELETABLE)}",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)
    if not confirm_destructive(
        f"确认删除 voice_type={voice_type} voice_id={voice_id}?不可恢复!",
        force=yes,
    ):
        typer.secho("已取消,啥也没干。", fg=typer.colors.YELLOW)
        raise typer.Exit(code=0)
    delete_voice(key, voice_type, voice_id)
    typer.secho(f"  ✅ 已删除 {voice_id}", fg=typer.colors.GREEN)


# ============================================================
# Files sub-app
# ============================================================
@files_app.command("list")
def files_list(
    purpose: str = typer.Option(
        "voice_clone", "--purpose", "-p",
        help="voice_clone | prompt_audio | t2a_async_input",
    ),
    api_key: Optional[str] = typer.Option(
        None, "--api-key", "-k", envvar="MINIMAX_API_KEY",
    ),
):
    """列出已上传的文件"""
    key = resolve_api_key(api_key)
    if purpose not in FILE_PURPOSES:
        typer.secho(f"❌ --purpose 必须 ∈ {FILE_PURPOSES}", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    items = list_files(key, purpose)
    render_files_table(purpose, items)


@files_app.command("retrieve")
def files_retrieve(
    file_id: int = typer.Argument(..., help="文件 ID"),
    api_key: Optional[str] = typer.Option(
        None, "--api-key", "-k", envvar="MINIMAX_API_KEY",
    ),
):
    """查单个文件的元信息"""
    key = resolve_api_key(api_key)
    f = retrieve_file_meta(key, file_id)
    render_file_meta(file_id, f)


@files_app.command("delete")
def files_delete(
    file_id: int = typer.Argument(..., help="文件 ID"),
    purpose: str = typer.Option(
        "voice_clone", "--purpose", "-p",
        help="文件分类(只有 list 能查的那三类可以删)",
    ),
    api_key: Optional[str] = typer.Option(
        None, "--api-key", "-k", envvar="MINIMAX_API_KEY",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="跳过交互式确认"),
):
    """删除一个已上传的文件"""
    key = resolve_api_key(api_key)
    if purpose not in FILE_PURPOSES:
        typer.secho(f"❌ --purpose 必须 ∈ {FILE_PURPOSES}", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    if not confirm_destructive(
        f"确认删除 file_id={file_id} (purpose={purpose})?不可恢复!",
        force=yes,
    ):
        typer.secho("已取消。", fg=typer.colors.YELLOW)
        raise typer.Exit(code=0)
    delete_file(key, file_id, purpose)
    typer.secho(f"  ✅ 已删除 file_id={file_id}", fg=typer.colors.GREEN)


@files_app.command("download")
def files_download(
    file_id: int = typer.Argument(..., help="文件 ID"),
    output: Path = typer.Argument(..., help="保存到本地的路径"),
    api_key: Optional[str] = typer.Option(
        None, "--api-key", "-k", envvar="MINIMAX_API_KEY",
    ),
):
    """下载文件原始内容(异步产物 file_id 9 小时内有效,过期后下载会失败)"""
    key = resolve_api_key(api_key)
    audio = download_file_content(key, file_id)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(audio)
    typer.secho(
        f"  ✅ 已下载:{output} ({len(audio)/1024:.1f} KB)",
        fg=typer.colors.GREEN,
    )


# ============================================================
# 批量并发合成 (CSV / JSON → tts_synthesize)
# ============================================================
def _load_batch_items(path: Path) -> list[dict[str, Any]]:
    """读 CSV 或 JSON 的任务列表。

    CSV 表头至少 voice_id,text,output;其余字段(model / emotion / speed / ...)可选。
    JSON 是 list of dict。
    """
    if not path.exists():
        raise FileNotFoundError(f"--input {path} 不存在")
    suf = path.suffix.lower()
    if suf == ".json":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise ValueError("JSON 必须是 list of dict")
        return data
    if suf == ".csv":
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            items = list(reader)
        return items
    raise ValueError(f"暂只支持 .csv / .json, 收到 {suf}")


@app.command("batch")
def batch_sub(
    input: Path = typer.Option(
        ..., "--input", "-i",
        help="CSV 或 JSON 文件路径",
        exists=True, readable=True,
    ),
    workers: int = typer.Option(
        4, "--workers", "-w", min=1, max=32,
        help="并发数(默认 4)",
    ),
    continue_on_error: bool = typer.Option(
        True, "--continue-on-error/--fail-fast",
        help="单条失败时是否继续(默认继续)",
    ),
    api_key: Optional[str] = typer.Option(
        None, "--api-key", "-k", envvar="MINIMAX_API_KEY",
    ),
):
    """批量并发合成:从 CSV / JSON 读多条任务,用 ThreadPoolExecutor 并行跑 tts。

    CSV 表头至少:`voice_id,text,output`;可选字段:`model, emotion, speed, pitch,
    volume, response_format, sample_rate, bitrate, channel, language_boost`。

    JSON 是 list of dict,字段同上。

    每条失败会写到 `<output>.err.txt`,进度条实时显示。
    """
    key = resolve_api_key(api_key)
    raw_items = _load_batch_items(input)

    # 校验 + 标准化
    jobs: list[dict[str, Any]] = []
    bad: list[tuple[int, str]] = []
    cfg = load_config()
    for idx, it in enumerate(raw_items):
        if "voice_id" not in it or not it["voice_id"]:
            bad.append((idx, "缺少 voice_id")); continue
        if "text" not in it or not it["text"]:
            bad.append((idx, "缺少 text")); continue
        if "output" not in it or not it["output"]:
            bad.append((idx, "缺少 output")); continue

        def _get(k: str) -> Any:
            v = it.get(k)
            if v is None or v == "":
                v = cfg.get(k)
            if v is None or v == "":
                v = INTERNAL_DEFAULTS.get(k)
            return v

        model_v = str(_get("model") or "speech-2.8-hd")
        if model_v not in ALLOWED_EMOTIONS and model_v not in (
            "speech-2.8-hd","speech-2.8-turbo","speech-2.6-hd",
            "speech-2.6-turbo","speech-02-hd","speech-02-turbo",
            "speech-01-hd","speech-01-turbo",
        ):
            bad.append((idx, f"非法 model: {model_v}")); continue
        emo_v = str(_get("emotion") or "neutral")
        if emo_v not in ALLOWED_EMOTIONS:
            bad.append((idx, f"非法 emotion: {emo_v}")); continue

        try:
            jobs.append({
                "voice_id": str(it["voice_id"]),
                "text":     str(it["text"]),
                "output":   Path(it["output"]),
                "model":    model_v,
                "emotion":  emo_v,
                "speed":    float(_get("speed") or 1.0),
                "pitch":    int(_get("pitch") or 0),
                "volume":   float(_get("volume") or 1.0),
                "response_format": str(_get("response_format") or "mp3"),
                "sample_rate": int(_get("sample_rate") or 32000),
                "bitrate":  int(_get("bitrate") or 128000),
                "channel":  int(_get("channel") or 1),
                "language_boost": it.get("language_boost"),
            })
        except (TypeError, ValueError) as e:
            bad.append((idx, f"参数解析失败: {e}"))

    if bad:
        typer.secho("❌ 以下任务有问题:", fg=typer.colors.RED)
        for idx, msg in bad:
            typer.secho(f"   [{idx}] {msg}", fg=typer.colors.RED)
        if not continue_on_error:
            raise typer.Exit(code=1)

    if not jobs:
        typer.secho("⚠️  没有合法任务,啥也不干。", fg=typer.colors.YELLOW)
        raise typer.Exit(code=0)

    typer.secho(
        f"  🚀 启动批量:共 {len(jobs)} 条,workers={workers}",
        fg=typer.colors.CYAN,
    )

    ok, fail = 0, 0
    with Progress(
        TextColumn("[cyan]批量合成[/cyan]"),
        BarColumn(),
        MofNCompleteColumn(),
        TextColumn("{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task_id = progress.add_task("tts", total=len(jobs))

        def _one(job: dict[str, Any]) -> tuple[str, str]:
            """返回 (status, info):'ok'/<output> 或 'err'/<msg>"""
            try:
                tts_synthesize(
                    key,
                    voice_id=job["voice_id"],
                    text=job["text"], out_path=job["output"],
                    model=job["model"], emotion=job["emotion"],
                    speed=job["speed"], pitch=job["pitch"], volume=job["volume"],
                    response_format=job["response_format"],
                    sample_rate=job["sample_rate"], bitrate=job["bitrate"],
                    channel=job["channel"],
                    language_boost=job["language_boost"],
                    quiet=True,
                )
                return ("ok", str(job["output"]))
            except Exception as e:
                return ("err", f"{job['output']}: {e}")

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_one, j): j for j in jobs}
            for fut in as_completed(futures):
                status, info = fut.result()
                if status == "ok":
                    ok += 1
                else:
                    fail += 1
                    err_path = Path(str(futures[fut]["output"]) + ".err.txt")
                    try:
                        err_path.parent.mkdir(parents=True, exist_ok=True)
                        err_path.write_text(info + "\n", encoding="utf-8")
                        typer.secho(f"  ❌ {info} → {err_path}", fg=typer.colors.RED)
                    except OSError:
                        pass
                progress.update(task_id, advance=1)

    typer.secho(
        f"\n  📊 完成:成功 {ok}, 失败 {fail} (失败时写到 <output>.err.txt)",
        fg=typer.colors.GREEN if fail == 0 else typer.colors.YELLOW,
    )
    if fail and not continue_on_error:
        raise typer.Exit(code=1)


# ============================================================
# 本地 config 管理 (~/.config/clone-voice/config.json)
# ============================================================
@app.command("config")
def config_sub(
    action: str = typer.Argument(
        ...,
        help="show | clear | set",
    ),
    pairs: Optional[list[str]] = typer.Argument(
        None,
        help="action=set 时传 key=value 对,例如 voice_id=WurongVoice01 model=speech-2.8-hd",
    ),
):
    """查看 / 清空 / 设置 本地默认参数缓存(供 tts / tts-async 跳过显式 flag 时用)"""
    if action == "show":
        cfg = load_config()
        from rich.table import Table as _Tbl
        tbl = _Tbl(
            title=f"⚙️   本地默认参数 ({CONFIG_FILE})",
            header_style="bold cyan",
            title_justify="left",
        )
        tbl.add_column("key", style="green")
        tbl.add_column("value", overflow="fold")
        tbl.add_column("source", style="dim")
        for k in sorted(INTERNAL_DEFAULTS.keys()):
            if k in cfg:
                tbl.add_row(k, str(cfg[k]), "config")
            else:
                tbl.add_row(k, str(INTERNAL_DEFAULTS[k]), "internal default")
        console.print(tbl)

    elif action == "clear":
        if CONFIG_FILE.exists():
            if not confirm_destructive(
                f"确认删除本地配置文件 {CONFIG_FILE}?", force=False,
            ):
                typer.secho("已取消。", fg=typer.colors.YELLOW)
                raise typer.Exit(code=0)
            CONFIG_FILE.unlink()
            typer.secho(f"  ✅ 已删除 {CONFIG_FILE}", fg=typer.colors.GREEN)
        else:
            typer.secho("  (没有 config 文件,啥也没干)", fg=typer.colors.CYAN)

    elif action == "set":
        if not pairs:
            typer.secho(
                "❌ action=set 需要至少一对 key=value,例:`config set voice_id=WurongVoice01`",
                fg=typer.colors.RED,
            )
            raise typer.Exit(code=1)
        updates: dict = {}
        bad: list[str] = []
        for p in pairs:
            if "=" not in p:
                bad.append(p)
                continue
            k, v = p.split("=", 1)
            if k not in INTERNAL_DEFAULTS:
                bad.append(p)
                continue
            updates[k] = v
        if bad:
            typer.secho(
                f"❌ 以下参数不合法:{bad}\n   允许:{sorted(INTERNAL_DEFAULTS.keys())}",
                fg=typer.colors.RED,
            )
            raise typer.Exit(code=1)
        update_config(updates)
        typer.secho(
            f"  ✅ 已写入 {len(updates)} 项到 {CONFIG_FILE}",
            fg=typer.colors.GREEN,
        )

    else:
        typer.secho(
            f"❌ 不支持的 action:{action}(可选: show / clear / set)",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)
