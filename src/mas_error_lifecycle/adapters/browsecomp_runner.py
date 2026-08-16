"""Minimal 3-agent BrowseComp relay: Searcher -> Synthesizer -> Verifier.

This is the self-built MAS pilot (see ``docs/browsecomp-mas-design.md`` section
8). It is a *controlled* relay, not a dynamic swarm, so every hand-off is an
explicit record that the error-lifecycle lens can inspect:

* Searcher (has tools): receives the question + Tavily search results + the
  fetched text of the top hit, and writes findings with sources.
* Synthesizer (no tools): receives the question + findings, writes an answer.
* Verifier (has tools): receives the question + answer, re-searches, and writes
  the final answer.

Every model call is an OpenAI-compatible chat completion against the pinned
PaperBypass endpoint; keys are passed in and never persisted.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from .browsecomp_tools import WebToolError, fetch_url, tavily_search

PAPERBYPASS_BASE_URL = "https://aigateway.paperbypass.com/api/v1"
DEFAULT_MODEL = "qwen/qwen3-30b-a3b-instruct-2507"

_SEARCHER_SYSTEM = (
    "You are a web research agent. Use the provided search results and page text "
    "to answer the question. Cite the source URLs you rely on. If the evidence is "
    "insufficient, say so rather than guessing."
)
_SYNTHESIZER_SYSTEM = (
    "You are an analyst. Given the question and the researcher's findings, write a "
    "concise final answer. Do not invent facts beyond the findings."
)
_VERIFIER_SYSTEM = (
    "You are a verifier. Given the question, a proposed answer, and fresh search "
    "results, output the corrected final answer (a short phrase or value only)."
)


class BrowseCompRunnerError(RuntimeError):
    """Safe public error (no secrets)."""


def _chat(api_key: str, model: str, system: str, user: str) -> str:
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.0,
    }).encode("utf-8")
    request = urllib.request.Request(
        f"{PAPERBYPASS_BASE_URL}/chat/completions",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=300.0) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
        raise BrowseCompRunnerError(f"model call failed: {type(exc).__name__}") from exc
    return payload["choices"][0]["message"]["content"]


def _search_brief(tavily_key: str, query: str, n: int = 3) -> str:
    results = tavily_search(tavily_key, query, max_results=n)
    lines = []
    for item in results:
        lines.append(f"- [{item['title']}] ({item['url']})\n  {item['content'][:400]}")
    return "\n".join(lines) or "(no results)"


def run_browsecomp_question(
    *,
    question: str,
    model_key: str,
    tavily_key: str,
    model: str = DEFAULT_MODEL,
) -> dict[str, Any]:
    """Run the 3-agent relay on one question and return the trace + final answer."""
    trace: list[dict[str, Any]] = []

    # --- Searcher ---
    search_brief = _search_brief(tavily_key, question)
    top_url = ""
    for line in search_brief.splitlines():
        if "(http" in line:
            top_url = line.split("(http", 1)[1].split(")", 1)[0]
            top_url = "http" + top_url
            break
    page_text = ""
    if top_url:
        try:
            page_text = fetch_url(top_url)[:4000]
        except WebToolError:
            page_text = "(fetch failed)"
    trace.append({"agent": "searcher", "tool": "search", "query": question,
                  "brief": search_brief[:2000]})
    searcher_user = (
        f"Question: {question}\n\nSearch results:\n{search_brief}\n\n"
        f"Top page text ({top_url}):\n{page_text}\n\nWrite your findings with sources."
    )
    findings = _chat(model_key, model, _SEARCHER_SYSTEM, searcher_user)
    trace.append({"agent": "searcher", "output": findings})

    # --- Synthesizer (no tools) ---
    synth_user = f"Question: {question}\n\nFindings:\n{findings}\n\nAnswer:"
    answer = _chat(model_key, model, _SYNTHESIZER_SYSTEM, synth_user)
    trace.append({"agent": "synthesizer", "output": answer})

    # --- Verifier (re-search) ---
    verify_brief = _search_brief(tavily_key, question, n=2)
    trace.append({"agent": "verifier", "tool": "search", "query": question,
                  "brief": verify_brief[:1500]})
    verifier_user = (
        f"Question: {question}\n\nProposed answer: {answer}\n\n"
        f"Fresh search results:\n{verify_brief}\n\nFinal answer (short phrase/value only):"
    )
    final = _chat(model_key, model, _VERIFIER_SYSTEM, verifier_user)
    trace.append({"agent": "verifier", "output": final})

    return {"question": question, "findings": findings, "answer": answer,
            "final": final, "trace": trace}


if __name__ == "__main__":
    import sys

    from .browsecomp_loader import load_browsecomp

    model_key = sys.stdin.readline().strip()
    tavily_key = sys.stdin.readline().strip()
    data = load_browsecomp()
    q = data[0]["question"]
    result = run_browsecomp_question(question=q, model_key=model_key, tavily_key=tavily_key)
    print("final:", result["final"][:200])
