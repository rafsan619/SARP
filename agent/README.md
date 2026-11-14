# SARP-Agent: virtual senior counsellor

An AI assistant for the agency's counsellors, not for students, built on the SARP-Net continuation model.
A counsellor describes a student's situation in English, Banglish or Bengali, the way they would tell a
senior colleague. The assistant then:

- **reads the case**: destination, level, course, result, English test, budget, bank statement, intake,
  study gap, visa refusal and dependants;
- **finds problems**: for example a bank statement under 28 days, a long study gap, a previous refusal,
  low English, a funding gap or a missed intake. Each is marked as a blocker, a risk or a check;
- **assesses eligibility**: likely eligible, potentially eligible, not yet eligible, or need more
  information, with the reason and what is missing;
- **suggests next steps**: what to verify, which documents to request, what to ask the student, the
  possible pathways and what to tell the student;
- **shows similar past cases**: the 200+ real agency conversations, with what our counsellor advised;
- **scores continuation risk** with SARP-Net and explains the SHAP drivers with project evidence;
- **trains new counsellors**: training mode explains why each step matters.

The counsellor makes the final decision. They can correct any detail on the case sheet, dismiss a
problem that doesn't apply, and flag a case for a senior counsellor. Senior counsellors see every case
on the team overview page.

## Run it

1. Install the Python packages (Python 3.12, from the repository root):
   ```
   python -m venv .venv
   .venv\Scripts\python.exe -m pip install -r requirements.txt -r agent/requirements.txt
   ```
2. Install [Ollama](https://ollama.com) and download the model: `ollama pull gemma3:4b`
3. Start the website from the repository root:
   ```
   .venv\Scripts\python.exe -m agent.server
   ```
   - Case assistant: http://127.0.0.1:8000
   - Team overview: http://127.0.0.1:8000/team

**Without an AI model the site still works.** If Ollama is off, or stops partway through a reply, the
assistant says that AI writing is offline. It then gives a structured answer built from the case rules
and past cases: the assessment, the problems, what to check, what to ask, the options and the next steps.
The follow-up buttons (documents, pathways, what to tell the student, what else to ask) also work offline.

To put the site online (Vercel, a free Neon database, the PC's GPU as the AI with a free hosted backup),
follow [DEPLOY.md](DEPLOY.md).

## How an answer is made

| Part | File | Source of truth |
|---|---|---|
| Reading the case from the counsellor's message | `extract.py`, `casebook.py` | Rules for English, Banglish and Bengali |
| Problems, eligibility, checks, next steps | `casebook.py` | Agency case rules: entry requirements, 28-day bank rule, gap, refusal and English thresholds |
| Similar past cases | `cases.py` | The agency's real counsellor conversations (problem type first, then wording) |
| Continuation risk and SHAP drivers | `risk_tool.py` | SARP-Net Gradient Boosting model, same code as the dashboard |
| Evidence for each driver | `findings.py` | `results_ablation/`, `experiments/results/e2_*`, `results_paper2/` |
| Written answer | `chat.py`, `llm.py`, `prompts.py` | Any OpenAI-compatible model, given the case sheet, case rules, SARP-Net result and past cases. Without a model, the same material is laid out without AI |
| PC model gateway | `llm_gateway.py`, `start_gateway.ps1` | Lets the online site use the PC's GPU safely |
| Storage | `store.py` | SQLite at `../agent_data/sarp_agent.db` on the PC; Postgres when `DATABASE_URL` is set |

## Data

Past cases and counsellor examples come from `../data/splits/train.jsonl` and `val.jsonl`, made by
`data_prep/parse_conversations.py`. They're kept outside the repository because the conversations are
confidential. Online, `python -m agent.seed_examples` uploads them to the database. The test split is
never used, so it stays clean for evaluation.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `SARP_LLM_BASE_URL` | `http://127.0.0.1:11434/v1` | AI endpoint (OpenAI-compatible) |
| `SARP_LLM_API_KEY` | empty | Key for that endpoint (the gateway key online) |
| `SARP_LLM_MODEL` | `gemma3:4b` | Model name; set to the fine-tuned model's name once imported |
| `SARP_LLM_FALLBACK_*` | not set | Optional backup AI (base URL, key, model) |
| `DATABASE_URL` | not set | Postgres connection; without it cases go to SQLite |
| `SARP_COUNSELLOR_PIN` | not set | PIN for the whole app. Required online; optional on the PC |
| `SARP_POLITICAL_PHASE` | `Newly Elected` | Phase used for every prediction |
| `SARP_BDT_PER_USD` | `122` | Exchange rate for budgets given in taka |
| `SARP_DATA_DIR` | `../data` | Folder holding `splits/` for past cases |
| `SARP_DB_PATH` | `../agent_data/sarp_agent.db` | Case database |

## Tests

```
.venv\Scripts\python.exe -m unittest agent.test_risk_tool agent.test_chat agent.test_deploy -v
```
Set `TEST_DATABASE_URL` to a Postgres database to also run the storage tests against Postgres.
