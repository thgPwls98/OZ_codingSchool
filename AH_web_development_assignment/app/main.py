import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from app.core.config import settings
from starlette.staticfiles import StaticFiles
from starlette.responses import FileResponse

from app.apis.auth import router as auth_router
from app.apis.admin_apis import router as admin_router
from app.apis.medical_record_apis import router as medical_record_router
from app.apis.patient_apis import router as patient_router
from app.apis.practice_apis import router as practice_router
from app.apis.user_apis import router as user_router

app = FastAPI()


@app.middleware("http")
async def validate_cookie_origin(request: Request, call_next):
    # Origin이 없는 CLI 요청은 허용하고, 브라우저의 교차 출처 변경 요청은 거부한다.
    if request.url.path.startswith("/api/v1/") and request.method in {"POST", "PATCH", "PUT", "DELETE"}:
        origin = request.headers.get("origin")
        allowed = settings.ALLOWED_ORIGINS or [str(request.base_url).rstrip("/")]
        if origin is not None and origin not in allowed:
            return JSONResponse(status_code=403, content={"detail": "허용되지 않은 요청 출처입니다."})
    return await call_next(request)


app.include_router(practice_router)
app.include_router(user_router)
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(patient_router)
app.include_router(medical_record_router)

BASE_DIR = Path(__file__).resolve().parent.parent

# 만약 static, media 폴더가 존재하지 않으면 생성
if not (BASE_DIR / "static").exists():
    os.mkdir(BASE_DIR / "static")
if not (BASE_DIR / "media").exists():
    os.mkdir(BASE_DIR / "media")

# 'static' 폴더를 '/static' 경로로 마운트 (CSS, JS 파일 서빙용)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
# 'media' 폴더를 '/media' 경로로 마운트 (사용자 업로드 파일 서빙용)
app.mount("/media", StaticFiles(directory=BASE_DIR / "media"), name="media")


@app.get(path="/healthcheck", status_code=200, include_in_schema=False)
async def healthcheck():
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/{path:path}", include_in_schema=False)
async def catch_all(path: str):
    # API나 정적 파일 경로는 제외 (FastAPI가 먼저 매칭하지 못한 경우에만 실행됨)
    if (
        path.startswith("api/v1")
        or path.startswith("static/")
        or path.startswith("media/")
    ):
        from fastapi import HTTPException

        raise HTTPException(status_code=404)
    return FileResponse(BASE_DIR / "static" / "index.html")
