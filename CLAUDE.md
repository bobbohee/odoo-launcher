# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Odoo Launcher는 브라우저에서 여러 Odoo 개발 서버를 시작/종료할 수 있는 경량 Python CLI 도구입니다. Python 표준 라이브러리만 사용하며 외부 의존성이 없습니다. macOS 전용(LaunchAgent 통합).

## Running

```bash
python3 app.py --port 9069
```

설치/제거는 `bash install.sh` / `bash uninstall.sh`로 수행합니다.

## Architecture

**단일 파일 설계**: 모든 백엔드/프론트엔드 로직이 `app.py` 한 파일에 포함되어 있습니다.

- **백엔드**: `http.server.BaseHTTPRequestHandler` 기반 HTTP 서버
- **프론트엔드**: HTML/CSS/JS가 `app.py` 내부에 문자열로 임베딩됨 (프레임워크/빌드 없음)
- **프로세스 관리**: `subprocess.Popen` + 데몬 스레드로 로그 수집
- **상태 관리**: `running_procs` 딕셔너리 (인메모리, 영속 없음)
- **설정**: `projects.json` (스키마는 `projects.example.json` 참조)

### REST API

| Method | Endpoint | 설명 |
|--------|----------|------|
| GET | `/` | HTML 페이지 |
| GET | `/api/projects` | 프로젝트 목록 (상태, 포트, git 변경사항) |
| GET | `/api/projects/{id}/git` | Git status |
| GET | `/api/projects/{id}/git-diff` | 파일 diff (context 파라미터) |
| GET | `/api/projects/{id}/logs` | 마지막 200줄 로그 |
| POST | `/api/projects/{id}/run/{cmd}` | 프로젝트 시작 |
| POST | `/api/projects/{id}/stop` | 프로젝트 중지 |

## Key Design Decisions

- **외부 의존성 절대 금지**: 표준 라이브러리만 사용 (requirements.txt 없음)
- **127.0.0.1만 바인딩**: 로컬 개발 전용, 인증 없음
- **프로세스 그룹 관리**: `os.setsid`로 시그널 전파, SIGINT → SIGKILL 폴백
- **로그 이중 소스**: logfile 존재 시 파일 tail, 없으면 stdout deque(500줄)
- **Git 연동**: subprocess로 `git status`/`git diff` 실행 (5초 타임아웃)

## Language

프로젝트 문서와 UI는 한국어로 작성합니다.
