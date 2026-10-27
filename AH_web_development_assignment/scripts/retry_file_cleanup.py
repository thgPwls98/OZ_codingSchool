"""미완료 파일 정리 작업을 재처리하고 남은 작업 수를 보여준다 (5일차 설계 6-4 ⑤, D18)

주기적으로 실행한다. 예) 매 5분 cron:
    */5 * * * * cd /path/to/AH_web_development_assignment && uv run python scripts/retry_file_cleanup.py

운영 확인만 할 때:
    uv run python scripts/retry_file_cleanup.py --status
"""

import argparse
import asyncio
import os
import sys

sys.path.append(os.getcwd())

from sqlalchemy import func, select  # noqa: E402

from app.core.db.databases import AsyncSessionLocal  # noqa: E402
from app.models import FileCleanupJob  # noqa: E402
from app.services.file_cleanup_service import ALERT_AFTER_ATTEMPTS, FileCleanupService  # noqa: E402


async def main(status_only: bool, limit: int) -> None:
    async with AsyncSessionLocal() as db:
        if not status_only:
            done = await FileCleanupService(db).retry_pending(limit=limit)
            print(f"이번에 완료한 작업: {done}개")
        pending = await db.scalar(
            select(func.count()).select_from(FileCleanupJob).where(FileCleanupJob.status == "pending")
        )
        stuck = await db.scalar(
            select(func.count())
            .select_from(FileCleanupJob)
            .where(FileCleanupJob.status == "pending", FileCleanupJob.attempts >= ALERT_AFTER_ATTEMPTS)
        )
        print(f"남은 미완료 작업: {pending}개 (그중 {ALERT_AFTER_ATTEMPTS}회 이상 실패: {stuck}개)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="파일 정리 작업 재처리")
    parser.add_argument("--status", action="store_true", help="재처리 없이 남은 작업 수만 확인")
    parser.add_argument("--limit", type=int, default=100, help="한 번에 처리할 최대 작업 수")
    args = parser.parse_args()
    asyncio.run(main(args.status, args.limit))
