import { useCallback, useEffect, useState, type FormEvent } from "react";

import { api, type Board, type Member, type Role } from "../api";

const ROLES: Array<{ value: Role; label: string; what: string }> = [
  { value: "director", label: "Director", what: "Reads briefings. Cannot upload or generate." },
  {
    value: "secretary",
    label: "Company secretary",
    what: "Uploads board packs, generates briefings, maintains the action register.",
  },
  { value: "admin", label: "Administrator", what: "All of the above, plus managing people." },
];

/**
 * Admin-only people management.
 *
 * Access to a board is a membership row, not a role, so this screen is where
 * segregation is actually administered. It exists because handing a reviewer a
 * shared password is the wrong answer: the audit log records who read which
 * briefing, and that is worthless if three people share one account.
 */
export default function People({ board }: { board: Board }) {
  const [members, setMembers] = useState<Member[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setMembers(await api.members(board.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [board.id]);

  useEffect(() => {
    void load();
  }, [load]);

  async function add(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const email = String(data.get("email")).trim();
    const password = String(data.get("password"));

    setBusy(true);
    setError("");
    setNotice("");
    try {
      await api.addMember(board.id, {
        email,
        role: String(data.get("role")) as Role,
        display_name: String(data.get("display_name")).trim(),
        password,
      });
      form.reset();
      await load();
      setNotice(
        `${email} can now sign in. Send them the address of this site, their email, ` +
          `and the password you just set — the password is not recoverable from here, ` +
          `so note it before you navigate away.`,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function remove(member: Member) {
    setError("");
    setNotice("");
    try {
      await api.removeMember(board.id, member.id);
      await load();
      setNotice(`${member.email} no longer has access to ${board.name}.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <div className="page">
      {error && <div className="banner error">{error}</div>}
      {notice && <div className="banner ok">{notice}</div>}

      <div className="card">
        <h2>People with access to {board.name}</h2>
        <p className="hint">
          Access is granted per board. Someone with an account here cannot see any other
          board unless they are added to it separately.
        </p>

        {members.length === 0 ? (
          <div className="empty">Nobody has access yet.</div>
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Email</th>
                  <th>Role</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {members.map((member) => (
                  <tr key={member.id}>
                    <td>{member.display_name || "—"}</td>
                    <td>{member.email}</td>
                    <td>
                      <span className="badge">
                        {ROLES.find((r) => r.value === member.role)?.label ?? member.role}
                      </span>
                    </td>
                    <td style={{ textAlign: "right" }}>
                      <button className="btn quiet small" onClick={() => void remove(member)}>
                        Remove
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <form className="card" onSubmit={add}>
        <h2>Add someone</h2>
        <p className="hint">
          Set a password here and pass it to them directly. If the email already has an
          account, they are simply granted access to this board and the password is ignored.
        </p>

        <div className="row">
          <div className="field">
            <label htmlFor="display_name">Name</label>
            <input id="display_name" name="display_name" placeholder="A. Desai" />
          </div>
          <div className="field">
            <label htmlFor="member_email">Email</label>
            <input
              id="member_email"
              name="email"
              type="email"
              required
              placeholder="director@example.com"
            />
          </div>
        </div>

        <div className="row" style={{ marginTop: 12 }}>
          <div className="field">
            <label htmlFor="member_role">Role</label>
            <select id="member_role" name="role" defaultValue="director">
              {ROLES.map((role) => (
                <option key={role.value} value={role.value}>
                  {role.label}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="member_password">Password</label>
            <input
              id="member_password"
              name="password"
              type="text"
              required
              minLength={10}
              placeholder="at least 10 characters"
            />
          </div>
          <button className="btn" type="submit" disabled={busy}>
            {busy ? "Adding..." : "Add person"}
          </button>
        </div>

        <div style={{ marginTop: 16 }}>
          {ROLES.map((role) => (
            <div key={role.value} style={{ fontSize: 13, color: "var(--ink-soft)" }}>
              <strong>{role.label}</strong> — {role.what}
            </div>
          ))}
        </div>
      </form>
    </div>
  );
}
