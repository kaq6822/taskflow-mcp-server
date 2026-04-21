import { useT } from '../i18n/useT';
import { Screen, useStore } from '../store/store';

type Nav = { id: Screen; label: (t: ReturnType<typeof useT>) => string; ico: string; group: string };

const NAV: Nav[] = [
  { id: 'dashboard', label: () => 'Dashboard', ico: '▤', group: 'workspace' },
  { id: 'detail', label: (t) => t.nav_job_detail, ico: '◉', group: 'workspace' },
  { id: 'builder', label: () => 'Workflow Builder', ico: '◇', group: 'workspace' },
  { id: 'monitor', label: (t) => t.nav_run_monitor, ico: '▷', group: 'runtime' },
  { id: 'logs', label: (t) => t.nav_step_logs, ico: '≡', group: 'runtime' },
  { id: 'artifacts', label: (t) => t.nav_artifacts, ico: '▦', group: 'assets' },
  { id: 'audit', label: (t) => t.nav_audit, ico: '◆', group: 'assets' },
  { id: 'mcp', label: () => 'MCP Key', ico: '⚹', group: 'integration' },
];

const GROUP_LABELS: Record<string, (t: ReturnType<typeof useT>) => string> = {
  workspace: (t) => t.nav_group_workspace,
  runtime: (t) => t.nav_group_runtime,
  assets: (t) => t.nav_group_assets,
  integration: (t) => t.nav_group_integration,
};

export function Sidebar() {
  const t = useT();
  const screen = useStore((s) => s.screen);
  const setScreen = useStore((s) => s.setScreen);
  const jobs = useStore((s) => s.jobs);
  const artifacts = useStore((s) => s.artifacts);
  const keys = useStore((s) => s.keys);
  const liveRun = useStore((s) => s.liveRun);
  const lang = useStore((s) => s.lang);
  const setLang = useStore((s) => s.setLang);

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
            <div className="nav-label">{GROUP_LABELS[g](t)}</div>
            {NAV.filter((n) => n.group === g).map((n) => {
              const count = countFor(n.id);
              return (
                <div
                  key={n.id}
                  className={`nav-item ${screen === n.id ? 'active' : ''}`}
                  onClick={() => setScreen(n.id)}
                >
                  <span className="ico">{n.ico}</span>
                  <span>{n.label(t)}</span>
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
        <span>{t.sidebar_worker}</span>
        <div className="spacer" />
        <button
          className={`btn ghost sm${lang === 'ko' ? ' active' : ''}`}
          style={{ fontSize: 10, padding: '2px 5px', minWidth: 0 }}
          onClick={() => setLang('ko')}
        >
          KO
        </button>
        <button
          className={`btn ghost sm${lang === 'en' ? ' active' : ''}`}
          style={{ fontSize: 10, padding: '2px 5px', minWidth: 0 }}
          onClick={() => setLang('en')}
        >
          EN
        </button>
      </div>
    </aside>
  );
}
