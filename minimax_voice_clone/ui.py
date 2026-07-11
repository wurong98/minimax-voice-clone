"""Rich 渲染 + Confirm。

所有视觉元素的统一入口。 console / Table / Confirm 都集中在这里,避免散落。
"""
from __future__ import annotations

import time
from typing import Any

from rich.console import Console
from rich.prompt import Confirm
from rich.table import Table

console = Console(highlight=False)


# ============================================================
# 确认弹窗
# ============================================================
def confirm_destructive(msg: str, *, force: bool = False) -> bool:
    """删除类操作的二次确认。`--yes` / force=True 时跳过。"""
    if force:
        return True
    return Confirm.ask(f"⚠️  {msg}", default=False)


# ============================================================
# Rich Table 渲染
# ============================================================
def render_voices_table(data: dict[str, Any]) -> None:
    """把 list_voices 返回的 dict 画成 Rich Table。空节不渲染。"""
    sections: list[tuple[str, list[dict]]] = [
        ("🎙  系统音色",     data.get("system_voice") or []),
        ("🎤  快速复刻音色", data.get("voice_cloning") or []),
        ("🪄  文生音色",     data.get("voice_generation") or []),
    ]
    rendered = False
    for title, items in sections:
        if not items:
            continue
        rendered = True
        tbl = Table(title=title, title_justify="left", header_style="bold cyan")
        has_created = "created_time" in items[0]
        tbl.add_column("voice_id", style="green")
        tbl.add_column("voice_name")
        if has_created:
            tbl.add_column("created", style="dim")
        tbl.add_column("description", overflow="fold")
        for it in items:
            desc = " ".join(it.get("description") or []) or "-"
            row: list[str] = [it["voice_id"], it.get("voice_name") or "-"]
            if has_created:
                row.append(it.get("created_time") or "-")
            row.append(desc)
            tbl.add_row(*row)
        console.print(tbl)
    if not rendered:
        console.print(
            "[dim](无匹配音色。克隆/文生音色须先正式合成一次才会出现)[/dim]"
        )


def render_files_table(purpose: str, items: list[dict]) -> None:
    if not items:
        console.print(f"[dim](purpose={purpose} 下还没有文件)[/dim]")
        return
    tbl = Table(
        title=f"📂  purpose={purpose}",
        header_style="bold cyan",
        title_justify="left",
    )
    tbl.add_column("file_id", style="green")
    tbl.add_column("filename")
    tbl.add_column("bytes", justify="right")
    tbl.add_column("created", style="dim")
    for f in items:
        ts = f.get("created_at")
        ts_str = (
            time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
            if isinstance(ts, (int, float))
            else str(ts)
        )
        tbl.add_row(
            str(f.get("file_id")),
            f.get("filename", "-"),
            f"{f.get('bytes', 0)/1024:.1f} KB",
            ts_str or "-",
        )
    console.print(tbl)


def render_file_meta(file_id: int, f: dict) -> None:
    if not f:
        console.print("[dim](文件不存在或已过期)[/dim]")
        return
    tbl = Table(title=f"📄  file_id={file_id}", header_style="bold cyan")
    tbl.add_column("field", style="green")
    tbl.add_column("value")
    for k in ("file_id", "filename", "purpose", "bytes", "created_at"):
        v = f.get(k)
        if k == "bytes" and isinstance(v, (int, float)):
            v = f"{v} ({v/1024:.1f} KB)"
        elif k == "created_at" and isinstance(v, (int, float)):
            v = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(v))
        tbl.add_row(k, str(v) if v is not None else "-")
    console.print(tbl)
