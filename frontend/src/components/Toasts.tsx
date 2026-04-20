import { useStore } from '../store/store';

export function Toasts() {
  const toasts = useStore((s) => s.toasts);
  return (
    <div className="toasts">
      {toasts.map((t) => (
        <div key={t.id} className={`toast ${t.kind}`}>
          <span
            style={{
              color:
                t.kind === 'err'
                  ? 'var(--err)'
                  : t.kind === 'ok'
                  ? 'var(--ok)'
                  : 'var(--accent)',
            }}
          >
            ●
          </span>
          <span>{t.msg}</span>
        </div>
      ))}
    </div>
  );
}
