import { useCallback, useEffect, useState } from "react";

import { api, STATUS_LABELS, type ActionItem, type Board } from "../api";

const STATUS_ORDER = ["unclear", "open", "in_progress", "completed", "superseded"];

/**
 * The standing register.
 *
 * The briefing carries the five actions that need airtime; this is the
 * complete list, and it is what makes "no item lost between meetings"
 * verifiable rather than aspirational. Items sit here across meeting cycles
 * until something in a pack demonstrates they were discharged.
 */
export default function ActionRegister({ board, canEdit }: { board: Board; canEdit: boolean }) {
  const [actions, setActions] = useState<ActionItem[]>([]);
  const [error, setError] = useState("");
  const [showClosed, setShowClosed] = useState(false);

  const load = useCallback(async () => {
    try {
      setActions(await api.actions(board.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [board.id]);

  useEffect(() => {
    void load();
  }, [load]);

  const closedStatuses = new Set(["completed", "superseded"]);
  const visible = showClosed ? actions : actions.filter((a) => !closedStatuses.has(a.status));

  const counts = STATUS_ORDER.map((status) => ({
    status,
    count: actions.filter((a) => a.status === status).length,
  })).filter((entry) => entry.count > 0);

  async function change(action: ActionItem, status: string) {
    try {
      await api.updateAction(
        board.id,
        action.id,
        status,
        `Set manually during review of the ${board.name} register.`,
      );
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <div className="page wide">
      {error && <div className="banner error">{error}</div>}

      <div className="card">
        <div className="row" style={{ alignItems: "center" }}>
          <div style={{ flex: 1 }}>
            <h2>{board.name} — action register</h2>
            <p className="hint" style={{ margin: "4px 0 0" }}>
              Every action extracted from prior minutes, carried across meeting cycles until
              the pack shows it was discharged.
            </p>
          </div>
          <label style={{ fontSize: 13.5, display: "flex", gap: 6, alignItems: "center" }}>
            <input
              type="checkbox"
              checked={showClosed}
              onChange={(event) => setShowClosed(event.target.checked)}
            />
            Show closed
          </label>
        </div>

        {counts.length > 0 && (
          <div className="sources" style={{ marginTop: 12 }}>
            {counts.map(({ status, count }) => (
              <span key={status} className={`badge ${status}`}>
                {count} {STATUS_LABELS[status] ?? status}
              </span>
            ))}
          </div>
        )}
      </div>

      <div className="card">
        {visible.length === 0 ? (
          <div className="empty">
            No open actions. Upload prior minutes with a board pack to populate the register.
          </div>
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th style={{ width: "42%" }}>Action</th>
                  <th>Owner</th>
                  <th>Raised</th>
                  <th>Due</th>
                  <th>Cycles</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((action) => (
                  <tr key={action.id}>
                    <td>
                      {action.action}
                      {action.status_basis && (
                        <div style={{ color: "var(--ink-faint)", fontSize: 12.5, marginTop: 4 }}>
                          {action.status_basis}
                        </div>
                      )}
                    </td>
                    <td>{action.owner}</td>
                    <td>{action.raised_at}</td>
                    <td>{action.committed_date}</td>
                    <td style={{ fontVariantNumeric: "tabular-nums" }}>
                      {action.ageing_cycles || "—"}
                    </td>
                    <td>
                      {canEdit ? (
                        <select
                          value={action.status}
                          onChange={(event) => void change(action, event.target.value)}
                        >
                          {STATUS_ORDER.map((status) => (
                            <option key={status} value={status}>
                              {STATUS_LABELS[status]}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <span className={`badge ${action.status}`}>
                          {STATUS_LABELS[action.status] ?? action.status}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
