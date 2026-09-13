# Deploy Vertex AI, Cloud Storage, and Firestore

This guide provisions the Google Cloud resources used by this repository,
loads the sample claims into Firestore and Cloud Storage, deploys the ADK
workflow to Vertex AI Agent Engine, and connects the local portals to it.

Only the agent is deployed. The customer and adjuster portals continue to run
locally; this repository does not include a Cloud Run deployment.

## What is deployed

| Component | Purpose |
| --- | --- |
| Vertex AI Agent Engine | Hosts `insurance_claim_agent` and `claims-core` |
| Firestore in Native mode | Stores policies, claims, escalations, and portal sessions |
| GCS evidence bucket | Stores customer damage photos |
| GCS staging bucket | Temporarily stages the Agent Engine deployment bundle |

Keep the evidence and staging buckets separate. The staging bucket contains
application artifacts, while the evidence bucket contains claim data.

## Prerequisites

- A billed Google Cloud project.
- Google Cloud CLI (`gcloud`) and `uv` installed locally.
- Python 3.12, which is required by the deployment serialization check.
- Permission to enable APIs, create a service account, create GCS buckets and
  a Firestore database, and grant IAM roles. If you do not administer the
  project, have an administrator run the provisioning and IAM sections.
- A Vertex AI Agent Engine region. The examples use `us-central1`. The
  configured `gemini-3.6-flash` model is served from the Vertex AI `global`
  endpoint, so the agent pins its model client to `global` regardless of the
  Agent Engine region (override with `CLAIMS_MODEL_LOCATION` if needed).

Run all repository commands from the repository root.

## 1. Choose resource names

Set these variables in the shell used for provisioning and deployment. GCS
bucket names are globally unique, so add a suffix if either name is taken.
Use the same Google account for `CLAIMS_OPERATOR_EMAIL` and local Application
Default Credentials unless your organization has a different IAM design.

```bash
export CLAIMS_PROJECT_ID="your-project-id"
export CLAIMS_REGION="us-central1"
export CLAIMS_FIRESTORE_DATABASE="(default)"
export CLAIMS_EVIDENCE_BUCKET="your-project-id-claims-evidence"
export CLAIMS_STAGING_BUCKET="your-project-id-claims-agent-staging"
export CLAIMS_EVIDENCE_PREFIX="dev"
export CLAIMS_RUNTIME_SA_NAME="insurance-claims-agent"
export CLAIMS_RUNTIME_SA="${CLAIMS_RUNTIME_SA_NAME}@${CLAIMS_PROJECT_ID}.iam.gserviceaccount.com"
export CLAIMS_OPERATOR_EMAIL="you@example.com"
```

The Firestore and bucket locations cannot be changed in place after creation.
For a production deployment, choose locations based on residency, latency,
availability, and recovery requirements rather than copying the example.

## 2. Authenticate and enable APIs

The Google Cloud CLI and Google client libraries use separate local
credentials. Authenticate both:

```bash
gcloud auth login
gcloud config set project "$CLAIMS_PROJECT_ID"
gcloud auth application-default login
gcloud auth application-default set-quota-project "$CLAIMS_PROJECT_ID"
```

Enable the APIs used directly by the application and deployment script:

```bash
gcloud services enable \
  aiplatform.googleapis.com \
  firestore.googleapis.com \
  storage.googleapis.com \
  --project="$CLAIMS_PROJECT_ID"
```

Cloud Logging is enabled in most projects. Enable the optional Agent Engine
observability APIs if your organization wants traces and metrics:

```bash
gcloud services enable \
  logging.googleapis.com \
  monitoring.googleapis.com \
  cloudtrace.googleapis.com \
  telemetry.googleapis.com \
  --project="$CLAIMS_PROJECT_ID"
```

## 3. Create Firestore

First check whether the intended database already exists:

```bash
gcloud firestore databases describe \
  --database="$CLAIMS_FIRESTORE_DATABASE" \
  --project="$CLAIMS_PROJECT_ID"
```

If it does not exist, create a Firestore Native database. Do not run this
command against a project whose existing Datastore/Firestore mode or location
you have not checked.

```bash
gcloud firestore databases create \
  --database="$CLAIMS_FIRESTORE_DATABASE" \
  --location="$CLAIMS_REGION" \
  --type=firestore-native \
  --project="$CLAIMS_PROJECT_ID"
```

Consider adding `--delete-protection` for a non-disposable environment.
Firestore collections are created automatically when the seed command writes
their first documents; there is no separate schema deployment.

## 4. Create the GCS buckets

Create private buckets with uniform bucket-level access and public access
prevention:

```bash
gcloud storage buckets create "gs://${CLAIMS_EVIDENCE_BUCKET}" \
  --project="$CLAIMS_PROJECT_ID" \
  --location="$CLAIMS_REGION" \
  --default-storage-class=STANDARD \
  --uniform-bucket-level-access \
  --public-access-prevention
```

```bash
gcloud storage buckets create "gs://${CLAIMS_STAGING_BUCKET}" \
  --project="$CLAIMS_PROJECT_ID" \
  --location="$CLAIMS_REGION" \
  --default-storage-class=STANDARD \
  --uniform-bucket-level-access \
  --public-access-prevention
```

These commands fail safely if a bucket with that globally unique name already
exists. Inspect an existing bucket before reusing it:

```bash
gcloud storage buckets describe "gs://${CLAIMS_EVIDENCE_BUCKET}"
gcloud storage buckets describe "gs://${CLAIMS_STAGING_BUCKET}"
```

## 5. Create the runtime identity and grant IAM access

The custom runtime service account is the identity used by the deployed agent.
Create it once:

```bash
gcloud iam service-accounts create "$CLAIMS_RUNTIME_SA_NAME" \
  --display-name="Insurance claims Agent Engine runtime" \
  --project="$CLAIMS_PROJECT_ID"
```

Grant the runtime access to Vertex AI and read/write access to Firestore:

```bash
gcloud projects add-iam-policy-binding "$CLAIMS_PROJECT_ID" \
  --member="serviceAccount:${CLAIMS_RUNTIME_SA}" \
  --role="roles/aiplatform.user"
```

```bash
gcloud projects add-iam-policy-binding "$CLAIMS_PROJECT_ID" \
  --member="serviceAccount:${CLAIMS_RUNTIME_SA}" \
  --role="roles/datastore.user"
```

Grant it read/write object access to claim evidence and read access to staged
deployment artifacts:

```bash
gcloud storage buckets add-iam-policy-binding \
  "gs://${CLAIMS_EVIDENCE_BUCKET}" \
  --member="serviceAccount:${CLAIMS_RUNTIME_SA}" \
  --role="roles/storage.objectUser"
```

```bash
gcloud storage buckets add-iam-policy-binding \
  "gs://${CLAIMS_STAGING_BUCKET}" \
  --member="serviceAccount:${CLAIMS_RUNTIME_SA}" \
  --role="roles/storage.objectViewer"
```

The operator deploys and invokes the agent, seeds Firestore and GCS, and runs
the local portals. Grant that account the following access:

```bash
gcloud projects add-iam-policy-binding "$CLAIMS_PROJECT_ID" \
  --member="user:${CLAIMS_OPERATOR_EMAIL}" \
  --role="roles/aiplatform.user"
```

```bash
gcloud projects add-iam-policy-binding "$CLAIMS_PROJECT_ID" \
  --member="user:${CLAIMS_OPERATOR_EMAIL}" \
  --role="roles/datastore.user"
```

```bash
gcloud storage buckets add-iam-policy-binding \
  "gs://${CLAIMS_EVIDENCE_BUCKET}" \
  --member="user:${CLAIMS_OPERATOR_EMAIL}" \
  --role="roles/storage.objectUser"
```

The deployment script checks bucket metadata and the Vertex SDK writes the
bundle, so the operator needs bucket administration on the staging bucket:

```bash
gcloud storage buckets add-iam-policy-binding \
  "gs://${CLAIMS_STAGING_BUCKET}" \
  --member="user:${CLAIMS_OPERATOR_EMAIL}" \
  --role="roles/storage.admin"
```

Finally, let the operator deploy workloads as the runtime service account:

```bash
gcloud iam service-accounts add-iam-policy-binding "$CLAIMS_RUNTIME_SA" \
  --project="$CLAIMS_PROJECT_ID" \
  --member="user:${CLAIMS_OPERATOR_EMAIL}" \
  --role="roles/iam.serviceAccountUser"
```

These commands assume the service account, buckets, and Agent Engine are in the
same project. Cross-project service accounts and staging buckets require
additional service-agent permissions and organization-policy checks.

## 6. Install and validate the deployment bundle

Install the locked workspace dependencies:

```bash
uv sync --all-packages
```

Build and inspect the exact bundle without calling Google Cloud:

```bash
uv run --package insurance-claim-agent python agent/deploy.py \
  --project "$CLAIMS_PROJECT_ID" \
  --location "$CLAIMS_REGION" \
  --staging-bucket "$CLAIMS_STAGING_BUCKET" \
  --service-account "$CLAIMS_RUNTIME_SA" \
  --evidence-bucket "$CLAIMS_EVIDENCE_BUCKET" \
  --evidence-prefix "$CLAIMS_EVIDENCE_PREFIX" \
  --database "$CLAIMS_FIRESTORE_DATABASE" \
  --display-name insurance-claims \
  --dry-run
```

The script exports locked agent dependencies, builds the agent and
`claims-core` wheels under `dist/agent-engine/`, checks that local portals and
`.env` files are excluded, and verifies ADK application serialization. A dry
run may download Python build dependencies, but it does not authenticate,
inspect cloud resources, or deploy anything.

## 7. Seed Firestore and upload sample evidence

Export the cloud storage settings used by `claims-core`:

```bash
export GOOGLE_CLOUD_PROJECT="$CLAIMS_PROJECT_ID"
export CLAIMS_STORE="firestore"
```

The database, evidence bucket, and evidence prefix were already exported in
step 1. If you opened a new shell, repeat step 1 before continuing.

Preview the import first. Preview validates records and bundled photos without
writing either backend:

```bash
uv run --package claims-core claims-data seed \
  --source data/seed \
  --with-evidence
```

Apply it after reviewing the counts:

```bash
uv run --package claims-core claims-data seed \
  --source data/seed \
  --with-evidence \
  --apply
```

The import creates only missing document IDs and can be rerun safely. Existing
records are skipped rather than overwritten. `--with-evidence` uploads the
bundled images and writes their resulting `gs://` references into Firestore.
See [data storage](data.md#seed-or-import) for legacy GCS JSON imports.

## 8. Deploy the agent to Vertex AI

Run the same validated command with `--deploy`:

```bash
uv run --package insurance-claim-agent python agent/deploy.py \
  --project "$CLAIMS_PROJECT_ID" \
  --location "$CLAIMS_REGION" \
  --staging-bucket "$CLAIMS_STAGING_BUCKET" \
  --service-account "$CLAIMS_RUNTIME_SA" \
  --evidence-bucket "$CLAIMS_EVIDENCE_BUCKET" \
  --evidence-prefix "$CLAIMS_EVIDENCE_PREFIX" \
  --database "$CLAIMS_FIRESTORE_DATABASE" \
  --display-name insurance-claims \
  --deploy
```

The successful command ends with a resource name similar to:

```text
AGENT_ENGINE_ID=projects/your-project-id/locations/us-central1/reasoningEngines/your-engine-id
```

Save the complete value. `agent/deploy.py` creates a new Agent Engine resource
on each deployment; it does not update an existing resource.

## 9. Connect the local portals

Copy `.env.example` to `.env` if needed, then configure the cloud backend with
the resource ID returned by deployment:

```dotenv
AGENT_BACKEND=vertex
GOOGLE_GENAI_USE_VERTEXAI=TRUE
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_CLOUD_LOCATION=us-central1
AGENT_ENGINE_ID=projects/your-project-id/locations/us-central1/reasoningEngines/your-engine-id
CLAIMS_STORE=firestore
CLAIMS_FIRESTORE_DATABASE=(default)
CLAIMS_EVIDENCE_BUCKET=your-project-id-claims-evidence
CLAIMS_EVIDENCE_PREFIX=dev
```

The local processes use Application Default Credentials; no service-account
key is required or recommended. The deployment script passes matching settings
to the Agent Engine runtime and never uploads the repository `.env`.

Start the portals in separate terminals:

```bash
uv run --package claims-local-apps python -m uvicorn client_portal.app:app \
  --port 8002 --reload
```

```bash
uv run --package claims-local-apps python -m uvicorn adjuster_portal.app:app \
  --port 8001 --reload
```

Open <http://localhost:8002> for customer chat and
<http://localhost:8001> for the adjuster queue. The portals have no login and
must remain bound to localhost unless authentication is added.

## 10. Verify the deployment

Confirm the database and buckets:

```bash
gcloud firestore databases describe \
  --database="$CLAIMS_FIRESTORE_DATABASE" \
  --project="$CLAIMS_PROJECT_ID"
```

```bash
gcloud storage ls \
  "gs://${CLAIMS_EVIDENCE_BUCKET}/${CLAIMS_EVIDENCE_PREFIX}/photos/**"
```

Then submit a test claim in the customer portal and check that:

1. The deployed agent responds and the conversation can continue across turns.
2. The claim appears in the adjuster queue when the workflow escalates it.
3. Uploaded evidence can be viewed from the adjuster portal.
4. New `client_sessions`, `claims_log`, and (when applicable) `escalations`
   documents appear in Firestore.

Run the local checks before promoting a new deployment:

```bash
uv run --all-packages pytest
uv run --all-packages ruff check .
uv run --all-packages ruff format --check .
```

For a new release, deploy again, replace `AGENT_ENGINE_ID` in `.env`, restart
the customer portal, test the new resource, and only then remove the old Agent
Engine resource. Deleting an Agent Engine does not delete Firestore data or
either GCS bucket.

## Troubleshooting

| Error | Check |
| --- | --- |
| `You do not have permission to act as service_account` | The operator needs `roles/iam.serviceAccountUser` on the selected runtime service account. |
| Staging bucket `403` or metadata error | The operator needs access to the exact staging bucket; this script calls `get_bucket` before deployment. |
| Firestore `403` | The active ADC user and runtime service account both need `roles/datastore.user`. |
| Evidence upload/download `403` | Both identities need `roles/storage.objectUser` on the evidence bucket. |
| ADC or quota-project error | Repeat `gcloud auth application-default login` and set the ADC quota project. |
| Model or location error (`Publisher model ... was not found`) | The portal returns HTTP 502 with the agent's error. `gemini-3.6-flash` is only served from the `global` endpoint; the agent routes model calls there via `CLAIMS_MODEL_LOCATION` (default `global`). Keep `GOOGLE_CLOUD_LOCATION` and the deployed resource location identical. |
| Portal uses old configuration | Restart both portal processes after changing `.env`; the remote agent client is cached in-process. |

IAM changes can take a short time to propagate. Avoid downloading service
account keys as a workaround; use user ADC locally and the attached runtime
service account in Vertex AI.

## Official references

- [Set up Vertex AI Agent Engine](https://cloud.google.com/vertex-ai/generative-ai/docs/agent-engine/set-up)
- [Deploy to Vertex AI Agent Engine](https://cloud.google.com/vertex-ai/generative-ai/docs/agent-engine/deploy)
- [Create and manage Firestore databases](https://cloud.google.com/firestore/docs/manage-databases)
- [Firestore IAM roles](https://cloud.google.com/firestore/docs/security/iam)
- [Create GCS buckets](https://cloud.google.com/storage/docs/creating-buckets)
- [Cloud Storage IAM](https://cloud.google.com/storage/docs/access-control/using-iam-permissions)
- [Application Default Credentials](https://cloud.google.com/docs/authentication/provide-credentials-adc)
