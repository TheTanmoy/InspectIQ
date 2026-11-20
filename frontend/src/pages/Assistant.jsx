import { useEffect, useRef, useState } from "react";
import { streamChat } from "../api";
import Markdown from "../components/Markdown.jsx";

const STARTERS = [
  "Why is porosity high on L1 night shift?",
  "Which features have Cpk below 1.33?",
  "Summarise the main quality risks this month",
  "Which reports are blocked and why?",
];

export default function Assistant() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const abortRef = useRef(null);
  const endRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  const send = async (text) => {
    const content = (text ?? input).trim();
    if (!content || busy) return;
    setError(""); setInput("");
    const history = [...messages, { role: "user", content }];
    setMessages([...history, { role: "assistant", content: "" }]);
    setBusy(true);
    abortRef.current = new AbortController();
    try {
      await streamChat({
        messages: history, signal: abortRef.current.signal,
        onToken: (chunk) => setMessages((m) => {
          const copy = [...m];
          copy[copy.length - 1] = { role: "assistant", content: copy[copy.length - 1].content + chunk };
          return copy;
        }),
      });
    } catch (e) {
      if (e.name !== "AbortError") setError(e.message);
    } finally { setBusy(false); }
  };

  return (
    <div className="chat">
      <header className="page-header">
        <div>
          <h1>Ask Quality AI</h1>
          <p className="muted">Answers come only from plant data you are allowed to see. Off-topic and rule-breaking prompts are blocked.</p>
        </div>
        <button className="ghost" onClick={() => { abortRef.current?.abort(); setMessages([]); }}>New chat</button>
      </header>
      <section className="messages">
        {!messages.length && (
          <div className="empty">
            <div className="empty-icon">💬</div>
            <h2>What would you like to know?</h2>
            <div className="starters">{STARTERS.map((s) => <button key={s} className="starter" onClick={() => send(s)}>{s}</button>)}</div>
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>
            <div className="bubble">
              {m.role === "assistant" ? (m.content ? <Markdown text={m.content} /> : <span className="typing"><i /><i /><i /></span>) : m.content}
            </div>
          </div>
        ))}
        <div ref={endRef} />
      </section>
      {error && <div className="error">⚠️ {error}</div>}
      <form className="composer" onSubmit={(e) => { e.preventDefault(); send(); }}>
        <textarea value={input} rows={1} placeholder="Ask about defects, lines, Cpk, compliance…"
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }} />
        {busy ? <button type="button" className="primary" onClick={() => abortRef.current?.abort()}>Stop</button>
              : <button type="submit" className="primary" disabled={!input.trim()}>Send</button>}
      </form>
    </div>
  );
}
