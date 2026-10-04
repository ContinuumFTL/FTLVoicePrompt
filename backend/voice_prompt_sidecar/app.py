from __future__ import annotations

import os
from typing import Literal
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .models import QWEN, SENSE, PARAFORMER
from .recorder import RecorderStateError, SoundDeviceAudioInput, VoiceRecorder
from .sessions import RecordingService
from .output_format import format_output
from .text_rules import DEFAULT_RULES_PATH, load_text_rules


class SidecarConfig(BaseModel):
    model: Literal[QWEN, SENSE, PARAFORMER] = os.getenv("FTL_ASR_MODEL", QWEN)
    device: Literal["auto", "cpu", "cuda:0"] = "auto"
    dtype: Literal["auto", "float32", "float16", "bfloat16"] = "auto"
    language: Literal["auto", "zh", "en"] = "zh"
    terms: str = ""
    inputDevice: str = ""
    englishPunctuation: bool = True
    arabicNumbers: bool = True
    sample_rate: Literal[16000] = 16000


class SessionRequest(BaseModel):
    sessionId: str


class TranscribeFileRequest(BaseModel):
    path: str
    language: Literal["auto", "zh", "en"] = "zh"


class FormatPreviewRequest(BaseModel):
    text: str
    settings: SidecarConfig = SidecarConfig()
    final: bool = True


def create_app(config: SidecarConfig | None = None, service=None) -> FastAPI:
    settings = config or SidecarConfig()
    app = FastAPI(title="FTL Voice Prompt Sidecar")
    service = service or RecordingService(VoiceRecorder(SoundDeviceAudioInput()))
    app.state.recording_service = service

    def call(action, *args):
        try:
            return action(*args)
        except RecorderStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/health")
    def health():
        return {"status": "ok", "protocol": 12, "pid": os.getpid()}

    @app.post("/format/preview")
    def format_preview(request: FormatPreviewRequest):
        # The same formatter and rule loader used by recording sessions, without
        # recording audio, invoking a model, or writing history/clipboard text.
        rules = call(load_text_rules) if request.settings.arabicNumbers else None
        return {"text": format_output(request.text, request.settings, request.final, rules),
                "pid": os.getpid(),
                "rulesFile": str(Path(os.environ.get("FTL_VOICE_PROMPT_RULES_FILE") or DEFAULT_RULES_PATH).resolve()),
                "arabicNumbers": request.settings.arabicNumbers}

    @app.get("/audio/devices")
    def input_devices():
        return call(service.input_devices)

    @app.post("/models/prepare")
    def prepare_models(request: SidecarConfig, retry: bool = False):
        try:
            return service.prepare(request, retry=retry)
        except RecorderStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/recording/start")
    def start_recording(request: SidecarConfig):
        return call(service.start, request)

    @app.get("/recording/status/{session_id}")
    def recording_status(session_id: str):
        return call(lambda: service.get(session_id).snapshot())

    @app.post("/recording/stop")
    def stop_recording(request: SessionRequest):
        return call(service.finish, request.sessionId)

    @app.post("/recording/abort")
    def abort_recording(request: SessionRequest):
        call(service.abort, request.sessionId)
        return {"status": "cancelled"}

    @app.post("/transcribe-file")
    def transcribe_file(request: TranscribeFileRequest):
        with service.control:
            if service.session and service.session.thread.is_alive():
                raise HTTPException(409, "录音正在进行")
            if not Path(request.path).is_file():
                raise HTTPException(404, "audio file not found")
            from .models import create_runtime, release_memory
            service.session = None
            service.runtime = None
            service.runtime_key = None
            release_memory()
            service.runtime = create_runtime(**settings.model_dump())
            result = call(service.runtime.transcribe, request.path, 16000, request.language)
            return dict(rawText=result.raw_text, model=result.model, language=result.language, durationMs=0)

    return app


app = create_app()
