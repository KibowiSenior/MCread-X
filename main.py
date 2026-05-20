#!/usr/bin/env python3
"""
Minecraft Server Checker
- Check any server by IP + port
- Background scan all ports 1024-65535 on that IP
- Store found servers in discovered_servers.txt
- Slide-out panel showing all discovered servers with live status
"""

import socket
import struct
import json
import time
import threading
import os
from datetime import datetime
from flask import Flask, request, jsonify, render_template_string

app = Flask(__name__)

RECORDS_FILE = "discovered_servers.txt"
_scan_lock = threading.Lock()
_records_lock = threading.Lock()
_active_scans = {}  # ip -> thread

# ──────────────────────────────────────────────
#  Minecraft Protocol Ping
# ──────────────────────────────────────────────

def ping_minecraft(host: str, port: int, timeout: float = 3.0) -> dict | None:
    """
    Send a Minecraft 1.7+ handshake + status request.
    Returns parsed status dict or None on failure.
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((host, port))

        def pack_varint(val):
            result = b""
            while True:
                part = val & 0x7F
                val >>= 7
                if val:
                    part |= 0x80
                result += bytes([part])
                if not val:
                    break
            return result

        def read_varint(s):
            result = 0
            shift = 0
            while True:
                b = s.recv(1)
                if not b:
                    return 0
                val = b[0]
                result |= (val & 0x7F) << shift
                shift += 7
                if not (val & 0x80):
                    break
            return result

        # Handshake packet
        host_bytes = host.encode("utf-8")
        handshake = (
            pack_varint(0x00)           # packet id
            + pack_varint(47)           # protocol version
            + pack_varint(len(host_bytes))
            + host_bytes
            + struct.pack(">H", port)  # port
            + pack_varint(1)           # next state: status
        )
        sock.send(pack_varint(len(handshake)) + handshake)

        # Status request
        status_req = pack_varint(0x00)
        sock.send(pack_varint(len(status_req)) + status_req)

        # Read response
        _ = read_varint(sock)   # length
        _ = read_varint(sock)   # packet id
        str_len = read_varint(sock)
        raw = b""
        while len(raw) < str_len:
            chunk = sock.recv(str_len - len(raw))
            if not chunk:
                break
            raw += chunk

        sock.close()

        data = json.loads(raw.decode("utf-8"))
        version = data.get("version", {}).get("name", "Unknown")
        players_on = data.get("players", {}).get("online", 0)
        players_max = data.get("players", {}).get("max", 0)
        desc = data.get("description", "")
        if isinstance(desc, dict):
            desc = desc.get("text", "")

        return {
            "online": True,
            "version": version,
            "players_online": players_on,
            "players_max": players_max,
            "description": desc,
            "latency": None,
        }
    except Exception:
        return None


def check_server(host: str, port: int) -> dict:
    """Public check: returns status dict always."""
    t0 = time.time()
    result = ping_minecraft(host, port)
    latency = round((time.time() - t0) * 1000)
    if result:
        result["latency"] = latency
        result["host"] = host
        result["port"] = port
        return result
    return {
        "online": False,
        "host": host,
        "port": port,
        "version": None,
        "players_online": 0,
        "players_max": 0,
        "description": "",
        "latency": None,
    }


# ──────────────────────────────────────────────
#  Records File Helpers
# ──────────────────────────────────────────────

def load_records() -> list[dict]:
    if not os.path.exists(RECORDS_FILE):
        return []
    records = []
    seen = set()
    with open(RECORDS_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("|")
            if len(parts) < 2:
                continue
            host, port_str = parts[0], parts[1]
            key = f"{host}:{port_str}"
            if key not in seen:
                seen.add(key)
                records.append({
                    "host": host,
                    "port": int(port_str),
                    "first_seen": parts[2] if len(parts) > 2 else "Unknown",
                })
    return records


def save_record(host: str, port: int):
    key = f"{host}:{port}"
    existing = load_records()
    for r in existing:
        if r["host"] == host and r["port"] == port:
            return  # already stored
    with _records_lock:
        with open(RECORDS_FILE, "a") as f:
            f.write(f"{host}|{port}|{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")


# ──────────────────────────────────────────────
#  Background Port Scanner
# ──────────────────────────────────────────────

def _scan_worker(host: str):
    """Scan ports 1024-65535 on host in background."""
    print(f"[SCAN] Starting background scan on {host}")
    found = 0
    for port in range(1024, 65536):
        # Quick TCP connect first (faster than full MC ping)
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.5)
            s.connect((host, port))
            s.close()
            # TCP open – try MC ping
            result = ping_minecraft(host, port, timeout=2.0)
            if result:
                save_record(host, port)
                found += 1
                print(f"[SCAN] Found MC server: {host}:{port}")
        except Exception:
            pass
    print(f"[SCAN] Finished scan on {host}. Found {found} server(s).")
    with _scan_lock:
        _active_scans.pop(host, None)


def start_background_scan(host: str):
    with _scan_lock:
        if host in _active_scans:
            return  # already scanning
        t = threading.Thread(target=_scan_worker, args=(host,), daemon=True)
        _active_scans[host] = t
        t.start()


# ──────────────────────────────────────────────
#  Flask Routes
# ──────────────────────────────────────────────

@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/api/check", methods=["POST"])
def api_check():
    data = request.get_json(force=True)
    host = data.get("host", "").strip()
    port = int(data.get("port", 25565))
    if not host:
        return jsonify({"error": "No host provided"}), 400

    status = check_server(host, port)

    # If online, save and start background scan
    if status["online"]:
        save_record(host, port)

    # Always kick off background scan (non-blocking)
    start_background_scan(host)

    return jsonify(status)


@app.route("/api/records")
def api_records():
    records = load_records()
    return jsonify(records)


@app.route("/api/records/status", methods=["POST"])
def api_records_status():
    """Fetch live status for all records."""
    records = load_records()
    results = []

    def fetch_one(r):
        s = check_server(r["host"], r["port"])
        s["first_seen"] = r["first_seen"]
        results.append(s)

    threads = [threading.Thread(target=fetch_one, args=(r,)) for r in records]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    results.sort(key=lambda x: (not x["online"], x["host"], x["port"]))
    return jsonify(results)


@app.route("/api/scan_status")
def api_scan_status():
    host = request.args.get("host", "")
    scanning = host in _active_scans
    return jsonify({"scanning": scanning})


# ──────────────────────────────────────────────
#  HTML / CSS / JS  (single-file frontend)
# ──────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>MC Server Radar</title>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link href="https://fonts.googleapis.com/css2?family=Press+Start+2P&family=Share+Tech+Mono&display=swap" rel="stylesheet"/>
<style>
:root {
  --bg: #0a0e0a;
  --panel: #0f1a0f;
  --border: #1a4d1a;
  --green: #00ff41;
  --green-dim: #007a20;
  --green-glow: rgba(0,255,65,0.15);
  --red: #ff3333;
  --yellow: #ffe033;
  --text: #c8ffc8;
  --muted: #4a7a4a;
  --slide-w: 440px;
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  background: var(--bg);
  color: var(--text);
  font-family: 'Share Tech Mono', monospace;
  min-height: 100vh;
  overflow-x: hidden;
}

/* Scanline overlay */
body::before {
  content:'';
  position:fixed; inset:0;
  background: repeating-linear-gradient(
    0deg,
    transparent,
    transparent 2px,
    rgba(0,0,0,0.15) 2px,
    rgba(0,0,0,0.15) 4px
  );
  pointer-events:none;
  z-index:1000;
}

/* Grid bg */
body::after {
  content:'';
  position:fixed; inset:0;
  background-image:
    linear-gradient(rgba(0,255,65,0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(0,255,65,0.03) 1px, transparent 1px);
  background-size: 40px 40px;
  pointer-events:none;
  z-index:0;
}

.wrap {
  position:relative;
  z-index:1;
  max-width:760px;
  margin:0 auto;
  padding:40px 24px 80px;
  transition: margin-right 0.4s ease;
}

/* ── Header ── */
header {
  text-align:center;
  margin-bottom:48px;
}
.logo {
  font-family:'Press Start 2P', monospace;
  font-size:clamp(16px,3.5vw,28px);
  color: var(--green);
  text-shadow: 0 0 20px var(--green), 0 0 40px rgba(0,255,65,0.4);
  letter-spacing:2px;
  line-height:1.6;
}
.logo span { color: var(--yellow); }
.tagline {
  margin-top:12px;
  color:var(--muted);
  font-size:11px;
  letter-spacing:3px;
  text-transform:uppercase;
}

/* ── Card ── */
.card {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius:4px;
  padding:28px;
  margin-bottom:24px;
  box-shadow: 0 0 30px rgba(0,255,65,0.05), inset 0 1px 0 rgba(0,255,65,0.1);
}
.card-title {
  font-family:'Press Start 2P', monospace;
  font-size:9px;
  color:var(--green-dim);
  letter-spacing:2px;
  margin-bottom:20px;
  text-transform:uppercase;
}

/* ── Form ── */
.input-row {
  display:flex;
  gap:12px;
  flex-wrap:wrap;
  margin-bottom:16px;
}
.field {
  display:flex;
  flex-direction:column;
  gap:6px;
}
.field label {
  font-size:10px;
  color:var(--muted);
  letter-spacing:2px;
  text-transform:uppercase;
}
.field input {
  background: #060d06;
  border: 1px solid var(--border);
  color: var(--green);
  font-family:'Share Tech Mono', monospace;
  font-size:14px;
  padding:10px 14px;
  border-radius:3px;
  outline:none;
  transition: border-color 0.2s, box-shadow 0.2s;
}
.field input:focus {
  border-color: var(--green);
  box-shadow: 0 0 10px var(--green-glow);
}
.field.ip { flex:1; min-width:200px; }
.field.port { width:110px; }

.btn {
  font-family:'Press Start 2P', monospace;
  font-size:9px;
  padding:12px 22px;
  border:none;
  border-radius:3px;
  cursor:pointer;
  letter-spacing:1px;
  transition: all 0.15s;
  align-self:flex-end;
}
.btn-primary {
  background: var(--green);
  color: #030803;
}
.btn-primary:hover:not(:disabled) {
  background:#00cc33;
  box-shadow: 0 0 20px rgba(0,255,65,0.5);
  transform:translateY(-1px);
}
.btn-primary:disabled { opacity:0.4; cursor:not-allowed; }
.btn-secondary {
  background:transparent;
  border:1px solid var(--border);
  color:var(--green-dim);
}
.btn-secondary:hover {
  border-color:var(--green);
  color:var(--green);
  box-shadow: 0 0 10px var(--green-glow);
}

/* ── Scan notice ── */
.scan-notice {
  display:none;
  align-items:center;
  gap:8px;
  font-size:10px;
  color:var(--muted);
  margin-top:8px;
}
.scan-notice.visible { display:flex; }
.pulse {
  width:8px; height:8px;
  border-radius:50%;
  background:var(--yellow);
  animation:pulse 1s ease-in-out infinite;
}
@keyframes pulse {
  0%,100%{opacity:1;transform:scale(1);}
  50%{opacity:0.4;transform:scale(0.7);}
}

/* ── Result block ── */
#result { display:none; }

.status-badge {
  display:inline-flex;
  align-items:center;
  gap:8px;
  font-family:'Press Start 2P', monospace;
  font-size:10px;
  padding:6px 14px;
  border-radius:3px;
  margin-bottom:20px;
}
.status-badge.online { background:rgba(0,255,65,0.12); color:var(--green); border:1px solid var(--green-dim); }
.status-badge.offline { background:rgba(255,51,51,0.1); color:var(--red); border:1px solid #662222; }
.dot { width:8px;height:8px;border-radius:50%; }
.dot.green { background:var(--green); box-shadow:0 0 6px var(--green); }
.dot.red { background:var(--red); box-shadow:0 0 6px var(--red); }

.info-grid {
  display:grid;
  grid-template-columns:1fr 1fr;
  gap:12px;
}
.info-item {
  background:#060d06;
  border:1px solid var(--border);
  border-radius:3px;
  padding:12px 14px;
}
.info-item .label {
  font-size:9px;
  color:var(--muted);
  letter-spacing:2px;
  text-transform:uppercase;
  margin-bottom:4px;
}
.info-item .value {
  font-size:14px;
  color:var(--green);
  word-break:break-all;
}
.info-item .value.red { color:var(--red); }
.info-item .value.yellow { color:var(--yellow); }

.motd {
  grid-column:1/-1;
}

/* ── Records trigger ── */
.records-trigger {
  position:fixed;
  right:0; top:50%;
  transform:translateY(-50%);
  z-index:200;
  writing-mode:vertical-rl;
  font-family:'Press Start 2P', monospace;
  font-size:8px;
  background:var(--panel);
  border:1px solid var(--border);
  border-right:none;
  color:var(--green-dim);
  padding:16px 10px;
  cursor:pointer;
  letter-spacing:2px;
  border-radius:4px 0 0 4px;
  transition: all 0.2s;
}
.records-trigger:hover {
  color:var(--green);
  border-color:var(--green);
  box-shadow: -4px 0 20px var(--green-glow);
}
.records-trigger .badge {
  writing-mode:horizontal-tb;
  display:inline-block;
  background:var(--green);
  color:#030803;
  border-radius:50%;
  width:18px; height:18px;
  line-height:18px;
  text-align:center;
  font-size:7px;
  margin-top:8px;
}

/* ── Slide Panel ── */
.slide-panel {
  position:fixed;
  right:0; top:0; bottom:0;
  width: var(--slide-w);
  background: var(--panel);
  border-left:1px solid var(--border);
  box-shadow:-10px 0 40px rgba(0,0,0,0.6);
  z-index:300;
  transform:translateX(100%);
  transition:transform 0.4s cubic-bezier(0.25,0.8,0.25,1);
  display:flex;
  flex-direction:column;
  overflow:hidden;
}
.slide-panel.open { transform:translateX(0); }

.panel-header {
  padding:20px 24px;
  border-bottom:1px solid var(--border);
  display:flex;
  align-items:center;
  justify-content:space-between;
  flex-shrink:0;
}
.panel-title {
  font-family:'Press Start 2P', monospace;
  font-size:9px;
  color:var(--green);
  letter-spacing:2px;
}
.panel-close {
  background:none;
  border:1px solid var(--border);
  color:var(--muted);
  font-family:'Share Tech Mono', monospace;
  font-size:16px;
  width:30px; height:30px;
  cursor:pointer;
  border-radius:3px;
  display:flex;align-items:center;justify-content:center;
  transition:all 0.15s;
}
.panel-close:hover { border-color:var(--red); color:var(--red); }

.panel-toolbar {
  padding:12px 24px;
  border-bottom:1px solid var(--border);
  flex-shrink:0;
}

.panel-list {
  flex:1;
  overflow-y:auto;
  padding:16px 24px;
}
.panel-list::-webkit-scrollbar { width:4px; }
.panel-list::-webkit-scrollbar-track { background:transparent; }
.panel-list::-webkit-scrollbar-thumb { background:var(--border); border-radius:2px; }

.record-card {
  border:1px solid var(--border);
  border-radius:3px;
  padding:14px;
  margin-bottom:10px;
  background:#060d06;
  transition:border-color 0.2s;
  animation:fadeIn 0.3s ease;
}
.record-card:hover { border-color:var(--green-dim); }
@keyframes fadeIn { from{opacity:0;transform:translateY(4px);}to{opacity:1;transform:translateY(0);} }

.record-header {
  display:flex;
  justify-content:space-between;
  align-items:center;
  margin-bottom:8px;
}
.record-addr {
  font-size:12px;
  color:var(--green);
  font-weight:bold;
}
.record-badge {
  font-size:8px;
  padding:3px 8px;
  border-radius:2px;
  font-family:'Press Start 2P', monospace;
}
.record-badge.on { background:rgba(0,255,65,0.15); color:var(--green); }
.record-badge.off { background:rgba(255,51,51,0.1); color:var(--red); }
.record-badge.loading { background:rgba(255,224,51,0.1); color:var(--yellow); }
.record-meta {
  font-size:10px;
  color:var(--muted);
  display:flex;
  flex-wrap:wrap;
  gap:8px;
}
.record-meta span { color:var(--text); }

.panel-empty {
  text-align:center;
  padding:48px 0;
  color:var(--muted);
  font-size:11px;
  line-height:2;
}

/* ── Loading spinner ── */
.spinner {
  display:none;
  width:20px; height:20px;
  border:2px solid var(--border);
  border-top-color:var(--green);
  border-radius:50%;
  animation:spin 0.7s linear infinite;
}
@keyframes spin { to{transform:rotate(360deg);} }
.spinner.visible { display:block; }

/* overlay when panel open */
.overlay {
  display:none;
  position:fixed;inset:0;
  background:rgba(0,0,0,0.5);
  z-index:250;
}
.overlay.visible { display:block; }

@media(max-width:500px){
  :root{--slide-w:100vw;}
  .info-grid{grid-template-columns:1fr;}
}
</style>
</head>
<body>

<div class="overlay" id="overlay" onclick="closePanel()"></div>

<!-- Slide Panel -->
<div class="slide-panel" id="slidePanel">
  <div class="panel-header">
    <div class="panel-title">⚡ SERVER RECORDS</div>
    <button class="panel-close" onclick="closePanel()">✕</button>
  </div>
  <div class="panel-toolbar">
    <button class="btn btn-secondary" onclick="loadRecords()" style="font-size:8px;padding:8px 14px;">
      ↻ REFRESH STATUS
    </button>
  </div>
  <div class="panel-list" id="recordList">
    <div class="panel-empty">No servers discovered yet.<br/>Check a server to begin scanning.</div>
  </div>
</div>

<!-- Records Trigger Tab -->
<button class="records-trigger" id="recordsTab" onclick="openPanel()">
  SERVER RECORDS
  <span class="badge" id="recordCount">0</span>
</button>

<!-- Main -->
<div class="wrap" id="mainWrap">
  <header>
    <div class="logo">⛏ MC SERVER<br/><span>RADAR</span></div>
    <div class="tagline">Real-time Minecraft Server Status & Discovery</div>
  </header>

  <!-- Checker Card -->
  <div class="card">
    <div class="card-title">▶ Check Server Status</div>
    <div class="input-row">
      <div class="field ip">
        <label>Server IP / Hostname</label>
        <input type="text" id="ipInput" placeholder="play.hypixel.net" autocomplete="off" spellcheck="false"/>
      </div>
      <div class="field port">
        <label>Port</label>
        <input type="number" id="portInput" value="25565" min="1" max="65535"/>
      </div>
      <button class="btn btn-primary" id="checkBtn" onclick="checkServer()">
        PING
      </button>
      <div class="spinner" id="spinner"></div>
    </div>
    <div class="scan-notice" id="scanNotice">
      <div class="pulse"></div>
      Background port scan running on this IP (1024–65535) — results auto-saved to records
    </div>
  </div>

  <!-- Result Card -->
  <div class="card" id="result">
    <div class="card-title">▶ Server Response</div>
    <div id="statusBadge"></div>
    <div class="info-grid" id="infoGrid"></div>
  </div>

</div>

<script>
let scanPollInterval = null;

async function checkServer() {
  const host = document.getElementById('ipInput').value.trim();
  const port = parseInt(document.getElementById('portInput').value) || 25565;
  if (!host) { alert('Enter a server IP or hostname.'); return; }

  setLoading(true);
  document.getElementById('result').style.display = 'none';

  try {
    const res = await fetch('/api/check', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({host, port})
    });
    const data = await res.json();
    renderResult(data);
    updateRecordCount();
    startScanPoll(host);
  } catch(e) {
    alert('Request failed: ' + e.message);
  } finally {
    setLoading(false);
  }
}

function setLoading(on) {
  document.getElementById('checkBtn').disabled = on;
  document.getElementById('spinner').classList.toggle('visible', on);
}

function renderResult(d) {
  const resultEl = document.getElementById('result');
  resultEl.style.display = 'block';

  const badge = document.getElementById('statusBadge');
  if (d.online) {
    badge.innerHTML = `<div class="status-badge online"><div class="dot green"></div>ONLINE</div>`;
  } else {
    badge.innerHTML = `<div class="status-badge offline"><div class="dot red"></div>OFFLINE / UNREACHABLE</div>`;
  }

  const grid = document.getElementById('infoGrid');
  if (d.online) {
    grid.innerHTML = `
      <div class="info-item">
        <div class="label">Address</div>
        <div class="value">${esc(d.host)}:${d.port}</div>
      </div>
      <div class="info-item">
        <div class="label">Version</div>
        <div class="value yellow">${esc(d.version||'Unknown')}</div>
      </div>
      <div class="info-item">
        <div class="label">Players</div>
        <div class="value">${d.players_online} <span style="color:var(--muted)">/ ${d.players_max}</span></div>
      </div>
      <div class="info-item">
        <div class="label">Latency</div>
        <div class="value ${d.latency > 200 ? 'red' : ''}">${d.latency}ms</div>
      </div>
      ${d.description ? `<div class="info-item motd"><div class="label">MOTD</div><div class="value" style="font-size:12px">${esc(d.description)}</div></div>` : ''}
    `;
  } else {
    grid.innerHTML = `
      <div class="info-item">
        <div class="label">Address</div>
        <div class="value">${esc(d.host)}:${d.port}</div>
      </div>
      <div class="info-item">
        <div class="label">Status</div>
        <div class="value red">Connection refused or timed out</div>
      </div>
    `;
  }

  resultEl.scrollIntoView({behavior:'smooth', block:'nearest'});
}

// ── Scan poll ──
function startScanPoll(host) {
  clearInterval(scanPollInterval);
  document.getElementById('scanNotice').classList.add('visible');
  scanPollInterval = setInterval(async () => {
    const r = await fetch('/api/scan_status?host=' + encodeURIComponent(host));
    const d = await r.json();
    updateRecordCount();
    if (!d.scanning) {
      clearInterval(scanPollInterval);
      document.getElementById('scanNotice').classList.remove('visible');
    }
  }, 5000);
}

// ── Records Panel ──
async function updateRecordCount() {
  const r = await fetch('/api/records');
  const d = await r.json();
  document.getElementById('recordCount').textContent = d.length;
}

function openPanel() {
  document.getElementById('slidePanel').classList.add('open');
  document.getElementById('overlay').classList.add('visible');
  loadRecords();
}

function closePanel() {
  document.getElementById('slidePanel').classList.remove('open');
  document.getElementById('overlay').classList.remove('visible');
}

async function loadRecords() {
  const list = document.getElementById('recordList');
  list.innerHTML = '<div class="panel-empty">Fetching live status…</div>';

  try {
    const r = await fetch('/api/records/status', {method:'POST'});
    const servers = await r.json();
    renderRecords(servers);
    document.getElementById('recordCount').textContent = servers.length;
  } catch(e) {
    list.innerHTML = '<div class="panel-empty">Failed to load records.</div>';
  }
}

function renderRecords(servers) {
  const list = document.getElementById('recordList');
  if (!servers.length) {
    list.innerHTML = '<div class="panel-empty">No servers discovered yet.<br/>Check a server to begin scanning.</div>';
    return;
  }

  list.innerHTML = servers.map(s => `
    <div class="record-card">
      <div class="record-header">
        <div class="record-addr">${esc(s.host)}:${s.port}</div>
        <div class="record-badge ${s.online?'on':'off'}">${s.online?'ONLINE':'OFFLINE'}</div>
      </div>
      <div class="record-meta">
        ${s.online ? `
          <span>v ${esc(s.version||'?')}</span>
          <span>👥 ${s.players_online}/${s.players_max}</span>
          <span>🏓 ${s.latency}ms</span>
        ` : '<span style="color:var(--red)">Unreachable</span>'}
        <span style="color:var(--muted);font-size:9px">First seen: ${esc(s.first_seen||'?')}</span>
      </div>
      ${s.online && s.description ? `<div style="margin-top:6px;font-size:10px;color:var(--muted)">${esc(s.description).substring(0,80)}</div>` : ''}
    </div>
  `).join('');
}

function esc(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g,'&amp;')
    .replace(/</g,'&lt;')
    .replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;');
}

// Enter key
document.addEventListener('keydown', e => {
  if (e.key === 'Enter') checkServer();
});

// Init
updateRecordCount();
</script>
</body>
</html>
"""

# ──────────────────────────────────────────────
#  Entry Point
# ──────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  MC Server Radar")
    print("  http://localhost:5000")
    print(f"  Discovered servers saved to: {RECORDS_FILE}")
    print("=" * 60)
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
