"""Offline tests: HTTP responses below are fixtures, never model evaluations."""

import json
import logging
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
    state: dict[str, str]
    questions: dict[str, dict[str, object]]


@pytest.mark.parametrize("fail", [False, True])
def test_verbose_logging_is_scoped_to_the_cli_invocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail: bool
) -> None:
    source = tmp_path / "input.srt"
    _ = source.write_text("unused fixture", encoding="utf-8")
    logger = logging.getLogger("keshigomu")
    before = (logger.level, logger.propagate, list(logger.handlers))

    def clean_file(*_args: object, **_kwargs: object) -> tuple[int, int]:
        logging.getLogger("keshigomu.cleaner").debug("fixture decision")
        if fail:
            raise TypeSafeError("fixture failure")
        return 0, 0

    monkeypatch.setattr(cli, "clean_file", clean_file)
    runner = CliRunner()
    result = runner.invoke(cli.app, [str(source), str(tmp_path / "out.srt"), "-v"])
    assert result.exit_code == (1 if fail else 0)
    assert result.stdout == ""
    assert result.stderr.count("fixture decision") == 1
    assert (logger.level, logger.propagate, logger.handlers) == before
    quiet = runner.invoke(cli.app, [str(source), str(tmp_path / "out.srt")])
    assert "fixture decision" not in quiet.stderr


def test_default_removes_sdh_and_furigana_but_keeps_speech() -> None:
    sentence = "（ミツオ）怖(こえ)えよ！（小声で話している）"
    labels = {
        "（ミツオ）": "annotation",
        "(こえ)": "furigana",
        "（小声で話している）": "speech",
    }
    seen: list[str] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        payload = cast(Payload, json.loads(request.content))
        assert payload["state"]["sentence"] == sentence
        question = payload["questions"]["classify_sdh"]
        criteria = cast(dict[str, object], question["criteria"])
        assert isinstance(question["instructions"], dict)
        assert set(criteria) == {"annotation", "furigana", "speech"}
        assert all(isinstance(option, dict) for option in criteria.values())
        span = payload["state"]["to_check"]
        seen.append(span)
        label = labels[span]
        return httpx2.Response(
            200,
            json={
                "model": "test-fixture",
                "usage": {"input_tokens": 1, "output_tokens": 1},
                "answers": {
                    "classify_sdh": {
                        "type": "choice",
                        "choice": label,
                        "confidence": 1.0,
                        "probabilities": {label: 1.0},
                    }
                },
            },
        )

    with TypeSafeClient(
        api_key="test-key", transport=httpx2.MockTransport(respond)
    ) as client:
        assert clean_text(sentence, client) == "怖えよ！（小声で話している）"
    assert seen == list(labels)


@pytest.mark.parametrize(
    "text, expected, candidates",
    [
        ("[拍手]はい", "はい", ["[拍手]"]),
        ("［拍手］はい", "［拍手］はい", []),
        ("【拍手】はい", "【拍手】はい", []),
        ("〔拍手〕はい", "はい", ["〔拍手〕"]),
        ("〈拍手〉はい", "〈拍手〉はい", []),
        ("《拍手》はい", "《拍手》はい", []),
        ("＜拍手＞はい", "＜拍手＞はい", []),
        ("“拍手”はい", "“拍手”はい", []),
        (r"（{\i1}声{\i0}）はい", r"{\i1}{\i0}はい", ["（声）"]),
        (r"（小さな\N声）はい", "はい", ["（小さな\n声）"]),
        ("「拍手」『拍手』はい", "「拍手」『拍手』はい", []),
        ("《（銃声）》", "《》", ["（銃声）"]),
        ("「（ダイヤル音）」", "「」", ["（ダイヤル音）"]),
        ("《（係員）こちらです》", "《こちらです》", ["（係員）"]),
        ("(岡(おか)本(もと))はい", "はい", ["(岡(おか)本(もと))"]),
        ("（岡(おか)本(もと)）はい", "はい", ["（岡(おか)本(もと)）"]),
        (r"{\pos(100,200)}（声）はい", r"{\pos(100,200)}はい", ["（声）"]),
        ("（声）はい（声）", "はい", ["（声）", "（声）"]),
        ("こんにちは", "こんにちは", []),
        ("（閉じていない", "（閉じていない", []),
    ],
)
def test_candidate_extraction(text: str, expected: str, candidates: list[str]) -> None:
    seen: list[str] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        state = cast(Payload, json.loads(request.content))["state"]
        assert state["sentence"] == pysubs2.SSAEvent(text=text).plaintext
        seen.append(state["to_check"])
        return httpx2.Response(
            200,
            json={
                "model": "test-fixture",
                "usage": {},
                "answers": {
                    "classify_sdh": {
                        "type": "choice",
                        "choice": "annotation",
                        "confidence": 1.0,
                        "probabilities": {"annotation": 1.0},
                    }
                },
            },
        )

    with TypeSafeClient(
        api_key="test-key", transport=httpx2.MockTransport(respond)
    ) as client:
        assert clean_text(text, client) == expected
    assert seen == candidates


@pytest.mark.parametrize("extension", ["srt", "ass", "vtt"])
def test_cli_preserves_dialogue_timing_and_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, extension: str
) -> None:
    source = tmp_path / f"input.{extension}"
    output = tmp_path / f"output.{extension}"
    subtitles = pysubs2.SSAFile()
    subtitles.events = [
        pysubs2.SSAEvent(start=1000, end=2000, text="（内村）（この２つで）"),
        pysubs2.SSAEvent(start=3000, end=4000, text="（拍手）"),
        pysubs2.SSAEvent(start=5000, end=6000, text="おはよう"),
    ]
    subtitles.save(source, encoding="cp932")
    original = source.read_bytes()
    seen: list[str] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        payload = cast(Payload, json.loads(request.content))
        span = payload["state"]["to_check"]
        seen.append(span)
        label = "speech" if span == "（この２つで）" else "annotation"
        return httpx2.Response(
            200,
            json={
                "model": "test-fixture",
                "usage": {},
                "answers": {
                    "classify_sdh": {
                        "type": "choice",
                        "choice": label,
                        "confidence": 1.0,
                        "probabilities": {label: 1.0},
                    }
                },
            },
        )

    client = TypeSafeClient(api_key="test-key", transport=httpx2.MockTransport(respond))

    def client_factory(**kwargs: object) -> TypeSafeClient:
        assert kwargs["model"] == "test-model"
        assert kwargs["timeout"] == 30.0
        return client

    monkeypatch.setattr(typesafe_sdk, "TypeSafeClient", client_factory)
    result = CliRunner().invoke(
        cli.app,
        [
            str(source),
            str(output),
            "--encoding",
            "cp932",
            "--model",
            "test-model",
            "--verbose",
        ],
    )
    assert result.exit_code == 0, result.output
    assert result.stdout == ""
    assert "speech" in result.stderr
    assert "annotation" in result.stderr
    assert "Changed 2 cues" in result.stderr
    assert seen == ["（内村）", "（この２つで）", "（拍手）"]
    assert source.read_bytes() == original
    cleaned = pysubs2.load(output)
    assert [(event.start, event.end, event.text) for event in cleaned] == [
        (1000, 2000, "（この２つで）"),
        (5000, 6000, "おはよう"),
    ]


def test_default_output_uses_source_stem_and_requires_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "subtitles" / "episode.ja.ass"
    source.parent.mkdir()
    subtitles = pysubs2.SSAFile()
    subtitles.events = [
        pysubs2.SSAEvent(start=1000, end=2000, text="（声）はい"),
    ]
    subtitles.save(source)
    original = source.read_bytes()
    output = source.parent / "episode.ja.keshigomu.srt"
    _ = output.write_text("KEEP ME\n" * 100, encoding="utf-8")
    before = output.read_bytes()
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)

    runner = CliRunner()
    refused = runner.invoke(cli.app, [str(source)])
    assert refused.exit_code != 0
    assert "--overwrite" in refused.stderr
    assert output.read_bytes() == before

    replaced = runner.invoke(
        cli.app,
        [str(source), "--overwrite", "--keep-sdh", "--keep-furigana"],
    )
    assert replaced.exit_code == 0, replaced.output
    assert replaced.stdout == ""
    assert [(event.start, event.end, event.text) for event in pysubs2.load(output)] == [
        (1000, 2000, "（声）はい"),
    ]
    assert b"KEEP ME" not in output.read_bytes()
    assert source.read_bytes() == original


@pytest.mark.parametrize("same_path", [False, True])
def test_refuses_to_overwrite_before_using_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, same_path: bool
) -> None:
    source = tmp_path / "source.srt"
    _ = source.write_text(
        "1\n00:00:01,000 --> 00:00:02,000\n（声）はい\n", encoding="utf-8"
    )
    output = source if same_path else tmp_path / "exists.srt"
    if not same_path:
        _ = output.write_text("KEEP ME", encoding="utf-8")
    before = output.read_bytes()
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    result = CliRunner().invoke(cli.app, [str(source), str(output)])
    assert result.exit_code != 0
    assert "exists" in result.stderr
    assert "Traceback" not in result.output
    assert output.read_bytes() == before


def test_missing_key_leaves_no_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.srt"
    output = tmp_path / "new.srt"
    _ = source.write_text(
        "1\n00:00:01,000 --> 00:00:02,000\n（声）はい\n", encoding="utf-8"
    )
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    result = CliRunner().invoke(cli.app, [str(source), str(output)])
    assert result.exit_code == 1
    assert "TYPESAFE_API_KEY" in result.stderr
    assert "Traceback" not in result.output
    assert not output.exists()


@pytest.mark.parametrize(
    "flags",
    [[], ["--keep-sdh", "--keep-furigana"]],
    ids=["defaults", "keep-both"],
)
def test_unknown_encoding_is_reported_before_creating_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flags: list[str]
) -> None:
    source = tmp_path / "source.srt"
    output = tmp_path / "new.srt"
    _ = source.write_text(
        "1\n00:00:01,000 --> 00:00:02,000\n（声）明日(あした)\n", encoding="utf-8"
    )
    original = source.read_bytes()

    def unexpected_client(**_kwargs: object) -> TypeSafeClient:
        pytest.fail("Invalid encoding must not create a client")

    monkeypatch.setattr(typesafe_sdk, "TypeSafeClient", unexpected_client)
    result = CliRunner().invoke(
        cli.app,
        [str(source), str(output), "--encoding", "not-a-codec", *flags],
    )
    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == "Error: unknown encoding: not-a-codec\n"
    assert "Traceback" not in result.output
    assert isinstance(result.exception, SystemExit)
    assert source.read_bytes() == original
    assert not output.exists()


@pytest.mark.parametrize("existing_output", [False, True])
def test_api_error_is_reported_without_partial_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, existing_output: bool
) -> None:
    source = tmp_path / "source.srt"
    output = tmp_path / "new.srt"
    _ = source.write_text(
        "1\n00:00:01,000 --> 00:00:02,000\n（声）はい\n", encoding="utf-8"
    )
    if existing_output:
        _ = output.write_text("KEEP ME", encoding="utf-8")
    client = TypeSafeClient(
        api_key="test-key",
        transport=httpx2.MockTransport(
            lambda _: httpx2.Response(401, json={"error": "unauthorized"})
        ),
    )

    def client_factory(**_kwargs: object) -> TypeSafeClient:
        return client

    monkeypatch.setattr(typesafe_sdk, "TypeSafeClient", client_factory)
    result = CliRunner().invoke(
        cli.app,
        [str(source), str(output), *(["--overwrite"] if existing_output else [])],
    )
    assert result.exit_code == 1
    assert "401" in result.stderr
    assert "Traceback" not in result.output
    if existing_output:
        assert output.read_text(encoding="utf-8") == "KEEP ME"
    else:
        assert not output.exists()


def test_ass_comments_drawings_and_styles_are_not_classified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.ass"
    output = tmp_path / "clean.ass"
    subtitles = pysubs2.SSAFile()
    subtitles.events = [
        pysubs2.SSAEvent(type="Comment", text="（制作メモ）"),
        pysubs2.SSAEvent(text=r"{\p1}m 0 0 l 10 10{\p0}"),
        pysubs2.SSAEvent(start=1000, end=2000, text=r"{\i1}おはよう{\i0}"),
        pysubs2.SSAEvent(type="Comment", text=""),
    ]
    subtitles.save(source)

    def unexpected_request(_request: httpx2.Request) -> httpx2.Response:
        pytest.fail("Non-dialogue and unbracketed text must not call TypeSafe")

    client = TypeSafeClient(
        api_key="test-key", transport=httpx2.MockTransport(unexpected_request)
    )

    def client_factory(**_kwargs: object) -> TypeSafeClient:
        return client

    monkeypatch.setattr(typesafe_sdk, "TypeSafeClient", client_factory)
    result = CliRunner().invoke(cli.app, [str(source), str(output)])
    assert result.exit_code == 0, result.output
    assert pysubs2.load(output).equals(pysubs2.load(source))
    assert "Changed 0 cues; dropped 0 empty cues." in result.stderr


@pytest.mark.parametrize("label", [None, "unexpected", "uncertain"])
def test_rejects_missing_or_unknown_classification(label: str | None) -> None:
    answers = (
        {}
        if label is None
        else {
            "classify_sdh": {
                "type": "choice",
                "choice": label,
                "confidence": 1.0,
                "probabilities": {label: 1.0},
            }
        }
    )
    client = TypeSafeClient(
        api_key="test-key",
        transport=httpx2.MockTransport(
            lambda _: httpx2.Response(
                200, json={"model": "test-fixture", "usage": {}, "answers": answers}
            )
        ),
    )
    with client, pytest.raises(TypeSafeError, match="classification"):
        _ = clean_text("（声）はい", client)
