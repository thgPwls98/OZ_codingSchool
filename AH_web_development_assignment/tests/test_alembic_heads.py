"""Alembic 마이그레이션이 한 줄로 이어져 있는지 확인한다 (multiple heads 방지)

팀원끼리 같은 리비전 뒤에 각자 마이그레이션을 만들어 둘 다 머지하면 head가 두 개가 되어
`alembic upgrade head`가 실패한다. 이 테스트가 실패하면 나중에 머지되는 쪽 파일의
down_revision을 먼저 머지된 마이그레이션의 revision으로 바꾼다.

실행: python -m unittest tests.test_alembic_heads -v
"""

import unittest
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class AlembicHeadsTests(unittest.TestCase):
    def test_single_head(self):
        config = Config(str(PROJECT_ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
        heads = ScriptDirectory.from_config(config).get_heads()
        self.assertEqual(
            len(heads), 1,
            f"마이그레이션 head가 {len(heads)}개입니다: {heads}. "
            "나중에 머지되는 마이그레이션의 down_revision을 다른 head로 바꿔 한 줄로 이어주세요.",
        )


if __name__ == "__main__":
    unittest.main()
