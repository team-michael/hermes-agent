Slack: 본문 답변은 origin(현재 DM)으로 자동 전달되나 `send_message(target="slack")`는 home 채널(C0B1Z99756K)로 라우팅됨 — Minkyu DM(D0AUW5SS0M8) 아님. slack_table 등을 현재 DM에 보내려면 target="slack:D0AUW5SS0M8" 명시.
§
Hermes 경로/creds: terminal $HOME=.../profiles/boris/home, write_file은 /home/ubuntu/.hermes/... 실경로 — 작업은 절대경로 .../boris/home/.hermes/workspace/<repo>. 토큰 미주입: `set -a; . .../boris/.env; set +a`, git은 GIT_ASKPASS=~/.hermes/git-askpass.sh(boris home 기준). 시크릿 curl 헤더 인라인 금지 — 스크립트 파일로. 과거 세션이 타 프로필(andrej 등)일 수 있음: 각 프로필 state.db sqlite3 검색 → session_search(profile=..., session_id=...). prod PG RO 프록시에서 n_live_tup=0 → pg_class.reltuples 사용.
§
scope cuts by service boundary but keep deploy-order warnings as 콜; new UI placement needs comparable-product UX refs + exact mount component. (Stale repo-local `.git/config [user]` overrides global.)
§
notifly-event `services/server/web-console` verify: worktree에서 `pnpm install --frozen-lockfile` 후 `pnpm turbo run build --filter='./packages/*'`(@notifly/* deps) — 안 하면 typecheck TS2307 폭주. 순서: prettier --write → tsc → eslint . --ext .ts,.tsx → pnpm jest <paths> --no-coverage. NEVER `pnpm build`. lint-runner `@/` alias TS2307 노이즈 무시. .env 미커밋(env.ts+ECS).
§
`check` 스킬 SKILL.md 100KB 초과→patch 불가(write_file만 됨). 통계/지표 "안 보임" 조사(알람 아님): `check/references/notifly-statistics-missing-metric-investigation.md` — RAW→AGG→DISPLAY 3레이어 + MessageStatsSheet close_button_click 미표시 버그.
§
Codex OAuth: Pro 계정 2개(greybox@/team@greyboxhq.com)를 4개 프로필(andrej/csm/notifly-sentinel/sdr)이 공유 — 한도 경합·revoke 리스크. 조사/복구 절차는 스킬 `hermes-codex-credential-ops`.
§
세그먼트 매칭/모수계산: 스킬 `notifly-segment-targeting-pipeline`. Minkyu 기술검토: 개념 드릴다운 연쇄 — 직접 답→메커니즘, 이전 주장과 일관·실측 기반, 한계는 정직하게. 설계검토에선 단순화 방향 연쇄 압박("기존 구조로 충분?") + 자기 대안 제시 — 대안은 분해해 부분 채택/기각(전부 수용·전부 방어 금지), 결론은 결정 사다리+사전 합의 이탈 트리거 형태 선호, 각 결론 즉시 문서 반영. "비전공자 설명" 요청 시 비유 재서술.
§
Slack Socket Mode 좀비 세션: 5시간 주기 세션 rotation 직후 WS가 TCP/ping-pong은 살아있는데 이벤트만 안 오는 상태 발생 가능. Hermes watchdog(is_connected)로 탐지 불가 — 로그에 rotation 이후 inbound 0이면 좀비. 복구: systemctl --user restart hermes-gateway-<profile>.