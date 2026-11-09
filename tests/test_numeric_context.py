"""Focused contextual regression cases for check_numbers.py.

These tests are intentionally not run in the current executor slice; the parent
owns the combined verification run.
"""
import importlib
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
calculator = importlib.import_module("check_numbers")


def source_record(applicability="적용", source="적용 기준 2026", scope="이번 용역·사업"):
    return {"적용성": applicability, "출처": source, "적용범위": scope,
            "원문": "적용 범위가 확인된 원문 인용", "위치": "[기준 p.2]"}


def profile_record(profile_id, applicability="적용", institution="기관 A"):
    return {"프로필ID": profile_id, "기관": institution, "적용성": applicability,
            "적용범위": "기관 A의 이번 사업", "출처": "기관 운영지침 2026",
            "원문": "이번 사업 적용 프로필", "위치": "[지침 p.4]"}


def dated_fact(value, quote, location="[문단 1] 입찰 일정", document="공고문", evidence="판독완료"):
    return {"값": value, "문서": document, "원문": quote, "위치": location, "증거상태": evidence}


def numeric_fact(value, quote, location="[문단 8] 공동계약", document="공고문", evidence="판독완료"):
    return {"값": value, "문서": document, "원문": quote, "위치": location, "증거상태": evidence}


def by_item(rows, item):
    return next(row for row in rows if row["항목"] == item)


class NumericContext(unittest.TestCase):
    def setUp(self):
        calculator.findings = []
        with open(calculator.DEFAULT_TH, encoding="utf-8") as stream:
            self.thresholds = json.load(stream)

    def run_scores(self, facts):
        calculator.findings = []
        calculator.check_scores(facts, self.thresholds)
        return calculator.findings

    def run_notice(self, facts, estimate=None):
        calculator.findings = []
        calculator.check_notice(facts, self.thresholds, estimate)
        return calculator.findings

    def run_joint(self, facts):
        calculator.findings = []
        calculator.check_joint(facts, self.thresholds)
        return calculator.findings

    def test_official_threshold_is_nested_and_metadata_gated(self):
        self.assertEqual(calculator.threshold_value(self.thresholds, "배점.원칙_기술"), 70)
        self.assertIsNone(calculator.threshold_value({"배점": {"원칙_기술": 70}}, "배점.원칙_기술"))
        value, record, applicability = calculator.official_rule(
            {"meta": {}}, self.thresholds, "배점.원칙_기술")
        self.assertEqual(value, 70)
        self.assertIsNone(record)
        self.assertEqual(applicability, "미확인")

    def test_unknown_official_scoring_is_confirmation_not_violation(self):
        rows = self.run_scores({
            "낙찰방식": "협상", "배점": {"기술": 80, "가격": 20, "문서": "제안요청서", "원문": "기술 80, 가격 20", "위치": "[문단 1]"},
            "기술평가항목": [{"항목": "방법", "배점": 100, "원문": "100점", "위치": "[문단 2]"}],
            "기술평가": {"원점수만점": 100},
        })
        ratio = by_item(rows, "가격평가 비중 범위")
        self.assertEqual(ratio["판정"], "확인필요")
        self.assertEqual(ratio["적용성"], "미확인")
        self.assertEqual(ratio["대상"], "구매팀")
        self.assertNotIn("기준참조", ratio)
        self.assertFalse(any(row["판정"] == "수정필요" and "70%" in row["문제점"] for row in rows))
        self.assertTrue(all(row.get("조치") for row in rows if row["판정"] == "확인필요"))

    def test_official_rule_requires_complete_source_and_scope_metadata(self):
        facts = {"meta": {"공식기준": {"배점.원칙_가격_최소": {
            "적용성": "적용", "출처": "기준", "적용범위": "이번 사업"}}}}
        value, record, applicability = calculator.official_rule(facts, self.thresholds, "배점.원칙_가격_최소")
        self.assertEqual(value, 20)
        self.assertEqual(applicability, "미확인")
        self.assertFalse(calculator.official_reference_exists(facts, "배점.원칙_가격_최소"))

    def test_correction_requires_real_source_document_quote_and_location(self):
        calculator.findings = []
        calculator.add("②-2", "사업금액 일치", "★필수", "수정필요", "값이 다릅니다.",
                        "국가계약법 시행령 제7조", "금액을 정합화하세요.")
        result = calculator.findings[0]
        self.assertEqual(result["판정"], "확인필요")
        self.assertEqual(result["문서"], "")
        self.assertEqual(result["원문"], "")
        self.assertEqual(result["위치"], "")
        self.assertIn("원문 인용", result["조치"])

        calculator.findings = []
        calculator.add("②-2", "사업금액 일치", "★필수", "수정필요", "값이 다릅니다.",
                        "국가계약법 시행령 제7조", "금액을 정합화하세요.",
                        "공고문", "[문단 1]", "총사업비 100원")
        self.assertEqual(calculator.findings[0]["판정"], "수정필요")

    def test_restriction_threshold_is_not_auto_applied_without_exact_meta(self):
        facts = {"계약유형": "용역", "실적제한": {"있음": True, "문서": "공고문",
                 "원문": "최근 3년 실적 보유", "위치": "[문단 1]"}}
        calculator.findings = []
        calculator.check_restrictions(facts, self.thresholds, 100000000)
        result = by_item(calculator.findings, "고시금액 미만 실적제한 불가")
        self.assertEqual(result["판정"], "확인필요")
        self.assertEqual(result["적용성"], "미확인")
        self.assertNotIn("기준참조", result)

    def test_restriction_threshold_applies_only_with_matching_source_record(self):
        facts = {"계약유형": "용역", "실적제한": {"있음": True, "문서": "공고문",
                 "원문": "최근 3년 실적 보유", "위치": "[문단 1]"},
                 "meta": {"공식기준": {"고시금액_물품용역": source_record()}}}
        calculator.findings = []
        calculator.check_restrictions(facts, self.thresholds, 100000000)
        result = by_item(calculator.findings, "고시금액 미만 실적제한 불가")
        self.assertEqual(result["판정"], "수정필요")
        self.assertEqual(result["기준참조"], ["고시금액_물품용역"])
        self.assertEqual(result["기준유형"], ["법령·공식기준"])

    def test_negative_restriction_requires_full_text_and_object_search_evidence(self):
        facts = {"계약유형": "용역", "실적제한": {"있음": False, "증거상태": "전수검색없음",
                 "문서": "공고문", "검색어": ["수행실적", "참가자격"], "검색범위": "본문·표·개체"}}
        calculator.findings = []
        calculator.check_restrictions(facts, self.thresholds, None)
        result = by_item(calculator.findings, "고시금액 미만 실적제한 불가")
        self.assertEqual(result["판정"], "확인필요")
        self.assertNotEqual(result["증거상태"], "전수검색없음")

        facts["meta"] = {"문서목록": [{"문서ID": "D1", "문서": "공고문", "개체조사": "완료"}]}
        facts["실적제한"]["문서ID"] = "D1"
        calculator.findings = []
        calculator.check_restrictions(facts, self.thresholds, None)
        result = by_item(calculator.findings, "고시금액 미만 실적제한 불가")
        self.assertEqual(result["판정"], "해당없음")
        self.assertEqual(result["증거상태"], "전수검색없음")
        self.assertEqual(result["검색어"], ["수행실적", "참가자격"])

    def test_source_scoped_90_10_and_80_20_profiles_are_not_legal_defaults(self):
        for profile_id, technology, price in (
                ("기관_기술강조_90_10", 90, 10), ("기관_균형_80_20", 80, 20)):
            with self.subTest(profile=profile_id):
                facts = {"낙찰방식": "협상", "배점": {"기술": technology, "가격": price,
                         "문서": "제안요청서", "원문": f"기술 {technology}, 가격 {price}", "위치": "[문단 1]"},
                         "meta": {"기관프로필": [profile_record(profile_id)]}}
                rows = self.run_scores(facts)
                result = by_item(rows, f"기관 배점 프로필({profile_id})")
                self.assertEqual(result["판정"], "적합")
                self.assertEqual(result["기준유형"], ["기관운영"])
                self.assertEqual(result["프로필참조"], profile_id)

    def test_unknown_profile_evidence_stays_unknown_and_linked(self):
        profile_id = "기관_기술강조_90_10"
        facts = {"낙찰방식": "협상", "배점": {"기술": 80, "가격": 20},
                 "meta": {"기관프로필": [profile_record(profile_id, applicability="미확인")]}}
        result = by_item(self.run_scores(facts), f"기관 배점 프로필 확인({profile_id})")
        self.assertEqual(result["판정"], "확인필요")
        self.assertEqual(result["적용성"], "미확인")
        self.assertEqual(result["프로필참조"], profile_id)
        self.assertNotEqual(result["판정"], "수정필요")

    def test_quantitative_70_is_only_applied_with_source_scoped_profile(self):
        profile_id = "기관_정량최저평점_70"
        facts = {"낙찰방식": "협상", "정량평가항목": [
            {"항목": "신용", "배점": 10, "최저등급평점": 6, "문서": "제안요청서", "원문": "최저 6점", "위치": "[표 1]"}],
            "meta": {"기관프로필": [profile_record(profile_id)]}}
        result = by_item(self.run_scores(facts), "정량평가 최저평점 기관기준")
        self.assertEqual(result["판정"], "수정필요")
        self.assertEqual(result["기준유형"], ["기관운영"])
        self.assertEqual(result["프로필참조"], profile_id)
        self.assertNotIn("법령·공식기준", result["기준유형"])

    def test_each_quantitative_violation_keeps_its_own_source_reference(self):
        profile_id = "기관_정량최저평점_70"
        facts = {"낙찰방식": "협상", "정량평가항목": [
            {"항목": "신용", "배점": 10, "최저등급평점": 6, "문서": "제안요청서", "원문": "신용 최저 6점", "위치": "[표 1]"},
            {"항목": "실적", "배점": 10, "최저등급평점": 5, "문서": "제안요청서", "원문": "실적 최저 5점", "위치": "[표 2]"}],
            "meta": {"기관프로필": [profile_record(profile_id)]}}
        rows = self.run_scores(facts)
        related = [row for row in rows if row["id"] == "③-7"]
        self.assertEqual(len(related), 2)
        self.assertEqual(sum(bool(row.get("참조")) for row in related), 1)
        self.assertTrue(all(row["프로필참조"] == profile_id for row in related))

    def test_absent_quantitative_profile_is_unknown_not_legal_defect(self):
        facts = {"낙찰방식": "협상", "정량평가항목": [
            {"항목": "신용", "배점": 10, "최저등급평점": 6, "원문": "최저 6점", "위치": "[표 1]"}]}
        result = by_item(self.run_scores(facts), "정량평가 최저평점 기관기준")
        self.assertEqual(result["판정"], "확인필요")
        self.assertEqual(result["증거상태"], "미제출")
        self.assertNotIn("프로필참조", result)

    def test_raw_100_point_table_normalizes_to_final_90_weight(self):
        official = {"배점.원칙_가격_최소": source_record(), "배점.원칙_가격_최대": source_record()}
        facts = {"낙찰방식": "협상", "배점": {"기술": 90, "가격": 10, "문서": "제안요청서",
                 "원문": "기술 90, 가격 10", "위치": "[문단 1]"},
                 "기술평가": {"원점수만점": 100, "환산기술배점": 90,
                              "환산방식": "비례환산", "환산식원문": "원점수 / 100 × 기술 90점"},
                 "기술평가항목": [{"항목": "A", "배점": 40, "원문": "A 40", "위치": "[표 1]"},
                                   {"항목": "B", "배점": 60, "원문": "B 60", "위치": "[표 1]"}],
                 "meta": {"공식기준": official}}
        rows = self.run_scores(facts)
        result = by_item(rows, "기술 원점수 환산")
        self.assertEqual(result["판정"], "적합")
        self.assertEqual(result["기준유형"], ["사업요건"])
        self.assertNotIn("수정필요", [row["판정"] for row in rows if row["id"] == "②-14"])

    def test_null_raw_points_are_not_zero_and_do_not_create_sum_violation(self):
        facts = {"낙찰방식": "협상", "배점": {"기술": 80, "가격": 20},
                 "기술평가": {"원점수만점": 100},
                 "기술평가항목": [{"항목": "A", "배점": 80}, {"항목": "B", "배점": None}]}
        rows = self.run_scores(facts)
        result = by_item(rows, "평가항목 배점 합계")
        self.assertEqual(result["판정"], "확인필요")
        self.assertFalse(any(row["항목"] == "평가항목 원점수 합계" and row["판정"] == "수정필요" for row in rows))

    def test_custom_item_cap_is_rendered_without_stale_thirty_point_claim(self):
        self.thresholds["공식기준"]["배점"]["평가항목_최대"] = 5
        facts = {"낙찰방식": "협상", "배점": {"기술": 80, "가격": 20, "문서": "제안요청서"},
                 "기술평가": {"원점수만점": 6},
                 "기술평가항목": [{"항목": "A", "배점": 6, "문서": "제안요청서", "원문": "6점", "위치": "[표 1]"}],
                 "meta": {"공식기준": {"배점.평가항목_최대": source_record()}}}
        rows = self.run_scores(facts)
        result = by_item(rows, "각 평가항목 배점한도")
        self.assertEqual(result["판정"], "수정필요")
        self.assertIn("적용 상한 5점을 넘습니다", result["문제점"])
        self.assertNotIn("30점", result["문제점"])

    def test_period_mismatch_requires_same_role_and_start_point(self):
        calculator.findings = []
        calculator.check_period({"사업기간": {
            "공고문": {"값": "6개월", "역할": "계약이행기간", "기산점": "계약일", "원문": "계약일부터 6개월", "위치": "[문단 1]"},
            "용역계약의뢰서": {"값": "12개월", "역할": "사업기간", "기산점": "착수일", "원문": "착수일부터 12개월", "위치": "[문단 2]"}}})
        result = by_item(calculator.findings, "사업기간 일치")
        self.assertEqual(result["판정"], "확인필요")
        self.assertEqual(result["대상"], "구매팀")

    def test_same_role_period_conflict_is_preserved_as_document_contradiction(self):
        calculator.findings = []
        calculator.check_period({"사업기간": {
            "공고문": {"값": "6개월", "역할": "계약이행기간", "기산점": "계약일로부터", "원문": "계약일로부터 6개월", "위치": "[문단 1]"},
            "제안요청서": {"값": "12개월", "역할": "계약이행기간", "기산점": "계약일로부터", "원문": "계약일로부터 12개월", "위치": "[문단 2]"}}})
        result = by_item(calculator.findings, "사업기간 일치")
        self.assertEqual(result["판정"], "수정필요")
        self.assertEqual(result["적용성"], "미확인")
        self.assertEqual(result["증거상태"], "충돌")
        self.assertEqual(result["기준유형"], ["사업요건"])

    def test_amounts_compare_only_same_role_scope_and_vat_and_estimate_is_explicit(self):
        calculator.findings = []
        est = calculator.check_amount({"사업금액": {
            "공고문": {"금액": 220000000, "역할": "사업예산", "범위": "총사업", "부가세": "포함", "원문": "예산 2.2억 포함", "위치": "[문단 1]"},
            "원가계산보고서": {"금액": 210000000, "역할": "원가산정액", "범위": "총사업", "부가세": "제외", "원문": "원가 2.1억 제외", "위치": "[표 1]"}}, "추정가격": None},
            self.thresholds)
        result = by_item(calculator.findings, "사업금액 일치")
        self.assertIsNone(est)
        self.assertEqual(result["판정"], "확인필요")
        self.assertEqual(result["증거상태"], "미판독")

    def vat_facts(self, included, excluded, meta=None):
        facts = {"사업금액": {
            "공고문": {"금액": included, "역할": "사업예산", "범위": "총사업", "부가세": "포함",
                       "원문": f"총액 {included}원, VAT 포함", "위치": "[문단 1]"},
            "제안요청서": {"금액": excluded, "역할": "사업예산", "범위": "총사업", "부가세": "제외",
                           "원문": f"총액 {excluded}원, VAT 제외", "위치": "[문단 2]"}}}
        if meta is not None:
            facts["meta"] = meta
        return facts

    def test_mixed_vat_amounts_normalize_to_equal_ex_vat_totals(self):
        facts = self.vat_facts(110000000, 100000000,
                               {"공식기준": {"부가세율": source_record()}})
        calculator.findings = []
        calculator.check_amount(facts, self.thresholds)
        result = by_item(calculator.findings, "사업금액 일치")
        self.assertEqual(result["판정"], "적합")
        self.assertEqual(result["기준참조"], ["부가세율"])
        self.assertIn("VAT 제외 환산", result["문제점"])

    def test_mixed_vat_normalized_totals_mismatch_without_source_primacy(self):
        facts = self.vat_facts(111000000, 100000000,
                               {"공식기준": {"부가세율": source_record()}})
        calculator.findings = []
        calculator.check_amount(facts, self.thresholds)
        result = by_item(calculator.findings, "사업금액 일치")
        self.assertEqual(result["판정"], "수정필요")
        self.assertEqual(result["기준참조"], ["부가세율"])
        self.assertIn("VAT 제외 환산", result["문제점"])
        self.assertNotIn("원가계산보고서", result["문제점"])

    def test_mixed_vat_without_applicable_rate_stays_confirmation(self):
        facts = self.vat_facts(110000000, 100000000)
        calculator.findings = []
        calculator.check_amount(facts, self.thresholds)
        result = by_item(calculator.findings, "사업금액 일치")
        self.assertEqual(result["판정"], "확인필요")
        self.assertEqual(result["적용성"], "미확인")
        self.assertNotIn("기준참조", result)

    def test_same_vat_one_won_tolerance_and_two_won_mismatch_boundary(self):
        for delta, expected in ((1, "적합"), (2, "수정필요")):
            with self.subTest(delta=delta):
                facts = {"사업금액": {
                    "공고문": {"금액": 100, "역할": "사업예산", "범위": "총사업", "부가세": "제외",
                               "원문": "100원", "위치": "[문단 1]"},
                    "제안요청서": {"금액": 100 + delta, "역할": "사업예산", "범위": "총사업", "부가세": "제외",
                                   "원문": f"{100 + delta}원", "위치": "[문단 2]"}}}
                calculator.findings = []
                calculator.check_amount(facts, self.thresholds)
                result = by_item(calculator.findings, "사업금액 일치")
                self.assertEqual(result["판정"], expected)

    def test_bool_and_nonfinite_amount_or_score_never_pass_as_numeric(self):
        for invalid in (True, float("nan")):
            with self.subTest(invalid=repr(invalid)):
                facts = {"사업금액": {
                    "공고문": {"금액": 100, "역할": "사업예산", "범위": "총사업", "부가세": "제외"},
                    "제안요청서": {"금액": invalid, "역할": "사업예산", "범위": "총사업", "부가세": "제외"}}}
                calculator.findings = []
                calculator.check_amount(facts, self.thresholds)
                self.assertEqual(by_item(calculator.findings, "사업금액 일치")["판정"], "확인필요")

                rows = self.run_scores({"낙찰방식": "협상", "배점": {"기술": 80, "가격": 20},
                                        "기술평가": {"원점수만점": 100},
                                        "기술평가항목": [{"항목": "점수", "배점": invalid}]})
                self.assertEqual(by_item(rows, "평가항목 배점 합계")["판정"], "확인필요")
                self.assertFalse(any(row["판정"] == "적합" and row["id"] == "②-14" for row in rows))

                rows = self.run_scores({"낙찰방식": "협상", "배점": {"기술": 100, "가격": invalid}})
                self.assertEqual(by_item(rows, "기술·가격 배점 합계 100점")["판정"], "확인필요")

    def test_explicit_zero_is_a_valid_numeric_price_weight(self):
        facts = {"낙찰방식": "협상", "배점": {"기술": 100, "가격": 0, "문서": "제안요청서",
                 "원문": "기술 100점, 가격 0점", "위치": "[문단 1]"},
                 "meta": {"공식기준": {"배점.원칙_가격_최소": source_record()}}}
        result = by_item(self.run_scores(facts), "기술평가 100% 불가, 가격평가 필수")
        self.assertEqual(result["판정"], "수정필요")
        self.assertEqual(result["적용성"], "적용")

    def test_sourced_short_notice_violation_retains_document_quote_and_location(self):
        facts = {"낙찰방식": "기타", "계약유형": "용역", "긴급": False,
                 "공고일": dated_fact("2026-11-01", "공고일 2026. 11. 1."),
                 "제출마감일": dated_fact("2026-11-03", "제출마감일 2026. 11. 3.", "[문단 2] 제출 일정"),
                 "meta": {"공식기준": {"공고기간_일.물품용역": source_record()}}}
        result = by_item(self.run_notice(facts), "공고기간 산정(달력 계산)")
        self.assertEqual(result["판정"], "수정필요")
        self.assertEqual(result["증거상태"], "판독완료")
        self.assertIn("공고문", result["문서"])
        self.assertIn("공고일 2026. 11. 1.", result["원문"])
        self.assertIn("제출마감일 2026. 11. 3.", result["원문"])
        self.assertIn("[문단 2] 제출 일정", result["위치"])

    def test_notice_boundary_confirms_and_equal_dates_prove_shortage(self):
        threshold_meta = {"공식기준": {"공고기간_일.물품용역": source_record()}}
        cases = (("2026-11-08", "확인필요"), ("2026-11-01", "수정필요"))
        for deadline, expected in cases:
            with self.subTest(deadline=deadline):
                facts = {"낙찰방식": "기타", "계약유형": "용역", "긴급": False,
                         "공고일": dated_fact("2026-11-01", "공고일 2026. 11. 1."),
                         "제출마감일": dated_fact(deadline, f"제출마감일 {deadline}", "[문단 2] 제출 일정"),
                         "meta": threshold_meta}
                result = by_item(self.run_notice(facts), "공고기간 산정(달력 계산)")
                self.assertEqual(result["판정"], expected)
                self.assertIn("공고문", result["문서"])
                self.assertTrue(result["원문"])
                self.assertTrue(result["위치"])
                if expected == "확인필요":
                    self.assertTrue(result["조치"])

    def test_unknown_notice_rule_scope_stays_confirmation_with_date_evidence(self):
        facts = {"낙찰방식": "기타", "계약유형": "용역", "긴급": False,
                 "공고일": dated_fact("2026-11-01", "공고일 2026. 11. 1."),
                 "제출마감일": dated_fact("2026-11-03", "제출마감일 2026. 11. 3.", "[문단 2] 제출 일정"),
                 "meta": {"공식기준": {"공고기간_일.물품용역": source_record("미확인")}}}
        result = by_item(self.run_notice(facts), "공고기간 산정(달력 계산)")
        self.assertEqual(result["판정"], "확인필요")
        self.assertEqual(result["적용성"], "미확인")
        self.assertEqual(result["증거상태"], "미판독")
        self.assertTrue(result["조치"])
        self.assertIn("공고일 2026. 11. 1.", result["원문"])

    def test_sourced_joint_member_and_share_breaches_keep_their_actual_anchors(self):
        facts = {"공동계약": {
            "공고문": {"값": "허용", "맥락": "현재참가조건", "원문": "공동수급 허용", "위치": "[문단 7]"},
            "구성원수": numeric_fact(6, "공동수급체 구성원은 6인 이내", "[문단 8] 구성원 수"),
            "최소지분율": numeric_fact(5, "구성원별 최소 지분율은 5%", "[문단 9] 지분율")},
            "meta": {"공식기준": {
                "공동계약.구성원_최대": source_record(),
                "공동계약.최소지분율_퍼센트": source_record()}}}
        rows = self.run_joint(facts)
        member = by_item(rows, "공동계약 구성원 수")
        share = by_item(rows, "공동계약 최소지분율")
        for result, quote, location in ((member, "구성원은 6인 이내", "[문단 8] 구성원 수"),
                                        (share, "최소 지분율은 5%", "[문단 9] 지분율")):
            self.assertEqual(result["판정"], "수정필요")
            self.assertEqual(result["증거상태"], "판독완료")
            self.assertEqual(result["문서"], "공고문")
            self.assertIn(quote, result["원문"])
            self.assertIn(location, result["위치"])

    def test_unsourced_and_unread_joint_limits_remain_confirmation(self):
        cases = (("구성원수", 6, "공동계약.구성원_최대", "공동계약 구성원 수"),
                 ("최소지분율", 5, "공동계약.최소지분율_퍼센트", "공동계약 최소지분율"))
        for fact_key, value, threshold_key, label in cases:
            records = (numeric_fact(value, "", "", evidence="판독완료"),
                       numeric_fact(value, "구성원 조건 원문", "[문단 8]", evidence="미판독"))
            for record in records:
                with self.subTest(fact=fact_key, evidence=record["증거상태"], location=record["위치"]):
                    facts = {"공동계약": {
                        "공고문": {"값": "허용", "맥락": "현재참가조건", "원문": "공동수급 허용", "위치": "[문단 7]"},
                        fact_key: record},
                        "meta": {"공식기준": {threshold_key: source_record()}}}
                    result = by_item(self.run_joint(facts), label)
                    self.assertEqual(result["판정"], "확인필요")
                    self.assertEqual(result["적용성"], "미확인")
                    self.assertEqual(result["대상"], "구매팀")
                    self.assertTrue(result["조치"])

    def test_numeric_joint_limit_records_are_not_document_map_entries(self):
        facts = {"공동계약": {
            "공고문": {"값": "허용", "맥락": "현재참가조건", "원문": "공동수급 허용", "위치": "[문단 7]"},
            "구성원수": numeric_fact(3, "구성원은 3인", "[문단 8]"),
            "최소지분율": numeric_fact(10, "최소 지분율 10%", "[문단 9]")}}
        rows = self.run_joint(facts)
        participation = by_item(rows, "공동도급 허용 여부 기재")
        self.assertEqual(participation["판정"], "확인필요")
        self.assertEqual(participation["문서"], "공고문")
        self.assertNotIn("구성원수", participation["문서"])
        self.assertNotIn("최소지분율", participation["문서"])

    def test_same_scope_amount_difference_is_not_suppressed_by_cost_report(self):
        calculator.findings = []
        calculator.check_amount({"사업금액": {
            "공고문": {"금액": 220000000, "역할": "사업예산", "범위": "총사업", "부가세": "제외", "원문": "예산 220000000원", "위치": "[문단 1]"},
            "제안요청서": {"금액": 210000000, "역할": "사업예산", "범위": "총사업", "부가세": "제외", "원문": "예산 210000000원", "위치": "[문단 2]"},
            "원가계산보고서": {"금액": 210000000, "역할": "원가산정액", "범위": "총사업", "부가세": "제외", "원문": "원가 210000000원", "위치": "[표 1]"}}}, self.thresholds)
        result = by_item(calculator.findings, "사업금액 일치")
        self.assertEqual(result["판정"], "수정필요")
        self.assertEqual(result["증거상태"], "충돌")
        self.assertEqual(result["기준유형"], ["사업요건"])

    def test_historical_joint_performance_never_becomes_current_eligibility(self):
        calculator.findings = []
        calculator.check_joint({"공동계약": {"과거실적증빙": {
            "제안요청서": {"요구여부": "요구", "요구내용": "공동수행 지분 증빙", "원문": "과거 실적 증빙", "위치": "[서식 1]"}}}}, self.thresholds)
        self.assertEqual(calculator.findings, [])

    def test_current_joint_participation_contradiction_is_still_found(self):
        calculator.findings = []
        calculator.check_joint({"공동계약": {
            "공고문": {"값": "허용", "맥락": "현재참가조건", "원문": "공동수급 허용", "위치": "[문단 1]"},
            "제안요청서": {"값": "불허", "맥락": "현재참가조건", "원문": "공동수급 불허", "위치": "[문단 2]"}}}, self.thresholds)
        result = next(row for row in calculator.findings if row["id"] == "②-3")
        self.assertEqual(result["판정"], "수정필요")
        self.assertEqual(result["증거상태"], "충돌")
        self.assertEqual(result["기준유형"], ["사업요건"])

    def test_numeric_output_preserves_source_metadata(self):
        facts = {"계약유형": "용역", "낙찰방식": "기타", "meta": {
            "공식기준": {"고시금액_물품용역": source_record("미확인")},
            "기관프로필": [profile_record("기관_기술강조_90_10", "미확인")]}}
        with tempfile.TemporaryDirectory() as directory:
            facts_path = os.path.join(directory, "facts.json")
            output_path = os.path.join(directory, "numbers.json")
            with open(facts_path, "w", encoding="utf-8") as stream:
                json.dump(facts, stream, ensure_ascii=False)
            with patch.object(sys, "argv", ["check_numbers.py", facts_path, "-o", output_path]):
                with open(os.devnull, "w", encoding="utf-8") as sink, patch("sys.stdout", sink):
                    calculator.main()
            with open(output_path, encoding="utf-8") as stream:
                result = json.load(stream)
        self.assertEqual(result["meta"], facts["meta"])


if __name__ == "__main__":
    unittest.main()
