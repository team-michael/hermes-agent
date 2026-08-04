The sdr Hermes profile is used for Notifly SDR/sales support in Slack as Kelly from San Diego.
§
For sdr Notifly Slack links, evidence-first means resolve channel/ts and call Slack Web API (`conversations.replies`/`history`) with `SLACK_BOT_TOKEN` from `.env` before answering or claiming inaccessible; browser sign-in ≠ access failure. Never print token.
§
Recovered Notifly sales context for the sdr profile is stored in /home/ubuntu/.hermes/profiles/sdr/reference/recovered-slack-sales-context.md and profile skills sales/notifly-sales-enablement and sales/notifly-sdr-lead-research.
§
Notifly onboarding sources: C06B39NC2AW/1777624171.275289 plus sales Doc, docs/pricing/blog, prospect Sheet and Drive folder. Positioning correction: Notifly is a CRM SaaS/platform with AI agent capabilities; do not call Notifly itself an AI agent.
§
sdr Google Workspace access: load google-workspace skill; use `gws` with `GOOGLE_WORKSPACE_CLI_CONFIG_DIR=/home/ubuntu/.config/gws`; verify with `gws auth status`.
§
Notifly pricing context for the sdr profile, including non-public Plus-plan handling and the customer/vendor KakaoTalk/SMS/RCS/080 unit-rate Sheet `고객사 현재 카카오톡/문자 발송 단가 조사` (1gJ32S0s4P-86yDWhnVD0VZCpUs9jJFIbDb7U3boIX_Y), is restored in skill `notifly-sales-enablement` at `references/notifly-pricing-context-2026.md`.
§
Trackit Open API uses `NOTIFLY_TRACKIT_API_KEY` for Notifly GTM reads/writes. Verified reads: objects/records/groups/entries/attribute-values/options/members. Verified scoped writes: `PUT /v1/objects/{object}/records` with `filter:{id:[record_id]}` + `allowMultiple:false` for single-record field updates, and `POST /v1/objects/{object}/records/delete` for safe shell deletes; no public merge/relink API verified.
§
Notifly product_id mappings: atease-cafe24=아디즈; sione-cafe24=시오네; swap=The Swing; vibeplus=Cafe24 wellness-food; okpos=오늘얼마; cmong=댓글몽; fresheasy=허닭 only.
§
Notifly 고객 회신에서 캠페인 전략·타겟 설계·문안 작성·대행 세팅 등 컨설팅을 제공한다고 표현하지 않는다. 브랜드가 직접 설정·운영하며, Notifly 지원 범위는 제품 사용법·연동·오류·카카오 템플릿 등록/반려 사유 등 운영 가이드다; 최종 템플릿 승인은 카카오가 결정한다.
§
People identity rule: Trackit English names must not be transliterated into Korean without a direct source.