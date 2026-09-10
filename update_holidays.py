#!/usr/bin/env python3
"""공휴일 자동 수집 — 정부 특일정보 API(정답) + 구글 캘린더 ICS(먼 미래 보충) → holidays.json.

    python update_holidays.py [--dry-run]

## 두 출처의 역할

1. **정부(공공데이터포털 · 한국천문연구원 특일정보, 서비스 ID 15012690)** — 관공서 공휴일의
   원본. 임시공휴일·대체공휴일이 지정되면 여기에 실린다. 올해·내년 정도만 제공한다.
   키가 필요하다(무료, 자동 승인) → 환경변수 `DATA_GO_KR_KEY`(GitHub Actions 는 secret).
   정부가 **한 해를 온전히**(GOV_MIN_PER_YEAR 개 이상) 돌려주면 그 해는 정부가 정답이다:
     · 정부에 있는 날은 바로 더한다(기다리지 않는다).
     · 정부에 없는 날(오늘 이후)은 GOV_RETRACT_AFTER_DAYS 일 연속 없으면 `removed` 로 취소한다.
       (하루짜리 API 장애·부분 응답에 휘둘리지 않으려는 최소한의 유예.)
     · 그 해엔 구글이 더하는 것을 받지 않는다(정부가 모르는 날을 구글 때문에 넣었다 빼는 왕복 방지).
2. **구글 캘린더 '대한민국의 휴일' ICS** — 키 불필요, 2031년까지. 정부가 아직 모르는
   해에만 쓴다. 구글은 미래 연도의 대체공휴일·선거일을 빠뜨리므로 "구글에 없다"는 이유로는
   지우지 않고, 구글이 **알다가 거둬들인** 날만 RETRACT_AFTER_DAYS 일 뒤에 취소한다.

키가 없으면 2번만 동작한다(예전 방식). 어느 쪽이든 한 번에 MAX_AUTO_RETRACT 개보다 많이
취소하게 되면 출처 장애·형식 변경일 수 있으니 손대지 않고 이슈(report.md)로 사람에게 넘긴다.

출처가 언제 무엇을 알았는지는 source_seen.json 에 남기고, 비교 결과는 STATUS.md 에 적는다.
"""
import io
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date

ICS_URL = (
    "https://calendar.google.com/calendar/ical/"
    "ko.south_korea%23holiday%40group.v.calendar.google.com/public/basic.ics"
)
GOV_URL = "https://apis.data.go.kr/B090041/openapi/service/SpcdeInfoService/getRestDeInfo"
GOV_KEY_ENV = "DATA_GO_KR_KEY"

# 앱이 코드로 매년 계산하는 고정 양력 공휴일 — dates 에 넣으면 중복이다.
# (출처가 이 날을 거둬들이면 removed 로는 취소한다 — 앱 내장을 끄는 유일한 길이므로.)
FIXED = {(1, 1), (3, 1), (5, 5), (6, 6), (8, 15), (10, 3), (10, 9), (12, 25)}

# 앱이 2026년부터 코드로 계산하는 날(2026년 법 개정으로 공휴일이 된 노동절·제헌절).
# dates 에도 두지만(구 빌드용), 출처가 거둬들이면 removed 로 취소해야 내장 계산까지 꺼진다.
APP_COMPUTED_SINCE = {(5, 1): 2026, (7, 17): 2026}

# 관공서 공휴일이 아닌데 출처가 '공휴일'로 표시하는 것을 이름으로 거른다. 지금은 없다.
#  · 노동절은 2026-09-10까지 여기 있었다 — 2026년 법 개정으로 관공서 공휴일이 돼 뺐다.
#  · 법이 또 바뀌면 정부 출처가 먼저 반영하므로 보통은 손댈 일이 없다.
EXCLUDE_KEYWORDS: set[str] = set()

# 이 범위 밖은 무시(출처에 과거 몇 년치가 같이 들어 있다).
YEAR_MIN, YEAR_MAX = 2025, 2035

SEEN_PATH = "source_seen.json"
STATUS_PATH = "STATUS.md"
REPORT_PATH = "report.md"          # 있으면 워크플로가 이슈를 만든다

RETRACT_AFTER_DAYS = 7             # 구글: 알던 날이 이 기간 이상 안 보여야 거둬들인 것으로 본다
GOV_RETRACT_AFTER_DAYS = 3         # 정부: 온전한 연도 응답에 이 기간 연속 없으면 취소
GOV_MIN_PER_YEAR = 12              # 정부 응답이 이보다 적으면 그 해는 "아직 모름"으로 본다
MAX_AUTO_RETRACT = 3               # 한 번에 이보다 많이 사라지면 사람에게 넘긴다
SNAPSHOT_REFRESH_DAYS = 7          # 변화가 없어도 이 주기로 스냅샷·STATUS 를 갱신


# ── 출처 1: 정부 특일정보 ──────────────────────────────────────────────────

def fetch_gov(key: str, year: int) -> str:
    # ★키는 urlencode 로 한 번만 인코딩한다. 포털의 '인코딩 키'를 다시 인코딩하면
    #   SERVICE_KEY_IS_NOT_REGISTERED_ERROR 가 난다 — '디코딩 키'를 secret 에 넣을 것.
    q = f"serviceKey={urllib.parse.quote(key, safe='')}&solYear={year}&numOfRows=100&_type=json"
    req = urllib.request.Request(f"{GOV_URL}?{q}", headers={"User-Agent": "check_holidays/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        # 키 오류는 403 + 본문(JSON)으로 온다 — 본문을 돌려줘 parse_gov 가 이유를 읽게 한다.
        body = e.read().decode("utf-8", "replace")
        if body.strip():
            return body
        raise


def parse_gov(raw: str) -> dict:
    """정부 응답 → (YYYY-MM-DD → 이름), isHoliday == 'Y' 만. 오류 응답이면 ValueError."""
    try:
        obj = json.loads(raw)
    except ValueError:
        m = re.search(r"<returnAuthMsg>(.*?)</returnAuthMsg>|<errMsg>(.*?)</errMsg>", raw)
        raise ValueError(f"JSON 아님: {(m.group(1) or m.group(2)) if m else raw[:80]!r}")
    if "OpenAPI_ServiceResponse" in obj:  # 키 오류 등은 이 모양으로 온다
        h = obj["OpenAPI_ServiceResponse"].get("cmmMsgHeader", {})
        raise ValueError(f"{h.get('errMsg')} / {h.get('returnAuthMsg')}")
    resp = obj.get("response", {})
    code = str(resp.get("header", {}).get("resultCode", ""))
    if code not in ("00", "0"):
        raise ValueError(f"resultCode={code} {resp.get('header', {}).get('resultMsg')}")
    items = resp.get("body", {}).get("items") or {}
    item = items.get("item", []) if isinstance(items, dict) else []
    if isinstance(item, dict):   # 항목이 하나면 리스트가 아니라 객체로 온다
        item = [item]
    out = {}
    for it in item:
        if str(it.get("isHoliday", "")).upper() != "Y":
            continue
        ds = str(it.get("locdate", ""))
        if not re.fullmatch(r"\d{8}", ds):
            continue
        y, mo, dd = int(ds[:4]), int(ds[4:6]), int(ds[6:])
        try:
            date(y, mo, dd)
        except ValueError:
            continue
        out[f"{y:04d}-{mo:02d}-{dd:02d}"] = str(it.get("dateName", "")).strip()
    return out


def gov_holidays(key: str, years, fetch=fetch_gov):
    """연도별로 정부에 묻는다. 반환 (found, covered_years, errors).
    covered_years 는 GOV_MIN_PER_YEAR 개 이상 돌려준 해만 — 그 해에 한해 정부가 정답이다."""
    found, covered, errors = {}, set(), []
    for y in years:
        try:
            got = parse_gov(fetch(key, y))
        except Exception as e:  # 네트워크·키·형식 — 그 해는 모르는 것으로
            errors.append(f"{y}: {e}")
            continue
        if len(got) >= GOV_MIN_PER_YEAR:
            covered.add(y)
            found.update(got)
        else:
            errors.append(f"{y}: {len(got)}개뿐이라 아직 없는 해로 봄")
    return found, covered, errors


# ── 출처 2: 구글 캘린더 ────────────────────────────────────────────────────

def fetch_ics(url: str = ICS_URL) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "check_holidays/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def parse_ics(raw: str):
    """(YYYY-MM-DD → 이름). DESCRIPTION 이 '공휴일' 인 것만. 고정 양력도 **포함**한다
    (거둬들임 감지에 필요) — dates 에 넣을지는 호출부가 FIXED 로 거른다."""
    raw = raw.replace("\r\n ", "").replace("\r\n", "\n")  # ICS 줄 접힘 해제
    out = {}
    for blk in raw.split("BEGIN:VEVENT")[1:]:
        m_d = re.search(r"DTSTART;VALUE=DATE:(\d{8})", blk)
        m_s = re.search(r"SUMMARY:(.*)", blk)
        m_x = re.search(r"DESCRIPTION:(.*)", blk)
        if not (m_d and m_s):
            continue
        # '기념일'(식목일·어버이날 등)은 쉬는 날이 아니다.
        if not (m_x and m_x.group(1).strip().startswith("공휴일")):
            continue
        ds = m_d.group(1)
        y, mo, dd = int(ds[:4]), int(ds[4:6]), int(ds[6:])
        if not (YEAR_MIN <= y <= YEAR_MAX):
            continue
        name = m_s.group(1).strip()
        if any(k in name for k in EXCLUDE_KEYWORDS):
            continue
        try:
            date(y, mo, dd)
        except ValueError:
            continue
        out[f"{y:04d}-{mo:02d}-{dd:02d}"] = name
    return out


# ── 공통 ─────────────────────────────────────────────────────────────────

def is_fixed(d: str) -> bool:
    y, m, dd = (int(x) for x in d.split("-"))
    return (m, dd) in FIXED


def is_app_computed(d: str) -> bool:
    """앱이 이 날을 스스로 빨갛게 칠하는가(고정 8종 + 2026년부터 노동절·제헌절)."""
    y, m, dd = (int(x) for x in d.split("-"))
    since = APP_COMPUTED_SINCE.get((m, dd))
    return (m, dd) in FIXED or (since is not None and y >= since)


def app_computed_dates(year: int):
    out = [f"{year:04d}-{m:02d}-{d:02d}" for (m, d) in FIXED]
    out += [f"{year:04d}-{m:02d}-{d:02d}" for (m, d), since in APP_COMPUTED_SINCE.items() if year >= since]
    return sorted(out)


def _days_between(a: str, b: str) -> int:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def update_seen(seen: dict, found: dict, today: str, source: str = "google") -> dict:
    """출처가 오늘 보여준 날짜의 first/last 를 갱신. 반환은 새 dict(입력 불변).
    구글은 first/last, 정부는 gov_first/gov_last 에 적는다."""
    f, l = ("first", "last") if source == "google" else ("gov_first", "gov_last")
    out = {k: dict(v) for k, v in seen.items()}
    for d, name in found.items():
        cur = out.setdefault(d, {})
        cur["name"] = name or cur.get("name", "")
        cur.setdefault(f, today)
        cur[l] = today
    return out


def plan_changes(dates: set, removed: set, found: dict, seen: dict, today: str,
                 gov: dict | None = None, gov_years: set | None = None):
    """무엇을 더하고 무엇을 거둬들일지 정한다. 파일은 건드리지 않는다(seen 의 gov_absent_since 만 갱신).

    반환 dict:
      add       : dates 에 더할 날짜 — 정부가 아는 해는 정부에서, 나머지 해는 구글에서
      retract   : removed 로 옮길 날짜 — 정부가 아는 해: 정부 응답에 GOV_RETRACT_AFTER_DAYS 일 연속 없음 /
                  나머지 해: 구글이 알다가 RETRACT_AFTER_DAYS 일 이상 거둬들임
      restore   : removed 에서 되살릴 날짜 — 자동으로 거둬들였던 것이 출처에 다시 나타남
      anomaly   : 취소 후보가 MAX_AUTO_RETRACT 를 넘어 손대지 않았으면 그 목록(사람 확인)
      only_local: dates 에 있는데 어느 출처도 모르는 미래 날짜(정보용) — 정부가 아는 해에서는 곧 취소 대상
    `seen` 은 update_seen 을 거친 **오늘 기준** 지도여야 한다.
    """
    gov = gov or {}
    gov_years = gov_years or set()
    auto_retracted = {d for d, v in seen.items() if v.get("retracted")}

    def year(d: str) -> int:
        return int(d[:4])

    # 더하기 — 정부가 아는 해는 정부만, 나머지는 구글.
    add = set()
    for d in gov:
        if year(d) in gov_years and not is_fixed(d) and d not in dates and d not in removed:
            add.add(d)
    for d in found:
        if year(d) not in gov_years and not is_fixed(d) and d not in dates and d not in removed:
            add.add(d)

    # 되살리기 — 자동으로 거둬들였던 날짜가 그 해의 정답 출처에 다시 나타남(사람이 뺀 것은 그대로).
    restore = set()
    for d in removed:
        if d not in auto_retracted:
            continue
        src = gov if year(d) in gov_years else found
        if d in src:
            restore.add(d)

    candidates = set()

    # 취소 ① 정부가 아는 해: 앱이 빨갛게 칠할 날(dates ∪ 앱 계산)이 정부 응답에 없다.
    for y in sorted(gov_years):
        interest = {d for d in dates if year(d) == y} | set(app_computed_dates(y))
        for d in sorted(interest):
            if d < today or d in removed:
                continue
            info = seen.setdefault(d, {})
            if d in gov:
                info.pop("gov_absent_since", None)
                continue
            info.setdefault("gov_absent_since", today)
            if _days_between(info["gov_absent_since"], today) >= GOV_RETRACT_AFTER_DAYS:
                candidates.add(d)

    # 취소 ② 정부가 모르는 해: 구글이 알다가 거둬들였다(한 번도 몰랐던 날은 절대 안 지운다).
    max_year = max((year(d) for d in found), default=0)
    for d, info in seen.items():
        if year(d) in gov_years or not info.get("last"):
            continue
        if d in found or d in removed or d < today or year(d) > max_year:
            continue
        if _days_between(info["last"], today) < RETRACT_AFTER_DAYS:
            continue
        if d in dates or is_app_computed(d):
            candidates.add(d)

    candidates = sorted(candidates)
    if len(candidates) > MAX_AUTO_RETRACT:
        retract, anomaly = [], candidates
    else:
        retract, anomaly = candidates, []

    only_local = sorted(
        d for d in dates
        if d >= today and d not in found and d not in gov
    )
    return {
        "add": sorted(add), "retract": retract, "restore": sorted(restore),
        "anomaly": anomaly, "only_local": only_local,
    }


def apply_plan(doc: dict, plan: dict, seen: dict, today: str) -> bool:
    """doc(holidays.json)·seen 을 제자리에서 고친다. version 을 올렸으면 True."""
    dates = set(doc.get("dates", []))
    removed = set(doc.get("removed", []))
    changed = False
    if plan["add"]:
        dates |= set(plan["add"])
        changed = True
    if plan["retract"]:
        for d in plan["retract"]:
            dates.discard(d)
            removed.add(d)
            seen.setdefault(d, {})["retracted"] = today
        changed = True
    if plan["restore"]:
        for d in plan["restore"]:
            removed.discard(d)
            if not is_fixed(d):
                dates.add(d)
            seen.setdefault(d, {}).pop("retracted", None)
        changed = True
    if changed:
        doc["dates"] = sorted(dates)
        doc["removed"] = sorted(removed)
        doc["version"] = int(doc.get("version", 0)) + 1
        doc["updated"] = today
    return changed


def render_status(doc: dict, found: dict, seen: dict, plan: dict, today: str,
                  gov_years=(), gov_errors=(), gov_enabled=False) -> str:
    years = sorted({int(d[:4]) for d in found})
    gy = sorted(gov_years)
    lines = [
        "# 상태 (자동 생성 — 손으로 고치지 마세요)",
        "",
        f"- 마지막 확인: {today}",
        f"- holidays.json version: {doc.get('version')} / dates {len(doc.get('dates', []))}개 / removed {len(doc.get('removed', []))}개",
        (f"- 정부 특일정보(정답): {', '.join(str(y) for y in gy) if gy else '온전한 해 없음'}"
         if gov_enabled else "- 정부 특일정보: **키 없음** — 구글 캘린더만 사용 중(README '정부 API 켜기')"),
        f"- 구글 캘린더(보충): {len(found)}개 ({years[0] if years else '-'}~{years[-1] if years else '-'})",
        "",
    ]
    if gov_errors:
        lines += ["정부 응답 메모:", ""] + [f"- {e}" for e in gov_errors] + [""]
    lines += ["## 출처와 다른 점", ""]
    if plan["only_local"]:
        lines += ["**dates 에 있지만 어느 출처도 모르는 날짜** — 사람이 넣은 것. 정부가 아는 해라면 곧 자동 취소되고, 모르는 해라면 그대로 둔다.", ""]
        lines += [f"- {d}" for d in plan["only_local"]]
        lines.append("")
    pending = sorted(d for d, v in seen.items() if v.get("gov_absent_since") and not v.get("retracted"))
    if pending:
        lines += [f"**정부 응답에 없어 취소 대기 중**({GOV_RETRACT_AFTER_DAYS}일 연속 없으면 취소)", ""]
        lines += [f"- {d} (없어진 날 {seen[d]['gov_absent_since']})" for d in pending]
        lines.append("")
    auto = sorted(d for d, v in seen.items() if v.get("retracted"))
    if auto:
        lines += ["**출처가 거둬들여 자동으로 removed 에 넣은 날짜** — 출처에 다시 나타나면 되살린다.", ""]
        lines += [f"- {d} ({seen[d].get('name', '')}, {seen[d]['retracted']})" for d in auto]
        lines.append("")
    if plan["anomaly"]:
        lines += ["**⚠ 사람 확인 필요** — 한꺼번에 사라진 날짜(장애·형식 변경 가능성). 손대지 않았다.", ""]
        lines += [f"- {d} ({seen[d].get('name', '')})" for d in plan["anomaly"]]
        lines.append("")
    if not (plan["only_local"] or pending or auto or plan["anomaly"]):
        lines += ["없음 — 출처와 일치.", ""]
    return "\n".join(lines)


def render_report(plan: dict, seen: dict, gov_errors=()) -> str:
    """사람이 봐야 할 일이 있을 때만 내용을 돌려준다(없으면 빈 문자열)."""
    parts = []
    if plan["anomaly"]:
        parts.append("## 출처에서 한꺼번에 사라진 날짜 — 손대지 않았습니다\n")
        parts.append("출처 장애나 형식 변경일 수 있습니다. 진짜 폐지라면 holidays.json 의 removed 에 손으로 넣어 주세요.\n")
        parts += [f"- {d} ({seen.get(d, {}).get('name', '')})" for d in plan["anomaly"]]
        parts.append("")
    if plan["retract"]:
        parts.append("## 출처가 거둬들여 자동으로 removed 에 넣었습니다\n")
        parts += [f"- {d} ({seen.get(d, {}).get('name', '')})" for d in plan["retract"]]
        parts.append("\n앱은 다음 확인 때(최대 7일) 이 날을 평일로 되돌립니다. 잘못이면 removed 에서 빼고 version 을 +1 하세요.")
        parts.append("")
    if plan["restore"]:
        parts.append("## 출처에 다시 나타나 되살렸습니다\n")
        parts += [f"- {d} ({seen.get(d, {}).get('name', '')})" for d in plan["restore"]]
        parts.append("")
    key_errors = [e for e in gov_errors if "SERVICE_KEY" in e or "등록되지 않은" in e or "LIMITED" in e]
    if key_errors:
        parts.append("## 정부 특일정보 API 키 문제\n")
        parts += [f"- {e}" for e in key_errors]
        parts.append("\n공공데이터포털에서 키 상태를 확인하고 GitHub secret `DATA_GO_KR_KEY` 를 갱신해 주세요. 그동안은 구글 캘린더만 씁니다.")
        parts.append("")
    return "\n".join(parts)


def load_json(path: str, default):
    try:
        with io.open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def dump_json(path: str, obj) -> None:
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")


def main() -> int:
    dry = "--dry-run" in sys.argv
    today = os.environ.get("TODAY") or date.today().isoformat()
    this_year = int(today[:4])

    doc = load_json("holidays.json", None)
    if doc is None:
        print("holidays.json 이 없습니다")
        return 1
    seen_doc = load_json(SEEN_PATH, {"written": "", "dates": {}})

    try:
        found = parse_ics(fetch_ics())
    except Exception as e:  # 출처가 죽어도 파일은 건드리지 않는다
        print(f"구글 캘린더를 읽지 못했습니다 — {e}")
        return 1
    if not found:
        print("구글 캘린더에서 공휴일을 하나도 못 찾았습니다 — 형식이 바뀌었을 수 있어 중단합니다")
        return 1

    key = os.environ.get(GOV_KEY_ENV, "").strip()
    gov, gov_years, gov_errors = {}, set(), []
    if key:
        gov, gov_years, gov_errors = gov_holidays(key, [this_year, this_year + 1, this_year + 2])
        print(f"정부 특일정보: {len(gov)}개, 온전한 해 {sorted(gov_years) or '없음'}"
              + (f", 메모 {gov_errors}" if gov_errors else ""))
    else:
        print("정부 특일정보 키 없음(DATA_GO_KR_KEY) — 구글 캘린더만 사용")

    seen = update_seen(seen_doc.get("dates", {}), found, today, "google")
    seen = update_seen(seen, gov, today, "gov")
    plan = plan_changes(set(doc.get("dates", [])), set(doc.get("removed", [])),
                        found, seen, today, gov, gov_years)

    names = {**found, **gov}
    for d in plan["add"]:
        print(f"  + {d}  {names.get(d, '')}  ({'정부' if int(d[:4]) in gov_years else '구글'})")
    for d in plan["retract"]:
        why = "정부 응답에 연속 없음" if int(d[:4]) in gov_years else "구글이 거둬들임"
        print(f"  - {d}  {seen.get(d, {}).get('name', '')}  ({why} → removed)")
    for d in plan["restore"]:
        print(f"  ~ {d}  {names.get(d, '')}  (출처에 다시 나타남 → 되살림)")
    for d in plan["anomaly"]:
        print(f"  ! {d}  {seen.get(d, {}).get('name', '')}  (한꺼번에 사라져 손대지 않음)")

    changed = apply_plan(doc, plan, seen, today)
    if not changed:
        print(f"변경 없음 (현재 {len(doc['dates'])}일, 구글 {len(found)}일, 정부 {len(gov)}일)")
    else:
        print(f"version {doc['version']} 로 올리고 {len(doc['dates'])}일 저장")

    if dry:
        print("\n--dry-run — 파일을 쓰지 않았습니다")
        return 0

    if changed:
        dump_json("holidays.json", doc)

    # 스냅샷·STATUS 는 내용이 바뀌었거나 주기가 지났을 때만 쓴다(매일 커밋하지 않으려고).
    # 취소 대기(gov_absent_since)가 새로 생긴 날은 유예 계산을 위해 바로 쓴다.
    prev = seen_doc.get("dates", {})
    new_dates = {d for d in list(found) + list(gov) if d not in prev}
    new_pending = {d for d, v in seen.items() if v.get("gov_absent_since") and not prev.get(d, {}).get("gov_absent_since")}
    written = seen_doc.get("written") or ""
    stale = (not written) or _days_between(written, today) >= SNAPSHOT_REFRESH_DAYS
    if changed or new_dates or new_pending or plan["anomaly"] or stale:
        dump_json(SEEN_PATH, {"written": today, "dates": dict(sorted(seen.items()))})
        with io.open(STATUS_PATH, "w", encoding="utf-8", newline="\n") as f:
            f.write(render_status(doc, found, seen, plan, today, gov_years, gov_errors, bool(key)))

    report = render_report(plan, seen, gov_errors)
    if report:
        with io.open(REPORT_PATH, "w", encoding="utf-8", newline="\n") as f:
            f.write(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
