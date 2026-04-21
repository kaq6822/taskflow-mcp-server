import { useRef, useState } from 'react';

import { api } from '../api/client';
import { useT } from '../i18n/useT';
import { useStore } from '../store/store';

export function Artifacts() {
  const t = useT();
  const artifacts = useStore((s) => s.artifacts);
  const refreshArtifacts = useStore((s) => s.refreshArtifacts);
  const pushToast = useStore((s) => s.pushToast);

  const [selIdx, setSelIdx] = useState(0);
  const [filter, setFilter] = useState('');
  const [uploading, setUploading] = useState(false);
  const [formName, setFormName] = useState('');
  const [formVer, setFormVer] = useState('');
  const [formExt, setFormExt] = useState('tar.gz');
  const fileRef = useRef<HTMLInputElement | null>(null);

  const filtered = artifacts.filter(
    (a) => !filter || a.name.includes(filter) || a.version.includes(filter)
  );
  const sel = filtered[selIdx] || filtered[0];

  const handleUpload = async () => {
    const file = fileRef.current?.files?.[0];
    if (!file || !formName || !formVer) {
      pushToast(t.toast_upload_required, 'err');
      return;
    }
    try {
      await api.uploadArtifact(formName, formVer, formExt, file);
      pushToast(t.toast_upload_ok(formName, formVer));
      setFormName('');
      setFormVer('');
      if (fileRef.current) fileRef.current.value = '';
      await refreshArtifacts();
    } catch (e) {
      pushToast(t.toast_upload_fail(String(e)), 'err');
    }
  };

  return (
    <div>
      <div className="page-head">
        <h1>Artifacts</h1>
        <span className="sub">{t.artifacts_sub}</span>
        <div className="spacer" />
        <input
          className="input sm"
          style={{ width: 200 }}
          placeholder={t.search_artifact}
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
        <button className="btn primary sm" onClick={() => setUploading((v) => !v)}>
          {uploading ? t.close : t.upload_btn_toggle}
        </button>
      </div>

      {uploading && (
        <div
          style={{
            padding: '12px 18px',
            borderBottom: '1px solid var(--line)',
            display: 'grid',
            gridTemplateColumns: '1fr 1fr 120px 2fr auto',
            gap: 10,
            alignItems: 'end',
          }}
        >
          <div>
            <label className="mono-s dim">Name</label>
            <input className="input sm" value={formName} onChange={(e) => setFormName(e.target.value)} />
          </div>
          <div>
            <label className="mono-s dim">Version</label>
            <input className="input mono sm" value={formVer} onChange={(e) => setFormVer(e.target.value)} />
          </div>
          <div>
            <label className="mono-s dim">Ext</label>
            <input className="input mono sm" value={formExt} onChange={(e) => setFormExt(e.target.value)} />
          </div>
          <div>
            <label className="mono-s dim">File</label>
            <input type="file" ref={fileRef} />
          </div>
          <button className="btn primary" onClick={handleUpload}>
            {t.btn_upload}
          </button>
        </div>
      )}

      {artifacts.length === 0 ? (
        <div style={{ padding: '40px 18px', textAlign: 'center' }}>
          <div style={{ fontSize: 40, color: 'var(--ink-4)', marginBottom: 10 }}>▦</div>
          <div style={{ color: 'var(--ink-3)' }}>{t.no_artifacts}</div>
        </div>
      ) : (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: '1fr 380px',
            minHeight: 'calc(100vh - 56px)',
          }}
        >
          <div>
            <table className="tbl">
              <thead>
                <tr>
                  <th>Artifact</th>
                  <th>Version</th>
                  <th>Ext · Size</th>
                  <th>SHA-256</th>
                  <th>Uploader</th>
                  <th>Uploaded</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((a, i) => (
                  <tr
                    key={a.id}
                    className={selIdx === i ? 'selected' : ''}
                    onClick={() => setSelIdx(i)}
                  >
                    <td>
                      <div style={{ fontWeight: 600 }}>{a.name}</div>
                      {a.latest && (
                        <span className="chip accent" style={{ marginTop: 2, fontSize: 9 }}>
                          latest
                        </span>
                      )}
                    </td>
                    <td className="mono-s">{a.version}</td>
                    <td className="mono-s">
                      <span className="chip">{a.ext}</span> {(a.size_bytes / 1024).toFixed(1)} KB
                    </td>
                    <td className="mono-s dim">{a.sha256.slice(0, 8)}…{a.sha256.slice(-6)}</td>
                    <td className="mono-s">{a.uploader}</td>
                    <td className="mono-s dim">{a.uploaded_at.slice(0, 19).replace('T', ' ')}</td>
                    <td>
                      {a.status === 'READY' && (
                        <span className="chip ok">
                          <span className="d" />
                          READY
                        </span>
                      )}
                      {a.status === 'SCANNING' && (
                        <span className="chip warn live">
                          <span className="d" />
                          SCANNING
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {sel && (
            <aside
              style={{
                borderLeft: '1px solid var(--line)',
                background: 'var(--bg-2)',
                padding: 14,
                overflow: 'auto',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <div>
                  <div style={{ fontSize: 14, fontWeight: 700 }}>{sel.name}</div>
                  <div className="mono-s dim">
                    {sel.version} · {sel.ext} · {(sel.size_bytes / 1024).toFixed(1)} KB
                  </div>
                </div>
                <div className="spacer" />
                {sel.latest && <span className="chip accent">latest</span>}
              </div>
              <div className="ctitle" style={{ marginTop: 14 }}>{t.detail}</div>
              <div className="kv">
                <div className="k">sha-256</div>
                <div className="v" style={{ wordBreak: 'break-all' }}>
                  {sel.sha256}
                </div>
                <div className="k">reference</div>
                <div className="v">uploads://{sel.name}@{sel.version}</div>
                {sel.latest && (
                  <>
                    <div className="k">alias</div>
                    <div className="v">uploads://{sel.name}@latest</div>
                  </>
                )}
              </div>
              <div className="ctitle" style={{ marginTop: 14 }}>{t.verify}</div>
              <div className="col mono-s" style={{ gap: 3 }}>
                <div>
                  <span style={{ color: 'var(--ok)' }}>✓</span> {t.verify_sha256}
                </div>
                <div>
                  <span style={{ color: 'var(--ok)' }}>✓</span> {t.verify_readonly}
                </div>
                <div>
                  <span style={{ color: 'var(--ok)' }}>✓</span> {t.verify_scan}
                </div>
              </div>
            </aside>
          )}
        </div>
      )}
    </div>
  );
}
