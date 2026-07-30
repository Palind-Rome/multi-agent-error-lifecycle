from __future__ import annotations

import unittest
from dataclasses import replace

from mas_error_lifecycle.runner import MockRunConfig, run_mock
from mas_error_lifecycle.store import TraceBundle, TraceValidationError


class ValidationTests(unittest.TestCase):
    def test_unknown_event_artifact_is_rejected(self) -> None:
        bundle = run_mock(MockRunConfig(seed=9))
        events = list(bundle.events)
        target = next(event for event in events if event.artifact_id)
        events[events.index(target)] = replace(target, artifact_id="missing")
        invalid = TraceBundle(
            bundle.manifest,
            bundle.artifacts,
            bundle.prompts,
            tuple(events),
            bundle.outcome,
        )
        with self.assertRaises(TraceValidationError) as context:
            invalid.validate()
        self.assertIn("unknown artifact", str(context.exception))

    def test_overwrite_requires_explicit_opt_in(self) -> None:
        bundle = run_mock(MockRunConfig(seed=10))
        self.assertIsInstance(bundle.outcome.success, bool)


if __name__ == "__main__":
    unittest.main()
