sharp/librsvg SVG→PNG 폰트 이슈 3종(§ NN mono 안 먹음, TTF 0xEFBFBD 손상, multi-word family 쿼팅, CJK + Latin-only serif italic → faux-italic skew) → `svg-to-png-font-rendering`
§
- `team-michael/notifly-catalogs`: 고객사례 플레이북 PPTX(`notifly-playbook-pptx/build_deck.js`, React→PptxGenJS; SVG→PNG 감사 dev_server/dev_dump_png). 미학은 스킬 `powerpoint` references 참조.
§
Slack: 본문 답변은 origin(현재 DM)으로 자동 전달되나 `send_message(target="slack")`는 home 채널(C0B1Z99756K)로 라우팅됨 — Minkyu DM(D0AUW5SS0M8) 아님. slack_table 등을 현재 DM에 보내려면 target="slack:D0AUW5SS0M8" 명시.
§
Hermes 환경 경로 트랩: terminal/process는 $HOME=/home/ubuntu/.hermes/profiles/boris/home (즉 `~/.hermes/...` → `/home/ubuntu/.hermes/profiles/boris/home/.hermes/...`)인데 write_file/patch는 `/home/ubuntu/.hermes/...` (profile 위 실경로)에 쓴다. 클론·dev server·테스트는 절대경로 `/home/ubuntu/.hermes/profiles/boris/home/.hermes/workspace/<repo>`로 통일하면 분기 안 생김.
§
Minkyu (조민규) engineering standards (recurring): (1) Evidence over theory — prove necessity by counterfactual, not reasoning. (2) Root cause fixed → remove earlier workarounds. (3) Minimal-diff option + tradeoff, then his call. (4) Planning: reuse existing in-repo logic for auth/gating (grep precedent); scope cuts by service boundary but keep deploy-order warnings as 콜; new UI placement needs comparable-product UX refs + exact mount component. (Stale repo-local `.git/config [user]` overrides global.)
§
notifly-event `services/server/web-console` verify: `pnpm install --frozen-lockfile` in worktree THEN `pnpm turbo run build --filter='./packages/*'` (builds `@notifly/*` deps) — else `pnpm typecheck` floods TS2307 "Cannot find module @notifly/*" false errors. Order: prettier `--write` → `tsc -p tsconfig.json` → `eslint . --ext .ts,.tsx` (no --max-warnings) → `pnpm jest <paths> --no-coverage`. NEVER `pnpm build` (web-console AGENTS.md). Ignore write_file/patch lint-runner `@/` alias TS2307 noise. No committed `.env` (env via env.ts+docker/ECS); worktrees lack node_modules/.env until set up.
§
`check` 스킬 SKILL.md 100KB 초과→patch 불가(write_file만 됨). 통계/지표 "안 보임" 조사(알람 아님): `check/references/notifly-statistics-missing-metric-investigation.md` — RAW→AGG→DISPLAY 3레이어 + MessageStatsSheet close_button_click 미표시 버그.