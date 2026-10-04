"""Model identifiers shared by recording, offline loading and explicit downloads."""
QWEN = "Qwen/Qwen3-ASR-1.7B"
SENSE = "iic/SenseVoiceSmall"
PARAFORMER = "paraformer-zh-streaming"
PARAFORMER_REPO = "iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-online"


def model_repository(model):
    return PARAFORMER_REPO if model == PARAFORMER else model
