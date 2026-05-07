Notifly csm Hermes profile home: /home/ubuntu/.hermes/profiles/csm. Profile .env has Slack/GitHub/Cloudflare credential keys; never print/save credential values. Slack recovery exports/scripts live under profile/recovery.
§
Notifly positioning/pricing (2026-05): Korean B2C CRM automation across push, popup, Kakao Alimtalk/brand message, SMS/MMS, email, webhook, LINE. Strengths: Kakao-native, Korean UX/support, predictable pricing, Braze alternative. Standard KRW 150k/mo; Pro KRW 800k/mo; Enterprise quoted.
§
Notifly Friendtalk support ends 2026-05-31; from 2026-06-01 Friendtalk channel selection and direct API endpoint are unsupported. Guide customers to Kakao brand message and verify latest scope before sales claims.
§
Notifly in-app popup exposure: SDK receives campaign/user-state on session fetch and matches triggers client-side; user-state cache can be ~60s. Retest: wait 1+ min after activation, fully restart app for session_start, trigger event, check in_app_message_show. Android in-app requires API 30+.
§
Notifly Kakao brand-message direct M/N delivery currently does not pre-fetch an opt-out/rejection list; flow is segment-publisher -> delivery policy/frequency capping -> Kakao marketing endpoint with targeting M/N and reseller_code. Verify Kakao-side opt-out responsibility if questioned.
§
Notifly campaign event data export: Athena event_params is map<string,string>; CSV SELECT * stringifies maps as {k=v,...}. Prefer json_format(CAST(event_params AS JSON)) + JSON.parse, with fallback parser splitting only top-level commas and preserving commas inside {}, [], ().
§
Notifly payments/Payple: invalid/missing billing keys (PUER0003/PUER0004) should be idempotent for drop/delete; preserve PCD_PAY_CODE/MSG in raw logs. Web console should not route generic 400/500 payment-method errors to new-registration paywall; card re-registration belongs in Settings -> Payment method management.
§
CSM profile active SOUL.md is a symlink: /home/ubuntu/.hermes/profiles/csm/SOUL.md -> /home/ubuntu/.hermes/hermes-agent/ignored/local/profiles/csm/SOUL.md. Use read_file on the exact profile path; search_files may miss the symlink.