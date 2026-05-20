# ⛏ MC Server Radar — Complete Documentation

> A single-file Python web application that checks Minecraft server status,
> silently scans all ports on a given IP for hidden Minecraft servers, and
> keeps a persistent record of every server ever discovered.

---

## Table of Contents

1. [Quick Start](#1-quick-start)
2. [Project Overview](#2-project-overview)
3. [File Structure](#3-file-structure)
4. [How to Run](#4-how-to-run)
5. [Feature 1 — Server Status Checker](#5-feature-1--server-status-checker)
6. [Feature 2 — Background Port Scanner](#6-feature-2--background-port-scanner)
7. [Feature 3 — Server Records & Slide Panel](#7-feature-3--server-records--slide-panel)
8. [Minecraft Protocol Explained](#8-minecraft-protocol-explained)
9. [API Endpoints Reference](#9-api-endpoints-reference)
10. [Backend Code Walkthrough](#10-backend-code-walkthrough)
11. [Frontend Code Walkthrough](#11-frontend-code-walkthrough)
12. [The Records File](#12-the-records-file)
13. [Threading & Concurrency](#13-threading--concurrency)
14. [Error Handling](#14-error-handling)
15. [Configuration & Customization](#15-configuration--customization)
16. [Frequently Asked Questions](#16-frequently-asked-questions)
17. [Troubleshooting](#17-troubleshooting)

---

## 1. Quick Start

```bash
# 1. Install the only dependency
pip install flask

# 2. Run the app
python3 minecraft_checker.py

# 3. Open your browser
# http://localhost:5000
```

That's it. No database, no config files, no additional setup.

---

## 2. Project Overview

MC Server Radar is a **single Python file** that does three things:

| What | How |
|------|-----|
| Check if a Minecraft server is online | Sends a real Minecraft handshake packet and reads the response |
| Silently scan all ports on an IP | Runs a background thread that tests every port from 1024 to 65535 |
| Remember every server found | Writes to a plain text file `discovered_servers.txt` |

The web interface is written in plain HTML/CSS/JavaScript and is embedded directly in the Python file as a string — no separate template files needed.

**Technology stack:**

- **Python 3.10+** — backend language
- **Flask** — lightweight web framework (the only pip dependency)
- **socket** — Python's built-in network library (used for the Minecraft ping)
- **threading** — Python's built-in concurrency library (used for background scanning)
- **HTML + CSS + Vanilla JS** — frontend, no frameworks, no build step

---

## 3. File Structure

```
minecraft_checker.py        ← The entire application (single file)
discovered_servers.txt      ← Auto-created when first server is found
```

When you run the app, `discovered_servers.txt` is created automatically in the same folder. You do not need to create it yourself.

---

## 4. How to Run

### Requirements

- Python 3.10 or newer (uses the `dict | None` union type hint syntax)
- Flask (`pip install flask`)
- A network connection

### Starting the server

```bash
python3 minecraft_checker.py
```

You will see:

```
============================================================
  MC Server Radar
  http://localhost:5000
  Discovered servers saved to: discovered_servers.txt
============================================================
```

The app listens on `0.0.0.0:5000`, which means it is reachable from:

- Your own machine: `http://localhost:5000`
- Other devices on your local network: `http://<your-local-ip>:5000`

### Stopping the server

Press `Ctrl+C` in the terminal. Any in-progress background scans will stop because the scan threads are daemon threads (they die when the main process ends).

---

## 5. Feature 1 — Server Status Checker

### What it does

When you type a server address (IP or hostname) and a port number, then click **PING**, the app:

1. Opens a raw TCP socket connection to that address and port
2. Sends a Minecraft handshake packet (the same packet the official Minecraft client sends)
3. Reads the server's JSON status response
4. Displays version, player count, MOTD (message of the day), and latency

### What you see if the server is online

- A green **ONLINE** badge
- Server IP and port
- Minecraft version (e.g. `Paper 1.20.4`)
- Current players / maximum players (e.g. `12 / 100`)
- Latency in milliseconds
- MOTD text (the server's welcome message)

### What you see if the server is offline

- A red **OFFLINE / UNREACHABLE** badge
- The IP and port you tried
- A note that the connection was refused or timed out

### Default port

The port field defaults to `25565`, which is the standard Minecraft server port. You can change it to any port between 1 and 65535.

### Pressing Enter

You can press the `Enter` key on your keyboard instead of clicking the PING button — the page listens for the Enter keydown event.

---

## 6. Feature 2 — Background Port Scanner

### What it does

Every time you click PING (regardless of whether the server is online or offline), the app automatically starts a **background port scan** on the IP address you entered. This scan:

- Tests every port from **1024 to 65535** (62,511 ports total)
- Runs completely in the background — it does not slow down or affect the main page
- Saves any Minecraft server it finds to `discovered_servers.txt`
- Never shows raw scan progress to the user (by design)

### The scanning indicator

A small **yellow pulsing dot** appears below the input form with the message:

> Background port scan running on this IP (1024–65535) — results auto-saved to records

This dot disappears automatically when the scan finishes. The page polls the `/api/scan_status` endpoint every 5 seconds to check if scanning is still active.

### How the scan works step by step

For each port number from 1024 to 65535:

1. Try to open a TCP connection with a 0.5-second timeout
2. If the TCP connection succeeds (port is open), attempt a full Minecraft handshake with a 2-second timeout
3. If the Minecraft handshake succeeds, save the server to the records file
4. Log the discovery to the terminal

### Why only ports 1024 and above?

Ports below 1024 are "well-known ports" reserved for system services (HTTP on 80, HTTPS on 443, SSH on 22, etc.). Minecraft servers never run on these ports, so scanning them would waste time.

### Duplicate scan prevention

The app tracks which IPs are currently being scanned in a dictionary called `_active_scans`. If you ping the same IP multiple times, it will not start a second scan — it checks whether a scan is already in progress first.

### Performance note

A full scan of all 62,511 ports can take anywhere from a few minutes to over an hour, depending on network conditions and how many ports are open. The 0.5-second TCP timeout per port is already quite aggressive. Most ports will fail instantly (connection refused), which makes scans much faster in practice.

---

## 7. Feature 3 — Server Records & Slide Panel

### The Records Tab

On the right side of the screen, there is a vertical tab labelled **SERVER RECORDS** with a green badge showing the number of saved servers. Clicking this tab slides open the records panel from the right side of the screen.

### What the panel shows

The panel makes a live request to fetch the current status of every saved server in parallel, then displays each one as a card showing:

- Server IP and port
- **ONLINE** (green) or **OFFLINE** (red) badge based on real-time ping
- Minecraft version
- Current / maximum player count
- Latency in milliseconds
- MOTD (truncated to 80 characters)
- When the server was first discovered

### Sorting

Results are sorted so online servers appear at the top. Offline servers appear below.

### Refreshing

There is a **↻ REFRESH STATUS** button inside the panel that re-pings all saved servers and updates the display.

### Closing the panel

Click the ✕ button in the top-right corner of the panel, or click the dark overlay behind the panel.

### Live parallel fetching

When you open the panel or click Refresh, the backend spawns one thread per saved server and pings them all simultaneously (with a 5-second join timeout per thread). This means 50 saved servers are checked in roughly 5 seconds rather than 50 × 3 = 150 seconds.

---

## 8. Minecraft Protocol Explained

Minecraft uses a custom binary protocol over TCP. The app implements the **Minecraft 1.7+ Server List Ping** (also called the Status Request), which is what the game's multiplayer server list uses to show server info without you having to connect.

### Step-by-step protocol flow

#### 1. Open a TCP connection

```
Client → TCP SYN → Server
Client ← TCP SYN-ACK ← Server
Client → TCP ACK → Server
```

A normal TCP handshake. Nothing Minecraft-specific yet.

#### 2. Send a Handshake packet

The client sends a packet that says:
- "I am using protocol version 47" (a placeholder — the server ignores this for status)
- "I am connecting to this hostname and port"
- "I want to enter the STATUS state" (not the LOGIN state)

All numbers in this protocol are encoded as **VarInt** — a variable-length integer format where each byte uses 7 bits for data and 1 bit to indicate whether more bytes follow.

```
Packet format:
  [Packet Length as VarInt]
  [Packet ID: 0x00 as VarInt]
  [Protocol Version: 47 as VarInt]
  [Host length as VarInt]
  [Host as UTF-8 bytes]
  [Port as unsigned short (2 bytes, big-endian)]
  [Next State: 1 (status) as VarInt]
```

#### 3. Send a Status Request packet

A very short packet — just the packet ID 0x00 with no additional data:

```
[Packet Length: 1 as VarInt]
[Packet ID: 0x00 as VarInt]
```

#### 4. Read the Status Response packet

The server responds with:

```
[Packet Length as VarInt]
[Packet ID: 0x00 as VarInt]
[JSON string length as VarInt]
[JSON string as UTF-8 bytes]
```

#### 5. Parse the JSON

The JSON payload looks like this (simplified):

```json
{
  "version": {
    "name": "Paper 1.20.4",
    "protocol": 765
  },
  "players": {
    "max": 100,
    "online": 12,
    "sample": [...]
  },
  "description": {
    "text": "A Minecraft Server"
  }
}
```

The app extracts version name, online count, max count, and description text.

### Why not use an existing library?

The ping logic is implemented from scratch using only Python's built-in `socket` module. This means the app has **zero Minecraft-specific dependencies** — just Flask.

---

## 9. API Endpoints Reference

The app exposes four HTTP endpoints that the frontend JavaScript calls.

### POST /api/check

Ping a single server and return its status.

**Request body (JSON):**
```json
{
  "host": "play.hypixel.net",
  "port": 25565
}
```

**Response (server online):**
```json
{
  "online": true,
  "host": "play.hypixel.net",
  "port": 25565,
  "version": "Velocity 1.7.2-1.20.4",
  "players_online": 47823,
  "players_max": 200000,
  "description": "Hypixel Network",
  "latency": 42
}
```

**Response (server offline):**
```json
{
  "online": false,
  "host": "dead.server.net",
  "port": 25565,
  "version": null,
  "players_online": 0,
  "players_max": 0,
  "description": "",
  "latency": null
}
```

**Side effects:**
- If the server is online, saves it to `discovered_servers.txt`
- Always starts a background port scan on the host (if not already scanning)

### GET /api/records

Returns a list of all saved server addresses from `discovered_servers.txt`. Does NOT ping them — just returns the stored data.

**Response:**
```json
[
  {
    "host": "192.168.1.10",
    "port": 25565,
    "first_seen": "2025-05-21 14:32:01"
  },
  {
    "host": "play.example.com",
    "port": 19132,
    "first_seen": "2025-05-21 15:00:44"
  }
]
```

### POST /api/records/status

Fetches live status for every saved server in parallel. This is called when the slide panel opens or the Refresh button is clicked.

**Request body:** empty (no body required)

**Response:** Same format as `/api/check` but as an array, sorted online-first, with an added `first_seen` field.

```json
[
  {
    "online": true,
    "host": "192.168.1.10",
    "port": 25565,
    "version": "Spigot 1.20.1",
    "players_online": 3,
    "players_max": 20,
    "description": "My Home Server",
    "latency": 5,
    "first_seen": "2025-05-21 14:32:01"
  }
]
```

### GET /api/scan_status?host=\<ip\>

Returns whether a background scan is currently running for a given host.

**Response:**
```json
{ "scanning": true }
```

or

```json
{ "scanning": false }
```

---

## 10. Backend Code Walkthrough

The Python file is divided into five logical sections:

### Section 1 — Imports and app setup

```python
import socket, struct, json, time, threading, os
from datetime import datetime
from flask import Flask, request, jsonify, render_template_string
```

Only standard library modules plus Flask. `socket` handles all network I/O, `threading` handles background scanning, `struct` is used to pack the 2-byte port number in the Minecraft handshake.

### Section 2 — Minecraft Protocol Ping (`ping_minecraft`)

The `ping_minecraft(host, port, timeout)` function:

- Opens a raw TCP socket
- Defines two helpers inline: `pack_varint` (encodes an integer as Minecraft VarInt bytes) and `read_varint` (reads VarInt bytes from a socket)
- Sends the handshake + status request packets
- Reads the response in a loop until `str_len` bytes are collected
- Parses and returns the JSON as a Python dict

Returns `None` if anything goes wrong (connection refused, timeout, malformed JSON, etc.).

The `check_server(host, port)` wrapper calls `ping_minecraft`, measures round-trip time, and always returns a complete dict (never None — offline servers get `"online": false`).

### Section 3 — Records File Helpers

`load_records()` reads `discovered_servers.txt` line by line. Each line has the format:

```
host|port|YYYY-MM-DD HH:MM:SS
```

Lines starting with `#` are treated as comments and skipped. Duplicate `host:port` combinations are deduplicated using a `seen` set.

`save_record(host, port)` appends a new line to the file. It first calls `load_records()` to check for duplicates — if the server is already saved, it does nothing.

### Section 4 — Background Port Scanner

`_scan_worker(host)` is the function that runs in a background thread. It:

1. Iterates ports 1024–65535
2. For each port, attempts a 0.5-second TCP connect
3. If TCP connects, attempts a full Minecraft ping with a 2-second timeout
4. If the Minecraft ping succeeds, calls `save_record`
5. Removes itself from `_active_scans` when done

`start_background_scan(host)` creates and starts the thread (if one isn't already running for that host), storing it in `_active_scans` so we can check its status later.

### Section 5 — Flask Routes

Four routes as described in the API section above. Each route:

- Validates input
- Calls the appropriate helper functions
- Returns JSON with `jsonify`

### Section 6 — HTML template

The `HTML` variable holds the entire frontend as a raw string. Flask's `render_template_string` serves it directly without any file system access.

---

## 11. Frontend Code Walkthrough

The frontend is pure HTML, CSS, and JavaScript — no frameworks, no build tools.

### Layout

There are three main visual areas:

- **Main content area** — the server checker card and result card, centered on the page
- **Records tab** — a fixed vertical tab on the right edge, always visible
- **Slide panel** — a 440px-wide panel that slides in from the right when the tab is clicked

### CSS Architecture

All colors are defined as CSS custom properties (variables) at the top of the `<style>` block:

```css
:root {
  --bg: #0a0e0a;          /* page background */
  --panel: #0f1a0f;       /* card backgrounds */
  --border: #1a4d1a;      /* all borders */
  --green: #00ff41;       /* primary accent */
  --green-dim: #007a20;   /* secondary accent */
  --red: #ff3333;         /* offline/error */
  --yellow: #ffe033;      /* scanning indicator */
  --text: #c8ffc8;        /* body text */
  --muted: #4a7a4a;       /* labels, secondary text */
  --slide-w: 440px;       /* panel width */
}
```

The aesthetic is a retro green-terminal / hacker theme with:

- Two overlaid `::before` / `::after` pseudo-elements on `body` for the CRT scanline effect and grid background
- `Press Start 2P` (Google Fonts pixel font) for headings and labels
- `Share Tech Mono` (Google Fonts monospace) for body text and inputs
- Text shadows on the logo to create a green glow effect

### JavaScript Functions

| Function | What it does |
|----------|-------------|
| `checkServer()` | Reads the form, calls `/api/check`, renders result |
| `setLoading(on)` | Disables the button and shows/hides the spinner |
| `renderResult(data)` | Builds the status badge and info grid HTML |
| `startScanPoll(host)` | Starts a `setInterval` that polls `/api/scan_status` every 5 seconds |
| `updateRecordCount()` | Calls `/api/records` and updates the badge number |
| `openPanel()` | Adds the `.open` class to the slide panel and calls `loadRecords()` |
| `closePanel()` | Removes the `.open` class |
| `loadRecords()` | Calls `/api/records/status`, renders all record cards |
| `renderRecords(servers)` | Builds the HTML for all record cards |
| `esc(str)` | HTML-escapes a string to prevent XSS when inserting user data into the DOM |

### The slide panel animation

The panel is always in the DOM but starts off-screen:

```css
.slide-panel {
  transform: translateX(100%);          /* hidden to the right */
  transition: transform 0.4s cubic-bezier(0.25, 0.8, 0.25, 1);
}
.slide-panel.open {
  transform: translateX(0);            /* slides into view */
}
```

Adding or removing the `.open` class triggers the CSS transition.

---

## 12. The Records File

`discovered_servers.txt` is a plain text file created in the same directory as the Python script. Its format is:

```
# Lines starting with # are ignored
192.168.1.10|25565|2025-05-21 14:32:01
play.example.com|19132|2025-05-21 15:00:44
10.0.0.5|25570|2025-05-21 15:03:12
```

Each line contains three fields separated by `|`:

| Field | Description |
|-------|-------------|
| `host` | IP address or hostname |
| `port` | Port number (integer) |
| `first_seen` | Date and time when the server was first discovered |

### Reading the file manually

You can open this file in any text editor. It is human-readable.

### Editing the file

You can manually add or remove entries. The app re-reads the file on every request, so changes take effect immediately without restarting the server.

### File location

The file is always created in the **current working directory** — wherever you ran the Python command from. If you run `python3 /home/user/apps/minecraft_checker.py` from `/tmp`, the file will be created at `/tmp/discovered_servers.txt`.

---

## 13. Threading & Concurrency

The app uses Python threads in two places:

### Background scan threads

One thread per scanned IP. Threads are stored in `_active_scans` dictionary:

```python
_active_scans = {}   # { "192.168.1.1": <Thread object> }
```

Access to this dict is protected by `_scan_lock` (a `threading.Lock`) to prevent race conditions when two requests for the same IP arrive simultaneously.

Scan threads are **daemon threads** (`daemon=True`), meaning they automatically terminate when the main Python process exits. You do not need to manually join or stop them.

### Parallel record status fetching

When the records panel loads, the app creates one thread per saved server and runs all the Minecraft pings concurrently:

```python
threads = [threading.Thread(target=fetch_one, args=(r,)) for r in records]
for t in threads:
    t.start()
for t in threads:
    t.join(timeout=5)  # wait max 5 seconds per thread
```

The `timeout=5` in `join` means that even if a server takes longer than 5 seconds to respond (or never responds), the request won't hang forever.

### Thread safety for the records file

Write operations to `discovered_servers.txt` are protected by `_records_lock` to prevent two threads from writing to the file at the same time.

### Flask threading

Flask is started with `threaded=True`:

```python
app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
```

This means each incoming HTTP request is handled in its own thread, so multiple users can use the app simultaneously without blocking each other.

---

## 14. Error Handling

### Network errors

All socket operations are wrapped in `try/except Exception`. Any error (connection refused, timeout, DNS failure, broken pipe, invalid response) causes `ping_minecraft` to return `None`, which the caller treats as "server offline."

### Invalid port input

The port field in the HTML has `min="1" max="65535"` validation. The Python backend does `int(data.get("port", 25565))` with a fallback to 25565 if no port is provided.

### Empty host

The `/api/check` route checks `if not host` and returns a 400 error:

```json
{ "error": "No host provided" }
```

### Malformed records file

`load_records()` silently skips any line that doesn't have at least 2 pipe-separated fields, so a corrupted line won't crash the app.

### Frontend fetch errors

The `checkServer()` function wraps the `fetch` call in `try/catch` and shows an `alert()` with the error message if the request fails.

---

## 15. Configuration & Customization

### Changing the port

Edit the last line of the file:

```python
app.run(host="0.0.0.0", port=5000, ...)
# Change 5000 to any available port number
```

### Changing the records file path

Edit the constant near the top of the file:

```python
RECORDS_FILE = "discovered_servers.txt"
# Change to any path, e.g. "/var/data/mc_servers.txt"
```

### Changing the scan port range

Edit the range inside `_scan_worker`:

```python
for port in range(1024, 65536):
# Change to e.g. range(25560, 25570) for a narrow scan
```

### Changing the ping timeout

Two timeouts are used:

```python
# In check_server (user-facing ping) — used for the PING button
result = ping_minecraft(host, port)          # default 3.0 seconds

# In _scan_worker (background scan) — faster, less patient
result = ping_minecraft(host, port, timeout=2.0)

# TCP quick-check timeout in the scanner
s.settimeout(0.5)
```

Lower values = faster scan but more missed servers on slow networks.
Higher values = slower scan but more reliable results.

### Making the app accessible from the internet

By default the app runs on `0.0.0.0`, so it's already reachable on your local network. To expose it to the internet, you need to:

1. Open port 5000 in your firewall / router
2. Consider adding authentication (Flask-Login or HTTP Basic Auth), as the app has none

---

## 16. Frequently Asked Questions

**Q: Does this work for Bedrock edition servers?**
The ping protocol used here is for Minecraft: Java Edition only. Bedrock edition uses a completely different protocol (RakNet/UDP-based). Bedrock servers will show as offline.

**Q: Why does a server show offline even though I know it's online?**
Some servers block or ignore status requests while still allowing gameplay connections. Also, some servers run behind anti-DDoS proxies that filter pings. Try connecting with the actual Minecraft client to confirm.

**Q: The background scan has been running for a very long time. Is that normal?**
Yes. Scanning 62,511 ports one by one takes time. At 0.5 seconds per failed port (worst case), a full scan could theoretically take ~8.6 hours. In practice, most ports fail instantly (connection immediately refused), so typical scans complete in minutes. The speed depends heavily on the network.

**Q: Can I scan an IP that isn't on my local network?**
Yes, as long as your machine has internet access and the target IP is reachable. Note that port scanning someone else's server without permission may be against their terms of service or local laws.

**Q: Why does the badge number on the tab go up even when I'm not looking?**
The `startScanPoll` function updates the record count every 5 seconds while a scan is running. If the background scan finds new servers, the badge updates automatically.

**Q: What happens to the records file if I run the app from a different directory?**
A new `discovered_servers.txt` will be created in the new directory. The old one in the previous directory will not be deleted or merged. To avoid this, always run the app from the same directory, or set an absolute path for `RECORDS_FILE`.

**Q: Does the app store anything in a database?**
No. The only persistent storage is the plain text `discovered_servers.txt` file.

---

## 17. Troubleshooting

### "ModuleNotFoundError: No module named 'flask'"

```bash
pip install flask
# or
pip3 install flask
```

### "Address already in use" error

Another process is already using port 5000. Either stop that process or change the port:

```python
app.run(host="0.0.0.0", port=5001, ...)  # use a different port
```

On macOS, port 5000 is used by AirPlay Receiver. Disable it in System Preferences → Sharing, or use a different port.

### The scan indicator never disappears

The JavaScript polls `/api/scan_status` every 5 seconds. If the backend is unreachable or the scan thread crashes, the indicator stays visible. Reloading the page resets it.

### No servers found by the background scanner

This is normal if there are no Minecraft servers running on non-standard ports on that IP. The standard port (25565) is the only one most servers use.

### The slide panel shows all servers as offline

If all known servers suddenly show offline, the most likely cause is a network issue on your machine. Check your internet connection and try pinging one of the servers manually using the checker form.

### Chinese characters / special characters show as boxes in MOTD

The app uses UTF-8 throughout, but the HTML-escaped output depends on the browser's font. Some Minecraft servers include color codes (like `§a`, `§r`) in their MOTD. These are displayed as raw text — the app does not interpret Minecraft color formatting.

---

*Documentation generated for MC Server Radar v1.0 — single-file Python application.*
