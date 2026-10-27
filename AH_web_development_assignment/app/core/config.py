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
    # 프록시 뒤에서는 브라우저에서 접속하는 외부 Origin을 명시한다.
    ALLOWED_ORIGINS: list[str] = []

    model_config = {
        "env_file": ".env",
        "extra": "ignore"
    }


settings = Settings()
