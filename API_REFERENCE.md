# MiniMax API 关键合约速查

完整文档索引:https://platform.minimaxi.com/docs/llms.txt
通用 API 基址:`https://api.minimaxi.com`(备用 `https://api-bj.minimaxi.com`)

## 1. 上传参考音频

`POST /v1/files/upload`(`multipart/form-data`)

| 字段 | 必填 | 说明 |
|---|---|---|
| `purpose` | ✅ | 取值 `voice_clone`(快速复刻);另外的 `prompt_audio` 用于上传 ≤8s 示例音频增强相似度 |
| `file` | ✅ | 二进制。**仅支持 mp3 / m4a / wav**(FLAC 会被拒,status_code 2013) |

约束:10s ≤ 时长 ≤ 5min,size ≤ 20MB。

返回:`{"file":{"file_id",...},"base_resp":{...}}`

## 2. 复刻音色

`POST /v1/voice_clone`(`application/json`)

必填:`file_id` (int64) 、`voice_id` (8~256 字符,首字母,允许 `[A-Za-z0-9_-]`,末位不能 `-_`)

可选:
- `model`:`speech-2.8-hd` / `2.8-turbo` / `2.6-hd` / `2.6-turbo` / `02-hd` / `02-turbo` / `01-hd` / `01-turbo`(给 `text` 时必填)
- `text` + `model`:生成试听音频(链接,有效期 24h),同时 `speech-2.8-*` 支持 `(laughs)` / `(breath)` / `(sighs)` 等语气词标签
- `clone_prompt`:{`prompt_audio`(int64 file_id),`prompt_text`} 增强音色稳定度
- `language_boost`:`auto` / 各种语言名,默认 `null`
- `text_validation` + `accuracy`(0~1,默认 0.7):对样本做 ASR 比对,相似度低于阈值则拒绝(错误码 1043)
- `need_noise_reduction` / `need_volume_normalization` / `aigc_watermark`(默认 false)

返回:`VoiceCloneResp` 含 `demo_audio`(试听链接,无 text 时为空)、`extra_info`(计费字符等)、`base_resp`

> ⚠️ 复刻得到的音色 **7 天内未正式合成调用一次** 会被自动删除。

## 3. 文本转语音(T2A v2)

`POST /v1/t2a_v2`(同步;旧的 `/v1/audio/speech` 在 MiniMax 上不存在,`/v1/tts/stream` 是流式端点)

完整 payload:
```json
{
  "model": "speech-2.8-hd",          // 必填,枚举见 §2
  "text": "...",                      // 必填,< 10000 字符;>3000 字符建议流式
  "stream": false,                    // 默认 false,非流式
  "voice_setting": {
    "voice_id": "WurongVoice01",
    "speed": 1,                       // 0.5 ~ 2.0 之类,默认 1
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
  "pronunciation_dict": { "tone": [] },   // 可选,行内发音替换
  "language_boost": "auto",           // 可选
  "subtitle_enable": false,           // 可选,会附带字幕下载链接
  "output_format": "hex",             // hex / url(非流式才有效);默认 hex
  "aigc_watermark": false             // 可选,音频末尾加节奏标识
}
```

非流式响应:
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

解码:`bytes.fromhex(j["data"]["audio"])` 写到文件即可。

## 4. 状态码常见值

| status_code | 含义 |
|---|---|
| 0 | 成功 |
| 1000 | 未知错误 |
| 1001 | 超时 |
| 1002 | 触发限流 |
| 1004 | 鉴权失败(API Key 错) |
| 1008 | 账号余额不足 |
| 1013 | 服务内部错误 |
| 1043 | ASR 相似度比对失败 |
| 2013 | 传入参数异常(比如上传了 FLAC) |
| 2038 | 无复刻权限(需完成个人/企业认证) |
| 2049 | 无效的 api key |

## 5. 音色管理辅助

- `POST /v1/voice/clone/delete` 删除已生成的音色
- `GET  /v1/voice/clone/list`   查询可用音色分类
- `POST /v1/voice/design`        音色设计(无需提供参考音频)
- `POST /v1/files/upload` (purpose=prompt_audio) 上传 ≤8s 示例音频
