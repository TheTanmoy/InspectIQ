import { useEffect, useState } from "react";
import { api } from "../api";
import { Logo } from "../components/Icons.jsx";

export default function Login({ onLogin }) {
  const [username, setUsername] = useState("inspector");
  const [password, setPassword] = useState("demo123");
  const [demo, setDemo] = useState([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => { api.demoUsers().then(setDemo).catch(() => {}); }, []);

  const submit = async (e) => {
    e?.preventDefault();
    setBusy(true); setError("");
    try { onLogin(await api.login(username, password)); }
    catch (err) { setError(err.message); }
    finally { setBusy(false); }
  };

  return (
    <div className="login-screen">
      <div className="login-card">
        <div className="brand big">
          <span className="logo"><Logo /></span>
          <div>
            <div className="brand-name">InspectIQ</div>
            <div className="brand-sub">AI quality inspection · Prompt Syndicates</div>
          </div>
        </div>
        <p className="muted">Restricted to quality personnel. Sign in with your role.</p>
        <form onSubmit={submit} className="form">
          <label>Username<input value={username} onChange={(e) => setUsername(e.target.value)} autoFocus /></label>
          <label>Password<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} /></label>
          {error && <div className="error">⚠️ {error}</div>}
          <button className="primary full" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
        </form>
        {demo.length > 0 && (
          <div className="demo-users">
            <div className="muted small-text">Demo accounts (password <code>demo123</code>):</div>
            <div className="row wrap">
              {demo.map((d) => (
                <button key={d.username} className={`ghost small ${username === d.username ? "selected" : ""}`}
                        onClick={() => { setUsername(d.username); setPassword("demo123"); }}>
                  {d.role_label}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
