// Backend REST client. base path is proxied through Vite to localhost:8000.

export type Step = {
  id: string;
  cmd: string[];
  timeout: number;
  on_failure: 'STOP' | 'CONTINUE' | 'RETRY' | 'ROLLBACK';
  deps: string[];
  env?: Record<string, string>;
  cwd?: string | null;
  success_contains?: string[];
  failure_contains?: string[];
};

export type Job = {
  id: string;
  name: string;
  description: string;
  owner: string;
  tags: string[];
  schedule: string;
  timeout: number;
  concurrency: number;
  on_failure: string;
  consumes_artifact: string | null;
  steps: Step[];
  created_at: string;
  updated_at: string;
};

export type RunStep = {
  step_id: string;
  state: 'PENDING' | 'RUNNING' | 'SUCCESS' | 'FAILED' | 'TIMEOUT' | 'SKIPPED';
  elapsed_sec: number;
  started_at: string | null;
  finished_at: string | null;
  exit_code: number | null;
};

export type Run = {
  id: number;
  job_id: string;
  status: 'RUNNING' | 'SUCCESS' | 'FAILED' | 'TIMEOUT';
  trigger: string;
  actor: string;
  started_at: string;
  finished_at: string | null;
  duration_sec: number;
  order: string[];
  artifact_ref: string | null;
  failed_step: string | null;
  err_message: string | null;
  steps: RunStep[];
};

export type Artifact = {
  id: number;
  name: string;
  version: string;
  ext: string;
  size_bytes: number;
  sha256: string;
  uploader: string;
  uploaded_at: string;
  latest: boolean;
  status: string;
  consumers: string[];
};

export type AuditEvent = {
  id: number;
  at: string;
  who: string;
  kind: string;
  target: string;
  src: string;
  ip: string;
  result: string;
};

export type Key = {
  id: string;
  label: string;
  key_prefix: string;
  key_suffix: string;
  scopes: string[];
  created: string;
  expires: string | null;
  last_used: string | null;
  rate_limit: string;
  state: string;
};

export type KeyIssued = Key & { plaintext: string };

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text();
    let detail: unknown = text;
    try {
      detail = JSON.parse(text);
    } catch {
      /* keep text */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export class ApiError extends Error {
  constructor(public status: number, public detail: unknown) {
    super(`HTTP ${status}`);
  }
}

export const api = {
  listJobs: () => req<Job[]>('/api/jobs'),
  getJob: (id: string) => req<Job>(`/api/jobs/${id}`),
  createJob: (body: Partial<Job> & { steps: Step[] }) =>
    req<Job>('/api/jobs', { method: 'POST', body: JSON.stringify(body) }),
  updateJob: (id: string, body: Partial<Job>) =>
    req<Job>(`/api/jobs/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  deleteJob: (id: string) => req<void>(`/api/jobs/${id}`, { method: 'DELETE' }),

  listRuns: (params: { job_id?: string; status?: string; limit?: number } = {}) => {
    const q = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined) q.set(k, String(v));
    });
    const qs = q.toString();
    return req<Run[]>(`/api/runs${qs ? '?' + qs : ''}`);
  },
  getRun: (id: number) => req<Run>(`/api/runs/${id}`),
  getRunLogs: async (runId: number, stepId: string, tail = 200) => {
    const res = await fetch(
      `/api/runs/${runId}/logs/${encodeURIComponent(stepId)}?tail=${tail}`
    );
    if (!res.ok) throw new ApiError(res.status, await res.text());
    return res.text();
  },
  startRun: (jobId: string, body: { trigger?: string; actor?: string; artifact_ref?: string | null } = {}) =>
    req<Run>(`/api/jobs/${jobId}/runs`, {
      method: 'POST',
      body: JSON.stringify({ trigger: 'manual', actor: 'admin', ...body }),
    }),
  cancelRun: (id: number) =>
    req<Run>(`/api/runs/${id}/cancel`, { method: 'POST', body: '{}' }),
  cancelJobRun: (jobId: string) =>
    req<Run>(`/api/jobs/${jobId}/runs/cancel`, { method: 'POST', body: '{}' }),

  listArtifacts: () => req<Artifact[]>('/api/artifacts'),
  uploadArtifact: async (name: string, version: string, ext: string, file: File) => {
    const fd = new FormData();
    fd.set('name', name);
    fd.set('version', version);
    fd.set('ext', ext);
    fd.set('uploader', 'admin');
    fd.set('file', file);
    const res = await fetch('/api/artifacts', { method: 'POST', body: fd });
    if (!res.ok) throw new ApiError(res.status, await res.text());
    return (await res.json()) as Artifact;
  },

  listAudit: (params: { kind?: string; result?: string; q?: string; limit?: number } = {}) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== 'all' && v !== '') qs.set(k, String(v));
    });
    const s = qs.toString();
    return req<AuditEvent[]>(`/api/audit${s ? '?' + s : ''}`);
  },

  listKeys: () => req<Key[]>('/api/keys'),
  issueKey: (body: {
    label: string;
    scopes: string[];
    expires_days: number;
    rate_limit: '10/min' | '30/min' | '60/min';
  }) => req<KeyIssued>('/api/keys', { method: 'POST', body: JSON.stringify(body) }),
  revokeKey: (id: string) => req<void>(`/api/keys/${id}`, { method: 'DELETE' }),
};
