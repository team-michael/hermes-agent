Notifly 관리자. 모코코 톤, ‘모험가’·조롱 금지. Slack 결과만.
§
anomaly threshold는 prod stale 분포·정상 retry budget 기준, 내부/dev 제외. 탐지는 최대 retry window+주기 후 선호.
§
스킬은 공식 문서·공개 저장소로 존재/설치를 구분하고 최신성·실엔진·umbrella+references를 중시함.
§
Locale UI는 검색·Auto-fill·tooltip·SVG 국기를 선호. 고객별 legacy locale 호환은 범용 CLDR보다 실데이터에 확인된 매핑만 해당 fallback 경계에 하드코딩하고 추후 삭제 가능하게 격리하길 원함.
§
PR은 독립 배포 단위로 분리. Web Console은 schema·transformer 핵심 spec만, mock-heavy UI spec은 제거. localized Journey는 기존 writer UI 유지 선호.
§
Notifly MCP/유저여정은 web-console create→편집 round-trip과 builder view_state↔runtime PG 컬럼을 구분해 비교하며, 신규 생성 오염을 ‘미복구’가 아닌 생성 시 계약 불일치로 설명하길 원함.
§
E2E는 실데이터·canary 선호. 배포 검증은 기존 경로의 실트래픽 건강성과 신규 조건 분기의 실제 입력 smoke를 구분. 운영 집계는 캠페인×lang별 distinct 사용자와 이벤트 건수 구분. schema CI는 local PG+prod probe, tenant/global 독립.
§
Poller 복구는 raw API·임의 success 대신 DDB mapping 기반 정상 task 재실행→PG final·checkpoint 확인. 알림은 accepted-vs-collected EMF보다 provider별 stale pending-only 선호. fresh main→TDD→실측→remote 확인.
§
Ponytail full: 전체 흐름·공유 호출자 추적→기존 snapshot을 가장 늦은 경계에서 재사용. payload 중복과 SQS·DDB·PG·Kinesis·S3 p95/max 용량 확인 후 최소 diff/check·짧은 결론 선호.
§
PR은 Semantic 제목. 목적/부수효과 분리. 승인 후 RED→검증→push→댓글·resolve→재조회.
§
팀 문서는 전→후 3줄 선호. 코드 설명은 파일 역할→실행 흐름→라인별 이유 순서로, 함수 이동·의미 변경과 입력→저장→실행 계약을 분리하길 원함.
§
설계/API는 provider 응답→snapshot→저장→export와 payload 중복·용량을 추적하고 parser 누락↔provider 미제공을 구분한다.
§
긴 작업이 도구 지연으로 늘어지면 현재 단계·블로커를 짧게 즉시 공유하길 원함.