# Example data

`seed/` contains the original JSON records: policies, parts prices, claim
history, VIN references, adjuster handoffs, and outcomes. Its `photos/`
directory holds three example WEBP images. Treat these files as import
sources; runtime writes belong in `.local/data/` or Firestore.

```bash
uv run --package claims-core claims-data seed --source data/seed --apply --with-evidence
```

`--with-evidence` resolves old photo references against the bundled images,
copies them to the configured local or GCS evidence location, and updates
the imported references. Original JSON and photos stay unchanged. Omit
`--apply` to preview; omit `--with-evidence` to import records only.

Existing record IDs are skipped. Fresh submissions use the same configured
evidence location.

See [data storage](../docs/data.md) for backend selection and legacy imports.
