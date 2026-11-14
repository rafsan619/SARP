"""Find similar past cases among the agency's recorded counselling conversations.

Each conversation is one past case: its situation (destination and scenario title, or the student's
opening question) and what the counsellor actually advised. The counsellor assistant shows the closest
cases next to the current one, so junior counsellors learn how senior colleagues handled the same
problem. Train and validation conversations only; the test split stays clean for evaluation.

On the team PC the cases come from ../data/splits; online they come from the `cases` database table,
filled by `python -m agent.seed_examples`.
"""
from __future__ import annotations

import json
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel

from agent.retriever import DEFAULT_DATA_DIR, SPLITS


def case_from_conversation(conv: dict) -> dict | None:
    turns = conv.get("turns", [])
    students = [t["text"] for t in turns if t["role"] == "user"]
    counsellor = [t["text"] for t in turns if t["role"] == "assistant"]
    if not students or not counsellor:
        return None
    if conv.get("scenario"):
        title = f"{conv.get('destination') or 'Study abroad'}: {conv['scenario']}"
    else:
        first = students[0].strip()
        title = (first[:90] + "…") if len(first) > 90 else first
    # The most substantial counsellor turns carry the advice.
    advice = sorted((c.strip() for c in counsellor if len(c.split()) >= 10), key=len, reverse=True)[:3]
    return {"id": conv["id"], "title": title, "destination": conv.get("destination"),
            "language": conv.get("language_detected"),
            "text": " ".join([conv.get("scenario") or ""] + students + counsellor),
            "advice": json.dumps(advice, ensure_ascii=False)}


def cases_from_files(data_dir: Path = DEFAULT_DATA_DIR) -> list[dict]:
    out = []
    for split in SPLITS:
        path = Path(data_dir) / "splits" / f"{split}.jsonl"
        if path.exists():
            with path.open(encoding="utf-8") as f:
                for line in f:
                    case = case_from_conversation(json.loads(line))
                    if case:
                        out.append(case)
    return out


class CaseLibrary:
    def __init__(self, data_dir: Path = DEFAULT_DATA_DIR, store=None):
        self.cases = cases_from_files(data_dir)
        self.source = "files" if self.cases else None
        if not self.cases and store is not None:
            self.cases = store.load_cases()
            self.source = "database" if self.cases else None
        self.vectorizer = None
        if self.cases:
            # Word n-grams for meaning plus character n-grams for Banglish spelling variation.
            self.vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True,
                                              max_features=60_000)
            self.matrix = self.vectorizer.fit_transform([c["text"] for c in self.cases])

    def __len__(self) -> int:
        return len(self.cases)

    @staticmethod
    def _out(c: dict, score: float, why: str) -> dict:
        return {"id": c["id"], "title": c["title"], "destination": c["destination"], "match": why,
                "advice": json.loads(c["advice"]) if isinstance(c["advice"], str) else c["advice"],
                "score": round(score, 3)}

    def similar(self, query: str, scenarios: list[str] | None = None, k: int = 3,
                min_score: float = 0.15) -> list[dict]:
        """Past cases for this situation: first those whose scenario matches a detected problem type
        (the knowledge base lists the matching scenario titles), then the closest by wording."""
        out, seen = [], set()
        for keyword in scenarios or []:
            for c in self.cases:
                if c["id"] not in seen and keyword.lower() in c["title"].lower():
                    out.append(self._out(c, 1.0, "same problem type"))
                    seen.add(c["id"])
                    break
            if len(out) == k:
                return out
        if self.vectorizer and query.strip():
            scores = linear_kernel(self.vectorizer.transform([query]), self.matrix)[0]
            for i in scores.argsort()[::-1]:
                if len(out) == k or scores[i] < min_score:
                    break
                if self.cases[i]["id"] not in seen:
                    out.append(self._out(self.cases[i], float(scores[i]), "similar wording"))
                    seen.add(self.cases[i]["id"])
        return out
