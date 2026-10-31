import { useEffect, useState } from "react";
import { checkNodeHealth, type ConnectionState } from "./api/nodeHealth";

export default function App() {
  const [state, setState] = useState<ConnectionState>({ kind: "checking" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    setState({ kind: "checking" });
    checkNodeHealth().then((next) => {
      if (active) {
        setState(next);
      }
    });
    return () => {
      active = false;
    };
  }, [attempt]);

  return (
    <main className="page">
      <section className="panel" aria-live="polite">
        <h1>Node connection</h1>
        {state.kind === "checking" && <p className="status">Checking the connection to this node...</p>}
        {state.kind === "connected" && (
          <p className="status status-ok">Connected to this node.</p>
        )}
        {state.kind === "unavailable" && (
          <>
            <p className="status status-error">{state.reason}</p>
            <button type="button" className="button" onClick={() => setAttempt((n) => n + 1)}>
              Try again
            </button>
          </>
        )}
      </section>
    </main>
  );
}
