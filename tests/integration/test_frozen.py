from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).parent.parent / "fixtures"

BOOT_SCRIPT = '''
"""A minimal frozen application: migrate, then use the database."""

import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

from stillhead import apply_pending, versions_dir
from mod_local.notes.module import MODULE as NOTES
from mod_local.sync.module import MODULE as SYNC

print("frozen", getattr(sys, "frozen", False))
print("versions_dir", versions_dir("mod_local.notes"))

engine = create_engine(f"sqlite+pysqlite:///{Path(sys.argv[1])}")
apply_pending([SYNC, NOTES], engine)

with engine.connect() as connection:
    print("tables", sorted(inspect(connection).get_table_names()))
    connection.execute(
        text("INSERT OR REPLACE INTO notes_note (id, body) VALUES ('n', 'b')")
    )
    connection.commit()

print("DONE")
'''

# Only the versions directories. The stillhead hook adds the rest.
SPEC = """
a = Analysis(
    ['boot.py'],
    pathex=[{fixtures!r}],
    datas=[
        ({notes!r}, 'mod_local/notes/versions'),
        ({sync!r}, 'mod_local/sync/versions'),
    ],
    hiddenimports=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='boot', console=True)
coll = COLLECT(exe, a.binaries, a.datas, name='boot')
"""


@pytest.fixture(scope="module")
def frozen_application(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """Build the bundle once, and return the path of the executable."""
    if shutil.which("pyinstaller") is None:
        pytest.skip(
            "pyinstaller is not on PATH, so the frozen bundle cannot be built. "
            "Every other tier still ran. `mise run deps:sync` installs it."
        )

    source = tmp_path_factory.mktemp("frozen-source")
    (source / "boot.py").write_text(BOOT_SCRIPT)
    (source / "boot.spec").write_text(
        SPEC.format(
            fixtures=str(FIXTURES),
            notes=str(FIXTURES / "mod_local" / "notes" / "versions"),
            sync=str(FIXTURES / "mod_local" / "sync" / "versions"),
        )
    )

    # A one-directory build. Run from the source directory, so the spec finds boot.py.
    build = tmp_path_factory.mktemp("frozen-dist")
    subprocess.run(
        [
            "pyinstaller",
            str(source / "boot.spec"),
            "--noconfirm",
            "--distpath",
            str(build / "dist"),
            "--workpath",
            str(build / "work"),
        ],
        cwd=str(source),
        check=True,
    )
    yield build / "dist" / "boot" / "boot"


def _run(executable: Path, database: Path) -> str:
    result = subprocess.run(
        [str(executable), str(database)],
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    assert result.returncode == 0, (
        f"the frozen application failed:\n{result.stdout}\n{result.stderr}"
    )
    return result.stdout


def test_a_frozen_application_migrates_its_database(
    frozen_application: Path, tmp_path: Path
) -> None:
    output = _run(frozen_application, tmp_path / "frozen.db")

    assert "frozen True" in output
    assert "DONE" in output
    assert "notes_note" in output
    assert "sync_link" in output


def test_versions_dir_resolves_inside_the_bundle(
    frozen_application: Path, tmp_path: Path
) -> None:
    output = _run(frozen_application, tmp_path / "resolve.db")

    resolved = next(
        line.split(" ", 1)[1]
        for line in output.splitlines()
        if line.startswith("versions_dir ")
    )
    assert resolved.endswith(str(Path("mod_local") / "notes" / "versions"))
    assert Path(resolved).is_absolute()


def test_running_it_twice_is_a_no_op(frozen_application: Path, tmp_path: Path) -> None:
    database = tmp_path / "twice.db"

    _run(frozen_application, database)
    output = _run(frozen_application, database)

    assert "DONE" in output


def test_the_interpreter_under_test_is_not_the_frozen_one() -> None:
    assert not getattr(sys, "frozen", False)
