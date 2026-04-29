import { useEffect, useState } from 'react';

import { Run, api } from '../api/client';
import { useT } from '../i18n/useT';
import { useStore } from '../store/store';

function failedStepId(run: Run): string | null {
  return (
    run.failed_step ||
    run.steps.find((s) => s.state === 'FAILED' || s.state === 'TIMEOUT')?.step_id ||
    run.steps[0]?.step_id ||
    null
  );
}

function splitLogLines(text: string): string[] {
  return text.replace(/\n$/, '').split('\n').filter((_, i, lines) => lines.length > 1 || lines[0]);
}

export function Monitor() {
  const t = useT();
  const liveRun = useStore((s) => s.liveRun);
  const runs = useStore((s) => s.runs);
  const jobs = useStore((s) => s.jobs);
  const selectedJobId = useStore((s) => s.selectedJobId);
  const selectedRunId = useStore((s) => s.selectedRunId);
  const setScreen = useStore((s) => s.setScreen);
  const setSelectedRunId = useStore((s) => s.setSelectedRunId);
  const startRun = useStore((s) => s.startRun);
  const cancelRun = useStore((s) => s.cancelRun);
  const selectedRun = selectedRunId ? runs.find((r) => r.id === selectedRunId) : null;
  const inspectedRun = selectedRun || runs[0] || null;
  const inspectedStepId = inspectedRun ? failedStepId(inspectedRun) : null;
  const [storedLogText, setStoredLogText] = useState('');

  useEffect(() => {
    if (liveRun || !inspectedRun || !inspectedStepId) {
      setStoredLogText('');
      return;
    }
    let active = true;
    setStoredLogText('');
    api
      .getRunLogs(inspectedRun.id, inspectedStepId, 160)
      .then((text) => {
        if (active) setStoredLogText(text);
      })
      .catch(() => {
        if (active) setStoredLogText(t.log_unavailable);
      });
    return () => {
      active = false;
    };
  }, [liveRun, inspectedRun?.id, inspectedStepId, t]);

  if (!liveRun) {
    return (
      <div>
        <div className="page-head">
          <h1>Runs</h1>
          <span className="sub">{t.sub_run_monitor}</span>
        </div>
        <div style={{ padding: '40px 18px', textAlign: 'center' }}>
          <div style={{ fontSize: 40, color: 'var(--ink-4)', marginBottom: 10 }}>◌</div>
          <div style={{ color: 'var(--ink-3)', marginBottom: 16 }}>
            {t.no_active_run}
          </div>
          {selectedJobId && (
            <button className="btn primary" onClick={() => startRun(selectedJobId)}>
              ▷ {selectedJobId}
            </button>
          )}
          <div className="hr" />
          <div style={{ textAlign: 'left' }}>
            <div className="ctitle" style={{ marginBottom: 8 }}>{t.recent_run_history}</div>
            {runs.length === 0 ? (
              <div className="mono-s dim">{t.no_runs}</div>
            ) : (
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Run</th>
                    <th>Job</th>
                    <th>{t.col_start}</th>
                    <th>{t.col_duration}</th>
                    <th>{t.col_status}</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.slice(0, 10).map((r) => (
                    <tr
                      key={r.id}
                      onClick={() => {
                        setSelectedRunId(r.id);
                        setScreen('logs');
                      }}
                    >
                      <td className="mono-s" style={{ fontWeight: 600 }}>
                        #{r.id}
                      </td>
                      <td>{r.job_id}</td>
                      <td className="mono-s dim">{r.started_at.slice(0, 19).replace('T', ' ')}</td>
                      <td className="mono-s">{r.duration_sec.toFixed(1)}s</td>
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
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
          {inspectedRun && inspectedStepId && (
            <div style={{ textAlign: 'left', marginTop: 16 }}>
              <div className="row" style={{ marginBottom: 8 }}>
                <div className="ctitle">{t.latest_run_output}</div>
                <span
                  className={`chip ${
                    inspectedRun.status === 'SUCCESS'
                      ? 'ok'
                      : inspectedRun.status === 'FAILED'
                      ? 'err'
                      : inspectedRun.status === 'TIMEOUT'
                      ? 'warn'
                      : 'info'
                  }`}
                >
                  <span className="d" />
                  #{inspectedRun.id} · {inspectedStepId} · {inspectedRun.status}
                </span>
                <div className="spacer" />
                <button
                  className="btn sm ghost"
                  onClick={() => {
                    setSelectedRunId(inspectedRun.id);
                    setScreen('logs');
                  }}
                >
                  {t.open_full_logs}
                </button>
              </div>
              {inspectedRun.err_message && (
                <div className="mono-s" style={{ color: 'var(--err)', marginBottom: 8 }}>
                  {inspectedRun.err_message}
                </div>
              )}
              <div className="console" style={{ maxHeight: 220 }}>
                {splitLogLines(storedLogText).length > 0 ? (
                  splitLogLines(storedLogText).map((line, i) => (
                    <div className="ln" key={i}>
                      <span className="no">{i + 1}</span>
                      <span style={{ whiteSpace: 'pre-wrap' }}>{line || ' '}</span>
                    </div>
                  ))
                ) : (
                  <div className="ln">
                    <span className="ts" />
                    <span className="lvl-dim">{t.no_log_output}</span>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    );
  }

  const job = jobs.find((j) => j.id === liveRun.job);
  const curId = liveRun.order[liveRun.currentIdx];
  const curStep = job?.steps.find((s) => s.id === curId);
  const curState = liveRun.stepStates[curId];
  const doneCount = liveRun.order.slice(0, liveRun.currentIdx).length;
  const pct = Math.round((doneCount / liveRun.order.length) * 100);

  return (
    <div>
      <div className="page-head">
        <h1>Run #{liveRun.id}</h1>
        <span className="sub">{job?.id} · {job?.name}</span>
        <span className="chip info live">
          <span className="d" />
          LIVE
        </span>
        <div className="spacer" />
        <button className="btn sm danger" onClick={() => cancelRun()}>
          ■ stop
        </button>
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '260px 1fr 220px',
          minHeight: 'calc(100vh - 96px)',
        }}
      >
        <div
          style={{
            borderRight: '1px solid var(--line)',
            padding: 12,
            background: 'var(--bg-2)',
            overflow: 'auto',
          }}
        >
          <div className="ctitle">Progress</div>
          <div className="pbar">
            <span style={{ width: pct + '%' }} />
          </div>
          <div className="mono-s dim" style={{ marginTop: 4 }}>
            {doneCount} / {liveRun.order.length} · {liveRun.dur.toFixed(1)}s
          </div>
          <div className="ctitle" style={{ marginTop: 14 }}>Steps</div>
          {liveRun.order.map((id, i) => {
            const st = liveRun.stepStates[id];
            const state = st.state.toLowerCase();
            return (
              <div
                key={id}
                style={{
                  display: 'grid',
                  gridTemplateColumns: '20px 1fr auto',
                  gap: 8,
                  alignItems: 'center',
                  padding: '5px 6px',
                  borderRadius: 3,
                  background: i === liveRun.currentIdx ? 'var(--panel)' : 'transparent',
                  borderLeft:
                    i === liveRun.currentIdx ? '2px solid var(--info)' : '2px solid transparent',
                }}
              >
                <span className={`sdot ${state}`} />
                <div>
                  <div
                    className="mono"
                    style={{ fontSize: 11, fontWeight: i === liveRun.currentIdx ? 700 : 500 }}
                  >
                    {id}
                  </div>
                  {state === 'running' && (
                    <div className="mono-s" style={{ color: 'var(--info)' }}>
                      running · {st.elapsed.toFixed(1)}s
                    </div>
                  )}
                </div>
                <span className="mono-s dim">
                  {state === 'success' ? st.elapsed.toFixed(1) + 's' : state === 'running' ? '…' : '—'}
                </span>
              </div>
            );
          })}
        </div>

        <div
          style={{
            padding: 14,
            display: 'flex',
            flexDirection: 'column',
            minHeight: 0,
          }}
        >
          <div className="row" style={{ marginBottom: 8 }}>
            <span className="mono" style={{ fontWeight: 600 }}>
              step: {curId}
            </span>
            {curStep && (
              <span className="chip info live">
                <span className="d" /> {curState.elapsed.toFixed(1)}s / {curStep.timeout}s timeout
              </span>
            )}
            <div className="spacer" />
            <span className="mono-s dim">stdout + stderr</span>
          </div>
          <div className="console" style={{ flex: 1, minHeight: 300 }}>
            {curState.logs.slice(-200).map((l, i) => (
              <div key={i} className="ln">
                <span className="ts">{l.ts}</span>
                <span className={`lvl-${l.lvl}`}>{l.text}</span>
              </div>
            ))}
            <div className="ln">
              <span className="ts" />
              <span>
                <span className="caret" />
              </span>
            </div>
          </div>
          <div className="mono-s dim" style={{ marginTop: 4 }}>
            {curState.logs.length} lines · live (SSE)
          </div>
        </div>

        <div
          style={{
            borderLeft: '1px solid var(--line)',
            padding: 12,
            background: 'var(--bg-2)',
            overflow: 'auto',
          }}
        >
          <div className="ctitle">{t.run_info}</div>
          <div className="kv">
            <div className="k">trigger</div>
            <div className="v">web</div>
            <div className="k">elapsed</div>
            <div className="v">{liveRun.dur.toFixed(1)}s</div>
          </div>
          <div className="ctitle" style={{ marginTop: 12 }}>{t.policy}</div>
          <div className="mono-s" style={{ lineHeight: 1.8 }}>
            <div>
              <span className="chip ok">shell=False</span>
            </div>
            <div>
              <span className="chip">user=taskflow</span>
            </div>
            <div>
              <span className="chip warn">no-root</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
