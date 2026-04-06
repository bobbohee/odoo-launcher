# .odoorc 파일 편집 기능

## 개요

Odoo Launcher 웹 UI에서 각 프로젝트의 `.odoorc` 설정 파일을 직접 편집할 수 있는 기능을 추가한다.

## 설정

`projects.json`에 `odoorc` 필드를 추가하여 각 프로젝트의 `.odoorc` 파일 경로를 명시한다.

```json
{
  "id": "my-odoo",
  "name": "My Odoo",
  "odoorc": "config/.odoorc",
  "commands": [
    { "name": "odoo-bin", "run": "odoo-bin --config={odoorc}" },
    { "name": "dev", "run": "odoo-bin --config={odoorc} --dev=all" }
  ],
  ...
}
```

- 상대경로는 프로젝트 `cwd` 기준으로 해석한다.
- 절대경로도 허용한다.
- `odoorc` 필드가 없는 프로젝트는 편집 버튼을 표시하지 않는다.

### 커맨드 변수 치환

commands의 `run` 문자열에서 `{odoorc}` 플레이스홀더를 `odoorc` 필드의 경로로 치환한다. 이를 통해 `.odoorc` 경로를 한 곳에서만 관리할 수 있다.

- 기존: `"run": "odoo-bin --config=./config/.odoorc"` (경로 중복)
- 변경: `"run": "odoo-bin --config={odoorc}"` (`odoorc` 필드 참조)
- `{odoorc}` 플레이스홀더가 없으면 치환 없이 그대로 실행한다.
- `odoorc` 필드가 없는데 `{odoorc}`를 사용하면 빈 문자열로 치환한다.

## 백엔드 API

### `GET /api/projects/{id}/odoorc`

- `.odoorc` 파일 내용을 텍스트로 읽어 JSON 응답한다.
- 응답: `{"content": "파일 내용"}`
- 파일이 없으면: `{"content": ""}` (status 404)
- `odoorc` 필드 미설정 시: status 404

### `PUT /api/projects/{id}/odoorc`

- 요청 본문의 `content` 값을 `.odoorc` 파일에 저장한다.
- 요청: `{"content": "새 내용"}`
- 응답: `{"status": "saved"}`
- `odoorc` 필드 미설정 시: status 404

## 프론트엔드

### 버튼 배치

- 프로젝트 이름 옆에 Font Awesome `fa-gear` 아이콘을 배치한다.
- `odoorc` 필드가 있는 프로젝트만 아이콘을 표시한다.
- `/api/projects` 응답에 `has_odoorc` 필드를 추가하여 프론트엔드에서 판단한다.

### 에디터 UI

기존 로그 패널(오른쪽)을 재활용한다. Git/Logs와 동일한 패턴:

1. ⚙ 아이콘 클릭 시 패널 헤더에 `{프로젝트명} — .odoorc` 표시
2. 패널 본문에 `<textarea>`로 파일 전체 내용을 표시
3. 하단에 저장 버튼 배치
4. 저장 성공 시 간단한 피드백 표시 (예: 버튼 텍스트 변경)
5. 저장 실패 시 에러 메시지 표시

### 스타일

- textarea는 기존 로그 패널의 monospace 폰트, 색상 테마를 따른다.
- 저장 버튼은 기존 `.btn` 스타일을 기반으로 한다.
- 다크 모드 대응 포함

### 상태 관리

- `activeOdoorcId` 변수로 현재 편집 중인 프로젝트를 추적한다.
- 기존 `clearPanel()` 함수에 odoorc 상태 초기화를 추가한다.
- ⚙ 버튼 토글: 같은 프로젝트 재클릭 시 패널 닫기

## 제약 사항

- 파일 경로 탐색(traversal) 방지: `odoorc` 경로가 프로젝트 `cwd` 외부를 가리키는 것은 `projects.json`을 직접 편집하는 사용자의 책임으로 둔다 (localhost 전용 도구이므로).
- 동시 편집 고려 없음: 단일 사용자 로컬 도구.
- 파일 인코딩: UTF-8 가정.
