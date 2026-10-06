import { useEffect, useRef, useState } from "react";

const POLL_INTERVAL_MS = 1000;

async function responseData(response) {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || "The repository could not be ingested.");
  }
  return data;
}

function UploadPanel({ onRepoReady }) {
  const [file, setFile] = useState(null);
  const [githubUrl, setGithubUrl] = useState("");
  const [status, setStatus] = useState("idle");
  const [statusMessage, setStatusMessage] = useState("");
  const [error, setError] = useState("");
  const pollTimeout = useRef(null);
  const isIngesting = status === "uploading" || status === "polling";

  useEffect(() => () => clearTimeout(pollTimeout.current), []);

  const pollIngestionStatus = async (repoId) => {
    const response = await fetch(`/ingest/status/${repoId}`);
    const data = await responseData(response);
    setStatusMessage(`Indexing... ${data.file_count} files processed`);

    if (data.status === "ready") {
      // Switch the current session to the newly indexed repository in memory.
      onRepoReady(repoId);
      setStatus("ready");
      setStatusMessage(`Repository ${repoId} is ready and now active.`);
      return;
    }

    if (data.status === "failed") {
      setStatus("error");
      setError("Repository ingestion failed. The previous repository is still active.");
      return;
    }

    // Poll until ingestion reports a terminal state.
    pollTimeout.current = setTimeout(() => {
      pollIngestionStatus(repoId).catch((pollError) => {
        setStatus("error");
        setError(pollError.message || "Unable to check repository ingestion status.");
      });
    }, POLL_INTERVAL_MS);
  };

  const startIngestion = async (request, progressMessage) => {
    // One shared state lock prevents ZIP and GitHub ingestion from polling concurrently.
    if (isIngesting) return;

    setStatus("uploading");
    setStatusMessage(progressMessage);
    setError("");

    try {
      const response = await fetch(request.url, request.options);
      const data = await responseData(response);

      setStatus("polling");
      setStatusMessage(`Indexing... ${data.file_count || 0} files processed`);
      await pollIngestionStatus(data.repo_id);
    } catch (ingestionError) {
      setStatus("error");
      setError(ingestionError.message || "Unable to ingest repository.");
    }
  };

  const uploadRepository = async (event) => {
    event.preventDefault();
    if (!file) return;

    const formData = new FormData();
    formData.append("file", file);
    await startIngestion(
      {
        url: "/ingest/zip",
        options: {
          method: "POST",
          body: formData,
        },
      },
      "Uploading repository ZIP..."
    );
  };

  const importGithubRepository = async (event) => {
    event.preventDefault();
    if (!githubUrl.trim()) return;

    await startIngestion(
      {
        url: "/ingest/github",
        options: {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ url: githubUrl.trim() }),
        },
      },
      "Importing GitHub repository..."
    );
  };

  return (
    <section className="upload-panel" aria-label="Upload a repository">
      <div className="upload-heading">
        <div>
          <h2>Load a repository</h2>
          <p>Upload a ZIP or import a public GitHub repository.</p>
        </div>
        <span className="upload-label">Repository sources</span>
      </div>

      <form className="upload-form" onSubmit={uploadRepository}>
        <input
          type="file"
          accept=".zip,application/zip"
          onChange={(event) => setFile(event.target.files?.[0] || null)}
          disabled={isIngesting}
        />
        <button
          type="submit"
          className="upload-button"
          disabled={!file || isIngesting}
        >
          {status === "uploading" ? "Ingesting..." : "Upload ZIP"}
        </button>
      </form>

      <div className="upload-subsection">
        <div className="upload-subheading">
          <h3>Import from GitHub</h3>
          <span>Public repositories</span>
        </div>
        <form className="upload-form" onSubmit={importGithubRepository}>
          <input
            className="github-input"
            type="url"
            value={githubUrl}
            onChange={(event) => setGithubUrl(event.target.value)}
            placeholder="https://github.com/owner/repository"
            aria-label="GitHub repository URL"
            disabled={isIngesting}
          />
          <button
            type="submit"
            className="upload-button"
            disabled={!githubUrl.trim() || isIngesting}
          >
            Import
          </button>
        </form>
      </div>

      {statusMessage && <div className="upload-status">{statusMessage}</div>}
      {error && <div className="error upload-error">{error}</div>}
    </section>
  );
}

export default UploadPanel;