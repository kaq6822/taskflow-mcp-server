// DAG / List / Timeline views, ported from proto/components/dag.jsx (algorithm only).

import { Step } from '../../api/client';
import { useStore } from '../../store/store';

type StepsLike = { steps: Step[] };
type RunStateLike = {
  stepStates: Record<string, { state: string; elapsed: number; logs: { ts: string; lvl: string; text: string }[] }>;
} | null;

type VizProps = {
  job: StepsLike;
  runState?: RunStateLike;
  selectedStep?: string | null;
  onStepClick?: (stepId: string) => void;
  compact?: boolean;
};

export function layoutDag(steps: Step[]) {
  const byId = Object.fromEntries(steps.map((s) => [s.id, s]));
  const level: Record<string, number> = {};
  const compute = (id: string): number => {
    if (level[id] !== undefined) return level[id];
    const s = byId[id];
    if (!s.deps || s.deps.length === 0) {
      level[id] = 0;
      return 0;
    }
    const lv = Math.max(...s.deps.map(compute)) + 1;
    level[id] = lv;
    return lv;
  };
  steps.forEach((s) => compute(s.id));
  const cols: Record<number, string[]> = {};
  steps.forEach((s) => {
    const lv = level[s.id];
    (cols[lv] = cols[lv] || []).push(s.id);
  });
  const COL_W = 160;
  const ROW_H = 60;
  const PAD_X = 20;
  const PAD_Y = 20;
  const pos: Record<string, { x: number; y: number }> = {};
  for (const [lv, ids] of Object.entries(cols)) {
    ids.forEach((id, row) => {
      pos[id] = { x: PAD_X + Number(lv) * COL_W, y: PAD_Y + row * ROW_H };
    });
  }
  const maxLv = Math.max(...Object.keys(cols).map(Number));
  const maxRows = Math.max(...Object.values(cols).map((a) => a.length));
  const width = PAD_X + (maxLv + 1) * COL_W;
  const height = PAD_Y + maxRows * ROW_H + 20;
  return { pos, width, height, byId };
}

function stateOf(runState: RunStateLike, id: string): string {
  if (!runState) return 'pending';
  const st = runState.stepStates[id];
  return (st?.state || 'pending').toLowerCase();
}

export function DagView({ job, runState, onStepClick, selectedStep, compact }: VizProps) {
  const layout = layoutDag(job.steps);
  const { pos, width, height } = layout;
  return (
    <div className="dag-stage" style={{ height: compact ? 220 : height + 20 }}>
      <svg
        width={width}
        height={height}
        style={{ position: 'absolute', left: 0, top: 0, pointerEvents: 'none' }}
      >
        <defs>
          <marker id="arr" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="5" markerHeight="5" orient="auto">
            <path d="M0,0 L10,5 L0,10 z" fill="var(--ink-4)" />
          </marker>
          <marker
            id="arr-ok"
            viewBox="0 0 10 10"
            refX="10"
            refY="5"
            markerWidth="5"
            markerHeight="5"
            orient="auto"
          >
            <path d="M0,0 L10,5 L0,10 z" fill="var(--ok)" />
          </marker>
        </defs>
        {job.steps.flatMap((st) =>
          (st.deps || []).map((dep) => {
            const from = pos[dep];
            const to = pos[st.id];
            if (!from || !to) return null;
            const x1 = from.x + 120;
            const y1 = from.y + 18;
            const x2 = to.x;
            const y2 = to.y + 18;
            const midX = (x1 + x2) / 2;
            const d = `M${x1},${y1} C${midX},${y1} ${midX},${y2} ${x2},${y2}`;
            const parentState = stateOf(runState ?? null, dep);
            const cls =
              parentState === 'success'
                ? 'edge done'
                : parentState === 'running'
                ? 'edge active'
                : 'edge';
            const marker = parentState === 'success' ? 'url(#arr-ok)' : 'url(#arr)';
            return <path key={`${dep}-${st.id}`} d={d} className={cls} markerEnd={marker} />;
          })
        )}
      </svg>
      {job.steps.map((st) => {
        const s = stateOf(runState ?? null, st.id);
        return (
          <div
            key={st.id}
            className={`node ${s} ${selectedStep === st.id ? 'selected' : ''}`}
            style={{ left: pos[st.id].x, top: pos[st.id].y }}
            onClick={() => onStepClick && onStepClick(st.id)}
          >
            <div className="n-name">{st.id}</div>
            <div className="n-cmd">
              {st.cmd.slice(0, 2).join(' ')}
              {st.cmd.length > 2 ? '…' : ''}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function ListView({ job, runState, onStepClick, selectedStep }: VizProps) {
  return (
    <div style={{ border: '1px solid var(--line)', borderRadius: 4, overflow: 'hidden' }}>
      {job.steps.map((st, i) => {
        const s = stateOf(runState ?? null, st.id);
        return (
          <div
            key={st.id}
            onClick={() => onStepClick && onStepClick(st.id)}
            style={{
              display: 'grid',
              gridTemplateColumns: '24px 20px 1fr auto auto',
              gap: 10,
              padding: '8px 12px',
              borderBottom: '1px solid var(--line-soft)',
              background: selectedStep === st.id ? 'var(--accent-soft)' : 'transparent',
              cursor: 'pointer',
            }}
          >
            <span className="mono-s dim">{String(i + 1).padStart(2, '0')}</span>
            <span className={`sdot ${s}`} style={{ marginTop: 4 }} />
            <div>
              <div className="mono" style={{ fontSize: 12, fontWeight: 600 }}>
                {st.id}
              </div>
              <div className="mono-s dim">{st.cmd.join(' ')}</div>
            </div>
            <div className="mono-s dim">deps: {(st.deps || []).join(',') || '—'}</div>
            <div className="mono-s dim">{st.timeout}s</div>
          </div>
        );
      })}
    </div>
  );
}

export function TimelineView({ job, runState }: VizProps) {
  const layout = layoutDag(job.steps);
  return (
    <div style={{ padding: 10 }}>
      {job.steps.map((st, i) => {
        const s = stateOf(runState ?? null, st.id);
        const startOffset = layout.pos[st.id] ? ((layout.pos[st.id].x - 20) / 160) * 120 : i * 120;
        const w = st.timeout / 3;
        return (
          <div
            key={st.id}
            style={{
              display: 'grid',
              gridTemplateColumns: '140px 1fr',
              gap: 10,
              padding: '3px 0',
              alignItems: 'center',
            }}
          >
            <div className="mono" style={{ fontSize: 11, fontWeight: 600 }}>
              <span className={`sdot ${s}`} style={{ marginRight: 6, verticalAlign: 'middle' }} />
              {st.id}
            </div>
            <div
              style={{
                position: 'relative',
                height: 18,
                background: 'var(--bg)',
                border: '1px solid var(--line-soft)',
                borderRadius: 2,
              }}
            >
              <div
                style={{
                  position: 'absolute',
                  left: `${(startOffset / 600) * 100}%`,
                  width: `${(w / 600) * 100}%`,
                  top: 1,
                  bottom: 1,
                  background:
                    s === 'success'
                      ? 'var(--ok)'
                      : s === 'running'
                      ? 'var(--info)'
                      : s === 'failed'
                      ? 'var(--err)'
                      : 'var(--line)',
                  opacity: s === 'pending' ? 0.3 : 0.7,
                  borderRadius: 2,
                  display: 'flex',
                  alignItems: 'center',
                  paddingLeft: 6,
                  fontFamily: 'var(--mono)',
                  fontSize: 10,
                  color: 'var(--bg)',
                  fontWeight: 600,
                }}
              >
                {st.timeout}s
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function WorkflowViz(props: VizProps) {
  const viz = useStore((s) => s.viz);
  if (viz === 'list') return <ListView {...props} />;
  if (viz === 'timeline') return <TimelineView {...props} />;
  return <DagView {...props} />;
}
