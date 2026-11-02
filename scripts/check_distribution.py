"""Install the built wheel offline in isolation and exercise packaged migrations."""

import os
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile
from pathlib import Path

from prepare_wheelhouse import prepare_wheelhouse

root = Path(__file__).resolve().parents[1]
project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
name = project["name"].replace("-", "_")
wheel = next((root / "dist").glob(f"{name}-{project['version']}-*.whl"))
with tarfile.open(root / "dist" / f"{name}-{project['version']}.tar.gz") as source:
    assert not any(
        any(
            part in {".venv", ".aws", ".codex", "__pycache__"}
            for part in Path(member.name).parts
        )
        or member.name.endswith((".db", ".env"))
        for member in source.getmembers()
    )
with zipfile.ZipFile(wheel) as archive:
    names = archive.namelist()
    assert "notify_kit/py.typed" in names
    assert "notify_kit/migrations/versions/nk_0002_worker_lifecycle.py" in names
    assert "notify_kit/migrations/versions/nk_0003_provider_generations.py" in names
    assert not any(name.endswith((".db", ".env")) for name in names)

with tempfile.TemporaryDirectory(prefix="notify-kit-wheel-") as temporary:
    directory = Path(temporary)
    wheelhouse = directory / "wheelhouse"
    prepare_wheelhouse("notify-kit", wheelhouse)
    environment = directory / "venv"
    subprocess.run(
        ["uv", "venv", "--python", sys.executable, str(environment)], check=True
    )
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run(
        [
            "uv",
            "pip",
            "install",
            "--offline",
            "--no-index",
            "--find-links",
            str(wheelhouse),
            "--python",
            str(python),
            str(wheel),
        ],
        check=True,
    )
    check = directory / "check.py"
    check.write_text("""
import asyncio
import tempfile
import tarfile
import tomllib
from importlib.resources import files
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import create_async_engine
import notify_kit
from notify_kit import DatabaseStorage

assert "site-packages" in notify_kit.__file__
assert files("notify_kit").joinpath("py.typed").is_file()

async def main():
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        (directory / "env.py").write_text("from alembic import context\\ncontext.configure(connection=context.config.attributes['connection'])\\nwith context.begin_transaction():\\n    context.run_migrations()\\n")
        config = Config()
        config.set_main_option("script_location", str(directory))
        config.set_main_option("path_separator", "newline")
        config.set_main_option("version_locations", "notify_kit:migrations/versions")
        url = f"sqlite+aiosqlite:///{directory / 'jobs.db'}"
        engine = create_async_engine(url)
        def upgrade(connection):
            config.attributes["connection"] = connection
            command.upgrade(config, "heads")
        try:
            async with engine.begin() as connection:
                await connection.run_sync(upgrade)
        finally:
            await engine.dispose()
        storage = DatabaseStorage(url=url)
        try:
            await storage.initialize()
            await storage.templates.create(label="smoke", definition={"body": "installed wheel"})
            assert (await storage.templates.get("smoke")).definition == {"body": "installed wheel"}
        finally:
            await storage.aclose()

asyncio.run(main())
print("Installed wheel, typing metadata, migrations and SQLite CRUD verified")
""")
    subprocess.run([str(python), "-I", str(check)], cwd=directory, check=True)
