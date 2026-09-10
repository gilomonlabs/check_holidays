#!/usr/bin/env python3
"""공휴일 자동 수집 — 구글 캘린더 '대한민국의 휴일' ICS에서 받아 holidays.json 에 병합.

    python update_holidays.py [--dry-run]

**추가는 자동, 삭제는 "출처가 알던 날을 거둬들였을 때만" 자동.**

출처가 미래 연도의 대체공휴일·선거일을 빠뜨리는 것이 실측으로 확인됐다
(예: 2030-05-06 대체공휴일(월), 2028-04-12 총선이 없다). 그래서 "출처에 없다"는
이유만으로 기존 날짜를 지우면 멀쩡한 휴일이 사라진다. 대신 이렇게 가른다:

  · 출처가 **한 번도 몰랐던** 날짜(사람이 넣은 미래 대체공휴일·선거일) → 절대 안 지운다.
  · 출처가 **알고 있다가 거둬들인** 날짜(법 개정으로 공휴일에서 빠짐, 대체공휴일 날짜 이동)
    → 7일 이상 계속 안 보이면 `removed` 로 옮긴다(앱 내장까지 취소되도록).
  · 한 번에 4개 이상 거둬들여지면 출처 장애·형식 변경일 수 있으니 손대지 않고
    이슈로 사람에게 넘긴다.

그러려면 "출처가 언제 무엇을 알았는지"를 기억해야 해서 source_seen.json 에 남긴다.
비교 결과는 STATUS.md 에 표로 적어 사람이 아무 때나 볼 수 있게 한다.

API 키가 필요 없다(공공데이터포털 특일정보는 키가 필요해 안 쓴다).
"""
import io
import json
import os
import re
import sys
import urllib.request
from datetime import date

ICS_URL = (
    "https://calendar.google.com/calendar/ical/"
    "ko.south_korea%23holiday%40group.v.calendar.google.com/public/basic.ics"
)

# 앱이 코드로 매년 계산하는 고정 양력 공휴일 — dates 에 넣으면 중복이다.
# (출처가 이 날을 거둬들이면 removed 로는 취소한다 — 앱 내장을 끄는 유일한 길이므로.)
FIXED = {(1, 1), (3, 1), (5, 5), (6, 6), (8, 15), (10, 3), (10, 9), (12, 25)}

# 관공서 공휴일이 아닌데 출처가 '공휴일'로 표시하는 것을 이름으로 거른다. 지금은 없다.
#  · 노동절은 2026-09-10까지 여기 있었다 — 근로기준법상 유급휴일일 뿐 관공서 공휴일이
#    아니었기 때문. 그런데 2026년 '공휴일에 관한 법률' 개정(3월 31일 국회 통과)으로
#    2026년 5월 1일부터 관공서 공휴일이 됐고 대체공휴일도 적용된다(2027-05-03).
#    제헌절도 같은 해 1월 개정으로 18년 만에 복귀했다(출처가 2026년부터 '공휴일'로 표시).
#  · 법이 또 바뀌어 빼야 하면 여기 이름을 넣고, 이미 들어간 날짜는 holidays.json 의
#    removed 로 취소한다.
EXCLUDE_KEYWORDS: set[str] = set()

# 이 범위 밖은 무시(출처에 과거 몇 년치가 같이 들어 있다).
YEAR_MIN, YEAR_MAX = 2025, 2035

SEEN_PATH = "source_seen.json"
STATUS_PATH = "STATUS.md"
REPORT_PATH = "report.md"          # 있으면 워크플로가 이슈를 만든다

RETRACT_AFTER_DAYS = 7             # 이 기간 이상 계속 안 보여야 거둬들인 것으로 본다
MAX_AUTO_RETRACT = 3               # 한 번에 이보다 많이 사라지면 사람에게 넘긴다
SNAPSHOT_REFRESH_DAYS = 7          # 변화가 없어도 이 주기로 스냅샷·STATUS 를 갱신


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


# 앱이 2026년부터 코드로 계산하는 날(2026년 법 개정). dates 에도 두지만(구 빌드용),
# 출처가 거둬들이면 removed 로 취소해야 새 빌드의 내장 계산까지 꺼진다.
APP_COMPUTED_SINCE = {(5, 1): 2026, (7, 17): 2026}


def is_fixed(d: str) -> bool:
    y, m, dd = (int(x) for x in d.split("-"))
    return (m, dd) in FIXED


def is_app_computed(d: str) -> bool:
    """앱이 이 날을 스스로 빨갛게 칠하는가(고정 8종 + 2026년부터 노동절·제헌절)."""
    y, m, dd = (int(x) for x in d.split("-"))
    since = APP_COMPUTED_SINCE.get((m, dd))
    return (m, dd) in FIXED or (since is not None and y >= since)


def update_seen(seen: dict, found: dict, today: str) -> dict:
    """출처가 오늘 보여준 날짜의 first/last 를 갱신. 반환은 새 dict(입력 불변)."""
    out = {k: dict(v) for k, v in seen.items()}
    for d, name in found.items():
        cur = out.get(d)
        if cur is None:
            out[d] = {"name": name, "first": today, "last": today}
        else:
            cur["name"] = name
            cur["last"] = today
    return out


def _days_between(a: str, b: str) -> int:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def plan_changes(dates: set, removed: set, found: dict, seen: dict, today: str):
    """무엇을 더하고 무엇을 거둬들일지 정한다. 파일은 건드리지 않는다.

    반환 dict:
      add      : dates 에 더할 날짜(정렬)
      retract  : removed 로 옮길 날짜(정렬) — 출처가 알다가 RETRACT_AFTER_DAYS 이상 거둬들인 것
      restore  : removed 에서 되살릴 날짜(정렬) — 자동으로 거둬들였던 것이 출처에 다시 나타남
      anomaly  : 거둬들일 후보가 MAX_AUTO_RETRACT 를 넘어 손대지 않았으면 그 목록(사람 확인)
      only_local: dates 에 있는데 출처가 한 번도 몰랐던 날짜(정보용, 안 지움)
    `seen` 은 update_seen 을 거친 **오늘 기준** 지도여야 한다.
    """
    auto_retracted = {d for d, v in seen.items() if v.get("retracted")}

    add = sorted(
        d for d in found
        if not is_fixed(d) and d not in dates and d not in removed
    )

    # 자동으로 거둬들였던 날짜가 출처에 다시 나타났다 → 되살린다(사람이 뺀 것은 그대로).
    restore = sorted(d for d in removed if d in found and d in auto_retracted)

    max_year = max((int(d[:4]) for d in found), default=0)
    candidates = []
    for d, info in seen.items():
        if d in found or d in removed or d < today:
            continue
        if int(d[:4]) > max_year:          # 출처 범위 밖(출처가 그 해를 아직 모름)
            continue
        if _days_between(info["last"], today) < RETRACT_AFTER_DAYS:
            continue
        if d in dates or is_app_computed(d):  # 앱 달력에 빨갛게 나올 날만 의미가 있다
            candidates.append(d)
    candidates.sort()

    if len(candidates) > MAX_AUTO_RETRACT:
        retract, anomaly = [], candidates
    else:
        retract, anomaly = candidates, []

    only_local = sorted(d for d in dates if d not in seen and d >= today)
    return {
        "add": add, "retract": retract, "restore": restore,
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
            seen[d].pop("retracted", None)
        changed = True
    if changed:
        doc["dates"] = sorted(dates)
        doc["removed"] = sorted(removed)
        doc["version"] = int(doc.get("version", 0)) + 1
        doc["updated"] = today
    return changed


def render_status(doc: dict, found: dict, seen: dict, plan: dict, today: str) -> str:
    years = sorted({int(d[:4]) for d in found})
    lines = [
        "# 상태 (자동 생성 — 손으로 고치지 마세요)",
        "",
        f"- 마지막 확인: {today}",
        f"- holidays.json version: {doc.get('version')} / dates {len(doc.get('dates', []))}개 / removed {len(doc.get('removed', []))}개",
        f"- 출처가 아는 공휴일: {len(found)}개 ({years[0] if years else '-'}~{years[-1] if years else '-'})",
        "",
        "## 출처와 다른 점",
        "",
    ]
    if plan["only_local"]:
        lines += ["**dates 에 있지만 출처는 모르는 날짜** — 사람이 넣은 것. 출처가 미래 대체공휴일·선거일을 빠뜨리므로 지우지 않는다.", ""]
        lines += [f"- {d}" for d in plan["only_local"]]
        lines.append("")
    auto = sorted(d for d, v in seen.items() if v.get("retracted"))
    if auto:
        lines += ["**출처가 거둬들여 자동으로 removed 에 넣은 날짜** — 출처에 다시 나타나면 되살린다.", ""]
        lines += [f"- {d} ({seen[d].get('name', '')}, {seen[d]['retracted']})" for d in auto]
        lines.append("")
    if plan["anomaly"]:
        lines += ["**⚠ 사람 확인 필요** — 출처에서 한꺼번에 사라진 날짜(장애·형식 변경 가능성). 손대지 않았다.", ""]
        lines += [f"- {d} ({seen[d].get('name', '')}, 마지막 확인 {seen[d]['last']})" for d in plan["anomaly"]]
        lines.append("")
    if not (plan["only_local"] or auto or plan["anomaly"]):
        lines += ["없음 — 출처와 일치.", ""]
    return "\n".join(lines)


def render_report(plan: dict, seen: dict) -> str:
    """사람이 봐야 할 일이 있을 때만 내용을 돌려준다(없으면 빈 문자열)."""
    parts = []
    if plan["anomaly"]:
        parts.append("## 출처에서 한꺼번에 사라진 날짜 — 손대지 않았습니다\n")
        parts.append("구글 캘린더 장애나 형식 변경일 수 있습니다. 진짜 폐지라면 holidays.json 의 removed 에 손으로 넣어 주세요.\n")
        parts += [f"- {d} ({seen[d].get('name', '')}, 마지막 확인 {seen[d]['last']})" for d in plan["anomaly"]]
        parts.append("")
    if plan["retract"]:
        parts.append("## 출처가 거둬들여 자동으로 removed 에 넣었습니다\n")
        parts += [f"- {d} ({seen[d].get('name', '')})" for d in plan["retract"]]
        parts.append("\n앱은 다음 확인 때(최대 7일) 이 날을 평일로 되돌립니다. 잘못이면 removed 에서 빼고 version 을 +1 하세요.")
        parts.append("")
    if plan["restore"]:
        parts.append("## 출처에 다시 나타나 되살렸습니다\n")
        parts += [f"- {d} ({seen[d].get('name', '')})" for d in plan["restore"]]
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

    doc = load_json("holidays.json", None)
    if doc is None:
        print("holidays.json 이 없습니다")
        return 1
    seen_doc = load_json(SEEN_PATH, {"written": "", "dates": {}})

    try:
        found = parse_ics(fetch_ics())
    except Exception as e:  # 출처가 죽어도 파일은 건드리지 않는다
        print(f"출처를 읽지 못했습니다 — {e}")
        return 1
    if not found:
        print("출처에서 공휴일을 하나도 못 찾았습니다 — 형식이 바뀌었을 수 있어 중단합니다")
        return 1

    seen = update_seen(seen_doc.get("dates", {}), found, today)
    plan = plan_changes(set(doc.get("dates", [])), set(doc.get("removed", [])), found, seen, today)

    for d in plan["add"]:
        print(f"  + {d}  {found[d]}")
    for d in plan["retract"]:
        print(f"  - {d}  {seen[d].get('name', '')}  (출처에서 {_days_between(seen[d]['last'], today)}일째 사라짐 → removed)")
    for d in plan["restore"]:
        print(f"  ~ {d}  {found[d]}  (출처에 다시 나타남 → 되살림)")
    for d in plan["anomaly"]:
        print(f"  ! {d}  {seen[d].get('name', '')}  (한꺼번에 사라져 손대지 않음)")

    changed = apply_plan(doc, plan, seen, today)
    if not changed:
        print(f"변경 없음 (현재 {len(doc['dates'])}일, 출처 {len(found)}일)")
    else:
        print(f"version {doc['version']} 로 올리고 {len(doc['dates'])}일 저장")

    if dry:
        print("\n--dry-run — 파일을 쓰지 않았습니다")
        return 0

    if changed:
        dump_json("holidays.json", doc)

    # 스냅샷·STATUS 는 내용이 바뀌었거나 주기가 지났을 때만 쓴다(매일 커밋하지 않으려고).
    new_dates = {d for d in found if d not in seen_doc.get("dates", {})}
    written = seen_doc.get("written") or ""
    stale = (not written) or _days_between(written, today) >= SNAPSHOT_REFRESH_DAYS
    if changed or new_dates or plan["anomaly"] or stale:
        dump_json(SEEN_PATH, {"written": today, "dates": dict(sorted(seen.items()))})
        with io.open(STATUS_PATH, "w", encoding="utf-8", newline="\n") as f:
            f.write(render_status(doc, found, seen, plan, today))

    report = render_report(plan, seen)
    if report:
        with io.open(REPORT_PATH, "w", encoding="utf-8", newline="\n") as f:
            f.write(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
