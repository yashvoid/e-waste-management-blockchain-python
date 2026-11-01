import { useEffect, useState, useCallback } from "react";
import { checkNodeHealth, type ConnectionState } from "./api/nodeHealth";
import { listWalletAddresses } from "./wallet/walletStore";
import {
  createWallet,
  unlock,
  lock,
  getUnlockedAddress,
  getUnlockedPublicKey,
  exportWalletBackup,
  importWalletBackup,
} from "./wallet/walletSession";
import { getParticipant, getChainStatus, requestRegistrationCode, submitRegistrationAttestation, type ParticipantView, type Role } from "./api/client";
import type { ChainInfo } from "./blockchain/transaction";
import Dashboard from "./screens/Dashboard";
import Batches from "./screens/Batches";
import Transfers from "./screens/Transfers";
import Processing from "./screens/Processing";
import Materials from "./screens/Materials";
import Traceability from "./screens/Traceability";
import NodeStatus from "./screens/NodeStatus";
import TransactionStatus from "./screens/TransactionStatus";
import Notifications from "./screens/Notifications";
import { useNotifications } from "./notifications/useNotifications";
import { shortKey } from "./utils/format";

type Screen = "dashboard" | "batches" | "transfers" | "processing" | "materials" | "traceability" | "txstatus" | "node" | "notifications";
type WalletView = "none" | "create" | "unlock" | "restore";

interface RegistrationState {
  step: "idle" | "email" | "code" | "done";
  email: string;
  code: string;
  role: Role;
  error: string;
  busy: boolean;
}

export default function App() {
  const [connection, setConnection] = useState<ConnectionState>({ kind: "checking" });
  const [chainInfo, setChainInfo] = useState<ChainInfo | null>(null);
  const [unlockedAddress, setUnlockedAddress] = useState<string | null>(null);
  const [savedAddresses, setSavedAddresses] = useState<string[]>([]);
  const [participant, setParticipant] = useState<ParticipantView | null>(null);
  const [participantError, setParticipantError] = useState("");
  const [screen, setScreen] = useState<Screen>("dashboard");
  const [refreshKey, setRefreshKey] = useState(0);
  const [focusTxid, setFocusTxid] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setConnection({ kind: "checking" });
    checkNodeHealth().then((next) => {
      if (active) setConnection(next);
    });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    setUnlockedAddress(getUnlockedAddress());
    listWalletAddresses().then(setSavedAddresses).catch(() => setSavedAddresses([]));
  }, []);

  const refreshParticipant = useCallback(async (publicKey: string) => {
    setParticipantError("");
    try {
      const p = await getParticipant(publicKey);
      setParticipant(p);
    } catch (e) {
      setParticipant(null);
      if (e instanceof Error && !e.message.includes("404")) {
        setParticipantError(e.message);
      }
    }
  }, []);

  useEffect(() => {
    const pub = getUnlockedPublicKey();
    if (pub) refreshParticipant(pub);
    else { setParticipant(null); setParticipantError(""); }
  }, [unlockedAddress, refreshParticipant]);

  useEffect(() => {
    if (connection.kind !== "connected") { setChainInfo(null); return; }
    let active = true;
    getChainStatus().then((info) => { if (active) setChainInfo(info); }).catch(() => {});
    return () => { active = false; };
  }, [connection, refreshKey]);

  const triggerRefresh = useCallback(() => setRefreshKey((k) => k + 1), []);

  const nodeConnected = connection.kind === "connected";
  const walletUnlocked = unlockedAddress !== null;
  const isRegistered = participant !== null;
  const role = participant?.role;
  const pubKey = getUnlockedPublicKey();
  const notificationResult = useNotifications(pubKey ?? "", walletUnlocked && isRegistered && nodeConnected);

  const handleNavigateFromNotification = useCallback((targetScreen: string, targetId?: string) => {
    const s = targetScreen as Screen;
    if (s === "txstatus" && targetId) {
      setFocusTxid(targetId);
    }
    setScreen(s);
  }, []);

  const navItems: { key: Screen; label: string }[] = [
    { key: "dashboard", label: "Dashboard" },
    { key: "batches", label: "Batches" },
    { key: "transfers", label: "Transfers" },
    { key: "processing", label: "Processing" },
    { key: "materials", label: "Materials" },
    { key: "traceability", label: "Traceability" },
    { key: "txstatus", label: "Transactions" },
    { key: "notifications", label: "Notifications" },
    { key: "node", label: "Node status" },
  ];

  return (
    <div className="app-layout">
      <header className="app-header">
        <div className="header-section">
          <span className={"header-indicator " + (nodeConnected ? "indicator-ok" : "indicator-error")} />
          <span className="header-text">
            {connection.kind === "checking" && "Checking node..."}
            {connection.kind === "connected" && "Node connected"}
            {connection.kind === "unavailable" && "Node unavailable"}
          </span>
          {chainInfo && (
            <span className="header-detail">Block height: {chainInfo.tipHeight}</span>
          )}
        </div>
        <div className="header-section">
          {walletUnlocked ? (
            <>
              <span className="header-text">Wallet: {unlockedAddress ? shortKey(unlockedAddress) : ""}</span>
              {isRegistered && <span className="header-role">{role}</span>}
              <button className="button button-small" onClick={() => { lock(); setUnlockedAddress(null); setParticipant(null); }}>Lock</button>
            </>
          ) : (
            <span className="header-text">No wallet connected</span>
          )}
        </div>
      </header>

      {!nodeConnected && (
        <div className="app-banner">
          {connection.kind === "checking" && "Checking the connection to this node..."}
          {connection.kind === "unavailable" && (connection.reason || "This node could not be reached.")}
        </div>
      )}

      <div className="app-body">
        {!walletUnlocked && (
          <WalletPanel onUnlocked={(addr) => setUnlockedAddress(addr)} savedAddresses={savedAddresses} />
        )}

        {walletUnlocked && !isRegistered && nodeConnected && (
          <div>
            {participantError && (
              <div className="app-banner">Unable to verify registration status: {participantError}</div>
            )}
            <RegistrationPanel
              publicKey={getUnlockedPublicKey()!}
              onRegistered={() => refreshParticipant(getUnlockedPublicKey()!)}
            />
          </div>
        )}

        {walletUnlocked && isRegistered && nodeConnected && (
          <>
            <nav className="app-nav">
              {navItems.map((item) => (
                <button
                  key={item.key}
                  className={"nav-button " + (screen === item.key ? "nav-active" : "")}
                  onClick={() => setScreen(item.key)}
                >
                  {item.label}
                  {item.key === "notifications" && notificationResult.unread > 0 && (
                    <span className="nav-badge">{notificationResult.unread}</span>
                  )}
                </button>
              ))}
            </nav>
            <main className="app-main">
              {screen === "dashboard" && <Dashboard role={role!} publicKey={getUnlockedPublicKey()!} chainInfo={chainInfo} refreshKey={refreshKey} />}
              {screen === "batches" && <Batches role={role!} onRefresh={triggerRefresh} />}
              {screen === "transfers" && <Transfers role={role!} publicKey={getUnlockedPublicKey()!} onRefresh={triggerRefresh} />}
              {screen === "processing" && <Processing role={role!} publicKey={getUnlockedPublicKey()!} onRefresh={triggerRefresh} />}
              {screen === "materials" && <Materials />}
              {screen === "traceability" && <Traceability />}
              {screen === "txstatus" && <TransactionStatus focusTxid={focusTxid} />}
              {screen === "notifications" && <Notifications result={notificationResult} onNavigate={handleNavigateFromNotification} />}
              {screen === "node" && <NodeStatus chainInfo={chainInfo} connection={connection} />}
            </main>
          </>
        )}

        {walletUnlocked && !nodeConnected && (
          <div className="panel">
            <p className="status">The node is not available. You can still lock your wallet and try again later.</p>
          </div>
        )}
      </div>
    </div>
  );
}

function WalletPanel({ onUnlocked, savedAddresses }: { onUnlocked: (addr: string) => void; savedAddresses: string[] }) {
  const [view, setView] = useState<WalletView>("none");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [unlockAddress, setUnlockAddress] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [restoreFileContent, setRestoreFileContent] = useState("");
  const [restoreFileName, setRestoreFileName] = useState("");
  const [restorePassword, setRestorePassword] = useState("");

  async function handleCreate() {
    setError("");
    if (password !== confirmPassword) { setError("Passwords do not match."); return; }
    setBusy(true);
    try {
      const address = await createWallet(password);
      onUnlocked(address);
      setView("none"); setPassword(""); setConfirmPassword("");
    } catch (e) { setError(e instanceof Error ? e.message : "Unable to create wallet."); }
    finally { setBusy(false); }
  }

  async function handleUnlock() {
    setError(""); setBusy(true);
    try {
      await unlock(unlockAddress, password);
      onUnlocked(unlockAddress);
      setView("none"); setPassword("");
    } catch (e) { setError(e instanceof Error ? e.message : "Unable to unlock wallet."); }
    finally { setBusy(false); }
  }

  async function handleRestore() {
    setError(""); setBusy(true);
    try {
      await importWalletBackup(restoreFileContent, restorePassword);
      setView("none"); setRestorePassword(""); setRestoreFileContent(""); setRestoreFileName("");
      setError("");
    } catch (e) { setError(e instanceof Error ? e.message : "Unable to restore wallet backup."); }
    finally { setBusy(false); }
  }

  async function handleExport() {
    const addr = getUnlockedAddress();
    if (!addr) return;
    setError(""); setBusy(true);
    try {
      const { content, filename } = await exportWalletBackup(addr);
      const blob = new Blob([content], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url; link.download = filename; link.click();
      URL.revokeObjectURL(url);
    } catch (e) { setError(e instanceof Error ? e.message : "Unable to export wallet backup."); }
    finally { setBusy(false); }
  }

  function handleFileSelect(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setError("");
    const reader = new FileReader();
    reader.onload = () => {
      setRestoreFileContent(reader.result as string);
      setRestoreFileName(file.name);
    };
    reader.onerror = () => setError("Unable to read the selected file.");
    reader.readAsText(file);
  }

  return (
    <section className="panel">
      <h1>Wallet</h1>
      {view === "none" && (
        <div>
          <p className="status">No wallet is currently unlocked.</p>
          <div className="button-group">
            <button className="button" onClick={() => { setError(""); setPassword(""); setConfirmPassword(""); setView("create"); }}>Create new wallet</button>
            {savedAddresses.length > 0 && (
              <button className="button button-secondary" onClick={() => { setError(""); setPassword(""); setUnlockAddress(savedAddresses[0]); setView("unlock"); }}>Unlock existing wallet</button>
            )}
            <button className="button button-secondary" onClick={() => { setError(""); setRestorePassword(""); setRestoreFileContent(""); setRestoreFileName(""); setView("restore"); }}>Restore wallet backup</button>
          </div>
          {savedAddresses.length > 0 && <p className="hint">{savedAddresses.length} wallet{savedAddresses.length > 1 ? "s" : ""} stored in this browser.</p>}
        </div>
      )}
      {view === "create" && (
        <div className="wallet-form">
          <p className="status">Choose a password for your new wallet. It must be at least 12 characters.</p>
          <label className="field-label">Password
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" minLength={12} />
          </label>
          <label className="field-label">Confirm password
            <input type="password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} autoComplete="new-password" minLength={12} />
          </label>
          {error && <p className="status status-error">{error}</p>}
          <div className="button-group">
            <button className="button" onClick={handleCreate} disabled={busy || !password || !confirmPassword}>{busy ? "Creating..." : "Create wallet"}</button>
            <button className="button button-secondary" onClick={() => setView("none")} disabled={busy}>Cancel</button>
          </div>
          <p className="hint">Your wallet is stored only in this browser for this node address. There is no way to recover a lost password.</p>
        </div>
      )}
      {view === "unlock" && (
        <div className="wallet-form">
          <p className="status">Enter your password to unlock the wallet.</p>
          {savedAddresses.length > 1 && (
            <label className="field-label">Wallet address
              <select value={unlockAddress} onChange={(e) => setUnlockAddress(e.target.value)}>
                <option value="">Select a wallet</option>
                {savedAddresses.map((addr) => <option key={addr} value={addr}>{addr}</option>)}
              </select>
            </label>
          )}
          <label className="field-label">Password
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
          </label>
          {error && <p className="status status-error">{error}</p>}
          <div className="button-group">
            <button className="button" onClick={handleUnlock} disabled={busy || !password || !unlockAddress}>{busy ? "Unlocking..." : "Unlock wallet"}</button>
            <button className="button button-secondary" onClick={() => setView("none")} disabled={busy}>Cancel</button>
          </div>
        </div>
      )}
      {view === "restore" && (
        <div className="wallet-form">
          <p className="status">Select a backup file and enter the wallet password to restore it.</p>
          <label className="field-label">Backup file
            <input type="file" accept=".ewallet,application/json" onChange={handleFileSelect} />
          </label>
          {restoreFileName && <p className="hint">Selected: {restoreFileName}</p>}
          <label className="field-label">Wallet password
            <input type="password" value={restorePassword} onChange={(e) => setRestorePassword(e.target.value)} autoComplete="current-password" />
          </label>
          {error && <p className="status status-error">{error}</p>}
          <div className="button-group">
            <button className="button" onClick={handleRestore} disabled={busy || !restoreFileContent || !restorePassword}>{busy ? "Restoring..." : "Restore wallet"}</button>
            <button className="button button-secondary" onClick={() => setView("none")} disabled={busy}>Cancel</button>
          </div>
          <p className="hint">The backup file contains your encrypted wallet. Store it securely.</p>
        </div>
      )}
      {getUnlockedAddress() && (
        <div className="wallet-status">
          <p className="status status-ok">Wallet unlocked</p>
          <p className="status address-label">Address: {getUnlockedAddress()}</p>
          <button className="button button-secondary" onClick={handleExport} disabled={busy}>Export wallet backup</button>
        </div>
      )}
    </section>
  );
}

const ROLE_OPTIONS: Role[] = ["Generator", "Collector", "Transporter", "Recycler", "Material Processor"];

function RegistrationPanel({ publicKey, onRegistered }: { publicKey: string; onRegistered: () => void }) {
  const [reg, setReg] = useState<RegistrationState>({
    step: "email", email: "", code: "", role: "Generator", error: "", busy: false,
  });

  async function requestCode() {
    setReg((r) => ({ ...r, error: "", busy: true }));
    try {
      await requestRegistrationCode(reg.email);
      setReg((r) => ({ ...r, step: "code", busy: false }));
    } catch (e) {
      setReg((r) => ({ ...r, error: e instanceof Error ? e.message : "Unable to request verification code.", busy: false }));
    }
  }

  async function submitAttestation() {
    setReg((r) => ({ ...r, error: "", busy: true }));
    try {
      await submitRegistrationAttestation(reg.email, reg.code, publicKey, reg.role);
      setReg((r) => ({ ...r, step: "done", busy: false }));
      onRegistered();
    } catch (e) {
      setReg((r) => ({ ...r, error: e instanceof Error ? e.message : "Registration failed.", busy: false }));
    }
  }

  return (
    <section className="panel">
      <h1>Register your wallet</h1>
      <p className="status">Your wallet is not yet registered on this network. Complete registration to participate.</p>
      <p className="hint">Public key: {shortKey(publicKey)}</p>
      {reg.step === "email" && (
        <div className="wallet-form">
          <label className="field-label">Email address
            <input type="email" value={reg.email} onChange={(e) => setReg((r) => ({ ...r, email: e.target.value }))} />
          </label>
          <label className="field-label">Business role
            <select value={reg.role} onChange={(e) => setReg((r) => ({ ...r, role: e.target.value as Role }))}>
              {ROLE_OPTIONS.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
          </label>
          <p className="hint">The role cannot be changed after registration. Email verification proves access to an email account, not real-world identity.</p>
          {reg.error && <p className="status status-error">{reg.error}</p>}
          <div className="button-group">
            <button className="button" onClick={requestCode} disabled={reg.busy || !reg.email}>{reg.busy ? "Sending..." : "Request verification code"}</button>
          </div>
        </div>
      )}
      {reg.step === "code" && (
        <div className="wallet-form">
          <p className="status">A verification code has been sent to {reg.email}. Enter the 6-digit code to complete registration as a {reg.role}.</p>
          <label className="field-label">Verification code
            <input type="text" maxLength={6} value={reg.code} onChange={(e) => setReg((r) => ({ ...r, code: e.target.value.replace(/\D/g, "") }))} />
          </label>
          {reg.error && <p className="status status-error">{reg.error}</p>}
          <div className="button-group">
            <button className="button" onClick={submitAttestation} disabled={reg.busy || reg.code.length !== 6}>{reg.busy ? "Registering..." : "Complete registration"}</button>
            <button className="button button-secondary" onClick={() => setReg((r) => ({ ...r, step: "email", code: "" }))} disabled={reg.busy}>Back</button>
          </div>
        </div>
      )}
      {reg.step === "done" && (
        <div>
          <p className="status status-ok">Registration submitted. Your wallet is now registered as a {reg.role}.</p>
        </div>
      )}
    </section>
  );
}
