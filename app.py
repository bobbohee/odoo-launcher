#!/usr/bin/env python3
"""Odoo Launcher - Start/Stop dev servers from browser. No external dependencies."""

import json
import os
import re
import signal
import socket
import subprocess
import sys
import threading
from collections import deque
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

BASE_DIR = Path(__file__).parent
PROJECTS_FILE = BASE_DIR / "projects.json"
DEFAULT_PORT = 9069


def get_launcher_port() -> int:
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--port" and i + 1 <= len(sys.argv) - 1:
            return int(sys.argv[i + 1])
        if arg.startswith("--port="):
            return int(arg.split("=", 1)[1])
    return DEFAULT_PORT

# Runtime state: {project_id: {"proc": Popen, "logs": deque, "cmd": str}}
running_procs: dict = {}
locks: dict = {}


def load_projects() -> list[dict]:
    if not PROJECTS_FILE.exists():
        with open(PROJECTS_FILE, "w") as f:
            json.dump([], f, indent=2)
        return []
    with open(PROJECTS_FILE) as f:
        projects = json.load(f)
    validated = []
    required_keys = ("id", "name", "port", "cwd", "python", "commands")
    for i, p in enumerate(projects):
        missing = [k for k in required_keys if k not in p]
        if missing:
            print(f"Warning: projects[{i}] ('{p.get('name', '?')}') missing keys: {missing}")
            continue
        cwd = os.path.expanduser(p["cwd"])
        if not os.path.isdir(cwd):
            print(f"Warning: projects[{i}] ('{p['name']}') cwd not found: {p['cwd']}")
            continue
        if not os.path.isfile(p["python"]):
            print(f"Warning: projects[{i}] ('{p['name']}') python not found: {p['python']}")
            continue
        validated.append(p)
    return validated


def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0




def resolve_logfile(proj: dict) -> str | None:
    logfile = proj.get("logfile")
    if not logfile:
        return None
    if os.path.isabs(logfile):
        return logfile
    return os.path.join(os.path.expanduser(proj["cwd"]), logfile)


def resolve_odoorc(proj: dict) -> str | None:
    odoorc = proj.get("odoorc")
    if not odoorc:
        return None
    if os.path.isabs(odoorc):
        return odoorc
    return os.path.join(os.path.expanduser(proj["cwd"]), odoorc)


def get_git_diff(cwd: str, filepath: str, context: int = 3) -> str:
    """Return git diff for a specific file."""
    cwd = os.path.expanduser(cwd)
    try:
        # Try tracked file diff first
        result = subprocess.run(
            ["git", "diff", f"-U{context}", "HEAD", "--", filepath],
            capture_output=True, text=True, timeout=5, cwd=cwd,
        )
        if result.stdout.strip():
            return result.stdout
        # Untracked file: show full content as additions
        result = subprocess.run(
            ["git", "diff", "--no-index", f"-U{context}", "/dev/null", filepath],
            capture_output=True, text=True, timeout=5, cwd=cwd,
        )
        return result.stdout if result.stdout.strip() else "(no diff available)"
    except Exception:
        return "(error reading diff)"


def get_git_branch(cwd: str) -> str:
    """Return current git branch name."""
    cwd = os.path.expanduser(cwd)
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=5, cwd=cwd,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""


def get_git_status(cwd: str) -> dict:
    """Return git status summary for a project directory."""
    cwd = os.path.expanduser(cwd)
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, timeout=5, cwd=cwd,
        )
        if result.returncode != 0:
            return {"total": 0, "files": []}
        files = []
        for line in result.stdout.strip().splitlines():
            if not line:
                continue
            status = line[:2].strip()
            filepath = line[2:].lstrip()
            label = {"M": "modified", "A": "added", "D": "deleted",
                     "R": "renamed", "??": "untracked"}.get(status, status)
            files.append({"status": label, "path": filepath})
        return {"total": len(files), "files": files}
    except Exception:
        return {"total": 0, "files": []}


def get_lock(project_id: str) -> threading.Lock:
    if project_id not in locks:
        locks[project_id] = threading.Lock()
    return locks[project_id]


def log_reader(project_id: str, proc: subprocess.Popen):
    buf = running_procs[project_id]["logs"]
    for line in iter(proc.stdout.readline, ""):
        if not line:
            break
        buf.append(line.rstrip("\n"))
    proc.stdout.close()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # suppress request logs

    def _json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, html):
        body = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _parse_path(self):
        return self.path.split("?")[0].rstrip("/")

    def do_GET(self):
        path = self._parse_path()

        if path == "" or path == "/":
            return self._html(HTML)

        if path == "/api/projects":
            projects = load_projects()
            result = []
            for p in projects:
                pid = p["id"]
                info = running_procs.get(pid)
                running = info is not None and info["proc"].poll() is None
                running_cmd = info["cmd"] if running else None

                port = p.get("port")
                if not running and port and is_port_in_use(port):
                    running = True

                git_cwd = os.path.join(p["cwd"], p["git_path"]) if p.get("git_path") else p["cwd"]
                git = get_git_status(git_cwd)
                branch = get_git_branch(git_cwd)
                result.append({
                    "id": p["id"],
                    "name": p["name"],
                    "host": p.get("host", "localhost"),
                    "port": port,
                    "commands": [c["name"] for c in p.get("commands", [])],
                    "running": running,
                    "running_cmd": running_cmd,
                    "git_changes": git["total"],
                    "git_branch": branch,
                    "has_odoorc": bool(p.get("odoorc")),
                })
            return self._json(result)

        m = re.match(r"^/api/projects/([^/]+)/git$", path)
        if m:
            project_id = m.group(1)
            projects = load_projects()
            proj = next((p for p in projects if p["id"] == project_id), None)
            if proj:
                git_cwd = os.path.join(proj["cwd"], proj["git_path"]) if proj.get("git_path") else proj["cwd"]
                return self._json(get_git_status(git_cwd))
            return self._json({"total": 0, "files": []})

        m = re.match(r"^/api/projects/([^/]+)/git-diff$", path)
        if m:
            project_id = m.group(1)
            # Parse query string for ?path=
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(self.path).query)
            filepath = qs.get("path", [""])[0]
            context = int(qs.get("context", ["3"])[0])
            if not filepath:
                return self._json({"diff": ""}, 400)
            projects = load_projects()
            proj = next((p for p in projects if p["id"] == project_id), None)
            if proj:
                git_cwd = os.path.join(proj["cwd"], proj["git_path"]) if proj.get("git_path") else proj["cwd"]
                return self._json({"diff": get_git_diff(git_cwd, filepath, context)})
            return self._json({"diff": ""}, 404)

        m = re.match(r"^/api/projects/([^/]+)/logs$", path)
        if m:
            project_id = m.group(1)
            projects = load_projects()
            proj = next((p for p in projects if p["id"] == project_id), None)
            if proj:
                logpath = resolve_logfile(proj)
                if logpath:
                    try:
                        with open(logpath, "rb") as f:
                            f.seek(0, 2)
                            size = f.tell()
                            f.seek(max(0, size - 65536))
                            lines = f.read().decode("utf-8", errors="replace").splitlines()
                            return self._json({"logs": lines[-200:]})
                    except FileNotFoundError:
                        return self._json({"logs": ["(log file not found)"]})
            # Fallback to stdout buffer
            if project_id in running_procs:
                return self._json({"logs": list(running_procs[project_id]["logs"])})
            return self._json({"logs": []})

        m = re.match(r"^/api/projects/([^/]+)/odoorc$", path)
        if m:
            project_id = m.group(1)
            projects = load_projects()
            proj = next((p for p in projects if p["id"] == project_id), None)
            if not proj or not proj.get("odoorc"):
                return self._json({"error": "not_found"}, 404)
            filepath = resolve_odoorc(proj)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
                return self._json({"content": content})
            except FileNotFoundError:
                return self._json({"content": ""}, 404)

        self.send_error(404)

    def do_POST(self):
        path = self._parse_path()

        m = re.match(r"^/api/projects/([^/]+)/run/(.+)$", path)
        if m:
            return self._handle_run(m.group(1), m.group(2))

        m = re.match(r"^/api/projects/([^/]+)/stop$", path)
        if m:
            return self._handle_stop(m.group(1))

        self.send_error(404)

    def do_PUT(self):
        path = self._parse_path()

        m = re.match(r"^/api/projects/([^/]+)/odoorc$", path)
        if m:
            project_id = m.group(1)
            projects = load_projects()
            proj = next((p for p in projects if p["id"] == project_id), None)
            if not proj or not proj.get("odoorc"):
                return self._json({"error": "not_found"}, 404)
            filepath = resolve_odoorc(proj)
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            content = body.get("content", "")
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            return self._json({"status": "saved"})

        self.send_error(404)

    def _handle_run(self, project_id, cmd_name):
        with get_lock(project_id):
            info = running_procs.get(project_id)
            if info and info["proc"].poll() is None:
                return self._json({"status": "already_running"}, 409)

            projects = load_projects()
            proj = next((p for p in projects if p["id"] == project_id), None)
            if not proj:
                return self._json({"status": "not_found"}, 404)

            cmd_entry = next((c for c in proj.get("commands", []) if c["name"] == cmd_name), None)
            if not cmd_entry:
                return self._json({"status": "command_not_found"}, 404)

            cwd = os.path.expanduser(proj["cwd"])
            odoorc_path = resolve_odoorc(proj) or ""
            run_cmd = cmd_entry["run"].replace("{odoorc}", odoorc_path)
            port_flag = f" --http-port={proj['port']}" if proj.get("port") else ""
            full_cmd = f"{proj['python']} {run_cmd}{port_flag}"

            proc = subprocess.Popen(
                full_cmd,
                shell=True,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                preexec_fn=os.setsid,
            )

            running_procs[project_id] = {"proc": proc, "logs": deque(maxlen=500), "cmd": cmd_name}
            t = threading.Thread(target=log_reader, args=(project_id, proc), daemon=True)
            t.start()

            return self._json({"status": "started", "pid": proc.pid})

    def _handle_stop(self, project_id):
        with get_lock(project_id):
            # Case 1: process tracked in memory
            info = running_procs.get(project_id)
            if info and info["proc"].poll() is None:
                proc = info["proc"]
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGINT)
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    proc.wait()
                except (ProcessLookupError, PermissionError):
                    pass
                return self._json({"status": "stopped"})

            # Case 2: not tracked but port is in use (e.g. after server restart)
            projects = load_projects()
            proj = next((p for p in projects if p["id"] == project_id), None)
            if proj and proj.get("port"):
                port = proj["port"]
                if port and is_port_in_use(port):
                    my_pid = os.getpid()
                    try:
                        result = subprocess.run(
                            ["lsof", "-ti", f"TCP:{port}", "-sTCP:LISTEN"],
                            capture_output=True, text=True, timeout=5,
                        )
                        pids = result.stdout.strip().split("\n")
                        for pid_str in pids:
                            pid_str = pid_str.strip()
                            if pid_str.isdigit():
                                pid = int(pid_str)
                                if pid == my_pid:
                                    continue
                                try:
                                    os.kill(pid, signal.SIGTERM)
                                except (ProcessLookupError, PermissionError):
                                    pass
                    except Exception:
                        pass
                    return self._json({"status": "stopped"})

            return self._json({"status": "not_running"}, 409)


# ── Frontend ─────────────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Launcher</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><path d='M25,18 L82,50 L25,82 Q14,88 14,75 L14,25 Q14,12 25,18Z' fill='%2322c55e'/></svg>">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css">
<style>
  :root {
    --bg: #f3f4f6; --card: #ffffff;
    --text: #191f28; --sub: #4e5968; --dim: #8b95a1; --muted: #d1d6db;
    --accent: #3182f6; --green: #30c85a; --red: #f04452; --yellow: #f09000;
    --btn-bg: #f2f4f6; --btn-hover: #e5e8eb;
  }
  [data-theme="dark"] {
    --bg: #17171b; --card: #212226;
    --text: #ececec; --sub: #8b95a1; --dim: #4e5968; --muted: #3a3a40;
    --accent: #3182f6; --green: #30c85a; --red: #f04452; --yellow: #f09000;
    --btn-bg: #2c2d32; --btn-hover: #37383d;
  }
  *, *::before, *::after { margin: 0; padding: 0; box-sizing: border-box; }
  html { height: 100%; overflow: hidden; }
  body {
    height: 100%; overflow: hidden; margin: 0; padding: 32px;
    display: flex;
    font-family: -apple-system, BlinkMacSystemFont, 'Pretendard', 'Segoe UI', sans-serif;
    background: var(--bg); color: var(--text); transition: background .25s, color .25s;
    -webkit-font-smoothing: antialiased;
  }

  .layout { flex: 1; display: flex; flex-direction: column; gap: 24px; min-height: 0; min-width: 0; }

  /* Header */
  .header { flex-shrink: 0; display: flex; align-items: center; position: relative; padding: 0 4px; }
  h1 { font-size: 24px; font-weight: 700; color: var(--text); letter-spacing: -0.5px; }

  .header-actions { position: absolute; right: 0; display: flex; gap: 4px; align-items: center; }
  .header-btn { width: 36px; height: 36px; border-radius: 50%; border: none;
    background: transparent; display: flex; align-items: center; justify-content: center;
    cursor: pointer; color: var(--dim); transition: all .15s; }
  .header-btn:hover { color: var(--text); }
  .header-btn:active { transform: scale(.93); }
  .header-btn i { font-size: 15px; }

  /* Content */
  .content { flex: 1; display: flex; gap: 20px; min-height: 0; }
  .content.swapped .cards { order: 2; }
  .content.swapped .log-panel { order: 1; }

  /* Cards */
  .cards { flex: 1; min-height: 0; min-width: 600px; overflow-y: auto; display: flex; flex-direction: column; gap: 16px; }
  .cards::-webkit-scrollbar { width: 4px; }
  .cards::-webkit-scrollbar-thumb { background: var(--muted); border-radius: 4px; }
  .card {
    background: var(--card); border-radius: 16px; padding: 20px 24px; display: flex; align-items: center; gap: 16px;
    flex-shrink: 0; transition: background .15s;
  }

  /* Status dot */
  .dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; margin-right: 4px; transition: all .3s; }
  .dot.off { background: var(--muted); }
  .dot.on  { background: var(--green); box-shadow: 0 0 8px rgba(48,200,90,.35); }

  /* Info */
  .info { flex: 1; min-width: 0; }
  .name { font-size: 16px; font-weight: 600; letter-spacing: -0.3px; display: flex; align-items: center; gap: 8px; min-width: 0; }
  .branch { font-family: 'SF Mono', 'Menlo', monospace; font-size: 12px; font-weight: 500; padding: 1px 8px; border-radius: 10px;
    background: #f0f0f0; color: #6b7280; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex-shrink: 1; min-width: 0; }
  .branch.dirty { background: #fef3c7; color: #d97706; }
  [data-theme="dark"] .branch { background: rgba(255,255,255,.08); color: #9ca3af; }
  [data-theme="dark"] .branch.dirty { background: rgba(240,144,0,.15); color: #fbbf24; }
  .badge { font-size: 11px; font-weight: 600; width: 20px; height: 20px; border-radius: 50%;
    display: inline-flex; align-items: center; justify-content: center;
    background: #fef3c7; color: #d97706; }
  [data-theme="dark"] .badge { background: rgba(240,144,0,.15); color: #fbbf24; }
  .url  { font-size: 13px; color: var(--dim); margin-top: 3px; text-decoration: none; display: inline-block; transition: color .15s; }
  .url:hover { color: var(--accent); }

  /* Actions */
  .actions { display: flex; gap: 6px; flex-shrink: 0; align-items: center; }
  .mode-select {
    appearance: none; -webkit-appearance: none;
    background: var(--btn-bg); border: none; border-radius: 8px;
    color: var(--sub); font-family: inherit; font-size: 13px; font-weight: 500;
    height: 36px; min-width: 116px; padding: 0 28px 0 12px; cursor: pointer; outline: none; transition: background .15s;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='10' viewBox='0 0 24 24' fill='none' stroke='%238b95a1' stroke-width='2.5'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E");
    background-repeat: no-repeat; background-position: right 10px center;
  }
  .mode-select:hover { background: var(--btn-hover); }
  .mode-select:disabled { opacity: .35; cursor: not-allowed; }
  .mode-select option { background: var(--card); color: var(--text); }

  /* Buttons */
  .btn {
    width: 36px; height: 36px; border-radius: 8px; border: none; background: var(--btn-bg);
    display: flex; align-items: center; justify-content: center; cursor: pointer;
    transition: background .15s; color: var(--sub);
  }
  .btn:hover { background: var(--btn-hover); }
  .btn:active { transform: scale(.95); }
  .btn:disabled { opacity: .25; cursor: not-allowed; transform: none; }
  .btn.start { color: #15803d; background: #dcfce7; font-size: 11px; }
  .btn.start:hover { background: #bbf7d0; }
  .btn.stop  { color: #dc2626; background: #fee2e2; }
  .btn.stop:hover  { background: #fecaca; }
  .btn.restart { color: #15803d; background: #dcfce7; }
  .btn.restart:hover { background: #bbf7d0; }
  [data-theme="dark"] .btn.start { color: #4ade80; background: rgba(48,200,90,.15); }
  [data-theme="dark"] .btn.start:hover { background: rgba(48,200,90,.25); }
  [data-theme="dark"] .btn.stop  { color: #fb7185; background: rgba(240,68,82,.15); }
  [data-theme="dark"] .btn.stop:hover  { background: rgba(240,68,82,.25); }
  [data-theme="dark"] .btn.restart { color: #4ade80; background: rgba(48,200,90,.15); }
  [data-theme="dark"] .btn.restart:hover { background: rgba(48,200,90,.25); }
  .btn.git { color: var(--dim); }
  .btn.git:hover { color: #d97706; background: #fef3c7; }
  [data-theme="dark"] .btn.git:hover { color: #fbbf24; background: rgba(240,144,0,.15); }
  .btn.git.active { color: #d97706; background: #fef3c7; }
  .btn.git.active:hover { background: #fde68a; }
  [data-theme="dark"] .btn.git.active { color: #fbbf24; background: rgba(240,144,0,.15); }
  [data-theme="dark"] .btn.git.active:hover { background: rgba(240,144,0,.25); }
  .btn.logs { color: var(--dim); }
  .btn.logs:hover { color: #1d8cf8; background: #e0f0ff; }
  [data-theme="dark"] .btn.logs:hover { color: #4dabf7; background: rgba(77,171,247,.15); }
  .btn.logs.active { color: #1d8cf8; background: #e0f0ff; }
  .btn.logs.active:hover { background: #c7e2ff; }
  [data-theme="dark"] .btn.logs.active { color: #4dabf7; background: rgba(77,171,247,.15); }
  [data-theme="dark"] .btn.logs.active:hover { background: rgba(77,171,247,.25); }
  .odoorc-btn { cursor: pointer; color: var(--dim); font-size: 12px; transition: color .15s; flex-shrink: 0; }
  .odoorc-btn:hover { color: var(--accent); }
  .odoorc-btn.active { color: var(--accent); }
  .odoorc-editor { display: flex; flex-direction: column; flex: 1; min-height: 0; gap: 12px; }
  .odoorc-editor textarea {
    flex: 1; min-height: 0; width: 100%; resize: none; border: 1px solid var(--muted); border-radius: 8px;
    background: var(--bg); color: var(--text); padding: 14px; font-family: 'SF Mono', 'Menlo', monospace;
    font-size: 12px; line-height: 1.7; outline: none; transition: border-color .15s;
  }
  .odoorc-editor textarea:focus { border-color: var(--accent); }
  .odoorc-toolbar { display: flex; align-items: center; gap: 10px; }
  .odoorc-save {
    padding: 6px 18px; border-radius: 8px; border: none; background: var(--accent); color: #fff;
    font-family: inherit; font-size: 13px; font-weight: 600; cursor: pointer; transition: opacity .15s;
  }
  .odoorc-save:hover { opacity: .85; }
  .odoorc-save:disabled { opacity: .5; cursor: not-allowed; }
  .odoorc-msg { font-size: 12px; color: var(--green); }
  .odoorc-msg.error { color: var(--red); }
  .btn i { font-size: 13px; }
  .btn.loading i { animation: spin 1.2s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* Loading */
  .loading-screen {
    position: fixed; top: 0; left: 0; right: 0; bottom: 0;
    background: var(--bg); display: flex; align-items: center; justify-content: center;
    z-index: 100; transition: opacity .3s;
  }
  .loading-screen.hide { opacity: 0; pointer-events: none; }
  .loading-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--dim); margin: 0 4px; animation: bounce .6s ease-in-out infinite; }
  .loading-dot:nth-child(2) { animation-delay: .1s; }
  .loading-dot:nth-child(3) { animation-delay: .2s; }
  @keyframes bounce { 0%, 100% { opacity: .3; transform: scale(.8); } 50% { opacity: 1; transform: scale(1); } }

  /* Log panel */
  .log-panel {
    flex: 2; min-height: 0; min-width: 0; display: flex; flex-direction: column;
    background: var(--card); border-radius: 16px; overflow: hidden;
  }
  .log-header { padding: 18px 24px; font-weight: 600; font-size: 15px; flex-shrink: 0; color: var(--text); }
  .log-body {
    flex: 1; min-height: 0; overflow-y: auto; overflow-x: hidden;
    padding: 0 24px 18px; font-family: 'SF Mono', 'Menlo', monospace; font-size: 12px; line-height: 1.7;
    color: var(--sub); white-space: pre-wrap; word-break: break-all;
    display: flex; flex-direction: column;
  }
  .log-body::-webkit-scrollbar { width: 4px; height: 4px; }
  .log-body::-webkit-scrollbar-thumb { background: var(--muted); border-radius: 4px; }

  /* Git file list */
  .git-file { padding: 6px 0; cursor: pointer; display: flex; gap: 10px; border-bottom: 1px solid var(--btn-bg); transition: color .15s; }
  .git-file:last-child { border-bottom: none; }
  .git-file:hover { color: var(--accent); }
  .git-file .tag { width: 18px; flex-shrink: 0; font-weight: 700; }
  .git-file .tag.m { color: #d97706; }
  .git-file .tag.a { color: #15803d; }
  .git-file .tag.d { color: #dc2626; }
  .git-file .tag.u { color: var(--dim); }
  [data-theme="dark"] .git-file .tag.m { color: #fbbf24; }
  [data-theme="dark"] .git-file .tag.a { color: #4ade80; }
  [data-theme="dark"] .git-file .tag.d { color: #fb7185; }

  /* Diff view */
  .diff-wrap { overflow-x: auto; flex: 1 0 auto; margin-bottom: -18px; }
  .diff-wrap::-webkit-scrollbar { height: 4px; }
  .diff-wrap::-webkit-scrollbar-thumb { background: var(--muted); border-radius: 4px; }
  .diff-inner { display: inline-block; min-width: 100%; padding-bottom: 18px; }
  .diff-line { padding: 0 4px; white-space: pre; display: flex; }
  .diff-ln { display: inline-block; width: 36px; text-align: right; padding-right: 8px; color: var(--muted); user-select: none; flex-shrink: 0; }
  .diff-code { flex: 1; }
  .diff-add { background: rgba(34,197,94,.15); color: #15803d; }
  .diff-del { background: rgba(239,68,68,.15); color: #dc2626; }
  .diff-hunk { color: var(--accent); font-weight: 600; padding-top: 8px; }
  [data-theme="dark"] .diff-add { background: rgba(74,222,128,.1); color: #4ade80; }
  [data-theme="dark"] .diff-del { background: rgba(251,113,133,.1); color: #fb7185; }
  .diff-toolbar { display: flex; align-items: center; justify-content: space-between; padding-bottom: 10px; border-bottom: 1px solid var(--btn-bg); margin-bottom: 6px; }
  .diff-back { cursor: pointer; color: var(--accent); }
  .diff-back:hover { text-decoration: underline; }
  .diff-ctx { display: flex; align-items: center; gap: 4px; }
  .diff-ctx-btn {
    border: none; background: var(--btn-bg); color: var(--sub); font-family: inherit;
    font-size: 11px; font-weight: 500; padding: 3px 8px; border-radius: 6px;
    cursor: pointer; transition: all .15s;
  }
  .diff-ctx-btn:hover { background: var(--btn-hover); }
  .diff-ctx-btn.active { color: var(--accent); background: #dbeafe; }
  [data-theme="dark"] .diff-ctx-btn.active { background: rgba(49,130,246,.15); }

  /* Mobile */
  @media (max-width: 1200px) {
    body { padding: 20px; }
    .layout { gap: 16px; }
    h1 { font-size: 20px; }
    .content { flex-direction: column; gap: 16px; }
    .cards { flex: none; max-height: 45%; overflow-y: auto; }
    .card { padding: 16px 18px; gap: 12px; border-radius: 14px; }
    .name { font-size: 14px; }
    .url { font-size: 12px; }
    .dot { width: 9px; height: 9px; }
    .actions { gap: 5px; }
    .mode-select { min-width: 96px; height: 32px; font-size: 12px; padding: 0 24px 0 10px; border-radius: 7px; }
    .btn { width: 32px; height: 32px; border-radius: 7px; }
    .btn svg { width: 13px; height: 13px; }
    .log-panel { flex: 1; min-height: 0; border-radius: 14px; }
    .log-header { padding: 14px 18px; font-size: 14px; }
    .log-body { padding: 0 18px 14px; font-size: 11px; }
    .diff-wrap { margin-bottom: -14px; }
    .diff-inner { padding-bottom: 14px; }
    .header-btn { width: 32px; height: 32px; }
    .header-btn i { font-size: 13px; }
  }
</style>
</head>
<body>

<div class="loading-screen" id="loading">
  <div class="loading-dot"></div>
  <div class="loading-dot"></div>
  <div class="loading-dot"></div>
</div>

<div class="layout">
  <div class="header">
    <h1>Launcher</h1>
    <div class="header-actions">
      <button class="header-btn" onclick="toggleSwap()" title="Swap layout">
        <i class="fa-solid fa-right-left"></i>
      </button>
      <button class="header-btn" onclick="toggleTheme()" title="Toggle theme">
        <i id="theme-icon" class="fa-solid fa-moon"></i>
      </button>
    </div>
  </div>
  <div class="content">
    <div class="cards" id="grid"></div>
    <div class="log-panel">
      <div class="log-header"><span id="log-title">Log</span></div>
      <div class="log-body" id="log-body">Select a project log to view.</div>
    </div>
  </div>
</div>

<script>
const $ = s => document.querySelector(s);
let projects = [];
let logInterval = null;
let modes = {};  // {projectId: 'command-name'}

function setMode(id, mode) { modes[id] = mode; }
function getDisplayMode(p) {
  if (p.running && p.running_cmd) return p.running_cmd;
  return modes[p.id] || (p.commands[0] || '');
}

async function load() {
  const res = await fetch('/api/projects');
  projects = await res.json();
  render();
  const el = $('#loading');
  if (el && !el.classList.contains('hide')) {
    el.classList.add('hide');
    setTimeout(() => el.remove(), 300);
  }
}

function render() {
  $('#grid').innerHTML = projects.map(p => {
    const mode = getDisplayMode(p);
    return `
    <div class="card" id="card-${p.id}">
      <div class="dot ${p.running ? 'on' : 'off'}"></div>
      <div class="info">
        <div class="name">${p.name}${p.git_branch ? `<span class="branch${p.git_changes ? ' dirty' : ''}"><i class="fa-solid fa-code-branch" style="margin-right:5px;font-size:10px"></i>${p.git_branch}</span>` : ''}</div>
        ${p.port ? `<a class="url" href="http://${p.host}:${p.port}/web" target="_blank" onclick="event.stopPropagation()">${p.host}:${p.port}</a>` : ''}
      </div>
      <div class="actions">
        <select class="mode-select" id="mode-${p.id}"
                ${p.running ? 'disabled' : ''}
                onchange="setMode('${p.id}', this.value)">
          ${p.commands.map(c => `<option value="${c}" ${mode === c ? 'selected' : ''}>${c}</option>`).join('')}
        </select>
        ${p.running
          ? `<button class="btn restart" onclick="restart('${p.id}')" title="Restart">
               <i class="fa-solid fa-rotate-right"></i>
             </button>
             <button class="btn stop" onclick="stop('${p.id}')" title="Stop">
               <i class="fa-solid fa-stop"></i>
             </button>`
          : `<button class="btn start" onclick="run('${p.id}')" title="Run">
               <i class="fa-solid fa-play"></i>
             </button>`
        }
        <button class="btn git ${activeGitId === p.id ? 'active' : ''}" onclick="openGit('${p.id}','${p.name}')" title="Git changes">
          <i class="fa-solid fa-code-branch"></i>
        </button>
        <button class="btn logs ${activeLogId === p.id ? 'active' : ''}" onclick="openLog('${p.id}','${p.name}')" title="Logs">
          <i class="fa-solid fa-terminal"></i>
        </button>
      </div>
    </div>`;
  }).join('');
}

async function run(id) {
  const mode = modes[id] || projects.find(p => p.id === id)?.commands[0] || '';
  setLoading(id, true);
  await fetch(`/api/projects/${id}/run/${encodeURIComponent(mode)}`, {method:'POST'});
  await load();
  if (activeLogId !== id) {
    const p = projects.find(p => p.id === id);
    if (p) openLog(id, p.name);
  }
}

async function stop(id) {
  setLoading(id, true);
  await fetch(`/api/projects/${id}/stop`, {method:'POST'});
  await load();
}

async function restart(id) {
  setLoading(id, true);
  await fetch(`/api/projects/${id}/stop`, {method:'POST'});
  const mode = modes[id] || projects.find(p => p.id === id)?.commands[0] || '';
  await fetch(`/api/projects/${id}/run/${encodeURIComponent(mode)}`, {method:'POST'});
  await load();
}

function setLoading(id, on) {
  const card = $(`#card-${id}`);
  if (!card) return;
  card.querySelectorAll('.btn').forEach(b => { b.disabled = on; b.classList.toggle('loading', on); });
}

let activeLogId = null;
let activeGitId = null;

function clearPanel() {
  clearInterval(logInterval);
  activeLogId = null;
  activeGitId = null;
  $('#log-title').textContent = 'Log';
  $('#log-body').textContent = 'Select a project log to view.';
  document.querySelectorAll('.btn.logs').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.btn.git').forEach(b => b.classList.remove('active'));
}

function esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

async function openGit(id, name) {
  const wasActive = activeGitId === id;
  clearPanel();

  if (wasActive) {
    render();
    return;
  }
  activeGitId = id;
  $('#log-title').textContent = name + ' \u2014 Git Changes';
  $('#log-body').textContent = 'Loading...';
  render();

  const res = await fetch(`/api/projects/${id}/git`);
  const data = await res.json();
  if (data.files.length === 0) {
    $('#log-body').textContent = '(no changes)';
    return;
  }
  renderGitFiles(id, name, data.files);
}

function renderGitFiles(id, name, files) {
  const tagMap = {modified:'M', added:'A', deleted:'D', renamed:'R', untracked:'?'};
  const clsMap = {modified:'m', added:'a', deleted:'d', untracked:'u'};
  const html = files.map(f => {
    const tag = tagMap[f.status] || f.status;
    const cls = clsMap[f.status] || '';
    return `<div class="git-file" onclick="openGitDiff('${esc(id)}','${esc(name)}','${esc(f.path)}')"><span class="tag ${cls}">${esc(tag)}</span><span>${esc(f.path)}</span></div>`;
  }).join('');
  $('#log-body').innerHTML = html;
}

async function backToGitFiles(id, name) {
  $('#log-title').textContent = name + ' \u2014 Git Changes';
  $('#log-body').textContent = 'Loading...';
  const res = await fetch(`/api/projects/${id}/git`);
  const data = await res.json();
  if (data.files.length === 0) {
    $('#log-body').textContent = '(no changes)';
    return;
  }
  renderGitFiles(id, name, data.files);
}

let diffContext = 5;

async function openGitDiff(id, name, filepath, ctx) {
  if (ctx !== undefined) diffContext = ctx;
  $('#log-title').textContent = name + ' \u2014 ' + filepath.split('/').pop();
  $('#log-body').textContent = 'Loading diff...';

  const res = await fetch(`/api/projects/${id}/git-diff?path=${encodeURIComponent(filepath)}&context=${diffContext}`);
  const data = await res.json();
  const diff = data.diff || '(no diff)';

  let oldLn = 0, newLn = 0;
  const lines = diff.split('\n').map(line => {
    const e = esc(line);
    if (line.startsWith('diff ') || line.startsWith('index ') || line.startsWith('---') || line.startsWith('+++')) return '';
    if (line.startsWith('@@')) {
      const m = line.match(/@@ -(\d+).*?\+(\d+)/);
      if (m) { oldLn = parseInt(m[1]); newLn = parseInt(m[2]); }
      return `<div class="diff-line diff-hunk"><span class="diff-ln"></span><span class="diff-ln"></span><span class="diff-code">${e}</span></div>`;
    }
    if (line.startsWith('+') && !line.startsWith('+++')) {
      const ln = newLn++;
      return `<div class="diff-line diff-add"><span class="diff-ln"></span><span class="diff-ln">${ln}</span><span class="diff-code">${e}</span></div>`;
    }
    if (line.startsWith('-') && !line.startsWith('---')) {
      const ln = oldLn++;
      return `<div class="diff-line diff-del"><span class="diff-ln">${ln}</span><span class="diff-ln"></span><span class="diff-code">${e}</span></div>`;
    }
    const oLn = oldLn++, nLn = newLn++;
    return `<div class="diff-line"><span class="diff-ln">${oLn}</span><span class="diff-ln">${nLn}</span><span class="diff-code">${e}</span></div>`;
  }).join('');

  const ctxOptions = [5, 10, 25, 'All'].map(v => {
    const val = v === 'All' ? 99999 : v;
    const active = diffContext === val ? ' active' : '';
    return `<button class="diff-ctx-btn${active}" onclick="openGitDiff('${esc(id)}','${esc(name)}','${esc(filepath)}',${val})">${v}</button>`;
  }).join('');

  const toolbar = `<div class="diff-toolbar"><span class="diff-back" onclick="backToGitFiles('${esc(id)}','${esc(name)}')">\u2190 Back to file list</span><div class="diff-ctx">${ctxOptions}</div></div>`;
  $('#log-body').innerHTML = toolbar + `<div class="diff-wrap"><div class="diff-inner">${lines}</div></div>`;
}

async function openLog(id, name) {
  const wasActive = activeLogId === id;
  clearPanel();

  if (wasActive) {
    render();
    return;
  }

  activeLogId = id;
  $('#log-title').textContent = name + ' \u2014 Logs';
  render();

  const fetchLogs = async () => {
    const res = await fetch(`/api/projects/${id}/logs`);
    const {logs} = await res.json();
    const body = $('#log-body');
    body.textContent = logs.join('\n') || '(no output yet)';
    body.scrollTop = body.scrollHeight;
  };
  await fetchLogs();
  logInterval = setInterval(fetchLogs, 2000);
}

function toggleSwap() {
  const content = document.querySelector('.content');
  content.classList.toggle('swapped');
  localStorage.setItem('swapped', content.classList.contains('swapped'));
}

function toggleTheme() {
  const html = document.documentElement;
  const isLight = html.getAttribute('data-theme') === 'light';
  html.setAttribute('data-theme', isLight ? 'dark' : 'light');
  localStorage.setItem('theme', isLight ? 'dark' : 'light');
  updateThemeIcon();
}

function updateThemeIcon() {
  const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
  const icon = document.getElementById('theme-icon');
  icon.className = isDark ? 'fa-solid fa-sun' : 'fa-solid fa-moon';
}

// Apply saved layout
if (localStorage.getItem('swapped') === 'true') {
  document.querySelector('.content').classList.add('swapped');
}

// Apply saved theme
const saved = localStorage.getItem('theme') || 'light';
document.documentElement.setAttribute('data-theme', saved);
updateThemeIcon();

// Prevent all page-level scrolling
window.scrollTo(0, 0);
document.addEventListener('scroll', () => window.scrollTo(0, 0), true);
document.addEventListener('wheel', e => {
  if (!e.target.closest('.cards, .log-body')) e.preventDefault();
}, { passive: false });

load();
setInterval(load, 5000);
</script>
</body>
</html>
"""

if __name__ == "__main__":
    port = get_launcher_port()
    server = HTTPServer(("127.0.0.1", port), Handler)
    print(f"Odoo Launcher running at http://127.0.0.1:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        for pid, info in running_procs.items():
            if info["proc"].poll() is None:
                try:
                    os.killpg(os.getpgid(info["proc"].pid), signal.SIGTERM)
                except ProcessLookupError:
                    pass
        server.server_close()
