import React, { useMemo, useState, useRef } from "react";

const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8050";
const WS_BASE = import.meta.env.VITE_WS_BASE ||
  (API_BASE.startsWith("https")
    ? API_BASE.replace("https", "wss")
    : API_BASE.replace("http", "ws"));

const ACCESS_KEY = "jwt_access";
const REFRESH_KEY = "jwt_refresh";
const APPROVED_KEY = "dev_approved";

function useLocalState(key, fallback = "") {
  const [value, setValue] = useState(() => localStorage.getItem(key) || fallback);
  const set = (next) => {
    setValue(next);
    if (next === "" || next === null || next === undefined) {
      localStorage.removeItem(key);
    } else {
      localStorage.setItem(key, next);
    }
  };
  return [value, set];
}

async function apiFetch(url, options = {}) {
  const token = localStorage.getItem(ACCESS_KEY);
  if (!token) {
    throw new Error("Not authenticated");
  }
  const headers = options.headers ? { ...options.headers } : {};
  headers.Authorization = `Bearer ${token}`;
  options.headers = headers;

  let response = await fetch(url, options);
  if (response.status === 401) {
    const refresh = localStorage.getItem(REFRESH_KEY);
    if (!refresh) {
      localStorage.removeItem(ACCESS_KEY);
      throw new Error("Session expired");
    }
    const refreshResponse = await fetch(`${API_BASE}/api/token/refresh/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh }),
    });
    if (!refreshResponse.ok) {
      localStorage.removeItem(ACCESS_KEY);
      localStorage.removeItem(REFRESH_KEY);
      throw new Error("Session expired");
    }
    const data = await refreshResponse.json();
    localStorage.setItem(ACCESS_KEY, data.access);
    if (data.refresh) {
      localStorage.setItem(REFRESH_KEY, data.refresh);
    }
    options.headers.Authorization = `Bearer ${data.access}`;
    response = await fetch(url, options);
  }
  return response;
}

export default function App() {
  const [approved, setApproved] = useLocalState(APPROVED_KEY, "");
  const [access, setAccess] = useLocalState(ACCESS_KEY, "");
  const [refresh, setRefresh] = useLocalState(REFRESH_KEY, "");
  const [approvalCode, setApprovalCode] = useState("");
  const [approvalMessage, setApprovalMessage] = useState("");

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [authMessage, setAuthMessage] = useState("");

  const [deleteMode, setDeleteMode] = useState("delete");
  const [deleteController, setDeleteController] = useState("xl");
  const [deleteMessage, setDeleteMessage] = useState("");
  const [deleteCounts, setDeleteCounts] = useState({ total: 0, success: 0, fail: 0 });
  const [deleteRows, setDeleteRows] = useState([]);

  const [priceController, setPriceController] = useState("xl");
  const [priceMessage, setPriceMessage] = useState("");

  const [uploadController, setUploadController] = useState("xl");
  const [uploadMode, setUploadMode] = useState("upload_collection");
  const [uploadMessage, setUploadMessage] = useState("");
  const [uploadFeed, setUploadFeed] = useState([]);

  const [wsStatus, setWsStatus] = useState({ upload: "Disconnected", delete: "Disconnected" });

  const deleteSocketRef = useRef(null);
  const uploadSocketRef = useRef(null);
  const deleteSeen = useRef(new Set());

  const isAuthed = useMemo(() => !!access, [access]);
  const isApproved = approved === "true";

  async function handleApprove(event) {
    event.preventDefault();
    setApprovalMessage("Checking...");
    try {
      const response = await fetch(`${API_BASE}/api/approve/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code: approvalCode }),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.error || "Approval failed");
      }
      setApproved("true");
      setApprovalMessage("Approved. You can continue.");
      setApprovalCode("");
    } catch (error) {
      setApproved("");
      setApprovalMessage(error.message);
    }
  }

  function revokeApproval() {
    setApproved("");
    setApprovalMessage("Approval removed.");
  }

  async function handleLogin(event) {
    event.preventDefault();
    setAuthMessage("Signing in...");
    try {
      const response = await fetch(`${API_BASE}/api/token/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || "Login failed");
      }
      setAccess(data.access || "");
      setRefresh(data.refresh || "");
      setAuthMessage("Signed in.");
    } catch (error) {
      setAuthMessage(error.message);
    }
  }

  function handleLogout() {
    setAccess("");
    setRefresh("");
    setAuthMessage("Signed out.");
  }

  function ensureUploadSocket() {
    if (uploadSocketRef.current && uploadSocketRef.current.readyState === WebSocket.OPEN) {
      return;
    }
    const socket = new WebSocket(`${WS_BASE}/ws/upload-progress/`);
    socket.onopen = () => setWsStatus((s) => ({ ...s, upload: "Connected" }));
    socket.onclose = () => setWsStatus((s) => ({ ...s, upload: "Disconnected" }));
    socket.onerror = () => setWsStatus((s) => ({ ...s, upload: "Error" }));
    socket.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        setUploadFeed((prev) => [
          { ean: payload.ean, stage: payload.stage, ts: new Date().toLocaleTimeString() },
          ...prev,
        ]);
      } catch (error) {
        console.error(error);
      }
    };
    uploadSocketRef.current = socket;
  }

  function ensureDeleteSocket() {
    if (deleteSocketRef.current && deleteSocketRef.current.readyState === WebSocket.OPEN) {
      return;
    }
    const socket = new WebSocket(`${WS_BASE}/ws/delete-progress/`);
    socket.onopen = () => setWsStatus((s) => ({ ...s, delete: "Connected" }));
    socket.onclose = () => setWsStatus((s) => ({ ...s, delete: "Disconnected" }));
    socket.onerror = () => setWsStatus((s) => ({ ...s, delete: "Error" }));
    socket.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        const success = payload.message?.info === "success";
        const key = `${payload.ean}-${payload.storefront}-${success}`;
        if (deleteSeen.current.has(key)) return;
        deleteSeen.current.add(key);
        setDeleteRows((prev) => [
          { ean: payload.ean, storefront: payload.storefront, success },
          ...prev,
        ]);
        setDeleteCounts((prev) => ({
          total: prev.total + 1,
          success: prev.success + (success ? 1 : 0),
          fail: prev.fail + (success ? 0 : 1),
        }));
      } catch (error) {
        console.error(error);
      }
    };
    deleteSocketRef.current = socket;
  }

  async function handleDeleteSubmit(event) {
    event.preventDefault();
    setDeleteMessage("Uploading...");
    const file = event.target.elements.deleteFile.files[0];
    if (!file) {
      setDeleteMessage("Select a file.");
      return;
    }
    if (deleteMode === "delete") {
      deleteSeen.current.clear();
      setDeleteRows([]);
      setDeleteCounts({ total: 0, success: 0, fail: 0 });
      ensureDeleteSocket();
    }
    ensureUploadSocket();
    const formData = new FormData();
    formData.append("file", file, file.name);
    formData.append("mode", deleteMode);
    formData.append("controller", deleteController);

    try {
      const response = await apiFetch(`${API_BASE}/api/kaufland_main/`, {
        method: "POST",
        body: formData,
      });
      if (!response.ok) {
        const err = await response.json();
        throw new Error(err.error || err.message || "Request failed");
      }
      if (deleteMode === "checker") {
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = "result.xlsx";
        link.click();
        URL.revokeObjectURL(url);
        setDeleteMessage("Checker report downloaded.");
      } else {
        const data = await response.json();
        setDeleteMessage(data.message || "Completed.");
      }
    } catch (error) {
      setDeleteMessage(error.message);
    }
  }

  async function handlePriceSubmit(event) {
    event.preventDefault();
    setPriceMessage("Uploading...");
    const file = event.target.elements.priceFile.files[0];
    if (!file) {
      setPriceMessage("Select a file.");
      return;
    }
    const formData = new FormData();
    formData.append("file", file, file.name);
    formData.append("mode", "change_price");
    formData.append("controller", priceController);
    try {
      const response = await apiFetch(`${API_BASE}/api/kaufland_main/`, {
        method: "POST",
        body: formData,
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.error || data.message || "Request failed");
      }
      setPriceMessage(data.message || "Prices updated.");
    } catch (error) {
      setPriceMessage(error.message);
    }
  }

  async function handleUploadSubmit(event) {
    event.preventDefault();
    setUploadMessage("Uploading...");
    const file = event.target.elements.uploadFile.files[0];
    if (!file) {
      setUploadMessage("Select a JSON file.");
      return;
    }
    ensureUploadSocket();
    const formData = new FormData();
    formData.append("file", file, file.name);
    formData.append("mode", uploadMode);
    formData.append("controller", uploadController);
    try {
      const response = await apiFetch(`${API_BASE}/api/kaufland_main/upload_json/`, {
        method: "POST",
        body: formData,
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.error || data.message || "Upload failed");
      }
      setUploadMessage(data.message || "Upload completed.");
    } catch (error) {
      setUploadMessage(error.message);
    }
  }

  return (
    <div className="page">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">K</span>
          <div>
            <strong>Kaufland Control</strong>
            <span>Simple Ops Console</span>
          </div>
        </div>
        <div className="status-row">
          <span className={`pill ${isApproved ? "ok" : "warn"}`}>
            {isApproved ? "Approved" : "Approval needed"}
          </span>
          <span className={`pill ${isAuthed ? "ok" : "warn"}`}>
            {isAuthed ? "Authenticated" : "Signed out"}
          </span>
        </div>
      </header>

      <main className="content">
        <section className="card">
          <div className="card-head">
            <h2>Developer Approval</h2>
            {isApproved ? (
              <button className="ghost" onClick={revokeApproval} type="button">
                Remove approval
              </button>
            ) : null}
          </div>
          <p>Enter the developer approval code to unlock the console.</p>
          <form className="form" onSubmit={handleApprove}>
            <input
              type="password"
              placeholder="Approval code"
              value={approvalCode}
              onChange={(event) => setApprovalCode(event.target.value)}
              required
            />
            <button type="submit" className="primary">
              Approve
            </button>
          </form>
          <span className="message">{approvalMessage}</span>
        </section>

        <div className={isApproved ? "" : "locked"}>
          <section className="card">
            <div className="card-head">
              <h2>Authentication</h2>
              {isAuthed ? (
                <button className="ghost" onClick={handleLogout} type="button">
                  Log out
                </button>
              ) : null}
            </div>
            <form className="form" onSubmit={handleLogin}>
              <input
                type="text"
                placeholder="Username"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                required
              />
              <input
                type="password"
                placeholder="Password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
              />
              <button type="submit" className="primary">
                Sign in
              </button>
            </form>
            <span className="message">{authMessage}</span>
          </section>

          <section className="grid">
            <div className="card">
              <h3>Delete or Checker</h3>
              <form className="form" onSubmit={handleDeleteSubmit}>
                <select value={deleteController} onChange={(e) => setDeleteController(e.target.value)}>
                  <option value="xl">XL</option>
                  <option value="jv">JV</option>
                </select>
                <select value={deleteMode} onChange={(e) => setDeleteMode(e.target.value)}>
                  <option value="delete">Delete</option>
                  <option value="checker">Checker</option>
                </select>
                <input type="file" name="deleteFile" accept=".csv,.xlsx" />
                <button type="submit" className="primary">Run</button>
              </form>
              <span className="message">{deleteMessage}</span>
              <div className="counts">
                <span>Total {deleteCounts.total}</span>
                <span>Success {deleteCounts.success}</span>
                <span>Fail {deleteCounts.fail}</span>
              </div>
              <div className="table">
                {deleteRows.slice(0, 10).map((row, index) => (
                  <div className="row" key={`${row.ean}-${index}`}>
                    <span>{row.ean}</span>
                    <span>{row.storefront}</span>
                    <span>{row.success ? "Success" : "Fail"}</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="card">
              <h3>Change Price</h3>
              <form className="form" onSubmit={handlePriceSubmit}>
                <select value={priceController} onChange={(e) => setPriceController(e.target.value)}>
                  <option value="xl">XL</option>
                  <option value="jv">JV</option>
                </select>
                <input type="text" value="change_price" disabled />
                <input type="file" name="priceFile" accept=".csv,.xlsx" />
                <button type="submit" className="primary">Update</button>
              </form>
              <span className="message">{priceMessage}</span>
            </div>

            <div className="card">
              <h3>Upload JSON</h3>
              <form className="form" onSubmit={handleUploadSubmit}>
                <select value={uploadController} onChange={(e) => setUploadController(e.target.value)}>
                  <option value="xl">XL</option>
                  <option value="jv">JV</option>
                </select>
                <select value={uploadMode} onChange={(e) => setUploadMode(e.target.value)}>
                  <option value="upload_collection">Upload collection</option>
                  <option value="upload_product">Upload single product</option>
                </select>
                <input type="file" name="uploadFile" accept=".json" />
                <button type="submit" className="primary">Upload</button>
              </form>
              <span className="message">{uploadMessage}</span>
              <div className="feed">
                {uploadFeed.slice(0, 8).map((item, index) => (
                  <div className="row" key={`${item.ean}-${index}`}>
                    <span>{item.ean}</span>
                    <span>{item.stage}</span>
                    <span className="muted">{item.ts}</span>
                  </div>
                ))}
              </div>
            </div>
          </section>

          <section className="card status">
            <h3>Websocket Status</h3>
            <div className="status-grid">
              <div>
                <span>Upload</span>
                <strong>{wsStatus.upload}</strong>
              </div>
              <div>
                <span>Delete</span>
                <strong>{wsStatus.delete}</strong>
              </div>
            </div>
            <small>WS endpoints: {WS_BASE}/ws/upload-progress/ and {WS_BASE}/ws/delete-progress/</small>
          </section>
        </div>
      </main>
    </div>
  );
}
