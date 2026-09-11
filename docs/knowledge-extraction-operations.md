# Knowledge extraction operations

The workflow is enabled by default with `S3MP_KNOWLEDGE_EXTRACTION_ENABLED=true`.
The source object remains in its application namespace. Generated cards are written to
the configured shared bucket under `tenants/<tenant-id>/knowledge-card-output/<batch-id>`;
PostgreSQL stores only task and object metadata, and Elasticsearch is a rebuildable
projection.

## Services

Run these independent services alongside the existing file worker:

```text
python -m s3mp.knowledge.worker analysis
python -m s3mp.knowledge.worker index
```

The analysis service requires an approved OpenAI-compatible endpoint configured with
`S3MP_KNOWLEDGE_LLM_PROVIDER` (`kimi`, `deepseek`, or `glm`), model, base URL and a
secret-backed API key. The index service requires `S3MP_ELASTICSEARCH_URL` and uses
`S3MP_KNOWLEDGE_ELASTICSEARCH_INDEX` (default `s3mp-knowledge-cards-v1`).

## Monitoring

Use `/health/knowledge` for redacted configuration and queue boundaries. Alert on:

- `knowledge.analysis.dlq` or `knowledge.index.dlq` depth;
- analysis tasks in `processing` beyond the configured timeout;
- `knowledge_llm_request_failed` events;
- `knowledge_s3_batch_completed` absence while analysis queue depth grows;
- index projection failures or a growing index retry backlog.

Do not log source text, card body, API keys, or presigned URLs.

## Recovery and rollback

Stop the knowledge workers or set `S3MP_KNOWLEDGE_EXTRACTION_ENABLED=false` to stop
new task creation. Existing source files and completed S3 batches remain untouched.
After Elasticsearch recovery, rebuild one tenant with:

```text
python -m s3mp.knowledge.rebuild_index <tenant-id>
```

Only completed card Markdown objects under that tenant prefix are read. Failed analysis
tasks use the durable DLQ/replay primitive; no cancellation or manual retry endpoint is
exposed.
