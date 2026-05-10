#!/usr/bin/env python3
"""Post a VNC handoff alert as a top-level Slack message when the scraper
hits /sorry/ or a CAPTCHA and cannot proceed.

Usage: copy to ~/.hermes/tmp/<task>/post_vnc_handoff.py, edit CHANNEL and the
block_type / block_url / driver_pid / coverage fields, then run with the
clix-growth venv:

    /home/ubuntu/.hermes/venvs/clix-growth/bin/python post_vnc_handoff.py

Writes the raw Slack API response to stdout so the caller can capture `ts`.

Design rules (from headful-chrome-vnc §4 and tiktok-viral-research-via-google):
- Handoff is a TOP-LEVEL channel post for ops visibility, not a thread reply.
- Uses direct chat.postMessage (NOT send_message) so we can control exact text
  and avoid the gateway's Markdown → mrkdwn auto-convert on this ops message.
- Text is already in Slack mrkdwn (single-asterisk *bold*, `code` backticks,
  emoji shortcodes). Do NOT feed Markdown here.
- Keeps driver alive — the caller's scraper should be parked in
  time.sleep(86400) per §4, this script only publishes the alert.
"""
import json
import urllib.request

# --- EDIT PER INVOCATION -----------------------------------------------------
CHANNEL = "C0APW93G614"          # clix-app-growth-project
BLOCK_TYPE = "google-sorry"       # google-sorry | tiktok-captcha | turnstile | recaptcha | other
BLOCK_URL = "https://www.google.com/sorry/index?continue=...&q=..."
BLOCK_Q_INDEX = "Q14/18"          # e.g. "Q14/18" or "video 7/15"
DETECTED_AT_UTC = "2026-05-09T23:04:34Z"
DRIVER_PID = 220628
COVERAGE_LINE = "13/18 쿼리는 클린 수집 완료 (raw 99개 후보). 14~18번 tail만 손실."
EXTRA_CONTEXT = (
    # One-liner of diagnostic context. Optional — set to "" to skip.
    "2026-05-08 23:01 UTC 런도 정확히 같은 Q14 지점에서 블록 — 동일 날짜 내 "
    "2차 런의 예상된 tail 손실 (스킬 메모 `same-day second run`)."
)
# -----------------------------------------------------------------------------


def load_slack_token() -> str:
    env = {}
    with open("/home/ubuntu/.hermes/profiles/tarantino/.env") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.split("#", 1)[0].strip().strip('"').strip("'")
            env[k] = v
    return env["SLACK_BOT_TOKEN"]


def build_text() -> str:
    lines = [
        ":octagonal_sign: *VNC 수동 솔빙 요청 — 일일 보고서 차단됨*",
        f"*차단 종류*: {BLOCK_TYPE}",
        f"*차단 URL*: {BLOCK_URL} ({BLOCK_Q_INDEX})",
        f"*감지 시각*: {DETECTED_AT_UTC} (UTC)",
        f"*드라이버 PID*: {DRIVER_PID} (살려둠, Tarantino 프로필에 차단 페이지 열린 상태)",
        f"*커버리지*: {COVERAGE_LINE}",
        (
            "*요청*: noVNC(포트 6080, `DISPLAY=:1`) 접속해서 Chrome 창 안에서 "
            "수동 솔빙 부탁. Tarantino 프로필에 쿠키 자동 저장되니까 풀기만 하면 "
            "다음 틱에서 자연 통과됨."
        ),
        '*이 메시지에 "풀었음" 답글 주면 다음 정규 틱에서 이어서 재시도.*',
    ]
    if EXTRA_CONTEXT:
        lines.append(f"*참고*: {EXTRA_CONTEXT}")
    return "\n".join(lines)


def post_top_level(text: str, channel: str, token: str) -> dict:
    payload = {
        "channel": channel,
        "text": text,
        "mrkdwn": True,
        "unfurl_links": False,
        "unfurl_media": False,
    }
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


if __name__ == "__main__":
    token = load_slack_token()
    text = build_text()
    resp = post_top_level(text, CHANNEL, token)
    print(json.dumps(resp, ensure_ascii=False))
    if not resp.get("ok"):
        raise SystemExit(f"chat.postMessage failed: {resp}")
