from lance_explorer import cli
from lance_explorer.demo_data import DemoTableResult


def test_cli_create_demo_data_dispatches_to_generator(monkeypatch, capsys) -> None:
    calls = {}

    def fake_create_demo_table(table_uri, *, row_count, locale, seed, version_count, overwrite):
        calls["args"] = {
            "table_uri": table_uri,
            "row_count": row_count,
            "locale": locale,
            "seed": seed,
            "version_count": version_count,
            "overwrite": overwrite,
        }
        return DemoTableResult(
            table_uri="/tmp/stars.lance",
            database_uri="/tmp",
            table_name="stars",
            row_count=row_count,
            version_count=version_count,
            locale="en_US",
        )

    monkeypatch.setattr(cli, "create_demo_table", fake_create_demo_table)

    exit_code = cli.run(
        [
            "--create-demo-data",
            "stars.lance",
            "--faker-locale",
            "usa",
            "--demo-rows",
            "12",
            "--demo-seed",
            "5",
            "--demo-versions",
            "4",
            "--overwrite-demo-data",
        ]
    )

    assert exit_code == 0
    assert calls["args"] == {
        "table_uri": "stars.lance",
        "row_count": 12,
        "locale": "usa",
        "seed": 5,
        "version_count": 4,
        "overwrite": True,
    }
    assert (
        "Created demo Lance table /tmp/stars.lance with 12 rows across 4 versions"
        in capsys.readouterr().out
    )


def test_cli_launches_streamlit_by_default(monkeypatch) -> None:
    calls = {}

    def fake_call(command):
        calls["command"] = command
        return 0

    monkeypatch.setattr(cli.subprocess, "call", fake_call)

    assert cli.run(["--server.port", "8502"]) == 0
    assert calls["command"][:4] == [cli.sys.executable, "-m", "streamlit", "run"]
    assert calls["command"][-2:] == ["--server.port", "8502"]
