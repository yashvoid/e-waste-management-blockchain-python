import { useState, type FormEvent } from "react";
import { signInOperator } from "../api/client";
import { setOperatorToken } from "../api/operatorSession";

interface Props {
  notice: string;
  onSignedIn: () => void;
}

export default function OperatorSignIn({ notice, onSignedIn }: Props) {
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!password) {
      setError("Enter the operator password.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const result = await signInOperator(password);
      setOperatorToken(result.token);
      onSignedIn();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to sign in.");
    } finally {
      setPassword("");
      setBusy(false);
    }
  }

  return (
    <div className="info-block">
      <h2>Operator sign in</h2>
      <p className="hint">Node management is restricted to the operator of this node. Enter the operator password to continue.</p>
      {notice && <p className="status">{notice}</p>}
      <form onSubmit={handleSubmit}>
        <label className="field-label">
          Operator password
          <input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            disabled={busy}
          />
        </label>
        <div className="button-group">
          <button type="submit" className="button button-small" disabled={busy}>
            {busy ? "Signing in..." : "Sign in"}
          </button>
        </div>
      </form>
      {error && <p className="status status-error">{error}</p>}
    </div>
  );
}
