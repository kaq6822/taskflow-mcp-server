import { Screen, useStore } from '../store/store';

type Nav = { id: Screen; label: string; ico: string; group: string };

const NAV: Nav[] = [
  { id: 'dashboard', label: 'Dashboard', ico: '▤', group: 'Workspace' },
  { id: 'detail', label: 'Job 상세', ico: '◉', group: 'Workspace' },
  { id: 'builder', label: 'Workflow Builder', ico: '◇', group: 'Workspace' },
  { id: 'monitor', label: '실행 모니터', ico: '▷', group: 'Runtime' },
  { id: 'logs', label: 'Step 로그 & 결과', ico: '≡', group: 'Runtime' },
  { id: 'artifacts', label: '배포 아티팩트', ico: '▦', group: 'Assets' },
  { id: 'audit', label: '감사 로그', ico: '◆', group: 'Assets' },
  { id: 'mcp', label: 'MCP Key', ico: '⚹', group: 'Integration' },
];

export function Sidebar() {
  const screen = useStore((s) => s.screen);
  const setScreen = useStore((s) => s.setScreen);
  const jobs = useStore((s) => s.jobs);
  const artifacts = useStore((s) => s.artifacts);
  const keys = useStore((s) => s.keys);
  const liveRun = useStore((s) => s.liveRun);

  const groups = Array.from(new Set(NAV.map((n) => n.group)));

  const countFor = (id: Screen): number | null => {
    if (id === 'dashboard') return jobs.length;
    if (id === 'monitor') return liveRun ? 1 : 0;
    if (id === 'artifacts') return artifacts.length;
    if (id === 'mcp') return keys.filter((k) => k.state === 'ACTIVE').length;
    return null;
  };

  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-logo">
          Task<span className="dot">Flow</span>
        </div>
        <div className="brand-sub">mcp · orchestration</div>
      </div>
      <nav className="nav">
        {groups.map((g) => (
          <div key={g}>
            <div className="nav-label">{g}</div>
            {NAV.filter((n) => n.group === g).map((n) => {
              const count = countFor(n.id);
              return (
                <div
                  key={n.id}
                  className={`nav-item ${screen === n.id ? 'active' : ''}`}
                  onClick={() => setScreen(n.id)}
                >
                  <span className="ico">{n.ico}</span>
                  <span>{n.label}</span>
                  {count != null && count > 0 && (
                    <span
                      className="count"
                      style={n.id === 'monitor' ? { background: 'var(--info-soft)', color: 'var(--info)' } : undefined}
                    >
                      {n.id === 'monitor' ? '● ' : ''}
                      {count}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        ))}
      </nav>
      <div className="sidebar-foot">
        <span className="pulse" />
        <span>worker · in-process</span>
      </div>
    </aside>
  );
}
