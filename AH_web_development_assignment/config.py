"""AI 모델 설정. 모든 값은 AI_ 로 시작하는 환경변수(.env)로 바꿀 수 있다.

예) AI_PRELOAD_MODEL=false, AI_MODEL_VERSION=1.1.0
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

AI_MODEL_COLUMN_MAX = 50  # ai_analysis_results.ai_model = String(50)


class AISettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AI_",
        env_file=".env",
        extra="ignore",
        protected_namespaces=(),  # model_name 등 "model_" 로 시작하는 필드 허용
    )

    # --- 로딩 ---
    preload_model: bool = Field(True, description="true: 서버 시작 시 로드 / false: 첫 예측 요청 때 로드")
    use_dummy_model: bool = Field(False, description="true: 실제 모델 없이 가짜 결과로 API 흐름 테스트")
    warmup: bool = Field(True, description="로드 직후 한 번 추론해 첫 요청 지연을 없앤다")

    # --- 모델 식별 (ai_analysis_results.ai_model = "{name}:{version}") ---
    model_name: str = "pneumonia-cnn"
    model_version: str = "1.0.0"
    model_path: Path = Path("models/pneumonia_model.pt")
    device: str = "cpu"

    # --- 판정 ---
    threshold: float = Field(0.5, ge=0.0, le=1.0, description="폐렴 확률이 이 값 이상이면 폐렴")

    # --- 히트맵 ---
    heatmap_dir: Path = Path("media/heatmaps")

    # --- 성능 (NFR-PRED-001) ---
    max_concurrency: int = Field(1, ge=1, description="동시에 실행할 추론 수")
    slow_prediction_ms: float = Field(3000, gt=0, description="이 시간을 넘으면 WARNING 로그")
    stats_window: int = Field(200, ge=10, description="성능 통계에 쓰는 최근 예측 수")

    @property
    def model_id(self) -> str:
        return f"{self.model_name}:{self.model_version}"

    @model_validator(mode="after")
    def _check_model_id_length(self) -> "AISettings":
        if len(self.model_id) > AI_MODEL_COLUMN_MAX:
            raise ValueError(
                f"AI_MODEL_NAME:AI_MODEL_VERSION 은 {AI_MODEL_COLUMN_MAX}자 이하여야 합니다. (현재 {self.model_id!r})"
            )
        return self


@lru_cache
def get_ai_settings() -> AISettings:
    return AISettings()
