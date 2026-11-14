"""SARP-Agent counsellor assistant: one counsellor message in, a stream of events out.

Each conversation is a student case. For every message the engine
 1. reads case details from the counsellor's text (agent/casebook.py on top of agent/extract.py);
 2. assesses the case: eligibility verdict, problems found, missing information;
 3. scores the student with SARP-Net (continuation probability, SHAP drivers and project evidence);
 4. finds similar past cases from the agency's recorded conversations;
 5. answers: the language model writes the reply from all of the above; if no model is reachable, a
    structured answer is built from the case rules and past cases, so the counsellor is never left
    without help.

Events yielded: meta, case, token, notice, chips, done.
"""
from __future__ import annotations

import logging
import re
import time
from collections.abc import Iterator
from dataclasses import dataclass

from agent import prompts as P
from agent.cases import CaseLibrary
from agent.casebook import BANK_STATES, ENGLISH_TESTS, ISSUES, LEVELS, assess, guidance, read_case
from agent.extract import detect_intent
from agent.language import LANGUAGES, detect_language
from agent.llm import LLMRouter
from agent.retriever import Retriever
from agent.risk_tool import COUNTRY_ALIASES, COURSE_ALIASES, INSTITUTION_ALIASES, RiskTool, match_name
from agent.store import Store

log = logging.getLogger("sarp.chat")

SARP_KEYS = ["gpa", "gpa_scale", "course", "country", "institution", "budget_amount", "budget_unit",
             "budget_band", "due_diligence", "intake"]
EDITABLE = {"country", "level", "course", "institution", "intake", "gpa", "gpa_scale", "english_test",
            "english_score", "budget_band", "budget_amount", "bank_status", "bank_days", "gap_years",
            "visa_refusal", "dependants", "due_diligence", "notes"}
# Which problem types each editable field decides (see casebook.assess).
FIELD_ISSUES = {"bank_status": ("bank_not_ready",), "bank_days": ("bank_not_ready",),
                "visa_refusal": ("visa_refusal",), "dependants": ("dependants",), "gap_years": ("study_gap",),
                "english_test": ("english_low", "english_missing"), "english_score": ("english_low", "english_missing"),
                "gpa": ("academic_below",), "gpa_scale": ("academic_below",), "intake": ("missed_intake",),
                "budget_band": ("funding_gap",), "budget_amount": ("funding_gap",)}
SARP_NEEDS = {"due_diligence": "research done by the student", "intake": "intake", "budget": "budget",
              "gpa": "latest result", "country": "destination"}
DUE_DILIGENCE = ["No", "Yes Low", "Yes Medium", "Yes High"]
# Money amounts in a model reply ("CAD 10,000", "£1,334", "20 lakh", "৳৫০,০০০")
AMOUNT_RE = re.compile(r"(?:[$£€৳]|\b(?:CAD|AUD|NZD|USD|GBP|EUR|RM|MYR|BDT|Tk)\.?)\s?[\d০-৯][\d০-৯,.]*|"
                       r"[\d০-৯][\d০-৯,.]*\s?(?:lakh|lac|crore|লাখ|কোটি|টাকা|taka|dollars?|pounds?|ডলার)", re.I)
DIGITS_RE = re.compile(r"[\d০-৯][\d০-৯,.]*")
BN_TO_ASCII = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
# Small models sometimes slip into another script; Bengali and Latin are kept.
FOREIGN_SCRIPT_RE = re.compile(r"[ऀ-ॿ਀-෿฀-๿぀-ヿ一-鿿가-힯]+")


@dataclass
class Turn:
    client_id: str
    text: str
    conversation_id: str | None = None
    quick_reply: dict | None = None   # kept for API compatibility; suggestion chips send plain text
    language: str | None = None       # "auto" or one of LANGUAGES
    client_ip: str | None = None
    mode: str = "case"                # "case" (assessment) or "training"


def make_title(text: str, limit: int = 48) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return (cut or text[:limit]) + "…"


class ChatEngine:
    type_delay = 0.008  # seconds per word for fixed text (tests set 0)

    def __init__(self, store: Store | None = None, tool: RiskTool | None = None,
                 llm: LLMRouter | None = None, retriever: Retriever | None = None,
                 library: CaseLibrary | None = None):
        self.store = store or Store()
        self.tool = tool or RiskTool()
        self.llm = llm or LLMRouter.from_env()
        self.retriever = retriever if retriever is not None else Retriever(store=self.store)
        self.library = library if library is not None else CaseLibrary(store=self.store)

    # ------------------------------------------------------------------ status
    def status(self) -> dict:
        return {"mode": "ai" if self.llm.available() else "offline", "model": self.llm.model,
                "examples": len(self.retriever), "cases": len(self.library), "bdt_per_usd": self.tool.bdt_per_usd}

    def detailed_status(self) -> dict:
        describe = getattr(self.llm, "describe", None)
        return {**self.status(), "providers": describe() if describe else [],
                "last_used": getattr(self.llm, "last_used", None), "storage": self.store.backend,
                "examples_source": getattr(self.retriever, "source", None),
                "cases_source": getattr(self.library, "source", None)}

    # ------------------------------------------------------------------ the case sheet
    def _profile_view(self, p: dict) -> list[dict]:
        t = self.tool

        def canon(value, options, aliases):
            return (match_name(value, options, aliases) or value) if value else None

        budget = None
        if p.get("budget_band"):
            budget = {"Below 10k": "Under $10k a year", "10-15K": "$10-15k a year", "16-20K": "$16-20k a year"}.get(
                p["budget_band"], p["budget_band"])
        elif p.get("budget_amount") is not None:
            amount, unit = float(p["budget_amount"]), p.get("budget_unit")
            budget = (f"{amount:g} lakh taka" if unit == "lakh_taka" or (unit is None and amount < 1000)
                      else f"{amount:,.0f} taka" if unit == "taka" else f"${amount:,.0f}")
        result = None
        if p.get("gpa") is not None:
            scale = p.get("gpa_scale") or (5 if float(p["gpa"]) > 4 else 4)
            result = f"{float(p['gpa']):.2f} / {float(scale):g}"
        english = None
        if p.get("english_test"):
            english = p["english_test"] + (f" {p['english_score']:g}" if p.get("english_score") is not None else "")
        bank = p.get("bank_status")
        if bank and p.get("bank_days") is not None:
            bank = f"{bank} ({p['bank_days']} days held)"
        intake = None
        if p.get("intake") and re.match(r"^\d{4}-\d{2}", str(p["intake"])):
            intake = f"{P.MONTHS_EN[int(p['intake'][5:7]) - 1]} {p['intake'][:4]}"
        yes_no = {True: "Yes", False: "No"}
        rows = [
            ("country", "Destination", canon(p.get("country"), t.countries, COUNTRY_ALIASES)),
            ("level", "Level", p.get("level")),
            ("course", "Course", canon(p.get("course"), t.courses, COURSE_ALIASES)),
            ("institution", "University", canon(p.get("institution"), t.institutions, INSTITUTION_ALIASES)),
            ("intake", "Intake", intake),
            ("gpa", "Latest result", result),
            ("english_test", "English", english),
            ("budget_band", "Budget", budget),
            ("bank_status", "Bank statement", bank),
            ("gap_years", "Study gap", f"{p['gap_years']} years" if p.get("gap_years") is not None
             else (f"Passed {p['pass_year']}" if p.get("pass_year") else None)),
            ("visa_refusal", "Visa refusal", (f"Yes ({p['refusal_country']})" if p.get("visa_refusal") and p.get("refusal_country")
                                              else yes_no.get(p.get("visa_refusal")))),
            ("dependants", "Dependants", yes_no.get(p.get("dependants"))),
            ("due_diligence", "Research done", {"No": "Not yet", "Yes Low": "Country and subject",
                                                "Yes Medium": "Shortlisted", "Yes High": "Well researched"}.get(
                p.get("due_diligence"))),
        ]
        return [{"key": k, "label": label, "value": v} for k, label, v in rows]

    def _assessment(self, state: dict) -> dict:
        dismissed = set(state.get("dismissed", []))
        mentioned = set(state.get("mentioned", [])) - dismissed
        result = assess(state.get("profile", {}), mentioned)
        result["issues"] = [i for i in result["issues"] if i["id"] not in dismissed]
        return result

    def _risk(self, state: dict) -> dict:
        p = state.get("profile", {})
        result = self.tool.assess({k: p[k] for k in SARP_KEYS if k in p})
        state["assessment"] = result  # also read by the team overview page
        if result["status"] != "ok":
            return {"status": "incomplete", "needs": [SARP_NEEDS.get(m, m) for m in result["missing"]]}
        view = result["counsellor_view"]
        return {"status": "ok", "probability": view["probability"], "tier": view["risk_tier"],
                "level": view["risk_level"], "cutoffs": view["cutoffs"],
                "drivers": [{"label": d["label"], "direction": d["direction"], "shap": d["shap"],
                             "evidence": d["evidence"][:2]} for d in view["drivers"][:3]],
                "what_if": view["due_diligence_what_if"],
                "warnings": [w["message"] for w in result["warnings"]
                             if w["code"] in ("intake_after_training_period", "country_not_in_model")]}

    def case_sheet(self, state: dict) -> dict:
        return {"profile": self._profile_view(state.get("profile", {})),
                "raw": {k: v for k, v in state.get("profile", {}).items() if k in EDITABLE},
                "assessment": self._assessment(state), "risk": self._risk(state),
                "similar": state.get("similar", []), "flag": state.get("flag"),
                "notes": state.get("profile", {}).get("notes", ""),
                "options": {"levels": LEVELS, "english_tests": ENGLISH_TESTS, "bank_states": BANK_STATES,
                            "due_diligence": DUE_DILIGENCE, "countries": self.tool.countries}}

    @staticmethod
    def counsellor_summary(conv: dict) -> dict:
        state = conv.get("state") or {}
        assessment = state.get("assessment") or {}
        view = assessment.get("counsellor_view") or {}
        return {"id": conv["id"], "title": conv.get("title") or "New case", "updated": conv["updated"],
                "language": state.get("language"), "message_count": conv.get("message_count"),
                "status": assessment.get("status"), "risk_level": view.get("risk_level"),
                "probability": view.get("probability"), "missing": assessment.get("missing", []),
                "verdict": state.get("verdict"), "flag": state.get("flag"), "handoff": state.get("flag")}

    # ------------------------------------------------------------------ one turn
    def handle(self, turn: Turn) -> Iterator[dict]:
        conv = self.store.get_conversation(turn.conversation_id) if turn.conversation_id else None
        if conv is None or conv["client_id"] != turn.client_id:
            conv = self.store.create_conversation(turn.client_id)
        cid = conv["id"]
        state = conv["state"] or {}
        state.setdefault("profile", {})
        state.setdefault("mentioned", [])
        yield {"type": "meta", "conversation_id": cid, "title": conv["title"]}

        text = turn.text.strip()
        self.store.add_message(cid, "user", text, client_id=turn.client_id, client_ip=turn.client_ip)
        lang = turn.language if turn.language in LANGUAGES else (detect_language(text) or state.get("language") or "english")
        state["language"] = lang
        mode = "training" if turn.mode == "training" or text == P.FOLLOW_UPS["train"] else "case"

        # Update the case from what the counsellor wrote.
        updates, mentioned = read_case(text)
        profile = state["profile"]
        if "budget_band" in updates:
            profile.pop("budget_amount", None)
            profile.pop("budget_unit", None)
        if "budget_amount" in updates:
            profile.pop("budget_band", None)
        if "gpa" in updates:
            profile.pop("gpa_scale", None)
        profile.update({k: v for k, v in updates.items() if v is not None})
        state["mentioned"] = sorted(set(state["mentioned"]) | mentioned)

        sheet = self._refresh(state, text)
        yield {"type": "case", "case": sheet}

        intent = detect_intent(text)
        message_id = self.store.add_message(cid, "assistant", "")
        out: list[str] = []
        chips = self._follow_ups(sheet, mode)
        try:
            if intent == "integrity":
                yield from self._typewriter(P.INTEGRITY_REPLY, out)
            elif intent == "greeting" and not updates and not mentioned:
                yield from self._typewriter(P.GREETING_REPLY, out)
            else:
                yield from self._answer(cid, lang, mode, state, sheet, out)
            if chips:
                yield {"type": "chips", "chips": chips}
        finally:
            self.store.update_message(message_id, "".join(out).strip(), {"chips": chips})
            title = conv["title"] or make_title(text)
            self.store.update_conversation(cid, title=title, state=state)
        if not conv["title"]:
            yield {"type": "meta", "conversation_id": cid, "title": title}
        yield {"type": "done", "message_id": message_id}

    def _refresh(self, state: dict, text: str = "") -> dict:
        assessment = self._assessment(state)
        scenarios = [s for i in assessment["issues"] for s in ISSUES[i["id"]]["scenarios"]]
        query = " ".join([text] + [i["title"] for i in assessment["issues"]] + [state["profile"].get("country") or ""])
        if text or not state.get("similar"):
            state["similar"] = self.library.similar(query, scenarios, k=3)
        state["verdict"] = assessment["verdict"]
        return self.case_sheet(state)

    # ------------------------------------------------------------------ answers
    def _typewriter(self, text: str, out: list[str]) -> Iterator[dict]:
        for piece in re.findall(r"\S+\s*|\s+", text):
            out.append(piece)
            yield {"type": "token", "text": piece}
            if self.type_delay:
                time.sleep(self.type_delay)

    @staticmethod
    def _follow_ups(sheet: dict, mode: str) -> list[dict]:
        keys = []
        if sheet["assessment"]["issues"]:
            keys += ["pathways", "documents", "tell"]
        if sheet["assessment"]["missing"]:
            keys.append("missing")
        if mode == "case":
            keys.append("train")
        return [{"label": P.FOLLOW_UPS[k], "kind": "suggest"} for k in keys[:4]]

    def _case_context(self, sheet: dict) -> str:
        known = "; ".join(f"{r['label']}: {r['value']}" for r in sheet["profile"] if r["value"]) or "nothing yet"
        a = sheet["assessment"]
        lines = [f"CASE SHEET\nKnown details: {known}.",
                 f"Eligibility (rule-based): {a['verdict']}. {a['reason']}",
                 "Checks: " + "; ".join(f"{c['area']}: {c['state']} ({c['note']})" for c in a["checks"])]
        if a["missing"]:
            lines.append("Missing information: " + ", ".join(a["missing"]))
        for g in guidance([i["id"] for i in a["issues"]][:3]):
            lines.append(f"\nCASE RULE: {g['title']} ({g['severity']}). {g['summary']}\n"
                         f"Check: {'; '.join(g['check'])}\nAsk the student: {'; '.join(g['ask'])}\n"
                         f"Documents: {'; '.join(g['documents'])}\nPathways: {'; '.join(g['pathways'])}\n"
                         f"Tell the student: {g['tell']}")
        r = sheet["risk"]
        if r["status"] == "ok":
            drivers = "; ".join(f"{d['label']} {d['direction']} ({' '.join(d['evidence'][:1])})" for d in r["drivers"])
            lines.append(f"\nSARP-NET (agency model, 6,000 records): continuation probability {r['probability']:.0%}, "
                         f"{r['tier']}. Main drivers: {drivers}")
        else:
            lines.append("\nSARP-NET: not scored yet; needs " + ", ".join(r["needs"]))
        for c in sheet["similar"]:
            lines.append(f"\nPAST CASE: {c['title']}\nWhat our counsellor advised: " + " | ".join(c["advice"][:2]))
        return "\n".join(lines)

    def _answer(self, cid: str, lang: str, mode: str, state: dict, sheet: dict, out: list[str]) -> Iterator[dict]:
        if self.llm.available():
            rules = (P.TRAINING_RULES if mode == "training" else P.CASE_RULES).format(language=P.LANGUAGE_NAMES[lang])
            system = "\n\n".join([P.COUNSELLOR_SYSTEM, rules, self._case_context(sheet)])
            history = [m for m in self.store.messages(cid) if m["content"].strip()]
            messages = [{"role": "system", "content": system}]
            messages += [{"role": m["role"], "content": m["content"]} for m in history[-10:]]
            try:
                for chunk in self.llm.stream_chat(messages):
                    chunk = FOREIGN_SCRIPT_RE.sub("", chunk)
                    if not "".join(out).strip():
                        chunk = chunk.lstrip(" !.,:;-–—\n")
                    if chunk:
                        out.append(chunk)
                        yield {"type": "token", "text": chunk}
                grounded = {d.translate(BN_TO_ASCII).replace(",", "") for d in DIGITS_RE.findall(system)}
                stated = [DIGITS_RE.search(a).group(0) for a in AMOUNT_RE.findall("".join(out))]
                if any(s.translate(BN_TO_ASCII).replace(",", "").rstrip(".") not in grounded for s in stated):
                    yield from self._typewriter("\n\n_Amounts change often: verify the current figure with the "
                                                "university or the official visa page._", out)
                return
            except Exception as error:
                log.warning("AI reply failed: %s", error)
                if out:
                    yield from self._typewriter("\n\n_(The AI reply was cut short. Please send the message again.)_", out)
                    return
        yield {"type": "notice", "text": "AI writing is offline right now; this answer comes from the case rules "
                                         "and past cases."}
        question = self.store.messages(cid)[-2]["content"] if len(self.store.messages(cid)) >= 2 else ""
        signature = f"{sheet['assessment']['verdict']}|{[i['id'] for i in sheet['assessment']['issues']]}|" \
                    f"{sorted((r['key'], r['value']) for r in sheet['profile'] if r['value'])}"
        answer = self.offline_followup(question, sheet)
        if answer is None:
            if state.get("offline_signature") == signature and mode == "case":
                answer = ("I can't answer that specific question while the AI writer is offline, and nothing new "
                          f"about the case has changed (still **{sheet['assessment']['verdict']}**). The case sheet "
                          "shows the full assessment; try this question again when the AI is back.\n\n" + P.OFFLINE_NOTE)
            else:
                answer = self.offline_answer(sheet, mode)
        state["offline_signature"] = signature
        yield from self._typewriter(answer, out)

    @staticmethod
    def offline_followup(question: str, sheet: dict) -> str | None:
        """Answer the follow-up buttons from the case rules alone."""
        rules = guidance([i["id"] for i in sheet["assessment"]["issues"]])
        q = question.strip()

        def section(title: str, field: str, n: int = 6) -> str:
            items: list[str] = []
            for g in rules:
                for item in g[field]:
                    if item not in items:
                        items.append(item)
            return f"**{title}**\n" + "\n".join(f"- {x}" for x in items[:n]) + "\n\n" + P.OFFLINE_NOTE

        if q == P.FOLLOW_UPS["documents"] and rules:
            return section("Documents to request", "documents")
        if q == P.FOLLOW_UPS["pathways"] and rules:
            return section("Possible pathways", "pathways")
        if q == P.FOLLOW_UPS["tell"] and rules:
            return "**What to tell the student**\n" + "\n".join(f"- {g['title']}: {g['tell']}" for g in rules) + \
                "\n\n" + P.OFFLINE_NOTE
        if q == P.FOLLOW_UPS["train"]:
            return ChatEngine.offline_answer(sheet, "training")
        if q == P.FOLLOW_UPS["missing"]:
            asks = [f"- {m}" for m in sheet["assessment"]["missing"]]
            for g in rules:
                asks += [f"- {x}" for x in g["ask"] if f"- {x}" not in asks]
            return "**Ask the student next**\n" + "\n".join(asks[:8]) + "\n\n" + P.OFFLINE_NOTE
        return None

    @staticmethod
    def offline_answer(sheet: dict, mode: str = "case") -> str:
        """A structured case answer built only from the case rules and past cases (no AI model)."""
        a = sheet["assessment"]
        known = ", ".join(f"{r['label'].lower()} {r['value']}" for r in sheet["profile"] if r["value"])
        parts = [f"**Assessment: {a['verdict']}.** {a['reason']}"]
        if known:
            parts.append(f"Case so far: {known}.")
        rules = guidance([i["id"] for i in a["issues"]])
        if rules:
            parts.append("**Main problem" + ("s" if len(rules) > 1 else "") + "**\n" +
                         "\n".join(f"- {g['title']}: {g['summary']}" for g in rules))

            def merged(field: str, n: int = 5) -> list[str]:
                seen: list[str] = []
                for g in rules[:2]:
                    for item in g[field]:
                        if item not in seen:
                            seen.append(item)
                return seen[:n]

            parts.append("**Check first**\n" + "\n".join(f"- {x}" for x in merged("check")))
            parts.append("**Ask the student**\n" + "\n".join(f"- {x}" for x in merged("ask")))
            parts.append("**Options**\n" + "\n".join(f"- {x}" for x in merged("pathways")))
            parts.append("**Documents to request**\n" + "\n".join(f"- {x}" for x in merged("documents", 4)))
            parts.append(f"**What to tell the student**\n{rules[0]['tell']}")
        else:
            parts.append("No specific problem found from what you have described so far.")
        if a["missing"]:
            parts.append("**Find out next**\n" + "\n".join(f"- {m}" for m in a["missing"][:6]))
        if sheet["similar"]:
            parts.append("**Similar past cases**\n" + "\n".join(f"- {c['title']}" for c in sheet["similar"]))
        if mode == "training":
            parts.append("**Training tip:** start every case by filling the missing details, then deal with blockers "
                         "(funds, English, results) before choosing universities.")
        parts.append(P.OFFLINE_NOTE)
        return "\n\n".join(parts)

    # ------------------------------------------------------------------ counsellor actions
    def update_profile(self, conversation_id: str, changes: dict, dismiss: list[str] | None = None,
                       restore: list[str] | None = None) -> dict:
        conv = self.store.get_conversation(conversation_id)
        state = conv["state"] or {}
        profile = state.setdefault("profile", {})
        for key, value in changes.items():
            if key not in EDITABLE:
                continue
            if value in (None, ""):
                profile.pop(key, None)
            else:
                profile[key] = value
        if "budget_band" in changes and changes["budget_band"]:
            profile.pop("budget_amount", None)
            profile.pop("budget_unit", None)
        # A detail the counsellor set by hand overrides problems read from their earlier wording; the
        # assessment re-derives the problem from the field itself when it still applies.
        overridden = {issue for key in changes for issue in FIELD_ISSUES.get(key, ())}
        state["mentioned"] = sorted(set(state.get("mentioned", [])) - overridden)
        dismissed = set(state.get("dismissed", [])) | set(dismiss or [])
        state["dismissed"] = sorted(dismissed - set(restore or []))
        sheet = self._refresh(state)
        self.store.update_conversation(conversation_id, state=state)
        return sheet

    def set_flag(self, conversation_id: str, flagged: bool, note: str | None = None) -> dict:
        conv = self.store.get_conversation(conversation_id)
        state = conv["state"] or {}
        state["flag"] = {"note": note or "", "at": time.time()} if flagged else None
        self.store.update_conversation(conversation_id, state=state)
        return {"flag": state["flag"]}
