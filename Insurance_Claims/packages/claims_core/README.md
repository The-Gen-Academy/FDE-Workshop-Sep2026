# Claims core

Shared Python code for the ADK agent and local portals. It owns policy
lookup, coverage and risk checks, repair estimates, recommendations,
adjuster decisions, and record/evidence storage. It does not depend on ADK
or FastAPI.

This separation gives the agent and adjuster portal the same rules without
requiring the portal to import the agent. Existing thresholds and outcome
rules are preserved; see the [claims handling policy](../../docs/claims_handling_policy.md).

## Storage

- `CLAIMS_STORE=local`: SQLite at `.local/data/claims.sqlite3`.
- `CLAIMS_STORE=firestore`: one Firestore document per record.
- Evidence: local files, or GCS when `CLAIMS_EVIDENCE_BUCKET` is set.

The JSON files under `data/seed/` are import sources. GCS JSON collections
are supported only as a legacy import source. See [data storage](../../docs/data.md)
for configuration and migration details.

## Seed example records

Run from the repository root:

```bash
uv run --package claims-core claims-data seed --source data/seed --with-evidence
uv run --package claims-core claims-data seed --source data/seed --with-evidence --apply
```

The first command previews the import; the second writes to the configured
store. Existing record IDs are skipped by default.

`--with-evidence` validates bundled photos during preview and copies them
with `--apply`, rewriting references in newly imported records. Existing
records are skipped, including their references; a rerun cannot repair an
earlier records-only import. The original seed files stay unchanged.
