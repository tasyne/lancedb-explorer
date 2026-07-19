from streamlit.testing.v1 import AppTest


def test_default_page_renders_without_exception(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LANCE_EXPLORER_HOME_URI", str(tmp_path))
    app = AppTest.from_file("src/lance_explorer/app.py", default_timeout=20)
    app.run()

    assert not app.exception
    assert [title.value for title in app.title] == ["Explorer"]
    assert "Location" in [caption.value for caption in app.caption]
