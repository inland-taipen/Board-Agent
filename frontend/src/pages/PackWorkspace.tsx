import { useCallback, useEffect, useRef, useState, type DragEvent, type FormEvent } from "react";

import {
  api,
  DOC_KINDS,
  type Board,
  type Pack,
  type Role,
  type UploadResult,
} from "../api";

const CLASSIFICATIONS = [
  { value: "confidential", label: "Confidential — board members only" },
  { value: "strictly_confidential", label: "Strictly confidential — not for circulation" },
  { value: "internal", label: "Internal" },
  { value: "public", label: "Public" },
];

// The pipeline runs for minutes on a real pack; poll often enough that the
// progress line feels live without hammering the API.
const POLL_MS = 2500;

interface Props {
  board: Board;
  role: Role;
  onOpenBriefing: (briefingId: string) => void;
}

export default function PackWorkspace({ board, role, onOpenBriefing }: Props) {
  const [packs, setPacks] = useState<Pack[]>([]);
  const [selected, setSelected] = useState<Pack | null>(null);
  const [error, setError] = useState("");
  const [upload, setUpload] = useState<UploadResult | null>(null);
  const [busy, setBusy] = useState(false);

  const canEdit = role !== "director";

  const loadPacks = useCallback(async () => {
    try {
      setPacks(await api.packs(board.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [board.id]);

  useEffect(() => {
    setSelected(null);
    setUpload(null);
    void loadPacks();
  }, [board.id, loadPacks]);

  // While a briefing is generating, refresh the selected pack so the operator
  // sees which stage the pipeline has reached.
  useEffect(() => {
    if (selected?.status !== "processing") return;
    const timer = setInterval(async () => {
      try {
        const fresh = await api.pack(selected.id);
        setSelected(fresh);
        if (fresh.status !== "processing") void loadPacks();
      } catch {
        /* a transient poll failure is not worth surfacing */
      }
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [selected?.status, selected?.id, loadPacks]);

  async function openPack(pack: Pack) {
    setUpload(null);
    setError("");
    try {
      setSelected(await api.pack(pack.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function createPack(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError("");
    try {
      const { id } = await api.createPack(board.id, {
        meeting_label: String(form.get("meeting_label")),
        meeting_date: String(form.get("meeting_date")),
        classification: String(form.get("classification")),
      });
      event.currentTarget.reset();
      await loadPacks();
      setSelected(await api.pack(id));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function addFiles(files: File[]) {
    if (!selected || files.length === 0) return;
    setBusy(true);
    setError("");
    try {
      const result = await api.uploadDocuments(selected.id, files);
      setUpload(result);
      setSelected(await api.pack(selected.id));
      await loadPacks();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function generate() {
    if (!selected) return;
    setBusy(true);
    setError("");
    try {
      await api.startBriefing(selected.id);
      setSelected({ ...selected, status: "processing", progress: "Queued", error: "" });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page">
      {error && <div className="banner error">{error}</div>}

      {!selected ? (
        <>
          <div className="card">
            <h2>{board.name} — meetings</h2>
            <p className="hint">
              One briefing is produced per meeting cycle. Open a meeting to upload its board
              pack or read the briefing.
            </p>

            {packs.length === 0 ? (
              <div className="empty">No meetings yet.</div>
            ) : (
              packs.map((pack) => (
                <button key={pack.id} className="list-item" onClick={() => void openPack(pack)}>
                  <div>
                    <div className="title">{pack.meeting_label}</div>
                    <div className="meta">
                      {pack.meeting_date} · {pack.document_count ?? 0} document
                      {pack.document_count === 1 ? "" : "s"}
                    </div>
                  </div>
                  <div className="spacer" />
                  <StatusBadge pack={pack} />
                </button>
              ))
            )}
          </div>

          {canEdit && (
            <form className="card" onSubmit={createPack}>
              <h2>New meeting</h2>
              <p className="hint">
                The classification you choose is stamped on every page of the exported briefing.
              </p>
              <div className="row">
                <div className="field">
                  <label htmlFor="meeting_label">Meeting</label>
                  <input
                    id="meeting_label"
                    name="meeting_label"
                    required
                    minLength={2}
                    placeholder="119th Board Meeting"
                  />
                </div>
                <div className="field">
                  <label htmlFor="meeting_date">Date</label>
                  <input
                    id="meeting_date"
                    name="meeting_date"
                    type="date"
                    defaultValue={new Date().toISOString().slice(0, 10)}
                  />
                </div>
                <div className="field">
                  <label htmlFor="classification">Classification</label>
                  <select id="classification" name="classification" defaultValue="confidential">
                    {CLASSIFICATIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </div>
                <button className="btn" type="submit" disabled={busy}>
                  Create
                </button>
              </div>
            </form>
          )}
        </>
      ) : (
        <PackDetail
          pack={selected}
          canEdit={canEdit}
          busy={busy}
          upload={upload}
          onBack={() => {
            setSelected(null);
            void loadPacks();
          }}
          onFiles={addFiles}
          onGenerate={generate}
          onOpenBriefing={onOpenBriefing}
          onRefresh={async () => setSelected(await api.pack(selected.id))}
        />
      )}
    </div>
  );
}

function StatusBadge({ pack }: { pack: Pack }) {
  if (pack.status === "ready") return <span className="badge completed">Briefing ready</span>;
  if (pack.status === "processing") return <span className="badge high">Generating</span>;
  if (pack.status === "failed") return <span className="badge critical">Failed</span>;
  return <span className="badge">Draft</span>;
}

interface DetailProps {
  pack: Pack;
  canEdit: boolean;
  busy: boolean;
  upload: UploadResult | null;
  onBack: () => void;
  onFiles: (files: File[]) => Promise<void>;
  onGenerate: () => Promise<void>;
  onOpenBriefing: (briefingId: string) => void;
  onRefresh: () => Promise<void>;
}

function PackDetail({
  pack,
  canEdit,
  busy,
  upload,
  onBack,
  onFiles,
  onGenerate,
  onOpenBriefing,
  onRefresh,
}: DetailProps) {
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const documents = pack.documents ?? [];
  const hasMinutes = documents.some((d) => d.doc_kind === "prior_minutes");
  const unreadable = documents.flatMap((d) =>
    d.ocr_pages.length ? [`${d.filename}: ${d.ocr_pages.length} page(s)`] : [],
  );

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    void onFiles(Array.from(event.dataTransfer.files));
  }

  return (
    <>
      <div className="card">
        <div className="row" style={{ alignItems: "center" }}>
          <div style={{ flex: 1 }}>
            <h2>{pack.meeting_label}</h2>
            <p className="hint" style={{ margin: "4px 0 0" }}>
              {pack.meeting_date} · {documents.length} document
              {documents.length === 1 ? "" : "s"}
            </p>
          </div>
          <button className="btn secondary small" onClick={onBack}>
            All meetings
          </button>
        </div>
      </div>

      {canEdit && (
        <div className="card">
          <h2>Board pack</h2>
          <p className="hint">
            Upload the prior minutes, board deck, financial pack, risk report and internal
            audit report. Document types are detected automatically — correct any that are
            wrong, because the type decides which specialist pass reads the file.
          </p>

          <div
            className={dragging ? "dropzone active" : "dropzone"}
            onDragOver={(event) => {
              event.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
          >
            <strong>Drop files here</strong> or{" "}
            <button className="btn secondary small" onClick={() => inputRef.current?.click()}>
              browse
            </button>
            <div className="formats">PDF, DOCX, PPTX, XLSX · up to 200 MB per file</div>
            <input
              ref={inputRef}
              type="file"
              multiple
              hidden
              accept=".pdf,.docx,.pptx,.xlsx,.xlsm"
              onChange={(event) => {
                void onFiles(Array.from(event.target.files ?? []));
                event.target.value = "";
              }}
            />
          </div>

          {busy && (
            <div className="progress" style={{ marginTop: 14 }}>
              <span className="spinner" /> Parsing and indexing...
            </div>
          )}

          {upload && upload.rejected.length > 0 && (
            <div className="banner warn" style={{ marginTop: 14 }}>
              {upload.rejected.map((r) => (
                <div key={r.filename}>
                  <strong>{r.filename}</strong> — {r.reason}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {documents.length > 0 && (
        <div className="card">
          <h2>Documents in this pack</h2>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>File</th>
                  <th>Type</th>
                  <th>Pages</th>
                  <th>Passages</th>
                  {canEdit && <th />}
                </tr>
              </thead>
              <tbody>
                {documents.map((doc) => (
                  <tr key={doc.id}>
                    <td>
                      {doc.filename}
                      {doc.ocr_pages.length > 0 && (
                        <div style={{ color: "var(--warn)", fontSize: 12.5 }}>
                          {doc.ocr_pages.length} page(s) have no extractable text
                        </div>
                      )}
                    </td>
                    <td>
                      {canEdit ? (
                        <select
                          value={doc.doc_kind}
                          onChange={async (event) => {
                            await api.reclassifyDocument(doc.id, event.target.value);
                            await onRefresh();
                          }}
                        >
                          {DOC_KINDS.map((kind) => (
                            <option key={kind.value} value={kind.value}>
                              {kind.label}
                            </option>
                          ))}
                        </select>
                      ) : (
                        DOC_KINDS.find((k) => k.value === doc.doc_kind)?.label ?? doc.doc_kind
                      )}
                    </td>
                    <td>{doc.pages}</td>
                    <td>{doc.chunk_count || "—"}</td>
                    {canEdit && (
                      <td>
                        <button
                          className="btn quiet small"
                          onClick={async () => {
                            await api.deleteDocument(doc.id);
                            await onRefresh();
                          }}
                        >
                          Remove
                        </button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="card">
        <h2>Briefing</h2>

        {!hasMinutes && documents.length > 0 && (
          <div className="banner warn">
            No prior minutes are in this pack. The briefing will still be produced, but
            unresolved actions can only come from the standing register — anything raised at
            the last meeting will be missing until its minutes are uploaded.
          </div>
        )}

        {unreadable.length > 0 && (
          <div className="banner warn">
            Some pages have no extractable text and will not be assessed ({unreadable.join("; ")}
            ). These are usually scans; re-export them as text PDFs if their content matters.
          </div>
        )}

        {pack.status === "processing" && (
          <div className="progress">
            <span className="spinner" />
            {pack.progress || "Working..."}
          </div>
        )}

        {pack.status === "failed" && (
          <div className="banner error">{pack.error || "The briefing run failed."}</div>
        )}

        {pack.status === "ready" && pack.briefing_id && (
          <div className="banner ok">Briefing ready for review.</div>
        )}

        <div className="row" style={{ marginTop: 12 }}>
          {pack.briefing_id && (
            <button className="btn" onClick={() => onOpenBriefing(pack.briefing_id!)}>
              Open briefing
            </button>
          )}
          {canEdit && (
            <button
              className={pack.briefing_id ? "btn secondary" : "btn"}
              disabled={busy || pack.status === "processing" || documents.length === 0}
              onClick={() => void onGenerate()}
            >
              {pack.briefing_id ? "Regenerate" : "Generate briefing"}
            </button>
          )}
        </div>
      </div>
    </>
  );
}
