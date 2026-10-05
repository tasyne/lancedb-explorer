import lancedb
import pandas as pd
import pyarrow as pa
from streamlit.testing.v1 import AppTest

from lance_explorer.scaling_planner import GiB
from lance_explorer.ui.pages.scaling import _health_index_rows, _health_schema_rows


def _page(tmp_path) -> AppTest:
    script = tmp_path / "scaling_page_app.py"
    script.write_text(
        "from lance_explorer.ui.pages.scaling import render\nrender()\n",
        encoding="utf-8",
    )
    return AppTest.from_file(str(script), default_timeout=20).run()


def _element_with_label(elements, label):
    return next(element for element in elements if element.label == label)


def test_scaling_page_renders_input_effects_and_load_strategy(tmp_path) -> None:
    app = _page(tmp_path)

    assert not app.exception
    assert [title.value for title in app.title] == ["Scaling Recommendations"]
    assert [tab.label for tab in app.tabs] == ["Recommendations", "Healthcheck"]
    assert "Dataset" in [heading.value for heading in app.subheader]
    assert "Recommended Load Approach" in [heading.value for heading in app.subheader]
    assert any(
        checkbox.label == "I know the average complete row size" for checkbox in app.checkbox
    )
    assert any("distributed file scan" in caption.value for caption in app.caption)
    assert any("pass-through" in caption.value for caption in app.caption)
    assert "Starter Code" in [heading.value for heading in app.subheader]
    assert {
        "Spark ingestion (recommended)",
        "Trino SQL ingestion alternative",
        "Python maintenance",
    }.issubset({status.label for status in app.status})

    _element_with_label(app.selectbox, "Load pattern").set_value("regular batch")
    app.run()

    assert any(
        "not automatically after every batch" in markdown.value for markdown in app.markdown
    )


def test_healthcheck_prompts_for_a_selected_table(tmp_path) -> None:
    app = _page(tmp_path)
    app.session_state["scaling-page-tabs"] = "Healthcheck"
    app.run()

    assert "Healthcheck" in [heading.value for heading in app.subheader]
    assert any("Select a Lance table" in message.value for message in app.info)
    assert "Dataset" not in [heading.value for heading in app.subheader]


def test_healthcheck_dataframes_have_arrow_compatible_column_types() -> None:
    snapshot = {
        "schema_fields": [
            {"name": "id", "type": "int64", "vector_dimension": None},
            {
                "name": "vector",
                "type": "fixed_size_list<item: float>[384]",
                "vector_storage": "fixed",
                "vector_dimension": 384,
            },
        ],
        "indexes": [
            {
                "name": "vector_idx",
                "index_type": "IVF_PQ",
                "columns": ["vector"],
                "num_segments": 4,
                "statistics": {"num_indexed_rows": 100, "num_unindexed_rows": 0},
            },
            {
                "name": "id_idx",
                "index_type": "BTREE",
                "columns": ["id"],
                "statistics": {"num_indexed_rows": 100, "num_unindexed_rows": 0},
            },
        ],
    }

    schema_frame = pd.DataFrame(_health_schema_rows(snapshot))
    index_frame = pd.DataFrame(_health_index_rows(snapshot))

    assert schema_frame["Dimension"].tolist() == ["-", "384"]
    assert index_frame["Segments"].tolist() == ["4", "-"]
    pa.Table.from_pandas(schema_frame)
    pa.Table.from_pandas(index_frame)


def test_scaling_page_marks_an_exceptionally_large_fragment_count(tmp_path) -> None:
    app = _page(tmp_path)
    _element_with_label(app.checkbox, "I know the average complete row size").set_value(True)
    app.run()
    _element_with_label(app.number_input, "Average complete row size (bytes)").set_value(GiB)
    app.run()

    fragments = _element_with_label(app.metric, "Fragments")
    assert "⚠" in fragments.value
    assert not app.exception


def test_scaling_code_tracks_selected_load_and_tuning_options(tmp_path) -> None:
    app = _page(tmp_path)
    spark_code = app.code[0].value

    assert "max_batch_bytes" not in spark_code
    assert "use_queued_write_buffer" not in spark_code
    assert "create_index_uncommitted" in spark_code
    assert "lance_ray" not in "\n".join(code.value for code in app.code)

    _element_with_label(app.selectbox, "Load pattern").set_value("frequent small appends")
    _element_with_label(app.checkbox, "Full-text search").set_value(True)
    _element_with_label(app.checkbox, "Phrase search required").set_value(True)
    _element_with_label(app.checkbox, "Override max_batch_bytes").set_value(True)
    _element_with_label(
        app.checkbox, "Enable experimental queued write buffer in this estimate"
    ).set_value(True)
    app.run()
    _element_with_label(app.number_input, "max_batch_bytes (MiB)").set_value(128)
    _element_with_label(app.number_input, "Queued buffer depth").set_value(3)
    app.run()

    spark_code = app.code[0].value
    assert "Frequent arrivals" in spark_code
    assert ".repartition(1)" in spark_code
    assert '.option("max_batch_bytes", 134217728)' in spark_code
    assert '.option("queue_depth", 3)' in spark_code
    assert "with_position = true" in spark_code


def test_healthcheck_inspects_the_selected_table(tmp_path) -> None:
    db = lancedb.connect(str(tmp_path / "db"))
    db.create_table("items", data=[{"id": item, "text": f"item {item}"} for item in range(20)])
    table_uri = str(tmp_path / "db" / "items.lance")
    script = tmp_path / "healthcheck_page_app.py"
    script.write_text(
        "import streamlit as st\n"
        f"st.session_state.selected_table_uri = {table_uri!r}\n"
        "st.session_state.cache_generations = {}\n"
        "st.session_state['scaling-page-tabs'] = 'Healthcheck'\n"
        "from lance_explorer.ui.pages.scaling import render\n"
        "render()\n",
        encoding="utf-8",
    )

    app = AppTest.from_file(str(script), default_timeout=20).run()

    assert not app.exception
    assert "Measured Signals" in [heading.value for heading in app.subheader]
    assert _element_with_label(app.metric, "Rows").value == "20"
    assert _element_with_label(app.metric, "Health score").value == "100/100"
