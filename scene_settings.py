"""Validated, per-user SCENE settings; installs never need write access."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import tempfile

DEFAULTS = {
    "audio_source": "local", "script_source": "local",
    "audio_url": "", "script_url": "", "audio_folder": "",
    "default_volume": 100, "fade_in_seconds": 3.0,
    "fade_in_from": 0, "fade_in_to": 100,
    "fade_out_seconds": 3.0, "fade_out_from": 100, "fade_out_to": 0,
    "video_encoder": "libx264", "video_preset": "veryslow",
    "check_updates": True,
}
ENCODERS = ("libx264", "h264_qsv", "h264_nvenc")
PRESETS = ("ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow")


def settings_path() -> Path:
    return Path(os.environ.get("APPDATA", Path.home() / ".config")) / "SCENE App" / "settings.json"


def validate_settings(values: dict) -> dict:
    result = dict(DEFAULTS)
    for key, default in DEFAULTS.items():
        value = values.get(key, default)
        if key in {"audio_source", "script_source"}:
            if value not in {"local", "web"}:
                raise ValueError("소스 모드는 local 또는 web이어야 합니다.")
        elif key == "video_encoder":
            if value not in ENCODERS:
                raise ValueError("지원하지 않는 영상 인코더입니다.")
        elif key == "video_preset":
            if value not in PRESETS:
                raise ValueError("지원하지 않는 영상 프리셋입니다.")
        elif isinstance(default, bool):
            if not isinstance(value, bool):
                raise ValueError("자동 업데이트 설정을 확인하세요.")
        elif isinstance(default, (int, float)):
            try:
                value = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{key}: 숫자를 입력하세요.") from exc
            limit = 600 if key.endswith("seconds") else 100
            if not math.isfinite(value) or not 0 <= value <= limit:
                raise ValueError(f"{key}: 0~{limit} 범위로 입력하세요.")
        elif not isinstance(value, str):
            raise ValueError(f"{key}: 문자열을 입력하세요.")
        result[key] = value
    return result


def load_settings(path: Path | None = None) -> dict:
    try:
        data = json.loads((path or settings_path()).read_text(encoding="utf-8"))
        return validate_settings(data) if isinstance(data, dict) else dict(DEFAULTS)
    except (OSError, ValueError, TypeError):
        return dict(DEFAULTS)


def save_settings(values: dict, path: Path | None = None) -> dict:
    validated = validate_settings(values)
    destination = path or settings_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=destination.parent,
                                         prefix="settings-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(validated, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        temporary.replace(destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return validated
