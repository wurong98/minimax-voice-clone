"""MiniMax 音色克隆 + 文字转语音 CLI(包)。

直接 import app:
    from minimax_voice_clone import app
    app()

或者通过入口脚本 / `python -m minimax_voice_clone`。
"""

from .cli import app

__all__ = ["app"]
__version__ = "0.2.0"
