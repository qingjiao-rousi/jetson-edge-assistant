# M9.1A-MD Offline Markdown RAG

M9.1A-MD provides the first offline retrieval layer for the industrial fault-assistance application. Its only fact source is the synthetic `knowledge/manuals/ax17-equipment-manual.md`; no customer or field data is included.

The builder validates the document metadata, splits only on level-two Markdown headings, assigns IDs from the fixed document ID and normalized heading, obtains actual token counts from the frozen Qwen2.5-VL tokenizer, then inserts documents and chunks in ordinal order into SQLite FTS5. Source paths and citations are repository-relative and stable. Generated `*.sqlite3` files are ignored and are not project artifacts.

The query path is keyword retrieval using FTS5 with Porter tokenization. It is explicitly not embedding or semantic retrieval. It returns original chunk text and citations; a query with no indexed term match returns `answerable=false`, empty results, and empty citations. No LLM answer is generated and no retrieved content is injected into a model in this milestone.

Citation shape:
```json
{"document_id":"AX17-MANUAL-001","chunk_id":"AX17-MANUAL-001#alarm-e42","source":"ax17-equipment-manual.md","section":"Alarm E42"}
```

M9.1B may retain the Document/Chunk/Citation contract while introducing a separately audited local embedding implementation. M9.1A does not claim semantic recall, answer quality, model grounding, performance, or deployment readiness.
