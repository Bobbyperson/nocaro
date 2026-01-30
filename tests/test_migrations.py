from pathlib import Path

from alembic.config import Config

from alembic import command

REPO_ROOT = Path(__file__).resolve().parents[1]


def _alembic_config() -> Config:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    return config


def test_alembic_upgrade_downgrade(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "test.sqlite"
    db_url = f"sqlite+aiosqlite:///{db_path}"
    monkeypatch.setenv("NOCARO_DB_URL", db_url)

    config = _alembic_config()
    command.upgrade(config, "head")
    command.downgrade(config, "base")

    assert db_path.exists()
