#!/usr/bin/env python3
"""holidays.json 형식 검사.

앱은 형식이 깨진 파일을 **조용히 무시**한다(오류 화면이 없다). 그래서 잘못 올리면
아무도 모르는 채로 업데이트가 멈춘다. 그 침묵을 여기서 깬다.

    python validate.py [holidays.json] [--prev-file 이전.json]

--prev-file 을 주면 **앱이 실제로 읽는 내용**(dates·removed)이 바뀌었는지 보고,
바뀌었는데 version 을 안 올렸으면 막는다. note 나 updated 만 고친 변경까지
version 을 요구하면 사용자에게 무의미한 업데이트가 나간다.
"""
import json
import re
import sys
from datetime import date

ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# 앱이 코드로 계산하는 고정 양력 공휴일 — dates에 넣으면 중복이다.
FIXED = {(1, 1), (3, 1), (5, 5), (6, 6), (8, 15), (10, 3), (10, 9), (12, 25)}


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    path = args[0] if args else "holidays.json"
    prev_doc = None
    if "--prev-file" in sys.argv:
        try:
            with open(sys.argv[sys.argv.index("--prev-file") + 1], encoding="utf-8") as f:
                prev_doc = json.load(f)
        except Exception:
            prev_doc = None  # 이전 파일이 없거나 깨졌으면 비교를 건너뛴다

    errors, warnings = [], []

    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except FileNotFoundError:
        print(f"FAIL: {path} 가 없습니다")
        return 1
    except json.JSONDecodeError as e:
        print(f"FAIL: JSON 파싱 실패 — {e}")
        return 1

    if not isinstance(doc, dict):
        print("FAIL: 최상위가 객체가 아닙니다")
        return 1

    version = doc.get("version")
    if not isinstance(version, int) or isinstance(version, bool):
        errors.append(f"version 이 정수가 아닙니다: {version!r}")

    dates = doc.get("dates")
    if not isinstance(dates, list):
        errors.append(f"dates 가 배열이 아닙니다: {type(dates).__name__}")
        dates = []

    seen = set()
    for d in dates:
        if not isinstance(d, str):
            errors.append(f"날짜가 문자열이 아닙니다: {d!r}")
            continue
        if not ISO.match(d):
            errors.append(f"YYYY-MM-DD 형식이 아닙니다 (앱이 조용히 버립니다): {d!r}")
            continue
        y, m, dd = (int(x) for x in d.split("-"))
        try:
            date(y, m, dd)
        except ValueError:
            errors.append(f"달력에 없는 날짜입니다: {d}")
            continue
        if d in seen:
            warnings.append(f"중복: {d}")
        seen.add(d)
        if (m, dd) in FIXED:
            warnings.append(f"고정 양력 공휴일이라 앱이 이미 계산합니다 (빼도 됩니다): {d}")

    if sorted(seen) != [d for d in dates if isinstance(d, str) and d in seen][: len(seen)]:
        warnings.append("날짜가 정렬돼 있지 않습니다 (동작엔 무관, 읽기 편하도록 권장)")

    removed = doc.get("removed", [])
    if not isinstance(removed, list):
        errors.append(f"removed 가 배열이 아닙니다: {type(removed).__name__}")
        removed = []
    rset = set()
    for d in removed:
        if not isinstance(d, str) or not ISO.match(d):
            errors.append(f"removed 의 날짜 형식이 잘못됐습니다: {d!r}")
            continue
        y, m, dd = (int(x) for x in d.split("-"))
        try:
            date(y, m, dd)
        except ValueError:
            errors.append(f"removed 에 달력에 없는 날짜: {d}")
            continue
        rset.add(d)
    both = rset & seen
    if both:
        errors.append(
            f"dates 와 removed 에 같이 있습니다(뜻이 모순): {sorted(both)}"
        )

    if prev_doc is not None and isinstance(version, int):
        prev_v = prev_doc.get("version")
        # 앱이 실제로 읽는 것만 비교한다(note·updated 변경은 version 을 요구하지 않는다).
        def sig(d):
            return (
                sorted(x for x in d.get("dates", []) if isinstance(x, str)),
                sorted(x for x in d.get("removed", []) if isinstance(x, str)),
            )
        if sig(prev_doc) != sig(doc):
            if version == prev_v:
                errors.append(
                    f"dates/removed 를 바꿨는데 version 이 그대로입니다({version}). +1 하세요 — "
                    "안 올리면 사용자 앱은 영원히 못 받습니다"
                )
            elif isinstance(prev_v, int) and version < prev_v:
                errors.append(
                    f"version 이 내려갔습니다({prev_v} → {version}). 앱 비교가 '>' 라 무시됩니다"
                )
        elif version != prev_v:
            warnings.append(
                f"내용은 그대로인데 version 만 바뀌었습니다({prev_v} → {version}) — "
                "사용자에게 빈 업데이트가 나갑니다"
            )

    for w in warnings:
        print(f"  주의: {w}")
    for e in errors:
        print(f"  오류: {e}")

    if errors:
        print(f"\nFAIL — 오류 {len(errors)}건")
        return 1
    print(f"OK — version {version} / 날짜 {len(seen)}개"
          + (f" / 취소 {len(rset)}개" if rset else "")
          + (f" ({min(seen)} ~ {max(seen)})" if seen else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
