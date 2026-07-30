# Decision log

## 2026-07-30

- Use a lifecycle decomposition instead of a single infected-agent score.
- Treat prompt exposure as distinct from message delivery.
- Treat textual reproduction as provisional adoption evidence, not definitive
  action-grounded adoption.
- Allow null final outcome because AgentCollabBench exposes diagnostic metrics,
  not a recognized task-success grader.
- Keep all primary conditional rates undefined when the denominator is zero.
- Support a provider router keyed by agent ID so heterogeneous-team experiments
  do not require one provider for all roles.
- Start with a standard-library-only implementation to make schema and mock
  validation independent of API and package availability.
- Defer paid provider adapters until model choices, budget and credentials are
  confirmed.
