"""Deterministic confidence-policy tests; API responses here are fixtures."""

import json
from pathlib import Path
from typing import TypedDict, cast

import httpx2
import pysubs2
import pytest
import typesafe_sdk
from typer.testing import CliRunner
from typesafe_sdk import TypeSafeClient, TypeSafeError

from keshigomu import clean_text, cli


class Payload(TypedDict):
    questions: dict[str, dict[str, object]]


def fixture_client(
    confidence: float,
    choice: str = "annotation",
    *,
    nouls: dict[str, float] | None = None,
) -> TypeSafeClient:
    def respond(request: httpx2.Request) -> httpx2.Response:
        payload = cast(Payload, json.loads(request.content))
        values = {} if nouls is None else nouls
        return httpx2.Response(
            200,
            content=json.dumps(
                {
                    "model": "offline-fixture",
                    "usage": {},
                    "answers": {
                        "classify_sdh": {
                            "type": "choice",
                            "choice": choice,
                            "confidence": confidence,
                            # Deliberately separate probability from confidence.
                            "probabilities": {
                                choice: 0.99,
                                "furigana" if choice == "speech" else "speech": 0.01,
                            },
                        },
                        **{
                            question_id: {
                                "type": "noul",
                                "noul": values.get(question_id, 0.0),
                            }
                            for question_id, question in payload["questions"].items()
                            if question["type"] == "noul"
                        },
                    },
                }
            ),
            headers={"Content-Type": "application/json"},
        )

    return TypeSafeClient(api_key="test-key", transport=httpx2.MockTransport(respond))


@pytest.mark.parametrize("confidence", [0.0, 0.6999])
def test_low_confidence_annotation_is_preserved(confidence: float) -> None:
    text = r"{\i1}（胃リンパ腫）{\i0}\Nはい"
    with fixture_client(confidence) as client:
        assert clean_text(text, client, min_confidence=0.7) == text


@pytest.mark.parametrize("confidence", [0.7, 1.0])
def test_confidence_boundary_is_inclusive(confidence: float) -> None:
    with fixture_client(confidence) as client:
        assert (
            clean_text(r"（声{\i1}）はい", client, min_confidence=0.7) == r"{\i1}はい"
        )


@pytest.mark.parametrize(
    "threshold, expected, action",
    [
        (None, "はい", "remove"),
        ("0.9", "（声）はい", "keep"),
        ("0.8", "はい", "remove"),
    ],
)
def test_cli_threshold_controls_action_and_verbose_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    threshold: str | None,
    expected: str,
    action: str,
) -> None:
    source = tmp_path / "input.srt"
    output = tmp_path / "output.srt"
    _ = source.write_text(
        "1\n00:00:01,000 --> 00:00:02,000\n（声）はい\n", encoding="utf-8"
    )
    client = fixture_client(0.85, nouls={"speech_content": 0.98})

    def factory(**_kwargs: object) -> TypeSafeClient:
        return client

    monkeypatch.setattr(typesafe_sdk, "TypeSafeClient", factory)
    arguments = [str(source), str(output), "--verbose"]
    if threshold is not None:
        arguments.extend(["--min-confidence", threshold])
    result = CliRunner().invoke(cli.app, arguments)
    assert result.exit_code == 0, result.output
    assert result.stdout == ""
    assert action in result.stderr
    assert "speech_content=0.98" in result.stderr
    assert pysubs2.load(output)[0].text == expected


@pytest.mark.parametrize("confidence", [-0.1, 1.1, float("nan"), float("inf")])
def test_invalid_model_confidence_fails_closed(confidence: float) -> None:
    with (
        fixture_client(confidence) as client,
        pytest.raises(TypeSafeError, match="confidence"),
    ):
        _ = clean_text("（声）はい", client)


@pytest.mark.parametrize("threshold", [-0.1, 1.1, float("nan"), float("inf")])
def test_invalid_function_threshold_is_rejected(threshold: float) -> None:
    with fixture_client(1.0) as client, pytest.raises(ValueError, match="confidence"):
        _ = clean_text("（声）はい", client, min_confidence=threshold)


@pytest.mark.parametrize("threshold", ["-0.1", "1.1", "nan", "inf"])
def test_invalid_cli_threshold_is_rejected_before_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, threshold: str
) -> None:
    source = tmp_path / "source.srt"
    output = tmp_path / "output.srt"
    _ = source.write_text(
        "1\n00:00:01,000 --> 00:00:02,000\n（声）はい\n", encoding="utf-8"
    )

    def unexpected_client(**_kwargs: object) -> TypeSafeClient:
        pytest.fail("Invalid threshold must be rejected before creating a client")

    monkeypatch.setattr(typesafe_sdk, "TypeSafeClient", unexpected_client)
    result = CliRunner().invoke(
        cli.app, [str(source), str(output), "--min-confidence", threshold]
    )
    assert result.exit_code == 2, result.output
    assert "confidence" in result.stderr
    assert not output.exists()


@pytest.mark.parametrize("confidence", [0.0, 0.9, 1.0])
def test_speech_is_kept_at_any_confidence(confidence: float) -> None:
    text = "（元のテキスト）"
    with fixture_client(confidence, "speech") as client:
        assert clean_text(text, client) == text
