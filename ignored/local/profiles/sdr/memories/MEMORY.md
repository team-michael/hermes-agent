The sdr Hermes profile is used for Notifly SDR/sales support in Slack as Kelly from San Diego.
§
Notifly Slack history for sdr is readable via Slack Web API with `SLACK_BOT_TOKEN` from `/home/ubuntu/.hermes/profiles/sdr/.env` when the bot is a member; known readable channels include #sales-partnership C06B39NC2AW, #revenue-report C06DEQQ2LGP, and #grants C05RMTQKBPU. Never print the token.
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
Notifly GTM engineering v0 prep artifacts for the sdr profile are stored at `/home/ubuntu/.hermes/profiles/sdr/workspace/gtm-copilot/`: prompts, scoring rules, JSON schema, daily queue template, outcome log template, and future cron prompt. The `notifly-sdr-lead-research` skill includes a GTM Copilot / Outbound Engineering v0 section pointing to this workspace.