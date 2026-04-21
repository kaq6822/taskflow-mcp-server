import { useMemo, useState } from 'react';

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

export function Audit() {
  const t = useT();
  const audit = useStore((s) => s.audit);

  const [kindF, setKindF] = useState('all');
  const [resultF, setResultF] = useState('all');
  const [search, setSearch] = useState('');

  const kinds = useMemo(() => ['all', ...Array.from(new Set(audit.map((a) => a.kind)))], [audit]);
  const results = ['all', 'OK', 'DENY', 'FAIL'];

  const filtered = audit.filter(
    (a) =>
      (kindF === 'all' || a.kind === kindF) &&
      (resultF === 'all' || a.result === resultF) &&
      (!search ||
        a.who.includes(search) ||
        a.target.includes(search) ||
        a.kind.includes(search))
  );

  return (
    <div>
      <div className="page-head">
        <h1>Audit Log</h1>
        <span className="sub">append-only · hash-chained</span>
        <span className="chip ok">
          <span className="d" />
          tamper-evident
        </span>
        <div className="spacer" />
        <input
          className="input sm"
          style={{ width: 200 }}
          placeholder="🔍 actor / target / kind"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select
          className="select"
          style={{ width: 150, fontSize: 11 }}
          value={kindF}
          onChange={(e) => setKindF(e.target.value)}
        >
          {kinds.map((k) => (
            <option key={k} value={k}>
              {k}
            </option>
          ))}
        </select>
        <select
          className="select"
          style={{ width: 90, fontSize: 11 }}
          value={resultF}
          onChange={(e) => setResultF(e.target.value)}
        >
          {results.map((k) => (
            <option key={k} value={k}>
              {k}
            </option>
          ))}
        </select>
        <a className="btn sm ghost" href="/api/audit/export.csv">⬇ CSV</a>
      </div>

      <div
        style={{
          padding: '14px 18px 0',
          display: 'grid',
          gridTemplateColumns: 'repeat(4,1fr)',
          gap: 12,
        }}
      >
        <StatBlock label="Events" value={audit.length} />
        <StatBlock label="Denied" value={audit.filter((a) => a.result === 'DENY').length} tone="err" />
        <StatBlock
          label="MCP events"
          value={audit.filter((a) => a.src === 'mcp').length}
          tone="accent"
        />
        <StatBlock label="Unique actors" value={new Set(audit.map((a) => a.who)).size} />
      </div>

      {audit.length === 0 ? (
        <div style={{ padding: '40px 18px', textAlign: 'center' }}>
          <div style={{ color: 'var(--ink-3)' }}>{t.no_audit_events}</div>
        </div>
      ) : (
        <>
          <table className="tbl" style={{ marginTop: 14 }}>
            <thead>
              <tr>
                <th style={{ width: 170 }}>Time</th>
                <th>Actor</th>
                <th>Kind</th>
                <th>Target</th>
                <th>Source</th>
                <th>IP</th>
                <th>Result</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((a) => (
                <tr key={a.id}>
                  <td className="mono-s dim">{a.at.slice(0, 19).replace('T', ' ')}</td>
                  <td
                    className="mono-s"
                    style={{
                      fontWeight: a.src === 'mcp' ? 600 : 500,
                      color: a.src === 'mcp' ? 'var(--accent)' : 'inherit',
                    }}
                  >
                    {a.who}
                  </td>
                  <td>
                    <span
                      className={`chip ${
                        a.kind.includes('fail') ||
                        a.kind.includes('violation') ||
                        a.kind.includes('auth.fail')
                          ? 'err'
                          : a.kind.startsWith('mcp')
                          ? 'accent'
                          : a.kind.includes('run')
                          ? 'info'
                          : ''
                      }`}
                    >
                      {a.kind}
                    </span>
                  </td>
                  <td className="mono-s">{a.target}</td>
                  <td>
                    <span className="chip">{a.src}</span>
                  </td>
                  <td className="mono-s dim">{a.ip}</td>
                  <td>
                    {a.result === 'OK' && (
                      <span className="chip ok">
                        <span className="d" />
                        OK
                      </span>
                    )}
                    {a.result === 'DENY' && (
                      <span className="chip err">
                        <span className="d" />
                        DENY
                      </span>
                    )}
                    {a.result === 'FAIL' && (
                      <span className="chip err">
                        <span className="d" />
                        FAIL
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ padding: '14px 18px' }} className="mono-s dim">
            showing {filtered.length} of {audit.length} events · hash-chained (verify at
            <code> GET /api/audit/verify</code>)
          </div>
        </>
      )}
    </div>
  );
}
