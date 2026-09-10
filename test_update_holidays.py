#!/usr/bin/env python3
"""update_holidays.py 의 판단 규칙 테스트. 네트워크 없음.

    python -m unittest -v
"""
import unittest

import update_holidays as u

TODAY = "2026-09-10"


def seen_entry(name, first, last, retracted=None):
    e = {"name": name, "first": first, "last": last}
    if retracted:
        e["retracted"] = retracted
    return e


ICS = """BEGIN:VCALENDAR\r
BEGIN:VEVENT\r
DTSTART;VALUE=DATE:20270503\r
SUMMARY:쉬는 날 노동절\r
DESCRIPTION:공휴일\r
END:VEVENT\r
BEGIN:VEVENT\r
DTSTART;VALUE=DATE:20270405\r
SUMMARY:식목일\r
DESCRIPTION:기념일\\n기념일을 숨기려면 Google Calendar\r
 설정을 이용하세요\r
END:VEVENT\r
BEGIN:VEVENT\r
DTSTART;VALUE=DATE:20270101\r
SUMMARY:새해첫날\r
DESCRIPTION:공휴일\r
END:VEVENT\r
BEGIN:VEVENT\r
DTSTART;VALUE=DATE:20200101\r
SUMMARY:새해첫날\r
DESCRIPTION:공휴일\r
END:VEVENT\r
END:VCALENDAR\r
"""


class ParseIcs(unittest.TestCase):
    def test_public_holidays_only_including_fixed(self):
        found = u.parse_ics(ICS)
        self.assertEqual(found, {"2027-05-03": "쉬는 날 노동절", "2027-01-01": "새해첫날"})

    def test_year_range(self):
        self.assertNotIn("2020-01-01", u.parse_ics(ICS))


class UpdateSeen(unittest.TestCase):
    def test_first_and_last(self):
        seen = {"2027-05-03": seen_entry("x", "2026-01-01", "2026-09-01")}
        out = u.update_seen(seen, {"2027-05-03": "쉬는 날 노동절", "2027-05-01": "노동절"}, TODAY)
        self.assertEqual(out["2027-05-03"], seen_entry("쉬는 날 노동절", "2026-01-01", TODAY))
        self.assertEqual(out["2027-05-01"], seen_entry("노동절", TODAY, TODAY))
        self.assertEqual(seen["2027-05-03"]["last"], "2026-09-01", "입력을 바꾸면 안 된다")


class PlanChanges(unittest.TestCase):
    def plan(self, dates, removed, found, seen):
        return u.plan_changes(set(dates), set(removed), found, seen, TODAY)

    def test_add_skips_fixed_and_known_and_retracted(self):
        found = {"2027-05-03": "a", "2027-01-01": "새해", "2027-05-13": "b", "2027-07-19": "c"}
        seen = u.update_seen({}, found, TODAY)
        p = self.plan(["2027-05-13"], ["2027-07-19"], found, seen)
        self.assertEqual(p["add"], ["2027-05-03"])

    def test_retract_after_seven_days(self):
        # 출처가 알던 2027-05-03 이 8일째 안 보인다 → removed 로
        seen = {"2027-05-03": seen_entry("쉬는 날 노동절", "2026-01-01", "2026-09-02")}
        found = {"2027-05-13": "b"}
        p = self.plan(["2027-05-03", "2027-05-13"], [], found, u.update_seen(seen, found, TODAY))
        self.assertEqual(p["retract"], ["2027-05-03"])
        self.assertEqual(p["anomaly"], [])

    def test_not_retracted_before_seven_days(self):
        seen = {"2027-05-03": seen_entry("x", "2026-01-01", "2026-09-05")}  # 5일
        found = {"2027-05-13": "b"}
        p = self.plan(["2027-05-03"], [], found, u.update_seen(seen, found, TODAY))
        self.assertEqual(p["retract"], [])

    def test_hand_entered_never_seen_is_kept(self):
        # 출처가 한 번도 모른 2030-05-06(어린이날 대체) — 절대 안 지운다, 정보로만
        found = {"2027-05-13": "b"}
        p = self.plan(["2030-05-06"], [], found, u.update_seen({}, found, TODAY))
        self.assertEqual(p["retract"], [])
        self.assertEqual(p["only_local"], ["2030-05-06"])

    def test_past_dates_untouched(self):
        seen = {"2026-05-01": seen_entry("노동절", "2026-01-01", "2026-08-01")}
        found = {"2027-05-13": "b"}
        p = self.plan(["2026-05-01"], [], found, u.update_seen(seen, found, TODAY))
        self.assertEqual(p["retract"], [])

    def test_beyond_source_years_untouched(self):
        # 출처가 2027년까지만 아는데 2031 날짜가 예전엔 있었다 해도 범위 밖이면 손대지 않음
        seen = {"2031-01-23": seen_entry("설날", "2026-01-01", "2026-08-01")}
        found = {"2027-05-13": "b"}
        p = self.plan(["2031-01-23"], [], found, u.update_seen(seen, found, TODAY))
        self.assertEqual(p["retract"], [])

    def test_fixed_holiday_retracted_goes_to_removed(self):
        # 제헌절이 다시 폐지되면 출처가 7/17 을 거둬들인다 → dates 엔 없지만 removed 로
        seen = {"2027-07-17": seen_entry("제헌절", "2026-01-01", "2026-09-01")}
        found = {"2027-05-13": "b"}
        p = self.plan([], [], found, u.update_seen(seen, found, TODAY))
        self.assertEqual(p["retract"], ["2027-07-17"])  # 앱이 2026~ 계산하므로 dates 에 없어도 취소
        seen2 = {"2027-01-01": seen_entry("새해첫날", "2026-01-01", "2026-09-01")}
        p2 = self.plan([], [], found, u.update_seen(seen2, found, TODAY))
        self.assertEqual(p2["retract"], ["2027-01-01"])

    def test_too_many_is_anomaly(self):
        seen = {f"2027-0{i}-10": seen_entry("x", "2026-01-01", "2026-09-01") for i in range(1, 6)}
        dates = list(seen)
        found = {"2027-05-13": "b"}
        p = self.plan(dates, [], found, u.update_seen(seen, found, TODAY))
        self.assertEqual(p["retract"], [])
        self.assertEqual(len(p["anomaly"]), 5)

    def test_restore_only_auto_retracted(self):
        found = {"2027-05-03": "쉬는 날 노동절", "2027-06-03": "선거"}
        seen = {
            "2027-05-03": seen_entry("쉬는 날 노동절", "2026-01-01", "2026-08-01", retracted="2026-08-10"),
            "2027-06-03": seen_entry("선거", "2026-01-01", "2026-08-01"),  # 사람이 뺀 것
        }
        p = self.plan([], ["2027-05-03", "2027-06-03"], found, u.update_seen(seen, found, TODAY))
        self.assertEqual(p["restore"], ["2027-05-03"])
        self.assertEqual(p["add"], [])  # removed 에 있는 건 add 로 안 감


class ApplyPlan(unittest.TestCase):
    def test_retract_and_restore_bump_version(self):
        doc = {"version": 3, "dates": ["2027-05-03", "2027-05-13"], "removed": ["2027-06-03"]}
        seen = {
            "2027-05-03": seen_entry("a", "2026-01-01", "2026-09-01"),
            "2027-06-03": seen_entry("b", "2026-01-01", TODAY, retracted="2026-08-10"),
        }
        plan = {"add": ["2027-07-19"], "retract": ["2027-05-03"], "restore": ["2027-06-03"],
                "anomaly": [], "only_local": []}
        self.assertTrue(u.apply_plan(doc, plan, seen, TODAY))
        self.assertEqual(doc["version"], 4)
        self.assertEqual(doc["dates"], ["2027-05-13", "2027-06-03", "2027-07-19"])
        self.assertEqual(doc["removed"], ["2027-05-03"])
        self.assertEqual(seen["2027-05-03"]["retracted"], TODAY)
        self.assertNotIn("retracted", seen["2027-06-03"])

    def test_no_change_keeps_version(self):
        doc = {"version": 3, "dates": ["2027-05-13"], "removed": []}
        plan = {"add": [], "retract": [], "restore": [], "anomaly": [], "only_local": []}
        self.assertFalse(u.apply_plan(doc, plan, {}, TODAY))
        self.assertEqual(doc["version"], 3)


class Report(unittest.TestCase):
    def test_empty_when_nothing_for_humans(self):
        plan = {"add": ["2027-07-19"], "retract": [], "restore": [], "anomaly": [], "only_local": ["2030-05-06"]}
        self.assertEqual(u.render_report(plan, {}), "")

    def test_mentions_retract_and_anomaly(self):
        seen = {"2027-05-03": seen_entry("a", "2026-01-01", "2026-09-01"),
                "2027-05-04": seen_entry("b", "2026-01-01", "2026-09-01")}
        plan = {"add": [], "retract": ["2027-05-03"], "restore": [], "anomaly": ["2027-05-04"], "only_local": []}
        r = u.render_report(plan, seen)
        self.assertIn("2027-05-03", r)
        self.assertIn("손대지 않았습니다", r)


if __name__ == "__main__":
    unittest.main()
