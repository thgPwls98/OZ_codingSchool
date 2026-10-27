from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DB_USER: str = "root"
    DB_PASSWORD: str = "password1234"
    DB_HOST: str = "localhost"
    DB_PORT: str = "3306"
    DB_NAME: str = "ai_health"

    # JWT 설정 (NFR-USER-001)
    JWT_SECRET_KEY: str = "dev-only-secret-key-change-me-in-env-file-0000"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    # 리프레시 쿠키 Secure 속성. 로컬(http) 개발은 False, 운영(https)은 True
    COOKIE_SECURE: bool = False

    # X-Ray 이미지 비공개 저장 위치 (5일차 설계 7-1). 프로젝트 폴더 기준 상대 경로
    XRAY_STORAGE_DIR: str = "storage/xray"
    # AI 히트맵 비공개 저장 위치 (파일 정리 작업에서 사용, AI 판독 API 구현 시 같은 값 사용)
    HEATMAP_STORAGE_DIR: str = "storage/heatmap"
    # X-Ray 이미지 최대 용량 10MB (5일차 설계 2-3, 7-3)
    MAX_UPLOAD_SIZE: int = 10 * 1024 * 1024

    model_config = {
        "env_file": ".env",
        "extra": "ignore"
    }


settings = Settings()
