# 云端 TTS 服务接入调研报告（2026-09-09）

> 目标：给桌宠加「云端 TTS 引擎」预设。结论：主流国内云 TTS 几乎都有 OpenAI 兼容 `/v1/audio/speech`，桌面应用只需改 base_url + key。**首推硅基流动 CosyVoice2。**

## 一、各服务商预设（直接填配置表单）

| 预设名 | base_url | model | voice | 克隆 | 说明 |
|---|---|---|---|---|---|
| **硅基流动 CosyVoice2（推荐）** | https://api.siliconflow.cn/v1 | FunAudioLLM/CosyVoice2-0.5B | `FunAudioLLM/CosyVoice2-0.5B:anna`（:alex/:anna/:bella/:david…）| ✅ | 国内直连、OpenAI 兼容零改动、中文极好、有免费额度、约 ¥0.3/千字。克隆：voice 传空+先上传参考音频 |
| MiniMax | https://api.minimaxi.com/v1 | speech-02-hd（turbo 低延迟）| 语音库 ID | ✅ | 情绪/拟人最强、中文好。$60-100/M 字符 |
| 阿里云 DashScope | https://dashscope.aliyuncs.com/api/v1 | cosyvoice-v2（v3-plus 带情绪）| longxiaochun 等 | ✅ | 与本地 CosyVoice 同源、稳定、中文极佳 |
| OpenAI 官方 | https://api.openai.com/v1 | gpt-4o-mini-tts（tts-1 便宜）| alloy 等 13 个 | ❌ | 最拟人、支持 instructions；需海外网络/结算 |
| 智谱 GLM-TTS | https://open.bigmodel.cn/api/paas/v4 | glm-tts | tongtong 等 | ✅ | 中文/方言极佳、OpenAI 兼容 |

### 备选（未进预设）
- 阶跃 StepFun：`https://api.stepfun.com/v1`，`stepaudio-2.5-tts`
- 火山方舟豆包：**非 OpenAI 兼容**（自定义头），需适配层，暂缓

## 二、请求体与通用注意
- 鉴权统一 `Authorization: Bearer <key>`（火山例外）。
- OpenAI 兼容口默认返回 mp3 流；桌宠要 wav 需显式 `response_format:"wav"`（部分服务支持有限，可 mp3）。
- 建议 15~30s 超时；长文本分句；克隆参考音频 <30s。
- 中文多音字/数字：交给云模型自动处理即可（CosyVoice/MiniMax/GLM 都能读好）。

## 三、来源
- OpenAI: https://developers.openai.com/api/docs/guides/text-to-speech
- 硅基流动: https://docs.siliconflow.com/cn/userguide/capabilities/text-to-speech
- MiniMax: https://platform.minimax.io/docs/api-reference/speech-t2a-http
- 阿里: https://help.aliyun.com/zh/model-studio/cosyvoice-256api
- 智谱: https://docs.bigmodel.cn/api-reference/模型-api/文本转语音
- 阶跃: https://platform.stepfun.com/docs/zh/api-reference/audio/create-audio
- 火山: https://docs.volcengine.com/docs/6561/1257584
