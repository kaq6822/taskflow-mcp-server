import { useEffect, useState } from 'react';

import { useStore } from '../store/store';

export function TweaksPanel() {
  const viz = useStore((s) => s.viz);
  const density = useStore((s) => s.density);
  const setViz = useStore((s) => s.setViz);
  const setDensity = useStore((s) => s.setDensity);
  const liveRun = useStore((s) => s.liveRun);
  const selectedJobId = useStore((s) => s.selectedJobId);
  const startRun = useStore((s) => s.startRun);
  const cancelRun = useStore((s) => s.cancelRun);

  const [open, setOpen] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === '.') {
        e.preventDefault();
        setOpen((v) => !v);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  return (
    <>
      <button
        className="btn sm ghost"
        onClick={() => setOpen((v) => !v)}
        style={{ position: 'fixed', bottom: 16, right: 16, zIndex: 8999 }}
      >
        ⚙ tweaks
      </button>
      <div className={`tweaks ${open ? 'open' : ''}`} style={{ bottom: 56 }}>
        <h4>Tweaks</h4>
        <div className="sub">Prototype controls</div>

        <div className="row">
          <label>Workflow 시각화</label>
        </div>
        <div className="seg">
          {(['dag', 'list', 'timeline'] as const).map((k) => (
            <button key={k} className={viz === k ? 'active' : ''} onClick={() => setViz(k)}>
              {k.toUpperCase()}
            </button>
          ))}
        </div>

        <div className="row">
          <label>정보 밀도</label>
        </div>
        <div className="seg">
          {(['compact', 'spacious'] as const).map((k) => (
            <button key={k} className={density === k ? 'active' : ''} onClick={() => setDensity(k)}>
              {k}
            </button>
          ))}
        </div>

        <div className="row">
          <label>Run 시뮬레이터</label>
        </div>
        <div className="seg">
          <button onClick={() => selectedJobId && startRun(selectedJobId)} disabled={!!liveRun || !selectedJobId}>
            ▷ Start
          </button>
          <button onClick={cancelRun} disabled={!liveRun}>
            ■ Stop
          </button>
        </div>
        <div style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--ink-3)', marginTop: 10 }}>
          Tweaks 변경은 저장됩니다. (⌘.)
        </div>
      </div>
    </>
  );
}
