import { Fragment, useEffect, useMemo, useRef, useState } from 'react';

import { Screen, useStore } from '../store/store';

const CRUMBS: Record<Screen, [string, Screen | null][]> = {
  dashboard: [['Dashboard', null]],
  detail: [['Jobs', 'dashboard'], ['{job}', null]],
  builder: [['Jobs', 'dashboard'], ['{job}', 'detail'], ['Edit', null]],
  monitor: [['Runs', null]],
  logs: [['Runs', 'monitor'], ['Logs', null]],
  artifacts: [['Artifacts', null]],
  audit: [['Audit', null]],
  mcp: [['MCP', null], ['Keys', null]],
};

const IS_MAC =
  typeof navigator !== 'undefined' &&
  /Mac|iPhone|iPad|iPod/i.test(
    (navigator as Navigator & { userAgentData?: { platform?: string } }).userAgentData?.platform ||
      navigator.platform ||
      navigator.userAgent ||
      ''
  );

const SHORTCUT_LABEL = IS_MAC ? '⌘K' : 'Ctrl+K';

type Hit =
  | { kind: 'job'; id: string; label: string; sub: string }
  | { kind: 'run'; id: number; label: string; sub: string }
  | { kind: 'artifact'; id: number; label: string; sub: string };

export function Topbar() {
  const screen = useStore((s) => s.screen);
  const setScreen = useStore((s) => s.setScreen);
  const selectedJobId = useStore((s) => s.selectedJobId);
  const setSelectedJobId = useStore((s) => s.setSelectedJobId);
  const setSelectedRunId = useStore((s) => s.setSelectedRunId);
  const liveRun = useStore((s) => s.liveRun);
  const jobs = useStore((s) => s.jobs);
  const runs = useStore((s) => s.runs);
  const artifacts = useStore((s) => s.artifacts);

  const inputRef = useRef<HTMLInputElement>(null);
  const [q, setQ] = useState('');
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const modifier = IS_MAC ? e.metaKey : e.ctrlKey;
      if (modifier && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        inputRef.current?.focus();
        inputRef.current?.select();
      } else if (e.key === 'Escape' && document.activeElement === inputRef.current) {
        inputRef.current?.blur();
        setOpen(false);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const hits: Hit[] = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (!s) return [];
    const out: Hit[] = [];
    for (const j of jobs) {
      if (
        j.id.toLowerCase().includes(s) ||
        (j.name || '').toLowerCase().includes(s) ||
        (j.tags || []).some((t) => t.toLowerCase().includes(s))
      ) {
        out.push({ kind: 'job', id: j.id, label: j.id, sub: j.name || '—' });
      }
    }
    for (const r of runs) {
      if (String(r.id).includes(s) || r.job_id.toLowerCase().includes(s)) {
        out.push({
          kind: 'run',
          id: r.id,
          label: `#${r.id}`,
          sub: `${r.job_id} · ${r.status}`,
        });
      }
    }
    for (const a of artifacts) {
      if (
        a.name.toLowerCase().includes(s) ||
        (a.version || '').toLowerCase().includes(s)
      ) {
        out.push({
          kind: 'artifact',
          id: a.id,
          label: `${a.name}@${a.version}`,
          sub: a.uploader,
        });
      }
    }
    return out.slice(0, 30);
  }, [q, jobs, runs, artifacts]);

  const pick = (h: Hit) => {
    if (h.kind === 'job') {
      setSelectedJobId(h.id);
      setScreen('detail');
    } else if (h.kind === 'run') {
      setSelectedRunId(h.id);
      setScreen('logs');
    } else {
      setScreen('artifacts');
    }
    setQ('');
    setOpen(false);
    inputRef.current?.blur();
  };

  const crumbs = CRUMBS[screen].map(
    ([label, target]) =>
      [label.replace('{job}', selectedJobId || '…'), target] as [string, Screen | null]
  );

  return (
    <div className="topbar">
      <div className="crumbs">
        <span className="mono" style={{ color: 'var(--accent)' }}>
          taskflow
        </span>
        <span className="sep">/</span>
        {crumbs.map(([label, target], i) => (
          <Fragment key={i}>
            {target ? (
              <a onClick={() => setScreen(target)}>{label}</a>
            ) : (
              <span className={i === crumbs.length - 1 ? 'here' : ''}>{label}</span>
            )}
            {i < crumbs.length - 1 && <span className="sep">/</span>}
          </Fragment>
        ))}
      </div>
      <div className="spacer" />
      {liveRun && (
        <div
          className="chip info live"
          onClick={() => setScreen('monitor')}
          style={{ cursor: 'pointer' }}
        >
          <span className="d" /> Run #{liveRun.id} · {liveRun.job} · {liveRun.currentIdx + 1}/
          {liveRun.order.length}
        </div>
      )}
      <div className="searchwrap">
        <input
          ref={inputRef}
          className="search"
          placeholder="🔍 search jobs, runs, artifacts…"
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setOpen(true);
          }}
          onFocus={() => {
            if (q) setOpen(true);
          }}
          onBlur={() => {
            window.setTimeout(() => setOpen(false), 150);
          }}
        />
        {open && q.trim() && (
          <div className="search-menu">
            {hits.length > 0 ? (
              hits.map((h, i) => (
                <div
                  key={`${h.kind}-${String((h as { id: unknown }).id)}-${i}`}
                  className="search-item"
                  onMouseDown={(e) => {
                    e.preventDefault();
                    pick(h);
                  }}
                >
                  <span className={`kindtag ${h.kind}`}>{h.kind}</span>
                  <span className="mono-s" style={{ fontWeight: 600 }}>
                    {h.label}
                  </span>
                  <span className="mono-s dim" style={{ marginLeft: 'auto' }}>
                    {h.sub}
                  </span>
                </div>
              ))
            ) : (
              <div className="search-empty mono-s dim">no results</div>
            )}
          </div>
        )}
      </div>
      <span className="k">{SHORTCUT_LABEL}</span>
    </div>
  );
}
