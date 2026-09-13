"""Build an Agent Engine bundle; only --deploy performs cloud writes."""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from contextlib import chdir
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def build_bundle() -> tuple[Path, list[Path]]:
    output = ROOT / "dist/agent-engine"
    output.mkdir(parents=True, exist_ok=True)
    bundle = Path(tempfile.mkdtemp(prefix="build-", dir=output))
    subprocess.run(
        [
            "uv",
            "export",
            "--locked",
            "--package",
            "insurance-claim-agent",
            "--no-dev",
            "--no-emit-workspace",
            "--no-hashes",
            "--no-annotate",
            "--no-header",
            "--output-file",
            str(bundle / "requirements.txt"),
        ],
        cwd=ROOT,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    for package in ("claims-core", "insurance-claim-agent"):
        subprocess.run(
            ["uv", "build", "--package", package, "--wheel", "--out-dir", str(bundle)],
            cwd=ROOT,
            check=True,
        )
    wheels = sorted(bundle.glob("*.whl"))
    if len(wheels) != 2:
        raise RuntimeError("Expected exactly the agent and claims-core wheels")
    for wheel in wheels:
        with zipfile.ZipFile(wheel) as archive:
            for name in archive.namelist():
                parts = Path(name).parts
                if any(
                    part in (".env", ".adk", "client_portal", "adjuster_portal") for part in parts
                ):
                    raise RuntimeError(f"Unexpected runtime file in {wheel.name}: {name}")
    requirements_file = bundle / "requirements.txt"
    exported = requirements_file.read_text(encoding="utf-8").rstrip("\n")
    requirements_file.write_text(
        "\n".join([exported, *(wheel.name for wheel in wheels)]) + "\n", encoding="utf-8"
    )
    return bundle, wheels


def main(argv=None):
    from claims_core.config import evidence_bucket, evidence_prefix, load_environment

    load_environment()
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Build and validate locally (default)")
    mode.add_argument("--deploy", action="store_true", help="Create a new Agent Engine deployment")
    parser.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT"))
    parser.add_argument(
        "--location", default=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
    )
    parser.add_argument(
        "--database", default=os.environ.get("CLAIMS_FIRESTORE_DATABASE", "(default)")
    )
    parser.add_argument("--evidence-bucket", default=evidence_bucket())
    parser.add_argument("--evidence-prefix", default=evidence_prefix())
    parser.add_argument("--staging-bucket")
    parser.add_argument("--service-account")
    parser.add_argument("--display-name", default="insurance-claims")
    args = parser.parse_args(argv)
    if sys.version_info[:2] != (3, 12):
        parser.error("Use the pinned Python 3.12 environment for Agent Engine serialization")
    if args.deploy:
        missing = [
            name
            for name in ("project", "staging_bucket", "service_account", "evidence_bucket")
            if not getattr(args, name)
        ]
        if missing:
            parser.error(
                "--deploy requires " + ", ".join("--" + name.replace("_", "-") for name in missing)
            )

    bundle, wheels = build_bundle()
    import cloudpickle
    from insurance_claim_agent.agent import root_agent
    from vertexai import agent_engines

    app = agent_engines.AdkApp(agent=root_agent, app_name="insurance_claim_agent")
    cloudpickle.loads(cloudpickle.dumps(app))
    # Agent Engine reserves GOOGLE_CLOUD_PROJECT/GOOGLE_CLOUD_LOCATION and injects
    # them at runtime; AdkApp.set_up sets GOOGLE_GENAI_USE_VERTEXAI itself.
    env = {
        "CLAIMS_STORE": "firestore",
        "CLAIMS_FIRESTORE_DATABASE": args.database,
        "CLAIMS_EVIDENCE_BUCKET": args.evidence_bucket,
        "CLAIMS_EVIDENCE_PREFIX": args.evidence_prefix,
    }
    print(
        json.dumps(
            {
                "mode": "deploy" if args.deploy else "dry-run",
                "bundle": str(bundle),
                "wheels": [wheel.name for wheel in wheels],
                "serialization": "passed",
                "runtime_environment": env,
                "service_account": args.service_account,
            },
            indent=2,
        )
    )
    if not args.deploy:
        return

    import vertexai
    from google.cloud import storage

    staging = args.staging_bucket.removeprefix("gs://").rstrip("/")
    # The SDK can create a missing staging bucket; require the existing resource instead.
    storage.Client(project=args.project).get_bucket(staging)
    vertexai.init(project=args.project, location=args.location, staging_bucket=f"gs://{staging}")
    # Relative wheel paths are preserved in the SDK's uploaded tar archive.
    with chdir(bundle):
        remote = agent_engines.create(
            agent_engine=app,
            requirements="requirements.txt",
            extra_packages=[wheel.name for wheel in wheels],
            display_name=args.display_name,
            service_account=args.service_account,
            env_vars=env,
            gcs_dir_name=bundle.name,
        )
    print(f"AGENT_ENGINE_ID={remote.resource_name}")


if __name__ == "__main__":
    main()
