# MiniMax API 关键合约速查

完整文档索引:`https://platform.minimaxi.com/docs/llms.txt`
通用 API 基址:`https://api.minimaxi.com`(华北备用 `https://api-bj.minimaxi.com`)

| 用 | 端点 | 方法 |
|---|---|---|
| 上传 voice_clone | `/v1/files/upload` (`purpose=voice_clone`) | POST (multipart) |
| 上传 prompt_audio | `/v1/files/upload` (`purpose=prompt_audio`, ≤8s) | POST (multipart) |
| 复刻音色 | `/v1/voice_clone` | POST |
| 同步合成 | `/v1/t2a_v2` | POST |
| 异步合成提交 | `/v1/t2a_async_v2` | POST |
| 异步合成查询 | `/v1/query/t2a_async_query_v2?task_id=...` | GET |
| 音色设计 | `/v1/voice_design` | POST |
| 列音色 | `/v1/get_voice` (`voice_type` ∈ system / voice_cloning / voice_generation / all) | POST |
| 删音色 | `/v1/delete_voice` (`voice_type` ∈ voice_cloning / voice_generation) | POST |
| 列文件 | `/v1/files/list?purpose=...` | GET |
| 文件检索 | `/v1/files/retrieve?file_id=...` | GET |
| 文件删除 | `/v1/files/delete` body=`{file_id, purpose}` | POST |
| 文件下载 | `/v1/files/retrieve_content?file_id=...` | GET |

---

## 1. 上传参考音频

`POST /v1/files/upload`(`multipart/form-data`)

| 字段 | 必填 | 说明 |
|---|---|---|
| `purpose` | ✅ | `voice_clone`(快速复刻);`prompt_audio`(≤8s 示例音频,增强音色稳定度) |
| `file` | ✅ | 二进制。**仅支持 mp3 / m4a / wav**(FLAC 会被 status_code 2013 拒) |

约束:10s ≤ 时长 ≤ 5min,size ≤ 20MB。

返回:`{"file":{"file_id","bytes","created_at","filename","purpose"}, "base_resp":{...}}`

## 2. 复刻音色

`POST /v1/voice_clone`(`application/json`)

**必填:** `file_id` (int64)、`voice_id` (8~256 字符,首字母,允许 `[A-Za-z0-9_-]`,末位不能 `-_`)

**可选:**
- `model`:`speech-2.8-hd` / `2.8-turbo` / `2.6-hd` / `2.6-turbo` / `02-hd` / `02-turbo` / `01-hd` / `01-turbo`(给 `text` 时必填)
- `text` + `model`:生成试听音频(链接,有效期 24h);`speech-2.8-*` 支持 `(laughs)` / `(breath)` / `(sighs)` 等语气词标签
- `clone_prompt`:`{prompt_audio (int64 file_id), prompt_text}` 增强相似度
- `language_boost`:`auto` / 各种语言名,默认 `null`
- `text_validation` + `accuracy` (0~1,默认 0.7):对样本做 ASR 比对,相似度低于阈值则拒绝(错误码 1043)
- `need_noise_reduction` / `need_volume_normalization` / `aigc_watermark`(默认 false)

返回 `VoiceCloneResp`:
- `demo_audio`:试听链接(无 `text` 时为空)
- `extra_info`:`{audio_length, audio_sample_rate, audio_size, bitrate, word_count, usage_characters}`
- `base_resp`

> ⚠️ 复刻得到的音色 **7 天内未正式合成调用一次** 会被自动删除。

## 3. 同步文本转语音

`POST /v1/t2a_v2`(`application/json`)

> 旧的 `/v1/audio/speech` 在 MiniMax 上不存在(404);`/v1/tts/stream` 是另一个流式端点。

完整 payload:
```json
{
  "model": "speech-2.8-hd",          // 必填,枚举见 §2
  "text": "...",                      // 必填,< 10000 字符;>3000 字符建议流式
  "stream": false,                    // 默认 false,非流式
  "voice_setting": {
    "voice_id": "WurongVoice01",
    "speed": 1,                       // 0.5 ~ 2.0,默认 1
    "vol": 1,                         // 音量,默认 1,范围 0~10
    "pitch": 0,                       // -12 ~ 12
    "emotion": "neutral"              // happy/sad/angry/fearful/disgusted/surprised/neutral/fluent
  },
  "audio_setting": {
    "sample_rate": 32000,             // 8000/16000/22050/24000/32000/44100
    "bitrate": 128000,                // 32000/64000/128000/256000
    "format": "mp3",                  // mp3 / pcm / flac
    "channel": 1                      // 1 单声道 / 2 双声道
  },
  "pronunciation_dict": { "tone": [] },   // 行内发音替换
  "language_boost": "auto",
  "subtitle_enable": false,           // 启用后会附 subtitle_file 字段
  "output_format": "hex",             // hex / url(非流式才有效);默认 hex
  "aigc_watermark": false             // 音频末尾加节奏标识
}
```

非流式响应(`data.audio` 是 **hex 编码**,要 `bytes.fromhex` 解码):
```json
{
  "data": {
    "audio": "<hex bytes>",
    "status": 2,
    "subtitle_file": "https://...json"   // subtitle_enable=true 才有
  },
  "extra_info": {
    "audio_length": 4180,           // ms
    "audio_sample_rate": 32000,
    "audio_size": 68532,
    "bitrate": 128000,
    "audio_format": "mp3",
    "audio_channel": 1,
    "usage_characters": 16
  },
  "trace_id": "...",
  "base_resp": { "status_code": 0, "status_msg": "success" }
}
```

## 4. 异步合成(长文本)

**提交:** `POST /v1/t2a_async_v2`

body 与 §3 `t2a_v2` 完全一致(`voice_setting` + `audio_setting` 嵌套)。text 可达 10 万字符级。

返回:`{task_id, task_token, file_id, usage_characters, base_resp}`

**查询:** `GET /v1/query/t2a_async_query_v2?task_id=...`

返回 `{task_id, status, file_id, base_resp}`,`status` ∈ `processing` / `success` / `failed` / `expired`。

成功后用返回的 `file_id` 调 `§10 /v1/files/retrieve_content` 下载音频。

> ⚠️ 异步任务完成后,**`file_id` 自生成起 9 小时 (32,400 秒) 内有效,过期后** `retrieve_content` 会失败。

## 5. 音色设计(文本 → voice_id)

`POST /v1/voice_design`(`application/json`)

**必填:**
- `prompt`(音色文字描述,如「中年男性播音员,声音低沉富有磁性」)
- `preview_text`(≤500 字符试听文本)

**可选:**
- `voice_id`(自定义;省略则后端自动生成 `ttv-voice-<timestamp>-<random>`)
- `aigc_watermark`(默认 false,音频末尾加节奏标识)

返回:`{voice_id, trial_audio(hex), base_resp}` — `trial_audio` 是设计音色的试听音频,hex 编码。

按字符计费:`preview_text` 走 T2A 标准价。

## 6. 列音色

`POST /v1/get_voice` body=`{"voice_type": "system" | "voice_cloning" | "voice_generation" | "all"}`

返回:
```json
{
  "system_voice": [ {voice_id, voice_name, description, created_time}, ... ],
  "voice_cloning": [ {voice_id, voice_name, description, created_time}, ... ],
  "voice_generation": [ {voice_id, voice_name, description, created_time}, ... ],
  "music_generation": null,
  "voice_slots": null,
  "base_resp": { "status_code": 0, "status_msg": "success" }
}
```

**重要:** `voice_cloning` / `voice_generation` 类型音色必须先正式合成调用一次才会出现在此接口的响应里。系统音色长期可用(`created_time=1970-01-01`)。

## 7. 删音色

`POST /v1/delete_voice` body=`{"voice_type": "voice_cloning" | "voice_generation", "voice_id": "..."}`

只支持删这两种类型。系统音色不可删。返回值:`{voice_id, created_time, base_resp}`。

## 8. 列文件

`GET /v1/files/list?purpose=<voice_clone | prompt_audio | t2a_async_input>`

返回 `{files: [{file_id, bytes, created_at (Unix 秒), filename, purpose}], base_resp}`。

## 9. 文件元信息检索

`GET /v1/files/retrieve?file_id=<int>`

返回 `{file: {file_id, bytes, created_at, filename, purpose}, base_resp}`。

## 10. 文件下载

`GET /v1/files/retrieve_content?file_id=<int>`

返回**原始二进制**(`Content-Type: application/json` 但 `format: binary`)。直接 `response.content` 写文件,不用 hex 解码(与 §3 t2a_v2 的 hex 编码不同)。

## 11. 文件删除

`POST /v1/files/delete` body=`{file_id, purpose}`

`purpose` 取值:`voice_clone` / `prompt_audio` / `t2a_async` / `t2a_async_input` / `video_generation`。

---

## 状态码常见值

| status_code | 含义 |
|---|---|
| 0 | 成功 |
| 1000 | 未知错误 |
| 1001 | 超时 |
| 1002 | 触发限流(轮询时常见,建议 backoff) |
| 1004 | 鉴权失败(API Key 错) |
| 1008 | 账号余额不足 |
| 1013 | 服务内部错误 |
| 1039 | 触发 TPM 限流 |
| 1042 | 非法字符超 10% |
| 1043 | ASR 相似度比对失败 |
| 2013 | 传入参数异常(比如上传 FLAC、payload 字段缺失/类型错) |
| 2038 | 无复刻权限(需完成个人/企业认证) |
| 2049 | 无效 api key |

---

## 本项目用到的端点 vs 服务端所有端点

本 CLI 已实装: §1 upload、§2 voice_clone、§3 t2a_v2、§4 t2a_async_v2 + query、§5 voice_design、
§6 get_voice、§7 delete_voice、§8 files/list、§9 files/retrieve、§10 files/retrieve_content、§11 files/delete。

未实装的(暂时够用): 历史接口(WebSocket 流式 / 视频生成 / ChatCompletion / Realtime 等),
详见官方 `llms.txt`。
