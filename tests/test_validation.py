from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from mas_error_lifecycle.runner import MockRunConfig, run_mock
from mas_error_lifecycle.schema import EventType
from mas_error_lifecycle.store import TraceValidationError, write_trace


class ValidationTests(unittest.TestCase):
    def test_unknown_event_artifact_is_rejected(self) -> None:
        bundle = run_mock(MockRunConfig(seed=9))
        events = list(bundle.events)
        target = next(event for event in events if event.artifact_id)
        events[events.index(target)] = replace(target, artifact_id="missing")
        invalid = replace(bundle, events=tuple(events))
        with self.assertRaises(TraceValidationError) as context:
            invalid.validate()
        self.assertIn("unknown artifact", str(context.exception))

    def test_future_parent_is_rejected(self) -> None:
        bundle = run_mock(
            MockRunConfig(seed=10, verification="none", governance_action="none")
        )
        events = list(bundle.events)
        target = next(
            event for event in events if event.event_type == EventType.MESSAGE_SENT
        )
        final = events[-1]
        events[events.index(target)] = replace(
            target, parent_event_ids=(final.event_id,)
        )
        with self.assertRaises(TraceValidationError) as context:
            replace(bundle, events=tuple(events)).validate()
        self.assertIn("parent must occur earlier", str(context.exception))

    def test_adoption_without_exposure_is_rejected(self) -> None:
        bundle = run_mock(
            MockRunConfig(
                seed=11,
                verification="none",
                governance_action="none",
                adoption_probability=1.0,
            )
        )
        removed = {
            event.event_id
            for event in bundle.events
            if event.event_type == EventType.ARTIFACT_EXPOSED
        }
        events = tuple(
            replace(
                event,
                parent_event_ids=tuple(
                    parent for parent in event.parent_event_ids if parent not in removed
                ),
            )
            for event in bundle.events
            if event.event_id not in removed
        )
        with self.assertRaises(TraceValidationError) as context:
            replace(bundle, events=events).validate()
        self.assertIn("without prior exposure/possession", str(context.exception))

    def test_exposure_prompt_agent_must_match_target(self) -> None:
        bundle = run_mock(MockRunConfig(seed=12))
        exposure = next(
            event
            for event in bundle.events
            if event.event_type == EventType.ARTIFACT_EXPOSED
        )
        prompts = tuple(
            replace(prompt, agent_id="root")
            if prompt.prompt_id == exposure.prompt_id
            else prompt
            for prompt in bundle.prompts
        )
        with self.assertRaises(TraceValidationError) as context:
            replace(bundle, prompts=prompts).validate()
        self.assertIn("prompt belongs to wrong agent", str(context.exception))

    def test_verification_evidence_cannot_dangle(self) -> None:
        bundle = run_mock(
            MockRunConfig(
                seed=13,
                verification_probability=1.0,
                verification_accuracy=1.0,
            )
        )
        events = list(bundle.events)
        target = next(
            event
            for event in events
            if event.event_type == EventType.VERIFICATION_COMPLETED
        )
        events[events.index(target)] = replace(
            target,
            details={**target.details, "evidence_ids": ["missing-evidence"]},
        )
        with self.assertRaises(TraceValidationError) as context:
            replace(bundle, events=tuple(events)).validate()
        self.assertIn("unknown evidence", str(context.exception))

    def test_overwrite_requires_explicit_opt_in(self) -> None:
        bundle = run_mock(MockRunConfig(seed=14))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.jsonl"
            write_trace(path, bundle)
            with self.assertRaises(FileExistsError):
                write_trace(path, bundle)
            write_trace(path, bundle, overwrite=True)


if __name__ == "__main__":
    unittest.main()
