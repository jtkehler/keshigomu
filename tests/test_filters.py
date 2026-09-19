"""Filter-selection tests using offline HTTP fixtures, not model evaluations."""

import json
from pathlib import Path
from typing import cast

import httpx2
import pysubs2
import pytest
import typesafe_sdk
from typer.testing import CliRunner
from typesafe_sdk import TypeSafeClient

import keshigomu
from keshigomu import cli


def response(choice: str, confidence: float = 0.95) -> httpx2.Response:
    return httpx2.Response(
        200,
        json={
            "model": "offline-fixture",
            "usage": {},
            "answers": {
                "classify_sdh": {
                    "type": "choice",
                    "choice": choice,
                    "confidence": confidence,
                    "probabilities": {choice: 1.0},
                }
            },
        },
    )


@pytest.mark.parametrize(
    "remove_sdh, remove_furigana, expected",
    [
        (True, False, "怖(こえ)えよ！（内緒）〔不明〕"),
        (False, True, "（ミツオ）怖えよ！（内緒）〔不明〕"),
        (True, True, "怖えよ！（内緒）〔不明〕"),
        (False, False, "（ミツオ）怖(こえ)えよ！（内緒）〔不明〕"),
    ],
)
def test_text_api_filters_only_selected_categories(
    remove_sdh: bool, remove_furigana: bool, expected: str
) -> None:
    sentence = "（ミツオ）怖(こえ)えよ！（内緒）〔不明〕"
    labels = {
        "（ミツオ）": "annotation",
        "(こえ)": "furigana",
        "（内緒）": "speech",
        "〔不明〕": "annotation",
    }
    seen: list[str] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        payload = cast(dict[str, dict[str, str]], json.loads(request.content))
        assert payload["state"]["sentence"] == sentence
        span = payload["state"]["to_check"]
        seen.append(span)
        choice = labels[span]
        return response(choice, confidence=0.45 if span == "〔不明〕" else 0.95)

    with TypeSafeClient(
        api_key="test-key", transport=httpx2.MockTransport(respond)
    ) as client:
        assert (
            keshigomu.clean_text(
                sentence, client, remove_sdh=remove_sdh, remove_furigana=remove_furigana
            )
            == expected
        )
    assert seen == (list(labels) if remove_sdh or remove_furigana else [])


@pytest.mark.parametrize("entrypoint", ["api", "cli"])
@pytest.mark.parametrize(
    "remove_sdh, remove_furigana, flags, expected",
    [
        (True, False, ["--keep-furigana"], ["怖(こえ)えよ！"]),
        (True, False, ["--no-remove-furigana"], ["怖(こえ)えよ！"]),
        (False, True, ["--keep-sdh"], ["（ミツオ）怖えよ！", "〔拍手〕"]),
        (False, True, ["--no-remove-sdh"], ["（ミツオ）怖えよ！", "〔拍手〕"]),
        (True, True, [], ["怖えよ！"]),
        (True, True, ["--remove-sdh", "--remove-furigana"], ["怖えよ！"]),
        (
            False,
            False,
            ["--keep-sdh", "--keep-furigana"],
            ["（ミツオ）怖(こえ)えよ！", "〔拍手〕"],
        ),
        (
            False,
            False,
            ["--no-remove-sdh", "--no-remove-furigana"],
            ["（ミツオ）怖(こえ)えよ！", "〔拍手〕"],
        ),
    ],
)
def test_file_filter_selection_preserves_timing_and_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    entrypoint: str,
    remove_sdh: bool,
    remove_furigana: bool,
    flags: list[str],
    expected: list[str],
) -> None:
    source, output = tmp_path / "input.srt", tmp_path / "output.srt"
    subtitles = pysubs2.SSAFile()
    subtitles.events = [
        pysubs2.SSAEvent(start=1000, end=2000, text="（ミツオ）怖(こえ)えよ！"),
        pysubs2.SSAEvent(start=3000, end=4000, text="〔拍手〕"),
    ]
    subtitles.save(source)
    original = source.read_bytes()
    seen: list[str] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        payload = cast(dict[str, dict[str, str]], json.loads(request.content))
        span = payload["state"]["to_check"]
        seen.append(span)
        choice = "furigana" if span == "(こえ)" else "annotation"
        return response(choice)

    with TypeSafeClient(
        api_key="test-key", transport=httpx2.MockTransport(respond)
    ) as client:
        if entrypoint == "api":
            changed, removed = keshigomu.clean_file(
                source,
                output,
                client=client,
                remove_sdh=remove_sdh,
                remove_furigana=remove_furigana,
            )
            assert changed == (2 if remove_sdh else int(remove_furigana))
            assert removed == 2 - len(expected)
        else:

            def factory(**_kwargs: object) -> TypeSafeClient:
                return client

            monkeypatch.setattr(typesafe_sdk, "TypeSafeClient", factory)
            result = CliRunner().invoke(cli.app, [str(source), str(output), *flags])
            assert result.exit_code == 0, result.output
            assert result.stdout == ""
            assert f"dropped {2 - len(expected)} empty cues" in result.stderr
    assert seen == (
        ["（ミツオ）", "(こえ)", "〔拍手〕"] if remove_sdh or remove_furigana else []
    )
    assert source.read_bytes() == original
    assert [(e.start, e.end, e.text) for e in pysubs2.load(output)] == [
        (subtitles[index].start, subtitles[index].end, text)
        for index, text in enumerate(expected)
    ]


@pytest.mark.parametrize("remove_furigana", [False, True])
def test_owned_client_keeps_selected_filter(
    monkeypatch: pytest.MonkeyPatch, remove_furigana: bool
) -> None:
    def factory(**_kwargs: object) -> TypeSafeClient:
        return TypeSafeClient(
            api_key="test-key",
            transport=httpx2.MockTransport(lambda _: response("furigana")),
        )

    monkeypatch.setattr(typesafe_sdk, "TypeSafeClient", factory)
    expected = "明日" if remove_furigana else "明日(あした)"
    assert (
        keshigomu.clean_text("明日(あした)", remove_furigana=remove_furigana)
        == expected
    )


def test_furigana_filter_does_not_revisit_nested_reading_in_speaker_label() -> None:
    text = "（緑川(みどりかわ)ルリ子）"
    seen: list[str] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        state = cast(dict[str, dict[str, str]], json.loads(request.content))["state"]
        seen.append(state["to_check"])
        return response("annotation")

    with TypeSafeClient(
        api_key="test-key", transport=httpx2.MockTransport(respond)
    ) as client:
        assert keshigomu.clean_text(text, client, remove_sdh=False) == text
    assert seen == [text]


@pytest.mark.parametrize("remove_sdh", [False, True])
@pytest.mark.parametrize("confidence", [0.89, 0.9])
def test_furigana_uses_confidence_gate_and_preserves_ass_tags(
    remove_sdh: bool, confidence: float, capsys: pytest.CaptureFixture[str]
) -> None:
    text = r"{\pos(12,24)}明日(あ{\i1}した{\i0})"
    expected = text if confidence < 0.9 else r"{\pos(12,24)}明日{\i1}{\i0}"
    requests: list[str] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        state = cast(dict[str, dict[str, str]], json.loads(request.content))["state"]
        requests.append(state["to_check"])
        return response("furigana", confidence)

    with TypeSafeClient(
        api_key="test-key", transport=httpx2.MockTransport(respond)
    ) as client:
        assert keshigomu.clean_text(text, client, remove_sdh=remove_sdh) == expected
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert requests == ["(あした)"]


@pytest.mark.parametrize("entrypoint", ["text", "file", "cli"])
def test_disabling_both_options_needs_no_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, entrypoint: str
) -> None:
    text = "（声）明日(あした)"
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)

    def unexpected_client(**_kwargs: object) -> TypeSafeClient:
        pytest.fail("Disabling both options must not create a client")

    monkeypatch.setattr(typesafe_sdk, "TypeSafeClient", unexpected_client)
    if entrypoint == "text":
        assert (
            keshigomu.clean_text(text, remove_sdh=False, remove_furigana=False) == text
        )
        return
    source, output = tmp_path / "input.srt", tmp_path / "output.srt"
    subtitles = pysubs2.SSAFile()
    subtitles.events = [pysubs2.SSAEvent(start=1000, end=2000, text=text)]
    subtitles.save(source)
    original = source.read_bytes()
    if entrypoint == "file":
        assert keshigomu.clean_file(
            source, output, remove_sdh=False, remove_furigana=False
        ) == (0, 0)
    else:
        result = CliRunner().invoke(
            cli.app, [str(source), str(output), "--keep-sdh", "--keep-furigana"]
        )
        assert result.exit_code == 0, result.output
        assert result.stdout == ""
        assert "Changed 0 cues; dropped 0 empty cues" in result.stderr
    assert source.read_bytes() == original
    assert pysubs2.load(output).equals(pysubs2.load(source))
