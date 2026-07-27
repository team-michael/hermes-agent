Notifly csm profile home: /home/ubuntu/.hermes/profiles/csm. Never print .env secrets. Notifly console repro: use .env NOTIFLY_AUTH email:password, login /ko/auth/login; Michael slug michael, dashboard /console/products/michael/dashboard.
§
Notifly positioning/pricing (2026-05): Korean B2C CRM automation across push, popup, Kakao Alimtalk/brand message, SMS/MMS, email, webhook, LINE. Strengths: Kakao-native, Korean UX/support, predictable pricing, Braze alternative. Standard KRW 150k/mo; Pro KRW 800k/mo; Enterprise quoted.
§
Notifly Friendtalk support ends 2026-05-31; from 2026-06-01 Friendtalk channel selection and direct API endpoint are unsupported. Guide customers to Kakao brand message and verify latest scope before sales claims.
§
Notifly in-app popup exposure: SDK receives campaign/user-state on session fetch and matches triggers client-side; user-state cache can be ~60s. Retest: wait 1+ min after activation, fully restart app for session_start, trigger event, check in_app_message_show. Android in-app requires API 30+.
§
Notifly Kakao brand-message direct M/N delivery currently does not pre-fetch an opt-out/rejection list; flow is segment-publisher -> delivery policy/frequency capping -> Kakao marketing endpoint with targeting M/N and reseller_code. Verify Kakao-side opt-out responsibility if questioned.
§
Notifly event export: Athena event_params is map<string,string>; use json_format(CAST(... AS JSON)) + JSON.parse, or top-level comma fallback parser.
§
Notifly Payple: PUER0003/0004 billing-key errors are idempotent for drop/delete; keep PCD_PAY_CODE/MSG raw logs. Card re-registration is Settings -> Payment method management.
§
Notifly web SDK: never expose real password/API secret as `NEXT_PUBLIC_*`; use public projectId+username, and pass `password: username` as a non-empty legacy placeholder. Empty password can fail current JS SDK/GTM validation.
§
Notifly ISMS/audit reply: console audit-log self-view unavailable; on request extract project/period logs: auth/access, user data CRUD/read, user CSV export, plus server access-log supplement. Campaign-upload file deletion is not a current console feature; future implementation unscheduled.