"""Counsellor knowledge base and case assessment: the "virtual senior counsellor" rules.

A counsellor describes a student's situation in English, Banglish or Bengali. This module
1. reads the case details from the text (destination, level, results, English test, bank statement,
   study gap, visa history, dependants and more), on top of agent/extract.py;
2. detects known problem types, each with what to check, questions to ask the student, documents to
   request, possible pathways and how to explain it to the student;
3. gives an eligibility verdict with reasons and the information still missing.

The problem types come from the situations in the agency's 205 recorded counselling conversations
(bank not ready, visa refusal, study gap, low CGPA, dependants, field change, missed intake, pending
results, sponsor issues and so on). Thresholds are agency defaults, not official rules: every check
tells the counsellor to verify the specific course and the current immigration requirements.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date

from agent.extract import BN_DIGITS_TO_ASCII, COUNTRY_PATTERNS, extract

# ---------------------------------------------------------------------------- agency defaults
# Typical minimums used to flag possible problems. Edit to match the agency's own experience;
# they never replace checking the actual course page and the current visa rules.
DEFAULTS = {
    "ielts_min": {"Bachelor's": 6.0, "Master's": 6.5, "Foundation": 5.0, "Diploma": 5.5, "PhD": 6.5},
    "hsc_gpa_direct_entry": 3.5,      # out of 5: below this, check foundation or diploma routes
    "cgpa_master_min": 2.5,           # out of 4: below this, many master's programmes need a pathway
    "bank_hold_days": 28,             # e.g. the UK's 28-day funds rule
    "long_gap_years": 2,
    "expensive_countries": {"UK", "USA", "Australia", "Canada", "New Zealand"},  # as in SARP-Net features
}

LEVELS = ["Foundation", "Diploma", "Bachelor's", "Master's", "PhD"]
ENGLISH_TESTS = ["IELTS", "PTE", "TOEFL", "Duolingo", "MOI", "None yet"]
BANK_STATES = ["Ready", "Not ready", "Recent large deposit"]


def _rx(pattern: str) -> re.Pattern:
    return re.compile(unicodedata.normalize("NFC", pattern), re.I)


# ---------------------------------------------------------------------------- problem types
# severity: "blocker" = must be solved before applying; "risk" = can be handled, needs a plan;
#           "check" = information to verify.
ISSUES: dict[str, dict] = {
    "bank_not_ready": {
        "title": "Bank statement not ready",
        "severity": "blocker",
        "triggers": _rx(r"bank\s*statement.{0,40}(not|isn'?t|hoy\s*nai|hoyni|ready\s*na|mature|28|matured)|"
                        r"(not|didn'?t).{0,15}(complete|finish|mature).{0,15}28|28\s*(days|din|দিন)|"
                        r"funds?\s*(not|isn'?t)\s*(ready|enough)|ব্যাংক\s*স্টেটমেন্ট"),
        "summary": "The student's funds have not been held long enough, or are not yet in the account.",
        "check": ["The holding period the visa route needs (for example 28 days for the UK) and when it completes",
                  "The application, deposit and visa deadlines for the intended intake",
                  "Whether the university or visa route accepts other evidence (education loan letter, sponsor letter, FDR)"],
        "ask": ["On what date were the funds deposited, and is the balance stable?",
                "Who is the sponsor, and how is the money related to their income?",
                "Which intake are you aiming for, and how flexible is that?"],
        "documents": ["Latest bank statement and the deposit history", "Sponsor's income proof and relationship document",
                      "Education loan sanction letter, if any"],
        "pathways": ["Wait until the holding period is complete, if the deadlines still allow",
                     "Move to the next intake so the funds can mature",
                     "Use other accepted financial evidence, if the university and visa route allow it",
                     "Look at a lower-cost destination or university where the required amount is smaller"],
        "tell": "Explain that the application can continue, but the visa needs funds held for the full period; "
                "give the date it completes and the intake that fits.",
        "scenarios": ["Bank Not Ready", "Bank Preparation", "Recent Large Deposit", "Financial Sponsor"],
    },
    "funding_gap": {
        "title": "Budget may not cover the full cost",
        "severity": "risk",
        "triggers": _rx(r"(budget|fund|taka|money).{0,30}(kom|low|short|not\s*enough|insufficient|cover)|"
                        r"part[\s-]*time.{0,30}(tuition|fee|pay|fund)|loan|sponsor.{0,20}(not|uncertain)|"
                        r"can'?t\s*afford|afford\s*kor"),
        "summary": "The student's budget may not cover tuition, living costs and the funds the visa requires.",
        "check": ["Full first-year cost: tuition after any scholarship, living costs, visa and insurance",
                  "The amount the visa requires to be shown",
                  "Whether part-time work is realistic (it should not be counted as tuition money)"],
        "ask": ["What is the confirmed budget per year, and who is paying?",
                "Is any part of it a loan, and is it already sanctioned?",
                "Would a lower-cost country or university be acceptable?"],
        "documents": ["Sponsor's income and asset proof", "Bank statements", "Loan documents, if any"],
        "pathways": ["Lower-cost destinations such as Malaysia or partner pathways with a later transfer",
                     "Universities with tuition discounts or confirmed partial scholarships",
                     "A foundation or diploma first, which costs less per year"],
        "tell": "Show the full cost clearly; do not plan on part-time income to pay tuition.",
        "scenarios": ["Funding the Degree Through Part-Time Work", "Education Loan", "Budget", "Lower-Cost Alternative"],
    },
    "english_low": {
        "title": "English score below the usual requirement",
        "severity": "blocker",
        "triggers": _rx(r"(ielts|pte|toefl|duolingo).{0,30}(low|kom|below|not\s*enough|one\s*band|band\s*below)|"
                        r"one\s*band\s*(does\s*not|is\s*low)"),
        "summary": "The student's English result is below what the course usually requires.",
        "check": ["The exact overall and per-band requirement of the course", "Whether the university offers a pre-sessional English course",
                  "Whether the visa route accepts the test the student has"],
        "ask": ["What are your overall and band scores, and when was the test taken?",
                "Can you retake the test before the deadline?"],
        "documents": ["Test report form"],
        "pathways": ["Retake the test before the application deadline",
                     "A pre-sessional English course with a conditional offer",
                     "A foundation or pathway programme with built-in English"],
        "tell": "Explain which band falls short and the fastest route: retake or a pre-sessional course.",
        "scenarios": ["One Band Does Not", "IELTS Result Will Arrive After the Deadline", "Old English Test"],
    },
    "english_missing": {
        "title": "No English test yet",
        "severity": "risk",
        "triggers": _rx(r"(no|without|chara|nai|nei|হয়নি)\s*(ielts|english\s*test|pte)|(ielts|pte)\s*(chara|nai|nei|dey\s*nai|hoy\s*nai)|"
                        r"moi|medium\s*of\s*instruction"),
        "summary": "There is no valid English test result yet.",
        "check": ["Whether the course accepts a medium-of-instruction (MOI) letter or the university's own test",
                  "Whether the visa route needs a specific test", "Test dates available before the deadline"],
        "ask": ["Was your previous study taught in English, and can the institution issue an MOI letter?",
                "When can you sit a test?"],
        "documents": ["MOI letter from the previous institution, if available"],
        "pathways": ["Book a test now and apply once results arrive",
                     "Universities that accept MOI or their own English test (check visa rules too)",
                     "A foundation or pathway programme with English included"],
        "tell": "Tell the student which test to book and the latest date the result must be ready.",
        "scenarios": ["Old English Test", "English-medium", "IELTS Result Will Arrive"],
    },
    "academic_below": {
        "title": "Results below direct-entry requirement",
        "severity": "risk",
        "triggers": _rx(r"(gpa|cgpa|result).{0,30}(low|kom|below|not\s*enough|meet\s*kore\s*na)|"
                        r"(not|doesn'?t)\s*meet.{0,20}(entry|requirement)|direct\s*entry.{0,20}(not|na|nai)|repeated\s*courses|backlog"),
        "summary": "The student's results may not meet the course's direct-entry requirement.",
        "check": ["The exact entry requirement and how the university converts Bangladeshi grades",
                  "Whether work experience or a portfolio can be considered",
                  "Foundation, diploma or pre-master's pathways and their progression conditions"],
        "ask": ["What are your SSC and HSC (or CGPA) results, and in which group?",
                "Do you have relevant work experience or a portfolio?"],
        "documents": ["Transcripts and certificates", "Work experience letters, if any"],
        "pathways": ["Foundation programme leading to the bachelor's",
                     "Diploma with progression into year 2 of a bachelor's",
                     "Pre-master's or a university with a lower entry requirement",
                     "A related course whose requirement the student meets"],
        "tell": "Explain that direct entry is unlikely but a pathway exists, with the extra time and cost it adds.",
        "scenarios": ["Low CGPA", "Weak Academic Grades", "Diploma Holder Seeking Direct Bachelor's Entry"],
    },
    "study_gap": {
        "title": "Study gap to explain",
        "severity": "risk",
        "triggers": _rx(r"(study|education)?\s*gap|\d+\s*(year|years|bochor|বছর)\w*\s*(er\s*)?gap|long\s*break|বিরতি"),
        "summary": "There is a gap since the last qualification that the university and visa officer will ask about.",
        "check": ["How long the gap is and what the student did during it",
                  "The university's policy on gaps for this level",
                  "Whether the activities in the gap support the chosen course (genuine student assessment)"],
        "ask": ["What have you been doing since your last qualification?",
                "Do you have proof: job letters, payslips, training certificates?",
                "Why this course now, and how does it connect to your plans?"],
        "documents": ["Employment letters and payslips", "Training or course certificates", "A gap explanation in the statement of purpose"],
        "pathways": ["Apply with a clear, documented gap explanation",
                     "Choose a course that builds on the work done during the gap",
                     "Consider universities known to accept mature applicants"],
        "tell": "Help the student prepare an honest, evidence-backed explanation of the gap.",
        "scenarios": ["Long Study Gap", "Older Than Classmates", "Family Business Experience"],
    },
    "visa_refusal": {
        "title": "Previous visa refusal",
        "severity": "risk",
        "triggers": _rx(r"refus|reject|refuse\s*hoy|denied|রিফিউজ|প্রত্যাখ্যান"),
        "summary": "A previous visa refusal must be declared and the reasons addressed.",
        "check": ["The refusal letter and the exact reasons given", "What has genuinely changed since then",
                  "That every new application declares the refusal honestly"],
        "ask": ["When and for which country was the visa refused?", "Do you have the refusal letter and the full previous application?",
                "What has changed: finances, study plan, documents?"],
        "documents": ["Refusal letter", "Copy of the previous application", "New evidence addressing each refusal reason"],
        "pathways": ["Reapply after fixing each refusal reason with new evidence",
                     "Choose a course that clearly fits the student's background",
                     "Consider another destination, declaring the refusal where asked"],
        "tell": "Be clear that hiding a refusal can lead to a ban; the case is about evidence, not a new college.",
        "scenarios": ["Previous Visa Refusal", "Deposit Refund After Visa Refusal", "Changing Colleges After a Study Permit"],
    },
    "dependants": {
        "title": "Dependants want to come",
        "severity": "check",
        "triggers": _rx(r"\b(wife|husband|spouse|partner|child|children|kid|baby|dependant|dependent|bou|bachcha)\b|স্ত্রী|স্বামী|সন্তান|বাচ্চা"),
        "summary": "The student wants to bring a spouse or children.",
        "check": ["Whether this course level and destination allow dependants (rules differ and change)",
                  "Extra funds the visa needs for each dependant", "Accommodation, schooling and healthcare costs"],
        "ask": ["Who exactly will come, and when?", "Is the extra budget for dependants confirmed?"],
        "documents": ["Marriage certificate", "Children's birth certificates", "Additional funds evidence"],
        "pathways": ["Choose a course and country where dependants are currently allowed",
                     "Student travels first; family joins later if the rules allow",
                     "Research or longer programmes, only if they genuinely fit the student's goals"],
        "tell": "Never change the course just for dependant rules; confirm current rules before any payment.",
        "scenarios": ["Taking a Partner Along", "Spouse Can Accompany", "Partner Supports the Plan"],
    },
    "field_change": {
        "title": "Changing academic field",
        "severity": "check",
        "triggers": _rx(r"(change|switch|shift).{0,25}(field|subject|major|course|career)|different\s*(field|background|subject)|"
                        r"from\s+\w+\s+to\s+\w+|career\s*change|অন্য\s*বিষয়"),
        "summary": "The new course is in a different field from the student's previous study.",
        "check": ["Whether the course accepts applicants from other backgrounds and any prerequisite subjects",
                  "How the change connects to the student's work or career goal (for the visa assessment)"],
        "ask": ["Why do you want to change field?", "Any work, training or projects in the new field?"],
        "documents": ["Statement of purpose explaining the change", "Evidence of related experience"],
        "pathways": ["Conversion master's or programmes designed for career changers",
                     "A related course that bridges both fields",
                     "A short preparatory course before applying"],
        "tell": "Help the student explain the change convincingly with evidence.",
        "scenarios": ["Changing from Engineering to Business", "Career Change into Nursing", "Changed Their Preferred Subject",
                      "Cannot Explain Their Course Choice"],
    },
    "missed_intake": {
        "title": "Intake missed or timeline too tight",
        "severity": "risk",
        "triggers": _rx(r"miss(ed)?\s*(the\s*)?(\w+\s*)?intake|deadline\s*(is\s*)?(passed|over|close|chole\s*geche)|"
                        r"intake\s*(is\s*)?(closed|over)|too\s*late|course\s*start.{0,20}(soon|approaching)|visa\s*pending"),
        "summary": "The intended intake has passed or the remaining time may not be enough.",
        "check": ["Application, offer acceptance, deposit and visa deadlines for this intake",
                  "Typical visa processing time for the destination", "Next available intakes and late-arrival policy"],
        "ask": ["Which intake did you plan for, and what stage is the application at?", "Is a later intake acceptable?"],
        "documents": ["Offer letter and any deadline emails"],
        "pathways": ["Next intake at the same university", "Universities with a later deadline for the same intake",
                     "A deferral request, if an offer already exists"],
        "tell": "Give a realistic timeline and get written confirmation before any non-refundable payment.",
        "scenarios": ["January Intake to April Intake", "Course Start Date Approaching", "Pressured by an Application Deadline",
                      "Change Their Intake"],
    },
    "documents_pending": {
        "title": "Documents pending or inconsistent",
        "severity": "check",
        "triggers": _rx(r"(result|certificate|transcript).{0,30}(pending|not\s*(out|published|issued)|ase\s*nai)|"
                        r"before\s*(the\s*)?final\s*result|mismatch|spelling|name\s*(is\s*)?different|wrong\s*file"),
        "summary": "A document is missing, pending, or does not match other documents.",
        "check": ["Whether the university accepts a provisional certificate or results letter",
                  "That names and dates match the passport across all documents",
                  "Only the issuing authority can correct a document"],
        "ask": ["Which document is missing or different, and when will it be issued or corrected?"],
        "documents": ["Provisional certificate or results letter", "Passport", "Correction application or affidavit, if needed"],
        "pathways": ["Apply for a conditional offer now and submit the final document later",
                     "Start the official correction with the board or institution early"],
        "tell": "Never edit a document; explain the official correction route and timing.",
        "scenarios": ["Document Mismatch", "Before Final Results", "Final Certificate Is Pending", "Official Transcript",
                      "Different Name Format"],
    },
    "under_18": {
        "title": "Student under 18 at start",
        "severity": "check",
        "triggers": _rx(r"under\s*18|1[5-7]\s*(years?\s*old|bochor)"),
        "summary": "The student will be under 18 when the course starts.",
        "check": ["University's under-18 policy, guardian and accommodation rules", "Visa requirements for minors"],
        "ask": ["When do you turn 18?", "Is there an approved guardian or relative in the destination?"],
        "documents": ["Parental consent", "Guardian details, if needed"],
        "pathways": ["Start at a university that supports under-18 students", "Start at a later intake after turning 18"],
        "tell": "Involve the parents and confirm welfare arrangements before paying.",
        "scenarios": ["Under-18 Student"],
    },
    "pr_motive": {
        "title": "Course chosen mainly for migration",
        "severity": "check",
        "triggers": _rx(r"\bPR\b|permanent\s*residen|settle|immigrat"),
        "summary": "The student is choosing the course mainly for permanent residency.",
        "check": ["Whether the course fits the student's background and career plan (genuine student assessment)"],
        "ask": ["What career do you want after the course, and how does this course lead there?"],
        "documents": ["Statement of purpose"],
        "pathways": ["Choose a course with a clear link to the student's study and career history"],
        "tell": "Be clear that no course guarantees PR, and visa officers check that the plan is genuine.",
        "scenarios": ["Course Only for Permanent Residency", "Post-Study Work", "Credibility Interview"],
    },
    "scholarship_expectation": {
        "title": "Unrealistic scholarship expectation",
        "severity": "check",
        "triggers": _rx(r"full\s*scholarship|100\s*%\s*scholarship|fully\s*funded|free\s*(study|tuition)"),
        "summary": "The student expects a full scholarship, which is rare for most courses.",
        "check": ["Actual scholarships offered for this course, their value and conditions"],
        "ask": ["What budget is possible if only a partial scholarship is offered?"],
        "documents": ["Results and achievements for scholarship applications"],
        "pathways": ["Apply for partial merit scholarships and plan the remaining cost",
                     "Lower-cost destinations where the remaining cost is manageable"],
        "tell": "Set expectations early: plan the budget assuming a partial scholarship.",
        "scenarios": ["Full Scholarship Expectations", "Conditional Scholarship"],
    },
}


# ---------------------------------------------------------------------------- reading case details
LEVEL_PATTERNS = [
    ("PhD", _rx(r"\bph\.?d\b|doctor(ate|al)")),
    ("Master's", _rx(r"master'?s?|\bmsc\b|\bmba\b|\bma\b|post\s*grad|\bpg\b|মাস্টার্স")),
    ("Foundation", _rx(r"foundation")),
    ("Diploma", _rx(r"\bdiploma\b|ডিপ্লোমা")),
    ("Bachelor's", _rx(r"bachelor'?s?|undergrad|\bbsc\b|\bbba\b|honou?rs|ব্যাচেলর|স্নাতক")),
]
ENGLISH_RE = _rx(r"\b(ielts|pte|toefl|duolingo)\b\D{0,12}(\d{1,3}(?:\.\d)?)")
NO_ENGLISH_RE = ISSUES["english_missing"]["triggers"]
PASS_YEAR_RE = _rx(r"\b(hsc|ssc|a\s*level|bachelor'?s?|graduat\w*|pass(ed)?|এইচএসসি)\b\D{0,15}((?:19|20)\d{2})")
GAP_YEARS_RE = _rx(r"(\d{1,2})\s*[- ]?\s*(?:year|years|yr|yrs|bochor|বছর)\w*\s*(?:er\s*)?(?:study\s*|education\s*)?gap|"
                   r"gap\s*(?:of\s*)?(\d{1,2})\s*(?:year|yr|bochor)")
BANK_DAYS_RE = _rx(r"(\d{1,2})\s*(?:days?|din|দিন)\b")
AGE_RE = _rx(r"\b(\d{2})\s*(?:years?\s*old|yo\b|bochor\s*boy)")


NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
                "ten": 10, "ek": 1, "dui": 2, "tin": 3, "char": 4, "pach": 5, "এক": 1, "দুই": 2, "তিন": 3, "চার": 4, "পাঁচ": 5}
NUMBER_WORD_RE = re.compile(r"\b(" + "|".join(NUMBER_WORDS) + r")\b(?=\s*[- ]?\s*(?:year|yr|bochor|বছর))", re.I)


# A country named only as the place of an earlier refusal ("had a UK visa refusal", "refused by Canada")
# is history, not the destination.
REFUSAL_AFTER_RE = re.compile(r"^\W{0,3}(?:\w+\s+){0,2}?(?:student\s+)?(?:visa|refus|reject|denied|রিফিউজ|ভিসা)", re.I)
REFUSAL_BEFORE_RE = re.compile(r"(?:refus\w*|reject\w*|denied|refuse\s*hoy\w*)\s+(?:by|from|in|for)\s+(?:the\s+)?$", re.I)


def _destination(text: str) -> tuple[str | None, str | None]:
    """(destination, refusal country) from all country mentions, skipping those that only describe a refusal."""
    destination, refused = None, None
    for name, patterns in COUNTRY_PATTERNS.items():
        for pattern in patterns:
            for m in pattern.finditer(text):
                after, before = text[m.end():m.end() + 40], text[max(0, m.start() - 30):m.start()]
                if REFUSAL_AFTER_RE.search(after) and re.search(r"refus|reject|denied|রিফিউজ", after, re.I)                         or REFUSAL_BEFORE_RE.search(before):
                    refused = refused or name
                elif destination is None or m.start() < destination[0]:
                    destination = (m.start(), name)
    return (destination[1] if destination else None), refused


def read_case(text: str, today: date | None = None) -> tuple[dict, set[str]]:
    """(profile updates, problem types mentioned) from a counsellor's message."""
    today = today or date.today()
    clean = unicodedata.normalize("NFC", text or "").translate(BN_DIGITS_TO_ASCII)
    clean = NUMBER_WORD_RE.sub(lambda m: str(NUMBER_WORDS[m.group(1).lower()]), clean)  # "three-year" -> "3-year"
    updates, _ = extract(clean, None, today)
    for level, pattern in LEVEL_PATTERNS:
        if pattern.search(clean):
            updates["level"] = level
            break
    if "level" not in updates and re.search(r"\bhsc\b|এইচএসসি|a\s*level", clean, re.I):
        updates["level"] = "Bachelor's"  # an HSC student usually applies for a bachelor's
    m = ENGLISH_RE.search(clean)
    if m:
        updates["english_test"], updates["english_score"] = m.group(1).upper().replace("DUOLINGO", "Duolingo"), float(m.group(2))
    elif NO_ENGLISH_RE.search(clean):
        updates["english_test"] = "MOI" if re.search(r"moi|medium\s*of\s*instruction", clean, re.I) else "None yet"
    m = PASS_YEAR_RE.search(clean)
    if m:
        updates["pass_year"] = int(m.group(3))
    m = GAP_YEARS_RE.search(clean)
    if m:
        updates["gap_years"] = int(m.group(1) or m.group(2))
    if ISSUES["visa_refusal"]["triggers"].search(clean):
        updates["visa_refusal"] = True
        destination, refused = _destination(clean)
        if refused:
            updates["refusal_country"] = refused
            if destination:
                updates["country"] = destination
            else:
                updates.pop("country", None)
    if ISSUES["dependants"]["triggers"].search(clean):
        updates["dependants"] = True
    if ISSUES["bank_not_ready"]["triggers"].search(clean):
        updates["bank_status"] = "Not ready"
        days = [int(d) for d in BANK_DAYS_RE.findall(clean) if int(d) != DEFAULTS["bank_hold_days"]]
        if days:
            updates["bank_days"] = days[0]
    elif re.search(r"recent\s*(large\s*)?deposit|just\s*deposited", clean, re.I):
        updates["bank_status"] = "Recent large deposit"
    m = AGE_RE.search(clean)
    if m:
        updates["age"] = int(m.group(1))
    mentioned = {key for key, issue in ISSUES.items() if issue["triggers"].search(clean)}
    return updates, mentioned


# ---------------------------------------------------------------------------- assessment
def _status(state: str, label: str, note: str) -> dict:
    return {"area": label, "state": state, "note": note}


def assess(profile: dict, mentioned: set[str], today: date | None = None) -> dict:
    """Eligibility verdict, area checks, active problems and missing information for a case."""
    today = today or date.today()
    p, active = profile, set(mentioned)
    checks: list[dict] = []
    level = p.get("level")

    # Academic
    gpa, scale = p.get("gpa"), p.get("gpa_scale") or (5.0 if (p.get("gpa") or 0) > 4 else 4.0)
    if gpa is None:
        checks.append(_status("unknown", "Academic", "Latest result not given"))
    elif scale == 5 and level in (None, "Bachelor's") and gpa < DEFAULTS["hsc_gpa_direct_entry"]:
        active.add("academic_below")
        checks.append(_status("issue", "Academic", f"HSC GPA {gpa:g}/5 is below the usual direct-entry level "
                                                   f"({DEFAULTS['hsc_gpa_direct_entry']}); check foundation or diploma"))
    elif scale == 4 and level == "Master's" and gpa < DEFAULTS["cgpa_master_min"]:
        active.add("academic_below")
        checks.append(_status("issue", "Academic", f"CGPA {gpa:g}/4 is below the usual master's minimum "
                                                   f"({DEFAULTS['cgpa_master_min']}); check pre-master's"))
    else:
        checks.append(_status("ok", "Academic", f"Result {gpa:g}/{scale:g}; confirm the course requirement"))

    # English
    test, score = p.get("english_test"), p.get("english_score")
    if test == "IELTS" and score is not None:
        need = DEFAULTS["ielts_min"].get(level or "Bachelor's", 6.0)
        if score < need:
            active.add("english_low")
            checks.append(_status("issue", "English", f"IELTS {score:g} is below the usual {need:g} for {level or 'this level'}"))
        else:
            checks.append(_status("ok", "English", f"IELTS {score:g}; check per-band requirements"))
    elif test in ("PTE", "TOEFL", "Duolingo") and score is not None:
        checks.append(_status("ok", "English", f"{test} {score:g}; confirm the university and visa route accept it"))
    elif test in ("MOI", "None yet"):
        active.add("english_missing")
        checks.append(_status("issue", "English", "No test yet" if test == "None yet" else "MOI letter only; check acceptance"))
    else:
        checks.append(_status("unknown", "English", "English test not given"))

    # Finance
    band, country = p.get("budget_band"), p.get("country")
    usd = None
    if p.get("budget_amount") is not None:
        amount, unit = float(p["budget_amount"]), p.get("budget_unit")
        usd = amount * 100_000 / 122 if unit == "lakh_taka" or (unit is None and amount < 1000) else \
            amount / 122 if unit == "taka" else amount
    low_budget = band == "Below 10k" or (usd is not None and usd < 10_000)
    if band is None and usd is None:
        checks.append(_status("unknown", "Finance", "Budget not given"))
    elif low_budget and country in DEFAULTS["expensive_countries"]:
        active.add("funding_gap")
        checks.append(_status("issue", "Finance", f"Budget under about $10k a year for {country}: high financial strain"))
    else:
        checks.append(_status("ok", "Finance", "Budget given; check it covers tuition, living costs and visa funds"))

    # Bank statement
    bank = p.get("bank_status")
    if bank == "Not ready":
        active.add("bank_not_ready")
        days = p.get("bank_days")
        note = f"Funds held {days} days so far" if days is not None else "Funds not yet held for the required period"
        checks.append(_status("issue", "Bank statement", note))
    elif bank == "Recent large deposit":
        active.add("bank_not_ready")
        checks.append(_status("issue", "Bank statement", "Recent large deposit: source of funds must be explained"))
    elif bank == "Ready":
        checks.append(_status("ok", "Bank statement", "Ready; confirm the amount and holding period"))
    else:
        checks.append(_status("unknown", "Bank statement", "Bank statement status not given"))

    # Study gap
    gap = p.get("gap_years")
    if gap is None and p.get("pass_year"):
        gap = max(0, today.year - int(p["pass_year"]) - 1)
    if gap is not None and gap >= DEFAULTS["long_gap_years"]:
        active.add("study_gap")
        checks.append(_status("issue", "Study gap", f"About {gap} years since the last qualification"))
    elif gap is not None:
        checks.append(_status("ok", "Study gap", "No significant gap"))

    # Visa history and dependants
    if p.get("visa_refusal"):
        active.add("visa_refusal")
        checks.append(_status("issue", "Visa history", "Previous refusal must be declared and addressed"))
    if p.get("dependants"):
        active.add("dependants")
        checks.append(_status("issue", "Dependants", "Check whether dependants are allowed for this course and country"))
    if p.get("age") is not None and p["age"] < 18:
        active.add("under_18")

    # Intake timing
    intake = p.get("intake")
    if intake and re.match(r"^\d{4}-\d{2}", str(intake)):
        start = date(int(intake[:4]), int(intake[5:7]), 1)
        days_left = (start - today).days
        if days_left < 0:
            active.add("missed_intake")
            checks.append(_status("issue", "Intake", f"{start:%B %Y} has already started"))
        elif days_left < 90:
            active.add("missed_intake")
            checks.append(_status("issue", "Intake", f"{start:%B %Y} is about {days_left // 7} weeks away: tight for visa"))
        else:
            checks.append(_status("ok", "Intake", f"{start:%B %Y}; check the application deadline"))
    else:
        checks.append(_status("unknown", "Intake", "Intake not given"))

    issues = [{"id": k, **{f: ISSUES[k][f] for f in ("title", "severity", "summary")}}
              for k in sorted(active, key=lambda k: ("blocker", "risk", "check").index(ISSUES[k]["severity"]))]

    missing = []
    for field, label in (("country", "Destination country"), ("level", "Study level"), ("gpa", "Latest result (GPA and scale)"),
                         ("english_test", "English test and score"), ("budget", "Yearly budget and sponsor"),
                         ("bank_status", "Bank statement status"), ("intake", "Intended intake")):
        have = p.get(field) if field != "budget" else (p.get("budget_band") or p.get("budget_amount"))
        if not have:
            missing.append(label)

    severities = {i["severity"] for i in issues}
    known = 7 - len(missing)
    if "blocker" in severities and p.get("country"):
        verdict, reason = "Not yet eligible", "At least one requirement is not met yet; see the pathways to fix it."
    elif known < 4:
        verdict, reason = "Need more information", "Too few details to judge eligibility yet; see the missing information."
    elif "blocker" in severities:
        verdict, reason = "Not yet eligible", "At least one requirement is not met yet; see the pathways to fix it."
    elif "risk" in severities:
        verdict, reason = "Potentially eligible", "Eligible if the problems below are handled and verified."
    elif missing:
        verdict, reason = "Potentially eligible", "No problems found so far, but some details are still missing."
    else:
        verdict, reason = "Likely eligible", "No problems found; verify the exact course and visa requirements."
    return {"verdict": verdict, "reason": reason, "checks": checks, "issues": issues, "missing": missing}


def guidance(issue_ids: list[str]) -> list[dict]:
    """Full knowledge-base entries for the given problem types, in order."""
    return [{"id": k, **{f: v for f, v in ISSUES[k].items() if f != "triggers"}} for k in issue_ids if k in ISSUES]
