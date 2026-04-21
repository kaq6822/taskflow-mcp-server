import { useState } from 'react';

import { api } from '../api/client';
import { useT } from '../i18n/useT';
import { useStore } from '../store/store';

function StatBlock({
  label,
  value,
  tone,
}: {
  label: string;
  value: number | string;
  tone?: 'err' | 'accent';
}) {
  const color = tone === 'err' ? 'var(--err)' : tone === 'accent' ? 'var(--accent)' : 'var(--ink)';
  return (
    <div className="card">
      <div className="ctitle">{label}</div>
      <div style={{ fontSize: 24, fontWeight: 600, color, letterSpacing: '-0.02em' }}>{value}</div>
    </div>
  );
}

export function McpKeys() {
  const t = useT();
  const keys = useStore((s) => s.keys);
  const audit = useStore((s) => s.audit);
  const refreshKeys = useStore((s) => s.refreshKeys);
  const refreshAudit = useStore((s) => s.refreshAudit);
  const pushToast = useStore((s) => s.pushToast);

  const [issuing, setIssuing] = useState(false);

  const stateChip = (st: string) => {
    if (st === 'ACTIVE')
      return (
        <span className="chip ok">
          <span className="d" />
          ACTIVE
        </span>
      );
    if (st === 'EXPIRING')
      return (
        <span className="chip warn">
          <span className="d" />
          EXPIRING
        </span>
      );
    if (st === 'REVOKED')
      return (
        <span className="chip err">
          <span className="d" />
          REVOKED
        </span>
      );
    return <span className="chip">{st}</span>;
  };

  const handleRevoke = async (id: string) => {
    try {
      await api.revokeKey(id);
      pushToast(t.toast_key_revoked, 'err');
      await refreshKeys();
      await refreshAudit();
    } catch (e) {
      pushToast(t.toast_revoke_fail(String(e)), 'err');
    }
  };

  return (
    <div>
      <div className="page-head">
        <h1>MCP Access Keys</h1>
        <span className="sub mono">http://localhost:7391/mcp</span>
        <div className="spacer" />
        <button className="btn primary sm" onClick={() => setIssuing(true)}>
          {t.btn_issue_key}
        </button>
      </div>

      <div style={{ padding: '14px 18px' }}>
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(4,1fr)',
            gap: 12,
            marginBottom: 14,
          }}
        >
          <StatBlock
            label="Active keys"
            value={keys.filter((k) => k.state === 'ACTIVE').length}
            tone="accent"
          />
          <StatBlock
            label="Expiring soon"
            value={keys.filter((k) => k.state === 'EXPIRING').length}
            tone="err"
          />
          <StatBlock label="Revoked" value={keys.filter((k) => k.state === 'REVOKED').length} />
          <StatBlock label="MCP events" value={audit.filter((a) => a.src === 'mcp').length} />
        </div>

        {keys.length === 0 ? (
          <div style={{ padding: '40px 0', textAlign: 'center' }}>
            <div style={{ fontSize: 40, color: 'var(--ink-4)', marginBottom: 10 }}>⚹</div>
            <div style={{ color: 'var(--ink-3)' }}>{t.no_keys}</div>
          </div>
        ) : (
          <table className="tbl">
            <thead>
              <tr>
                <th>Label</th>
                <th>Key</th>
                <th>Scopes</th>
                <th>{t.col_created}</th>
                <th>{t.col_expires}</th>
                <th>Rate limit</th>
                <th>{t.col_status}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {keys.map((k) => (
                <tr key={k.id}>
                  <td style={{ fontWeight: 600 }}>{k.label}</td>
                  <td className="mono-s">
                    {k.key_prefix}••••{k.key_suffix}
                  </td>
                  <td>
                    {k.scopes.length === 0 && <span className="mono-s dim">—</span>}
                    {k.scopes.map((sc) => (
                      <span
                        key={sc}
                        className={`chip ${
                          sc.startsWith('run:') ? 'accent' : sc.startsWith('write:') ? 'warn' : 'info'
                        }`}
                        style={{ marginRight: 3, marginBottom: 2, display: 'inline-block' }}
                      >
                        {sc}
                      </span>
                    ))}
                  </td>
                  <td className="mono-s dim">{k.created.slice(0, 10)}</td>
                  <td className="mono-s">{k.expires ? k.expires.slice(0, 10) : '—'}</td>
                  <td className="mono-s">{k.rate_limit}</td>
                  <td>{stateChip(k.state)}</td>
                  <td>
                    {k.state !== 'REVOKED' && (
                      <button className="btn sm danger" onClick={() => handleRevoke(k.id)}>
                        revoke
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: '1fr 1fr',
            gap: 14,
            marginTop: 14,
          }}
        >
          <div className="card">
            <div className="ctitle">{t.connection_example}</div>
            <div className="console" style={{ fontSize: 10 }}>
              <div className="ln">
                <span className="lvl-dim"># ~/.config/claude/mcp.json</span>
              </div>
              <div className="ln">
                <span>{'{'}</span>
              </div>
              <div className="ln">
                <span>{'  "taskflow": {'}</span>
              </div>
              <div className="ln">
                <span>{'    "endpoint": "http://localhost:7391/mcp",'}</span>
              </div>
              <div className="ln">
                <span>{'    "auth": "Bearer mcp_tk_live_...",'}</span>
              </div>
              <div className="ln">
                <span>{'    "scopes": ["read:*", "run:<job-id>"]'}</span>
              </div>
              <div className="ln">
                <span>{'  }'}</span>
              </div>
              <div className="ln">
                <span>{'}'}</span>
              </div>
            </div>
          </div>
          <div className="card">
            <div className="ctitle">{t.recent_mcp_calls}</div>
            <table className="tbl" style={{ fontSize: 11 }}>
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Agent</th>
                  <th>Target</th>
                  <th>Result</th>
                </tr>
              </thead>
              <tbody>
                {audit.filter((a) => a.src === 'mcp').slice(0, 5).map((a) => (
                  <tr key={a.id}>
                    <td className="mono-s dim">{a.at.slice(11, 19)}</td>
                    <td
                      className="mono-s"
                      style={{ color: 'var(--accent)', fontWeight: 600 }}
                    >
                      {a.who}
                    </td>
                    <td className="mono-s">{a.target}</td>
                    <td>
                      {a.result === 'OK' ? (
                        <span className="chip ok">
                          <span className="d" />
                          OK
                        </span>
                      ) : (
                        <span className="chip err">
                          <span className="d" />
                          {a.result}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
                {audit.filter((a) => a.src === 'mcp').length === 0 && (
                  <tr>
                    <td colSpan={4} className="mono-s dim">
                      {t.no_mcp_calls}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {issuing && <IssueKeyModal onClose={() => setIssuing(false)} />}
    </div>
  );
}

function IssueKeyModal({ onClose }: { onClose: () => void }) {
  const t = useT();
  const refreshKeys = useStore((s) => s.refreshKeys);
  const refreshAudit = useStore((s) => s.refreshAudit);
  const jobs = useStore((s) => s.jobs);
  const pushToast = useStore((s) => s.pushToast);

  const [label, setLabel] = useState('');
  const [exp, setExp] = useState<30 | 90 | 180>(90);
  const [rate, setRate] = useState<'10/min' | '30/min' | '60/min'>('30/min');
  const availableScopes = [
    'read:jobs',
    'read:runs',
    'read:*',
    'write:uploads',
    ...jobs.map((j) => `run:${j.id}`),
    'run:*',
  ];
  const [scopes, setScopes] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(availableScopes.map((s) => [s, s === 'read:jobs' || s === 'read:runs']))
  );
  const [issued, setIssued] = useState<string | null>(null);

  const submit = async () => {
    if (!label) return;
    const selected = Object.keys(scopes).filter((k) => scopes[k]);
    try {
      const res = await api.issueKey({
        label,
        scopes: selected,
        expires_days: exp,
        rate_limit: rate,
      });
      setIssued(res.plaintext);
      await refreshKeys();
      await refreshAudit();
    } catch (e) {
      pushToast(t.toast_issue_fail(String(e)), 'err');
    }
  };

  const dayLabel = (d: number) => (d === 30 ? '30 days' : d === 90 ? '90 days' : '180 days');

  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        {!issued ? (
          <>
            <h3>{t.modal_issue_title}</h3>
            <div className="col" style={{ gap: 10 }}>
              <div>
                <label className="mono-s dim">Label</label>
                <input
                  className="input"
                  value={label}
                  onChange={(e) => setLabel(e.target.value)}
                  placeholder="claude · staging"
                />
              </div>
              <div>
                <label className="mono-s dim">Scopes</label>
                <div
                  style={{
                    border: '1px solid var(--line)',
                    borderRadius: 4,
                    padding: 8,
                    maxHeight: 200,
                    overflow: 'auto',
                  }}
                >
                  {availableScopes.map((sc) => (
                    <label
                      key={sc}
                      style={{
                        display: 'flex',
                        gap: 6,
                        padding: '3px 0',
                        fontSize: 12,
                        fontFamily: 'var(--mono)',
                        cursor: 'pointer',
                      }}
                    >
                      <input
                        type="checkbox"
                        checked={!!scopes[sc]}
                        onChange={(e) => setScopes({ ...scopes, [sc]: e.target.checked })}
                      />
                      <span>{sc}</span>
                    </label>
                  ))}
                </div>
              </div>
              <div className="split s2" style={{ gap: 10 }}>
                <div>
                  <label className="mono-s dim">{t.expires_period}</label>
                  <select
                    className="select"
                    value={exp}
                    onChange={(e) => setExp(Number(e.target.value) as 30 | 90 | 180)}
                  >
                    <option value={30}>{dayLabel(30)}</option>
                    <option value={90}>{dayLabel(90)}</option>
                    <option value={180}>{dayLabel(180)}</option>
                  </select>
                </div>
                <div>
                  <label className="mono-s dim">Rate limit</label>
                  <select
                    className="select"
                    value={rate}
                    onChange={(e) => setRate(e.target.value as typeof rate)}
                  >
                    <option>10/min</option>
                    <option>30/min</option>
                    <option>60/min</option>
                  </select>
                </div>
              </div>
            </div>
            <div className="row" style={{ marginTop: 16 }}>
              <button className="btn ghost" onClick={onClose}>
                {t.cancel}
              </button>
              <div className="spacer" />
              <button className="btn primary" onClick={submit} disabled={!label}>
                {t.btn_key_issue}
              </button>
            </div>
          </>
        ) : (
          <>
            <h3 style={{ color: 'var(--accent)' }}>{t.key_issued_title}</h3>
            <div className="mono-s dim" style={{ marginBottom: 8 }}>
              {t.key_issued_hint}
            </div>
            <div className="console" style={{ fontSize: 11, wordBreak: 'break-all' }}>
              <div className="ln">
                <span className="lvl-cmd">{issued}</span>
              </div>
            </div>
            <div className="row" style={{ marginTop: 16 }}>
              <button
                className="btn ghost"
                onClick={() => {
                  navigator.clipboard.writeText(issued);
                }}
              >
                {t.btn_copy}
              </button>
              <div className="spacer" />
              <button className="btn primary" onClick={onClose}>
                {t.done}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
