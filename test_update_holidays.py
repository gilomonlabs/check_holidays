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


GOV_JSON = """{"response":{"header":{"resultCode":"00","resultMsg":"NORMAL SERVICE."},
"body":{"items":{"item":[
 {"dateKind":"01","dateName":"1월1일","isHoliday":"Y","locdate":20270101,"seq":1},
 {"dateKind":"01","dateName":"설날","isHoliday":"Y","locdate":20270206,"seq":1},
 {"dateKind":"01","dateName":"근로자의날","isHoliday":"N","locdate":20270501,"seq":1},
 {"dateKind":"01","dateName":"임시공휴일","isHoliday":"Y","locdate":20271015,"seq":1}
]},"numOfRows":100,"pageNo":1,"totalCount":4}}}"""


class ParseGov(unittest.TestCase):
    def test_holiday_items_only(self):
        self.assertEqual(u.parse_gov(GOV_JSON),
                         {"2027-01-01": "1월1일", "2027-02-06": "설날", "2027-10-15": "임시공휴일"})

    def test_single_item_is_object(self):
        raw = '{"response":{"header":{"resultCode":"00"},"body":{"items":{"item":{"dateName":"x","isHoliday":"Y","locdate":20270101}}}}}'
        self.assertEqual(u.parse_gov(raw), {"2027-01-01": "x"})

    def test_empty_items(self):
        raw = '{"response":{"header":{"resultCode":"00"},"body":{"items":"","totalCount":0}}}'
        self.assertEqual(u.parse_gov(raw), {})

    def test_key_error_raises(self):
        raw = '{"OpenAPI_ServiceResponse":{"cmmMsgHeader":{"errMsg":"SERVICE_KEY_IS_NOT_REGISTERED_ERROR","returnAuthMsg":"등록되지 않은 서비스키","returnReasonCode":"30"}}}'
        with self.assertRaises(ValueError):
            u.parse_gov(raw)

    def test_xml_error_raises(self):
        with self.assertRaises(ValueError):
            u.parse_gov("<OpenAPI_ServiceResponse><cmmMsgHeader><returnAuthMsg>LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR</returnAuthMsg></cmmMsgHeader></OpenAPI_ServiceResponse>")


class GovHolidays(unittest.TestCase):
    def test_partial_year_not_covered(self):
        def fetch(key, year):
            if year == 2026:
                items = ",".join('{"dateName":"h%d","isHoliday":"Y","locdate":2026%02d01}' % (i, i) for i in range(1, 13))
                return '{"response":{"header":{"resultCode":"00"},"body":{"items":{"item":[%s]}}}}' % items
            if year == 2027:
                return '{"response":{"header":{"resultCode":"00"},"body":{"items":{"item":[{"dateName":"x","isHoliday":"Y","locdate":20270101}]}}}}'
            raise OSError("timeout")
        found, covered, errors = u.gov_holidays("k", [2026, 2027, 2028], fetch=fetch)
        self.assertEqual(covered, {2026})
        self.assertEqual(len(found), 12)
        self.assertEqual(len(errors), 2)


class PlanWithGov(unittest.TestCase):
    """정부가 아는 해(2027)는 정부가 정답, 모르는 해(2030)는 구글 규칙."""

    def setUp(self):
        self.gov = {"2027-02-06": "설날", "2027-02-07": "설날", "2027-02-08": "설날",
                    "2027-01-01": "1월1일", "2027-10-15": "임시공휴일"}
        self.gov_years = {2027}
        self.google = {"2027-02-07": "설날", "2027-02-08": "설날 연휴", "2027-09-09": "구글만 아는 날",
                       "2030-05-09": "부처님오신날"}

    def plan(self, dates, removed, seen):
        return u.plan_changes(set(dates), set(removed), self.google, seen, TODAY, self.gov, self.gov_years)

    def test_gov_adds_immediately_and_google_ignored_in_gov_year(self):
        seen = u.update_seen(u.update_seen({}, self.google, TODAY), self.gov, TODAY, "gov")
        p = self.plan(["2027-02-07", "2027-02-08"], [], seen)
        self.assertIn("2027-10-15", p["add"])       # 정부가 아는 임시공휴일 → 즉시
        self.assertIn("2027-02-06", p["add"])
        self.assertNotIn("2027-09-09", p["add"])    # 정부가 아는 해엔 구글 추가 무시
        self.assertIn("2030-05-09", p["add"])       # 정부가 모르는 해는 구글로
        self.assertNotIn("2027-01-01", p["add"])    # 고정 양력은 앱이 계산

    def test_gov_absence_retracts_after_three_days(self):
        # 사람이 넣은 2027-11-11 이 정부 응답에 없다 — 첫날은 대기, 3일째 취소
        seen = u.update_seen(u.update_seen({}, self.google, TODAY), self.gov, TODAY, "gov")
        p1 = self.plan(["2027-11-11"], [], seen)
        self.assertEqual(p1["retract"], [])
        self.assertEqual(seen["2027-11-11"]["gov_absent_since"], TODAY)
        seen["2027-11-11"]["gov_absent_since"] = "2026-09-07"
        p2 = self.plan(["2027-11-11"], [], seen)
        self.assertEqual(p2["retract"], ["2027-11-11"])

    def test_gov_presence_clears_absence(self):
        seen = u.update_seen(u.update_seen({}, self.google, TODAY), self.gov, TODAY, "gov")
        seen["2027-02-06"] = {"name": "설날", "gov_absent_since": "2026-09-01"}
        p = self.plan(["2027-02-06"], [], seen)
        self.assertEqual(p["retract"], [])
        self.assertNotIn("gov_absent_since", seen["2027-02-06"])

    def test_fixed_missing_from_gov_is_retracted_via_removed(self):
        # 정부 응답에 2027-10-09(한글날)가 없으면 앱 계산을 removed 로 끈다(유예 뒤)
        seen = u.update_seen({}, self.gov, TODAY, "gov")
        seen["2027-10-09"] = {"gov_absent_since": "2026-09-01"}
        p = self.plan([], [], seen)
        self.assertIn("2027-10-09", p["anomaly"] + p["retract"])

    def test_past_dates_not_retracted_by_gov(self):
        seen = u.update_seen({}, self.gov, TODAY, "gov")
        seen["2027-01-02"] = {"gov_absent_since": "2026-09-01"}
        p = u.plan_changes({"2026-05-01"}, set(), self.google, seen, "2027-06-01", self.gov, self.gov_years)
        self.assertNotIn("2026-05-01", p["retract"])

    def test_google_rules_untouched_for_other_years(self):
        seen = {"2030-05-06": {"name": "대체", "first": "2026-01-01", "last": "2026-09-01"}}
        seen = u.update_seen(u.update_seen(seen, self.google, TODAY), self.gov, TODAY, "gov")
        p = self.plan(["2030-05-06"], [], seen)
        self.assertEqual(p["retract"], ["2030-05-06"])  # 구글이 알다가 9일째 거둬들임


class ReportGov(unittest.TestCase):
    def test_key_error_reported(self):
        plan = {"add": [], "retract": [], "restore": [], "anomaly": [], "only_local": []}
        r = u.render_report(plan, {}, ["2026: SERVICE_KEY_IS_NOT_REGISTERED_ERROR / 등록되지 않은 서비스키"])
        self.assertIn("DATA_GO_KR_KEY", r)

    def test_partial_year_note_not_reported(self):
        plan = {"add": [], "retract": [], "restore": [], "anomaly": [], "only_local": []}
        self.assertEqual(u.render_report(plan, {}, ["2028: 3개뿐이라 아직 없는 해로 봄"]), "")
