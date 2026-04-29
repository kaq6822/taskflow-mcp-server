import { useState } from 'react';

import { Job, Run } from '../api/client';
import { DagView } from '../components/dag/WorkflowViz';
import { useT } from '../i18n/useT';
import { useStore } from '../store/store';

function fmtDur(s: number): string {
  if (s < 60) return `${s.toFixed(0)}s`;
  const m = Math.floor(s / 60);
  const r = Math.round(s % 60);
  return `${m}m ${r}s`;
}

export function JobDetail() {
  const t = useT();
  const jobs = useStore((s) => s.jobs);
  const runs = useStore((s) => s.runs);
  const selectedJobId = useStore((s) => s.selectedJobId);
  const setScreen = useStore((s) => s.setScreen);
  const setSelectedRunId = useStore((s) => s.setSelectedRunId);
  const startRun = useStore((s) => s.startRun);
  const cancelRun = useStore((s) => s.cancelRun);
  const liveRun = useStore((s) => s.liveRun);
  const [tab, setTab] = useState<'overview' | 'runs' | 'yaml'>('overview');

  const job = jobs.find((j) => j.id === selectedJobId);
  if (!job) {
    return (
      <div style={{ padding: 20 }}>
        <div className="mono-s dim">{t.select_job_prompt}</div>
        <button className="btn sm" style={{ marginTop: 10 }} onClick={() => setScreen('dashboard')}>
          ← Dashboard
        </button>
      </div>
    );
  }
  const jobRuns = runs.filter((r) => r.job_id === job.id);
  const runningRun = jobRuns.find((r) => r.status === 'RUNNING');
  const stopRunId = runningRun?.id ?? (liveRun?.job === job.id ? liveRun.id : null);

  const successRate = jobRuns.length
    ? Math.round((jobRuns.filter((r) => r.status === 'SUCCESS').length / jobRuns.length) * 100)
    : 100;
  const avgDur = jobRuns.length
    ? Math.round(jobRuns.reduce((a, r) => a + r.duration_sec, 0) / jobRuns.length)
    : 0;

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>{job.id}</h1>
          <div className="sub" style={{ marginTop: 2 }}>
            {job.name}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 4 }}>
          {job.tags.map((tg) => (
            <span key={tg} className="chip">
              {tg}
            </span>
          ))}
        </div>
        <div className="spacer" />
        <button className="btn ghost sm" onClick={() => setScreen('builder')}>
          ✎ Edit
        </button>
        {stopRunId ? (
          <button className="btn danger sm" onClick={() => cancelRun(stopRunId)}>
            {t.btn_stop}
          </button>
        ) : (
          <button
            className="btn primary sm"
            onClick={() => startRun(job.id)}
            disabled={!!liveRun}
          >
            {t.btn_run}
          </button>
        )}
      </div>

      <div className="tabs" style={{ paddingLeft: 18 }}>
        {([
          ['overview', t.tab_overview],
          ['runs', t.tab_runs(jobRuns.length)],
          ['yaml', 'YAML'],
        ] as const).map(([k, l]) => (
          <div
            key={k}
            className={`tab ${tab === k ? 'active' : ''}`}
            onClick={() => setTab(k)}
          >
            {l}
          </div>
        ))}
      </div>

      {tab === 'overview' && (
        <OverviewTab job={job} runs={jobRuns} successRate={successRate} avgDur={avgDur} />
      )}
      {tab === 'runs' && (
        <RunsTab
          runs={jobRuns}
          onOpen={(id) => { setSelectedRunId(id); setScreen('logs'); }}
          onCancel={cancelRun}
        />
      )}
      {tab === 'yaml' && <YamlTab job={job} />}
    </div>
  );
}

function OverviewTab({
  job,
  runs,
  successRate,
  avgDur,
}: {
  job: Job;
  runs: Run[];
  successRate: number;
  avgDur: number;
}) {
  const t = useT();
  const setScreen = useStore((s) => s.setScreen);
  const liveRun = useStore((s) => s.liveRun);
  const liveStepStates =
    liveRun && liveRun.job === job.id
      ? { stepStates: liveRun.stepStates }
      : null;
  return (
    <div
      style={{
        padding: '14px 18px',
        display: 'grid',
        gridTemplateColumns: '1fr 320px',
        gap: 14,
      }}
    >
      <div className="col" style={{ gap: 14 }}>
        <div className="card">
          <div className="ctitle">Workflow · {job.steps.length} steps</div>
          <DagView job={job} runState={liveStepStates} compact />
          <div className="mono-s dim" style={{ marginTop: 8 }}>
            {t.running_colors_hint}
          </div>
        </div>
        <div className="card">
          <div className="ctitle">{t.recent_run_activity}</div>
          {runs.length === 0 ? (
            <div className="mono-s dim">{t.no_runs}</div>
          ) : (
            <>
              <div
                style={{
                  display: 'flex',
                  alignItems: 'flex-end',
                  gap: 3,
                  height: 60,
                  marginBottom: 8,
                }}
              >
                {runs.slice(0, 30).reverse().map((r, i) => (
                  <div
                    key={i}
                    title={`#${r.id} · ${r.duration_sec.toFixed(1)}s · ${r.status}`}
                    style={{
                      flex: 1,
                      minWidth: 4,
                      background:
                        r.status === 'SUCCESS'
                          ? 'var(--ok)'
                          : r.status === 'FAILED' || r.status === 'TIMEOUT'
                          ? 'var(--err)'
                          : 'var(--info)',
                      height: Math.max(6, Math.min(60, r.duration_sec * 5 + 8)),
                      borderRadius: 1,
                      opacity: 0.8,
                    }}
                  />
                ))}
              </div>
              <div style={{ display: 'flex', gap: 20 }}>
                <span className="mono-s dim">
                  {t.success_rate} <span style={{ color: 'var(--ok)' }}>{successRate}%</span>
                </span>
                <span className="mono-s dim">
                  {t.avg} <span style={{ color: 'var(--ink)' }}>{avgDur}s</span>
                </span>
                <span className="mono-s dim">
                  {t.total} <span style={{ color: 'var(--ink)' }}>{runs.length}</span> runs
                </span>
              </div>
            </>
          )}
        </div>
      </div>
      <div className="col" style={{ gap: 14 }}>
        <div className="card">
          <div className="ctitle">{t.settings}</div>
          <div className="kv">
            <div className="k">Owner</div>
            <div className="v">{job.owner}</div>
            <div className="k">Schedule</div>
            <div className="v">{job.schedule}</div>
            <div className="k">Timeout</div>
            <div className="v">{job.timeout}s</div>
            <div className="k">Concurrency</div>
            <div className="v">{job.concurrency}</div>
            <div className="k">On failure</div>
            <div className="v">{job.on_failure}</div>
            {job.consumes_artifact && (
              <>
                <div className="k">Artifact</div>
                <div className="v">
                  <span className="link" onClick={() => setScreen('artifacts')}>
                    uploads://{job.consumes_artifact}@latest
                  </span>
                </div>
              </>
            )}
          </div>
        </div>
        <div className="card">
          <div className="ctitle">{t.policy_enforced}</div>
          <div className="mono-s" style={{ lineHeight: 1.8 }}>
            <div>
              <span className="chip ok">allowlist</span> {t.allowlist_argv}
            </div>
            <div>
              <span className="chip ok">shell=False</span>
            </div>
            <div>
              <span className="chip">user=taskflow</span>
            </div>
            <div>
              <span className="chip">cwd</span>
            </div>
            <div>
              <span className="chip warn">no-root</span>
            </div>
          </div>
        </div>
        {job.description && (
          <div className="card">
            <div className="ctitle">{t.description_section}</div>
            <div style={{ fontSize: 12, color: 'var(--ink-2)', lineHeight: 1.6 }}>{job.description}</div>
          </div>
        )}
      </div>
    </div>
  );
}

function RunsTab({
  runs,
  onOpen,
  onCancel,
}: {
  runs: Run[];
  onOpen: (id: number) => void;
  onCancel: (id: number) => void;
}) {
  const t = useT();
  if (runs.length === 0) {
    return <div style={{ padding: 20 }} className="mono-s dim">{t.no_runs_for_job}</div>;
  }
  return (
    <table className="tbl">
      <thead>
        <tr>
          <th>Run</th>
          <th>{t.col_start}</th>
          <th>{t.col_trigger}</th>
          <th>{t.col_actor}</th>
          <th>{t.col_duration}</th>
          <th>{t.col_status}</th>
          <th>Fail step</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {runs.map((r) => (
          <tr key={r.id} onClick={() => onOpen(r.id)}>
            <td className="mono-s" style={{ fontWeight: 600 }}>
              #{r.id}
            </td>
            <td className="mono-s dim">{r.started_at.slice(0, 19).replace('T', ' ')}</td>
            <td>
              <span className="chip">{r.trigger}</span>
            </td>
            <td className="mono-s">{r.actor}</td>
            <td className="mono-s">{fmtDur(r.duration_sec)}</td>
            <td>
              <span
                className={`chip ${
                  r.status === 'SUCCESS'
                    ? 'ok'
                    : r.status === 'FAILED'
                    ? 'err'
                    : r.status === 'TIMEOUT'
                    ? 'warn'
                    : 'info'
                }`}
              >
                <span className="d" />
                {r.status}
              </span>
            </td>
            <td className="mono-s">
              {r.failed_step ? <span style={{ color: 'var(--err)' }}>{r.failed_step}</span> : '—'}
            </td>
            <td className="mono-s dim">
              {r.status === 'RUNNING' ? (
                <button
                  className="btn danger sm"
                  onClick={(e) => {
                    e.stopPropagation();
                    onCancel(r.id);
                  }}
                >
                  {t.btn_stop}
                </button>
              ) : (
                '→'
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function YamlTab({ job }: { job: Job }) {
  return (
    <div style={{ padding: 18 }}>
      <div className="console" style={{ maxHeight: 520 }}>
        <YamlRender job={job} />
      </div>
    </div>
  );
}

export function YamlRender({ job }: { job: Job }) {
  let n = 1;
  const ln = (content: React.ReactNode) => {
    const el = (
      <div className="ln" key={n}>
        <span className="no">{n}</span>
        <span className="yaml-line">{content}</span>
      </div>
    );
    n += 1;
    return el;
  };
  return (
    <>
      {ln(<><span className="y-key">id</span>: {job.id}</>)}
      {ln(
        <>
          <span className="y-key">name</span>: <span className="y-str">"{job.name}"</span>
        </>
      )}
      {ln(<><span className="y-key">owner</span>: {job.owner}</>)}
      {ln(
        <>
          <span className="y-key">schedule</span>: <span className="y-str">"{job.schedule}"</span>
        </>
      )}
      {ln(
        <>
          <span className="y-key">timeout</span>: <span className="y-num">{job.timeout}</span>
        </>
      )}
      {ln(
        <>
          <span className="y-key">concurrency</span>: <span className="y-num">{job.concurrency}</span>
        </>
      )}
      {ln(<><span className="y-key">on_failure</span>: {job.on_failure}</>)}
      {ln(<><span className="y-key">steps</span>:</>)}
      {job.steps.map((st) => (
        <div key={st.id}>
          {ln(<>  - <span className="y-key">id</span>: {st.id}</>)}
          {st.cwd &&
            ln(
              <>
                {'    '}
                <span className="y-key">cwd</span>: <span className="y-str">"{st.cwd}"</span>
              </>
            )}
          {ln(
            <>
              {'    '}
              <span className="y-key">command</span>: [
              {st.cmd.map((c, i) => (
                <span key={i}>
                  <span className="y-str">"{c}"</span>
                  {i < st.cmd.length - 1 ? ', ' : ''}
                </span>
              ))}
              ]
            </>
          )}
          {(st.deps || []).length > 0 &&
            ln(
              <>
                {'    '}
                <span className="y-key">depends_on</span>: [{(st.deps || []).join(', ')}]
              </>
            )}
          {ln(
            <>
              {'    '}
              <span className="y-key">timeout</span>: <span className="y-num">{st.timeout}</span>
            </>
          )}
          {ln(
            <>
              {'    '}
              <span className="y-key">on_failure</span>: {st.on_failure}
            </>
          )}
        </div>
      ))}
    </>
  );
}
