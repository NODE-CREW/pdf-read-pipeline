# Repository Guidelines

## Project Structure & Module Organization
- `src/`: Production code organized by feature (e.g., `src/auth/`, `src/utils/`).
- `tests/`: Mirrors `src/` with matching test modules (e.g., `tests/auth/`).
- `scripts/`: Repeatable developer tasks (setup, data seeding, local tools).
- `config/`: Non-secret configs (YAML/TOML/JSON). Secrets go in `.env`.
- `docs/`: Architecture notes, ADRs, and design diagrams.

## Build, Test, and Development Commands
- `make setup`: Install local dependencies and pre-commit hooks.
- `make test`: Run the full test suite with coverage.
- `make lint`: Run linters/formatters and fail on issues.
- `make run`: Start the local dev server or CLI entry.
If a `Makefile` is not present, run the language-specific equivalents directly (e.g., `pytest`, `npm test`, `cargo test`).

## Coding Style & Naming Conventions
- Indentation: 4 spaces for Python; 2 spaces for YAML/TOML/JSON; no tabs.
- Line length: 100 chars unless a tool enforces differently.
- Naming: snake_case for files/modules; PascalCase for classes; lowerCamelCase for variables/functions (match ecosystem norms if language differs).
- Formatting/Linting: Prefer tool-backed enforcement (e.g., `black`, `ruff`, `prettier`, `eslint`). Add rules to CI and run via `make lint`.

## Testing Guidelines
- Location: Place tests in `tests/` mirroring `src/` paths.
- Naming: Use clear, behavior-focused names (e.g., `test_handles_expired_token`).
- Coverage: Target ≥ 80% line coverage; include edge/error paths.
- Running: `make test` or the project’s native test runner.

## Commit & Pull Request Guidelines
- Commits: Use Conventional Commits (e.g., `feat: add token refresh`), small and scoped.
- Branches: `type/short-topic` (e.g., `fix/login-timeout`).
- PRs: Include purpose, approach, trade-offs, and linked issues. Add logs/screenshots for UI or CLI changes. Ensure CI green and `make lint` passes.

## Security & Configuration Tips
- Never commit secrets. Use `.env` and provide `.env.example` with placeholders.
- Document required environment variables in `README.md` and `config/`.
- Review third-party dependencies regularly; pin versions where practical.

# Additional Guidelines
## Rules must follow
1. 가능한 가장 간단한 솔루션을 따라야 함.
2. 요청한 내용만 수정해야 함.
3. 지시한 내용과 상관없는 내용은 수정하지 않아야 함.
4. 프로젝트 구조 자체를 바꾸는 행동은 하지 않아야 함.
5. 중복된 function이 있는지 철저하게 찾아보고 없을 때만 새로운 function을 작성해야 함.
6. 증상만 해결하는 것이 아닌 근본 원인을 해결할 수 있는 방법을 찾아야 함.
7. 동일한 기능을 하는 코드가 있는지 반드시 먼저 체크해야 해.
8. UI와 관련된 내용이 아니라면 테스트 코드를 먼저 작성한 뒤 로직 수정을 해야 함.
9. 새로운 방법(새 스크립트/새 워크플로우)을 추가하면 관련 실행 방법과 설명을 반드시 README.md에 반영해야 함.
10. 완성된 파일은 직접 수정하지 않고, 변경이 필요하면 `기존번호-1_...` 형태의 새 파일을 만들어 작업해야 함.

## Language
- Korean

## Skills
A skill is a set of local instructions to follow that is stored in a `SKILL.md` file. Below is the list of skills that can be used. Each entry includes a name, description, and file path so you can open the source for full instructions when using a specific skill.
### Available skills
- develop-web-game: Use when Codex is building or iterating on a web game (HTML/JS) and needs a reliable development + testing loop: implement small changes, run a Playwright-based test script with short input bursts and intentional pauses, inspect screenshots/text, and review console errors with render_game_to_text. (file: /Users/woong.park/.codex/skills/develop-web-game/SKILL.md)
- doc: Use when the task involves reading, creating, or editing `.docx` documents, especially when formatting or layout fidelity matters; prefer `python-docx` plus the bundled `scripts/render_docx.py` for visual checks. (file: /Users/woong.park/.codex/skills/doc/SKILL.md)
- gh-address-comments: Help address review/issue comments on the open GitHub PR for the current branch using gh CLI; verify gh auth first and prompt the user to authenticate if not logged in. (file: /Users/woong.park/.codex/skills/gh-address-comments/SKILL.md)
- imagegen: Use when the user asks to generate or edit images via the OpenAI Image API (for example: generate image, edit/inpaint/mask, background removal or replacement, transparent background, product shots, concept art, covers, or batch variants); run the bundled CLI (`scripts/image_gen.py`) and require `OPENAI_API_KEY` for live calls. (file: /Users/woong.park/.codex/skills/imagegen/SKILL.md)
- linear: Manage issues, projects & team workflows in Linear. Use when the user wants to read, create or updates tickets in Linear. (file: /Users/woong.park/.codex/skills/linear/SKILL.md)
- pdf: Use when tasks involve reading, creating, or reviewing PDF files where rendering and layout matter; prefer visual checks by rendering pages (Poppler) and use Python tools such as `reportlab`, `pdfplumber`, and `pypdf` for generation and extraction. (file: /Users/woong.park/.codex/skills/pdf/SKILL.md)
- playwright: Use when the task requires automating a real browser from the terminal (navigation, form filling, snapshots, screenshots, data extraction, UI-flow debugging) via `playwright-cli` or the bundled wrapper script. (file: /Users/woong.park/.codex/skills/playwright/SKILL.md)
- screenshot: Use when the user explicitly asks for a desktop or system screenshot (full screen, specific app or window, or a pixel region), or when tool-specific capture capabilities are unavailable and an OS-level capture is needed. (file: /Users/woong.park/.codex/skills/screenshot/SKILL.md)
- security-best-practices: Perform language and framework specific security best-practice reviews and suggest improvements. Trigger only when the user explicitly requests security best practices guidance, a security review/report, or secure-by-default coding help. Trigger only for supported languages (python, javascript/typescript, go). Do not trigger for general code review, debugging, or non-security tasks. (file: /Users/woong.park/.codex/skills/security-best-practices/SKILL.md)
- security-ownership-map: Analyze git repositories to build a security ownership topology (people-to-file), compute bus factor and sensitive-code ownership, and export CSV/JSON for graph databases and visualization. Trigger only when the user explicitly wants a security-oriented ownership or bus-factor analysis grounded in git history (for example: orphaned sensitive code, security maintainers, CODEOWNERS reality checks for risk, sensitive hotspots, or ownership clusters). Do not trigger for general maintainer lists or non-security ownership questions. (file: /Users/woong.park/.codex/skills/security-ownership-map/SKILL.md)
- skill-creator: Guide for creating effective skills. This skill should be used when users want to create a new skill (or update an existing skill) that extends Codex's capabilities with specialized knowledge, workflows, or tool integrations. (file: /Users/woong.park/.codex/skills/.system/skill-creator/SKILL.md)
- skill-installer: Install Codex skills into $CODEX_HOME/skills from a curated list or a GitHub repo path. Use when a user asks to list installable skills, install a curated skill, or install a skill from another repo (including private repos). (file: /Users/woong.park/.codex/skills/.system/skill-installer/SKILL.md)
- senior-software-engineer: 프로젝트를 진행하면서 Senior Software Engineer 역할로 의사결정, 구현, 검수, 개선 우선순위를 일관되게 수행한다. (file: /Users/woong.park/misc/pdf-reader/skills/senior-software-engineer/SKILL.md)
- release-readiness-review: 결과물(기능/문서/CLI/PDF)의 배포 준비 상태를 점검하고 배포 가능 여부를 판정한다. (file: /Users/woong.park/misc/pdf-reader/skills/release-readiness-review/SKILL.md)
- code-quality-review: 코드 변경사항에서 버그, 회귀 위험, 중복 로직, 테스트 누락을 식별하는 코드 검수를 수행한다. (file: /Users/woong.park/misc/pdf-reader/skills/code-quality-review/SKILL.md)
- improvement-roadmap: 현재 제품 상태를 기반으로 실행 가능한 개선 next step을 우선순위화한 로드맵을 제시한다. (file: /Users/woong.park/misc/pdf-reader/skills/improvement-roadmap/SKILL.md)
### How to use skills
- Discovery: The list above is the skills available in this session (name + description + file path). Skill bodies live on disk at the listed paths.
- Trigger rules: If the user names a skill (with `$SkillName` or plain text) OR the task clearly matches a skill's description shown above, you must use that skill for that turn. Multiple mentions mean use them all. Do not carry skills across turns unless re-mentioned.
- Missing/blocked: If a named skill isn't in the list or the path can't be read, say so briefly and continue with the best fallback.
- How to use a skill (progressive disclosure):
  1) After deciding to use a skill, open its `SKILL.md`. Read only enough to follow the workflow.
  2) When `SKILL.md` references relative paths (e.g., `scripts/foo.py`), resolve them relative to the skill directory listed above first, and only consider other paths if needed.
  3) If `SKILL.md` points to extra folders such as `references/`, load only the specific files needed for the request; don't bulk-load everything.
  4) If `scripts/` exist, prefer running or patching them instead of retyping large code blocks.
  5) If `assets/` or templates exist, reuse them instead of recreating from scratch.
- Coordination and sequencing:
  - If multiple skills apply, choose the minimal set that covers the request and state the order you'll use them.
  - Announce which skill(s) you're using and why (one short line). If you skip an obvious skill, say why.
- Context hygiene:
  - Keep context small: summarize long sections instead of pasting them; only load extra files when needed.
  - Avoid deep reference-chasing: prefer opening only files directly linked from `SKILL.md` unless you're blocked.
  - When variants exist (frameworks, providers, domains), pick only the relevant reference file(s) and note that choice.
- Safety and fallback: If a skill can't be applied cleanly (missing files, unclear instructions), state the issue, pick the next-best approach, and continue.
