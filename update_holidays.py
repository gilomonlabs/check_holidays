#!/usr/bin/env python3
"""공휴일 자동 수집 — 구글 캘린더 '대한민국의 휴일' ICS에서 받아 holidays.json 에 병합.

    python update_holidays.py [--dry-run]

**추가만 한다. 삭제하지 않는다.**
출처가 미래 연도의 대체공휴일·선거일을 빠뜨리는 것이 실측으로 확인됐다
(예: 2030-05-06 대체공휴일(월), 2028-04-12 총선이 없다). 그래서 출처에 없다는
이유로 기존 날짜를 지우면 멀쩡한 휴일이 사라진다. 지우는 건 사람이 판단한다.

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

# 앱이 코드로 매년 계산하는 고정 양력 공휴일 — 넣으면 중복이다.
FIXED = {(1, 1), (3, 1), (5, 5), (6, 6), (8, 15), (10, 3), (10, 9), (12, 25)}

# 관공서 공휴일이 아닌 것. 출처가 '공휴일'로 표시해도 거른다.
#  · 노동절(근로자의 날)은 근로기준법상 유급휴일이지 관공서 공휴일이 아니다.
#    게다가 출처에는 '쉬는 날 노동절'(2027-05-03) 같은, 대체공휴일 대상도 아닌
#    항목이 섞여 있다.
#  → 달력에 빨갛게 칠하고 싶으면 이 집합을 비우면 된다.
EXCLUDE_KEYWORDS = {"노동절"}

# 이 범위 밖은 무시(출처에 과거 몇 년치가 같이 들어 있다).
YEAR_MIN, YEAR_MAX = 2025, 2035


def fetch_ics(url: str = ICS_URL) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "check_holidays/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def parse_ics(raw: str):
    """(YYYY-MM-DD, 이름) 목록. DESCRIPTION 이 '공휴일' 인 것만."""
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
        if (mo, dd) in FIXED:
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


def main() -> int:
    dry = "--dry-run" in sys.argv
    path = "holidays.json"

    with io.open(path, encoding="utf-8") as f:
        doc = json.load(f)
    current = set(doc.get("dates", []))

    try:
        found = parse_ics(fetch_ics())
    except Exception as e:  # 출처가 죽어도 파일은 건드리지 않는다
        print(f"출처를 읽지 못했습니다 — {e}")
        return 1

    if not found:
        print("출처에서 공휴일을 하나도 못 찾았습니다 — 형식이 바뀌었을 수 있어 중단합니다")
        return 1

    new = sorted(set(found) - current)
    if not new:
        print(f"변경 없음 (현재 {len(current)}일, 출처 {len(found)}일)")
        return 0

    print(f"새 날짜 {len(new)}개:")
    for d in new:
        print(f"  + {d}  {found[d]}")

    if dry:
        print("\n--dry-run — 파일을 쓰지 않았습니다")
        return 0

    doc["dates"] = sorted(current | set(new))
    doc["version"] = int(doc.get("version", 0)) + 1
    doc["updated"] = os.environ.get("TODAY") or date.today().isoformat()
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"\nversion {doc['version']} 로 올리고 {len(doc['dates'])}일 저장")
    return 0


if __name__ == "__main__":
    sys.exit(main())
