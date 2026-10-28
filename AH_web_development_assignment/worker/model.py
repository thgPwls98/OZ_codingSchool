"""Inference matching the team's Colab five-fold submission pipeline."""
from pydantic import Field
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import BinaryIO

import timm
import torch
from PIL import Image
from torch import nn
from torchvision import transforms as T


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
        with Image.open(image_path) as image:
            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise ValueError("Image pixel limit exceeded")
            inputs = self.transform(image.convert("RGB")).unsqueeze(0)
        inputs = inputs.to(self.device)
        # Colab stores float32 probabilities in a NumPy float64 array before
        # taking their mean. Use float64 here as well to preserve that behavior.
        probabilities = torch.stack([
            torch.softmax(model(inputs), dim=1)[0, 1]
            for model in self.models
        ]).to(dtype=torch.float64)
        if not torch.isfinite(probabilities).all().item():
            raise ValueError("Model returned a non-finite probability")
        if ((probabilities < 0) | (probabilities > 1)).any().item():
            raise ValueError("Model returned an invalid probability")
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

_load_lock = threading.Lock()
_predict_slots = threading.BoundedSemaphore(settings.AI_MAX_CONCURRENT_PREDICTIONS)
 
 
def is_loaded() -> bool:
    """get_predictor() 가 한 번 성공해 모델이 메모리에 있으면 True."""
    return get_predictor.cache_info().currsize > 0
 
 
def _ensure_predictor() -> LoadedPredictor:
    if is_loaded():
        return get_predictor()
    # 지연 로딩(AI_PRELOAD_MODEL=false): 동시에 여러 요청이 와도 한 번만 로드
    with _load_lock:
        if is_loaded():  # 기다리는 동안 다른 요청이 로드를 끝낸 경우
            return get_predictor()
        started = time.perf_counter()
        try:
            predictor = get_predictor()
        except Exception as exc:
            # 가중치 누락(FileNotFoundError)이 이미지 누락과 섞이지 않도록 RuntimeError 로 감싼다
            raise RuntimeError(f"Model load failed: {exc}") from exc
        logger.info("AI 모델 지연 로드 완료 %s:%s (%.0fms)",
                    MODEL_NAME, MODEL_VERSION, (time.perf_counter() - started) * 1000)
        return predictor
 
 
def predict(path: str | Path | BinaryIO) -> PredictionOutput:
    """저장된 X-Ray 이미지로 예측한다. 블로킹 함수이므로 API 에서는 스레드풀로 호출한다."""
    predictor = _ensure_predictor()
 
    started = time.perf_counter()
    with _predict_slots:
        acquired = time.perf_counter()
        output = predictor.predict(path)
    finished = time.perf_counter()
 
    # 성능 측정 (NFR-PRED-001). 파일명만 남기고 환자 정보는 남기지 않는다.
    name = Path(path).name if isinstance(path, (str, Path)) else "<stream>"
    logger.info(
        "prediction model=%s:%s image=%s pneumonia=%s confidence=%.2f wait=%.0fms inference=%.0fms total=%.0fms",
        MODEL_NAME, MODEL_VERSION, name, output.is_pneumonia, output.confidence,
        (acquired - started) * 1000, (finished - acquired) * 1000, (finished - started) * 1000,
    )
    return output
 
 
def predict_pneumonia(image: str | Path | BinaryIO) -> PredictionOutput:
    """기존 이름 호환용. predict() 와 같다."""
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

def predict_pneumonia(image: str | Path | BinaryIO) -> PredictionOutput:
    """Predict an uploaded image, reusing the in-memory default models."""
    return get_predictor().predict(image)


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
