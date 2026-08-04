from pathlib import Path

import pytest

from lance_explorer.codegen import TemplateRenderer


def test_connection_template_uses_runtime_storage_values_not_credentials(monkeypatch) -> None:
    monkeypatch.setenv("AWS_ENDPOINT", "http://minio.local:9000")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-west-2")
    monkeypatch.setenv("ALLOW_HTTP", "true")

    code = TemplateRenderer().render("connect", {"database_uri": "s3://bucket/database"})

    assert "UPath('s3://bucket/database')" in code
    assert "import os" in code
    assert 'AWS_ENDPOINT = os.getenv("AWS_ENDPOINT", \'http://minio.local:9000\')' in code
    assert 'AWS_DEFAULT_REGION = os.getenv("AWS_DEFAULT_REGION", \'us-west-2\')' in code
    assert 'ALLOW_HTTP = os.getenv("ALLOW_HTTP", \'true\')' in code
    assert '"endpoint": AWS_ENDPOINT' in code
    assert "AWS_ACCESS_KEY_ID" not in code
    assert "AWS_SECRET_ACCESS_KEY" not in code


def test_connection_template_can_fallback_to_aws_region(monkeypatch) -> None:
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    monkeypatch.setenv("AWS_REGION", "eu-central-1")

    code = TemplateRenderer().render("connect", {"database_uri": "s3://bucket/database"})

    assert 'AWS_DEFAULT_REGION = os.getenv("AWS_DEFAULT_REGION", \'eu-central-1\')' in code


def test_index_template_renders_runtime_configuration() -> None:
    code = TemplateRenderer().render(
        "create_index",
        {
            "table_uri": "/tmp/db/items.lance",
            "column": "text",
            "index_type": "FTS",
            "config_class": "FTS",
            "config_options": {"with_position": True},
            "needs_language_model_home": False,
            "index_name": "text_idx",
            "replace": False,
        },
    )
    assert "from lancedb.index import FTS" in code
    assert "with_position" in code
    assert "text_idx" in code


def test_jieba_index_template_configures_packaged_language_models() -> None:
    code = TemplateRenderer().render(
        "create_index",
        {
            "table_uri": "/tmp/db/items.lance",
            "column": "text",
            "index_type": "FTS",
            "config_class": "FTS",
            "config_options": {"base_tokenizer": "jieba/default"},
            "needs_language_model_home": True,
            "index_name": "jieba_idx",
            "replace": False,
        },
    )

    assert "configure_packaged_language_model('jieba/default')" in code
    assert "$LANCE_LANGUAGE_MODEL_HOME/jieba/default/dict.txt" in code
    assert "$LANCE_LANGUAGE_MODEL_HOME/jieba/default/idf.txt" in code
    assert "$LANCE_LANGUAGE_MODEL_HOME/jieba/default/stop_words.txt" in code
    assert "jieba/default" in code


def test_lindera_index_template_does_not_assume_packaged_models() -> None:
    code = TemplateRenderer().render(
        "create_index",
        {
            "table_uri": "/tmp/db/items.lance",
            "column": "text_ja",
            "index_type": "FTS",
            "config_class": "FTS",
            "config_options": {"base_tokenizer": "lindera/ipadic"},
            "needs_language_model_home": False,
            "index_name": "ja_idx",
            "replace": False,
        },
    )

    assert "configure_packaged_language_model" not in code
    assert "lindera/ipadic" in code
    assert "LINDERA_CONFIG_PATH" in code


def test_vector_index_template_renders_vector_configuration() -> None:
    code = TemplateRenderer().render(
        "create_index",
        {
            "table_uri": "/tmp/db/items.lance",
            "column": "embedding",
            "index_type": "IVF_HNSW_SQ",
            "config_class": "IvfHnswSq",
            "config_options": {
                "distance_type": "cosine",
                "num_partitions": 2,
                "max_iterations": 50,
                "sample_rate": 256,
                "m": 20,
                "ef_construction": 300,
            },
            "needs_language_model_home": False,
            "index_name": "embedding_ivf_hnsw_sq_idx",
            "replace": True,
        },
    )

    assert "from lancedb.index import IvfHnswSq" in code
    assert "distance_type" in code
    assert "ef_construction" in code
    assert "embedding_ivf_hnsw_sq_idx" in code


def test_open_table_template_uses_checkout_for_versions() -> None:
    code = TemplateRenderer().render(
        "open_table",
        {"table_uri": "/tmp/db/items.lance", "open_version": 2},
    )

    assert "db.open_table(table_path.name.removesuffix(\".lance\"))" in code
    assert "version=open_version" not in code
    assert "table.checkout(open_version)" in code


def test_insert_arrow_blob_template_renders_blob_v2_example() -> None:
    code = TemplateRenderer().render(
        "insert_arrow_blobs",
        {"table_uri": "/tmp/db/items.lance", "open_version": None},
    )

    assert "blob_field(\"headshot_full_bytes\")" in code
    assert "blob_array([full_image_bytes])" in code
    assert "data_storage_version=\"2.2\"" in code
    assert "table.add(batch)" in code


def test_insert_pandas_template_renders_dataframe_append() -> None:
    code = TemplateRenderer().render(
        "insert_pandas",
        {"table_uri": "/tmp/db/items.lance", "open_version": None},
    )

    assert "pd.DataFrame" in code
    assert "table.add(rows)" in code
    assert "embedding" in code


def test_insert_pydantic_template_renders_model_validation() -> None:
    code = TemplateRenderer().render(
        "insert_pydantic",
        {"table_uri": "/tmp/db/items.lance", "open_version": None},
    )

    assert "LanceModel" in code
    assert "Vector(64)" in code
    assert "model_dump()" in code


def test_merge_upsert_template_renders_merge_insert_builder() -> None:
    code = TemplateRenderer().render(
        "merge_upsert",
        {"table_uri": "/tmp/db/items.lance", "open_version": None},
    )

    assert 'table.merge_insert("id")' in code
    assert "when_matched_update_all" in code
    assert "when_not_matched_insert_all" in code


def test_update_rows_template_renders_predicate_update() -> None:
    code = TemplateRenderer().render(
        "update_rows",
        {"table_uri": "/tmp/db/items.lance", "open_version": None},
    )

    assert "table.update(" in code
    assert 'where="id = 1001"' in code
    assert "values_sql" in code


def test_compare_template_uses_checkout_for_versions() -> None:
    code = TemplateRenderer().render(
        "compare_tables",
        {
            "left_uri": "/tmp/left/items.lance",
            "right_uri": "/tmp/right/items.lance",
            "columns": ["id", "value"],
            "key": "id",
            "limit": 100,
            "left_version": 1,
            "right_version": 2,
        },
    )

    assert "db.open_table(path.name.removesuffix(\".lance\"))" in code
    assert "version=" not in code
    assert "table.checkout(version)" in code


def test_hybrid_query_template_uses_text_vector_and_optional_rerank() -> None:
    code = TemplateRenderer().render(
        "hybrid_query",
        {
            "table_uri": "/tmp/db/items.lance",
            "text": "apple",
            "vector": [0.1, -0.2, 0.3, 0.5],
            "vector_column": "embedding",
            "fts_column": "text",
            "columns": ["id", "text"],
            "where": "",
            "limit": 10,
            "rerank": True,
            "fts_model_id": "",
            "needs_language_model_home": False,
        },
    )

    assert 'query_type="hybrid"' in code
    assert ".vector(vector)" in code
    assert ".text('apple')" in code
    assert "from lancedb.rerankers import RRFReranker" in code
    assert 'query.rerank(RRFReranker(return_score="all"))' in code
    assert "_score" in code


def test_fts_query_template_includes_jieba_language_model_setup() -> None:
    code = TemplateRenderer().render(
        "fts_query",
        {
            "table_uri": "/tmp/db/items.lance",
            "text": "南京",
            "column": "bio",
            "columns": ["id", "bio"],
            "where": "",
            "limit": 10,
            "fts_model_id": "jieba/default",
            "needs_language_model_home": True,
        },
    )

    assert "configure_packaged_language_model('jieba/default')" in code
    assert 'os.environ["LANCE_LANGUAGE_MODEL_HOME"]' in code
    assert "language_models" in code


def test_template_context_rejects_secret_keys() -> None:
    with pytest.raises(ValueError, match="Secret-bearing"):
        TemplateRenderer().render(
            "connect",
            {"database_uri": "s3://bucket/db", "secret_key": "do-not-render"},
        )


def test_override_directory_can_replace_template(tmp_path: Path) -> None:
    packaged = (
        Path(__file__).resolve().parents[1] / "src" / "lance_explorer" / "templates" / "python"
    )
    (tmp_path / "manifest.yaml").write_text(
        (packaged / "manifest.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "connect.py.j2").write_text("override {{ database_uri }}\n", encoding="utf-8")

    code = TemplateRenderer(tmp_path).render("connect", {"database_uri": "/tmp/db"})
    assert code == "override /tmp/db\n"


def test_all_python_templates_render_as_valid_python() -> None:
    import ast

    renderer = TemplateRenderer()
    contexts = {
        "connect": {"database_uri": "/tmp/db"},
        "open_table": {"table_uri": "/tmp/db/items.lance", "open_version": None},
        "insert_arrow_blobs": {"table_uri": "/tmp/db/items.lance", "open_version": None},
        "insert_pandas": {"table_uri": "/tmp/db/items.lance", "open_version": None},
        "insert_pydantic": {"table_uri": "/tmp/db/items.lance", "open_version": None},
        "merge_upsert": {"table_uri": "/tmp/db/items.lance", "open_version": None},
        "update_rows": {"table_uri": "/tmp/db/items.lance", "open_version": None},
        "filter_query": {
            "table_uri": "/tmp/db/items.lance",
            "columns": ["id"],
            "where": "id > 0",
            "limit": 10,
        },
        "fts_query": {
            "table_uri": "/tmp/db/items.lance",
            "text": "apple",
            "column": "text",
            "columns": ["id", "text"],
            "where": "",
            "limit": 10,
            "fts_model_id": "",
            "needs_language_model_home": False,
        },
        "hybrid_query": {
            "table_uri": "/tmp/db/items.lance",
            "text": "apple",
            "vector": [0.1, -0.2, 0.3, 0.5],
            "vector_column": "embedding",
            "fts_column": "text",
            "columns": ["id", "text"],
            "where": "",
            "limit": 10,
            "rerank": False,
            "fts_model_id": "",
            "needs_language_model_home": False,
        },
        "vector_query": {
            "table_uri": "/tmp/db/items.lance",
            "vector": [0.1, 0.2],
            "column": "vector",
            "columns": ["id"],
            "where": "",
            "limit": 10,
        },
        "compare_tables": {
            "left_uri": "/tmp/left/items.lance",
            "right_uri": "/tmp/right/items.lance",
            "columns": ["id", "value"],
            "key": "id",
            "limit": 100,
            "left_version": 1,
            "right_version": None,
        },
        "create_index": {
            "table_uri": "/tmp/db/items.lance",
            "column": "id",
            "index_type": "BTREE",
            "config_class": "BTree",
            "config_options": {},
            "needs_language_model_home": False,
            "index_name": "id_idx",
            "replace": False,
        },
        "drop_index": {
            "table_uri": "/tmp/db/items.lance",
            "index_name": "id_idx",
        },
        "optimize": {
            "table_uri": "/tmp/db/items.lance",
            "cleanup_days": None,
        },
        "cleanup_versions": {
            "table_uri": "/tmp/db/items.lance",
            "older_than_days": 7,
            "delete_unverified": False,
        },
        "restore_version": {
            "table_uri": "/tmp/db/items.lance",
            "version": 2,
        },
        "drop_table": {"table_uri": "/tmp/db/items.lance"},
    }

    for template_id, context in contexts.items():
        ast.parse(renderer.render(template_id, context), filename=template_id)
