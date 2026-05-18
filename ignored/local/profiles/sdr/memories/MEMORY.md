The sdr Hermes profile is used for Notifly SDR/sales support in Slack as Kelly from San Diego.
§
For sdr Notifly Slack links, evidence-first means resolve channel/ts and call Slack Web API (`conversations.replies`/`history`) with `SLACK_BOT_TOKEN` from `.env` before answering or claiming inaccessible; browser sign-in ≠ access failure. Never print token.
§
Recovered Notifly sales context for the sdr profile is stored in /home/ubuntu/.hermes/profiles/sdr/reference/recovered-slack-sales-context.md and profile skills sales/notifly-sales-enablement and sales/notifly-sdr-lead-research.
§
Notifly sales onboarding thread source pointers are in C06B39NC2AW/thread 1777624171.275289: sales reference Doc 1-BMHxjKYI0aNOOqF-ou3KWIAQHb8HOEiXtxgc-0eb2s, docs.notifly.tech/ko, notifly.tech/ko pricing, CRM Top5 competitor blog, prospect Sheet 1Kz6d6VdSDMrrNfeuVdqKhsx0CH19zriRkFUSUrSOpBU, Drive folder 1E0v7jZnTK-tkcqw2PexYEO1OwZtgi-b, Slack C06B39NC2AW and C06DEQQ2LGP.
§
For the sdr profile, when accessing Google Workspace documents, load the google-workspace skill and use the gws CLI as the primary access method; first check authentication with the skill setup check and/or `gws auth status`.
§
For the sdr profile, Google Workspace access uses `gws` with `GOOGLE_WORKSPACE_CLI_CONFIG_DIR=/home/ubuntu/.config/gws`; this env var is saved in `/home/ubuntu/.hermes/profiles/sdr/.env`. Load the google-workspace skill first, then use `gws` for Docs/Drive/Sheets access.
§
Notifly pricing context for the sdr profile, including non-public Plus-plan handling and the customer/vendor KakaoTalk/SMS/RCS/080 unit-rate Sheet `고객사 현재 카카오톡/문자 발송 단가 조사` (1gJ32S0s4P-86yDWhnVD0VZCpUs9jJFIbDb7U3boIX_Y), is restored in skill `notifly-sales-enablement` at `references/notifly-pricing-context-2026.md`.
§
Notifly GTM/outbound engineering v0 artifacts live under `/home/ubuntu/.hermes/profiles/sdr/workspace/gtm-copilot/`; the `notifly-sdr-lead-research` skill points there. For future Notifly revenue tasks, use DynamoDB `transactions` as the source of truth for revenue and type split; Slack revenue reports are secondary summaries.