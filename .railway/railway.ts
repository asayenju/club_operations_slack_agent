import { defineRailway, github, preserve, project, service } from "railway/iac";

// Deploys the same repo/source three times as separate Railway services,
// differing only by start command -- Railway's equivalent of Fly's
// [processes] table. Explicitly forced to RAILPACK: a Dockerfile exists at
// the repo root (kept for other tooling), and Railway's build-detection
// silently prefers it over Railpack when `build` isn't set -- confirmed via
// a live deploy's metadata showing "builder": "DOCKERFILE" despite this file
// never requesting Docker. Root requirements.txt is all Railpack needs
// (student-org-agent/requirements.txt is dev-tooling for the separate
// `slack` CLI, not imported by any running code).
//
// PYTHONPATH=. is required on every service: `python student-org-agent/app.py`
// only puts that subdirectory on sys.path by default, not the repo root, so
// `from common.config import ...` etc. fail without it (same reason local
// runs this session needed `PYTHONPATH=$PWD`).
//
// Secret VALUES are deliberately not written here -- this file is committed
// to git. They were set out-of-band via `railway variable set --stdin` per
// service. Each key is still declared below wrapped in preserve() -- leaving
// a key out entirely tells `railway config apply` the variable is unwanted
// and to delete it; preserve() means "this key is managed elsewhere, keep
// whatever value is already set."
const SECRET_KEYS = [
  "SUPABASE_URL",
  "SUPABASE_SERVICE_KEY",
  "WORKSPACE_ID",
  "VOYAGE_API_KEY",
  "ANTHROPIC_API_KEY",
  "APP_ENCRYPTION_KEY",
  "SLACK_APP_TOKEN",
  "SLACK_BOT_TOKEN",
  "SLACK_CLIENT_ID",
  "SLACK_CLIENT_SECRET",
  "SLACK_SIGNING_SECRET",
  "GOOGLE_TOKEN_JSON_B64",
] as const;

function preservedSecrets(): Record<string, ReturnType<typeof preserve>> {
  return Object.fromEntries(SECRET_KEYS.map((key) => [key, preserve()]));
}

const source = github("asayenju/club_operations_slack_agent", { branch: "main" });

export default defineRailway(() => {
  const app = service("app", {
    source,
    // buildCommand is a no-op (`true`) rather than unset: an earlier config
    // mistakenly set it to the literal string "RAILPACK" (the string form of
    // `build` sets buildCommand, not the builder), and `railway config apply`
    // cannot clear buildCommand back to null -- it reports success but the
    // stale value persists (verified via `railway config pull --json`).
    // Railpack auto-runs `pip install -r requirements.txt`, so no real build
    // step is needed; overwriting with `true` is the reliable way to stop it
    // running `sh -c RAILPACK` (command-not-found, exit 127).
    build: { builder: "RAILPACK", buildCommand: "true" },
    start: "python student-org-agent/app.py",
    env: {
      PYTHONPATH: ".",
      ...preservedSecrets(),
    },
  });

  const ingestion = service("ingestion", {
    source,
    // buildCommand is a no-op (`true`) rather than unset: an earlier config
    // mistakenly set it to the literal string "RAILPACK" (the string form of
    // `build` sets buildCommand, not the builder), and `railway config apply`
    // cannot clear buildCommand back to null -- it reports success but the
    // stale value persists (verified via `railway config pull --json`).
    // Railpack auto-runs `pip install -r requirements.txt`, so no real build
    // step is needed; overwriting with `true` is the reliable way to stop it
    // running `sh -c RAILPACK` (command-not-found, exit 127).
    build: { builder: "RAILPACK", buildCommand: "true" },
    start: "uvicorn ingestion_api.main:app --host 0.0.0.0 --port 8000",
    env: {
      PYTHONPATH: ".",
      ...preservedSecrets(),
    },
  });

  const worker = service("worker", {
    source,
    // buildCommand is a no-op (`true`) rather than unset: an earlier config
    // mistakenly set it to the literal string "RAILPACK" (the string form of
    // `build` sets buildCommand, not the builder), and `railway config apply`
    // cannot clear buildCommand back to null -- it reports success but the
    // stale value persists (verified via `railway config pull --json`).
    // Railpack auto-runs `pip install -r requirements.txt`, so no real build
    // step is needed; overwriting with `true` is the reliable way to stop it
    // running `sh -c RAILPACK` (command-not-found, exit 127).
    build: { builder: "RAILPACK", buildCommand: "true" },
    start: "python -m tools.drive_poll_worker",
    env: {
      PYTHONPATH: ".",
      ...preservedSecrets(),
    },
  });

  return project("memora-clubops", {
    resources: [app, ingestion, worker],
  });
});
