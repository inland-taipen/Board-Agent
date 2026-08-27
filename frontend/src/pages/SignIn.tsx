import { useState, type FormEvent } from "react";

import { api, type SessionUser } from "../api";

export default function SignIn({ onSignedIn }: { onSignedIn: (user: SessionUser) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [reveal, setReveal] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await api.login(email.trim(), password);
      onSignedIn({
        email: result.email,
        role: result.role,
        display_name: result.display_name,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="signin">
      <div className="mark">
        <h1>BoardLens AI</h1>
        <p>Board Intelligence Agent</p>
      </div>

      <form className="card" onSubmit={submit}>
        {error && (
          <div className="banner error" role="alert">
            {error}
          </div>
        )}

        <div className="field">
          <label htmlFor="email">Email</label>
          <input
            id="email"
            name="email"
            type="email"
            autoComplete="username"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
        </div>

        <div className="field">
          <label htmlFor="password">Password</label>
          <input
            id="password"
            name="password"
            type={reveal ? "text" : "password"}
            autoComplete="current-password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
          {/* Password managers autofill a saved credential for localhost far more
              often than anyone expects, and the result is an unexplained 401.
              Letting the user see what is actually in the field settles it. */}
          <button
            type="button"
            className="btn quiet small"
            style={{ alignSelf: "flex-start", padding: "2px 0" }}
            onClick={() => setReveal((current) => !current)}
          >
            {reveal ? "Hide password" : "Show password"}
          </button>
        </div>

        <button className="btn" type="submit" disabled={busy}>
          {busy ? "Signing in..." : "Sign in"}
        </button>
      </form>
    </div>
  );
}
