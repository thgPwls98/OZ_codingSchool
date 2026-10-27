"""X-Ray 이미지 파일 검사·저장·삭제 공통 함수 (5일차 설계 7-1, 7-3, D5, D11, D12, D16)

- 저장 위치: 공개 폴더(media/)가 아닌 비공개 폴더 storage/xray/{patient_id}/{uuid}.{ext}
- DB(xray_images.image_url)에는 저장 폴더 기준 상대 경로 "{patient_id}/{uuid}.{ext}"만 저장한다.
- 형식은 확장자·Content-Type이 아니라 파일 앞부분의 서명(매직 넘버)으로 확인한다.
- 용량은 청크 단위로 읽으며 누적해서 확인하고, 10MB를 넘는 순간 중단 후 쓰던 파일을 지운다.
"""

import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from starlette.concurrency import run_in_threadpool

from app.core.config import settings

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CHUNK_SIZE = 1024 * 1024  # 1MB씩 읽는다

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"  # 89 50 4E 47 0D 0A 1A 0A
JPEG_SIGNATURE = b"\xff\xd8\xff"

IMAGE_TOO_LARGE = "이미지 용량은 10MB 이하여야 합니다."
UNSUPPORTED_IMAGE = "JPG, PNG 이미지만 업로드할 수 있습니다."

# 파일 종류 (파일 정리 작업 file_kind와 같은 값)
FILE_KIND_XRAY = "xray"
FILE_KIND_HEATMAP = "heatmap"


def _storage_dir(file_kind: str) -> str:
    if file_kind == FILE_KIND_XRAY:
        return settings.XRAY_STORAGE_DIR
    if file_kind == FILE_KIND_HEATMAP:
        return settings.HEATMAP_STORAGE_DIR
    raise ValueError(f"알 수 없는 파일 종류입니다: {file_kind}")


def get_storage_root(file_kind: str = FILE_KIND_XRAY) -> Path:
    """종류별 비공개 저장 폴더의 절대 경로"""
    root = Path(_storage_dir(file_kind))
    return root if root.is_absolute() else PROJECT_ROOT / root


def resolve_stored_path(file_kind: str, relative_path: str) -> Path:
    """DB에 저장된 상대 경로를 실제 파일 경로로 바꾼다. 저장 폴더 밖을 가리키면 ValueError"""
    root = get_storage_root(file_kind).resolve()
    path = (root / relative_path).resolve()
    if not path.is_relative_to(root):
        raise ValueError("저장 폴더 밖의 경로입니다.")
    return path


def resolve_xray_path(image_url: str) -> Path:
    """xray_images.image_url(예: "3/abc123.png")을 실제 파일 경로로 바꾼다.

    저장 폴더(XRAY_STORAGE_DIR) 밖을 가리키면 ValueError. 이미지 조회·환자 삭제·기록 삭제에서 공통 사용.
    """
    return resolve_stored_path(FILE_KIND_XRAY, image_url)


def detect_image_extension(header: bytes) -> str | None:
    """파일 앞부분의 서명으로 형식을 판별한다. 지원하지 않으면 None"""
    if header.startswith(PNG_SIGNATURE):
        return "png"
    if header.startswith(JPEG_SIGNATURE):
        return "jpg"
    return None


async def save_xray_image(upload: UploadFile, patient_id: int) -> str:
    """이미지를 검사한 뒤 저장하고, DB에 넣을 상대 경로를 돌려준다.

    - 서명이 PNG·JPEG가 아니면 415
    - 10MB를 넘으면 413 (쓰던 파일은 삭제)
    """
    header = await upload.read(len(PNG_SIGNATURE))
    extension = detect_image_extension(header)
    if extension is None:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=UNSUPPORTED_IMAGE)

    # 저장 확장자는 원본 파일명이 아닌 감지한 형식으로 정한다.
    relative_path = f"{patient_id}/{uuid.uuid4().hex}.{extension}"
    path = resolve_xray_path(relative_path)
    await run_in_threadpool(path.parent.mkdir, parents=True, exist_ok=True)

    total_size = len(header)
    try:
        with path.open("wb") as file:
            await run_in_threadpool(file.write, header)
            while chunk := await upload.read(CHUNK_SIZE):
                total_size += len(chunk)
                if total_size > settings.MAX_UPLOAD_SIZE:
                    raise HTTPException(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail=IMAGE_TOO_LARGE
                    )
                await run_in_threadpool(file.write, chunk)
    except BaseException:
        # 용량 초과·쓰기 실패 등 어떤 이유로든 중단되면 쓰던 파일을 남기지 않는다.
        try:
            await delete_xray_file(relative_path)
        except OSError:
            pass  # 원래 오류(413 등)를 그대로 돌려주는 것이 우선
        raise
    return relative_path


def _remove_file_and_empty_parent(path: Path, root: Path) -> None:
    path.unlink(missing_ok=True)
    # 환자별 폴더가 비면 정리한다 (폴더째 삭제하지 않고 빈 폴더만, 설계 6-4 ①)
    parent = path.parent
    if parent != root and parent.is_relative_to(root):
        try:
            parent.rmdir()
        except OSError:
            pass  # 다른 파일이 남아 있거나 이미 없음


async def delete_stored_file(file_kind: str, relative_path: str) -> None:
    """저장된 파일을 삭제한다.

    - 이미 없는 파일은 성공으로 본다 (멱등).
    - 저장 폴더 밖 경로는 ValueError, 권한 등 삭제 실패는 OSError를 그대로 올린다.
    """
    path = resolve_stored_path(file_kind, relative_path)
    root = get_storage_root(file_kind).resolve()
    await run_in_threadpool(_remove_file_and_empty_parent, path, root)


async def delete_xray_file(image_url: str) -> None:
    """X-Ray 파일을 삭제한다. 이미 없으면 무시한다. 실패하면 ValueError / OSError"""
    await delete_stored_file(FILE_KIND_XRAY, image_url)
