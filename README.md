# Odoo Launcher

Odoo 개발 서버를 브라우저에서 시작/종료할 수 있는 경량 런처입니다.

- Python 표준 라이브러리만 사용 (외부 의존성 없음)
- 메모리 ~8MB, CPU ~0%
- macOS LaunchAgent로 로그인 시 자동 실행
- 라이트/다크 테마, 모바일 대응

## 설치

```bash
git clone <repo-url> ~/tools/odoo-launcher
cd ~/tools/odoo-launcher
bash install.sh
```

설치 시 Python 경로와 런처 포트를 입력합니다 (기본: 9069).

## 프로젝트 설정

`projects.json`에 Odoo 프로젝트를 등록합니다.

```bash
cp projects.example.json projects.json
```

```json
{
  "id": "my-odoo",
  "name": "My Odoo",
  "port": 8069,
  "cwd": "/path/to/odoo-project",
  "python": "/path/to/.pyenv/versions/my-env/bin/python",
  "logfile": "config/log/odooserver.log",
  "commands": [
    { "name": "odoo-bin", "run": "odoo-bin --config=./config/.odoorc" },
    { "name": "dev", "run": "odoo-bin --config=./config/.odoorc --dev=all" },
    { "name": "update", "run": "odoo-bin --config=./config/.odoorc -u my_module" }
  ]
}
```

| 필드 | 설명 |
|------|------|
| `id` | 고유 식별자 (영문, 하이픈) |
| `name` | 화면에 표시되는 이름 |
| `port` | Odoo HTTP 포트 (`--http-port`로 전달됨) |
| `cwd` | 프로젝트 루트 디렉토리 (절대 경로) |
| `python` | pyenv 등 Python 인터프리터 경로 |
| `logfile` | 로그 파일 경로 (`cwd` 기준 상대 경로 가능) |
| `commands` | 실행 명령어 목록 (`run`은 `cwd` 기준 상대 경로) |

## 사용법

브라우저에서 `http://127.0.0.1:9069` 접속 (설치 시 지정한 포트).

## 제거

```bash
bash ~/tools/odoo-launcher/uninstall.sh
```

## 수동 실행

LaunchAgent 없이 직접 실행:

```bash
python3 app.py --port 9069
```
