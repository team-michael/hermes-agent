Notifly 관리자. ‘모험가’ 금지, 모코코 톤. Slack 결과만, 조롱 금지.
§
anomaly threshold는 prod stale 분포·정상 retry budget 기준, 내부/dev 제외. 탐지는 최대 retry window+주기 후 선호.
§
스킬은 공식 문서·공개 저장소로 존재/설치를 구분하고 최신성·실엔진·umbrella+references를 중시함.
§
Codex 사용량은 5시간·7일 제한과 초기화 시각을 정확히 표시하길 원함.
§
Locale UI는 언어 검색·빈값 Auto-fill·source/fallback tooltip·SVG 국기를 선호하고, 중국어 script locale(`zh-Hant`/`zh-Hans`)과 콘솔 locale(`zh-TW`/`zh-CN`)의 명시적 호환을 중시함.
§
PR은 독립 배포 단위로 분리하되 한 check면 묶음. 동일 작업 분리 PR은 Linear 공유·본인 In Progress; 책임이 다르면 이슈·parent 연결 금지. Linear Todo는 제목이 아니라 완료 조건과 merge·배포·검증 근거를 대조해 충족된 것만 Done 처리하길 원함.
§
Notifly MCP/유저여정은 web-console create→편집 round-trip과 builder view_state↔runtime PG 컬럼을 구분해 비교하며, 신규 생성 오염을 ‘미복구’가 아닌 생성 시 계약 불일치로 설명하길 원함.
§
E2E는 실데이터·canary 선호. fixture 부재 시 기존 회귀와 신규 기능 미검증을 구분. schema CI는 local PG+prod catalog tenant probe·나머지 mismatch 실패, tenant/global 독립 check.
§
Poller 복구는 raw API·임의 success 대신 DDB mapping 기반 정상 task 재실행→PG final·checkpoint 확인. 알림은 accepted-vs-collected EMF보다 provider별 stale pending-only 선호. fresh main→TDD→실측→remote 확인.
§
Ponytail full은 최소 작업·짧은 결론. 장애는 live DB·계약·로그·queue metric으로 입증; pending 이력은 ID·updated_at·audit/log로 확인.
§
PR은 Semantic 제목. 본래 목적과 부수 효과를 구분. 승인 후 RED→수정·검증→push→댓글·resolve→재조회.
§
팀 문서는 전→후 3줄 선호. 코드는 함수 이동과 의미 변경을 분리하고 입력→저장→실행 계약을 코드로 설명하길 원함.
§
설계/API는 DB 저장 가능 여부를 먼저 확인하고 UI→저장 transformer→runtime 전 경로를 구분해 검증하길 원함.