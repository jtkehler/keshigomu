"""Public Python API tests; only HTTP responses are mocked."""

import json
import subprocess
import sys
from pathlib import Path
from typing import cast, override

import httpx2
import pysubs2
import pytest
import typesafe_sdk
from typesafe_sdk import TypeSafeClient, TypeSafeError

import keshigomu


def respond(request: httpx2.Request) -> httpx2.Response:
    payload = cast(dict[str, dict[str, str]], json.loads(request.content))
    span = payload["state"]["to_check"]
    label = {
        "（声）": "annotation",
        "（拍手）": "annotation",
        "(あした)": "furigana",
    }.get(span, "speech")
    return httpx2.Response(
        200,
        json={
            "model": "offline-fixture",
            "usage": {},
            "answers": {
                "classify_sdh": {
                    "type": "choice",
                    "choice": label,
                    "confidence": 0.95,
                    "probabilities": {label: 1.0},
                }
            },
        },
    )


def test_public_text_api_returns_text_without_printing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with TypeSafeClient(
        api_key="test-key", transport=httpx2.MockTransport(respond)
    ) as client:
        assert keshigomu.clean_text("（声）はい（内緒）", client) == "はい（内緒）"
        # A supplied client remains usable and is still owned by the caller.
        assert keshigomu.clean_text("（声）もう一度", client) == "もう一度"
    assert capsys.readouterr() == ("", "")


def test_import_needs_neither_cli_nor_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, keshigomu; assert callable(keshigomu.clean_text); "
            + "assert 'keshigomu.cli' not in sys.modules; assert 'typer' not in sys.modules",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == result.stderr == ""


def test_python_module_entrypoint_help_needs_no_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    result = subprocess.run(
        [sys.executable, "-m", "keshigomu", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--min-confidence" in result.stdout
    assert "jev-latest" in result.stdout
    assert result.stderr == ""


class TrackedTransport(httpx2.MockTransport):
    closed: bool = False

    @override
    def close(self) -> None:
        self.closed = True
        super().close()


def test_text_api_creates_and_closes_its_own_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = TrackedTransport(respond)
    client = TypeSafeClient(api_key="test-key", transport=transport)

    def factory(**_kwargs: object) -> TypeSafeClient:
        return client

    monkeypatch.setattr(typesafe_sdk, "TypeSafeClient", factory)
    assert keshigomu.clean_text("（声）はい") == "はい"
    assert transport.closed


@pytest.mark.parametrize("extension", ["srt", "ass", "vtt"])
def test_file_api_preserves_source_and_returns_counts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], extension: str
) -> None:
    source = tmp_path / f"input.{extension}"
    output = tmp_path / f"output.{extension}"
    subtitles = pysubs2.SSAFile()
    subtitles.events = [
        pysubs2.SSAEvent(start=1000, end=2000, text="（声）はい（内緒）明日(あした)"),
        pysubs2.SSAEvent(start=3000, end=4000, text="（拍手）"),
        pysubs2.SSAEvent(start=5000, end=6000, text="おはよう"),
    ]
    subtitles.save(source, encoding="cp932")
    original = source.read_bytes()
    with TypeSafeClient(
        api_key="test-key", transport=httpx2.MockTransport(respond)
    ) as client:
        changed, removed = keshigomu.clean_file(
            str(source), output, client=client, encoding="cp932"
        )
        assert (changed, removed) == (2, 1)
        assert keshigomu.clean_text("（声）はい", client) == "はい"
    assert capsys.readouterr() == ("", "")
    assert source.read_bytes() == original
    assert [(event.start, event.end, event.text) for event in pysubs2.load(output)] == [
        (1000, 2000, "はい（内緒）明日"),
        (5000, 6000, "おはよう"),
    ]


def test_file_context_skips_non_dialogue_and_preserves_dropped_neighbors(
    tmp_path: Path,
) -> None:
    source = tmp_path / "input.ass"
    output = tmp_path / "output.ass"
    subtitles = pysubs2.SSAFile()
    subtitles.events = [
        pysubs2.SSAEvent(type="Comment", text="（冒頭メモ）"),
        pysubs2.SSAEvent(start=1000, end=2000, text="（拍手）"),
        pysubs2.SSAEvent(type="Comment", text="（制作メモ）"),
        pysubs2.SSAEvent(text=r"{\p1}m 0 0 l 10 10{\p0}"),
        pysubs2.SSAEvent(start=3000, end=4000, text=r"（声）\Nはい"),
        pysubs2.SSAEvent(start=5000, end=6000, text=r"つづき\N（声）また"),
        pysubs2.SSAEvent(start=7000, end=8000, text="（内緒）"),
        pysubs2.SSAEvent(type="Comment", text="（末尾メモ）"),
    ]
    subtitles.save(source)
    original = source.read_bytes()
    states: list[dict[str, str]] = []

    def record(request: httpx2.Request) -> httpx2.Response:
        state = cast(dict[str, dict[str, str]], json.loads(request.content))["state"]
        states.append(state)
        return respond(request)

    with TypeSafeClient(
        api_key="test-key", transport=httpx2.MockTransport(record)
    ) as client:
        assert keshigomu.clean_file(source, output, client=client) == (3, 1)
        assert keshigomu.clean_text("（声）単独", client) == "単独"

    assert states == [
        {
            "previousLine": "",
            "sentence": "（拍手）",
            "nextLine": "（声）",
            "to_check": "（拍手）",
        },
        {
            "previousLine": "（拍手）",
            "sentence": "（声）",
            "nextLine": "はい",
            "to_check": "（声）",
        },
        {
            "previousLine": "つづき",
            "sentence": "（声）また",
            "nextLine": "（内緒）",
            "to_check": "（声）",
        },
        {
            "previousLine": "（声）また",
            "sentence": "（内緒）",
            "nextLine": "",
            "to_check": "（内緒）",
        },
        {
            "previousLine": "",
            "sentence": "（声）単独",
            "nextLine": "",
            "to_check": "（声）",
        },
    ]
    assert source.read_bytes() == original
    cleaned = pysubs2.load(output)
    assert [
        (event.start, event.end, event.text)
        for event in cleaned
        if not (event.is_comment or event.is_drawing)
    ] == [
        (3000, 4000, r"\Nはい"),
        (5000, 6000, r"つづき\Nまた"),
        (7000, 8000, "（内緒）"),
    ]
    assert [
        (event.type, event.start, event.end, event.text)
        for event in cleaned
        if event.is_comment or event.is_drawing
    ] == [
        (event.type, event.start, event.end, event.text)
        for event in subtitles
        if event.is_comment or event.is_drawing
    ]


@pytest.mark.parametrize("fail_second", [False, True])
def test_owned_file_client_closes_even_after_partial_processing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    fail_second: bool,
) -> None:
    source = tmp_path / "input.srt"
    output = tmp_path / "output.srt"
    original = "1\n00:00:01,000 --> 00:00:02,000\n（声）はい\n\n2\n00:00:03,000 --> 00:00:04,000\n（拍手）\n"
    _ = source.write_text(original, encoding="utf-8")
    requests: list[httpx2.Request] = []

    def response(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        if fail_second and len(requests) == 2:
            return httpx2.Response(401, json={"error": "offline fixture"})
        return respond(request)

    transport = TrackedTransport(response)
    client = TypeSafeClient(api_key="test-key", transport=transport)

    def factory(**_kwargs: object) -> TypeSafeClient:
        return client

    monkeypatch.setattr(typesafe_sdk, "TypeSafeClient", factory)
    if fail_second:
        with pytest.raises(TypeSafeError):
            _ = keshigomu.clean_file(source, output, model="custom-model")
        assert not output.exists()
    else:
        # A stricter threshold preserves both 0.95-confidence annotations.
        changed, removed = keshigomu.clean_file(
            source, output, model="custom-model", min_confidence=0.99
        )
        assert (changed, removed) == (0, 0)
        assert [e.text for e in pysubs2.load(output)] == ["（声）はい", "（拍手）"]
    assert source.read_text(encoding="utf-8") == original
    assert len(requests) == 2
    assert transport.closed
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("same_path", [False, True])
def test_file_api_refuses_existing_output_without_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    same_path: bool,
) -> None:
    source = tmp_path / "input.srt"
    _ = source.write_text(
        "1\n00:00:01,000 --> 00:00:02,000\n（声）はい\n", encoding="utf-8"
    )
    output = source if same_path else tmp_path / "output.srt"
    if not same_path:
        _ = output.write_text("keep me", encoding="utf-8")
    before = output.read_bytes()
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with pytest.raises(FileExistsError):
        _ = keshigomu.clean_file(source, output)
    assert output.read_bytes() == before


def test_file_api_does_not_overwrite_output_created_during_classification(
    tmp_path: Path,
) -> None:
    source = tmp_path / "input.srt"
    output = tmp_path / "output.srt"
    _ = source.write_text(
        "1\n00:00:01,000 --> 00:00:02,000\n（声）はい\n", encoding="utf-8"
    )

    def response(request: httpx2.Request) -> httpx2.Response:
        _ = output.write_text("created by another writer", encoding="utf-8")
        return respond(request)

    transport = TrackedTransport(response)
    with TypeSafeClient(api_key="test-key", transport=transport) as client:
        with pytest.raises(FileExistsError):
            _ = keshigomu.clean_file(source, output, client=client)
        assert not transport.closed
    assert output.read_text(encoding="utf-8") == "created by another writer"


@pytest.mark.parametrize("threshold", [-0.1, 1.1, float("nan"), float("inf")])
def test_file_api_validates_threshold_before_creating_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    threshold: float,
) -> None:
    def unexpected_client(**_kwargs: object) -> TypeSafeClient:
        pytest.fail("Invalid threshold must not create a client")

    monkeypatch.setattr(typesafe_sdk, "TypeSafeClient", unexpected_client)
    output = tmp_path / "output.srt"
    with pytest.raises(ValueError, match="confidence"):
        _ = keshigomu.clean_file(
            tmp_path / "input.srt", output, min_confidence=threshold
        )
    assert not output.exists()


@pytest.mark.parametrize("owned", [False, True])
def test_text_client_ownership_after_failure(
    monkeypatch: pytest.MonkeyPatch, owned: bool
) -> None:
    requests: list[httpx2.Request] = []

    def response(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx2.Response(401, json={"error": "offline fixture"})
        return respond(request)

    transport = TrackedTransport(response)
    client = TypeSafeClient(api_key="test-key", transport=transport)

    def factory(**_kwargs: object) -> TypeSafeClient:
        return client

    monkeypatch.setattr(typesafe_sdk, "TypeSafeClient", factory)
    try:
        with pytest.raises(TypeSafeError):
            _ = keshigomu.clean_text("（声）はい", None if owned else client)
        assert transport.closed is owned
        if not owned:
            assert keshigomu.clean_text("（声）はい", client) == "はい"
            assert not transport.closed
    finally:
        client.close()
