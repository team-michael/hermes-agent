‘모험가’ 호칭 금지. 친구 같은 모코코 톤과 솔직한 공유를 선호함.
§
`notifly-kokomo`는 개인 테스트 product; 결제 장애는 DDB 원복 전제의 prod Payple 동일 카드 재등록으로 검증함.
§
사용자는 AI 에이전트의 대화 로그를 조회할 때 토큰이나 레이턴시 등의 상세 필드는 제외하고, 'usermessage', 'assistantresponse', 'createdat', 'sessionid' 네 가지 핵심 필드만 요약해서 보기를 원함.
§
사용자는 API/MCP를 최신 main·live DB·실구현으로 검증하고, 핵심 계약을 tool/parameter description에 두길 원함. timezone·형식·경계·freshness/unavailable·빈 결과를 점검하며, 예시는 자연어 날짜가 아닌 실제 형식(예: YYYY-MM-DD)으로 쓰길 원함.
§
사용자는 스킬의 최신·정확성과 제품 고유 dialect·실제 엔진 호환성 검증을 중시하며, 범용 Skill/MCP의 무비판적 권장을 원치 않음.
§
사용자는 MCP 리포트에서 프로젝트별 호출량·도구 종류·도구별 횟수·사용패턴과 도구별 사용량 그래프를 원함. 민감한 parameter는 권한 통제 상세 링크로 분리함.
§
사용자는 Codex 사용량에서 추상적인 ‘세션’ 명칭보다 API가 반환한 실제 제한 기간(예: 5시간·7일)과 초기화 시각을 정확히 표시하길 원함.
§
Locale UI는 ‘언어 추가’·하단 검색/선택·default 기반 빈 언어 Auto-fill을 선호함. rollout은 Michael allowlist, 번역 키는 `.env`·Secrets Manager, PG writer 전 live schema·별도 migration SQL 검증을 원함.
§
사용자는 Linear에서 `Hyukjun Kang`이며, Parent 대신 개별 Todo 이슈를 마일스톤에 직접 연결하고 본인에게 배정하길 원함.
§
Notifly MCP 문서는 ChatGPT 데스크톱·웹·Codex를 분리하고, 도구 갱신 안내는 ChatGPT에서 제외하되 Claude에는 유지함. 변경은 Draft PR→사용자 미리보기·스크린샷→CI→Ready 순이며 사용자 미리보기 때 에이전트 서버는 종료함.
§
계획·검토만 요청하면 승인 전 이슈 생성·코드 수정·상태 변경을 원하지 않음.
§
사용자는 Poller retry 전 enqueue→checkpoint crash window와 멱등성을 확인하고, partial retry는 handler 응답·event source mapping·live `FunctionResponseTypes`를 모두 검증함. PR 보고 전 remote head/main도 재조회함.
§
‘원시인 모드’는 다음 할 일 하나만 짧게 답하는 형식임.