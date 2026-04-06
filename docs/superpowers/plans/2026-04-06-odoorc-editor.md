# .odoorc 편집 기능 구현 플랜

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 웹 UI에서 각 프로젝트의 `.odoorc` 파일을 읽고 편집/저장할 수 있는 기능 추가

**Architecture:** `app.py` 단일 파일에 백엔드 API 2개(GET/PUT)와 프론트엔드 에디터 UI를 추가한다. 기존 로그 패널을 재활용하여 textarea 기반 에디터를 표시하고, commands의 `{odoorc}` 플레이스홀더를 런타임에 치환한다.

**Tech Stack:** Python 표준 라이브러리, 인라인 HTML/CSS/JS (프레임워크 없음)

**Spec:** `docs/superpowers/specs/2026-04-06-odoorc-editor-design.md`

---

### Task 1: odoorc 경로 해석 헬퍼 함수 추가

**Files:**
- Modify: `app.py:67-73` (`resolve_logfile` 근처에 추가)

- [ ] **Step 1: `resolve_odoorc` 함수 작성**

`resolve_logfile`과 동일한 패턴으로, 프로젝트의 `odoorc` 필드를 절대경로로 해석하는 함수를 추가한다.
`app.py`에서 `resolve_logfile` 함수 바로 아래에 삽입:

```python
def resolve_odoorc(proj: dict) -> str | None:
    odoorc = proj.get("odoorc")
    if not odoorc:
        return None
    if os.path.isabs(odoorc):
        return odoorc
    return os.path.join(os.path.expanduser(proj["cwd"]), odoorc)
```

- [ ] **Step 2: 서버 실행하여 기존 기능 정상 동작 확인**

Run: `python3 app.py --port 9069`
Expected: 기존 기능 정상 동작, 에러 없음 (Ctrl+C로 종료)

- [ ] **Step 3: Commit**

```bash
git add app.py
git commit -m "[ADD] resolve_odoorc 헬퍼 함수 추가"
```

---

### Task 2: {odoorc} 변수 치환 로직 추가

**Files:**
- Modify: `app.py:286-288` (`_handle_run` 메서드 내 `full_cmd` 생성 부분)

- [ ] **Step 1: `_handle_run`에서 `{odoorc}` 치환 로직 추가**

`app.py:288`의 `full_cmd` 생성 라인 직전에 odoorc 경로를 해석하고, `cmd_entry['run']`에서 `{odoorc}`를 치환한다:

```python
            cwd = os.path.expanduser(proj["cwd"])
            odoorc_path = resolve_odoorc(proj) or ""
            run_cmd = cmd_entry["run"].replace("{odoorc}", odoorc_path)
            port_flag = f" --http-port={proj['port']}" if proj.get("port") else ""
            full_cmd = f"{proj['python']} {run_cmd}{port_flag}"
```

기존 코드에서 변경되는 부분:
- `cmd_entry['run']` → `run_cmd` (치환된 커맨드 사용)
- `odoorc_path` 변수 추가

- [ ] **Step 2: `projects.example.json` 업데이트**

`projects.example.json`의 commands에서 하드코딩된 경로를 `{odoorc}`로 변경:

```json
[
  {
    "id": "my-odoo",
    "name": "My Odoo",
    "host": "my-odoo.local",
    "port": 8069,
    "cwd": "/path/to/odoo-project",
    "git_path": "src",
    "odoorc": "config/.odoorc",
    "python": "/path/to/.pyenv/versions/my-env/bin/python",
    "logfile": "config/log/odooserver.log",
    "commands": [
      { "name": "odoo-bin", "run": "odoo-bin --config={odoorc}" },
      { "name": "dev", "run": "odoo-bin --config={odoorc} --dev=all" },
      { "name": "update", "run": "odoo-bin --config={odoorc} -u my_module" }
    ]
  }
]
```

- [ ] **Step 3: 서버 실행하여 프로젝트 시작 정상 동작 확인**

Run: `python3 app.py --port 9069`
Expected: 프로젝트 Run 버튼 클릭 시 `{odoorc}`가 실제 경로로 치환되어 실행됨

- [ ] **Step 4: Commit**

```bash
git add app.py projects.example.json
git commit -m "[ADD] commands에서 {odoorc} 변수 치환 지원"
```

---

### Task 3: GET/PUT /api/projects/{id}/odoorc 엔드포인트 추가

**Files:**
- Modify: `app.py:172-256` (`do_GET` 메서드에 라우트 추가)
- Modify: `app.py:258-269` (`do_POST` → `do_PUT` 지원 추가)

- [ ] **Step 1: `/api/projects` 응답에 `has_odoorc` 필드 추가**

`app.py`의 `do_GET` 메서드에서 `/api/projects` 응답을 생성하는 부분(약 194-204줄)의 `result.append` 딕셔너리에 `has_odoorc` 필드를 추가:

```python
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
```

- [ ] **Step 2: `GET /api/projects/{id}/odoorc` 라우트 추가**

`do_GET` 메서드에서 `/api/projects/{id}/logs` 라우트 바로 아래(약 254줄), `self.send_error(404)` 직전에 추가:

```python
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
```

- [ ] **Step 3: `do_PUT` 메서드 추가**

`do_POST` 메서드 바로 아래에 `do_PUT` 메서드를 새로 추가:

```python
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
```

- [ ] **Step 4: curl로 API 동작 확인**

서버 실행 후 별도 터미널에서:

```bash
# 읽기 테스트 (프로젝트 ID를 실제 값으로 대체)
curl -s http://127.0.0.1:9069/api/projects/my-odoo/odoorc | python3 -m json.tool

# 저장 테스트
curl -s -X PUT http://127.0.0.1:9069/api/projects/my-odoo/odoorc \
  -H "Content-Type: application/json" \
  -d '{"content": "[options]\ndb_name = test"}' | python3 -m json.tool
```

Expected: 읽기 시 `{"content": "..."}`, 저장 시 `{"status": "saved"}`

- [ ] **Step 5: Commit**

```bash
git add app.py
git commit -m "[ADD] GET/PUT /api/projects/{id}/odoorc API 엔드포인트"
```

---

### Task 4: 프론트엔드 CSS 추가

**Files:**
- Modify: `app.py:469-483` (CSS 영역, `.btn.logs` 스타일 아래)

- [ ] **Step 1: `.odoorc-btn` 및 에디터 CSS 추가**

`app.py` HTML 내 CSS에서 `.btn.logs.active:hover` 블록(약 482줄) 바로 아래, `.btn i` 앞에 추가:

```css
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
```

- [ ] **Step 2: Commit**

```bash
git add app.py
git commit -m "[ADD] .odoorc 에디터 CSS 스타일"
```

---

### Task 5: 프론트엔드 JS — 프로젝트 이름 옆 ⚙ 아이콘 및 에디터 로직

**Files:**
- Modify: `app.py:630-665` (JS `render()` 함수)
- Modify: `app.py:699-710` (JS 상태 변수 및 `clearPanel()`)
- Modify: `app.py:860-863` 근처 (JS 끝부분에 함수 추가)

- [ ] **Step 1: `render()` 함수에서 카드 HTML에 ⚙ 아이콘 추가**

`render()` 함수 내 카드 템플릿에서 프로젝트 이름(`${p.name}`) 뒤, branch 표시 앞에 조건부 ⚙ 아이콘을 추가한다.

기존 코드 (약 637줄):
```javascript
        <div class="name">${p.name}${p.git_branch ? `<span class="branch...
```

변경 후:
```javascript
        <div class="name">${p.name}${p.has_odoorc ? `<span class="odoorc-btn ${activeOdoorcId === p.id ? 'active' : ''}" onclick="event.stopPropagation();openOdoorc('${p.id}','${p.name}')" title=".odoorc"><i class="fa-solid fa-gear"></i></span>` : ''}${p.git_branch ? `<span class="branch${p.git_changes ? ' dirty' : ''}"><i class="fa-solid fa-code-branch" style="margin-right:5px;font-size:10px"></i>${p.git_branch}</span>` : ''}</div>
```

- [ ] **Step 2: 상태 변수 및 `clearPanel()` 업데이트**

`activeGitId` 선언(약 700줄) 아래에 `activeOdoorcId` 추가:

```javascript
let activeOdoorcId = null;
```

`clearPanel()` 함수에 odoorc 초기화 추가. 기존 함수:
```javascript
function clearPanel() {
  clearInterval(logInterval);
  activeLogId = null;
  activeGitId = null;
  $('#log-title').textContent = 'Log';
  $('#log-body').textContent = 'Select a project log to view.';
  document.querySelectorAll('.btn.logs').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.btn.git').forEach(b => b.classList.remove('active'));
}
```

변경 후:
```javascript
function clearPanel() {
  clearInterval(logInterval);
  activeLogId = null;
  activeGitId = null;
  activeOdoorcId = null;
  $('#log-title').textContent = 'Log';
  $('#log-body').textContent = 'Select a project log to view.';
  document.querySelectorAll('.btn.logs').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.btn.git').forEach(b => b.classList.remove('active'));
}
```

- [ ] **Step 3: `openOdoorc()` 및 `saveOdoorc()` 함수 추가**

JS 영역 끝부분, `load();` 호출(약 862줄) 직전에 추가:

```javascript
async function openOdoorc(id, name) {
  const wasActive = activeOdoorcId === id;
  clearPanel();

  if (wasActive) {
    render();
    return;
  }
  activeOdoorcId = id;
  $('#log-title').textContent = name + ' \u2014 .odoorc';
  $('#log-body').textContent = 'Loading...';
  render();

  const res = await fetch(`/api/projects/${id}/odoorc`);
  const data = await res.json();
  const content = data.content || '';

  $('#log-body').innerHTML = `<div class="odoorc-editor">
    <textarea id="odoorc-ta" spellcheck="false">${esc(content)}</textarea>
    <div class="odoorc-toolbar">
      <button class="odoorc-save" onclick="saveOdoorc('${esc(id)}')">Save</button>
      <span class="odoorc-msg" id="odoorc-msg"></span>
    </div>
  </div>`;
}

async function saveOdoorc(id) {
  const ta = $('#odoorc-ta');
  const btn = document.querySelector('.odoorc-save');
  const msg = $('#odoorc-msg');
  if (!ta || !btn) return;
  btn.disabled = true;
  msg.textContent = '';
  msg.className = 'odoorc-msg';

  try {
    const res = await fetch(`/api/projects/${id}/odoorc`, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({content: ta.value}),
    });
    if (res.ok) {
      msg.textContent = 'Saved!';
    } else {
      msg.textContent = 'Save failed';
      msg.classList.add('error');
    }
  } catch (e) {
    msg.textContent = 'Save failed';
    msg.classList.add('error');
  }
  btn.disabled = false;
  setTimeout(() => { msg.textContent = ''; }, 2000);
}
```

- [ ] **Step 4: 브라우저에서 전체 기능 검증**

서버 실행 후 브라우저에서:
1. `odoorc` 필드가 있는 프로젝트 이름 옆에 ⚙ 아이콘 표시 확인
2. ⚙ 클릭 → 오른쪽 패널에 .odoorc 내용 표시 확인
3. 내용 편집 후 Save 버튼 클릭 → "Saved!" 메시지 확인
4. 다시 ⚙ 클릭 → 변경된 내용 반영 확인
5. ⚙ 재클릭 → 패널 닫힘 확인
6. Logs/Git 버튼과 상호 전환 정상 동작 확인
7. 다크 모드 전환 시 에디터 스타일 정상 확인

- [ ] **Step 5: Commit**

```bash
git add app.py
git commit -m "[ADD] .odoorc 편집 UI (프론트엔드)"
```
