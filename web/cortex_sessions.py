#!/usr/bin/env python3
"""
Cortex Code Session Manager
A local web UI for managing Cortex Code CLI sessions across multiple Snowflake connections.
Zero external dependencies -- Python 3.11+ stdlib only.

Usage:
    python3 cortex_sessions.py [--port PORT]
"""

import http.server
import json
import os
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tomllib
import urllib.parse
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SNOWFLAKE_DIR = Path.home() / ".snowflake"
CONNECTIONS_TOML = SNOWFLAKE_DIR / "connections.toml"
CORTEX_DIR = SNOWFLAKE_DIR / "cortex"
CONVERSATIONS_DIR = CORTEX_DIR / "conversations"
DB_PATH = CORTEX_DIR / "sessions_manager.db"
DEFAULT_PORT = 8470


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
def get_db() -> sqlite3.Connection:
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id      TEXT UNIQUE NOT NULL,
            connection_name TEXT,
            label           TEXT DEFAULT '',
            notes           TEXT DEFAULT '',
            working_dir     TEXT DEFAULT '',
            created_at      TEXT,
            last_updated    TEXT,
            preview         TEXT DEFAULT '',
            pinned          INTEGER DEFAULT 0,
            archived        INTEGER DEFAULT 0
        )
    """)
    db.commit()
    return db


# ---------------------------------------------------------------------------
# Connections parser
# ---------------------------------------------------------------------------
def load_connections() -> list[dict]:
    if not CONNECTIONS_TOML.exists():
        return []
    with open(CONNECTIONS_TOML, "rb") as f:
        data = tomllib.load(f)
    default = data.get("default_connection_name", "")
    conns = []
    for name, val in data.items():
        if name == "default_connection_name":
            continue
        if isinstance(val, dict):
            conns.append({
                "name": name,
                "account": val.get("account", ""),
                "user": val.get("user", ""),
                "authenticator": val.get("authenticator", ""),
                "is_default": name == default,
            })
    conns.sort(key=lambda c: (not c["is_default"], c["name"].lower()))
    return conns


# ---------------------------------------------------------------------------
# Conversation scanner
# ---------------------------------------------------------------------------
def extract_preview(session_id: str) -> str:
    """Get the first real user message from a conversation history file."""
    history_file = CONVERSATIONS_DIR / f"{session_id}.history.jsonl"
    if not history_file.exists():
        return ""
    try:
        with open(history_file, encoding="utf-8") as f:
            for line in f:
                entry = json.loads(line)
                if entry.get("role") != "user":
                    continue
                content = entry.get("content", "")
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            text = block.get("text", "").strip()
                            if text and not text.startswith("<system-reminder"):
                                return text[:200]
                elif isinstance(content, str):
                    text = content.strip()
                    if text and not text.startswith("<system-reminder"):
                        return text[:200]
    except Exception as e:
        print(f"Error reading history file {history_file}: {e}")
    return ""


def scan_conversations(db: sqlite3.Connection) -> int:
    """Discover sessions from Cortex conversation files. Returns count of new sessions added."""
    if not CONVERSATIONS_DIR.exists():
        return 0
    added = 0
    for path in CONVERSATIONS_DIR.glob("*.json"):
        if path.name.endswith(".history.jsonl"):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                meta = json.load(f)
        except Exception as e:
            print(f"Error reading meta file {path}: {e}")
            continue
        sid = meta.get("session_id", path.stem)
        existing = db.execute("SELECT id FROM sessions WHERE session_id = ?", (sid,)).fetchone()
        if existing:
          db.execute(
              """UPDATE sessions SET
                last_updated = COALESCE(?, last_updated),
                connection_name = COALESCE(?, connection_name),
                working_dir = COALESCE(?, working_dir)
                WHERE session_id = ?""",
              (
                  meta.get("last_updated"),
                  meta.get("connection_name"),
                  meta.get("working_directory"),
                  sid,
              ),
          )
          continue
        preview = extract_preview(sid)
        title = meta.get("title", "")
        # Use title as label if it's not the generic auto-generated one
        label = ""
        if title and not title.startswith("Chat for session:"):
            label = title
        db.execute(
            """INSERT INTO sessions (session_id, connection_name, label, working_dir,
               created_at, last_updated, preview) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                sid,
                meta.get("connection_name", ""),
                label,
                meta.get("working_directory", ""),
                meta.get("created_at", ""),
                meta.get("last_updated", ""),
                preview,
            ),
        )
        added += 1
    db.commit()
    return added


# ---------------------------------------------------------------------------
# Terminal launcher (cross-platform)
# ---------------------------------------------------------------------------
def launch_cortex_in_terminal(args: list[str]) -> None:
    """Open a new terminal window running a cortex command."""
    cortex_path = shutil.which("cortex") or "cortex"
    cmd_str = f"{cortex_path} {' '.join(shlex.quote(a) for a in args)}"

    if sys.platform == "darwin":
        import tempfile
        script_path = Path(tempfile.mktemp(suffix=".command"))
        script_path.write_text(f"#!/bin/bash\n{cmd_str}\n")
        script_path.chmod(0o755)
        subprocess.Popen(["open", "-a", "Terminal", str(script_path)])
    elif sys.platform == "win32":
        subprocess.Popen(["cmd", "/c", "start", "cmd", "/k", cmd_str])
    else:
        # Linux/BSD — try common terminal emulators
        for term_cmd in [
            ["gnome-terminal", "--", "bash", "-c", cmd_str],
            ["xfce4-terminal", "-e", cmd_str],
            ["konsole", "-e", "bash", "-c", cmd_str],
            ["xterm", "-e", cmd_str],
        ]:
            if shutil.which(term_cmd[0]):
                subprocess.Popen(term_cmd)
                return
        # Fallback: run in background (no interactive terminal)
        subprocess.Popen(["bash", "-c", cmd_str])


# ---------------------------------------------------------------------------
# HTML Template
# ---------------------------------------------------------------------------
HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Cortex Code Session Manager</title>
<style>
  :root {
    --bg: #0d1117; --surface: #161b22; --surface2: #21262d;
    --border: #30363d; --text: #e6edf3; --text2: #8b949e;
    --accent: #29b5f6; --accent-hover: #58c9f8; --danger: #f85149;
    --success: #3fb950; --warning: #d29922;
    --font: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Segoe UI', sans-serif;
    --mono: 'SF Mono', 'Fira Code', 'JetBrains Mono', monospace;
    --user-bg: #1c2533; --assistant-bg: transparent;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: var(--font); background: var(--bg); color: var(--text); height: 100vh; overflow: hidden; }

  /* ---- Full-page layout ---- */
  .app { display: flex; height: 100vh; }

  /* ---- Left sidebar ---- */
  .sidebar {
    width: 280px; min-width: 280px; background: var(--surface);
    border-right: 1px solid var(--border); display: flex; flex-direction: column;
    overflow: hidden;
  }
  .sidebar-header {
    padding: 14px 16px; border-bottom: 1px solid var(--border);
    display: flex; align-items: center; gap: 10px;
  }
  .sidebar-header .logo { color: var(--accent); font-family: var(--mono); font-size: 16px; font-weight: 700; }
  .sidebar-header .title { font-size: 13px; font-weight: 600; }
  .sidebar-actions { padding: 10px 12px; display: flex; gap: 6px; }
  .sidebar-actions .btn { flex: 1; text-align: center; font-size: 12px; padding: 7px 0; }
  .sidebar-search {
    margin: 0 12px 8px; padding: 7px 10px; border-radius: 6px;
    border: 1px solid var(--border); background: var(--surface2);
    color: var(--text); font-size: 12px; width: calc(100% - 24px);
  }
  .sidebar-search:focus { outline: none; border-color: var(--accent); }

  .session-list { flex: 1; overflow-y: auto; padding: 0 8px 12px; }
  .session-group-label {
    font-size: 11px; text-transform: uppercase; color: var(--text2);
    letter-spacing: 0.5px; padding: 12px 8px 4px; font-weight: 600;
  }
  .session-item {
    padding: 10px 12px; border-radius: 8px; cursor: pointer;
    margin-bottom: 2px; border: 1px solid transparent; transition: all 0.12s;
    position: relative;
  }
  .session-item:hover { background: var(--surface2); }
  .session-item.active { background: var(--surface2); border-color: var(--accent); }
  .session-item.pinned::before {
    content: ''; position: absolute; left: 0; top: 8px; bottom: 8px;
    width: 3px; border-radius: 2px; background: var(--warning);
  }
  .session-item .si-title {
    font-size: 13px; font-weight: 500; white-space: nowrap;
    overflow: hidden; text-overflow: ellipsis;
  }
  .session-item .si-preview {
    font-size: 11px; color: var(--text2); margin-top: 2px;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .session-item .si-meta {
    font-size: 10px; color: var(--text2); margin-top: 3px;
    display: flex; gap: 8px; align-items: center;
  }
  .session-item .si-conn {
    font-family: var(--mono); font-size: 10px; padding: 1px 5px;
    background: var(--surface); border-radius: 3px; border: 1px solid var(--border);
  }

  /* Connections panel (collapsible) */
  .conn-panel { border-top: 1px solid var(--border); }
  .conn-toggle {
    display: flex; align-items: center; justify-content: space-between;
    padding: 10px 16px; cursor: pointer; font-size: 11px;
    text-transform: uppercase; color: var(--text2); letter-spacing: 0.5px;
    font-weight: 600; user-select: none;
  }
  .conn-toggle:hover { color: var(--text); }
  .conn-toggle .arrow { transition: transform 0.15s; font-size: 10px; }
  .conn-toggle .arrow.open { transform: rotate(90deg); }
  .conn-body { display: none; padding: 0 12px 10px; max-height: 200px; overflow-y: auto; }
  .conn-body.open { display: block; }
  .conn-chip {
    display: inline-block; padding: 3px 8px; border-radius: 4px; font-size: 10px;
    font-family: var(--mono); background: var(--surface2); border: 1px solid var(--border);
    margin: 2px 3px 2px 0; cursor: default;
  }
  .conn-chip.default { border-color: var(--accent); color: var(--accent); }

  /* ---- Main chat area ---- */
  .chat-area { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
  .chat-header {
    padding: 12px 20px; border-bottom: 1px solid var(--border);
    display: flex; align-items: center; justify-content: space-between;
    background: var(--surface); min-height: 54px;
  }
  .chat-header-left { display: flex; align-items: center; gap: 12px; min-width: 0; }
  .chat-header-left .ch-title {
    font-size: 15px; font-weight: 600; white-space: nowrap;
    overflow: hidden; text-overflow: ellipsis;
  }
  .chat-header-left .ch-conn {
    font-family: var(--mono); font-size: 11px; padding: 2px 8px;
    background: var(--surface2); border-radius: 4px; border: 1px solid var(--border);
    white-space: nowrap;
  }
  .chat-header-left .ch-dir {
    font-size: 11px; color: var(--text2); white-space: nowrap;
    overflow: hidden; text-overflow: ellipsis;
  }
  .chat-header-actions { display: flex; gap: 6px; flex-shrink: 0; }

  /* Messages */
  .chat-messages {
    flex: 1; overflow-y: auto; padding: 20px 0;
    scroll-behavior: smooth;
  }
  .msg {
    padding: 14px 24px; max-width: 820px; margin: 0 auto; width: 100%;
  }
  .msg.user { background: var(--user-bg); border-radius: 12px; margin-bottom: 4px; max-width: 780px; margin-left: auto; margin-right: auto; }
  .msg.assistant { margin-bottom: 4px; }
  .msg-role {
    font-size: 11px; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.5px; margin-bottom: 6px;
  }
  .msg-role.user { color: var(--accent); }
  .msg-role.assistant { color: var(--success); }
  .msg-body { font-size: 14px; line-height: 1.65; word-wrap: break-word; }
  .msg-body p { margin-bottom: 10px; }
  .msg-body p:last-child { margin-bottom: 0; }

  /* Markdown rendering */
  .msg-body h1, .msg-body h2, .msg-body h3, .msg-body h4 { margin: 16px 0 8px; font-weight: 600; }
  .msg-body h1 { font-size: 20px; }
  .msg-body h2 { font-size: 17px; }
  .msg-body h3 { font-size: 15px; }
  .msg-body code {
    font-family: var(--mono); font-size: 12px; padding: 2px 6px;
    background: var(--surface2); border-radius: 4px; border: 1px solid var(--border);
  }
  .msg-body pre {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 8px; padding: 14px 16px; margin: 10px 0;
    overflow-x: auto; position: relative;
  }
  .msg-body pre code {
    padding: 0; background: none; border: none; font-size: 12px;
    line-height: 1.5; display: block; white-space: pre;
  }
  .msg-body pre .lang-tag {
    position: absolute; top: 6px; right: 10px; font-size: 10px;
    color: var(--text2); font-family: var(--mono); text-transform: uppercase;
  }
  .msg-body ul, .msg-body ol { margin: 8px 0; padding-left: 24px; }
  .msg-body li { margin-bottom: 4px; }
  .msg-body strong { font-weight: 600; }
  .msg-body em { font-style: italic; }
  .msg-body a { color: var(--accent); text-decoration: none; }
  .msg-body a:hover { text-decoration: underline; }
  .msg-body blockquote {
    border-left: 3px solid var(--border); padding-left: 12px;
    color: var(--text2); margin: 10px 0;
  }
  .msg-body hr { border: none; border-top: 1px solid var(--border); margin: 16px 0; }

  /* Tool call chips */
  .tool-chips { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 8px; }
  .tool-chip {
    font-size: 10px; font-family: var(--mono); padding: 3px 8px;
    background: var(--surface2); border: 1px solid var(--border);
    border-radius: 4px; color: var(--text2);
  }

  /* Welcome / empty state */
  .welcome {
    flex: 1; display: flex; align-items: center; justify-content: center;
    text-align: center; color: var(--text2); padding: 40px;
  }
  .welcome .logo-big { font-size: 48px; font-family: var(--mono); color: var(--accent); margin-bottom: 16px; }
  .welcome h2 { font-size: 20px; color: var(--text); margin-bottom: 8px; }
  .welcome p { font-size: 14px; max-width: 400px; margin: 0 auto; line-height: 1.5; }



  /* Loading spinner */
  .loading { text-align: center; padding: 40px; color: var(--text2); }
  .loading::after {
    content: ''; display: inline-block; width: 20px; height: 20px;
    border: 2px solid var(--border); border-top-color: var(--accent);
    border-radius: 50%; animation: spin 0.6s linear infinite;
    vertical-align: middle; margin-left: 8px;
  }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* Buttons */
  .btn {
    padding: 7px 14px; border-radius: 6px; border: 1px solid var(--border);
    background: var(--surface2); color: var(--text); cursor: pointer;
    font-size: 12px; font-weight: 500; transition: all 0.15s; white-space: nowrap;
  }
  .btn:hover { border-color: var(--accent); color: var(--accent); }
  .btn-primary { background: var(--accent); color: #000; border-color: var(--accent); font-weight: 600; }
  .btn-primary:hover { background: var(--accent-hover); }
  .btn-sm { padding: 4px 10px; font-size: 11px; }
  .btn-danger { color: var(--danger); }
  .btn-danger:hover { border-color: var(--danger); background: rgba(248,81,73,0.1); }
  .btn-icon { padding: 5px 8px; font-size: 14px; line-height: 1; }

  /* Modal */
  .modal-overlay {
    display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.6);
    z-index: 100; align-items: center; justify-content: center;
  }
  .modal-overlay.active { display: flex; }
  .modal {
    background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
    padding: 24px; width: 480px; max-width: 90vw;
  }
  .modal h3 { font-size: 16px; margin-bottom: 16px; }
  .form-group { margin-bottom: 14px; }
  .form-group label { display: block; font-size: 12px; color: var(--text2); margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.3px; }
  .form-group input, .form-group select, .form-group textarea {
    width: 100%; padding: 8px 12px; border-radius: 6px; border: 1px solid var(--border);
    background: var(--surface2); color: var(--text); font-size: 13px; font-family: var(--font);
  }
  .form-group input:focus, .form-group select:focus, .form-group textarea:focus { outline: none; border-color: var(--accent); }
  .form-group select { cursor: pointer; }
  .form-group textarea { resize: vertical; min-height: 60px; }
  .modal-actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 20px; }

  /* Toast */
  .toast {
    position: fixed; bottom: 20px; right: 20px; padding: 12px 20px; border-radius: 8px;
    background: var(--surface2); border: 1px solid var(--border); font-size: 13px;
    z-index: 200; opacity: 0; transition: opacity 0.3s; pointer-events: none;
  }
  .toast.show { opacity: 1; }
  .toast.success { border-color: var(--success); }
  .toast.error { border-color: var(--danger); }

  /* Scrollbar */
  ::-webkit-scrollbar { width: 6px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: var(--surface2); border-radius: 3px; }
  ::-webkit-scrollbar-thumb:hover { background: var(--border); }
</style>
</head>
<body>

<div class="app">
  <!-- Left sidebar -->
  <div class="sidebar">
    <div class="sidebar-header">
      <span class="logo">&gt;_</span>
      <span class="title">Cortex Sessions</span>
    </div>
    <div class="sidebar-actions">
      <button class="btn btn-primary" onclick="openNewModal()">+ New</button>
      <button class="btn" onclick="openImportModal()">Import</button>
    </div>
    <input type="text" class="sidebar-search" placeholder="Search sessions..." oninput="filterSessions(this.value)" />
    <div class="session-list" id="session-list"></div>
    <div class="conn-panel">
      <div class="conn-toggle" onclick="toggleConnPanel()">
        <span>Connections (<span id="conn-count">0</span>)</span>
        <span class="arrow" id="conn-arrow">&#9654;</span>
      </div>
      <div class="conn-body" id="conn-body"></div>
    </div>
  </div>

  <!-- Main chat area -->
  <div class="chat-area">
    <div class="chat-header" id="chat-header" style="display:none">
      <div class="chat-header-left">
        <span class="ch-title" id="ch-title"></span>
        <span class="ch-conn" id="ch-conn"></span>
        <span class="ch-dir" id="ch-dir"></span>
      </div>
      <div class="chat-header-actions">
        <button class="btn btn-sm" onclick="openEditModal(activeSession)" title="Edit">Edit</button>
        <button class="btn btn-sm btn-primary" onclick="resumeSession(activeSession)">Resume in Terminal</button>
        <button class="btn btn-sm btn-danger" onclick="deleteSession(activeSession)" title="Delete">Del</button>
      </div>
    </div>

    <div class="chat-messages" id="chat-messages" style="display:none"></div>



    <div class="welcome" id="welcome">
      <div>
        <div class="logo-big">&gt;_</div>
        <h2>Cortex Code Session Manager</h2>
        <p>Select a conversation from the sidebar to view its history, or start a new session.</p>
      </div>
    </div>
  </div>
</div>

<!-- New Session Modal -->
<div class="modal-overlay" id="new-modal">
  <div class="modal">
    <h3>New Session</h3>
    <div class="form-group">
      <label>Connection</label>
      <select id="new-conn"></select>
    </div>
    <div class="form-group">
      <label>Label (optional)</label>
      <input type="text" id="new-label" placeholder="e.g. Pipeline Refactor" />
    </div>
    <div class="form-group">
      <label>Working Directory (optional)</label>
      <input type="text" id="new-workdir" placeholder="/Users/you/Projects/..." />
    </div>
    <div class="modal-actions">
      <button class="btn" onclick="closeModals()">Cancel</button>
      <button class="btn btn-primary" onclick="createSession()">Launch</button>
    </div>
  </div>
</div>

<!-- Import Session Modal -->
<div class="modal-overlay" id="import-modal">
  <div class="modal">
    <h3>Import Session</h3>
    <div class="form-group">
      <label>Session ID</label>
      <input type="text" id="import-sid" placeholder="e.g. 0cf55027-4669-42e0-ba03-27b3f6922652" />
    </div>
    <div class="form-group">
      <label>Connection (override, optional)</label>
      <select id="import-conn"><option value="">Auto-detect from session</option></select>
    </div>
    <div class="form-group">
      <label>Label (optional)</label>
      <input type="text" id="import-label" />
    </div>
    <div class="modal-actions">
      <button class="btn" onclick="closeModals()">Cancel</button>
      <button class="btn btn-primary" onclick="importSession()">Import</button>
    </div>
  </div>
</div>

<!-- Edit Session Modal -->
<div class="modal-overlay" id="edit-modal">
  <div class="modal">
    <h3>Edit Session</h3>
    <input type="hidden" id="edit-id" />
    <div class="form-group">
      <label>Label</label>
      <input type="text" id="edit-label" />
    </div>
    <div class="form-group">
      <label>Notes</label>
      <textarea id="edit-notes"></textarea>
    </div>
    <div class="form-group">
      <label>Connection</label>
      <select id="edit-conn"></select>
    </div>
    <div class="modal-actions">
      <button class="btn" onclick="closeModals()">Cancel</button>
      <button class="btn btn-primary" onclick="saveEdit()">Save</button>
    </div>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
let sessions = [];
let connections = [];
let activeSession = null; // db id of selected session
let searchFilter = '';
let msgCache = {};

// ---- API helper ----
async function api(path, method = 'GET', body = null) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch('/api' + path, opts);
  return res.json();
}

// ---- Toast ----
function toast(msg, type = 'success') {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = 'toast show ' + type;
  setTimeout(() => el.className = 'toast', 2500);
}

// ---- Utils ----
function escapeHtml(s) {
  if (!s) return '';
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function relativeTime(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  const now = new Date();
  const diff = (now - d) / 1000;
  if (diff < 60) return 'just now';
  if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
  if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
  if (diff < 604800) return Math.floor(diff / 86400) + 'd ago';
  return d.toLocaleDateString();
}

function shortDir(dir) {
  if (!dir) return '';
  return dir.replace(/^\/Users\/[^/]+\//, '~/');
}

function dateGroup(iso) {
  if (!iso) return 'Older';
  const d = new Date(iso);
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today); yesterday.setDate(yesterday.getDate() - 1);
  const weekAgo = new Date(today); weekAgo.setDate(weekAgo.getDate() - 7);
  if (d >= today) return 'Today';
  if (d >= yesterday) return 'Yesterday';
  if (d >= weekAgo) return 'This Week';
  return 'Older';
}

// ---- Markdown renderer ----
function renderMarkdown(text) {
  if (!text) return '';
  let html = escapeHtml(text);

  // Code blocks: ```lang\n...\n```
  html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) => {
    const langTag = lang ? `<span class="lang-tag">${lang}</span>` : '';
    return `<pre>${langTag}<code>${code}</code></pre>`;
  });

  // Inline code
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

  // Headers
  html = html.replace(/^#### (.+)$/gm, '<h4>$1</h4>');
  html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
  html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
  html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');

  // Bold / italic
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');

  // Horizontal rule
  html = html.replace(/^---$/gm, '<hr>');

  // Blockquotes
  html = html.replace(/^&gt; (.+)$/gm, '<blockquote>$1</blockquote>');

  // Unordered lists
  html = html.replace(/^- (.+)$/gm, '<li>$1</li>');
  html = html.replace(/((?:<li>.*<\/li>\n?)+)/g, '<ul>$1</ul>');

  // Ordered lists
  html = html.replace(/^\d+\. (.+)$/gm, '<li>$1</li>');

  // Links
  html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');

  // Paragraphs: split on double newlines
  html = html.split(/\n\n+/).map(block => {
    block = block.trim();
    if (!block) return '';
    // Don't wrap blocks that are already block-level elements
    if (/^<(h[1-4]|pre|ul|ol|li|blockquote|hr)/.test(block)) return block;
    // Wrap remaining text in <p>, converting single newlines to <br>
    return '<p>' + block.replace(/\n/g, '<br>') + '</p>';
  }).join('\n');

  return html;
}

// ---- Connections panel ----
function renderConnections() {
  document.getElementById('conn-count').textContent = connections.length;
  const body = document.getElementById('conn-body');
  body.innerHTML = connections.map(c =>
    `<span class="conn-chip ${c.is_default ? 'default' : ''}" title="${escapeHtml(c.account)} / ${escapeHtml(c.user)}">${escapeHtml(c.name)}</span>`
  ).join('');
}

function toggleConnPanel() {
  const body = document.getElementById('conn-body');
  const arrow = document.getElementById('conn-arrow');
  body.classList.toggle('open');
  arrow.classList.toggle('open');
}

function populateConnSelect(selectId, selected = '') {
  const sel = document.getElementById(selectId);
  const existingFirst = sel.querySelector('option[value=""]');
  sel.innerHTML = existingFirst ? existingFirst.outerHTML : '';
  connections.forEach(c => {
    const opt = document.createElement('option');
    opt.value = c.name;
    opt.textContent = `${c.name} (${c.account})`;
    if (c.name === selected) opt.selected = true;
    sel.appendChild(opt);
  });
}

// ---- Session list (sidebar) ----
function renderSessionList() {
  let list = [...sessions];

  if (searchFilter) {
    const q = searchFilter.toLowerCase();
    list = list.filter(s =>
      (s.label || '').toLowerCase().includes(q) ||
      (s.connection_name || '').toLowerCase().includes(q) ||
      (s.preview || '').toLowerCase().includes(q) ||
      (s.session_id || '').toLowerCase().includes(q) ||
      (s.working_dir || '').toLowerCase().includes(q) ||
      (s.notes || '').toLowerCase().includes(q)
    );
  }

  // Group: pinned first, then by date group
  const pinned = list.filter(s => s.pinned);
  const unpinned = list.filter(s => !s.pinned);

  const groups = {};
  unpinned.forEach(s => {
    const g = dateGroup(s.last_updated);
    if (!groups[g]) groups[g] = [];
    groups[g].push(s);
  });

  const container = document.getElementById('session-list');
  let html = '';

  if (pinned.length) {
    html += `<div class="session-group-label">Pinned</div>`;
    pinned.forEach(s => { html += sessionItemHtml(s); });
  }

  ['Today', 'Yesterday', 'This Week', 'Older'].forEach(g => {
    if (groups[g] && groups[g].length) {
      html += `<div class="session-group-label">${g}</div>`;
      groups[g].forEach(s => { html += sessionItemHtml(s); });
    }
  });

  if (!list.length) {
    html = '<div style="padding:20px;text-align:center;color:var(--text2);font-size:13px">No sessions found</div>';
  }

  container.innerHTML = html;
}

function sessionItemHtml(s) {
  const title = escapeHtml(s.label || s.preview || 'Untitled session');
  const preview = s.label ? escapeHtml((s.preview || '').substring(0, 80)) : '';
  const isActive = activeSession === s.id;
  return `<div class="session-item ${isActive ? 'active' : ''} ${s.pinned ? 'pinned' : ''}"
    onclick="selectSession(${s.id})" oncontextmenu="sessionContextMenu(event, ${s.id})">
    <div class="si-title">${title}</div>
    ${preview ? `<div class="si-preview">${preview}</div>` : ''}
    <div class="si-meta">
      ${s.connection_name ? `<span class="si-conn">${escapeHtml(s.connection_name)}</span>` : ''}
      <span>${relativeTime(s.last_updated)}</span>
    </div>
  </div>`;
}

function filterSessions(q) {
  searchFilter = q;
  renderSessionList();
}

// ---- Select & load messages ----
async function selectSession(id) {
  activeSession = id;
  renderSessionList(); // highlight active

  const s = sessions.find(s => s.id === id);
  if (!s) return;

  // Update header
  document.getElementById('chat-header').style.display = 'flex';
  document.getElementById('ch-title').textContent = s.label || 'Untitled session';
  document.getElementById('ch-conn').textContent = s.connection_name || '';
  document.getElementById('ch-dir').textContent = shortDir(s.working_dir);

  // Show messages area, hide welcome
  document.getElementById('welcome').style.display = 'none';
  const msgEl = document.getElementById('chat-messages');
  msgEl.style.display = 'block';

  // Check cache
  if (msgCache[id]) {
    renderMessages(msgCache[id]);
    return;
  }

  msgEl.innerHTML = '<div class="loading">Loading conversation</div>';

  try {
    const msgs = await api(`/sessions/${id}/messages`);
    msgCache[id] = msgs;
    renderMessages(msgs);
  } catch (e) {
    msgEl.innerHTML = '<div class="loading" style="color:var(--danger)">Failed to load messages</div>';
  }
}

function renderMessages(msgs) {
  const el = document.getElementById('chat-messages');
  if (!msgs.length) {
    el.innerHTML = '<div style="text-align:center;padding:40px;color:var(--text2)">No messages in this conversation yet.</div>';
    return;
  }

  el.innerHTML = msgs.map(m => {
    const roleLabel = m.role === 'user' ? 'You' : 'Cortex';
    let body = renderMarkdown(m.text);
    let tools = '';
    if (m.tools && m.tools.length) {
      tools = '<div class="tool-chips">' +
        m.tools.map(t => `<span class="tool-chip">${escapeHtml(t)}</span>`).join('') +
        '</div>';
    }
    return `<div class="msg ${m.role}">
      <div class="msg-role ${m.role}">${roleLabel}</div>
      <div class="msg-body">${body}</div>
      ${tools}
    </div>`;
  }).join('');

  // Scroll to bottom
  el.scrollTop = el.scrollHeight;
}

// ---- Session context menu (right click) ----
function sessionContextMenu(e, id) {
  e.preventDefault();
  // For now, toggle pin on right-click
  togglePin(id);
}

// ---- Modals ----
function closeModals() {
  document.querySelectorAll('.modal-overlay').forEach(m => m.classList.remove('active'));
}

function openNewModal() {
  populateConnSelect('new-conn', connections.find(c => c.is_default)?.name || '');
  document.getElementById('new-label').value = '';
  document.getElementById('new-workdir').value = '';
  document.getElementById('new-modal').classList.add('active');
}

function openImportModal() {
  populateConnSelect('import-conn');
  document.getElementById('import-sid').value = '';
  document.getElementById('import-label').value = '';
  document.getElementById('import-modal').classList.add('active');
}

function openEditModal(id) {
  const s = sessions.find(s => s.id === id);
  if (!s) return;
  document.getElementById('edit-id').value = id;
  document.getElementById('edit-label').value = s.label || '';
  document.getElementById('edit-notes').value = s.notes || '';
  populateConnSelect('edit-conn', s.connection_name || '');
  document.getElementById('edit-modal').classList.add('active');
}

// ---- Actions ----
async function createSession() {
  const conn = document.getElementById('new-conn').value;
  const label = document.getElementById('new-label').value.trim();
  const workdir = document.getElementById('new-workdir').value.trim();
  if (!conn) { toast('Select a connection', 'error'); return; }
  const res = await api('/sessions/new', 'POST', { connection: conn, label, working_dir: workdir });
  if (res.error) { toast(res.error, 'error'); return; }
  toast('Session launched in new terminal');
  closeModals();
  await loadSessions();
}

async function importSession() {
  const sid = document.getElementById('import-sid').value.trim();
  const conn = document.getElementById('import-conn').value;
  const label = document.getElementById('import-label').value.trim();
  if (!sid) { toast('Enter a session ID', 'error'); return; }
  const res = await api('/sessions/import', 'POST', { session_id: sid, connection: conn, label });
  if (res.error) { toast(res.error, 'error'); return; }
  toast('Session imported');
  closeModals();
  await loadSessions();
}

async function resumeSession(id) {
  const res = await api(`/sessions/${id}/resume`, 'POST', {});
  if (res.error) { toast(res.error, 'error'); return; }
  toast('Resumed in new terminal');
}

async function saveEdit() {
  const id = document.getElementById('edit-id').value;
  const label = document.getElementById('edit-label').value.trim();
  const notes = document.getElementById('edit-notes').value.trim();
  const conn = document.getElementById('edit-conn').value;
  const res = await api(`/sessions/${id}/update`, 'POST', { label, notes, connection_name: conn });
  if (res.error) { toast(res.error, 'error'); return; }
  toast('Session updated');
  closeModals();
  await loadSessions();
  // Refresh header if editing active session
  if (parseInt(id) === activeSession) {
    const s = sessions.find(s => s.id === activeSession);
    if (s) {
      document.getElementById('ch-title').textContent = s.label || 'Untitled session';
      document.getElementById('ch-conn').textContent = s.connection_name || '';
    }
  }
}

async function deleteSession(id) {
  if (!confirm('Remove this session from the manager?\n(The Cortex session itself is not deleted.)')) return;
  const res = await api(`/sessions/${id}/delete`, 'POST');
  if (res.error) { toast(res.error, 'error'); return; }
  toast('Session removed');
  if (activeSession === id) {
    activeSession = null;
    document.getElementById('chat-header').style.display = 'none';
    document.getElementById('chat-messages').style.display = 'none';
    document.getElementById('welcome').style.display = 'flex';
  }
  delete msgCache[id];
  await loadSessions();
}

async function togglePin(id) {
  const s = sessions.find(s => s.id === id);
  if (!s) return;
  await api(`/sessions/${id}/update`, 'POST', { pinned: s.pinned ? 0 : 1 });
  await loadSessions();
}

// ---- Load sessions ----
async function loadSessions() {
  sessions = await api('/sessions');
  renderSessionList();
}

// ---- Init ----
async function init() {
  connections = await api('/connections');
  renderConnections();
  await loadSessions();
}

// Close modals on escape / overlay click
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModals(); });
document.querySelectorAll('.modal-overlay').forEach(el => {
  el.addEventListener('click', e => { if (e.target === el) closeModals(); });
});

init();
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# HTTP Handler
# ---------------------------------------------------------------------------
class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Suppress default logging noise
        pass

    def _json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, html, status=200):
        body = html.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length))

    # --- Routes ---
    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path

        if path == "/":
            return self._html(HTML_PAGE)

        if path == "/api/connections":
            return self._json(load_connections())

        if path == "/api/sessions":
            db = get_db()
            scan_conversations(db)
            rows = db.execute(
                "SELECT * FROM sessions WHERE archived = 0 ORDER BY pinned DESC, last_updated DESC"
            ).fetchall()
            return self._json([dict(r) for r in rows])

        # GET /api/sessions/<id>/messages
        m = re.match(r"^/api/sessions/(\d+)/messages$", path)
        if m:
            return self._handle_messages(int(m.group(1)))

        self.send_error(404)

    def _handle_messages(self, db_id: int):
        db = get_db()
        row = db.execute("SELECT * FROM sessions WHERE id = ?", (db_id,)).fetchone()
        if not row:
            return self._json({"error": "Session not found"}, 404)

        sid = row["session_id"]
        history_file = CONVERSATIONS_DIR / f"{sid}.history.jsonl"
        if not history_file.exists():
            return self._json([])

        messages = []
        try:
            with open(history_file, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    role = entry.get("role", "")
                    content = entry.get("content", "")

                    texts = []
                    tool_calls = []

                    if isinstance(content, list):
                        for block in content:
                            if not isinstance(block, dict):
                                continue
                            btype = block.get("type", "")
                            if btype == "text":
                                text = block.get("text", "").strip()
                                # Skip system reminders
                                if text.startswith("<system-reminder"):
                                    continue
                                # Strip inline system reminders
                                text = re.sub(
                                    r"<system-reminder>.*?</system-reminder>",
                                    "", text, flags=re.DOTALL
                                ).strip()
                                if text:
                                    texts.append(text)
                            elif btype == "tool_use":
                                name = block.get("name", "unknown_tool")
                                if name:
                                    tool_calls.append(name)
                            # Skip tool_result blocks entirely
                    elif isinstance(content, str):
                        text = content.strip()
                        if text and not text.startswith("<system-reminder"):
                            text = re.sub(
                                r"<system-reminder>.*?</system-reminder>",
                                "", text, flags=re.DOTALL
                            ).strip()
                            if text:
                                texts.append(text)

                    # Only include entries that have visible content
                    if texts or (role == "assistant" and tool_calls):
                        messages.append({
                            "role": role,
                            "text": "\n\n".join(texts),
                            "tools": tool_calls,
                        })
        except Exception as e:
            print(f"Error reading history file {history_file}: {e}")

        # Limit to last 200 messages for very long conversations
        if len(messages) > 200:
            messages = messages[-200:]

        return self._json(messages)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path

        if path == "/api/sessions/new":
            return self._handle_new()

        if path == "/api/sessions/import":
            return self._handle_import()

        m = re.match(r"^/api/sessions/(\d+)/(\w+)$", path)
        if m:
            session_db_id = int(m.group(1))
            action = m.group(2)
            if action == "resume":
                return self._handle_resume(session_db_id)
            if action == "update":
                return self._handle_update(session_db_id)
            if action == "delete":
                return self._handle_delete(session_db_id)

        self.send_error(404)

    def _handle_new(self):
        body = self._read_body()
        conn = body.get("connection", "")
        label = body.get("label", "")
        workdir = body.get("working_dir", "")

        if not conn:
            return self._json({"error": "Connection is required"}, 400)

        args = ["-c", conn]
        if workdir:
            args += ["-w", workdir]

        launch_cortex_in_terminal(args)

        # We can't know the session ID yet -- it gets created when cortex starts.
        # The next scan_conversations() call will pick it up.
        # But we do a scan now to catch any just-created ones.
        db = get_db()
        scan_conversations(db)

        return self._json({"ok": True})

    def _handle_import(self):
        body = self._read_body()
        sid = body.get("session_id", "").strip()
        conn_override = body.get("connection", "")
        label = body.get("label", "")

        if not sid:
            return self._json({"error": "Session ID is required"}, 400)

        db = get_db()
        existing = db.execute("SELECT id FROM sessions WHERE session_id = ?", (sid,)).fetchone()
        if existing:
            return self._json({"error": "Session already exists in manager"}, 400)

        # Try to read metadata from Cortex conversation files
        meta_file = CONVERSATIONS_DIR / f"{sid}.json"
        meta = {}
        if meta_file.exists():
            try:
                with open(meta_file, encoding="utf-8") as f:
                    meta = json.load(f)
            except Exception as e:
                print(f"Error reading meta file {meta_file}: {e}")

        connection_name = conn_override or meta.get("connection_name", "")
        preview = extract_preview(sid)
        created = meta.get("created_at", datetime.now(timezone.utc).isoformat())
        updated = meta.get("last_updated", created)
        workdir = meta.get("working_directory", "")

        if not label and meta.get("title", ""):
            t = meta["title"]
            if not t.startswith("Chat for session:"):
                label = t

        db.execute(
            """INSERT INTO sessions (session_id, connection_name, label, working_dir,
               created_at, last_updated, preview) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (sid, connection_name, label, workdir, created, updated, preview),
        )
        db.commit()
        return self._json({"ok": True})

    def _handle_resume(self, db_id: int):
        db = get_db()
        row = db.execute("SELECT * FROM sessions WHERE id = ?", (db_id,)).fetchone()
        if not row:
            return self._json({"error": "Session not found"}, 404)

        args = ["-r", row["session_id"]]
        if row["connection_name"]:
            args += ["-c", row["connection_name"]]
        if row["working_dir"]:
            args += ["-w", row["working_dir"]]

        launch_cortex_in_terminal(args)

        db.execute(
            "UPDATE sessions SET last_updated = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), db_id),
        )
        db.commit()
        return self._json({"ok": True})

    def _handle_update(self, db_id: int):
        body = self._read_body()
        db = get_db()
        row = db.execute("SELECT * FROM sessions WHERE id = ?", (db_id,)).fetchone()
        if not row:
            return self._json({"error": "Session not found"}, 404)

        updates = []
        params = []
        for field in ("label", "notes", "connection_name"):
            if field in body:
                updates.append(f"{field} = ?")
                params.append(body[field])
        if "pinned" in body:
            updates.append("pinned = ?")
            params.append(int(body["pinned"]))

        if updates:
            params.append(db_id)
            db.execute(f"UPDATE sessions SET {', '.join(updates)} WHERE id = ?", params)
            db.commit()
        return self._json({"ok": True})

    def _handle_delete(self, db_id: int):
        db = get_db()
        db.execute("DELETE FROM sessions WHERE id = ?", (db_id,))
        db.commit()
        return self._json({"ok": True})


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    port = DEFAULT_PORT
    if "--port" in sys.argv:
        idx = sys.argv.index("--port")
        if idx + 1 < len(sys.argv):
            port = int(sys.argv[idx + 1])

    # Ensure DB directory exists
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Init DB and do initial scan
    db = get_db()
    # db.execute("DELETE FROM sessions")
    # db.commit()
    added = scan_conversations(db)
    db.close()

    # If the default port is busy, try the next few ports
    server = None
    for attempt in range(10):
        try:
            srv = http.server.HTTPServer(("127.0.0.1", port + attempt), Handler)
            srv.allow_reuse_address = True
            server = srv
            port = port + attempt
            break
        except OSError:
            continue

    if server is None:
        print(f"ERROR: Could not bind to any port in range {DEFAULT_PORT}-{DEFAULT_PORT + 9}")
        sys.exit(1)

    url = f"http://127.0.0.1:{port}"

    print(f"Cortex Code Session Manager")
    print(f"Listening on {url}")
    print(f"Discovered {added} new session(s) from Cortex conversations")
    print(f"Press Ctrl+C to stop\n")

    webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()


if __name__ == "__main__":
    main()
