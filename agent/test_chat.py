"""Tests for the counsellor assistant: case reading, assessment, engine (AI on, off and failing) and API.

Run from the repository root:
    .venv/Scripts/python.exe -m unittest agent.test_chat -v
"""
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from agent import prompts as P
from agent import server
from agent.casebook import assess, read_case
from agent.chat import ChatEngine, Turn
from agent.extract import detect_intent, extract
from agent.language import detect_language
from agent.risk_tool import RiskTool
from agent.store import Store

TODAY = date(2026, 11, 13)
TOOL = None
OFFLINE_NOTICE = "AI writing is offline right now"


def tool() -> RiskTool:
    global TOOL
    if TOOL is None:
        TOOL = RiskTool(political_phase="Newly Elected", bdt_per_usd=122)
    return TOOL


class FakeLLM:
    model = "fake-model"

    def __init__(self, available=True, reply="**Main problem**\n- The bank statement is not ready.", fail=False):
        self._available, self.reply, self.fail, self.calls = available, reply, fail, []

    def available(self, max_age=15.0):
        return self._available

    def stream_chat(self, messages, temperature=0.4):
        self.calls.append(messages)
        if self.fail:  # e.g. Ollama switched off after the status check
            raise RuntimeError("No language model reachable (primary: ConnectError)")
        yield self.reply[:12]
        yield self.reply[12:]


class NoExamples:
    def search(self, *args, **kwargs):
        return []

    def __len__(self):
        return 0


class FakeLibrary:
    """Two past cases, so tests do not depend on the confidential conversation files."""
    CASES = [{"id": "c1", "title": "Bank Statement Not 28 Days Old", "destination": "Malaysia",
              "match": "same problem type", "advice": ["Delay to the next intake or use a sponsor."], "score": 1.0},
             {"id": "c2", "title": "Study Gap Explanation", "destination": "UK",
              "match": "similar wording", "advice": ["Ask for a gap explanation letter."], "score": 0.4}]

    def similar(self, query, scenarios=None, k=3, min_score=0.15):
        return self.CASES[:k]

    def __len__(self):
        return len(self.CASES)


def make_engine(llm=None) -> ChatEngine:
    db = Path(tempfile.mkdtemp()) / "test.db"
    engine = ChatEngine(store=Store(db), tool=tool(), llm=llm or FakeLLM(available=False),
                        retriever=NoExamples(), library=FakeLibrary())
    engine.type_delay = 0
    return engine


def run(engine, client, text, cid=None, language=None, mode="case"):
    events = list(engine.handle(Turn(client_id=client, text=text, conversation_id=cid, quick_reply=None,
                                     language=language, mode=mode)))
    reply = "".join(e["text"] for e in events if e["type"] == "token")
    chips = next((e["chips"] for e in events if e["type"] == "chips"), [])
    cid = next(e["conversation_id"] for e in events if e["type"] == "meta")
    return cid, reply, chips, events


def case_of(events) -> dict:
    return next(e["case"] for e in events if e["type"] == "case")


BANK_CASE = ("My student wants to study a Business bachelor's in Malaysia, but the bank statement has not "
             "completed 28 days. HSC GPA 4.5, IELTS 6.0, budget 12 lakh. They want the January 2027 intake.")


class ExtractTest(unittest.TestCase):
    CASES = [
        ("I want to study Computer Science in Canada, my CGPA is 3.25 out of 4", None,
         {"country": "Canada", "course": "Computer Science", "gpa": 3.25, "gpa_scale": 4.0}),
        ("Ami UK te porte chai, budget 18 lakh er moto", None,
         {"country": "UK", "budget_amount": 18.0, "budget_unit": "lakh_taka"}),
        ("আমি অস্ট্রেলিয়ায় পড়তে চাই, বাজেট ২০ লাখ টাকা", None,
         {"country": "Australia", "budget_amount": 20.0, "budget_unit": "lakh_taka"}),
        ("আমি মালয়েশিয়ায় বিবিএ পড়তে চাই। কি কি ডকুমেন্ট লাগবে?", None,
         {"country": "Malaysia", "course": "Business Administration"}),  # no false "May" intake
        ("January 2027 intake", None, {"intake": "2027-01"}),
        ("I may apply next year", None, {}),
        ("IELTS 6.5 and HSC GPA 5.00", None, {"gpa": 5.0, "gpa_scale": 5.0}),
        ("মে মাসে ভর্তি হতে চাই", None, {"intake": "2027-05"}),
        ("$15k per year", None, {"budget_amount": 15000.0, "budget_unit": "usd"}),
    ]

    def test_cases(self):
        for text, awaiting, expected in self.CASES:
            with self.subTest(text=text):
                self.assertEqual(extract(text, awaiting, TODAY)[0], expected)

    def test_intents_and_language(self):
        self.assertEqual(detect_intent("Can the student edit the bank statement to show more money?"), "integrity")
        self.assertEqual(detect_intent("Hello"), "greeting")
        self.assertEqual(detect_language("Student er IELTS nai, ki korbo?"), "banglish")
        self.assertEqual(detect_language("আমার স্টুডেন্টের ভিসা রিফিউজ হয়েছে"), "bengali")


class CasebookTest(unittest.TestCase):
    def test_reads_problems_from_a_counsellor_description(self):
        updates, mentioned = read_case("Student has a three-year study gap, a previous UK visa refusal and "
                                       "wants to bring his wife. IELTS 5.5.", TODAY)
        self.assertEqual(updates["gap_years"], 3)
        self.assertTrue(updates["visa_refusal"])
        self.assertTrue(updates["dependants"])
        self.assertEqual((updates["english_test"], updates["english_score"]), ("IELTS", 5.5))
        self.assertTrue({"study_gap", "visa_refusal", "dependants"} <= mentioned)

    def test_refusal_country_is_not_the_destination(self):
        self.assertEqual(read_case("The student also had a UK visa refusal last year.", TODAY)[0].get("country"), None)
        updates, _ = read_case("Refused by Canada in 2024, now wants to study in Australia", TODAY)
        self.assertEqual((updates["country"], updates["refusal_country"]), ("Australia", "Canada"))
        updates, _ = read_case("আমার স্টুডেন্টের আগে কানাডার ভিসা রিফিউজ হয়েছে। এখন UK-তে মাস্টার্স করতে চায়।", TODAY)
        self.assertEqual((updates["country"], updates["refusal_country"]), ("UK", "Canada"))

    def test_bank_statement_not_ready_blocks_the_intake(self):
        updates, mentioned = read_case(BANK_CASE, TODAY)
        self.assertEqual(updates["bank_status"], "Not ready")
        result = assess(updates, mentioned, TODAY)
        self.assertEqual(result["verdict"], "Not yet eligible")
        self.assertIn("bank_not_ready", [i["id"] for i in result["issues"]])

    def test_thin_case_asks_for_more_information(self):
        updates, mentioned = read_case("Student wants to go to Canada.", TODAY)
        result = assess(updates, mentioned, TODAY)
        self.assertEqual(result["verdict"], "Need more information")
        self.assertTrue(result["missing"])

    def test_complete_case_without_problems(self):
        updates, mentioned = read_case("Master's in Computer Science in the UK, CGPA 3.6 out of 4, IELTS 7.0, "
                                       "budget 30 lakh, bank statement ready, September 2027 intake.", TODAY)
        self.assertIn(assess(updates, mentioned, TODAY)["verdict"], ("Likely eligible", "Potentially eligible"))


class EngineTest(unittest.TestCase):
    def test_offline_gives_a_full_case_answer_not_an_error(self):
        engine = make_engine(FakeLLM(available=False))
        _, reply, chips, events = run(engine, "client-0001", BANK_CASE)
        types = [e["type"] for e in events]
        self.assertEqual(types[0], "meta")
        self.assertIn("case", types)
        self.assertEqual(types[-1], "done")
        notice = next(e["text"] for e in events if e["type"] == "notice")
        self.assertIn(OFFLINE_NOTICE, notice)
        self.assertNotIn("RuntimeError", json.dumps(events))
        self.assertIn("Not yet eligible", reply)
        self.assertIn("Bank statement", reply)
        self.assertEqual(case_of(events)["assessment"]["verdict"], "Not yet eligible")
        self.assertIn(P.FOLLOW_UPS["documents"], [c["label"] for c in chips])

    def test_ai_failing_after_the_status_check_falls_back(self):
        """The reported bug: Ollama turned off on the PC showed 'AI model unavailable (RuntimeError)'."""
        llm = FakeLLM(available=True, fail=True)
        engine = make_engine(llm)
        _, reply, _, events = run(engine, "client-0002", BANK_CASE)
        self.assertEqual(len(llm.calls), 1)
        self.assertIn(OFFLINE_NOTICE, next(e["text"] for e in events if e["type"] == "notice"))
        self.assertNotIn("RuntimeError", reply)
        self.assertIn("Not yet eligible", reply)
        self.assertNotIn("error", [e["type"] for e in events])

    def test_offline_follow_up_buttons_answer_from_the_rules(self):
        engine = make_engine(FakeLLM(available=False))
        cid, _, _, _ = run(engine, "client-0003", BANK_CASE)
        for label, heading in [(P.FOLLOW_UPS["documents"], "Documents to request"),
                               (P.FOLLOW_UPS["pathways"], "Possible pathways"),
                               (P.FOLLOW_UPS["tell"], "What to tell the student"),
                               (P.FOLLOW_UPS["missing"], "Ask the student next")]:
            with self.subTest(label=label):
                _, reply, _, _ = run(engine, "client-0003", label, cid=cid)
                self.assertIn(heading, reply)

    def test_ai_answer_is_grounded_in_the_case_sheet(self):
        llm = FakeLLM(available=True)
        engine = make_engine(llm)
        _, reply, _, events = run(engine, "client-0004", BANK_CASE)
        self.assertTrue(reply.startswith("**Main problem**"))
        self.assertNotIn("notice", [e["type"] for e in events])
        system = llm.calls[0][0]["content"]
        self.assertIn(P.COUNSELLOR_SYSTEM, system)
        self.assertIn("CASE RULE", system)
        self.assertIn("PAST CASE: Bank Statement Not 28 Days Old", system)
        self.assertIn("Not yet eligible", system)

    def test_follow_ups_do_not_repeat_the_full_assessment(self):
        llm = FakeLLM(available=True)
        engine = make_engine(llm)
        cid, _, _, _ = run(engine, "client-0009", BANK_CASE)
        run(engine, "client-0009", P.FOLLOW_UPS["pathways"], cid=cid)
        first, second = llm.calls[0][0]["content"], llm.calls[1][0]["content"]
        self.assertIn(P.CASE_RULES.splitlines()[0], first)
        self.assertIn(P.FOLLOW_UP_RULES.splitlines()[0], second)
        self.assertNotIn(P.CASE_RULES.splitlines()[0], second)

    def test_training_mode_uses_training_rules(self):
        llm = FakeLLM(available=True, reply="In training: first check the bank statement date.")
        engine = make_engine(llm)
        run(engine, "client-0005", "How do I handle a student with a study gap?", mode="training")
        self.assertIn(P.TRAINING_RULES.split("{")[0][:40], llm.calls[0][0]["content"])

    def test_document_tampering_is_refused_without_the_model(self):
        llm = FakeLLM(available=True)
        engine = make_engine(llm)
        _, reply, _, _ = run(engine, "client-0006", "Can the student edit the bank statement to show more money?")
        self.assertIn(P.INTEGRITY_REPLY[:40], reply)
        self.assertEqual(llm.calls, [])

    def test_amounts_not_in_the_case_get_a_caveat(self):
        engine = make_engine(FakeLLM(available=True, reply="Malaysia needs about MYR 45,000 in the account."))
        _, reply, _, _ = run(engine, "client-0007", BANK_CASE)
        self.assertIn("verify the current figure", reply)

    def test_edit_dismiss_and_flag(self):
        engine = make_engine()
        cid, _, _, _ = run(engine, "client-0008", BANK_CASE)
        sheet = engine.update_profile(cid, {"bank_status": "Ready", "country": "UK"})
        self.assertNotIn("bank_not_ready", [i["id"] for i in sheet["assessment"]["issues"]])
        self.assertEqual(sheet["raw"]["country"], "UK")
        sheet = engine.update_profile(cid, {"visa_refusal": True})
        self.assertIn("visa_refusal", [i["id"] for i in sheet["assessment"]["issues"]])
        sheet = engine.update_profile(cid, {}, dismiss=["visa_refusal"])
        self.assertNotIn("visa_refusal", [i["id"] for i in sheet["assessment"]["issues"]])
        self.assertTrue(engine.set_flag(cid, True, "Please check the sponsor letter")["flag"])
        summary = engine.counsellor_summary(engine.store.get_conversation(cid))
        self.assertEqual(summary["flag"]["note"], "Please check the sponsor letter")


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server._engine = make_engine()
        cls.client = TestClient(server.app)

    def chat(self, client_id, text, **extra):
        body = {"client_id": client_id, "text": text, **extra}
        with self.client.stream("POST", "/api/chat", json=body) as response:
            self.assertEqual(response.status_code, 200)
            raw = "".join(response.iter_text())
        return [json.loads(line[6:]) for line in raw.splitlines() if line.startswith("data: ")]

    def test_chat_stream_case_sheet_and_privacy(self):
        events = self.chat("api-client-01", BANK_CASE)
        types = [e["type"] for e in events]
        self.assertEqual((types[0], types[-1]), ("meta", "done"))
        self.assertIn("case", types)
        self.assertIn("notice", types)  # the fake AI is offline
        cid = events[0]["conversation_id"]
        conv = self.client.get(f"/api/conversations/{cid}", params={"client_id": "api-client-01"}).json()
        self.assertEqual(conv["case"]["assessment"]["verdict"], "Not yet eligible")
        self.assertEqual(len(conv["messages"]), 2)
        self.assertEqual(self.client.get(f"/api/conversations/{cid}", params={"client_id": "someone-else"}).status_code, 404)

    def test_profile_flag_and_team_overview(self):
        cid = self.chat("api-client-02", BANK_CASE)[0]["conversation_id"]
        params = {"client_id": "api-client-02"}
        sheet = self.client.post(f"/api/conversations/{cid}/profile", params=params,
                                 json={"changes": {"bank_status": "Ready"}}).json()
        self.assertNotEqual(sheet["assessment"]["verdict"], "Not yet eligible")
        flag = self.client.post(f"/api/conversations/{cid}/flag", params=params,
                                json={"flagged": True, "note": "Check funds"}).json()
        self.assertEqual(flag["flag"]["note"], "Check funds")
        listed = self.client.get("/api/conversations", params=params).json()
        self.assertTrue(listed[0]["flagged"])
        self.assertTrue(listed[0]["verdict"])
        team = self.client.get("/api/counsellor/conversations").json()
        self.assertTrue(any(c["flag"] for c in team["conversations"]))
        detail = self.client.get(f"/api/counsellor/conversations/{cid}").json()
        self.assertEqual(detail["case"]["flag"]["note"], "Check funds")
        # Someone else's browser cannot edit the case.
        self.assertEqual(self.client.post(f"/api/conversations/{cid}/flag", params={"client_id": "other-client"},
                                          json={"flagged": False}).status_code, 404)

    def test_pages(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertIn("Team overview", self.client.get("/team").text)
        self.assertEqual(self.client.get("/counsellor", follow_redirects=False).status_code, 307)


if __name__ == "__main__":
    unittest.main()
