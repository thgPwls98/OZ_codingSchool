"""6일차 1단계 worker/model.py와 API 연결부(3단계 D) 테스트

- 가중치 없이 도는 테스트: API 약속(MODEL_NAME·MODEL_VERSION·is_loaded·ensure_loaded·predict), 출력 오류 RuntimeError
- 실제 가중치가 있을 때만 도는 테스트: 5개 모델 로딩과 실제 이미지 예측 (가중치는 Git 제외라 없으면 건너뜀)

실행: uv run python -m unittest tests.test_worker_model -v
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import torch
from PIL import Image

from worker import model as worker_model

WEIGHTS_READY = all((worker_model.DEFAULT_MODEL_DIR / f"best_model_fold{i}.pt").is_file() for i in range(5))


class _FixedLogits(torch.nn.Module):
    def __init__(self, logits):
        super().__init__()
        self.logits = torch.tensor([logits], dtype=torch.float32)

    def forward(self, images):
        return self.logits


def predictor_with(logits_list):
    """가중치 없이 LoadedPredictor의 판정 로직만 확인하기 위한 객체"""
    predictor = worker_model.LoadedPredictor.__new__(worker_model.LoadedPredictor)
    predictor.device = torch.device("cpu")
    predictor.models = [_FixedLogits(logits) for logits in logits_list]
    predictor.transform = worker_model.T.Compose([worker_model.T.Resize((8, 8)), worker_model.T.ToTensor()])
    return predictor


class WorkerContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.image = Path(self.tmp.name) / "xray.png"
        Image.new("RGB", (32, 32), (120, 120, 120)).save(self.image)

    def test_api_contract_names(self):  # 설계 5-1절
        self.assertEqual(worker_model.MODEL_NAME, "efficientnet_b0-5fold")
        self.assertEqual(worker_model.MODEL_VERSION, "v1")
        self.assertLessEqual(len(worker_model.MODEL_NAME), 50)  # ai_model String(50)
        for name in ("is_loaded", "ensure_loaded", "load_default_model", "predict"):
            self.assertTrue(callable(getattr(worker_model, name)))

    def test_threshold_and_confidence(self):
        normal = predictor_with([[2.0, 0.0]] * 5).predict(self.image)  # 폐렴 확률 약 0.12
        self.assertFalse(normal.is_pneumonia)
        self.assertEqual(normal.confidence, round((1 - normal.pneumonia_probability) * 100, 2))
        pneumonia = predictor_with([[0.0, 2.0]] * 5).predict(self.image)
        self.assertTrue(pneumonia.is_pneumonia)
        self.assertGreater(pneumonia.confidence, 50)

    def test_non_finite_output_is_runtime_error(self):  # 손상 이미지(ValueError)와 구분
        with self.assertRaises(RuntimeError):
            predictor_with([[float("nan"), 0.0]] * 5).predict(self.image)

    def test_corrupt_image_is_value_error(self):
        bad = Path(self.tmp.name) / "bad.png"
        bad.write_bytes(b"not an image")
        with self.assertRaises(ValueError):
            predictor_with([[0.0, 0.0]] * 5).predict(bad)

    def test_missing_weights_ensure_loaded_false_and_predict_runtime_error(self):
        worker_model.get_predictor.cache_clear()
        self.addCleanup(worker_model.get_predictor.cache_clear)
        with patch.object(worker_model, "DEFAULT_MODEL_DIR", Path(self.tmp.name) / "none"), \
                patch.object(worker_model.load_model, "__defaults__", (Path(self.tmp.name) / "none",)):
            self.assertFalse(worker_model.is_loaded())
            self.assertFalse(worker_model.ensure_loaded())
            with self.assertRaises(RuntimeError):
                worker_model.predict(self.image)


@unittest.skipUnless(WEIGHTS_READY, "worker/models에 가중치 5개가 없어 실제 모델 테스트를 건너뜀")
class RealModelTests(unittest.TestCase):
    def test_load_once_and_predict(self):
        worker_model.load_default_model()
        self.assertTrue(worker_model.is_loaded())
        first = worker_model.get_predictor()
        worker_model.load_default_model()
        self.assertIs(worker_model.get_predictor(), first)  # 다시 로딩하지 않음

        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "xray.png"
            Image.new("L", (512, 512), 128).save(image)
            result = worker_model.predict(image)
        self.assertIn(result.is_pneumonia, (True, False))
        self.assertTrue(0 <= result.confidence <= 100)


if __name__ == "__main__":
    unittest.main()
