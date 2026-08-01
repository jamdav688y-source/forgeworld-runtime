import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from config import Settings, SourceLocation
from database import Database


@pytest.fixture()
def project_root(tmp_path: Path) -> Path:
    (tmp_path / "runtime" / "previews").mkdir(parents=True)
    (tmp_path / "runtime" / "backups").mkdir(parents=True)
    return tmp_path


@pytest.fixture()
def settings(project_root: Path) -> Settings:
    s = Settings()
    s.database_path = str(project_root / "runtime" / "database" / "test.db")
    return s


@pytest.fixture()
def db(settings: Settings, project_root: Path):
    database = Database(settings, project_root)
    database.connect()
    yield database
    database.close()
