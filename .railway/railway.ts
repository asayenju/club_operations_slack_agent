import { defineRailway, github, project, service } from "railway/iac";

// Deploys the same repo/source three times as separate Railway services,
// differing only by start command -- Railway's equivalent of Fly's
// [processes] table. No Dockerfile: Railpack auto-detects Python from the
// root requirements.txt (student-org-agent/requirements.txt is dev-tooling
// for the separate `slack` CLI, not imported by any running code, so it's
// intentionally not referenced here).
//
// PYTHONPATH=. is required on every service: `python student-org-agent/app.py`
// only puts that subdirectory on sys.path by default, not the repo root, so
// `from common.config import ...` etc. fail without it (same reason local
// runs this session needed `PYTHONPATH=$PWD`).
//
// Secrets (SLACK_BOT_TOKEN, APP_ENCRYPTION_KEY, GOOGLE_TOKEN_JSON_B64, etc.)
// are deliberately NOT declared here -- this file is committed to git. They
// are set separately per service via `railway variable set` / `variable
// import`, piped through stdin, never written into source.

const source = github("asayenju/club_operations_slack_agent", { branch: "main" });

export default defineRailway(() => {
  const app = service("app", {
    source,
    start: "python student-org-agent/app.py",
    env: {
      PYTHONPATH: ".",
    },
  });

  const ingestion = service("ingestion", {
    source,
    start: "uvicorn ingestion_api.main:app --host 0.0.0.0 --port 8000",
    env: {
      PYTHONPATH: ".",
    },
  });

  const worker = service("worker", {
    source,
    start: "python -m tools.drive_poll_worker",
    env: {
      PYTHONPATH: ".",
    },
  });

  return project("memora-clubops", {
    resources: [app, ingestion, worker],
  });
});
