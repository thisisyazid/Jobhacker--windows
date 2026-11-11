"""Everything that talks to Claude (Anthropic API).

The API key is pasted in Settings and stored in the app's database, or comes
from ANTHROPIC_API_KEY. Every feature takes an optional engine argument for
compatibility; only "claude" exists. When no key is set, AI features are off
and the UI hides them."""
from __future__ import annotations

import json
import logging
import re
import time
import threading

from . import config

log = logging.getLogger("jobhacker.ai")
ENGINES = ("claude",)
KEY_SETTING = "anthropic_api_key"
_client = None
_client_key = None
_stored_key: str | None = None  # cache of the key saved in Settings
_lock = threading.Lock()


class AIError(Exception):
    pass


# ---------- API key ----------

def _load_stored_key() -> str:
    global _stored_key
    if _stored_key is None:
        from .db import AppSetting, SessionLocal
        with SessionLocal() as s:
            row = s.get(AppSetting, KEY_SETTING)
            _stored_key = (row.value if row else "") or ""
    return _stored_key


def claude_key() -> str:
    return config.ANTHROPIC_API_KEY or _load_stored_key()


def key_status() -> dict:
    k = claude_key()
    return {
        "has_key": bool(k),
        "hint": f"…{k[-4:]}" if len(k) >= 8 else "",
        "from_env": bool(config.ANTHROPIC_API_KEY),
        "model": config.CLAUDE_MODEL,
    }


def check_key(key: str) -> None:
    """Ask Anthropic whether the key works (listing models is free)."""
    from anthropic import Anthropic, AuthenticationError, PermissionDeniedError
    try:
        Anthropic(api_key=key, max_retries=1, timeout=20).models.list(limit=1)
    except (AuthenticationError, PermissionDeniedError) as e:
        raise AIError("Anthropic didn't accept that key. Copy it again from console.anthropic.com and paste the whole thing.") from e
    except Exception as e:
        raise AIError(f"Couldn't reach Anthropic to check the key ({e.__class__.__name__}). Check the internet connection and try again.") from e


def save_key(key: str) -> None:
    global _stored_key
    from .db import AppSetting, SessionLocal
    with SessionLocal() as s:
        row = s.get(AppSetting, KEY_SETTING)
        if key:
            if row:
                row.value = key
            else:
                s.add(AppSetting(key=KEY_SETTING, value=key))
        elif row:
            s.delete(row)
        s.commit()
    _stored_key = key


# ---------- availability ----------

def available(engine: str = "claude") -> bool:
    return bool(claude_key())


def default_engine() -> str | None:
    return "claude" if claude_key() else None


def enabled(engine: str | None = None) -> bool:
    return default_engine() is not None


def engines() -> dict:
    ok = bool(claude_key())
    return {
        "claude": {"available": ok, "label": "Claude", "model": config.CLAUDE_MODEL,
                   "reason": "" if ok else "Add your Claude API key in Settings."},
        "default": default_engine(),
    }


def resolve(engine: str | None = None) -> str:
    """Only Claude exists; anything else (e.g. an old "local" setting) means Claude."""
    if not claude_key():
        raise AIError("AI features are off. Add your Claude API key in Settings.")
    return "claude"


def label(engine: str = "claude") -> str:
    return f"Claude ({config.CLAUDE_MODEL})"


# ---------- calls ----------

def _get_client():
    global _client, _client_key
    key = claude_key()
    with _lock:
        if _client is None or _client_key != key:
            from anthropic import Anthropic
            _client, _client_key = Anthropic(api_key=key), key
        return _client


# Current Claude models think before answering, and that thinking counts toward max_tokens.
# A tight limit cuts the answer off part-way, so give every request generous room
# (only what's used is billed).
CLAUDE_MAX_TOKENS = 16000


def _ask(system: str, user: str, max_tokens: int = 2000, engine: str | None = None, json_mode: bool = False) -> str:
    resolve(engine)
    t0 = time.monotonic()
    try:
        resp = _get_client().messages.create(
            model=config.CLAUDE_MODEL, max_tokens=max(max_tokens, CLAUDE_MAX_TOKENS), system=system,
            messages=[{"role": "user", "content": user}],
        )
    except Exception as e:  # network, auth, rate limit…
        log.warning("AI call (Claude) failed after %.1fs: %s", time.monotonic() - t0, e.__class__.__name__)
        raise AIError(f"Claude request failed: {e.__class__.__name__}: {e}") from e
    stop = getattr(resp, "stop_reason", None)
    if stop == "max_tokens":
        log.warning("AI call (Claude) was cut off at the token limit after %.1fs", time.monotonic() - t0)
        raise AIError("Claude's answer was cut off before it finished. Try again.")
    if stop == "refusal":
        log.warning("AI call (Claude) was declined after %.1fs", time.monotonic() - t0)
        raise AIError("Claude declined this request. Try again.")
    out = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
    log.info("AI call (Claude): %.1fs, %d chars in, %d chars out", time.monotonic() - t0, len(user), len(out))
    return out


def _json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise AIError("The AI didn't return the expected format. Try again.")
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise AIError("The AI didn't return the expected format. Try again.") from e


def _job_block(job) -> str:
    g = (lambda k: getattr(job, k, None) if not isinstance(job, dict) else job.get(k))
    return (
        f"Job title: {g('title') or 'n/a'}\n"
        f"Company: {g('company') or 'n/a'}\n"
        f"Location: {g('location') or 'n/a'}\n"
        f"Salary: {g('salary') or 'n/a'}\n\n"
        f"Job description:\n{g('description') or '(no description saved)'}\n"
    )


# ---------- extraction ----------

EXTRACT_SYSTEM = """You extract job posting details from messy text copied off a web page.
Return ONLY a JSON object with these string keys:
title, company, location, salary, employment_type, posted_date, description.
Rules:
- Use "" for anything not stated. Never guess a company or salary.
- posted_date: YYYY-MM-DD if a date is given, otherwise the text as written (e.g. "3 days ago"), else "".
- description: the full job description (responsibilities, requirements, benefits, about the company)
  as clean plain text with "- " bullets and blank lines between sections. Drop navigation, cookie
  banners, "similar jobs", sign-in prompts and other page chrome. Do not summarise or shorten it."""


def extract_job(text: str, hint_title: str = "", engine: str | None = None) -> dict:
    user = (f"Page title: {hint_title}\n\n" if hint_title else "") + f"TEXT:\n{text}"
    data = _json(_ask(EXTRACT_SYSTEM, user, max_tokens=4000, engine=engine, json_mode=True))
    return {k: str(data.get(k) or "").strip() for k in
            ("title", "company", "location", "salary", "employment_type", "posted_date", "description")}


# ---------- fit score ----------

FIT_SYSTEM = """You are a frank career advisor. Score how well a candidate fits a job, 1–10.
10 = they meet essentially every requirement and it matches what they want.
7 = solid match worth applying, a few gaps. 4 = stretch. 1 = clearly wrong role.
If anything in the candidate's stated dealbreakers applies, score 2 or lower and say which.
Return ONLY JSON:
{"score": <int 1-10>,
 "verdict": "<one plain sentence, max 25 words>",
 "strengths": ["<max 4 short points, each tied to real resume evidence>"],
 "gaps": ["<max 4 short points: missing requirements or concerns>"],
 "keywords": ["<up to 8 terms from the posting worth mirroring in the resume>"]}"""


def fit(resume: str, preferences: str, job, engine: str | None = None) -> dict:
    user = (
        f"CANDIDATE RESUME:\n{resume or '(none provided)'}\n\n"
        f"WHAT THE CANDIDATE WANTS / DEALBREAKERS:\n{preferences or '(not specified)'}\n\n"
        f"JOB:\n{_job_block(job)}"
    )
    d = _json(_ask(FIT_SYSTEM, user, max_tokens=1200, engine=engine, json_mode=True))
    try:
        d["score"] = max(1, min(10, int(d.get("score", 0))))
    except (TypeError, ValueError):
        raise AIError("Claude didn't return a score. Try again.")
    for k in ("strengths", "gaps", "keywords"):
        d[k] = [str(x) for x in (d.get(k) or [])][:8]
    d["verdict"] = str(d.get("verdict") or "")
    return d


# ---------- documents ----------

RESUME_SYSTEM = """You are an expert resume writer. You get a candidate's base resume and a target
job. Produce a tailored resume in the exact Markdown structure below — nothing else.

# Full Name
email | phone | city | website
Headline 1 | Headline 2 | Headline 3

## Professional Summary
One paragraph, 3–5 sentences, written for this role.

## Core Capabilities
- **Group name:** item, item, item

## Professional Experience
### Company | Month YYYY – Month YYYY
**Job Title — Team or Department**
- Achievement bullet
- Achievement bullet

## Certifications & Education
- **Certifications:** ...
- **Education:** ...

## Tools & Technology
Comma-separated list.

Hard rules:
- ROLE ORDER IS FIXED: list every role in reverse chronological order (most recent first),
  with the same companies, titles and dates as the base resume. Never move a role up or down
  because it is more relevant, and never drop a role. Older roles may be shortened to 1–2 bullets.
- Within a role you MAY reorder, reword and trim bullets to mirror the job's language and
  priorities. You MAY rewrite the summary, headlines and capability groups for this role.
- Never invent employers, titles, dates, certifications, tools or metrics.
- Write past roles in past tense and the current role (end date "Present") in present tense.
- Use only the markers shown: #, ##, ###, "- " bullets and **bold**. No tables, no horizontal
  rules, no decorative symbols (❖ ▪ • ★ etc.) — remove any that appear in the base resume.
- Contact and headline lines separate items with " | ".
- Keep it to about two pages; cut the least relevant bullets first.
- Output ONLY the resume."""

COVER_SYSTEM = """You are an expert cover letter writer. You get a candidate's resume and a target
job. Write a specific cover letter of 250–350 words as clean plain text — no Markdown, no
asterisks, no headings, no bullet points.

Use exactly this shape, with a blank line between each part:

Dear <the hiring manager's name if the posting gives one, otherwise "Hiring Manager">,

<paragraph 1: why this role at this company, opening with something specific to them>

<paragraph 2: the most relevant experience from the resume, with concrete results>

<paragraph 3: more relevant experience or skills that match the posting's requirements>

<paragraph 4: a short close saying you'd welcome a conversation>

Kind regards,
<the candidate's full name>

Rules:
- Always start with the "Dear ...," line and always end with "Kind regards," and the candidate's name.
- Never open with "I am writing to express my interest".
- Reference concrete details from the posting (team, product, requirements).
- Use only real experience from the resume; never fabricate.
- No placeholders such as [Company] or [Your Name]: use the real names given.
- Plain, confident, warm tone.
- Output ONLY the letter, from "Dear" to the name. No notes before or after it."""

CLOSINGS = re.compile(r"^(kind regards|best regards|warm regards|regards|sincerely|yours sincerely|yours faithfully|"
                      r"best wishes|best|many thanks|thank you|thanks|warmly|cheers|respectfully)\b[ ,.!]*$", re.I)


def candidate_name(resume: str) -> str:
    """The name at the top of a resume: a "# Name" heading, else a short first line."""
    for line in resume.splitlines():
        s = line.strip().lstrip("#").strip().strip("*").strip()
        if not s:
            continue
        words = s.split()
        if (len(s) <= 60 and "@" not in s and not re.search(r"\d", s) and 2 <= len(words) <= 6
                and words[0][:1].isupper() and words[-1][:1].isupper()):
            return s
        return ""
    return ""


def finish_letter(text: str, name: str = "") -> str:
    """Make sure a cover letter reads as a letter, whatever the model returned:
    plain text, a greeting at the top, and a sign-off with the name at the end."""
    t = re.sub(r"^```(?:\w+)?\s*|\s*```$", "", text.strip())
    t = re.sub(r"\*\*(.*?)\*\*", r"\1", t)                  # no Markdown bold
    t = re.sub(r"^#+\s*", "", t, flags=re.M)                  # no Markdown headings
    lines = t.splitlines()
    # drop chatter before the letter ("Here is your cover letter:")
    start = next((i for i, l in enumerate(lines) if re.match(r"^\s*(dear|hi|hello|to whom)\b", l, re.I)), None)
    if start is not None and start <= 3:
        lines = lines[start:]
    elif lines and re.match(r"^\s*(here('| i)s|sure|certainly|below)\b.*:\s*$", lines[0], re.I):
        lines = lines[1:]
    t = "\n".join(lines).strip()
    if not re.match(r"^(dear|hi|hello|to whom)\b", t, re.I):
        t = "Dear Hiring Manager,\n\n" + t
    tail = [l.strip() for l in t.splitlines() if l.strip()][-3:]
    closing_at = next((i for i, l in enumerate(tail) if CLOSINGS.match(l)), None)
    if closing_at is None:
        t += "\n\nKind regards," + (f"\n{name}" if name else "")
    elif closing_at == len(tail) - 1 and name:  # sign-off but no name under it
        t += f"\n{name}"
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def tailor_resume(resume: str, job, extra: str = "", engine: str | None = None) -> str:
    if not resume.strip():
        raise AIError("Add your base resume in Settings first.")
    from .resume_format import base_roles, missing_roles, sort_experience
    roles = base_roles(resume)
    user = f"BASE RESUME:\n{resume}\n\nTARGET JOB:\n{_job_block(job)}"
    if roles:
        # A checklist helps smaller local models, which otherwise sometimes drop a role.
        user += ("\n\nROLES IN THE BASE RESUME. Every one must appear under Professional Experience, "
                 "most recent first, with its company, title and dates:\n" + "\n".join(f"- {r}" for r in roles))
    if extra.strip():
        user += f"\n\nEXTRA INSTRUCTIONS FROM THE CANDIDATE:\n{extra}"

    def ask(prompt: str) -> str:
        out = _ask(RESUME_SYSTEM, prompt, max_tokens=4000, engine=engine)
        return re.sub(r"^```(?:markdown|md)?\s*|\s*```$", "", out.strip())

    out = ask(user)
    lost = missing_roles(roles, out)
    if lost:
        log.warning("tailored resume left out %d role(s): %s; asking again", len(lost), "; ".join(lost))
        retry = ask(user + "\n\nIMPORTANT: a previous draft left out these roles. Include every one of them, "
                    "with its company, title and dates, in date order:\n" + "\n".join(f"- {r}" for r in lost))
        still = missing_roles(roles, retry)
        if len(still) < len(lost):
            out = retry
        if still:
            log.warning("tailored resume still leaves out: %s", "; ".join(still))
    return sort_experience(out)


def cover_letter(resume: str, job, extra: str = "", engine: str | None = None) -> str:
    if not resume.strip():
        raise AIError("Add your base resume in Settings first.")
    name = candidate_name(resume)
    company = (job.get("company") if isinstance(job, dict) else getattr(job, "company", "")) or ""
    user = (f"CANDIDATE'S NAME: {name or '(take it from the top of the resume)'}\n"
            f"COMPANY: {company or '(see the job below)'}\n\nRESUME:\n{resume}\n\nTARGET JOB:\n{_job_block(job)}")
    if extra.strip():
        user += f"\n\nEXTRA INSTRUCTIONS FROM THE CANDIDATE:\n{extra}"
    out = _ask(COVER_SYSTEM, user, max_tokens=1500, engine=engine)
    return finish_letter(out, name)
