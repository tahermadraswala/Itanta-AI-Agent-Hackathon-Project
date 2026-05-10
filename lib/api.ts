/**
 * lib/api.ts
 * ──────────
 * API client for the Omnix FastAPI backend (localhost:8000).
 */

const BASE_URL = "http://localhost:8000";

// ── Types ────────────────────────────────────────────────────

export interface LogEntry {
  time: string;
  agent: string;
  action: string;
}

export interface CheckpointPayload {
  type: string;
  content: string;
}

export interface PipelineStatus {
  stage: string;
  agent: string;
  logs: LogEntry[];
  status: "running" | "checkpoint" | "complete" | "failed";
  checkpoint: CheckpointPayload | null;
  output: string | null;
}

// ── API functions ────────────────────────────────────────────

/**
 * Start a new orchestrator pipeline run.
 * Returns the run_id used to poll status and send approvals.
 */
export async function startPipeline(
  project: string,
  spec: string
): Promise<{ run_id: string }> {
  const res = await fetch(`${BASE_URL}/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project, spec }),
  });
  if (!res.ok) throw new Error(`Failed to start pipeline: ${res.statusText}`);
  return res.json();
}

/**
 * Poll the current state of a pipeline run.
 */
export async function getStatus(run_id: string): Promise<PipelineStatus> {
  const res = await fetch(`${BASE_URL}/status/${run_id}`);
  if (!res.ok) throw new Error(`Failed to get status: ${res.statusText}`);
  return res.json();
}

/**
 * Send a human checkpoint decision (approve / reject) to the backend.
 */
export async function sendApproval(
  run_id: string,
  decision: string,
  feedback: string = ""
): Promise<void> {
  const res = await fetch(`${BASE_URL}/approve/${run_id}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision, feedback }),
  });
  if (!res.ok) throw new Error(`Failed to send approval: ${res.statusText}`);
}
