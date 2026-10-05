from streamlit.testing.v1 import AppTest


def test_schema_section_renders_summary_and_standalone_model() -> None:
    script = '''
from lance_explorer.config import AppConfig
import lance_explorer.ui.pages.table as page

page.cached_lance_model_export = lambda *args: {
    "model_name": "ItemsModel",
    "source": (
        "from lancedb.pydantic import LanceModel\\n\\n"
        "class ItemsModel(LanceModel):\\n"
        "    id: int\\n"
    ),
    "notes": [],
}
snapshot = {
    "schema": [
        {
            "path": "id",
            "type": "int64",
            "nullable": False,
            "metadata": {},
            "ordinal": 0,
        },
        {
            "path": "profile",
            "type": "struct<name: string>",
            "nullable": True,
            "metadata": {},
            "ordinal": 1,
        },
        {
            "path": "profile.name",
            "type": "string",
            "nullable": True,
            "metadata": {},
            "ordinal": 0,
        },
    ],
    "schema_string": "id: int64 not null",
    "table_metadata": {},
    "name": "items",
    "version": 3,
}
page._render_schema(
    AppConfig(home_uri=".", template_override_dir=None),
    "items.lance",
    None,
    0,
    snapshot,
)
'''

    app = AppTest.from_string(script, default_timeout=20).run()

    assert not app.exception
    assert [metric.label for metric in app.metric] == [
        "Fields",
        "Nullable",
        "Nested fields",
        "Vector fields",
    ]
    assert [heading.value for heading in app.subheader] == ["Fields", "Standalone LanceModel"]
    assert len(app.dataframe) == 1
    assert len(app.code) == 2
