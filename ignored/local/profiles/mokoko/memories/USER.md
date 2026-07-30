사용자는 '모험가' 호칭을 금지하며, 친구 같은 모코코 페르소나와 기술 이슈의 솔직한 공유·우회안 제시를 선호함.
§
사용자는 시스템 설정·연동 계정·API 키 존재 여부를 실제 환경에서 재검증하는 것을 중시함.
§
사용자는 AI 에이전트의 대화 로그를 조회할 때 토큰이나 레이턴시 등의 상세 필드는 제외하고, 'usermessage', 'assistantresponse', 'createdat', 'sessionid' 네 가지 핵심 필드만 요약해서 보기를 원함.
§
사용자는 API·아키텍처를 schema→DTO→adapter/DB→UI·Git history와 실제 호출 흐름으로 검증함. 코드 PR 설명에서는 수정·생성한 함수·메서드를 빠짐없이 나열하고 각각의 필요성·동작 경계·실패 흐름을 설명받길 원함.
§
사용자는 스킬의 최신·정확성을 중시하고, 기존 보고 스킬을 더 긴 기간으로 확장해 쓰길 원함.
§
사용자는 MCP 사용 리포트에서 Slack에는 고객사·도구별 집계만 표시하고, 민감할 수 있는 tool parameter는 권한 통제된 상세 조회 링크로 분리하는 방식을 선호함.
§
사용자는 Codex 사용량에서 추상적인 ‘세션’ 명칭보다 API가 반환한 실제 제한 기간(예: 5시간·7일)과 초기화 시각을 정확히 표시하길 원함.
§
사용자는 API·web-console UI 호환을 검증함. Locale UI는 ‘locale 추가’보다 ‘언어 추가’와 하단 검색·선택 창, default 기반 빈 언어 Auto-fill을 선호함. rollout은 Michael 하드코딩, 번역 키는 `.env`·AWS Secrets Manager를 선호함. PG writer 전 live tenant schema와 별도 migration SQL을 기대함.
§
사용자는 Linear에서 `Hyukjun Kang`이며, Parent 대신 개별 Todo 이슈를 마일스톤에 직접 연결하고 본인에게 배정하길 원함.
§
Notifly MCP 문서는 ChatGPT 데스크톱·웹·Codex를 분리하고, 도구 갱신 안내는 ChatGPT에서 제외하되 Claude에는 유지함. 변경은 Draft PR→사용자 미리보기·스크린샷→CI→Ready 순이며 사용자 미리보기 때 에이전트 서버는 종료함.
§
계획·검토만 요청하면 승인 전 이슈 생성·코드 수정·상태 변경을 원하지 않음.
§
사용자는 합의 범위만 최소 변경함. Notifly retry 전 Poller의 SMS failover/N resend side effect와 enqueue→checkpoint crash window를 추적하고, 멱등성 후 retry를 활성화하길 원함. AWS·Terraform remote plan의 무 destroy/replace·PR·CI 검증도 선호함.