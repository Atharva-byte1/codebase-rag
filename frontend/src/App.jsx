import { useEffect, useState } from "react";
import { Send, Code2 } from "lucide-react";
import UploadPanel from "./UploadPanel";
import "./App.css";

const REPOSITORY_ID = 16;

function App() {
  const [message, setMessage] = useState("");
  const [answer, setAnswer] = useState("");
  const [sources, setSources] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [backendStatus, setBackendStatus] = useState("checking");
  const [activeRepositoryId, setActiveRepositoryId] = useState(REPOSITORY_ID);

  useEffect(() => {
    const controller = new AbortController();

    fetch("/health", { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error("Backend health check failed");
        setBackendStatus("connected");
      })
      .catch((healthError) => {
        if (healthError.name !== "AbortError") setBackendStatus("offline");
      });

    return () => controller.abort();
  }, []);

  const sendMessage = async () => {
    if (!message.trim() || loading) return;

    setLoading(true);
    setAnswer("");
    setSources([]);
    setError("");

    try {
      const response = await fetch("/chat", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          message: message.trim(),
          repo_id: activeRepositoryId,
        }),
      });

      const data = await response.json().catch(() => ({}));

      if (!response.ok) {
        throw new Error(data.detail || "The backend could not answer the request.");
      }

      setAnswer(data.answer || "No answer returned.");
      setSources(data.sources || []);
    } catch (error) {
      setError(error.message || "Unable to reach the backend.");
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendMessage();
    }
  };

  return (
    <div className="app">
      <header className="header">
        <div className="logo">
          <Code2 size={28} />
          <span>Codebase RAG</span>
        </div>

          <span className={`status status-${backendStatus}`}>
            <span className="status-dot"></span>
            {backendStatus === "checking" && "Checking backend"}
            {backendStatus === "connected" && "Backend connected"}
            {backendStatus === "offline" && "Backend unavailable"}
        </span>
      </header>

      <main className="main">
        <section className="hero">
          <h1>Ask your codebase.</h1>
          <p>
            Understand your repository using AI-powered code search and
            retrieval.
          </p>
        </section>

        <section className="chat-container">
          <UploadPanel onRepoReady={setActiveRepositoryId} />

          <div className="input-area">
            <textarea
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask something about your codebase..."
              rows={3}
              disabled={loading}
            />

            <button
              onClick={sendMessage}
              disabled={!message.trim() || loading}
              className="send-button"
            >
              {loading ? "Thinking..." : <Send size={19} />}
            </button>
          </div>

          {loading && (
            <div className="loading">
              Searching your codebase and generating an answer...
            </div>
          )}

          {error && <div className="error">{error}</div>}

          {answer && (
            <div className="answer-card">
              <div className="answer-header">
                <span>AI Answer</span>
              </div>

              <div className="answer">
                {answer}
              </div>
            </div>
          )}

          {sources.length > 0 && (
            <div className="sources-card">
              <h3>Sources</h3>

              {sources.map((source) => (
                <div
                  className="source"
                  key={`${source.citation_id}-${source.file_path}`}
                >
                  <div className="source-title">
                    [{source.citation_id}] {source.file_path}
                  </div>

                  <div className="source-details">
                    {source.symbol_name && (
                      <span>{source.symbol_name}</span>
                    )}

                    {source.start_line != null && source.end_line != null && (
                      <span>
                        Lines {source.start_line}-{source.end_line}
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      </main>
    </div>
  );
}

export default App;