# BrowseComp × multi-agent — pilot design (draft, for review)

This is the design for running a *small* multi-agent system (MAS) on a few
BrowseComp questions and reading the trajectories for failure modes. It is
**not** a MAST-style framework evaluation and **not** a score-hunting run: the
goal is to see whether putting a MAS on a browsing task — which, as far as we
know, no one has published — exposes new error-lifecycle failure modes that the
single-agent BrowseComp eval cannot see.

Status: **design only. Not run yet.** This doc is what needs your sign-off
before any run. Nothing here requires an API key or a search key to review.

## 1. The tools question (does BrowseComp come with tools?)

Short answer: **BrowseComp ships questions only. It does not ship tools, and it
does not run agents.** You wire the tools yourself — but you do not write them
from scratch.

- BrowseComp is a dataset of 1,266 questions that *require* web search + reading
  pages to answer. Each question is a `problem` string (plus an encrypted form
  in the official distribution).
- OpenAI's reference harness is in `openai/simple-evals` (`browsecomp_eval.py`).
  It defines exactly two tools for the agent:
  - `web_search(query)` — a thin wrapper that calls a *search backend*. The
    backend is pluggable; the reference points at a specific search endpoint,
    but any provider works (Tavily / Serper / Bing / Google, via API key).
  - `fetch(url)` — HTTP GET a page and turn it into readable text (real, ~20
    lines; no external key needed).
- So: the two **tool definitions** and the `fetch` implementation come from the
  reference harness. The only thing you supply is the **search backend + key**
  behind `web_search`. For AG2 you register these two functions as AG2 tools.

**Update (verified 2026-08 in a throwaway container):** AG2 `1.0.2` ships the
tools built-in, so you do not even write the functions:

- `ag2.tools.WebSearchTool` — hosted, versioned web search (`web_search_2025…`
  / `20260209` / `20260318`), with `allowed_domains` / `blocked_domains` /
  `user_location` knobs.
- `ag2.tools.WebFetchTool` — URL fetch with `citations` + `max_content_tokens`.
- `ag2.tools.TavilySearchTool` / `DuckDuckSearchTool` — third-party backends if
  you do not use the hosted `WebSearchTool`.

So the tool question resolves to: **BrowseComp gives questions, AG2 1.0 gives the
tools; the only things you supply are a search key (hosted or Tavily/DuckDuckGo)
and a model key.**

## 2. Why multi-agent here (what we are testing)

BrowseComp is single-agent: one loop does search → read → answer. A MAS on top
of it separates those stages into distinct agents, which creates hand-off points
where information can be lost or corrupted — the exact phenomenon RQ1/RQ2 study.
Concretely, the pilot asks:

- Does a correct search finding survive the Searcher → Synthesizer hand-off?
- Does a wrong/irrelevant search result get *adopted* by a downstream agent
  (the RQ2 "false fact" pattern, but organic instead of injected)?
- Does the answer come from evidence, or from the Synthesizer's priors when the
  evidence is dropped in transit?

## 3. The MAS design

A minimal, deterministic 3-agent chain (not a dynamic swarm) so the topology is
legible in the trace.

Note on AG2 1.0 (verified by spike): the old `GroupChat` / `RoundRobinGroupChat`
API is **gone**. `ag2.Agent(name, prompt, config=…, tools=[…])` is the agent, and
multi-agent is done by wrapping one agent as a **`subagent_tool`** of another
(`ag2.tools.subagents.subagent_tool`), plus a separate `tasks`/`assembly`
surface. That is a *nested* subagent model, not a flat relay, and its trace is a
tool-call/event stream rather than our source→target `message` records. See the
harness decision in section 8.

```
Searcher ──(findings + cited URLs)──▶ Synthesizer ──(answer + rationale)──▶ Verifier ──▶ final
```

| Role | Has tools? | Input | Output |
| --- | --- | --- | --- |
| **Searcher** | `web_search` + `fetch` | the question | raw findings + source URLs |
| **Synthesizer** | none | Searcher's findings | a proposed answer + rationale |
| **Verifier** | `web_search` + `fetch` | question + Synthesizer's answer | final answer (agree / correct) |

Design choices, made deliberately:

1. **Only Searcher and Verifier have tools.** The Synthesizer is tool-less so
   "using tools" and "reasoning over evidence" are cleanly separated. A
   hallucinated or lost finding then shows up as a Synthesizer error, not a tool
   error.
2. **Verbatim relay for the pilot** (no compaction) — the baseline. The
   existing Codex-compaction mechanism is the obvious second arm if the
   verbatim pilot shows a hand-off loss worth amplifying.
3. **The question is handed to every agent**, not just the first, so a later
   agent can *notice* when upstream findings drift from the question (this is
   where a Verifier can catch a Searcher that answered the wrong sub-question).

### Small N

Follow the AgentCollabBench pattern: pick ~7 questions first (stratified by
rough topic / difficulty if that is cheap, else the first 7 decrypted), run
once, read trajectories. Do not scale until the trajectory analysis says there
is something to scale.

## 4. Trace recording

Reuse the existing schema, not a new one. For each BrowseComp run, emit a
`run_manifest` plus, per agent turn:

- a `message` record for each inter-agent hand-off (source → target, content);
- a `model_call` record for each agent LLM call;
- a `tool_call`/`event` record for every `web_search`/`fetch` invocation with
  its result (so a search result is attributable to the agent that saw it);
- an `outcome` record with the final answer.

This is the same record vocabulary as `lifecycle-trace.jsonl` in the
AgentCollabBench adapter, which means the RQ1/RQ2 semantic-annotation layer and
the MAST taxonomy can be applied to BrowseComp traces without a new pipeline.

## 5. What failure modes to look for

Starting from MAST's 14-mode taxonomy as a checklist, but expecting BrowseComp
to add browsing-specific ones:

- FC2 (inter-agent misalignment) — e.g. Synthesizer ignores Searcher's findings.
- FC3 (task verification) — Verifier rubber-stamps a wrong answer.
- New: **evidence provenance loss** — answer cites a URL the Searcher never
  returned (hallucinated source).
- New: **premature convergence** — Synthesizer answers from its priors because
  the findings were too long / dropped.

## 6. Implementation steps + blockers

Steps, in order:

1. **Get BrowseComp** (encrypted in the official release; decrypt via the
   simple-evals util). Verify the question count and spot-check ~7.
2. **Web tools** — done: `adapters/browsecomp_tools.py` provides `tavily_search`
   + `fetch_url` (stdlib only, key never persisted). Smoke-tested against the
   real Tavily key.
3. **3-agent relay + trace logger**, emitting the record vocabulary above.
4. **Run ~7 questions verbatim**, dump traces, and run the annotation pass.

## 8. Harness decision (updated after the AG2 spike)

AG2 1.0's multi-agent path is a **nested subagent tool** (one agent wraps another
as a `subagent_tool`), plus a `tasks`/`assembly` surface — not a flat relay, and
its trace is a tool-call/event stream, not our `source → target` `message`
records. For a pilot whose whole point is *analyzing the trajectory*, that is a
poor fit: it hides the hand-off we want to inspect behind framework plumbing.

**Decision: build the BrowseComp MAS as a minimal self-built relay**, reusing the
existing trace schema + provider primitives (the same machinery the
AgentCollabBench adapter already uses). The web tools come from
`browsecomp_tools.py`; the 3 roles are three calls in a controlled loop, so each
hand-off is an explicit `message` record. This is faster, fully traceable, and
keeps the error-lifecycle lens (relay → adoption → downstream) intact.

Remaining blocker: **the BrowseComp dataset itself** (encrypted in the official
release; needs download + decryption via the simple-evals util), plus the model
key at run time (as usual, via stdin, never persisted).

## 7. Decisions to confirm

1. ~~Search backend~~ — **Tavily, key supplied** (2026-08).
2. ~~AG2 vs self-built relay~~ — **self-built relay** (see section 8).
3. **Verbatim first, or compact as a second arm from the start?**
