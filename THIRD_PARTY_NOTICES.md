# 第三方依赖与模型许可

本仓库自有代码采用 MIT，版权署名沿用项目现有 Git 作者 `ContinuumFTL`。该许可证不替代第三方代码、模型权重或服务的许可，也不授权重新标注它们。

## 1. 模型来源

仓库不包含模型权重。初始化脚本通过上游工具下载到用户缓存，运行时读取本地文件。公开发布前应核对实际下载来源和修订中的许可文件；下载记录能提供来源路径，不能代替许可核对。

| 模型 | 当前加载来源 | 许可说明 |
| --- | --- | --- |
| Qwen3-ASR 1.7B | Hugging Face `Qwen/Qwen3-ASR-1.7B` | 官方模型页标注 Apache-2.0；保留该修订的许可和通知。见 [模型页](https://huggingface.co/Qwen/Qwen3-ASR-1.7B) |
| SenseVoice Small | ModelScope `iic/SenseVoiceSmall` | 源码仓库使用 MIT，官方权重采用单独的 FunASR Model Open Source License Agreement，不能把权重统称为 MIT。见 [官方许可说明](https://github.com/QwenAudio/SenseVoice#license) 和 [下载来源](https://www.modelscope.cn/models/iic/SenseVoiceSmall) |
| Paraformer 中文流式 | ModelScope `iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-online` | 按该来源及所下载修订的许可处理。Hugging Face 上的 `funasr/paraformer-zh-streaming` 有自己的许可及固定标签，不能自动将另一仓库或旧缓存视为同一许可。见 [当前来源](https://www.modelscope.cn/models/iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-online) 和 [HF 许可及修订说明](https://huggingface.co/funasr/paraformer-zh-streaming#license-and-immutable-revision) |

本次没有替用户打包或再分发权重，也没有修改上游许可证。准备再分发模型或转换版本时，需要另外核对对应来源的条件。

## 2. 软件依赖

前端依赖记录在 `package.json` 和 `pnpm-lock.yaml`，原生依赖记录在 `src-tauri/Cargo.toml` 和 `Cargo.lock`，Python 依赖记录在 `backend/pyproject.toml` 和经过本地测试的 `backend/constraints.txt`。依赖安装包保留其自身的 LICENSE / NOTICE。

MIT 只覆盖本项目可授权的部分。源码公开、依赖再分发和包含依赖的二进制发布是不同的操作；准备安装包时还需要核对实际包含的依赖及相应通知。本说明不声称所有传递依赖都已完成法律兼容性审查。

## 3. 外部服务

DeepSeek 文本分析使用用户自行配置的接口和 API Key，受该服务的条款约束。语音识别在本机运行；只有使用文本分析功能时才发送相应文字。项目不提供共享的服务密钥。
