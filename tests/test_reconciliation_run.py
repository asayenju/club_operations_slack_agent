from unittest.mock import MagicMock, patch

from reconciliation.composer import ComposedProposal
from reconciliation.run import run_reconciliation
from tools.confidence import ConfidenceResult
from tools.models import Citation, Evidence


def make_evidence(source: str = "gdoc") -> Evidence:
    return Evidence(
        source=source,
        text="some evidence text",
        citation=Citation(source=source, label=f"label-{source}"),
        similarity=0.85,
    )


def make_candidate_mock(evidence: list[Evidence]) -> MagicMock:
    candidate = MagicMock()
    candidate.all_evidence.return_value = evidence
    return candidate


def test_actionable_result_posts_and_persists():
    evidence = [make_evidence("gdoc"), make_evidence("gsheet")]
    confidence = ConfidenceResult(level="Medium", reason="Conflicting.", conflict=True)
    composed = ComposedProposal(
        blocks=[{"type": "section"}],
        is_actionable=True,
        confidence=confidence,
        proposed_action="Update the budget sheet to $500.",
    )
    slack_client = MagicMock()
    slack_client.chat_postMessage.return_value = {"ts": "111.222"}
    proposal_service = MagicMock()
    proposal_service.create_pending.return_value = "created-proposal"

    with patch(
        "reconciliation.run.build_reconciliation_candidate",
        return_value=make_candidate_mock(evidence),
    ), patch("reconciliation.run.score_confidence", return_value=confidence), patch(
        "reconciliation.run.compose_reconciliation_proposal", return_value=composed
    ):
        result = run_reconciliation(
            workspace_id="T1",
            topic="finance budget",
            slack_client=slack_client,
            slack_channel_id="C1",
            proposal_service=proposal_service,
        )

    slack_client.chat_postMessage.assert_called_once_with(
        channel="C1",
        blocks=composed.blocks,
        text="Reconciliation proposal: finance budget",
    )
    proposal_service.create_pending.assert_called_once_with(
        workspace_id="T1",
        source_evidence=[
            {
                "source": "gdoc",
                "text": "some evidence text",
                "citation": {"source": "gdoc", "label": "label-gdoc"},
                "similarity": 0.85,
                "score": None,
                "timestamp": None,
                "author": None,
                "metadata": {},
            },
            {
                "source": "gsheet",
                "text": "some evidence text",
                "citation": {"source": "gsheet", "label": "label-gsheet"},
                "similarity": 0.85,
                "score": None,
                "timestamp": None,
                "author": None,
                "metadata": {},
            },
        ],
        proposed_action={"description": "Update the budget sheet to $500."},
        slack_channel_id="C1",
        slack_message_ts="111.222",
    )
    assert result == "created-proposal"


def test_non_actionable_result_posts_but_does_not_persist():
    evidence = [make_evidence("gdoc")]
    confidence = ConfidenceResult(level="Low", reason="No relevant evidence found.")
    composed = ComposedProposal(
        blocks=[{"type": "section"}],
        is_actionable=False,
        confidence=confidence,
    )
    slack_client = MagicMock()
    slack_client.chat_postMessage.return_value = {"ts": "111.222"}
    proposal_service = MagicMock()

    with patch(
        "reconciliation.run.build_reconciliation_candidate",
        return_value=make_candidate_mock(evidence),
    ), patch("reconciliation.run.score_confidence", return_value=confidence), patch(
        "reconciliation.run.compose_reconciliation_proposal", return_value=composed
    ):
        result = run_reconciliation(
            workspace_id="T1",
            topic="finance budget",
            slack_client=slack_client,
            slack_channel_id="C1",
            proposal_service=proposal_service,
        )

    slack_client.chat_postMessage.assert_called_once()
    proposal_service.create_pending.assert_not_called()
    assert result is None
