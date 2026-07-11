# clone-voice — MiniMax 音色克隆 + 文字转语音 CLI

基于 [MiniMax 开放平台](https://platform.minimaxi.com) 的 Typer + Rich CLI 工具:
上传音频 → 克隆音色 → 文字转语音,加上 voice 管理、长文异步、文件管理、本地参数缓存等
实用子命令。专为本地开发场景设计,不依赖前端。

---

## 安装

需要:
- **Python ≥ 3.10**(本机用 `/home/wurong/miniconda3/bin/python3`)
- 系统装了 **ffmpeg**(FLAC 上传前自动转 WAV 用)
- 已安装 `typer`、`requests`、`rich`(Typer 自带 Rich)

把仓库 `clone-voice/` 加进 `PATH`,或者直接用 `python minimax_voice_clone.py ...`。

```bash
python -m pip install typer requests rich   # 一次到位
```

---

## 准备 API Key

1. 在 [MiniMax 开放平台](https://platform.minimaxi.com) 完成个人/企业认证
2. 在 [接口密钥](https://platform.minimaxi.com/user-center/basic-information/interface-key) 拿到 API_KEY
3. **推荐**用环境变量,避免每次传:

```bash
export MINIMAX_API_KEY="sk-cp-xxxxxxxxxxxx"
```

也可临时 `--api-key sk-xxx`。

---

## 命令一览

| 命令 | 用途 |
|---|---|
| `run` | 一条龙:上传 → 克隆 → 同步合成(旧版兼容) |
| `tts` | 只做同步 TTS(`/v1/t2a_v2`);缺省参数从本地缓存读 |
| `clone` | 只做上传 + 克隆(`/v1/voice_clone`);可选让后端生成试听 |
| `design` | 文字描述生成音色(`/v1/voice_design`),自动下载试听 |
| `tts-async` | 异步合成长文本(`/v1/t2a_async_v2`),自动轮询 + 下载 |
| `voices list` | 列音色(系统 / 克隆 / 文生 / 全) |
| `voices delete` | 删一个克隆/文生 voice_id(系统音色不可删) |
| `files list` | 列已上传文件 |
| `files retrieve` | 查单个文件元信息 |
| `files delete` | 删一个文件 |
| `files download` | 下载文件(异步产物 9 小时内有效) |
| `config show` / `clear` / `set KEY=VAL` | 管理本地默认参数 |

每个子命令都带自己的 `--help`(Typer + Rich 渲染)。

---

## 常用例子

```bash
# ============ 完整流程 ============
python minimax_voice_clone.py run my_voice.wav \
    --voice-id MyVoice001 \
    --text "你好,这是克隆的声音"

# ============ 跳过上传/克隆,只合成 ============
python minimax_voice_clone.py run /dev/null \
    --voice-id MyVoice001 \
    --text "第二句话" \
    --skip-clone

# ============ 单步 TTS,所有参数走 config ============
python minimax_voice_clone.py config set \
    voice_id=MyVoice001 model=speech-2.8-hd emotion=neutral
python minimax_voice_clone.py tts --text "用上次的音色再说一句" -o out.mp3

# ============ 异步长文 ============
python minimax_voice_clone.py tts-async \
    --text "$(cat long.txt)" --output long.mp3

# ============ 描述生成音色 ============
python minimax_voice_clone.py design \
    --prompt "中年男性播音员,声音低沉富磁性" \
    --preview-text "夜深了,古屋里只有他一人……" \
    --voice-id MyDesigner01

# ============ 音色管理 ============
python minimax_voice_clone.py voices list --type voice_cloning
python minimax_voice_clone.py voices delete MyVoice001   # 交互确认
python minimax_voice_clone.py voices delete MyVoice001 --yes   # 跳过确认

# ============ 文件管理 ============
python minimax_voice_clone.py files list --purpose voice_clone
python minimax_voice_clone.py files download 418702907416898 -o recon.wav
```

---

## 本地参数缓存

`~/.config/clone-voice/config.json` 里保存"最近成功用过"的合成参数,
`tts` / `tts-async` 命令没显式传的字段会从这里读,再 fallback 到内置默认。

```bash
python minimax_voice_clone.py config show         # 看到当前值 vs 默认
python minimax_voice_clone.py config set voice_id=MyVoice model=speech-2.8-hd
python minimax_voice_clone.py config clear -y     # 清空
```

---

## 隐私与本地保留

**仓库里的 `.gitignore` 屏蔽了所有个人音频和合成的产物**
(`*.wav` / `*.flac` / `*.mp3` / `*.m4a` / `output_speech.*` / `__pycache__/` 等),
不会因为 `git add .` 误传到仓库。

工具源里也没有硬编码的 API_KEY —— 全走 `MINIMAX_API_KEY` 环境变量或
`--api-key` 显式传入。

⚠️ 注意:
- 复刻后的 `voice_id` 在 MiniMax 服务端 **7 天内必须正式合成调用一次**,
  否则会自动删除。
- 异步合成产物的 `file_id` 服务端 **9 小时后过期**,过期的就拉不到了。

---

## 文件结构

```
clone-voice/
├── minimax_voice_clone.py        # 5 行入口脚本
├── minimax_voice_clone/          # 包
│   ├── __init__.py               # 暴露 app / __version__
│   ├── __main__.py               # python -m minimax_voice_clone
│   ├── config.py                 # 常量 + auth + 校验 + 本地缓存
│   ├── api.py                    # 所有 MiniMax HTTP 接口封装
│   ├── ui.py                     # Rich Console / Table / Confirm
│   └── cli.py                    # 所有 Typer 命令 + app / sub-app
├── docs/
│   ├── README.md                 # 你正在看的这个
│   └── API_REFERENCE.md          # 12 个端点的完整 schema 速查
├── samples/                      # 个人待克隆原始音频(不进 git)
├── .gitignore                    # 屏蔽个人音频 + 凭据
└── .gitattributes
```

## 工作流:把参考音频放到哪里?

`samples/` 目录(在仓库根、gitignored)是"待克隆原始音频"的工作区。
新加参考音频就直接丢到 `samples/` 下,然后:

```bash
python minimax_voice_clone.py run samples/my_voice.wav \
    --voice-id MyVoice001 \
    --text "你好,这是我的克隆声音"
```

或者:

```bash
# 先开新音色
python minimax_voice_clone.py clone samples/my_voice.wav --voice-id MyVoice001
# 之后所有合成走 cache
python minimax_voice_clone.py tts --text "另一段话" -o out.mp3
```

---

## API 文档

详见 [`API_REFERENCE.md`](./API_REFERENCE.md) —— 各端点路径、payload schema、
响应结构、状态码、对照官方文档(2026-07 拉取)。
