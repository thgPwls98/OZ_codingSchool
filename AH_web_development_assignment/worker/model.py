"""Inference matching the team's Colab five-fold submission pipeline."""

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
