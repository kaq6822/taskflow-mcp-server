// Thin EventSource wrapper for /api/runs/{id}/stream.

export type RunEvent =
  | { event: 'run.started'; data: { run_id: number; job_id: string; at: string } }
  | { event: 'step.started'; data: { step_id: string; cmd: string[]; timeout: number } }
  | {
      event: 'step.log';
      data: { step_id: string; ts: string; lvl: string; text: string };
    }
  | { event: 'step.finished'; data: { step_id: string; state: string; elapsed_sec: number } }
  | {
      event: 'run.finished';
      data: {
        run_id: number;
        status: string;
        failed_step: string | null;
        err_message: string | null;
        duration_sec: number;
      };
    }
  | { event: 'ping'; data: {} };

export function subscribeRun(runId: number, onEvent: (ev: RunEvent) => void) {
  const es = new EventSource(`/api/runs/${runId}/stream`);
  const names: RunEvent['event'][] = [
    'run.started',
    'step.started',
    'step.log',
    'step.finished',
    'run.finished',
    'ping',
  ];
  names.forEach((name) => {
    es.addEventListener(name, (raw) => {
      try {
        const data = JSON.parse((raw as MessageEvent).data);
        onEvent({ event: name, data } as RunEvent);
      } catch {
        /* ignore malformed frame */
      }
    });
  });
  es.onerror = () => {
    // EventSource auto-reconnects; close on run.finished instead.
  };
  return () => es.close();
}
