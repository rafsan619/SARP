"""Everything the agent says that is not written by the language model, in English, Banglish and Bengali.

Also holds the system prompt (identical to the one used for fine-tuning in data_prep) and the rules the
model follows in every reply.
"""
from __future__ import annotations

import random
from datetime import date

# Must match SYSTEM_PROMPT in data_prep/parse_conversations.py so the fine-tuned model sees the same prompt.
SYSTEM_PROMPT = (
    "You are SARP-Agent, a study-abroad counsellor at a Bangladeshi education agency. "
    "You help students plan study in the UK, Canada, Australia, New Zealand, Malaysia and other destinations. "
    "Reply in the same language style the student uses (Bengali, Banglish or English). "
    "Ask for missing details before advising, be honest about requirements, costs and risks, "
    "never promise admission or a visa, never help falsify documents, and suggest a human counsellor "
    "when a decision needs official confirmation."
)

LANGUAGE_NAMES = {
    "english": "English",
    "banglish": "Banglish (Bengali written in English letters, mixed with English words, the way Bangladeshi "
                "students text). Do not use Bengali script",
    "bengali": "Bengali in Bangla script only (English words for course, visa or university names are fine). "
               "Never use Hindi, Tamil or any other script",
}

REPLY_RULES = """Rules for this reply:
- Write in {language}.
- Start with the direct answer to the student's question. Be warm, clear and brief: under 120 words unless the student asks for detail. Use a short list for documents or steps.
- Do not ask the student any questions; the app asks its own follow-up questions after your reply.
- Only give exact fees, scores, amounts or visa rules if they appear in the facts or counsellor examples below; otherwise give general guidance and say a counsellor will confirm current figures.
- Refer the student to "your counsellor" for confirmation (not customer service or anyone else).
- Never mention risk, scores, probabilities, predictions, models, data or politics to the student.
- Never help change, edit or fake documents; explain the official correction route instead.
- Do not repeat questions about details you already know (listed below)."""

CONVERSATION_ORDER = ["country", "intake", "budget", "gpa", "due_diligence"]

QUESTIONS = {
    "country": {
        "english": "Which country are you hoping to study in, and what subject?",
        "banglish": "Apni kon desh-e porte jete chan, ar kon subject niye?",
        "bengali": "আপনি কোন দেশে পড়তে যেতে চান, আর কোন বিষয়ে?",
    },
    "intake": {
        "english": "Which intake are you aiming for?",
        "banglish": "Apni kon intake-e jete chacchen?",
        "bengali": "আপনি কোন ইনটেকে যেতে চাচ্ছেন?",
    },
    "budget": {
        "english": "Roughly what is your total yearly budget for tuition and living costs?",
        "banglish": "Tuition ar living cost miliye apnar bochore mot budget koto hote pare?",
        "bengali": "টিউশন আর থাকা-খাওয়া মিলিয়ে আপনার বছরে মোট বাজেট কত হতে পারে?",
    },
    "gpa": {
        "english": "What is your latest result? A CGPA out of 4 or an HSC GPA out of 5 is fine.",
        "banglish": "Apnar latest result koto? CGPA (4-er moddhe) ba HSC GPA (5-er moddhe) bolle hobe.",
        "bengali": "আপনার সর্বশেষ রেজাল্ট কত? সিজিপিএ (৪-এর মধ্যে) বা এইচএসসি জিপিএ (৫-এর মধ্যে) বললেই হবে।",
    },
    "due_diligence": {
        "english": "How much have you looked into your options so far?",
        "banglish": "Ekhon porjonto course ar university niye apni koto ta khoj niyechen?",
        "bengali": "এখন পর্যন্ত কোর্স আর ইউনিভার্সিটি নিয়ে আপনি কতটা খোঁজ নিয়েছেন?",
    },
}

SKIP_LABEL = {"english": "Skip for now", "banglish": "Pore bolbo", "bengali": "পরে বলব"}

COUNTRY_CHIPS = ["UK", "Canada", "Australia", "Malaysia", "New Zealand", "USA", "Germany", "Ireland"]
COUNTRY_BN = {"UK": "যুক্তরাজ্য", "Canada": "কানাডা", "Australia": "অস্ট্রেলিয়া", "Malaysia": "মালয়েশিয়া",
              "New Zealand": "নিউজিল্যান্ড", "USA": "যুক্তরাষ্ট্র", "Germany": "জার্মানি", "Ireland": "আয়ারল্যান্ড"}

DUE_DILIGENCE_CHIPS = {
    "english": ["Not yet", "I know the country and subject", "I've shortlisted courses or universities",
                "I know the requirements, costs and visa steps"],
    "banglish": ["Ekhono kichu dekhini", "Desh ar subject thik korechi", "Kichu course/university shortlist korechi",
                 "Requirements, khoroch ar visa process jani"],
    "bengali": ["এখনো কিছু দেখিনি", "দেশ আর বিষয় ঠিক করেছি", "কিছু কোর্স/ইউনিভার্সিটি শর্টলিস্ট করেছি",
                "রিকোয়ারমেন্ট, খরচ আর ভিসার ধাপ জানি"],
}
DUE_DILIGENCE_VALUES = ["No", "Yes Low", "Yes Medium", "Yes High"]
RESEARCH_LABELS = {
    "No": {"english": "Just starting", "banglish": "Shobe shuru", "bengali": "সবে শুরু"},
    "Yes Low": {"english": "Country and subject chosen", "banglish": "Desh ar subject thik",
                "bengali": "দেশ ও বিষয় ঠিক"},
    "Yes Medium": {"english": "Options shortlisted", "banglish": "Shortlist kora", "bengali": "শর্টলিস্ট করা"},
    "Yes High": {"english": "Well researched", "banglish": "Bhalo moto research kora", "bengali": "ভালোভাবে খোঁজ নেওয়া"},
}

MONTHS_EN = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
             "November", "December"]
MONTHS_BN = ["জানুয়ারি", "ফেব্রুয়ারি", "মার্চ", "এপ্রিল", "মে", "জুন", "জুলাই", "আগস্ট", "সেপ্টেম্বর", "অক্টোবর",
             "নভেম্বর", "ডিসেম্বর"]
BN_DIGITS = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")
NOT_DECIDED = {"english": "Not decided yet", "banglish": "Ekhono thik kori nai", "bengali": "এখনো ঠিক করিনি"}

ACKS = {
    "english": ["Got it, thanks.", "Thanks, noted.", "Great, that helps."],
    "banglish": ["Thik ache, note korlam.", "Dhonnobad, bujhte perechi.", "Accha, bhalo."],
    "bengali": ["ঠিক আছে, লিখে রাখলাম।", "ধন্যবাদ, বুঝতে পেরেছি।", "আচ্ছা, ভালো।"],
}
GREETING_REPLY = {
    "english": "Hello! I'm SARP-Agent. I can help you choose a country and course, plan your budget, and "
               "understand the application and visa steps.",
    "banglish": "Assalamu Alaikum! Ami SARP-Agent. Desh ar course choose kora, budget plan kora, ar application "
                "o visa-r step bujhte ami apnake help korte pari.",
    "bengali": "আসসালামু আলাইকুম! আমি SARP-Agent। দেশ ও কোর্স বাছাই, বাজেট পরিকল্পনা আর আবেদন ও ভিসার ধাপ বুঝতে "
               "আমি আপনাকে সাহায্য করতে পারি।",
}
GENERAL_REPLY = {
    "english": "I can help you choose a country and course, plan your budget, and understand documents and visa "
               "steps. A counsellor will confirm exact fees and visa rules.",
    "banglish": "Ami desh ar course choose kora, budget plan, documents ar visa-r step niye help korte pari. "
                "Exact fee ar visa rules counsellor confirm kore diben.",
    "bengali": "দেশ ও কোর্স বাছাই, বাজেট, ডকুমেন্ট আর ভিসার ধাপ নিয়ে আমি সাহায্য করতে পারি। সঠিক ফি আর ভিসার "
               "নিয়ম কাউন্সেলর নিশ্চিত করে দেবেন।",
}
RETRIEVED_PREFIX = {
    "english": "Here is how our counsellors usually answer this:",
    "banglish": "Amader counsellor-ra sadharonoto eta erokom bhabe bolen:",
    "bengali": "আমাদের কাউন্সেলররা সাধারণত এভাবে উত্তর দেন:",
}
# ---- The plan message, shared once all five details are known. It recaps, gives next steps for where the
# student is, and invites them to keep going; it never sounds like the end of the conversation.
PLAN_SUMMARY = {
    "english": "Your plan is taking shape: {summary}.",
    "banglish": "Apnar plan toiri hocche: {summary}.",
    "bengali": "আপনার পরিকল্পনা তৈরি হচ্ছে: {summary}।",
}
SUMMARY_PARTS = {  # how each known detail reads inside the summary line
    "intake": {"english": "{v} intake", "banglish": "{v} intake", "bengali": "{v} ইনটেক"},
    "budget": {"english": "budget {v}", "banglish": "budget {v}", "bengali": "বাজেট {v}"},
    "gpa": {"english": "result {v}", "banglish": "result {v}", "bengali": "রেজাল্ট {v}"},
}
NEXT_STEPS_INTRO = {
    "english": "Here's what I'd do next:",
    "banglish": "Ami next e egulo korte boli:",
    "bengali": "এরপর আমি এগুলো করতে বলব:",
}
RESEARCH_STEP = {  # the next step from the student's current research level
    "No": {
        "english": "Choose a subject you enjoy and a country that fits your budget. I can help you compare options.",
        "banglish": "Apnar pochonder subject ar budget-er sathe mile emon desh thik korun. Option compare korte ami help korbo.",
        "bengali": "পছন্দের বিষয় আর বাজেটের সাথে মেলে এমন দেশ বেছে নিন। বিকল্পগুলো তুলনা করতে আমি সাহায্য করব।",
    },
    "Yes Low": {
        "english": "Shortlist 3 to 5 courses or universities in {country} that match your result and budget.",
        "banglish": "{country}-e apnar result ar budget-er sathe mile emon 3 theke 5 ta course ba university shortlist korun.",
        "bengali": "{country}-এ আপনার রেজাল্ট আর বাজেটের সাথে মেলে এমন ৩ থেকে ৫টি কোর্স বা ইউনিভার্সিটি শর্টলিস্ট করুন।",
    },
    "Yes Medium": {
        "english": "Compare the entry requirements, total costs and deadlines of the options on your shortlist.",
        "banglish": "Apnar shortlist-er option gulor entry requirement, mot khoroch ar deadline compare korun.",
        "bengali": "শর্টলিস্টের বিকল্পগুলোর ভর্তির যোগ্যতা, মোট খরচ আর ডেডলাইন তুলনা করুন।",
    },
    "Yes High": {
        "english": "Get your documents ready: transcripts, passport, English test result and proof of funds.",
        "banglish": "Documents ready korun: transcript, passport, English test result ar fund-er proof.",
        "bengali": "ডকুমেন্ট তৈরি রাখুন: ট্রান্সক্রিপ্ট, পাসপোর্ট, ইংরেজি পরীক্ষার রেজাল্ট আর টাকার প্রমাণ।",
    },
}
COURSE_STEP = {
    "english": "Decide which subject you want to study, and I can suggest courses that fit your result.",
    "banglish": "Kon subject porte chan sheta thik korun, ami apnar result-er sathe mile emon course suggest korte parbo.",
    "bengali": "কোন বিষয়ে পড়তে চান তা ঠিক করুন, আপনার রেজাল্টের সাথে মেলে এমন কোর্স আমি সাজেস্ট করতে পারব।",
}
DEADLINE_STEP = {
    "english": "Check application deadlines for the {intake} intake early, so there is enough time for the visa.",
    "banglish": "{intake} intake-er application deadline age thekei dekhe rakhun, jate visa-r jonno jothesto shomoy thake.",
    "bengali": "{intake} ইনটেকের আবেদনের ডেডলাইন আগে থেকেই দেখে রাখুন, যাতে ভিসার জন্য যথেষ্ট সময় থাকে।",
}
PLAN_ASK = {
    "english": "What would you like to look at first?",
    "banglish": "Prothome kon ta niye kotha bolben?",
    "bengali": "প্রথমে কোনটা নিয়ে কথা বলবেন?",
}
SUGGESTIONS = {  # tappable follow-up questions shown under the plan
    "choose_course": {"english": "Help me choose a subject", "banglish": "Subject choose korte help korun",
                      "bengali": "বিষয় বাছাইয়ে সাহায্য করুন"},
    "universities": {"english": "Which universities in {country} suit me?",
                     "banglish": "{country}-e kon university amar jonno bhalo?",
                     "bengali": "{country}-এ কোন ইউনিভার্সিটি আমার জন্য ভালো?"},
    "documents": {"english": "What documents do I need?", "banglish": "Ki ki documents lagbe?",
                  "bengali": "কী কী ডকুমেন্ট লাগবে?"},
    "scholarship": {"english": "How can I get a scholarship?", "banglish": "Scholarship kivabe pabo?",
                    "bengali": "স্কলারশিপ কীভাবে পাব?"},
    "budget": {"english": "Is my budget enough?", "banglish": "Amar budget ki jothesto?",
               "bengali": "আমার বাজেট কি যথেষ্ট?"},
}
ACK_DETAIL = {  # repeats back what was understood, so a misreading is easy to spot
    "english": "Got it: {items}.",
    "banglish": "Thik ache, note korlam: {items}.",
    "bengali": "ঠিক আছে, লিখে রাখলাম: {items}।",
}
SKIP_ACK = {
    "english": "No problem, we can come back to that later.",
    "banglish": "Kono shomossha nai, pore dekhbo.",
    "bengali": "সমস্যা নেই, পরে দেখে নেব।",
}
STUDENT_TOPICS = {
    "help_research": {
        "english": "Research your course and university in detail: the modules, entry requirements, total cost and visa steps.",
        "banglish": "Apnar course ar university niye details research korun: modules, entry requirements, total khoroch ar visa process.",
        "bengali": "আপনার কোর্স আর ইউনিভার্সিটি নিয়ে বিস্তারিত খোঁজ নিন: মডিউল, ভর্তির যোগ্যতা, মোট খরচ আর ভিসার ধাপ।",
    },
    "funding_plan": {
        "english": "Work out the full cost of the programme and the funds the visa needs; look at scholarships or lower-cost options if it falls short.",
        "banglish": "Puro programme-er khoroch ar visa-r jonno koto fund lagbe sheta hishab korun; kom porle scholarship ba kom khorocher option dekhun.",
        "bengali": "পুরো প্রোগ্রামের খরচ আর ভিসার জন্য কত টাকা দেখাতে হবে তা হিসাব করুন; কম পড়লে স্কলারশিপ বা কম খরচের বিকল্প দেখুন।",
    },
    "academic_fit": {
        "english": "Check each programme's entry requirements against your results; foundation or pathway programmes can help.",
        "banglish": "Protiti programme-er entry requirement apnar result-er sathe milie dekhun; dorkar hole foundation ba pathway programme ache.",
        "bengali": "প্রতিটি প্রোগ্রামের ভর্তির যোগ্যতা আপনার রেজাল্টের সাথে মিলিয়ে দেখুন; দরকার হলে ফাউন্ডেশন বা পাথওয়ে প্রোগ্রাম আছে।",
    },
    "timing": {
        "english": "Plan your intake around application deadlines and visa processing time.",
        "banglish": "Application deadline ar visa processing-er shomoy hishab kore intake plan korun.",
        "bengali": "আবেদনের ডেডলাইন আর ভিসা প্রসেসিংয়ের সময় হিসাব করে ইনটেক ঠিক করুন।",
    },
    "destination_fit": {
        "english": "Compare your chosen course, university and country with a few alternatives before deciding.",
        "banglish": "Final korar age apnar course, university ar desh-ke aro kichu option-er sathe compare korun.",
        "bengali": "চূড়ান্ত করার আগে আপনার কোর্স, ইউনিভার্সিটি আর দেশকে আরও কয়েকটি বিকল্পের সাথে তুলনা করুন।",
    },
}
RESEARCH_FACT = {
    "english": "In our agency's recent records, students who had researched their course and university went ahead "
               "with their plans far more often (up to {hi}) than students who had not ({lo}).",
    "banglish": "Amader agency-r recent record-e dekha geche, jara course ar university niye research korechilo tara "
                "onek beshi plan onujayi egiye geche ({hi} porjonto), jara koreni tader ({lo}) tulonay.",
    "bengali": "আমাদের এজেন্সির সাম্প্রতিক রেকর্ডে দেখা গেছে, যারা কোর্স আর ইউনিভার্সিটি নিয়ে খোঁজ নিয়েছিলেন তারা "
               "অনেক বেশি পরিকল্পনা অনুযায়ী এগিয়েছেন (সর্বোচ্চ {hi}), যারা নেননি তাদের ({lo}) তুলনায়।",
}
HANDOFF_REPLY = {
    "english": "Of course. Tap **Talk to a counsellor** at the top and leave your number; a counsellor will call you back.",
    "banglish": "Obosshoi. Upore **Talk to a counsellor** button-e click kore apnar number din, counsellor apnake call korben.",
    "bengali": "অবশ্যই। উপরে **কাউন্সেলরের সাথে কথা বলুন** বোতামে চাপ দিয়ে আপনার নম্বর দিন, কাউন্সেলর আপনাকে ফোন করবেন।",
}
AMOUNT_NOTE = {
    "english": "_Amounts and requirements change often, so your counsellor will confirm the current figure._",
    "banglish": "_Amount ar requirement prayi change hoy, tai current figure apnar counsellor confirm kore diben._",
    "bengali": "_টাকার পরিমাণ আর শর্ত প্রায়ই বদলায়, তাই সর্বশেষ তথ্য আপনার কাউন্সেলর নিশ্চিত করে দেবেন।_",
}
HANDOFF_CONFIRM = {
    "english": "Thanks, {name}. A counsellor will contact you at {contact}{when}. You can keep chatting here meanwhile.",
    "banglish": "Dhonnobad, {name}. Counsellor apnake {contact} number-e jogajog korben{when}. Ei moddhe ekhane chat chalie jete paren.",
    "bengali": "ধন্যবাদ, {name}। কাউন্সেলর আপনার সাথে {contact} নম্বরে যোগাযোগ করবেন{when}। এর মধ্যে এখানে কথা চালিয়ে যেতে পারেন।",
}
HANDOFF_WHEN = {"english": " ({time})", "banglish": " ({time})", "bengali": " ({time})"}
INTEGRITY_REPLY = {
    "english": "I can't help change or edit official documents. Only the issuing authority can correct them, and "
               "submitting altered documents can get an application refused. A counsellor can guide you through the "
               "official correction process.",
    "banglish": "Official document change ba edit korte ami help korte parbo na. Shudhu issuing authority-i eta "
                "correct korte pare, ar edit kora document dile application refuse hote pare. Official correction "
                "process-e counsellor apnake guide korben.",
    "bengali": "অফিসিয়াল ডকুমেন্ট বদলানো বা এডিট করতে আমি সাহায্য করতে পারব না। শুধু যে কর্তৃপক্ষ ডকুমেন্ট দিয়েছে "
               "তারাই সংশোধন করতে পারে, আর এডিট করা ডকুমেন্ট দিলে আবেদন বাতিল হতে পারে। সঠিক সংশোধনের প্রক্রিয়ায় "
               "কাউন্সেলর আপনাকে সাহায্য করবেন।",
}


def ack(lang: str) -> str:
    return random.choice(ACKS[lang])


def bn_digits(text: str) -> str:
    return text.translate(BN_DIGITS)


def upcoming_intakes(today: date | None = None, count: int = 3) -> list[tuple[int, int]]:
    """Next common intake months (January, May, September) as (year, month)."""
    today = today or date.today()
    out, year = [], today.year
    while len(out) < count:
        for month in (1, 5, 9):
            if (year, month) > (today.year, today.month) and len(out) < count:
                out.append((year, month))
        year += 1
    return out


def chips_for(field: str, lang: str, bdt_per_usd: float, today: date | None = None) -> list[dict]:
    """Quick-reply buttons for a profile question. Each sets the field directly when tapped."""
    chips: list[dict] = []
    if field == "country":
        for c in COUNTRY_CHIPS:
            label = COUNTRY_BN[c] if lang == "bengali" else c
            chips.append({"label": label, "field": "country", "value": c})
    elif field == "intake":
        for year, month in upcoming_intakes(today):
            label = f"{MONTHS_BN[month - 1]} {bn_digits(str(year))}" if lang == "bengali" \
                else f"{MONTHS_EN[month - 1]} {year}"
            chips.append({"label": label, "field": "intake", "value": f"{year}-{month:02d}"})
        chips.append({"label": NOT_DECIDED[lang], "field": "intake", "value": None, "skip": True})
        return chips
    elif field == "budget":
        low = round(10_000 * bdt_per_usd / 100_000)    # lakh taka at the 10k USD band edge
        high = round(16_000 * bdt_per_usd / 100_000)   # lakh taka at the 16k USD band edge
        labels = {
            "english": [f"Under {low} lakh taka", f"{low} to {high - 1} lakh taka", f"{high} lakh taka or more"],
            "banglish": [f"{low} lakh-er kom", f"{low} theke {high - 1} lakh", f"{high} lakh ba beshi"],
            "bengali": [f"{bn_digits(str(low))} লাখ টাকার কম", f"{bn_digits(str(low))} থেকে {bn_digits(str(high - 1))} লাখ টাকা",
                        f"{bn_digits(str(high))} লাখ টাকা বা বেশি"],
        }[lang]
        for label, band in zip(labels, ["Below 10k", "10-15K", "16-20K"]):
            chips.append({"label": label, "field": "budget_band", "value": band})
    elif field == "due_diligence":
        for label, value in zip(DUE_DILIGENCE_CHIPS[lang], DUE_DILIGENCE_VALUES):
            chips.append({"label": label, "field": "due_diligence", "value": value})
    chips.append({"label": SKIP_LABEL[lang], "field": field, "value": None, "skip": True})
    return chips
