import { create } from 'zustand';
import { persist } from 'zustand/middleware';

import { api, Artifact, AuditEvent, Job, Key, Run, RunStep } from '../api/client';
import { subscribeRun } from '../api/sse';

export type Screen =
  | 'dashboard'
  | 'detail'
  | 'builder'
  | 'monitor'
  | 'logs'
  | 'artifacts'
  | 'audit'
  | 'mcp';

export type Viz = 'dag' | 'list' | 'timeline';
export type Density = 'compact' | 'spacious';

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
  viz: Viz;
  density: Density;

  jobs: Job[];
  runs: Run[];
  artifacts: Artifact[];
  audit: AuditEvent[];
  keys: Key[];

  liveRun: LiveRun | null;
  toasts: Toast[];

  setScreen: (s: Screen) => void;
  setSelectedJobId: (id: string | null) => void;
  setSelectedRunId: (id: number | null) => void;
  setViz: (v: Viz) => void;
  setDensity: (d: Density) => void;

  refreshJobs: () => Promise<unknown>;
  refreshRuns: () => Promise<unknown>;
  refreshArtifacts: () => Promise<unknown>;
  refreshAudit: () => Promise<unknown>;
  refreshKeys: () => Promise<unknown>;
  refreshAll: () => Promise<unknown>;

  startRun: (jobId: string) => Promise<void>;
  cancelRun: () => Promise<void>;

  pushToast: (msg: string, kind?: Toast['kind']) => void;
  dismissToast: (id: string) => void;
};

export const useStore = create<State>()(
  persist(
    (set, get) => ({
      screen: 'dashboard',
      selectedJobId: null,
      selectedRunId: null,
      viz: 'dag',
      density: 'compact',

      jobs: [],
      runs: [],
      artifacts: [],
      audit: [],
      keys: [],

      liveRun: null,
      toasts: [],

      setScreen: (s) => set({ screen: s }),
      setSelectedJobId: (id) => set({ selectedJobId: id }),
      setSelectedRunId: (id) => set({ selectedRunId: id }),
      setViz: (v) => set({ viz: v }),
      setDensity: (d) => set({ density: d }),

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
          get().pushToast(`Run #${run.id} 시작`);

          const close = subscribeRun(run.id, (ev) => {
            const cur = get().liveRun;
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
            } else if (ev.event === 'run.finished') {
              const status = (ev.data.status || 'SUCCESS') as LiveRun['status'];
              set({
                liveRun: null,
                selectedRunId: run.id,
              });
              get().pushToast(
                `Run #${run.id} 완료 · ${status}`,
                status === 'SUCCESS' ? 'ok' : 'err'
              );
              close();
              get().refreshRuns();
              get().refreshAudit();
            }
          });
        } catch (e: unknown) {
          const msg = e instanceof Error ? e.message : String(e);
          get().pushToast(`Run 시작 실패: ${msg}`, 'err');
        }
      },

      cancelRun: async () => {
        const live = get().liveRun;
        if (!live) return;
        try {
          await api.cancelRun(live.id);
          set({ liveRun: null });
          get().pushToast('Run이 취소되었습니다', 'err');
          get().refreshRuns();
        } catch (e) {
          /* ignore */
        }
      },
    }),
    {
      name: 'taskflow-ui',
      partialize: (s) => ({
        screen: s.screen,
        selectedJobId: s.selectedJobId,
        selectedRunId: s.selectedRunId,
        viz: s.viz,
        density: s.density,
      }),
    }
  )
);

export type StepState = RunStep['state'];
