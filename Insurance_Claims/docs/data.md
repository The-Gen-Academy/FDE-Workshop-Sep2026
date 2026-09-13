# Data storage

Use SQLite for development on one computer, Firestore for records shared
with the deployed agent, and GCS for cloud evidence files. Storage
selection is explicit; setting an evidence bucket does not select the
records backend.

## Configuration

Settings are loaded from the repository `.env`, or the file specified by
`CLAIMS_ENV_FILE`. Exported environment variables take precedence. Deployed
agents receive explicit runtime settings rather than a bundled `.env`.

| Variable | Purpose |
| --- | --- |
| `CLAIMS_STORE` | `local` (default) or `firestore` |
| `CLAIMS_DATA_DIR` | Local writable data directory; defaults to `.local/data` |
| `GOOGLE_CLOUD_PROJECT` | Project containing the Firestore database |
| `CLAIMS_FIRESTORE_DATABASE` | Firestore database ID; defaults to `(default)` |
| `CLAIMS_EVIDENCE_BUCKET` | GCS bucket for photos; unset uses local files |
| `CLAIMS_EVIDENCE_PREFIX` | Optional object prefix within the evidence bucket |
| `CLAIMS_GCS_BUCKET` | Compatibility alias for the evidence bucket |

Firestore configuration and deployment parameters are covered in the
[deployment guide](deployment.md). A legacy GCS JSON bucket is never
automatically treated as the live records store.

## Records

The claims schema preserves existing collection names and document IDs.
The customer portal also stores session metadata and transcripts. Local
SQLite stores these JSON-shaped records with atomic transactions;
Firestore stores individual documents.

| Collection | Document ID | Contains |
| --- | --- | --- |
| `policies` | Policy number | Coverage, exclusions, drivers, and limits |
| `claim_history` | Policyholder ID | Prior claims used by risk checks |
| `parts_pricing` | Part key | Parts cost and labor estimates |
| `vin_claims` | VIN | Cross-policyholder claim references |
| `escalations` | Claim ID | Adjuster handoff, recommendation, and status |
| `claims_log` | Claim ID | Executed outcome and decision details |
| `client_sessions` | Session ID | Customer portal session metadata and transcript |

The separate history and VIN indexes remain for compatibility. A later
schema change could replace growing history arrays with individual claim
documents; that is separate from this storage refactor.

Evidence records contain references and metadata. Photo bytes remain
outside the database. Local paths work only when the processes share that
filesystem; use GCS evidence when the agent runs on Vertex.

## Seed or import

Checked-in examples live in `data/seed/`. Runtime writes go to `.local/`
or the selected cloud backend. Run these commands from the repository root:

```bash
# Preview records and validate bundled photos.
uv run --package claims-core claims-data seed --source data/seed --with-evidence

# Copy records and photos; existing document IDs are skipped.
uv run --package claims-core claims-data seed --source data/seed --apply --with-evidence
```

`--with-evidence` resolves historical local photo paths against the bundled
`photos/` directory, copies images to the configured evidence backend, and
rewrites references in imported records. It never changes the source JSON
or photos. Preview validates files without copying/uploading. Omit the flag
for a records-only import.

To import records from the previous one-JSON-object-per-collection GCS store:

```bash
uv run --package claims-core claims-data import-gcs --bucket OLD_BUCKET
```

Add `--prefix`, including any trailing `/`, if the old JSON objects are
under a prefix. Review the
preview, then add `--apply` to write to the configured destination. Reading
a GCS import requires credentials even during preview. The importer does
not delete the source objects.

Set `CLAIMS_STORE=firestore` and the intended project/database before
applying a cloud import. `import-gcs` copies records only; moving any
referenced evidence is a separate operation. Creating infrastructure and
granting access are also separate operations; deployment does not silently
perform a migration.
