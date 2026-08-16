# BrowseComp × MAS pilot — first 7 questions (preliminary)

First run of the self-built 3-agent relay (Searcher → Synthesizer → Verifier)
over the first 7 decrypted BrowseComp questions, one
`qwen/qwen3-30b-a3b-instruct-2507`, Tavily search, temperature 0. Raw traces at
`outputs/browsecomp-run-pilot1.jsonl` (git-ignored).

## Result

6/7 completed (one timed out), **1/7 correct** (row 6, "Savannah College of Art
and Design"). The rest are "insufficient evidence" or a wrong guess.

| row | final | true answer | correct |
| --- | --- | --- | --- |
| 0 | "did not work as a probation officer" | 1988-96 | no |
| 1 | "No such match found" | Ireland v Romania | no |
| 2 | (model call timed out) | Amr Zaki | — |
| 3 | "founder unknown" | Rosalea Murphy, 1912 | no |
| 4 | "Sara Ahmed" | Cristina Ortiz | no |
| 5 | "12:00 AM" | 3:50 PM | no |
| 6 | "Savannah College of Art and Design" | SCAD | **yes** |

## Where the failure is: search coverage, not the relay

For 6/7 questions the true answer never appeared in the Searcher's findings at
all (checked by fragment match). The relay is **faithful**: the one question the
Searcher did find (row 6) propagated cleanly findings → answer → final.

So the pilot's dominant failure mode is at the **tooling/search layer**, not the
multi-agent hand-off: one verbatim-question Tavily search + one top-hit fetch is
far too shallow for BrowseComp, whose questions need multi-hop browsing.

## Failure modes observed (for the taxonomy)

- **Search-coverage failure** (rows 0,1,3,4): the evidence never entered the
  system; downstream correctly reports "not found" rather than hallucinating.
- **Confident wrong answer from thin evidence** (rows 4,5): the Verifier picks a
  specific wrong value instead of abstaining.
- **Transient model timeout** (row 2): one `TimeoutError` at 300s.

## What this implies for the next step

To make BrowseComp a real test of the relay (rather than of search depth), the
Searcher needs an *iterative* loop: search → fetch → issue follow-up queries →
fetch more, with a token/step budget, so the evidence actually reaches the
hand-off. Until then the pilot mainly demonstrates that the 3-agent relay does
not lose or corrupt information — the loss is upstream, in search.

## Re-run with the iterative Searcher + a stronger model (235b-a22b)

The Searcher loop (search → follow-up query → findings, up to 3 rounds) was
added, and the 7 questions re-run with `qwen/qwen3-235b-a22b-2507` throughout.

- **No crashes** (7/7 completed, vs 6/7 with 30b), and the model actually
  iterates: 1-2 search rounds per question (mean 1.4), where 30b gave up after
  round 1.
- **Still 1/7 correct** (only SCAD). The others are now clean *abstentions*
  ("Unknown", "Insufficient data", "cannot be determined") rather than 30b's
  confident wrong guesses (e.g. 30b said "Sara Ahmed" where 235b abstains).

Conclusion is unchanged and now cleaner: **the bottleneck is search depth, not
the relay, and a stronger Searcher abstains instead of hallucinating.** To lift
accuracy, the search itself must go deeper (more rounds, page-level multi-hop,
or a real browsing tool) — not the relay.
