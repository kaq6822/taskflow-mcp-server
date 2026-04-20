import { useEffect, useMemo, useState } from 'react';

import { ApiError, Step, api } from '../api/client';
import { DagView } from '../components/dag/WorkflowViz';
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

  const validation = useMemo(() => validateDraft(draft), [draft]);

  const save = async () => {
    if (!validation.ok) {
      pushToast(`검증 실패: ${validation.errors[0]}`, 'err');
      return;
    }
    setSaving(true);
    try {
      if (existing) {
        await api.updateJob(existing.id, draft);
        pushToast('저장되었습니다');
      } else {
        const created = await api.createJob(draft);
        setSelectedJobId(created.id);
        pushToast('Job이 생성되었습니다');
      }
      await refreshJobs();
      setDirty(false);
    } catch (e) {
      if (e instanceof ApiError) {
        pushToast(`저장 실패: ${JSON.stringify(e.detail)}`, 'err');
      } else {
        pushToast(`저장 실패: ${String(e)}`, 'err');
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <div className="page-head">
        <h1>{draft.id || '(신규 Job)'}</h1>
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
          ← 돌아가기
        </button>
        <button className="btn primary sm" onClick={save} disabled={saving}>
          {saving ? '저장 중…' : '저장'}
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
        />
      )}
    </div>
  );
}

type ValidationResult = { ok: boolean; errors: string[] };
function validateDraft(d: Draft): ValidationResult {
  const errs: string[] = [];
  if (!/^[a-z][a-z0-9-]{1,}$/.test(d.id)) errs.push('id는 kebab-case 소문자');
  if (!d.name) errs.push('name 필요');
  const ids = new Set<string>();
  for (const s of d.steps) {
    if (!s.id) errs.push('step.id 필요');
    else if (ids.has(s.id)) errs.push(`중복 step id: ${s.id}`);
    ids.add(s.id);
    if (!Array.isArray(s.cmd) || s.cmd.length === 0 || s.cmd.some((c) => typeof c !== 'string'))
      errs.push(`${s.id}: cmd must be argv array`);
  }
  for (const s of d.steps) {
    for (const dep of s.deps || []) {
      if (!ids.has(dep)) errs.push(`${s.id}: unknown dep ${dep}`);
    }
  }
  return { ok: errs.length === 0, errors: errs };
}

function CanvasView({
  draft,
  setDraft,
  step,
  selStep,
  setSelStep,
}: {
  draft: Draft;
  setDraft: (d: Draft) => void;
  step: Step;
  selStep: string | null;
  setSelStep: (id: string) => void;
}) {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '180px 1fr 320px',
        minHeight: 'calc(100vh - 96px)',
      }}
    >
      <div style={{ borderRight: '1px solid var(--line)', padding: 10, background: 'var(--bg-2)' }}>
        <div className="ctitle">팔레트</div>
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
          + Step 추가
        </button>
        <div className="mono-s dim" style={{ marginTop: 10 }}>
          Step 클릭으로 편집 →
        </div>
      </div>
      <div style={{ padding: 14 }}>
        <DagView
          job={draft}
          selectedStep={selStep}
          onStepClick={(id) => setSelStep(id)}
        />
        <div className="mono-s dim" style={{ marginTop: 8 }}>
          Step을 클릭해 우측 Inspector에서 편집. argv는 <b>shell=False</b> — 리스트만 허용.
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
        <Inspector draft={draft} setDraft={setDraft} step={step} />
        <div className="hr" />
        <MetaEditor draft={draft} setDraft={setDraft} />
      </div>
    </div>
  );
}

function Inspector({
  draft,
  setDraft,
  step,
}: {
  draft: Draft;
  setDraft: (d: Draft) => void;
  step: Step;
}) {
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

  return (
    <div>
      <div className="ctitle">Inspector · {step.id}</div>
      <div className="col" style={{ gap: 8 }}>
        <div>
          <label className="mono-s dim">ID</label>
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
            }}
          />
        </div>
        <div>
          <label className="mono-s dim">Command (argv — shell=False)</label>
          <input
            className="input mono sm"
            value={cmdText}
            onChange={(e) => setCmdText(e.target.value)}
            onBlur={() => {
              try {
                const parsed = JSON.parse(cmdText);
                if (Array.isArray(parsed)) patch({ cmd: parsed });
              } catch {
                /* invalid JSON — revert */
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
          이 Step 삭제
        </button>
      </div>
    </div>
  );
}

function MetaEditor({ draft, setDraft }: { draft: Draft; setDraft: (d: Draft) => void }) {
  return (
    <div>
      <div className="ctitle">Job 메타</div>
      <div className="col" style={{ gap: 8 }}>
        <div>
          <label className="mono-s dim">ID (kebab-case)</label>
          <input
            className="input mono sm"
            value={draft.id}
            onChange={(e) => setDraft({ ...draft, id: e.target.value })}
          />
        </div>
        <div>
          <label className="mono-s dim">Name</label>
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
            />
          </div>
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
              setDraft({ ...draft, tags: e.target.value.split(',').map((t) => t.trim()).filter(Boolean) })
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
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '1fr 320px',
        minHeight: 'calc(100vh - 96px)',
      }}
    >
      <div style={{ padding: 14 }}>
        <div className="console" style={{ minHeight: 400 }}>
          <YamlRender job={draft as any} />
        </div>
      </div>
      <div style={{ borderLeft: '1px solid var(--line)', padding: 12, background: 'var(--bg-2)' }}>
        <div className="ctitle">검증</div>
        {validation.ok ? (
          <div className="col mono-s" style={{ gap: 5 }}>
            <div>
              <span style={{ color: 'var(--ok)' }}>✓</span> 모든 step id 고유
            </div>
            <div>
              <span style={{ color: 'var(--ok)' }}>✓</span> 의존성 참조 유효
            </div>
            <div>
              <span style={{ color: 'var(--ok)' }}>✓</span> argv 배열 (shell=False)
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
}: {
  draft: Draft;
  setDraft: (d: Draft) => void;
  step: Step;
  selStep: string | null;
  setSelStep: (id: string) => void;
}) {
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
          + Step 추가
        </button>
      </div>
      <div style={{ padding: 18, maxWidth: 680 }}>
        <h2 style={{ margin: '0 0 16px', fontSize: 15, fontWeight: 600 }}>
          Step · <span className="mono">{step.id}</span>
        </h2>
        <Inspector draft={draft} setDraft={setDraft} step={step} />
        <div className="hr" />
        <MetaEditor draft={draft} setDraft={setDraft} />
      </div>
    </div>
  );
}
