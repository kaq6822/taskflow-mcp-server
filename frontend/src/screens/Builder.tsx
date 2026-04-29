import { useEffect, useMemo, useState } from 'react';

import { ApiError, Step, api } from '../api/client';
import { DagView } from '../components/dag/WorkflowViz';
import { useT } from '../i18n/useT';
import { useStore } from '../store/store';
import { YamlRender } from './JobDetail';

type View = 'canvas' | 'yaml' | 'form';

type Draft = {
  id: string;
  name: string;
  description: string;
  owner: string;
  tags: string[];
  schedule: string;
  timeout: number;
  concurrency: number;
  on_failure: 'STOP' | 'CONTINUE' | 'RETRY' | 'ROLLBACK';
  consumes_artifact: string | null;
  steps: Step[];
};

const EMPTY: Draft = {
  id: '',
  name: '',
  description: '',
  owner: 'admin',
  tags: [],
  schedule: 'manual',
  timeout: 600,
  concurrency: 1,
  on_failure: 'STOP',
  consumes_artifact: null,
  steps: [
    { id: 'greet', cmd: ['echo', 'hello from taskflow'], timeout: 10, on_failure: 'STOP', deps: [] },
  ],
};

export function Builder() {
  const t = useT();
  const selectedJobId = useStore((s) => s.selectedJobId);
  const jobs = useStore((s) => s.jobs);
  const setSelectedJobId = useStore((s) => s.setSelectedJobId);
  const refreshJobs = useStore((s) => s.refreshJobs);
  const setScreen = useStore((s) => s.setScreen);
  const pushToast = useStore((s) => s.pushToast);

  const existing = selectedJobId ? jobs.find((j) => j.id === selectedJobId) : null;

  const [draft, setDraft] = useState<Draft>(
    existing
      ? {
          id: existing.id,
          name: existing.name,
          description: existing.description,
          owner: existing.owner,
          tags: existing.tags,
          schedule: existing.schedule,
          timeout: existing.timeout,
          concurrency: existing.concurrency,
          on_failure: existing.on_failure as Draft['on_failure'],
          consumes_artifact: existing.consumes_artifact,
          steps: existing.steps,
        }
      : EMPTY
  );
  const [view, setView] = useState<View>('canvas');
  const [selStep, setSelStep] = useState<string | null>(draft.steps[0]?.id ?? null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (existing) {
      setDraft({
        id: existing.id,
        name: existing.name,
        description: existing.description,
        owner: existing.owner,
        tags: existing.tags,
        schedule: existing.schedule,
        timeout: existing.timeout,
        concurrency: existing.concurrency,
        on_failure: existing.on_failure as Draft['on_failure'],
        consumes_artifact: existing.consumes_artifact,
        steps: existing.steps,
      });
    } else {
      setDraft(EMPTY);
    }
    setDirty(false);
  }, [selectedJobId]);

  const step = draft.steps.find((s) => s.id === selStep) || draft.steps[0];

  const validation = useMemo(() => validateDraft(draft, t, !!existing), [draft, t, existing]);

  const save = async () => {
    if (!validation.ok) {
      pushToast(t.toast_validation_fail(validation.errors[0]), 'err');
      return;
    }
    setSaving(true);
    try {
      if (existing) {
        await api.updateJob(existing.id, draft);
        pushToast(t.toast_save_ok);
      } else {
        const created = await api.createJob(draft);
        setSelectedJobId(created.id);
        pushToast(t.toast_job_created);
      }
      await refreshJobs();
      setDirty(false);
    } catch (e) {
      if (e instanceof ApiError) {
        pushToast(t.toast_save_fail(JSON.stringify(e.detail)), 'err');
      } else {
        pushToast(t.toast_save_fail(String(e)), 'err');
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <div className="page-head">
        <h1>{draft.id || t.new_job_title}</h1>
        <span className="sub">Workflow editor</span>
        {dirty && <span className="chip warn">unsaved</span>}
        <div
          className="tabs"
          style={{ marginLeft: 16, marginBottom: -15, borderBottom: 'none', background: 'transparent' }}
        >
          {(['canvas', 'yaml', 'form'] as const).map((k) => (
            <div key={k} className={`tab ${view === k ? 'active' : ''}`} onClick={() => setView(k)}>
              {k}
            </div>
          ))}
        </div>
        <div className="spacer" />
        <button className="btn ghost sm" onClick={() => setScreen(existing ? 'detail' : 'dashboard')}>
          {t.btn_back}
        </button>
        <button className="btn primary sm" onClick={save} disabled={saving}>
          {saving ? t.saving : t.save}
        </button>
      </div>

      {view === 'canvas' && (
        <CanvasView
          draft={draft}
          setDraft={(u) => {
            setDraft(u);
            setDirty(true);
          }}
          step={step}
          selStep={selStep}
          setSelStep={setSelStep}
          isExisting={!!existing}
        />
      )}
      {view === 'yaml' && (
        <YamlView
          draft={draft}
          validation={validation}
        />
      )}
      {view === 'form' && (
        <FormView
          draft={draft}
          setDraft={(u) => {
            setDraft(u);
            setDirty(true);
          }}
          step={step}
          selStep={selStep}
          setSelStep={setSelStep}
          isExisting={!!existing}
        />
      )}
    </div>
  );
}

type ValidationResult = { ok: boolean; errors: string[] };
function validateDraft(
  d: Draft,
  t: ReturnType<typeof useT>,
  isExisting: boolean
): ValidationResult {
  const errs: string[] = [];
  const stateCommands = new Set(['cd', 'pushd', 'popd']);
  if (!isExisting && !/^[a-z][a-z0-9-]{1,}$/.test(d.id)) errs.push(t.err_id_format);
  if (!d.name) errs.push(t.err_name_required);
  const ids = new Set<string>();
  for (const s of d.steps) {
    if (!s.id) errs.push(t.err_step_id_required);
    else if (ids.has(s.id)) errs.push(t.err_step_id_dup(s.id));
    ids.add(s.id);
    if (!Array.isArray(s.cmd) || s.cmd.length === 0 || s.cmd.some((c) => typeof c !== 'string'))
      errs.push(`${s.id}: cmd must be argv array`);
    const head = typeof s.cmd[0] === 'string' ? s.cmd[0].split('/').filter(Boolean).at(-1) : undefined;
    if (head && stateCommands.has(head)) errs.push(t.err_state_command(head));
    if (s.cwd !== undefined && s.cwd !== null && !s.cwd.trim()) errs.push(`${s.id}: cwd must be non-empty`);
    for (const field of ['success_contains', 'failure_contains'] as const) {
      const patterns = s[field] || [];
      if (!Array.isArray(patterns) || patterns.some((p) => typeof p !== 'string' || !p)) {
        errs.push(`${s.id}: ${field} must be non-empty strings`);
      }
    }
  }
  for (const s of d.steps) {
    for (const dep of s.deps || []) {
      if (dep === s.id) {
        errs.push(t.err_dep_self_ref(s.id));
      } else if (!ids.has(dep)) {
        errs.push(t.err_dep_unknown(s.id, dep));
      }
    }
  }

  // Cycle detection — mirrors backend/app/engine/dag.py DFS coloring so the
  // validation panel flags cycles before the save round-trip.
  const byId: Record<string, Step> = Object.fromEntries(d.steps.map((s) => [s.id, s]));
  const WHITE = 0;
  const GRAY = 1;
  const BLACK = 2;
  const color: Record<string, number> = {};
  for (const s of d.steps) color[s.id] = WHITE;
  let cycleReported = false;
  const visit = (sid: string, stack: string[]): boolean => {
    if (cycleReported) return true;
    if (color[sid] === GRAY) {
      const start = stack.indexOf(sid);
      const path = [...stack.slice(start), sid].join(' → ');
      errs.push(t.err_dep_cycle(path));
      cycleReported = true;
      return true;
    }
    if (color[sid] === BLACK) return false;
    color[sid] = GRAY;
    stack.push(sid);
    for (const dep of byId[sid]?.deps || []) {
      if (!byId[dep] || dep === sid) continue;
      if (visit(dep, stack)) return true;
    }
    stack.pop();
    color[sid] = BLACK;
    return false;
  };
  for (const s of d.steps) {
    if (color[s.id] === WHITE && visit(s.id, [])) break;
  }

  return { ok: errs.length === 0, errors: errs };
}

function CanvasView({
  draft,
  setDraft,
  step,
  selStep,
  setSelStep,
  isExisting,
}: {
  draft: Draft;
  setDraft: (d: Draft) => void;
  step: Step;
  selStep: string | null;
  setSelStep: (id: string) => void;
  isExisting: boolean;
}) {
  const t = useT();
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '180px 1fr 320px',
        minHeight: 'calc(100vh - 96px)',
      }}
    >
      <div style={{ borderRight: '1px solid var(--line)', padding: 10, background: 'var(--bg-2)' }}>
        <div className="ctitle">{t.palette}</div>
        <button
          className="btn sm ghost"
          style={{ width: '100%', marginBottom: 4 }}
          onClick={() => {
            const newId = `step_${draft.steps.length + 1}`;
            setDraft({
              ...draft,
              steps: [
                ...draft.steps,
                { id: newId, cmd: ['echo', newId], timeout: 10, on_failure: 'STOP', deps: [] },
              ],
            });
            setSelStep(newId);
          }}
        >
          {t.add_step}
        </button>
      </div>
      <div style={{ padding: 14 }}>
        <DagView
          job={draft}
          selectedStep={selStep}
          onStepClick={(id) => setSelStep(id)}
        />
        <div className="mono-s dim" style={{ marginTop: 8 }}>
          {t.canvas_cmd_hint}
        </div>
      </div>
      <div
        style={{
          borderLeft: '1px solid var(--line)',
          padding: 12,
          background: 'var(--bg-2)',
          overflow: 'auto',
        }}
      >
        <Inspector draft={draft} setDraft={setDraft} step={step} setSelStep={setSelStep} />
        <div className="hr" />
        <MetaEditor draft={draft} setDraft={setDraft} isExisting={isExisting} />
      </div>
    </div>
  );
}

function Inspector({
  draft,
  setDraft,
  step,
  setSelStep,
}: {
  draft: Draft;
  setDraft: (d: Draft) => void;
  step: Step;
  setSelStep: (id: string) => void;
}) {
  const t = useT();
  const patch = (u: Partial<Step>) => {
    setDraft({ ...draft, steps: draft.steps.map((s) => (s.id === step.id ? { ...s, ...u } : s)) });
  };
  const deleteStep = () => {
    setDraft({
      ...draft,
      steps: draft.steps
        .filter((s) => s.id !== step.id)
        .map((s) => ({ ...s, deps: (s.deps || []).filter((d) => d !== step.id) })),
    });
  };
  const [cmdText, setCmdText] = useState(JSON.stringify(step.cmd));
  useEffect(() => setCmdText(JSON.stringify(step.cmd)), [step.id, step.cmd.join('\u0001')]);
  const listText = (items: string[] | undefined) => (items || []).join('\n');
  const parseList = (value: string) =>
    value
      .split('\n')
      .map((s) => s.trim())
      .filter(Boolean);

  return (
    <div>
      <div className="ctitle">Inspector · {step.id}</div>
      <div className="col" style={{ gap: 8 }}>
        <div>
          <label className="mono-s dim">
            ID <span className="req" aria-label="required">*</span>
          </label>
          <input
            className="input mono sm"
            value={step.id}
            onChange={(e) => {
              const newId = e.target.value;
              setDraft({
                ...draft,
                steps: draft.steps.map((s) =>
                  s.id === step.id ? { ...s, id: newId } : {
                    ...s,
                    deps: (s.deps || []).map((d) => (d === step.id ? newId : d)),
                  }
                ),
              });
              setSelStep(newId);
            }}
          />
        </div>
        <div>
          <label className="mono-s dim">
            Command (argv — shell=False) <span className="req" aria-label="required">*</span>
          </label>
          <input
            className="input mono sm"
            value={cmdText}
            onChange={(e) => setCmdText(e.target.value)}
            onBlur={() => {
              try {
                const parsed = JSON.parse(cmdText);
                if (Array.isArray(parsed)) patch({ cmd: parsed });
              } catch {
                setCmdText(JSON.stringify(step.cmd));
              }
            }}
          />
        </div>
        <div className="split s2" style={{ gap: 8 }}>
          <div>
            <label className="mono-s dim">Timeout (s)</label>
            <input
              className="input mono sm"
              type="number"
              value={step.timeout}
              onChange={(e) => patch({ timeout: Number(e.target.value) })}
            />
          </div>
          <div>
            <label className="mono-s dim">On failure</label>
            <select
              className="select"
              style={{ fontSize: 11 }}
              value={step.on_failure}
              onChange={(e) => patch({ on_failure: e.target.value as Step['on_failure'] })}
            >
              <option>STOP</option>
              <option>CONTINUE</option>
              <option>RETRY</option>
              <option>ROLLBACK</option>
            </select>
          </div>
        </div>
        <div>
          <label className="mono-s dim">Working directory (cwd)</label>
          <input
            className="input mono sm"
            value={step.cwd || ''}
            placeholder="default: TASKFLOW_STEP_CWD"
            onChange={(e) => patch({ cwd: e.target.value || null })}
          />
        </div>
        <div>
          <label className="mono-s dim">Success output contains (one per line)</label>
          <textarea
            className="input mono sm"
            style={{ minHeight: 54, resize: 'vertical' }}
            value={listText(step.success_contains)}
            placeholder="Deploy complete"
            onChange={(e) => patch({ success_contains: parseList(e.target.value) })}
          />
        </div>
        <div>
          <label className="mono-s dim">Failure output contains (one per line)</label>
          <textarea
            className="input mono sm"
            style={{ minHeight: 54, resize: 'vertical' }}
            value={listText(step.failure_contains)}
            placeholder="ERROR"
            onChange={(e) => patch({ failure_contains: parseList(e.target.value) })}
          />
        </div>
        <div>
          <label className="mono-s dim">Depends on (comma-separated step ids)</label>
          <input
            className="input mono sm"
            value={(step.deps || []).join(',')}
            onChange={(e) =>
              patch({
                deps: e.target.value
                  .split(',')
                  .map((s) => s.trim())
                  .filter(Boolean),
              })
            }
          />
        </div>
      </div>
      <div className="row" style={{ marginTop: 8 }}>
        <button className="btn sm danger" style={{ marginLeft: 'auto' }} onClick={deleteStep}>
          {t.delete_step}
        </button>
      </div>
    </div>
  );
}

function MetaEditor({
  draft,
  setDraft,
  isExisting,
}: {
  draft: Draft;
  setDraft: (d: Draft) => void;
  isExisting: boolean;
}) {
  const t = useT();
  return (
    <div>
      <div className="ctitle">{t.job_meta}</div>
      <div className="col" style={{ gap: 8 }}>
        <div>
          <label className="mono-s dim">
            ID (kebab-case) <span className="req" aria-label="required">*</span>
          </label>
          <input
            className="input mono sm"
            value={draft.id}
            onChange={(e) => setDraft({ ...draft, id: e.target.value })}
            disabled={isExisting}
            title={isExisting ? t.job_id_locked_hint : undefined}
          />
          {isExisting && (
            <div className="mono-s dim" style={{ marginTop: 4 }}>
              {t.job_id_locked_hint}
            </div>
          )}
        </div>
        <div>
          <label className="mono-s dim">
            Name <span className="req" aria-label="required">*</span>
          </label>
          <input
            className="input sm"
            value={draft.name}
            onChange={(e) => setDraft({ ...draft, name: e.target.value })}
          />
        </div>
        <div>
          <label className="mono-s dim">Owner</label>
          <input
            className="input sm"
            value={draft.owner}
            onChange={(e) => setDraft({ ...draft, owner: e.target.value })}
          />
        </div>
        <div>
          <label className="mono-s dim">Schedule</label>
          <input
            className="input mono sm"
            value={draft.schedule}
            onChange={(e) => setDraft({ ...draft, schedule: e.target.value })}
          />
        </div>
        <div className="split s2" style={{ gap: 8 }}>
          <div>
            <label className="mono-s dim">Timeout (s)</label>
            <input
              className="input mono sm"
              type="number"
              value={draft.timeout}
              onChange={(e) => setDraft({ ...draft, timeout: Number(e.target.value) })}
            />
          </div>
          <div>
            <label className="mono-s dim">Concurrency</label>
            <input
              className="input mono sm"
              type="number"
              value={draft.concurrency}
              onChange={(e) => setDraft({ ...draft, concurrency: Number(e.target.value) })}
              disabled
              title={t.job_concurrency_locked_hint}
            />
          </div>
        </div>
        <div className="mono-s dim" style={{ marginTop: -4 }}>
          {t.job_concurrency_locked_hint}
        </div>
        <div>
          <label className="mono-s dim">On failure</label>
          <select
            className="select"
            style={{ fontSize: 11 }}
            value={draft.on_failure}
            onChange={(e) => setDraft({ ...draft, on_failure: e.target.value as Draft['on_failure'] })}
          >
            <option>STOP</option>
            <option>CONTINUE</option>
            <option>RETRY</option>
            <option>ROLLBACK</option>
          </select>
        </div>
        <div>
          <label className="mono-s dim">Tags (comma)</label>
          <input
            className="input mono sm"
            value={draft.tags.join(',')}
            onChange={(e) =>
              setDraft({ ...draft, tags: e.target.value.split(',').map((tg) => tg.trim()).filter(Boolean) })
            }
          />
        </div>
        <div>
          <label className="mono-s dim">Consumes artifact (name, optional)</label>
          <input
            className="input mono sm"
            value={draft.consumes_artifact || ''}
            onChange={(e) => setDraft({ ...draft, consumes_artifact: e.target.value || null })}
          />
        </div>
      </div>
    </div>
  );
}

function YamlView({
  draft,
  validation,
}: {
  draft: Draft;
  validation: ValidationResult;
}) {
  const t = useT();
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '1fr 320px',
        minHeight: 'calc(100vh - 96px)',
      }}
    >
      <div style={{ padding: 14 }}>
        <div
          className="row"
          style={{ alignItems: 'center', gap: 8, marginBottom: 8 }}
        >
          <span className="chip">{t.yaml_readonly_badge}</span>
          <span className="mono-s dim">{t.yaml_readonly_hint}</span>
        </div>
        <div className="console" style={{ minHeight: 400 }}>
          <YamlRender job={draft as any} />
        </div>
      </div>
      <div style={{ borderLeft: '1px solid var(--line)', padding: 12, background: 'var(--bg-2)' }}>
        <div className="ctitle">{t.validation_panel}</div>
        {validation.ok ? (
          <div className="col mono-s" style={{ gap: 5 }}>
            <div>
              <span style={{ color: 'var(--ok)' }}>✓</span> {t.validation_unique_ids}
            </div>
            <div>
              <span style={{ color: 'var(--ok)' }}>✓</span> {t.validation_deps_valid}
            </div>
            <div>
              <span style={{ color: 'var(--ok)' }}>✓</span> {t.validation_argv}
            </div>
          </div>
        ) : (
          <div className="col mono-s" style={{ gap: 3, color: 'var(--err)' }}>
            {validation.errors.map((e, i) => (
              <div key={i}>
                <span>✗</span> {e}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function FormView({
  draft,
  setDraft,
  step,
  selStep,
  setSelStep,
  isExisting,
}: {
  draft: Draft;
  setDraft: (d: Draft) => void;
  step: Step;
  selStep: string | null;
  setSelStep: (id: string) => void;
  isExisting: boolean;
}) {
  const t = useT();
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '220px 1fr',
        minHeight: 'calc(100vh - 96px)',
      }}
    >
      <div style={{ borderRight: '1px solid var(--line)', padding: 10, background: 'var(--bg-2)' }}>
        <div className="ctitle">Steps</div>
        {draft.steps.map((st, i) => (
          <div
            key={st.id}
            onClick={() => setSelStep(st.id)}
            style={{
              padding: '6px 8px',
              borderRadius: 4,
              cursor: 'pointer',
              background: selStep === st.id ? 'var(--accent-soft)' : 'transparent',
              marginBottom: 2,
            }}
          >
            <div className="mono-s dim">{String(i + 1).padStart(2, '0')}</div>
            <div className="mono" style={{ fontSize: 11, fontWeight: 600 }}>
              {st.id}
            </div>
          </div>
        ))}
        <button
          className="btn sm ghost"
          style={{ marginTop: 8, width: '100%' }}
          onClick={() => {
            const newId = `step_${draft.steps.length + 1}`;
            setDraft({
              ...draft,
              steps: [
                ...draft.steps,
                { id: newId, cmd: ['echo', newId], timeout: 10, on_failure: 'STOP', deps: [] },
              ],
            });
            setSelStep(newId);
          }}
        >
          {t.add_step}
        </button>
      </div>
      <div style={{ padding: 18, maxWidth: 680 }}>
        <h2 style={{ margin: '0 0 16px', fontSize: 15, fontWeight: 600 }}>
          Step · <span className="mono">{step.id}</span>
        </h2>
        <Inspector draft={draft} setDraft={setDraft} step={step} setSelStep={setSelStep} />
        <div className="hr" />
        <MetaEditor draft={draft} setDraft={setDraft} isExisting={isExisting} />
      </div>
    </div>
  );
}
