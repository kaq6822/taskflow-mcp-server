import { useEffect, useState } from 'react';

import { Run, api } from '../api/client';
import { useT } from '../i18n/useT';
import { useStore } from '../store/store';

function splitLogLines(text: string): string[] {
  return text.replace(/\n$/, '').split('\n').filter((_, i, lines) => lines.length > 1 || lines[0]);
}

export function Logs() {
  const t = useT();
  const runs = useStore((s) => s.runs);
  const jobs = useStore((s) => s.jobs);
  const selectedRunId = useStore((s) => s.selectedRunId);
  const setSelectedRunId = useStore((s) => s.setSelectedRunId);
  const setScreen = useStore((s) => s.setScreen);
  const startRun = useStore((s) => s.startRun);
  const cancelRun = useStore((s) => s.cancelRun);
  const liveRun = useStore((s) => s.liveRun);

  const [selStep, setSelStep] = useState<string | null>(null);
  const [logText, setLogText] = useState<string>('');

  const run = runs.find((r) => r.id === selectedRunId) || runs[0];
  const job = run ? jobs.find((j) => j.id === run.job_id) : null;

  useEffect(() => {
    if (run && run.steps.length > 0) {
      setSelStep(run.failed_step || run.steps[0].step_id);
    } else {
      setSelStep(null);
    }
  }, [run?.id, run?.failed_step, run?.steps.length]);

  useEffect(() => {
    setLogText('');
    if (!run || !selStep) return;
    let active = true;
    api
      .getRunLogs(run.id, selStep, 500)
      .then((text) => {
        if (active) setLogText(text);
      })
      .catch(() => {
        if (active) setLogText(t.log_unavailable);
      });
    return () => {
      active = false;
    };
  }, [run?.id, selStep, t]);

  if (!run) {
    return (
      <div style={{ padding: 20 }} className="mono-s dim">
        {t.select_run_prompt}
      </div>
    );
  }
  if (!job) {
    return <div style={{ padding: 20 }} className="mono-s dim">{t.job_not_found}</div>;
  }

  const failedId = run.failed_step;
  const stepState = (id: string): string => {
    const rs = run.steps.find((s) => s.step_id === id);
    return (rs?.state || 'PENDING').toLowerCase();
  };
  const curStep = job.steps.find((s) => s.id === selStep);
  const curState = selStep ? stepState(selStep) : 'pending';

  return (
    <div>
      <div className="page-head">
        <h1>Run #{run.id}</h1>
        <span className="sub">
          {job.id} · {run.started_at.slice(0, 19).replace('T', ' ')}
        </span>
        <span
          className={`chip ${
            run.status === 'SUCCESS'
              ? 'ok'
              : run.status === 'FAILED'
              ? 'err'
              : run.status === 'RUNNING'
              ? 'info live'
              : 'warn'
          }`}
        >
          <span className="d" />
          {run.status}
        </span>
        <div className="spacer" />
        {run.status === 'RUNNING' ? (
          <button className="btn danger sm" onClick={() => cancelRun(run.id)}>
            {t.btn_stop}
          </button>
        ) : (
          <button
            className="btn primary sm"
            onClick={() => startRun(job.id)}
            disabled={!!liveRun}
          >
            {t.rerun}
          </button>
        )}
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '240px 1fr 260px',
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
          <div className="ctitle">Steps</div>
          {run.steps.map((rs) => {
            const state = rs.state.toLowerCase();
            const isFailed = state === 'failed' || state === 'timeout';
            return (
              <div
                key={rs.step_id}
                onClick={() => setSelStep(rs.step_id)}
                style={{
                  display: 'grid',
                  gridTemplateColumns: '16px 1fr auto',
                  gap: 8,
                  alignItems: 'center',
                  padding: '6px 8px',
                  borderRadius: 3,
                  cursor: 'pointer',
                  marginBottom: 2,
                  background:
                    selStep === rs.step_id
                      ? 'var(--accent-soft)'
                      : isFailed
                      ? 'var(--err-soft)'
                      : 'transparent',
                  borderLeft: isFailed ? '2px solid var(--err)' : '2px solid transparent',
                }}
              >
                <span className={`sdot ${state}`} />
                <div>
                  <div
                    className="mono"
                    style={{ fontSize: 11, fontWeight: isFailed ? 700 : 500 }}
                  >
                    {rs.step_id}
                  </div>
                  <div className="mono-s dim">{state}</div>
                </div>
                <span className="mono-s dim">
                  {rs.elapsed_sec > 0 ? `${rs.elapsed_sec.toFixed(1)}s` : '—'}
                </span>
              </div>
            );
          })}
          <div className="hr" />
          <div className="ctitle">{t.summary}</div>
          <div className="kv">
            <div className="k">result</div>
            <div
              className="v"
              style={{
                color: run.status === 'SUCCESS' ? 'var(--ok)' : 'var(--err)',
              }}
            >
              {run.status}
            </div>
            <div className="k">trigger</div>
            <div className="v">{run.trigger}</div>
            <div className="k">by</div>
            <div className="v">{run.actor}</div>
            <div className="k">duration</div>
            <div className="v">{run.duration_sec.toFixed(1)}s</div>
          </div>
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
            <span className="mono" style={{ fontSize: 13, fontWeight: 700 }}>
              {selStep}
            </span>
            <span
              className={`chip ${
                curState === 'success'
                  ? 'ok'
                  : curState === 'failed'
                  ? 'err'
                  : curState === 'timeout'
                  ? 'warn'
                  : ''
              }`}
            >
              <span className="d" />
              {curState.toUpperCase()}
            </span>
            <div className="spacer" />
            <span className="mono-s dim">logs from storage/logs/{run.id}/{selStep}.log</span>
          </div>
          <div className="console" style={{ flex: 1, minHeight: 260 }}>
            <div className="ln">
              <span className="ts" />
              <span className="lvl-dim">
                {t.log_path_hint(run.id, selStep || '')}
              </span>
            </div>
            {curStep && (
              <div className="ln">
                <span className="ts" />
                <span className="lvl-cmd">$ {curStep.cmd.join(' ')}</span>
              </div>
            )}
            {splitLogLines(logText).length > 0 ? (
              splitLogLines(logText).map((line, i) => (
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
          {(curState === 'failed' || curState === 'timeout') && (
            <div className="card" style={{ marginTop: 12, borderColor: 'var(--err)' }}>
              <div className="ctitle" style={{ color: 'var(--err)' }}>
                {t.error_diagnosis}
              </div>
              <div className="col mono-s" style={{ gap: 3 }}>
                <div>
                  • <b>{run.err_message || 'unknown error'}</b>
                </div>
                {failedId && <div>{t.failed_step_label(failedId)}</div>}
                <div>• {t.check_stderr}</div>
              </div>
              <div className="row" style={{ marginTop: 8, gap: 6 }}>
                <button
                  className="btn sm primary"
                  onClick={() => startRun(job.id)}
                  disabled={!!liveRun}
                >
                  {t.rerun}
                </button>
                <button className="btn sm ghost" onClick={() => setScreen('builder')}>
                  {t.edit_step_btn}
                </button>
              </div>
            </div>
          )}
        </div>

        <div
          style={{
            borderLeft: '1px solid var(--line)',
            padding: 12,
            background: 'var(--bg-2)',
            overflow: 'auto',
          }}
        >
          <div className="ctitle">{t.environment}</div>
          <div className="kv">
            <div className="k">user</div>
            <div className="v">taskflow</div>
            <div className="k">cwd</div>
            <div className="v">{curStep?.cwd || 'storage/runtime'}</div>
            <div className="k">shell</div>
            <div className="v">False</div>
          </div>
          {curStep && (
            <>
              <div className="ctitle" style={{ marginTop: 12 }}>Command</div>
              <div className="console" style={{ fontSize: 10, maxHeight: 80 }}>
                <div className="ln">
                  <span className="lvl-cmd">$ {curStep.cmd.join(' ')}</span>
                </div>
              </div>
              {((curStep.success_contains || []).length > 0 ||
                (curStep.failure_contains || []).length > 0) && (
                <>
                  <div className="ctitle" style={{ marginTop: 12 }}>Output Assertions</div>
                  <div className="col mono-s" style={{ gap: 4 }}>
                    {(curStep.success_contains || []).map((p) => (
                      <div key={`ok-${p}`}>
                        <span className="chip ok">must contain</span> {p}
                      </div>
                    ))}
                    {(curStep.failure_contains || []).map((p) => (
                      <div key={`fail-${p}`}>
                        <span className="chip err">fail on</span> {p}
                      </div>
                    ))}
                  </div>
                </>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
