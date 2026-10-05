import os

from lance_explorer import cli
from lance_explorer.demo_data import DemoTableResult


def test_cli_create_demo_data_dispatches_to_generator(monkeypatch, capsys) -> None:
    calls = {}

    def fake_create_demo_table(
        table_uri,
        *,
        row_count,
        locale,
        seed,
        version_count,
        overwrite,
        namespace_path,
    ):
        calls["args"] = {
            "table_uri": table_uri,
            "row_count": row_count,
            "locale": locale,
            "seed": seed,
            "version_count": version_count,
            "overwrite": overwrite,
            "namespace_path": namespace_path,
        }
        return DemoTableResult(
            table_uri="/tmp/stars.lance",
            database_uri="/tmp",
            table_name="stars",
            row_count=row_count,
            version_count=version_count,
            locale="en_US",
            namespace_table_ref="lance-ns://dir/demo/movie_stars/stars?root=%2Ftmp",
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
        "namespace_path": "demo/movie_stars",
    }
    output = capsys.readouterr().out
    assert "Created demo Lance table /tmp/stars.lance with 12 rows across 4 versions" in output
    assert "headshot_thumbnail_bytes, headshot_full_bytes" in output
    assert "Namespace copy: lance-ns://dir/demo/movie_stars/stars?root=%2Ftmp" in output


def test_cli_launches_streamlit_by_default(monkeypatch) -> None:
    calls = {}

    def fake_call(command, *, env):
        calls["command"] = command
        calls["env"] = env
        return 0

    monkeypatch.setattr(cli.subprocess, "call", fake_call)
    monkeypatch.delenv("LANCE_INCLUDE_VECTOR_CENTROIDS", raising=False)

    assert cli.run(["--server.port", "8502"]) == 0
    assert calls["command"][:4] == [cli.sys.executable, "-m", "streamlit", "run"]
    assert calls["command"][-2:] == ["--server.port", "8502"]
    package_root = str(cli.Path(cli.__file__).resolve().parent.parent)
    assert calls["env"]["PYTHONPATH"].split(os.pathsep)[0] == package_root
    assert calls["env"]["LANCE_INCLUDE_VECTOR_CENTROIDS"] == "false"


def test_cli_preserves_explicit_vector_centroid_setting(monkeypatch) -> None:
    calls = {}

    def fake_call(command, *, env):
        calls["env"] = env
        return 0

    monkeypatch.setattr(cli.subprocess, "call", fake_call)
    monkeypatch.setenv("LANCE_INCLUDE_VECTOR_CENTROIDS", "true")

    assert cli.run([]) == 0
    assert calls["env"]["LANCE_INCLUDE_VECTOR_CENTROIDS"] == "true"
