import { useEffect, useState, type ReactNode } from "react";

import { api, STATUS_LABELS, type Briefing, type Verification } from "../api";
import SourceDrawer from "../components/SourceDrawer";

interface Props {
  briefingId: string;
  onBack: () => void;
}

export default function BriefingView({ briefingId, onBack }: Props) {
  const [briefing, setBriefing] = useState<Briefing | null>(null);
  const [error, setError] = useState("");
  const [openChunk, setOpenChunk] = useState<string | null>(null);
  const [downloading, setDownloading] = useState("");

  useEffect(() => {
    api
      .briefing(briefingId)
      .then(setBriefing)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, [briefingId]);

  if (error) return <div className="page banner error">{error}</div>;
  if (!briefing) {
    return (
      <div className="page progress">
        <span className="spinner" /> Loading briefing...
      </div>
    );
  }

  const { content, verification } = briefing;

  async function download(format: "pdf" | "docx") {
    if (!briefing) return;
    setDownloading(format);
    try {
      const slug = `${briefing.company} ${briefing.meeting_label} Board Briefing`
        .replace(/[^\w\s-]/g, "")
        .trim()
        .replace(/\s+/g, "-");
      await api.downloadExport(briefing.id, format, `${slug}.${format}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setDownloading("");
    }
  }

  const cite = (evidence: string[]) => (
    <Sources
      evidence={evidence}
      verification={verification}
      onOpen={(chunkId) => setOpenChunk(chunkId)}
    />
  );

  return (
    <div className="page wide">
      <div className="briefing-head">
        <div>
          <div className="classification">
            {briefing.classification.replace(/_/g, " ").toUpperCase()}
          </div>
          <h1>Board Briefing</h1>
          <div className="sub">
            {briefing.company} · {briefing.meeting_label} · {briefing.meeting_date}
          </div>
        </div>
        <div className="actions">
          <button className="btn secondary small" onClick={onBack}>
            Back
          </button>
          <button
            className="btn secondary small"
            disabled={downloading !== ""}
            onClick={() => void download("docx")}
          >
            {downloading === "docx" ? "Preparing..." : "DOCX"}
          </button>
          <button
            className="btn small"
            disabled={downloading !== ""}
            onClick={() => void download("pdf")}
          >
            {downloading === "pdf" ? "Preparing..." : "PDF"}
          </button>
        </div>
      </div>

      <VerificationBanner verification={verification} />

      {content.meeting_context && (
        <div className="card">
          <h2>Meeting context</h2>
          <p style={{ fontFamily: "var(--serif)", fontSize: 15, margin: "8px 0 0" }}>
            {content.meeting_context}
          </p>
        </div>
      )}

      <Section
        number={1}
        title="Critical risks for board attention"
        note="The three risks that most warrant board time at this meeting."
      >
        {content.critical_risks.map((risk, index) => (
          <Finding
            key={index}
            index={`1.${index + 1}`}
            title={risk.title}
            badge={risk.severity}
            rows={[
              ["Why now", risk.why_now],
              ["Exposure", risk.exposure],
              ["Management position", risk.management_position],
              ["What the pack does not say", risk.gap],
            ]}
            sources={cite(risk.evidence)}
          />
        ))}
      </Section>

      <Section
        number={2}
        title="Unresolved actions from previous meetings"
        note="Carried forward from prior minutes and reconciled against this pack."
      >
        {content.unresolved_actions.map((action, index) => (
          <Finding
            key={index}
            index={`2.${index + 1}`}
            title={action.action}
            badge={action.status}
            badgeLabel={STATUS_LABELS[action.status] ?? action.status}
            rows={[
              [
                "Status",
                `${STATUS_LABELS[action.status] ?? action.status}${
                  action.ageing_cycles
                    ? ` · open across ${action.ageing_cycles} meeting cycle${
                        action.ageing_cycles === 1 ? "" : "s"
                      }`
                    : ""
                }`,
              ],
              ["Owner", action.owner],
              ["Raised / committed", `${action.raised_at} / ${action.committed_date}`],
              ["Basis for status", action.status_basis],
            ]}
            sources={cite(action.evidence)}
          />
        ))}
      </Section>

      <Section
        number={3}
        title="Material performance changes"
        note="Movements material to this business, with the basis of comparison stated."
      >
        {content.performance_changes.map((change, index) => (
          <Finding
            key={index}
            index={`3.${index + 1}`}
            title={change.metric}
            badge={change.direction}
            rows={[
              ["Movement", change.movement],
              ["Why it matters", change.materiality],
              ["Explanation offered", change.explanation_given],
            ]}
            sources={cite(change.evidence)}
          />
        ))}
      </Section>

      <Section
        number={4}
        title="Questions the board should put to management"
        note="Specific enough that a prepared executive cannot deflect them."
      >
        {content.management_questions.map((question, index) => (
          <div className="finding" key={index}>
            <div className="finding-head">
              <span className="index">4.{index + 1}</span>
              <h3 style={{ fontFamily: "var(--sans)", fontSize: 13, color: "var(--accent)" }}>
                To {question.directed_to}
              </h3>
              <span className={`badge ${question.priority}`}>{question.priority}</span>
            </div>
            <p className="quote">“{question.question}”</p>
            <dl>
              <dt>Why ask it</dt>
              <dd>{question.rationale}</dd>
            </dl>
            {cite(question.evidence)}
          </div>
        ))}
      </Section>

      <Section
        number={5}
        title="Decisions required at this meeting"
        note="Including whether the pack equips the board to take them."
      >
        {content.decisions_required.length === 0 ? (
          <div className="empty">This pack puts no decisions to the board.</div>
        ) : (
          content.decisions_required.map((decision, index) => (
            <Finding
              key={index}
              index={`5.${index + 1}`}
              title={decision.decision}
              rows={[
                ["Proposed by", decision.proposed_by],
                ["Financial impact", decision.financial_impact],
                ["Basis for approval", decision.approval_basis],
                ["Is the board equipped to decide", decision.readiness],
                ["Governance considerations", decision.considerations],
              ]}
              sources={cite(decision.evidence)}
            />
          ))
        )}
      </Section>

      <div className="card">
        <h2>Coverage and limitations</h2>
        <p style={{ fontFamily: "var(--serif)", fontSize: 14.5, margin: "8px 0 0" }}>
          {content.coverage_note}
        </p>
        <p className="hint" style={{ marginTop: 14, marginBottom: 0 }}>
          Generated by {briefing.model} on {briefing.created_at.slice(0, 10)}. Review before
          circulating to directors.
        </p>
      </div>

      {openChunk && (
        <SourceDrawer
          packId={briefing.pack_id}
          chunkId={openChunk}
          onClose={() => setOpenChunk(null)}
        />
      )}
    </div>
  );
}

function VerificationBanner({ verification }: { verification: Verification }) {
  if (!verification || verification.total_items === 0) return null;

  if (verification.passed) {
    return (
      <div className="banner ok">
        All {verification.resolved_citations} citations resolved to source pages.
      </div>
    );
  }

  return (
    <div className="banner warn">
      <strong>
        {verification.issues.length} finding
        {verification.issues.length === 1 ? "" : "s"} could not be traced to a source page.
      </strong>{" "}
      They are retained below so you can judge them, and should be confirmed or removed before
      this briefing is circulated.
      <ul style={{ margin: "8px 0 0", paddingLeft: 18 }}>
        {verification.issues.map((issue, index) => (
          <li key={index}>
            {issue.section}: {issue.item_label} — {issue.detail}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Section({
  number,
  title,
  note,
  children,
}: {
  number: number;
  title: string;
  note: string;
  children: ReactNode;
}) {
  return (
    <section className="section">
      <header>
        <h2>
          {number}. {title}
        </h2>
        <p>{note}</p>
      </header>
      {children}
    </section>
  );
}

function Finding({
  index,
  title,
  badge,
  badgeLabel,
  rows,
  sources,
}: {
  index: string;
  title: string;
  badge?: string;
  badgeLabel?: string;
  rows: Array<[string, string]>;
  sources: ReactNode;
}) {
  return (
    <div className="finding">
      <div className="finding-head">
        <span className="index">{index}</span>
        <h3>{title}</h3>
        {badge && <span className={`badge ${badge}`}>{badgeLabel ?? badge}</span>}
      </div>
      <dl>
        {rows.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      {sources}
    </div>
  );
}

function Sources({
  evidence,
  verification,
  onOpen,
}: {
  evidence: string[];
  verification: Verification;
  onOpen: (chunkId: string) => void;
}) {
  if (!evidence || evidence.length === 0) {
    return (
      <div className="sources">
        <span className="label">Source</span>
        <span style={{ fontSize: 13, color: "var(--ink-faint)" }}>
          nothing in this pack addresses it
        </span>
      </div>
    );
  }

  return (
    <div className="sources">
      <span className="label">Source</span>
      {evidence.map((chunkId) => {
        const record = verification.citation_map?.[chunkId];
        if (!record) {
          return (
            <span key={chunkId} className="cite broken" title="This reference does not resolve">
              unverified {chunkId}
            </span>
          );
        }
        return (
          <button key={chunkId} className="cite" onClick={() => onOpen(chunkId)}>
            {record.document}, {record.locator}
          </button>
        );
      })}
    </div>
  );
}
