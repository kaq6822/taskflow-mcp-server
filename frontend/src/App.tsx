import { useEffect } from 'react';

import { Sidebar } from './components/Sidebar';
import { Toasts } from './components/Toasts';
import { Topbar } from './components/Topbar';
import { Artifacts } from './screens/Artifacts';
import { Audit } from './screens/Audit';
import { Builder } from './screens/Builder';
import { Dashboard } from './screens/Dashboard';
import { JobDetail } from './screens/JobDetail';
import { Logs } from './screens/Logs';
import { McpKeys } from './screens/McpKeys';
import { Monitor } from './screens/Monitor';
import { Screen, useStore } from './store/store';

const screens: Record<Screen, () => JSX.Element> = {
  dashboard: Dashboard,
  detail: JobDetail,
  builder: Builder,
  monitor: Monitor,
  logs: Logs,
  artifacts: Artifacts,
  audit: Audit,
  mcp: McpKeys,
};

export function App() {
  const screen = useStore((s) => s.screen);
  const refreshAll = useStore((s) => s.refreshAll);

  useEffect(() => {
    // The design system ships with DAG viz + compact density as the fixed
    // production look. The per-user toggle was a prototype-only feature and
    // is not part of this app.
    document.body.className = 'density-compact viz-dag';
  }, []);

  useEffect(() => {
    refreshAll().catch(() => {
      /* initial fetch failure is non-fatal */
    });
  }, [refreshAll]);

  const Current = screens[screen];
  return (
    <div className="app">
      <Sidebar />
      <div className="main">
        <Topbar />
        <div className="content">
          <Current />
        </div>
      </div>
      <Toasts />
    </div>
  );
}
