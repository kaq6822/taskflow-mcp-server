import { useMemo, useState } from 'react';

import { Run } from '../api/client';
import { useT } from '../i18n/useT';
import { useStore } from '../store/store';

function KpiCard({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: number | string;
  sub?: string;
  tone?: 'info' | 'err' | 'ok';
}) {
  const color =
    tone === 'info'
      ? 'var(--info)'
      : tone === 'err'
      ? 'var(--err)'
      : tone === 'ok'
      ? 'var(--ok)'
      : 'var(--ink)';
  return (
    <div className="card">
      <div className="ctitle">{label}</div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
        <div
          style={{
            fontSize: 28,
            fontWeight: 600,
            color,
            letterSpacing: '-0.02em',
          }}
        >
          {value}
        </div>
        {sub && <div className="mono-s dim">{sub}</div>}
      </div>
    </div>
  );
}

export function Dashboard() {
  const t = useT();
  const jobs = useStore((s) => s.jobs);
  const runs = useStore((s) => s.runs);
  const keys = useStore((s) => s.keys);
  const liveRun = useStore((s) => s.liveRun);
  const setScreen = useStore((s) => s.setScreen);
  const setSelectedJobId = useStore((s) => s.setSelectedJobId);
  const setSelectedRunId = useStore((s) => s.setSelectedRunId);
  const startRun = useStore((s) => s.startRun);
  const selectedJobId = useStore((s) => s.selectedJobId);

  const [tag, setTag] = useState('all');
  const tags = useMemo(
    () => ['all', ...Array.from(new Set(jobs.flatMap((j) => j.tags || [])))],
    [jobs]
  );
  const filtered = tag === 'all' ? jobs : jobs.filter((j) => j.tags?.includes(tag));

  const recentFailed = runs.filter(
    (r) => r.status === 'FAILED' || r.status === 'TIMEOUT'
  ).length;
  const scheduled = jobs.filter((j) => j.schedule !== 'manual').length;

  const openJob = (id: string) => {
    setSelectedJobId(id);
    setScreen('detail');
  };

  const lastRunFor = (jobId: string) => runs.find((r) => r.job_id === jobId);
  const successRate = (jobId: string) => {
    const rs = runs.filter((r) => r.job_id === jobId);
    if (rs.length === 0) return 100;
    const ok = rs.filter((r) => r.status === 'SUCCESS').length;
    return Math.round((ok / rs.length) * 100);
  };

  return (
    <div>
      <div className="page-head">
        <h1>Jobs</h1>
        <span className="sub">orchestration workspace</span>
        <div className="spacer" />
        <button
          className="btn primary sm"
          onClick={() => {
            setSelectedJobId(null);
            setScreen('builder');
          }}
        >
          {t.btn_new_job}
        </button>
      </div>

      <div
        style={{
          padding: '14px 18px',
          display: 'grid',
          gridTemplateColumns: 'repeat(4,1fr)',
          gap: 12,
        }}
      >
        <KpiCard label={t.kpi_total_jobs} value={jobs.length} />
        <KpiCard label={t.kpi_running} value={liveRun ? 1 : 0} tone="info" />
        <KpiCard
          label={t.kpi_recent_fails}
          value={recentFailed}
          tone={recentFailed > 0 ? 'err' : 'ok'}
          sub={`${runs.length}`}
        />
        <KpiCard label={t.kpi_scheduled} value={scheduled} sub="cron jobs" />
      </div>

      {jobs.length === 0 ? (
        <div style={{ padding: '40px 18px', textAlign: 'center' }}>
          <div style={{ fontSize: 40, color: 'var(--ink-4)', marginBottom: 10 }}>◌</div>
          <div style={{ color: 'var(--ink-3)', marginBottom: 16 }}>
            {t.dashboard_empty} <b>{t.btn_new_job}</b> — {t.dashboard_empty_hint}
          </div>
          <button
            className="btn primary"
            onClick={() => {
              setSelectedJobId(null);
              setScreen('builder');
            }}
          >
            {t.btn_new_job_create}
          </button>
        </div>
      ) : (
        <>
          <div
            style={{
              padding: '0 18px 10px',
              display: 'flex',
              gap: 6,
              alignItems: 'center',
            }}
          >
            {tags.map((tg) => (
              <span
                key={tg}
                className={`chip ${tag === tg ? 'accent' : ''}`}
                style={{ cursor: 'pointer' }}
                onClick={() => setTag(tg)}
              >
                {tg}
              </span>
            ))}
            <div className="spacer" />
            <span className="muted mono" style={{ fontSize: 11 }}>
              {t.dashboard_showing(filtered.length, jobs.length)}
            </span>
          </div>

          <table className="tbl">
            <thead>
              <tr>
                <th style={{ width: '28%' }}>Job</th>
                <th>Owner</th>
                <th>Schedule</th>
                <th>Last run</th>
                <th>Status</th>
                <th>{t.col_success_rate}</th>
                <th>Steps</th>
                <th>Runs</th>
                <th style={{ width: 120 }} />
              </tr>
            </thead>
            <tbody>
              {filtered.map((j) => {
                const last = lastRunFor(j.id);
                const running = liveRun && liveRun.job === j.id;
                const status = running ? 'RUNNING' : last?.status || 'NEW';
                const ok = successRate(j.id);
                return (
                  <tr
                    key={j.id}
                    className={selectedJobId === j.id ? 'selected' : ''}
                    onClick={() => openJob(j.id)}
                  >
                    <td>
                      <div style={{ fontWeight: 600 }}>{j.id}</div>
                      <div className="mono-s dim" style={{ marginTop: 1 }}>
                        {j.name}
                      </div>
                    </td>
                    <td className="mono-s">{j.owner}</td>
                    <td className="mono-s">
                      {j.schedule === 'manual' ? (
                        <span className="chip">manual</span>
                      ) : (
                        <span className="chip info">{j.schedule}</span>
                      )}
                    </td>
                    <td className="mono-s dim">
                      {running ? 'now' : last ? last.started_at.slice(0, 19).replace('T', ' ') : '—'}
                    </td>
                    <td>
                      <span
                        className={`chip ${
                          status === 'SUCCESS'
                            ? 'ok'
                            : status === 'RUNNING'
                            ? 'info live'
                            : status === 'FAILED' || status === 'TIMEOUT'
                            ? 'err'
                            : ''
                        }`}
                      >
                        <span className="d" />
                        {status}
                      </span>
                    </td>
                    <td>
                      <div className="meter">
                        <div className="bar">
                          <span
                            style={{
                              width: `${ok}%`,
                              background:
                                ok >= 98
                                  ? 'var(--ok)'
                                  : ok >= 90
                                  ? 'var(--warn)'
                                  : 'var(--err)',
                            }}
                          />
                        </div>
                        <span>{ok}%</span>
                      </div>
                    </td>
                    <td className="mono-s">{j.steps.length}</td>
                    <td className="mono-s dim">
                      {runs.filter((r) => r.job_id === j.id).length}
                    </td>
                    <td>
                      <button
                        className="btn sm primary"
                        onClick={(e) => {
                          e.stopPropagation();
                          startRun(j.id);
                        }}
                        disabled={!!liveRun}
                      >
                        {t.btn_run}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          <div
            style={{
              padding: '16px 18px',
              display: 'grid',
              gridTemplateColumns: '2fr 1fr',
              gap: 14,
            }}
          >
            <div className="card">
              <div className="ctitle">{t.recent_runs(runs.slice(0, 20).length)}</div>
              {runs.length === 0 ? (
                <div className="mono-s dim">{t.no_runs}</div>
              ) : (
                <>
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'flex-end',
                      gap: 4,
                      height: 60,
                      marginBottom: 8,
                    }}
                  >
                    {runs.slice(0, 20).reverse().map((r: Run, i: number) => (
                      <div
                        key={i}
                        title={`#${r.id} · ${r.status}`}
                        style={{
                          flex: 1,
                          minWidth: 4,
                          background:
                            r.status === 'SUCCESS'
                              ? 'var(--ok)'
                              : r.status === 'FAILED' || r.status === 'TIMEOUT'
                              ? 'var(--err)'
                              : 'var(--info)',
                          height: Math.max(8, Math.min(60, r.duration_sec * 5 + 8)),
                          borderRadius: 1,
                          opacity: 0.85,
                          cursor: 'pointer',
                        }}
                        onClick={() => {
                          setSelectedRunId(r.id);
                          setScreen('logs');
                        }}
                      />
                    ))}
                  </div>
                  <div className="mono-s dim">
                    {t.run_chart_hint}
                  </div>
                </>
              )}
            </div>
            <div className="card">
              <div className="ctitle">System</div>
              <div className="kv">
                <div className="k">API</div>
                <div className="v" style={{ color: 'var(--ok)' }}>● 200
                </div>
                <div className="k">Worker</div>
                <div className="v" style={{ color: 'var(--ok)' }}>● in-process
                </div>
                <div className="k">Queue</div>
                <div className="v">{liveRun ? '1 running' : 'idle'}</div>
                <div className="k">DB</div>
                <div className="v" style={{ color: 'var(--ok)' }}>● sqlite
                </div>
                <div className="k">MCP</div>
                <div className="v">{keys.filter((k) => k.state === 'ACTIVE').length} active keys</div>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
