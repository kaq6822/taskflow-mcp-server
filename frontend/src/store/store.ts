import { create } from 'zustand';
import { persist } from 'zustand/middleware';

import { api, Artifact, AuditEvent, Job, Key, Run, RunStep } from '../api/client';
import { subscribeRun } from '../api/sse';
import { Lang, translations } from '../i18n/translations';

export type Screen =
  | 'dashboard'
  | 'detail'
  | 'builder'
  | 'monitor'
  | 'logs'
  | 'artifacts'
  | 'audit'
  | 'mcp';

export type Toast = { id: string; msg: string; kind: 'ok' | 'err' | 'info' };

type LiveRun = {
  id: number;
  job: string;
  order: string[];
  stepStates: Record<string, { state: string; elapsed: number; logs: { ts: string; lvl: string; text: string }[] }>;
  currentIdx: number;
  dur: number;
  status: 'RUNNING' | 'SUCCESS' | 'FAILED' | 'TIMEOUT';
};

type State = {
  screen: Screen;
  selectedJobId: string | null;
  selectedRunId: number | null;
  selectedArtifactId: number | null;

  jobs: Job[];
  runs: Run[];
  artifacts: Artifact[];
  audit: AuditEvent[];
  keys: Key[];

  liveRun: LiveRun | null;
  toasts: Toast[];
  lang: Lang;

  setScreen: (s: Screen) => void;
  setSelectedJobId: (id: string | null) => void;
  setSelectedRunId: (id: number | null) => void;
  setSelectedArtifactId: (id: number | null) => void;
  setLang: (l: Lang) => void;

  refreshJobs: () => Promise<unknown>;
  refreshRuns: () => Promise<unknown>;
  refreshArtifacts: () => Promise<unknown>;
  refreshAudit: () => Promise<unknown>;
  refreshKeys: () => Promise<unknown>;
  refreshAll: () => Promise<unknown>;

  startRun: (jobId: string) => Promise<void>;
  cancelRun: (runId?: number) => Promise<void>;
  deleteJob: (jobId: string) => Promise<void>;

  pushToast: (msg: string, kind?: Toast['kind']) => void;
  dismissToast: (id: string) => void;
};

function detectInitialLang(): Lang {
  if (typeof navigator === 'undefined') return 'ko';
  const languages = [...(navigator.languages || []), navigator.language]
    .filter(Boolean)
    .map((lang) => lang.toLowerCase());
  return languages.some((lang) => lang === 'ko' || lang.startsWith('ko-')) ? 'ko' : 'en';
}

let activeRunStreamId: number | null = null;
let closeActiveRunStream: (() => void) | null = null;

function replaceActiveRunStream(runId: number, close: () => void) {
  closeActiveRunStream?.();
  activeRunStreamId = runId;
  closeActiveRunStream = close;
}

function closeRunStream(runId: number) {
  if (activeRunStreamId !== runId) return;
  closeActiveRunStream?.();
  activeRunStreamId = null;
  closeActiveRunStream = null;
}

export const useStore = create<State>()(
  persist(
    (set, get) => ({
      screen: 'dashboard',
      selectedJobId: null,
      selectedRunId: null,
      selectedArtifactId: null,

      jobs: [],
      runs: [],
      artifacts: [],
      audit: [],
      keys: [],

      liveRun: null,
      toasts: [],
      lang: detectInitialLang(),

      setScreen: (s) => set({ screen: s }),
      setSelectedJobId: (id) => set({ selectedJobId: id }),
      setSelectedRunId: (id) => set({ selectedRunId: id }),
      setSelectedArtifactId: (id) => set({ selectedArtifactId: id }),
      setLang: (l) => set({ lang: l }),

      refreshJobs: async () => set({ jobs: await api.listJobs() }),
      refreshRuns: async () => set({ runs: await api.listRuns({ limit: 50 }) }),
      refreshArtifacts: async () => set({ artifacts: await api.listArtifacts() }),
      refreshAudit: async () => set({ audit: await api.listAudit({ limit: 200 }) }),
      refreshKeys: async () => set({ keys: await api.listKeys() }),
      refreshAll: async () => {
        const [jobs, runs, artifacts, audit, keys] = await Promise.all([
          api.listJobs(),
          api.listRuns({ limit: 50 }),
          api.listArtifacts(),
          api.listAudit({ limit: 200 }),
          api.listKeys(),
        ]);
        set({ jobs, runs, artifacts, audit, keys });
      },

      pushToast: (msg, kind = 'ok') => {
        const id = Math.random().toString(36).slice(2);
        set({ toasts: [...get().toasts, { id, msg, kind }] });
        setTimeout(() => get().dismissToast(id), 3500);
      },
      dismissToast: (id) => set({ toasts: get().toasts.filter((t) => t.id !== id) }),

      startRun: async (jobId: string) => {
        try {
          const run = await api.startRun(jobId);
          const live: LiveRun = {
            id: run.id,
            job: run.job_id,
            order: run.order,
            stepStates: Object.fromEntries(
              run.order.map((id) => [id, { state: 'PENDING', elapsed: 0, logs: [] }])
            ),
            currentIdx: 0,
            dur: 0,
            status: 'RUNNING',
          };
          set({ liveRun: live });
          get().pushToast(translations[get().lang].toast_run_started(run.id));

          const close = subscribeRun(run.id, (ev) => {
            const cur = get().liveRun;
            if (ev.event === 'run.finished') {
              const status = (ev.data.status || 'SUCCESS') as LiveRun['status'];
              closeRunStream(run.id);
              if (cur?.id === run.id) {
                set({
                  liveRun: null,
                  selectedRunId: run.id,
                });
                get().pushToast(
                  translations[get().lang].toast_run_done(run.id, status),
                  status === 'SUCCESS' ? 'ok' : 'err'
                );
              }
              get().refreshRuns();
              get().refreshAudit();
              return;
            }
            if (!cur || cur.id !== run.id) return;
            if (ev.event === 'step.started') {
              const next = { ...cur, stepStates: { ...cur.stepStates } };
              next.currentIdx = cur.order.indexOf(ev.data.step_id);
              next.stepStates[ev.data.step_id] = {
                ...(next.stepStates[ev.data.step_id] || { state: 'PENDING', elapsed: 0, logs: [] }),
                state: 'RUNNING',
              };
              set({ liveRun: next });
            } else if (ev.event === 'step.log') {
              const next = { ...cur, stepStates: { ...cur.stepStates } };
              const s = { ...(next.stepStates[ev.data.step_id] || { state: 'RUNNING', elapsed: 0, logs: [] }) };
              s.logs = [...s.logs, { ts: ev.data.ts, lvl: ev.data.lvl, text: ev.data.text }];
              next.stepStates[ev.data.step_id] = s;
              set({ liveRun: next });
            } else if (ev.event === 'step.finished') {
              const next = { ...cur, stepStates: { ...cur.stepStates } };
              const s = { ...(next.stepStates[ev.data.step_id] || { state: 'RUNNING', elapsed: 0, logs: [] }) };
              s.state = ev.data.state;
              s.elapsed = ev.data.elapsed_sec;
              next.stepStates[ev.data.step_id] = s;
              set({ liveRun: next });
            }
          });
          replaceActiveRunStream(run.id, close);
        } catch (e: unknown) {
          const msg = e instanceof Error ? e.message : String(e);
          get().pushToast(translations[get().lang].toast_run_start_fail(msg), 'err');
        }
      },

      cancelRun: async (runId?: number) => {
        const live = get().liveRun;
        const targetId = runId ?? live?.id;
        if (!targetId) return;
        try {
          await api.cancelRun(targetId);
          if (live?.id === targetId) {
            closeRunStream(targetId);
            set({ liveRun: null, selectedRunId: targetId });
          }
          get().pushToast(translations[get().lang].toast_run_cancelled, 'err');
          get().refreshRuns();
          get().refreshAudit();
        } catch (e) {
          const msg = e instanceof Error ? e.message : String(e);
          get().pushToast(translations[get().lang].toast_run_cancel_fail(msg), 'err');
        }
      },

      deleteJob: async (jobId: string) => {
        if (get().liveRun?.job === jobId) {
          get().pushToast(translations[get().lang].toast_job_delete_running, 'err');
          return;
        }
        try {
          await api.deleteJob(jobId);
          set({
            jobs: get().jobs.filter((j) => j.id !== jobId),
            runs: get().runs.filter((r) => r.job_id !== jobId),
            selectedJobId: null,
            selectedRunId: null,
            screen: 'dashboard',
          });
          get().pushToast(translations[get().lang].toast_job_deleted(jobId));
          get().refreshJobs();
          get().refreshRuns();
          get().refreshAudit();
        } catch (e) {
          const msg = e instanceof Error ? e.message : String(e);
          get().pushToast(translations[get().lang].toast_job_delete_fail(msg), 'err');
        }
      },
    }),
    {
      name: 'taskflow-ui',
      partialize: (s) => ({
        screen: s.screen,
        selectedJobId: s.selectedJobId,
        selectedRunId: s.selectedRunId,
        selectedArtifactId: s.selectedArtifactId,
        lang: s.lang,
      }),
    }
  )
);

export type StepState = RunStep['state'];
