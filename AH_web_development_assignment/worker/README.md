# 폐렴 모델 추론

`models/best_model_fold0.pt`부터 `best_model_fold4.pt`까지 5개 파일이 필요합니다.
가중치는 Git 추적에서 제외합니다. 팀원에게 ZIP을 별도로 전달해주세요.

torch: 2.11.0+cu130
torchvision: 0.26.0+cu130
timm: 1.0.30
threshold: 0.40000000000000013

## 실행

프로젝트 루트(`AH_web_development_assignment/`)에서 지원되는 Python
환경에 `python -m pip install -r worker/requirements.txt`로 의존성을 설치합니다.
학습 환경은 torch 2.11.0+cu130, torchvision 0.26.0+cu130, timm 1.0.30이며,
배포 환경에 맞는 CPU/CUDA 빌드를 선택합니다.

```sh
python -m worker.model /path/to/xray.jpg
```

서비스에서는 `load_model()`을 worker 시작 시 한 번 호출하고 반환된
predictor의 `predict(image_path)`를 작업마다 재사용합니다. 기본 장치는 CPU이며
CUDA는 `load_model(device="cuda")` 또는 CLI의 `--device cuda`로 선택합니다.

## 업로드된 이미지로 예측하기

업로드되어 저장된 이미지 경로를 전달하면 결과를 반환합니다. API 구현 없이
파이썬 코드에서 직접 호출할 수 있습니다.

```python
from worker.model import get_predictor, predict_pneumonia

# 프로세스 시작 시 미리 로드합니다. 이후 호출에서는 같은 모델을 재사용합니다.
get_predictor()
result = predict_pneumonia("/path/to/uploaded-xray.jpg")
print("폐렴" if result.is_pneumonia else "정상")
print(f"폐렴 확률: {result.pneumonia_probability * 100:.2f}%")
print(f"판정 클래스 점수: {result.confidence:.2f}%")
```

`predict_pneumonia()`는 열린 바이너리 이미지 파일도 입력받습니다.
모델은 프로세스마다 별도로 로드됩니다. `get_predictor()`를 시작 시 호출하지
않으면 첫 예측 시 로드합니다. 모델 로드는 동시 요청을 받기 전에 수행합니다.

## 예측 규칙

- EfficientNet-B0 구조와 Colab의 `model.` 가중치 키를 그대로 사용합니다.
- RGB → 224×224 리사이즈 → 텐서 → ImageNet 정규화 순서입니다.
- 5개 모델의 softmax 클래스 1(폐렴) 확률을 평균합니다.
- 평균이 `0.40000000000000013`보다 **클 때** 폐렴으로 판정합니다.
- confidence는 판정된 클래스의 점수를 백분율로 표시합니다.
- 히트맵은 구현하지 않았으며 `heatmap_relative_path`는 null입니다.

OOF Macro F1 0.9850은 OOF에서 임계값을 탐색한 점수입니다. 별도 테스트의
앙상블 성능을 의미하지 않습니다. Recall·Accuracy와 실제 추론 시간은 별도로
검증해야 합니다. 이미지 디코딩·가중치 로딩·추론 실패는 예외로 전달합니다.

이 모듈은 모델 추론만 제공합니다. DB 작업 큐, API 연결, 결과 저장,
worker 실행 루프와 팀 리뷰·브랜치 병합은 별도 작업입니다.

## 팀 코드 리뷰 항목

- `get_predictor()`가 모델을 메모리에 유지하고 예측마다 다시 읽지 않는 이유
- 학습 코드와 RGB·리사이즈·정규화를 동일하게 맞추는 이유
- 클래스 1 확률을 평균한 뒤 임계값과 비교하는 과정
- 폐렴 확률과 판정 클래스 confidence의 차이
- 이미지 오류는 예외로 전달하고 임의의 정상 결과를 반환하지 않는 동작

팀 규칙(`docs/1일차_team_rules.md`)에 따라 리뷰어 승인 후 병합합니다.
팀원 이해 공유와 승인 여부는 실제 리뷰에서 확인해야 합니다.

## 실행 검증 기록 (2026-10-28)

Python 3.14 임시 가상환경(`/private/tmp/pneumonia-worker-venv`)에 의존성을
설치하여 CPU에서 다음을 확인했습니다.

- 실제 Fold 가중치 5개 로딩 성공
- `get_predictor()` 반복 호출 시 동일 모델 객체 재사용
- 합성 PNG의 저장 경로와 바이너리 파일 입력에서 동일한 예측 결과 반환
- 손상 이미지 입력 시 디코딩 예외 발생

저장소에 실제 X-Ray 샘플이 없어 합성 이미지로 실행 흐름만 검증했습니다.
실제 X-Ray 성능·Recall·Accuracy 검증 결과는 아닙니다.
