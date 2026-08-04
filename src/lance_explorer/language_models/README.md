# Packaged Lance tokenizer models

These files support offline full-text-search demos for LanceDB model-backed tokenizers.

- `jieba/default`: Mandarin-oriented Jieba files from the Jieba ecosystem, including `dict.txt`,
  `dict.txt.small`, `idf.txt`, and `stop_words.txt`.
- `lindera/ipadic`: placeholder for externally supplied Japanese IPADIC files.
- `lindera/unidic`: placeholder for externally supplied Japanese UniDic files.
- `lindera/ko-dic`: placeholder for externally supplied Korean ko-dic files.

ICU tokenizers do not need external model files. Lindera dictionaries are intentionally not
bundled because they are large third-party binary data assets. To use Lindera, supply compiled
dictionaries outside this repository and set `LANCE_LANGUAGE_MODEL_HOME` plus `LINDERA_CONFIG_PATH`.
For downloaded Jieba archives, set `LANCE_LANGUAGE_MODEL_HOME` to the extracted `language_models`
directory.

LanceDB version matters for demo defaults. Lance Explorer uses the multilingual ICU FTS preset on
LanceDB `0.34.0+`; on `0.33.x`, demo table creation falls back to the English/simple tokenizer
because older public APIs and tokenizer support are narrower. Generated index snippets include
compatibility fallbacks where the installed SDK exposes older helper methods instead of
`create_index(..., config=...)`.

To refresh from source, set `LANCE_LANGUAGE_MODEL_HOME` to this directory, install `lindera-cli`,
and use Lance's downloader:

```bash
python -m lance.download jieba
python -m lance.download lindera -l ipadic
python -m lance.download lindera -l unidic
python -m lance.download lindera -l ko-dic
```

Review the upstream dictionary licenses before redistributing packaged archives.
