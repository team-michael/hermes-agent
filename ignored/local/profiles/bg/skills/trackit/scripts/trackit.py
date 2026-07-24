#!/usr/bin/env python3
"""Trackit CRM CLI (Notifly workspace).

조회는 Record Query API(ids -> attribute-values -> 옵션/멤버 해석)를,
쓰기는 HTTP API(create/update/delete)를 감쌉니다. 표준 라이브러리만 사용.

인증: TRACKIT_API_TOKEN 환경변수 > TRACKIT_API_TOKEN_FILE > ~/.config/trackit/token > ./.trackit_token
"""

import argparse
import csv as csv_mod
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = os.environ.get("TRACKIT_BASE_URL", "https://api.trackit.so/v1")
TZ = os.environ.get("TRACKIT_TZ", "Asia/Seoul")
TZ_OFFSET = os.environ.get("TRACKIT_TZ_OFFSET", "+09:00")
CACHE_DIR = Path(os.environ.get("TRACKIT_CACHE_DIR", Path.home() / ".cache" / "trackit"))
CACHE_FILE = CACHE_DIR / "schema.json"
MAX_LIMIT = 500
SLEEP = 0.15

RELATIVE_DATE_OPS = {
    "today", "this_week", "this_month", "this_quarter", "this_year",
    "last_7_days", "last_1_month", "last_3_months", "last_6_months", "last_1_year",
}
NO_VALUE_OPS = RELATIVE_DATE_OPS | {"empty", "not_empty", "is_true", "is_false"}
FIELD_DEFAULTS = {
    "select": "selectOptionId", "status": "statusOptionId",
    "email_address": "emailAddress", "phone_number": "phoneNumber",
    "currency": "currencyValue", "record": "recordId", "relation_record": "recordId",
    "actor_reference": "actorId",
}
HEX24 = re.compile(r"^[0-9a-f]{24}$")


def fail(msg, code=2):
    sys.stdout.flush()
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def get_token():
    tok = os.environ.get("TRACKIT_API_TOKEN")
    if tok:
        return tok.strip()
    token_file = os.environ.get("TRACKIT_API_TOKEN_FILE")
    if token_file:
        p = Path(token_file).expanduser()
        if not p.is_file():
            fail(f"TRACKIT_API_TOKEN_FILE을 찾을 수 없습니다: {p}")
        tok = p.read_text().strip()
        if tok:
            return tok
        fail(f"TRACKIT_API_TOKEN_FILE이 비어 있습니다: {p}")
    for p in (Path.home() / ".config" / "trackit" / "token", Path(".trackit_token")):
        if p.is_file():
            return p.read_text().strip()
    fail("API 토큰이 없습니다. TRACKIT_API_TOKEN 환경변수를 설정하거나 ~/.config/trackit/token 파일을 만드세요.")


def api(method, path, body=None, retries=3, raise_error=False):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {get_token()}",
        "Content-Type": "application/json",
        "X-Timezone": TZ,
    })
    last = None
    for i in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")
            if e.code in (429, 500, 502, 503, 504) and i < retries - 1:
                time.sleep(1.5 * (i + 1))
                last = f"HTTP {e.code}: {detail}"
                continue
            if raise_error:
                raise RuntimeError(f"HTTP {e.code}: {detail}")
            if e.code == 401:
                fail("401 인증 실패. TRACKIT_API_TOKEN을 확인하세요.")
            fail(f"HTTP {e.code} {method} {path}\n{detail}")
        except urllib.error.URLError as e:
            if i < retries - 1:
                time.sleep(1.5 * (i + 1))
                last = str(e)
                continue
            fail(f"네트워크 오류: {e}")
    fail(f"재시도 실패: {last}")


# ---------------------------------------------------------------- schema cache

def refresh_schema():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    objects = api("GET", "/objects")["result"]
    groups = api("GET", "/groups")["result"]
    members = api("GET", "/members")["result"]
    attributes, options = {}, {}
    for kind, ents in (("objects", objects), ("groups", groups)):
        for e in ents:
            key = e["slug"] if kind == "objects" else e["_id"]
            attrs = api("GET", f"/{kind}/{key}/attributes")["result"]
            attributes[e["_id"]] = attrs
            time.sleep(SLEEP)
            for a in attrs:
                if a["type"] in ("select", "status"):
                    sub = "select-options" if a["type"] == "select" else "status-options"
                    try:
                        options[a["_id"]] = api("GET", f"/{kind}/{key}/attributes/{a['_id']}/{sub}")["result"]
                    except SystemExit:
                        options[a["_id"]] = []
                    time.sleep(SLEEP)
    ws = api("POST", f"/objects/{objects[0]['slug']}/records/ids", {"limit": 1})["result"]["workspaceId"]
    schema = {
        "fetchedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "workspaceId": ws,
        "objects": objects, "groups": groups,
        "attributes": attributes, "options": options, "members": members,
    }
    CACHE_FILE.write_text(json.dumps(schema, ensure_ascii=False))
    CACHE_FILE.chmod(0o600)
    return schema


def load_schema(refresh=False):
    if not refresh and CACHE_FILE.is_file():
        try:
            return json.loads(CACHE_FILE.read_text())
        except Exception:
            pass
    return refresh_schema()


class WS:
    """스키마 접근 헬퍼."""

    def __init__(self, schema):
        self.s = schema
        self._name_cache = {}

    # ---- entity ----
    def entity(self, ident):
        """오브젝트 slug/_id/이름 또는 그룹 _id/이름 -> entity dict."""
        q = ident.strip().lower()
        for o in self.s["objects"]:
            if q in (o["slug"].lower(), o["_id"].lower(),
                     (o.get("singularNoun") or "").lower(), (o.get("pluralNoun") or "").lower()):
                return {"kind": "objects", "id": o["_id"], "slug": o["slug"], "name": o.get("pluralNoun") or o["slug"], "raw": o}
        for g in self.s["groups"]:
            if q in (g["_id"].lower(), (g.get("slug") or "").lower(), (g.get("name") or "").lower()):
                return {"kind": "groups", "id": g["_id"], "slug": g.get("slug") or g["_id"], "name": g.get("name"), "raw": g}
        for g in self.s["groups"]:  # 그룹 이름 부분 일치
            if q in (g.get("name") or "").lower():
                return {"kind": "groups", "id": g["_id"], "slug": g.get("slug") or g["_id"], "name": g.get("name"), "raw": g}
        fail(f"오브젝트/그룹을 찾을 수 없음: {ident}\n오브젝트: "
             + ", ".join(o["slug"] for o in self.s["objects"])
             + "\n그룹: " + ", ".join(g.get("name", g["_id"]) for g in self.s["groups"]))

    def attrs(self, ent):
        return self.s["attributes"].get(ent["id"], [])

    def attr(self, ent, ident):
        q = ident.strip().lower()
        for a in self.attrs(ent):
            if q in (a["slug"].lower(), a["_id"].lower(), (a.get("name") or "").lower()):
                return a
        cands = [a for a in self.attrs(ent) if q in (a.get("name") or "").lower() or q in a["slug"].lower()]
        if len(cands) == 1:
            return cands[0]
        fail(f"'{ent['name']}'에서 속성을 찾을 수 없음: {ident}\n후보: "
             + ", ".join(f"{a['slug']}({a.get('name')})" for a in self.attrs(ent)))

    # ---- options / members ----
    def options(self, attr_id):
        return self.s["options"].get(attr_id, [])

    def option_name(self, attr_id, opt_id):
        for o in self.options(attr_id):
            if o["_id"] == opt_id:
                return o.get("name", opt_id)
        return opt_id

    def option_id(self, attr, text):
        opts = self.options(attr["_id"])
        t = text.strip().lower()
        for o in opts:
            if o.get("name", "").lower() == t or o["_id"] == text:
                return o["_id"]
        part = [o for o in opts if t in o.get("name", "").lower()]
        if len(part) == 1:
            return part[0]["_id"]
        fail(f"옵션을 찾을 수 없음: '{text}' (속성 {attr['slug']})\n옵션: "
             + ", ".join(o.get("name", "?") for o in opts))

    def member_name(self, user_id):
        for m in self.s["members"]:
            if m.get("userId") == user_id:
                return m.get("name") or m.get("emailAddress") or user_id
        return user_id

    def member_id(self, text):
        t = text.strip().lower()
        for m in self.s["members"]:
            if t in ((m.get("emailAddress") or "").lower(), (m.get("name") or "").lower(), m.get("userId", "")):
                return m["userId"]
        part = [m for m in self.s["members"] if t in (m.get("name") or "").lower() or t in (m.get("emailAddress") or "").lower()]
        if len(part) == 1:
            return part[0]["userId"]
        fail(f"멤버를 찾을 수 없음: '{text}'\n멤버: "
             + ", ".join(f"{m.get('name')}<{m.get('emailAddress')}>" for m in self.s["members"]))

    def object_by_id(self, oid):
        for o in self.s["objects"]:
            if o["_id"] == oid:
                return o
        return None

    def name_attr(self, obj_id):
        """오브젝트의 대표(이름) 속성 추정."""
        attrs = self.s["attributes"].get(obj_id, [])
        for slug in ("name", "title"):
            for a in attrs:
                if a["slug"] == slug and a["type"] == "text":
                    return a
        for nm in ("서비스명", "이름", "회사", "Name", "Title"):
            for a in attrs:
                if (a.get("name") or "") == nm and a["type"] == "text":
                    return a
        for a in attrs:
            if a["type"] == "text" and not a.get("isSystem"):
                return a
        for a in attrs:
            if a["type"] == "text":
                return a
        return None


# ---------------------------------------------------------------- query core

def ids_path(ent):
    return (f"/objects/{ent['slug']}/records/ids" if ent["kind"] == "objects"
            else f"/groups/{ent['id']}/entries/ids")


def values_path(ent):
    return (f"/objects/{ent['slug']}/records/attribute-values" if ent["kind"] == "objects"
            else f"/groups/{ent['id']}/entries/attribute-values")


def fetch_ids(ent, flt=None, sorts=None, limit=100, offset=0, fetch_all=False):
    """(ids, totalCount) 반환. limit>500이면 자동 페이지네이션."""
    collected, total = [], None
    cap = int(os.environ.get("TRACKIT_MAX_ROWS", 5000))
    target = cap if fetch_all else min(limit, cap)
    while len(collected) < target:
        step = min(MAX_LIMIT, target - len(collected))
        body = {"offset": offset, "limit": step}
        if flt:
            body["filter"] = flt
        if sorts:
            body["sorts"] = sorts
        r = api("POST", ids_path(ent), body)["result"]
        total = r["totalCount"]
        collected.extend(r["entityInstanceIds"])
        offset += step
        if offset >= total:
            break
        time.sleep(SLEEP)
    return collected, total


def fetch_values(ws, ent, ids, attr_ids):
    """{instanceId: {attrId: [value,...]}} 반환."""
    out = {}
    if len(attr_ids) > 100:
        print(f"주의: 속성 {len(attr_ids)}개 중 100개만 조회됩니다 (API 제한).", file=sys.stderr)
    key_ids = "recordIds" if ent["kind"] == "objects" else "entryIds"
    key_list = "records" if ent["kind"] == "objects" else "entries"
    key_id = "recordId" if ent["kind"] == "objects" else "entryId"
    for i in range(0, len(ids), MAX_LIMIT):
        chunk = ids[i:i + MAX_LIMIT]
        r = api("POST", values_path(ent), {key_ids: chunk, "attributeIds": attr_ids[:100]})["result"]
        for rec in r.get(key_list, []):
            out[rec[key_id]] = {a["attributeId"]: a.get("values", []) for a in rec.get("attributes", [])}
        if i + MAX_LIMIT < len(ids):
            time.sleep(SLEEP)
    return out


def collect_refs(values_by_id):
    refs = {}
    for attrs in values_by_id.values():
        for vals in attrs.values():
            for v in vals:
                if v.get("type") in ("record", "relation_record") and v.get("recordId"):
                    refs.setdefault(v.get("objectId"), set()).add(v["recordId"])
    return refs


def resolve_refs(ws, refs):
    """{recordId: 이름} 맵."""
    out = {}
    for oid, rids in refs.items():
        obj = ws.object_by_id(oid)
        na = ws.name_attr(oid) if obj else None
        if not obj or not na:
            continue
        ent = {"kind": "objects", "id": oid, "slug": obj["slug"]}
        vals = fetch_values(ws, ent, sorted(rids), [na["_id"]])
        for rid in rids:
            vlist = vals.get(rid, {}).get(na["_id"], [])
            out[rid] = vlist[0].get("value") if vlist else rid
    return out


def render_value(ws, v, refmap):
    t = v.get("type")
    if t in ("text", "number", "url", "domain", "checkbox", "rating", "json"):
        val = v.get("value")
        return json.dumps(val, ensure_ascii=False) if isinstance(val, (dict, list)) else str(val)
    if t == "currency":
        cv, cc = v.get("currencyValue"), v.get("currencyCode", "")
        try:
            return f"{cv:,.0f} {cc}".strip()
        except (TypeError, ValueError):
            return f"{cv} {cc}".strip()
    if t == "email_address":
        return v.get("emailAddress", "")
    if t == "phone_number":
        return v.get("phoneNumber", "")
    if t == "location":
        parts = [v.get(k) for k in ("countryCode", "state", "city", "addressLine")]
        return " ".join(p for p in parts if p)
    if t == "date":
        return v.get("calendarDate") or v.get("value", "")
    if t == "timestamp":
        return (v.get("value") or "")[:16]
    if t == "select":
        return v.get("selectOptionId", "")
    if t == "status":
        return v.get("statusOptionId", "")
    if t == "actor_reference":
        if v.get("actorType") == "user":
            return ws.member_name(v.get("actorId"))
        return f"{v.get('actorType')}:{str(v.get('actorId'))[:8]}"
    if t in ("record", "relation_record"):
        rid = v.get("recordId")
        return refmap.get(rid, rid or "")
    if t == "file":
        return v.get("filename", "file")
    if t == "interaction":
        for k in ("date", "value", "timestamp"):
            if v.get(k):
                return str(v[k])[:16]
        d = {k: x for k, x in v.items() if x is not None and k != "type"}
        return json.dumps(d, ensure_ascii=False)[:60]
    return json.dumps(v, ensure_ascii=False)[:60]


def render_cell(ws, attr, vals, refmap):
    parts = []
    for v in vals:
        t = v.get("type")
        if t == "select":
            parts.append(ws.option_name(attr["_id"], v.get("selectOptionId", "")))
        elif t == "status":
            parts.append(ws.option_name(attr["_id"], v.get("statusOptionId", "")))
        else:
            parts.append(render_value(ws, v, refmap))
    return "; ".join(str(p) for p in parts if p is not None and p != "None")


# ---------------------------------------------------------------- filter DSL

OP_ALIASES = {"=": "is", "!=": "is_not", "~": "contains"}


def build_condition(ws, ent, clause):
    """'slug[.field] op [value]' -> condition dict."""
    m = re.match(r"^\s*(\S+)\s+(\S+)(?:\s+(.*))?$", clause)
    if not m:
        fail(f"--where 형식 오류: '{clause}' (형식: '<속성> <연산자> [값]')")
    slug_field, op, value = m.group(1), m.group(2), (m.group(3) or "").strip()
    op = OP_ALIASES.get(op, op)
    field_override = None
    if "." in slug_field:
        slug_field, field_override = slug_field.split(".", 1)
    attr = ws.attr(ent, slug_field)
    t = attr["type"]
    field = field_override or FIELD_DEFAULTS.get(t, "value")
    if t == "location" and not field_override:
        fail("location 속성은 필드를 명시해야 함: 예) location.city contains 서울")

    if t in ("select", "status"):
        if op in ("is", "contains"):
            op = "contains#list"
        elif op in ("is_not", "not_contains"):
            op = "not_contains#list"
        val = None if op in NO_VALUE_OPS else ws.option_id(attr, value)
    elif t == "actor_reference":
        val = None if op in NO_VALUE_OPS else ws.member_id(value)
    elif t in ("record", "relation_record"):
        if op in ("is", "contains"):
            op = "contains#list"
        elif op in ("is_not", "not_contains"):
            op = "not_contains#list"
        if op in NO_VALUE_OPS:
            val = None
        elif HEX24.match(value):
            val = value
        else:
            val = resolve_record_ref(ws, attr, value)
    elif t in ("date", "timestamp"):
        if op in NO_VALUE_OPS:
            val = None
        else:
            val = value
            if re.match(r"^\d{4}-\d{2}-\d{2}$", value):
                suffix = "T23:59:59" if op in ("until", "after") else "T00:00:00"
                val = f"{value}{suffix}{TZ_OFFSET}"
    elif t in ("number", "rating", "currency"):
        if op in NO_VALUE_OPS:
            val = None
        else:
            try:
                val = json.loads(value)
            except (ValueError, json.JSONDecodeError):
                fail(f"숫자 값이 필요합니다: '{value}' (속성 {attr['slug']}, 쉼표 없이)")
    elif t == "checkbox":
        if op == "is" and value.lower() in ("true", "1", "yes"):
            op = "is_true"
        elif op == "is" and value.lower() in ("false", "0", "no"):
            op = "is_false"
        val = None
    else:
        val = None if op in NO_VALUE_OPS else value

    return {
        "type": "condition",
        "path": [{"entityType": ent["kind"], "entityId": ent["id"],
                  "attributeType": t, "attributeId": attr["_id"], "referencedEntityId": None}],
        "constraints": [{"field": field, "operator": op, "value": val,
                         "valueType": "static", "fieldLocation": "value"}],
    }


def resolve_record_ref(ws, attr, text):
    """레코드 참조 값(이름) -> recordId. 대상 오브젝트에서 이름으로 검색."""
    allowed = ((attr.get("config") or {}).get("recordReference") or {}).get("allowedObjectIds") or []
    if not allowed:
        fail(f"'{text}'를 recordId로 해석할 수 없음 (참조 대상 오브젝트 불명). 24자리 recordId를 직접 지정하세요.")
    oid = allowed[0]
    obj = ws.object_by_id(oid)
    na = ws.name_attr(oid)
    ent = {"kind": "objects", "id": oid, "slug": obj["slug"]}
    flt = {"operator": "and", "forms": [{
        "type": "condition",
        "path": [{"entityType": "objects", "entityId": oid, "attributeType": na["type"], "attributeId": na["_id"], "referencedEntityId": None}],
        "constraints": [{"field": "value", "operator": "contains", "value": text, "valueType": "static", "fieldLocation": "value"}]}]}
    ids, total = fetch_ids(ent, flt, limit=6)
    if total == 1:
        return ids[0]
    if total == 0:
        fail(f"{obj['slug']}에서 '{text}' 매칭 레코드 없음")
    vals = fetch_values(ws, ent, ids, [na["_id"]])
    names = [f"{i}={vals.get(i, {}).get(na['_id'], [{}])[0].get('value', '?')}" for i in ids]
    fail(f"{obj['slug']}에서 '{text}' 매칭 {total}건. recordId로 지정하세요:\n  " + "\n  ".join(names))


def build_filter(ws, ent, wheres, op="and"):
    if not wheres:
        return None
    return {"operator": op, "forms": [build_condition(ws, ent, w) for w in wheres]}


def build_sorts(ws, ent, sort_specs):
    sorts = []
    for spec in sort_specs or []:
        parts = spec.split()
        attr = ws.attr(ent, parts[0])
        direction = parts[1] if len(parts) > 1 else "asc"
        sorts.append({
            "path": [{"workspaceId": ws.s["workspaceId"], "entityType": ent["kind"],
                      "entityId": ent["id"], "entitySlug": ent["slug"],
                      "attributeId": attr["_id"], "attributeSlug": attr["slug"],
                      "attributeType": attr["type"], "referencedEntityId": None}],
            "field": FIELD_DEFAULTS.get(attr["type"], "value"),
            "direction": direction,
        })
    return sorts


# ---------------------------------------------------------------- output

def print_table(headers, rows, max_w=44):
    def cut(s):
        s = str(s)
        return s if len(s) <= max_w else s[:max_w - 1] + "…"
    rows = [[cut(c) for c in r] for r in rows]
    widths = [max(len(str(h)), *(len(r[i]) for r in rows)) if rows else len(str(h))
              for i, h in enumerate(headers)]
    line = "  ".join(str(h).ljust(w) for h, w in zip(headers, widths))
    print(line)
    print("-" * min(len(line), 160))
    for r in rows:
        print("  ".join(str(c).ljust(w) for c, w in zip(r, widths)))


def default_fields(ws, ent):
    keep_sys = {"name", "domains", "email-addresses", "title", "company-name", "email-address",
                "description", "job-title", "company", "stage", "owner", "priority",
                "estimated-contract-value", "projected-close-date", "close-confidence",
                "parent-record", "created-date", "due-date", "completed", "assignees", "customer",
                "date", "type", "category", "referenced-records"}
    out = []
    for a in ws.attrs(ent):
        if a["type"] in ("interaction", "json"):
            continue
        if a["slug"] in ("id", "list-entries", "leads", "team"):
            continue
        if not a.get("isSystem") or a["slug"] in keep_sys:
            out.append(a)
    return out[:30]


def rows_for(ws, ent, ids, attrs, resolve=True):
    vals = fetch_values(ws, ent, ids, [a["_id"] for a in attrs])
    refmap = resolve_refs(ws, collect_refs(vals)) if resolve else {}
    rows = []
    for i in ids:
        row = [render_cell(ws, a, vals.get(i, {}).get(a["_id"], []), refmap) for a in attrs]
        rows.append(row + [i])
    return rows


def emit(ws, ent, ids, total, attrs, args):
    rows = rows_for(ws, ent, ids, attrs)
    headers = [a.get("name") or a["slug"] for a in attrs] + ["_id"]
    if getattr(args, "csv", None):
        with open(args.csv, "w", newline="", encoding="utf-8-sig") as f:
            w = csv_mod.writer(f)
            w.writerow(headers)
            w.writerows(rows)
        print(f"CSV 저장: {args.csv} ({len(rows)}행 / 전체 {total}건)")
    elif getattr(args, "json_out", False):
        print(json.dumps({"totalCount": total, "rows": [dict(zip(headers, r)) for r in rows]},
                         ensure_ascii=False, indent=1))
    else:
        print_table(headers, rows)
        print(f"\n{len(rows)}행 표시 / 조건 일치 전체 {total}건")


# ---------------------------------------------------------------- commands

def cmd_schema(args):
    ws = WS(load_schema(refresh=args.refresh))
    s = ws.s
    if args.entity:
        ent = ws.entity(args.entity)
        print(f"[{ent['kind']}] {ent['name']}  id={ent['id']} slug={ent['slug']}")
        hdr = ["slug", "name", "type", "flags", "attributeId"]
        rows = []
        for a in ws.attrs(ent):
            flags = ",".join(f for f, ok in (("multi", a.get("isMultiple")), ("sys", a.get("isSystem"))) if ok)
            rows.append([a["slug"], a.get("name"), a["type"], flags, a["_id"]])
        print_table(hdr, rows)
        for a in ws.attrs(ent):
            if a["type"] in ("select", "status") and ws.options(a["_id"]):
                print(f"\n옵션 [{a.get('name')} ({a['slug']})]:")
                for o in ws.options(a["_id"]):
                    print(f"  {o['_id']}  {o.get('name')}")
        return
    print(f"workspace={s['workspaceId']}  fetchedAt={s['fetchedAt']}  (갱신: schema --refresh)")
    print("\n오브젝트:")
    for o in s["objects"]:
        print(f"  {o['slug']:<14} {o.get('pluralNoun', ''):<14} attrs={len(s['attributes'].get(o['_id'], []))}  id={o['_id']}")
    print("\n그룹 (entries):")
    for g in s["groups"]:
        parent = ws.object_by_id(g.get("parentObjectId"))
        print(f"  {g.get('name', ''):<24} parent={parent['slug'] if parent else '?'}  attrs={len(s['attributes'].get(g['_id'], []))}  id={g['_id']}")
    print("\n멤버:")
    for m in s["members"]:
        print(f"  {m.get('name', ''):<16} {m.get('emailAddress', ''):<28} {m.get('type', '')}  userId={m.get('userId')}")


def cmd_members(args):
    ws = WS(load_schema())
    for m in ws.s["members"]:
        print(f"{m.get('name', ''):<16} {m.get('emailAddress', ''):<28} {m.get('type', '')}  userId={m.get('userId')}")


def cmd_query(args):
    ws = WS(load_schema())
    ent = ws.entity(args.object)
    flt = build_filter(ws, ent, args.where, "or" if args.or_mode else "and")
    sorts = build_sorts(ws, ent, args.sort)
    if args.count:
        _, total = fetch_ids(ent, flt, sorts, limit=1)
        print(total)
        return
    if args.group_by:
        attr = ws.attr(ent, args.group_by)
        ids, total = fetch_ids(ent, flt, fetch_all=True)
        vals = fetch_values(ws, ent, ids, [attr["_id"]])
        refmap = resolve_refs(ws, collect_refs(vals)) if attr["type"] in ("record", "relation_record") else {}
        counts = {}
        for i in ids:
            vlist = vals.get(i, {}).get(attr["_id"], [])
            if not vlist:
                counts["(없음)"] = counts.get("(없음)", 0) + 1
            for v in vlist:
                key = render_cell(ws, attr, [v], refmap) or "(없음)"
                counts[key] = counts.get(key, 0) + 1
        rows = sorted(counts.items(), key=lambda kv: -kv[1])
        print_table([attr.get("name") or attr["slug"], "건수"], [[k, v] for k, v in rows])
        print(f"\n전체 {total}건 (다중값 속성은 값 단위로 집계)")
        return
    ids, total = fetch_ids(ent, flt, sorts, limit=args.limit, fetch_all=args.all)
    if args.ids_only:
        for i in ids:
            print(i)
        print(f"# {len(ids)} / {total}", file=sys.stderr)
        return
    if args.fields == "all":
        attrs = [a for a in ws.attrs(ent)][:100]
    elif args.fields:
        attrs = [ws.attr(ent, f.strip()) for f in args.fields.split(",")]
    else:
        attrs = default_fields(ws, ent)
    emit(ws, ent, ids, total, attrs, args)


def groups_for_object(ws, obj_id):
    return [g for g in ws.s["groups"] if g.get("parentObjectId") == obj_id]


def entries_for_record(ws, obj_id, rec_id):
    """레코드 -> 소속 그룹(파이프라인) 엔트리 [(그룹명, {slug: 렌더값})]."""
    found = []
    for g in groups_for_object(ws, obj_id):
        ent = {"kind": "groups", "id": g["_id"], "slug": g.get("slug") or g["_id"], "name": g.get("name")}
        pr = next((a for a in ws.attrs(ent) if a["slug"] == "parent-record"), None)
        if not pr:
            continue
        flt = {"operator": "and", "forms": [{
            "type": "condition",
            "path": [{"entityType": "groups", "entityId": g["_id"], "attributeType": "relation_record",
                      "attributeId": pr["_id"], "referencedEntityId": None}],
            "constraints": [{"field": "recordId", "operator": "contains#list", "value": rec_id,
                             "valueType": "static", "fieldLocation": "value"}]}]}
        ids, total = fetch_ids(ent, flt, limit=20)
        if not ids:
            continue
        wanted = [a for a in ws.attrs(ent)
                  if (not a.get("isSystem") and a["type"] not in ("interaction", "json"))
                  or a["slug"] == "created-date"]
        vals = fetch_values(ws, ent, ids, [a["_id"] for a in wanted])
        for eid in ids:
            info = {a["slug"]: render_cell(ws, a, vals.get(eid, {}).get(a["_id"], []), {}) for a in wanted}
            info["_entryId"] = eid
            found.append((g.get("name"), info))
        time.sleep(SLEEP)
    return found


def cmd_lookup(args):
    ws = WS(load_schema())
    q = args.text
    targets = ["companies", "people", "braze", "s_leads"] if args.object == "all" else [args.object]
    for slug in targets:
        ent = ws.entity(slug)
        search_attrs = {
            "companies": ["name", "domains"],
            "people": ["name", "email-addresses"],
            "braze": ["서비스명", "회사", "도메인", "홈페이지"],
            "s_leads": ["company-name", "name", "email-address"],
        }.get(slug, ["name"])
        forms = []
        for sa in search_attrs:
            try:
                a = ws.attr(ent, sa)
            except SystemExit:
                continue
            field = FIELD_DEFAULTS.get(a["type"], "value")
            forms.append({"type": "condition",
                          "path": [{"entityType": ent["kind"], "entityId": ent["id"],
                                    "attributeType": a["type"], "attributeId": a["_id"], "referencedEntityId": None}],
                          "constraints": [{"field": field, "operator": "contains", "value": q,
                                           "valueType": "static", "fieldLocation": "value"}]})
        flt = {"operator": "or", "forms": forms}
        ids, total = fetch_ids(ent, flt, limit=args.limit)
        if total == 0:
            print(f"[{slug}] 0건")
            continue
        print(f"\n[{slug}] {total}건" + (f" (상위 {len(ids)}건 표시)" if total > len(ids) else ""))
        attrs = default_fields(ws, ent)
        vals = fetch_values(ws, ent, ids, [a["_id"] for a in attrs])
        refmap = resolve_refs(ws, collect_refs(vals))
        for rid in ids:
            cells = [(a.get("name") or a["slug"], render_cell(ws, a, vals.get(rid, {}).get(a["_id"], []), refmap)) for a in attrs]
            summary = " | ".join(f"{n}: {v}" for n, v in cells if v)
            print(f"- {summary}  [_id={rid}]")
            if not args.no_entries:
                for gname, info in entries_for_record(ws, ent["id"], rid):
                    detail = " | ".join(f"{k}: {v}" for k, v in info.items() if v and not k.startswith("_"))
                    print(f"    · {gname}: {detail or '(속성값 없음)'}")


def cmd_pipeline(args):
    ws = WS(load_schema())
    ent = ws.entity(args.group)
    if ent["kind"] != "groups":
        fail(f"'{args.group}'은 그룹이 아닙니다. schema로 그룹 이름을 확인하세요.")
    stage_attr = next((a for a in ws.attrs(ent) if a["type"] == "status"), None)
    if not stage_attr:
        fail("이 그룹에 status(stage) 속성이 없습니다.")
    wheres = list(args.where or [])
    if args.stage:
        wheres.append(f"{stage_attr['slug']} is {args.stage}")
    flt = build_filter(ws, ent, wheres)
    ids, total = fetch_ids(ent, flt, fetch_all=True)
    wanted = [a for a in ws.attrs(ent)
              if a["slug"] in ("parent-record", "created-date")
              or (not a.get("isSystem") and a["type"] not in ("interaction", "json"))
              or a["_id"] == stage_attr["_id"]]
    vals = fetch_values(ws, ent, ids, [a["_id"] for a in wanted])
    refmap = resolve_refs(ws, collect_refs(vals))
    opt_list = ws.options(stage_attr["_id"])
    order = {o["_id"]: i for i, o in enumerate(opt_list)}  # 옵션 목록 순서 = 표시 순서
    names = {o["_id"]: o.get("name") for o in opt_list}
    by_stage = {}
    for eid in ids:
        svals = vals.get(eid, {}).get(stage_attr["_id"], [])
        sid = svals[0].get("statusOptionId") if svals else None
        by_stage.setdefault(sid, []).append(eid)
    print(f"파이프라인: {ent['name']}  (전체 {total}건)\n")
    headers = [a.get("name") or a["slug"] for a in wanted if a["_id"] != stage_attr["_id"]] + ["_entryId"]
    for sid in sorted(by_stage, key=lambda x: order.get(x, 10 ** 9)):
        sname = names.get(sid) or (sid or "(단계 없음)")
        eids = by_stage[sid]
        total_value = 0.0
        rows = []
        for eid in eids:
            row = []
            for a in wanted:
                if a["_id"] == stage_attr["_id"]:
                    continue
                cell = render_cell(ws, a, vals.get(eid, {}).get(a["_id"], []), refmap)
                if a["slug"] == "estimated-contract-value":
                    for v in vals.get(eid, {}).get(a["_id"], []):
                        try:
                            total_value += float(v.get("currencyValue") or 0)
                        except (TypeError, ValueError):
                            pass
                row.append(cell)
            rows.append(row + [eid])
        vs = f"  (예상 금액 합계 {total_value:,.0f})" if total_value else ""
        print(f"### {sname} — {len(eids)}건{vs}")
        print_table(headers, rows)
        print()


# ---------------------------------------------------------------- write ops

def parse_match(ws, ent, pairs):
    """slug/표시이름=값 -> 쓰기 API filter (slug 검증·해석 포함)."""
    flt = {}
    for p in pairs:
        if "=" not in p:
            fail(f"--match 형식 오류: '{p}' (형식: slug=값)")
        k, v = p.split("=", 1)
        attr = ws.attr(ent, k.strip())
        flt.setdefault(attr["slug"], []).append(v.strip())
    return flt


def normalize_values(ws, ent, values):
    """values 키를 slug로 해석·검증하고 스칼라를 배열로 감싼다."""
    fixed = {}
    for k, v in values.items():
        attr = ws.attr(ent, k)
        fixed[attr["slug"]] = v if isinstance(v, list) else [v]
    return fixed


def preview_write_targets(ws, ent, match_filter):
    """쓰기 filter와 같은 조건을 Query API로 미리 조회."""
    wheres = []
    for slug, vals in match_filter.items():
        attr = ws.attr(ent, slug)
        for v in vals:
            op = "is"
            if attr["type"] in ("select", "status", "record", "relation_record"):
                op = "contains#list"
            wheres.append(f"{slug} {op} {v}")
    try:
        flt = build_filter(ws, ent, wheres)
        ids, total = fetch_ids(ent, flt, limit=10)
        na = ws.name_attr(ent["id"])
        names = {}
        if na and ids:
            vals = fetch_values(ws, ent, ids, [na["_id"]])
            names = {i: (vals.get(i, {}).get(na["_id"], [{}]) or [{}])[0].get("value", "?") for i in ids}
        return total, [(i, names.get(i, "?")) for i in ids]
    except SystemExit:
        return None, []


def cmd_create(args):
    ws = WS(load_schema())
    ent = ws.entity(args.object)
    if ent["kind"] != "objects":
        fail("생성은 오브젝트 레코드만 지원합니다 (그룹 엔트리 쓰기 API는 미제공).")
    if args.csv:
        return bulk_create(ws, ent, args)
    if not args.values:
        fail("--values 또는 --csv 가 필요합니다.")
    values = normalize_values(ws, ent, json.loads(args.values))
    body = {"values": values}
    print(f"생성 대상: {ent['slug']}")
    print(json.dumps(body, ensure_ascii=False, indent=1))
    if not args.yes:
        print("\n(미실행) 실제 생성하려면 --yes 를 붙이세요.")
        return
    r = api("POST", f"/objects/{ent['slug']}/records", body)
    print("생성 완료:")
    print(json.dumps(r, ensure_ascii=False, indent=1))


def bulk_create(ws, ent, args):
    """CSV 일괄 생성. 헤더 = 속성 slug 또는 표시 이름. 행별 성공/실패 리포트."""
    with open(args.csv, encoding="utf-8-sig") as f:
        rows = list(csv_mod.DictReader(f))
    if not rows:
        fail("CSV에 데이터 행이 없습니다.")
    header_map = {h: ws.attr(ent, h)["slug"] for h in rows[0].keys()}  # 헤더 검증
    print(f"일괄 생성 대상: {ent['slug']} / {len(rows)}행")
    print(f"컬럼 매핑: {json.dumps(header_map, ensure_ascii=False)}")
    print("샘플 (첫 2행):")
    for row in rows[:2]:
        print(" ", json.dumps({header_map[k]: v for k, v in row.items() if v and v.strip()}, ensure_ascii=False))
    if not args.yes:
        print(f"\n(미실행) 실제로 {len(rows)}건 생성하려면 --yes 를 붙이세요.")
        return
    ok, failed = 0, []
    for idx, row in enumerate(rows, start=2):  # CSV 행 번호 (헤더=1행)
        values = {header_map[k]: [v.strip()] for k, v in row.items() if v and v.strip()}
        if not values:
            continue
        try:
            api("POST", f"/objects/{ent['slug']}/records", {"values": values}, raise_error=True)
            ok += 1
        except RuntimeError as e:
            msg = str(e)
            failed.append((idx, msg[:160]))
        time.sleep(0.2)
    print(f"\n완료: 성공 {ok}건 / 실패 {len(failed)}건")
    for idx, msg in failed:
        print(f"  {idx}행: {msg}")
    if failed:
        print("힌트: 'must be unique' 에러는 이메일/도메인 중복(이미 존재하는 레코드)입니다.")


def cmd_update(args):
    ws = WS(load_schema())
    ent = ws.entity(args.object)
    if ent["kind"] != "objects":
        fail("수정은 오브젝트 레코드만 지원합니다.")
    flt = parse_match(ws, ent, args.match)
    values = normalize_values(ws, ent, json.loads(args.values))
    total, sample = preview_write_targets(ws, ent, flt)
    if total is not None:
        print(f"매칭 예상: {total}건")
        for i, n in sample:
            print(f"  - {n}  [{i}]")
        if total == 0:
            print("매칭 0건. 실행 중단.")
            return
        if total > 1 and not args.allow_multiple:
            print("\n2건 이상 매칭. 정말 전부 수정하려면 --allow-multiple 을 명시하세요. 실행 중단.")
            return
    else:
        print("주의: 매칭 미리보기를 만들 수 없었습니다. filter를 다시 확인하세요.")
    body = {"filter": flt, "values": values, "allowMultiple": bool(args.allow_multiple)}
    print("\nPUT body:")
    print(json.dumps(body, ensure_ascii=False, indent=1))
    if not args.yes:
        print("\n(미실행) 실제 수정하려면 --yes 를 붙이세요.")
        return
    r = api("PUT", f"/objects/{ent['slug']}/records", body)
    print("수정 완료:")
    print(json.dumps(r, ensure_ascii=False, indent=1))


def cmd_delete(args):
    ws = WS(load_schema())
    ent = ws.entity(args.object)
    if ent["kind"] != "objects":
        fail("삭제는 오브젝트 레코드만 지원합니다.")
    flt = parse_match(ws, ent, args.match)
    total, sample = preview_write_targets(ws, ent, flt)
    if total is not None:
        print(f"매칭 예상: {total}건")
        for i, n in sample:
            print(f"  - {n}  [{i}]")
        if total == 0:
            print("매칭 0건. 실행 중단.")
            return
        if total > 1:
            print("\n삭제는 1건 매칭일 때만 허용합니다. 조건을 좁히세요. 실행 중단.")
            return
    body = {"filter": flt, "allowMultiple": False}
    print("\nDELETE body:")
    print(json.dumps(body, ensure_ascii=False, indent=1))
    if not args.yes:
        print("\n(미실행) 실제 삭제하려면 --yes 를 붙이세요.")
        return
    r = api("POST", f"/objects/{ent['slug']}/records/delete", body)
    print("삭제 완료:")
    print(json.dumps(r, ensure_ascii=False, indent=1))


def cmd_raw(args):
    method = args.method.upper()
    p = args.path.lower()
    read_post = p.endswith("/ids") or p.endswith("/attribute-values")
    writeish = method in ("PUT", "DELETE", "PATCH") or (method == "POST" and not read_post)
    if writeish and not args.allow_write:
        fail("raw로 쓰기성 호출은 --allow-write 플래그가 필요합니다. "
             "가능하면 미리보기가 내장된 create/update/delete 명령을 사용하세요.")
    body = None
    if args.body:
        body = json.loads(args.body)
    elif args.body_file:
        body = json.loads(Path(args.body_file).read_text())
    r = api(method, args.path, body)
    print(json.dumps(r, ensure_ascii=False, indent=1))


# ---------------------------------------------------------------- main

def main():
    p = argparse.ArgumentParser(description="Trackit CRM CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("schema", help="스키마 요약 / 갱신")
    s.add_argument("--refresh", action="store_true")
    s.add_argument("--entity", help="오브젝트/그룹 상세 (속성+옵션)")
    s.set_defaults(fn=cmd_schema)

    s = sub.add_parser("members", help="멤버 목록")
    s.set_defaults(fn=cmd_members)

    s = sub.add_parser("query", help="레코드/엔트리 조회")
    s.add_argument("--object", "-o", required=True, help="오브젝트 slug 또는 그룹 이름")
    s.add_argument("--where", "-w", action="append", default=[], help="'<속성> <연산자> [값]' (반복 = AND)")
    s.add_argument("--or", dest="or_mode", action="store_true", help="where들을 OR로 결합")
    s.add_argument("--sort", action="append", help="'<속성> [asc|desc]'")
    s.add_argument("--fields", "-f", help="쉼표구분 속성 slug 목록, 또는 all")
    s.add_argument("--limit", "-n", type=int, default=100)
    s.add_argument("--all", action="store_true", help="전체 페이지네이션")
    s.add_argument("--count", action="store_true", help="건수만")
    s.add_argument("--ids", dest="ids_only", action="store_true", help="ID만")
    s.add_argument("--group-by", help="속성값별 건수 집계 (예: --group-by categories)")
    s.add_argument("--csv", help="CSV 저장 경로")
    s.add_argument("--json", dest="json_out", action="store_true")
    s.set_defaults(fn=cmd_query)

    s = sub.add_parser("lookup", help="이름/도메인/이메일로 통합 검색 (owner·이력 확인)")
    s.add_argument("text")
    s.add_argument("--object", "-o", default="all", help="companies|people|braze|s_leads|all")
    s.add_argument("--limit", "-n", type=int, default=5)
    s.add_argument("--no-entries", action="store_true", help="회사의 그룹(파이프라인) 이력 생략")
    s.set_defaults(fn=cmd_lookup)

    s = sub.add_parser("pipeline", help="그룹 파이프라인 현황 (단계별)")
    s.add_argument("--group", "-g", default="Notifly - Acquisition")
    s.add_argument("--stage", help="특정 단계만")
    s.add_argument("--where", "-w", action="append", default=[])
    s.set_defaults(fn=cmd_pipeline)

    s = sub.add_parser("create", help="레코드 생성 (--yes 필요). --csv로 일괄 생성")
    s.add_argument("--object", "-o", required=True)
    s.add_argument("--values", help='JSON: {"name": ["..."], ...} (키는 slug 또는 표시 이름)')
    s.add_argument("--csv", help="CSV 일괄 생성 (헤더 = slug 또는 표시 이름)")
    s.add_argument("--yes", action="store_true")
    s.set_defaults(fn=cmd_create)

    s = sub.add_parser("update", help="레코드 수정 (미리보기 후 --yes)")
    s.add_argument("--object", "-o", required=True)
    s.add_argument("--match", "-m", action="append", required=True, help="slug=값 (쓰기 API filter)")
    s.add_argument("--values", required=True, help="JSON")
    s.add_argument("--allow-multiple", action="store_true")
    s.add_argument("--yes", action="store_true")
    s.set_defaults(fn=cmd_update)

    s = sub.add_parser("delete", help="레코드 삭제 (1건 매칭 + --yes 필수)")
    s.add_argument("--object", "-o", required=True)
    s.add_argument("--match", "-m", action="append", required=True)
    s.add_argument("--yes", action="store_true")
    s.set_defaults(fn=cmd_delete)

    s = sub.add_parser("raw", help="임의 API 호출 (쓰기 경로는 --allow-write)")
    s.add_argument("--method", default="GET")
    s.add_argument("--path", required=True)
    s.add_argument("--body")
    s.add_argument("--body-file")
    s.add_argument("--allow-write", action="store_true")
    s.set_defaults(fn=cmd_raw)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
