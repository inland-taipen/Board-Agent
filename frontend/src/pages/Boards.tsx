import { useState, type FormEvent } from "react";

import { api, type Board } from "../api";

interface Props {
  boards: Board[];
  canCreate: boolean;
  onSelect: (board: Board) => void;
  onCreated: () => void;
}

export default function Boards({ boards, canCreate, onSelect, onCreated }: Props) {
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function create(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.createBoard(name.trim());
      setName("");
      onCreated();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <div className="card">
        <h2>Client boards</h2>
        <p className="hint">
          Each board is fully segregated. Packs, briefings and the action register for one
          board are never visible from another.
        </p>

        {boards.length === 0 ? (
          <div className="empty">
            You are not a member of any board yet. An administrator needs to add you.
          </div>
        ) : (
          boards.map((board) => (
            <button key={board.id} className="list-item" onClick={() => onSelect(board)}>
              <div>
                <div className="title">{board.name}</div>
                <div className="meta">Added {board.created_at.slice(0, 10)}</div>
              </div>
              <div className="spacer" />
              <span className="badge">Open</span>
            </button>
          ))
        )}
      </div>

      {canCreate && (
        <form className="card" onSubmit={create}>
          <h2>Add a board</h2>
          <p className="hint">
            Use the company's registered name — it appears on every exported briefing.
          </p>
          {error && <div className="banner error">{error}</div>}
          <div className="row">
            <div className="field">
              <label htmlFor="board-name">Company name</label>
              <input
                id="board-name"
                required
                minLength={2}
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="Meridian Industries Limited"
              />
            </div>
            <button className="btn" type="submit" disabled={busy || name.trim().length < 2}>
              {busy ? "Adding..." : "Add board"}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
