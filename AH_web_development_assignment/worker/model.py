"""Inference matching the team's Colab five-fold submission pipeline."""

import logging
import threading
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import BinaryIO

import timm
import torch
from PIL import Image, UnidentifiedImageError
from torch import nn
from torchvision import transforms as T


logger = logging.getLogger(__name__)

# API(⑫)가 결과 재사용 기준으로 쓰는 모델 식별자 (6일차 설계 5-1절, D5).
# 가중치·전처리·클래스 순서·THRESHOLD 중 하나라도 바뀌면 MODEL_VERSION을 올린다.
MODEL_NAME = "efficientnet_b0-5fold"
MODEL_VERSION = "v1"

DEFAULT_MODEL_DIR = Path(__file__).resolve().parent / "models"
THRESHOLD = 0.40000000000000013
MAX_IMAGE_PIXELS = 25_000_000


class PneumoniaClassifier(nn.Module):
    def __init__(self):
        super().__init__()
        # Preserve the "model." prefix in the saved Colab state_dict.
        # All weights come from local files; no pretrained download is needed.
        self.model = timm.create_model(
            "efficientnet_b0", pretrained=False, num_classes=2
        )

    def forward(self, images):
        return self.model(images)


@dataclass(frozen=True)
class PredictionOutput:
    pneumonia_probability: float
    is_pneumonia: bool
    confidence: float
    heatmap_relative_path: str | None = None


class LoadedPredictor:
    """Create once at worker startup, then reuse for all prediction jobs."""

    def __init__(self, model_dir=DEFAULT_MODEL_DIR, *, device="cpu"):
        self.device = torch.device(device)
        paths = [Path(model_dir) / f"best_model_fold{i}.pt" for i in range(5)]
        for path in paths:
            if not path.is_file():
                raise FileNotFoundError(f"Missing model weight: {path.name}")
        self.models = []
        for path in paths:
            model = PneumoniaClassifier()
            weights = torch.load(path, map_location="cpu", weights_only=True)
            model.load_state_dict(weights, strict=True)
            self.models.append(model.to(self.device).eval())
        self.transform = T.Compose([
            T.Resize((224, 224)),
            T.ToTensor(),
            T.Normalize(
                mean=[0.485, 0.456, 0.406],
                std=[0.229, 0.224, 0.225],
            ),
        ])

    @torch.inference_mode()
    def predict(self, image_path: str | Path | BinaryIO) -> PredictionOutput:
        """Accept a saved upload path or an opened binary image file."""
        try:
            with Image.open(image_path) as image:
                if image.width * image.height > MAX_IMAGE_PIXELS:
                    raise ValueError("Image pixel limit exceeded")
                inputs = self.transform(image.convert("RGB")).unsqueeze(0)
        except UnidentifiedImageError as exc:
            # 이미지가 아니거나 손상된 파일은 ValueError로 통일한다 (API 422, 설계 D9)
            raise ValueError("Unreadable image") from exc
        inputs = inputs.to(self.device)
        # Colab stores float32 probabilities in a NumPy float64 array before
        # taking their mean. Use float64 here as well to preserve that behavior.
        probabilities = torch.stack([
            torch.softmax(model(inputs), dim=1)[0, 1]
            for model in self.models
        ]).to(dtype=torch.float64)
        # 모델 출력 오류는 RuntimeError (API 500). 손상 이미지(ValueError, API 422)와 구분한다 (설계 5-1절)
        if not torch.isfinite(probabilities).all().item():
            raise RuntimeError("Model returned a non-finite probability")
        if ((probabilities < 0) | (probabilities > 1)).any().item():
            raise RuntimeError("Model returned an invalid probability")
        probability = probabilities.mean().item()
        is_pneumonia = probability > THRESHOLD
        confidence = round(
            (probability if is_pneumonia else 1 - probability) * 100, 2
        )
        return PredictionOutput(probability, is_pneumonia, confidence)


def load_model(model_path=DEFAULT_MODEL_DIR, *, device="cpu") -> LoadedPredictor:
    return LoadedPredictor(model_path, device=device)


@lru_cache(maxsize=1)
def get_predictor() -> LoadedPredictor:
    """Load the default CPU ensemble once and retain it in process memory."""
    return load_model()


# ===== API 연결 (6일차 3단계 D, 설계 5-1절) =====
_load_lock = threading.Lock()


def is_loaded() -> bool:
    """기본 모델 5개가 메모리에 올라가 있으면 True"""
    return get_predictor.cache_info().currsize > 0


def load_default_model() -> None:
    """서버 시작(lifespan) 또는 첫 예측 때 기본 모델을 1번만 메모리에 올린다. 실패하면 예외."""
    with _load_lock:  # 동시에 여러 요청이 와도 한 번만 로딩
        if is_loaded():
            return
        started = time.perf_counter()
        get_predictor()
        logger.info("AI 모델 로딩 완료 %s:%s (%.0fms)", MODEL_NAME, MODEL_VERSION,
                    (time.perf_counter() - started) * 1000)


def ensure_loaded() -> bool:
    """모델이 없으면 지금 로딩한다 (AI_PRELOAD_MODEL=false 지연 로딩). 성공 여부를 돌려준다."""
    if is_loaded():
        return True
    try:
        load_default_model()
        return True
    except Exception as exc:
        # 가중치 파일 경로는 남기지 않고 예외 종류만 기록한다
        logger.error("AI 모델 로딩 실패 %s:%s (%s)", MODEL_NAME, MODEL_VERSION, type(exc).__name__)
        return False


def predict(image_path: str | Path | BinaryIO) -> PredictionOutput:
    """메모리의 기본 모델로 X-Ray 1장을 예측한다. 블로킹 함수라 API는 스레드풀에서 호출한다.

    - 이미지 파일 없음: FileNotFoundError / 이미지가 아니거나 손상: ValueError
    - 모델 미로드·출력 오류: RuntimeError
    동시 실행 수 제한은 API(prediction_service)가 맡는다.
    """
    if not ensure_loaded():
        raise RuntimeError("AI model is not available")
    started = time.perf_counter()
    output = get_predictor().predict(image_path)
    # 성능 측정 (NFR-PRED-002). 환자 정보·파일 경로는 남기지 않는다.
    logger.info("AI 예측 %s:%s pneumonia=%s confidence=%.2f inference=%.0fms", MODEL_NAME, MODEL_VERSION,
                output.is_pneumonia, output.confidence, (time.perf_counter() - started) * 1000)
    return output


def predict_pneumonia(image: str | Path | BinaryIO) -> PredictionOutput:
    """기존 이름 호환용. predict()와 같다."""
    return predict(image)


if __name__ == "__main__":
    import argparse
    import json
    from dataclasses import asdict

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image_path", type=Path)
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()
    predictor = load_model(args.model_dir, device=args.device)
    print(json.dumps(asdict(predictor.predict(args.image_path))))
