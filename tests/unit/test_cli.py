from __future__ import annotations

import pytest

from stillhead._internal.cli import (
    DATABASE_URL_VARIABLE,
    format_status_line,
    load_module,
    main,
)
from stillhead.errors import (
    MalformedModuleReference,
    NotAModuleMigrations,
)

ALPHA = "mod_alpha.module:MODULE"
BETA = "mod_app.modules.beta.module:MODULE"
NOTES = "mod_local.notes.module:MODULE"


# --- Naming a module --------------------------------------------------------


def test_imports_a_module_definition_by_path() -> None:
    module = load_module(ALPHA)

    assert module.name == "alpha"
    assert module.table_prefix == "alpha_"


def test_imports_a_module_that_lives_inside_an_application() -> None:
    assert load_module(BETA).name == "beta"


def test_imports_a_module_definition_from_a_flat_package() -> None:
    assert load_module(NOTES).table_prefix == "notes_"


def test_a_module_is_named_on_its_own() -> None:
    assert load_module(BETA).name == "beta"


@pytest.mark.parametrize(
    "reference", ["mod_alpha.module", ":MODULE", "mod_alpha.module:"]
)
def test_rejects_a_reference_that_is_not_package_colon_attribute(
    reference: str,
) -> None:
    with pytest.raises(MalformedModuleReference):
        load_module(reference)


def test_rejects_a_reference_to_something_that_is_not_a_module_definition() -> None:
    with pytest.raises(NotAModuleMigrations, match="MetaData"):
        load_module("mod_alpha.models:metadata")


# --- Failures reported, not raised ------------------------------------------


def test_reports_a_missing_database_url(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(DATABASE_URL_VARIABLE, raising=False)

    assert main(["current", "--module", ALPHA]) == 1
    assert DATABASE_URL_VARIABLE in capsys.readouterr().err


def test_a_malformed_module_is_reported_not_raised(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(DATABASE_URL_VARIABLE, "postgresql+psycopg://unused/unused")

    assert main(["current", "--module", "mod_alpha.module"]) == 1
    assert "package.module:ATTRIBUTE" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("reference", "expected"),
    [
        ("mod_alpha.module:NOPE", "has no attribute 'NOPE'"),
        ("mod_alpha.models:metadata", "not a ModuleMigrations"),
    ],
)
def test_a_bad_module_reference_is_reported_not_raised(
    reference: str,
    expected: str,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATABASE_URL_VARIABLE, "postgresql+psycopg://unused/unused")

    assert main(["current", "--module", reference]) == 1
    assert expected in capsys.readouterr().err


def test_status_with_no_modules_says_what_it_needs(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(DATABASE_URL_VARIABLE, "postgresql+psycopg://unused/unused")

    assert main(["status"]) == 1

    message = capsys.readouterr().err
    assert "package.module:ATTRIBUTE" in message
    assert "at least one" in message


def test_status_takes_module_more_than_once(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(DATABASE_URL_VARIABLE, raising=False)

    assert main(["status", "--module", ALPHA, "--module", NOTES]) == 1
    assert DATABASE_URL_VARIABLE in capsys.readouterr().err


# --- The status line --------------------------------------------------------


def test_the_status_line_reports_a_module_that_is_up_to_date() -> None:
    line = format_status_line(
        "alpha", applied="0001_alpha", head="0001_alpha", pending=0
    )

    assert line.split() == [
        "alpha",
        "db=0001_alpha",
        "head=0001_alpha",
        "up",
        "to",
        "date",
    ]


def test_the_status_line_reports_a_module_the_database_has_never_seen() -> None:
    line = format_status_line("notes", applied=None, head="0001_notes", pending=1)

    assert line.split() == ["notes", "db=(none)", "head=0001_notes", "1", "pending"]
