import { Fragment } from 'react';

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

export function Topbar() {
  const screen = useStore((s) => s.screen);
  const setScreen = useStore((s) => s.setScreen);
  const selectedJobId = useStore((s) => s.selectedJobId);
  const liveRun = useStore((s) => s.liveRun);

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
      <input className="search" placeholder="🔍 search jobs, runs, artifacts…" />
      <span className="k">⌘K</span>
    </div>
  );
}
