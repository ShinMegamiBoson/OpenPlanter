from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent.investigation_state import (
    build_question_reasoning_packet,
    migrate_legacy_state,
    state_to_legacy_projection,
)
from agent.runtime import SessionStore


class InvestigationStateMigrationTests(unittest.TestCase):
    def test_migrate_legacy_state_creates_structured_evidence(self) -> None:
        legacy = {
            "session_id": "sid",
            "saved_at": "2026-03-13T00:00:00+00:00",
            "external_observations": ["obs a", "obs b"],
            "turn_history": [{"turn_number": 1}],
            "loop_metrics": {"turns": 1},
            "custom_field": "keep me",
        }
        state = migrate_legacy_state("sid", legacy)

        self.assertEqual(state["schema_version"], "1.0.0")
        self.assertEqual(state["legacy"]["external_observations"], ["obs a", "obs b"])
        self.assertEqual(state["legacy"]["extra_fields"]["custom_field"], "keep me")
        self.assertEqual(
            state["evidence"]["ev_legacy_000001"]["evidence_type"],
            "legacy_observation",
        )
        self.assertEqual(
            state["evidence"]["ev_legacy_000002"]["source_uri"],
            "state.json#external_observations[1]",
        )

    def test_state_to_legacy_projection_falls_back_to_evidence(self) -> None:
        state = {
            "schema_version": "1.0.0",
            "session_id": "sid",
            "updated_at": "2026-03-13T00:00:00+00:00",
            "legacy": {"turn_history": [], "loop_metrics": {}, "extra_fields": {"custom_field": "hello"}},
            "evidence": {
                "ev_legacy_000002": {
                    "content": "second",
                    "normalization": {"kind": "legacy_observation"},
                },
                "ev_legacy_000001": {
                    "content": "first",
                    "normalization": {"kind": "legacy_observation"},
                },
            },
        }

        projected = state_to_legacy_projection(state, session_id="sid")
        self.assertEqual(projected["external_observations"], ["first", "second"])
        self.assertEqual(projected["custom_field"], "hello")


class SessionStoreTypedStateTests(unittest.TestCase):
    def test_save_state_writes_typed_file_and_typed_first_load_preserves_extras(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = SessionStore(workspace=root)
            sid, _, _ = store.open_session(session_id="typed-save", resume=False)

            store.save_state(
                sid,
                {
                    "session_id": sid,
                    "saved_at": "2026-03-13T12:00:00+00:00",
                    "external_observations": ["alpha", "beta"],
                    "turn_history": [{"turn_number": 1}],
                    "loop_metrics": {"turns": 1},
                    "custom_field": "hello",
                },
            )

            session_dir = root / ".openplanter" / "sessions" / sid
            typed_path = session_dir / "investigation_state.json"
            self.assertTrue(typed_path.exists())

            typed = json.loads(typed_path.read_text(encoding="utf-8"))
            self.assertEqual(typed["legacy"]["extra_fields"]["custom_field"], "hello")
            self.assertEqual(typed["evidence"]["ev_legacy_000001"]["content"], "alpha")

            (session_dir / "state.json").write_text("{}", encoding="utf-8")
            loaded = store.load_state(sid)
            self.assertEqual(loaded["external_observations"], ["alpha", "beta"])
            self.assertEqual(loaded["custom_field"], "hello")
            self.assertEqual(loaded["turn_history"], [{"turn_number": 1}])

    def test_load_state_accepts_legacy_rust_external_context_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = SessionStore(workspace=root)
            sid, _, _ = store.open_session(session_id="rust-legacy", resume=False)
            session_dir = root / ".openplanter" / "sessions" / sid

            (session_dir / "state.json").write_text(
                json.dumps(
                    {
                        "observations": [
                            {
                                "source": "wiki",
                                "timestamp": "2026-03-13T00:00:00Z",
                                "content": "obs one",
                            },
                            {
                                "source": "tool",
                                "timestamp": "2026-03-13T00:00:01Z",
                                "content": "obs two",
                            },
                        ],
                        "custom_field": "preserve-me",
                    }
                ),
                encoding="utf-8",
            )

            loaded = store.load_state(sid)
            self.assertEqual(loaded["external_observations"], ["obs one", "obs two"])
            self.assertEqual(loaded["custom_field"], "preserve-me")

    def test_save_state_preserves_existing_typed_fields_and_prunes_only_legacy_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = SessionStore(workspace=root)
            sid, _, _ = store.open_session(session_id="typed-merge", resume=False)
            session_dir = root / ".openplanter" / "sessions" / sid

            typed = {
                "schema_version": "1.0.0",
                "session_id": sid,
                "created_at": "2026-03-13T00:00:00+00:00",
                "updated_at": "2026-03-13T00:00:00+00:00",
                "objective": "",
                "ontology": {"namespace": "openplanter.core", "version": "2026-03"},
                "entities": {},
                "links": {},
                "claims": {},
                "evidence": {
                    "ev_legacy_000001": {
                        "id": "ev_legacy_000001",
                        "content": "stale",
                        "normalization": {"kind": "legacy_observation"},
                    },
                    "ev_legacy_000002": {
                        "id": "ev_legacy_000002",
                        "content": "remove me",
                        "normalization": {"kind": "legacy_observation"},
                    },
                    "ev_other": {
                        "id": "ev_other",
                        "content": "keep me",
                        "normalization": {"kind": "web_fetch"},
                    },
                },
                "hypotheses": {},
                "questions": {"q_1": {"id": "q_1", "question_text": "keep me"}},
                "tasks": {},
                "actions": {},
                "provenance_nodes": {},
                "confidence_profiles": {},
                "timeline": [],
                "indexes": {"by_external_ref": {}, "by_tag": {}},
                "legacy": {
                    "external_observations": ["stale", "remove me"],
                    "turn_history": [],
                    "loop_metrics": {},
                    "extra_fields": {"custom_field": "before"},
                },
            }
            (session_dir / "investigation_state.json").write_text(
                json.dumps(typed),
                encoding="utf-8",
            )

            store.save_state(
                sid,
                {
                    "session_id": sid,
                    "saved_at": "2026-03-13T12:30:00+00:00",
                    "external_observations": ["fresh"],
                    "turn_history": [{"turn_number": 3}],
                    "loop_metrics": {"turns": 3},
                    "custom_field": "after",
                },
            )

            updated = json.loads((session_dir / "investigation_state.json").read_text(encoding="utf-8"))
            self.assertEqual(updated["questions"]["q_1"]["question_text"], "keep me")
            self.assertIn("ev_other", updated["evidence"])
            self.assertEqual(updated["evidence"]["ev_legacy_000001"]["content"], "fresh")
            self.assertNotIn("ev_legacy_000002", updated["evidence"])
            self.assertEqual(updated["legacy"]["extra_fields"]["custom_field"], "after")

            projected = json.loads((session_dir / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(projected["external_observations"], ["fresh"])
            self.assertEqual(projected["custom_field"], "after")


class QuestionReasoningPacketTests(unittest.TestCase):
    def test_build_question_reasoning_packet_groups_findings_and_contradictions(self) -> None:
        state = {
            "questions": {
                "q_2": {
                    "id": "q_2",
                    "question_text": "Is claim 2 true?",
                    "status": "open",
                    "priority": "high",
                    "claim_ids": ["cl_2"],
                    "evidence_ids": ["ev_2"],
                },
                "q_1": {
                    "id": "q_1",
                    "question_text": "Is claim 1 true?",
                    "status": "open",
                    "priority": "critical",
                    "claim_ids": ["cl_1"],
                    "evidence_ids": ["ev_1", "ev_3"],
                },
                "q_done": {
                    "id": "q_done",
                    "question_text": "Ignore",
                    "status": "resolved",
                },
            },
            "claims": {
                "cl_1": {
                    "claim_text": "Claim supported",
                    "status": "supported",
                    "support_evidence_ids": ["ev_1"],
                    "confidence": 0.91,
                },
                "cl_2": {
                    "claim_text": "Claim contested",
                    "status": "contested",
                    "support_evidence_ids": ["ev_2"],
                    "contradiction_evidence_ids": ["ev_3"],
                    "confidence_score": 0.4,
                },
                "cl_3": {
                    "claim_text": "Claim unresolved",
                    "status": "unresolved",
                    "evidence_ids": ["ev_4"],
                },
            },
            "evidence": {
                "ev_1": {"evidence_type": "doc", "provenance_ids": ["pv_1"], "source_uri": "s1"},
                "ev_2": {"evidence_type": "doc", "provenance_ids": ["pv_2"], "source_uri": "s2"},
                "ev_3": {"evidence_type": "doc", "provenance_ids": ["pv_3"], "source_uri": "s3"},
                "ev_4": {"evidence_type": "doc", "provenance_ids": ["pv_4"], "source_uri": "s4"},
            },
        }

        packet = build_question_reasoning_packet(state)

        self.assertEqual(packet["reasoning_mode"], "question_centric")
        self.assertEqual(packet["focus_question_ids"], ["q_1", "q_2"])
        self.assertEqual(len(packet["findings"]["supported"]), 1)
        self.assertEqual(packet["findings"]["supported"][0]["id"], "cl_1")
        self.assertEqual(len(packet["findings"]["contested"]), 1)
        self.assertEqual(packet["findings"]["contested"][0]["id"], "cl_2")
        self.assertEqual(len(packet["findings"]["unresolved"]), 1)
        self.assertEqual(packet["findings"]["unresolved"][0]["id"], "cl_3")
        self.assertEqual(packet["contradictions"][0]["claim_id"], "cl_2")
        self.assertIn("ev_3", packet["evidence_index"])
        self.assertEqual(
            [action["id"] for action in packet["candidate_actions"]],
            ["ca_q_q_1", "ca_q_q_2", "ca_c_cl_2", "ca_c_cl_3"],
        )
        self.assertEqual(packet["candidate_actions"][0]["required_sources"], ["s1", "s3"])
        self.assertEqual(
            packet["candidate_actions"][1]["rationale"]["reason_codes"],
            ["question_unresolved", "claim_low_confidence"],
        )
        self.assertEqual(
            packet["candidate_actions"][2]["evidence_gap_refs"][0]["kind"],
            "low_confidence",
        )
        self.assertEqual(
            packet["candidate_actions"][3]["evidence_gap_refs"][0]["kind"],
            "missing_counter_evidence",
        )
        self.assertEqual(packet["candidate_actions"][3]["required_sources"], ["s4"])
        self.assertTrue(packet["candidate_actions"][0]["ontology_object_refs"])

    def test_build_question_reasoning_packet_emits_candidate_actions_for_missing_evidence(self) -> None:
        state = {
            "questions": {
                "q_1": {
                    "id": "q_1",
                    "question_text": "What source confirms the claim?",
                    "status": "open",
                    "priority": "high",
                    "claim_ids": ["cl_1"],
                    "evidence_ids": [],
                }
            },
            "claims": {
                "cl_1": {
                    "id": "cl_1",
                    "claim_text": "Needs evidence",
                    "status": "proposed",
                    "evidence_ids": [],
                    "confidence": "0.20",
                }
            },
            "evidence": {},
        }

        packet = build_question_reasoning_packet(state)

        self.assertEqual(packet["candidate_actions"][0]["id"], "ca_q_q_1")
        self.assertEqual(packet["candidate_actions"][0]["evidence_gap_refs"][0]["kind"], "missing_evidence")
        self.assertEqual(packet["candidate_actions"][1]["id"], "ca_c_cl_1")
        self.assertEqual(
            packet["candidate_actions"][1]["rationale"]["reason_codes"],
            ["claim_unresolved", "claim_low_confidence", "question_unresolved"],
        )
        self.assertEqual(packet["candidate_actions"][1]["required_sources"], [])

    def test_build_question_reasoning_packet_keeps_entity_inputs_entity_only_and_collects_question_sources(
        self,
    ) -> None:
        state = {
            "questions": {
                "q_1": {
                    "id": "q_1",
                    "question_text": "What source confirms the claim?",
                    "status": "open",
                    "priority": "high",
                    "claim_ids": ["cl_1"],
                    "resolution_claim_id": "cl_resolution",
                    "provenance_ids": ["pv_q_1"],
                }
            },
            "claims": {
                "cl_1": {
                    "id": "cl_1",
                    "claim_text": "Needs evidence",
                    "status": "proposed",
                    "evidence_ids": [],
                    "confidence": 0.2,
                }
            },
            "provenance_nodes": {
                "pv_q_1": {
                    "id": "pv_q_1",
                    "source_uri": "https://question-source.test",
                }
            },
            "evidence": {},
        }

        packet = build_question_reasoning_packet(state)
        question_action = next(action for action in packet["candidate_actions"] if action["id"] == "ca_q_q_1")

        self.assertEqual(question_action["required_inputs"]["entity_ids"], [])
        self.assertEqual(question_action["required_sources"], ["https://question-source.test"])
        self.assertFalse(
            any(ref.get("object_type") == "entity" for ref in question_action["ontology_object_refs"])
        )


if __name__ == "__main__":
    unittest.main()
