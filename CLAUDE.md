# W2TD — Web to TouchDesigner Bridge

## Structure
```
docs/              Free 버전 웹 클라이언트 (JS/HTML)
docs-pro/          Pro 버전 웹 클라이언트 (JS/HTML)
touchdesigner/py/          Free 버전 TD Python
touchdesigner-pro/py/      Pro 버전 TD Python
touchdesigner-examples/    예제 프로젝트
development/       개발 문서 (DEV_DOCS.md 등)
.claude/commands/  프로젝트 슬래시 커맨드
```

## Branch–URL Rules
| Branch | Free | Pro |
|--------|------|-----|
| `main` | `https://w2td.studio-edul.com/` | `https://w2td-pro.studio-edul.com/` |
| `dev`  | `https://w2td-dev.studio-edul.com/` | `https://w2td-pro-dev.studio-edul.com/` |

URL 위치 (전체 파일 읽기 불필요):
- `touchdesigner/py/callbacks.py` L6
- `touchdesigner/py/w2td_init.py` L316
- `touchdesigner-pro/py/callbacks.py` L5
- `touchdesigner-pro/py/w2td_init.py` L492

## Always-On Rules
- TD 노드 작업 전 derivative.ca/wiki 문서 먼저 확인. 확인 안 된 사항은 "문서 확인 필요"로 명시.
- 커밋 전 현재 브랜치 URL 검증 필수 (main/dev 브랜치 한정).
- 코드 외부 동작 변경 시 README.md + development/DEV_DOCS.md 동기화.
- 모든 커밋에 `Co-Authored-By: Claude ... <noreply@anthropic.com>` 포함.
- 경로 참조 시 절대경로 금지 — 레포 루트 기준 상대경로 사용.
- **`git add -f` 절대 금지** — .gitignore 규칙을 우회하지 않는다. `development/` 등 ignore된 파일은 로컬 전용.
- **`git push --force` 절대 금지.**

## Commands
- `/commit [message]` — 브랜치 URL 검증 후 커밋 (@.claude/commands/commit.md)
- `/update-docs` — README + DEV_DOCS 동기화 (@.claude/commands/update-docs.md)
- `/td-node` — TD 노드 문서 확인 절차 (@.claude/commands/td-node.md)
