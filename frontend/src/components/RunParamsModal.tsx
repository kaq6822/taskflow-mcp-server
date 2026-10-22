import { useEffect, useRef, useState } from 'react';

import { useT } from '../i18n/useT';
import { RunPrompt, useStore } from '../store/store';

/** Asks for a Job's declared params before the run is triggered. Mounted once
 *  in App so every ▷ Run button gets it through `startRun`. On a rejected
 *  value the backend's INVALID_PARAM toast appears and the dialog stays open
 *  for correction. */
export function RunParamsModal() {
  const prompt = useStore((s) => s.runPrompt);
  // Remount per prompt so its values never flash the previous prompt's.
  return prompt ? <RunParamsDialog key={`${prompt.jobId}:${JSON.stringify(prompt.initial)}`} prompt={prompt} /> : null;
}

function RunParamsDialog({ prompt }: { prompt: RunPrompt }) {
  const t = useT();
  const job = useStore((s) => s.jobs.find((j) => j.id === prompt.jobId));
  const startRun = useStore((s) => s.startRun);
  const closeRunPrompt = useStore((s) => s.closeRunPrompt);

  const [values, setValues] = useState<Record<string, string>>(prompt.initial);
  const [submitting, setSubmitting] = useState(false);
  // State updates land a render late; a ref also stops an Enter that repeats
  // before the button disables from triggering a second run.
  const inFlight = useRef(false);

  useEffect(() => {
    // The Job was deleted while the dialog was open — don't leave a prompt
    // that would pop up again if it ever came back.
    if (!job) closeRunPrompt();
  }, [job, closeRunPrompt]);

  if (!job) return null;

  // Empty means "not given": a param with a default then falls back to it on
  // the backend, and a required one is blocked here before the round-trip.
  const missing = job.params.filter((p) => p.default === null && !values[p.name]?.trim());

  const submit = async () => {
    if (inFlight.current || missing.length > 0) return;
    const given = Object.fromEntries(
      job.params.filter((p) => values[p.name]?.trim()).map((p) => [p.name, values[p.name]])
    );
    inFlight.current = true;
    setSubmitting(true);
    try {
      await startRun(job.id, given);
    } finally {
      inFlight.current = false;
      setSubmitting(false);
    }
  };

  return (
    <div className="modal-bg" onClick={closeRunPrompt}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3>{t.run_params_title(job.id)}</h3>
        <div className="col" style={{ gap: 10 }}>
          {job.params.map((p) => (
            <div key={p.name}>
              <label className="mono-s dim">
                {p.name}
                {p.default === null && <span className="req">*</span>}
                <span> · PARAM_{p.name.toUpperCase()}</span>
              </label>
              <input
                className="input mono"
                value={values[p.name] ?? ''}
                placeholder={p.default ?? t.run_params_required_ph}
                onChange={(e) => setValues({ ...values, [p.name]: e.target.value })}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') submit();
                }}
              />
              {p.pattern && <div className="mono-s dim">pattern: {p.pattern}</div>}
            </div>
          ))}
        </div>
        <div className="row" style={{ marginTop: 16 }}>
          <button className="btn ghost" onClick={closeRunPrompt}>
            {t.cancel}
          </button>
          <div className="spacer" />
          <button
            className="btn primary"
            onClick={submit}
            disabled={submitting || missing.length > 0}
          >
            {t.btn_run}
          </button>
        </div>
      </div>
    </div>
  );
}
