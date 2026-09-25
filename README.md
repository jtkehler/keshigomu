# Keshigomu

An experimental Python library and CLI for removing bracketed Japanese subtitle
SDH annotations and furigana with [TypeSafe](https://docs.typesafe.ai/).
TypeSafe classifies spans; ordinary Python code decides which to remove.

This is a proof of concept, not a general subtitle cleaner. Review the output:
a confident model answer can still be wrong. The API is provisional.

## Run from a checkout

Requires Python 3.13+, uv, and `TYPESAFE_API_KEY` in the process environment when
classification is enabled. Keshigomu does not load a `.env` file or store credentials.

```sh
uv sync
uv run keshigomu input.srt
uv run keshigomu input.srt cleaned.srt
uv run keshigomu input.srt cleaned.srt --overwrite
uv run keshigomu input.ass cleaned.ass --verbose
uv run keshigomu input.srt cleaned.srt --keep-furigana
uv run keshigomu input.srt cleaned.srt --keep-sdh
uv run keshigomu input.srt cleaned.srt --min-confidence 0.95
uv run keshigomu input.srt cleaned.srt --encoding cp932
uv run keshigomu --help
```

- **Both SDH and furigana removal are enabled by default.** Use `--keep-sdh`
  (alias `--no-remove-sdh`) or `--keep-furigana` (alias `--no-remove-furigana`)
  to preserve either category. The corresponding positive flags are `--remove-sdh`
  and `--remove-furigana`.
- `--keep-sdh --keep-furigana` disables classification entirely; no API key or
  requests are needed. The file is still loaded and serialized, not copied byte
  for byte.
- `--min-confidence`: inclusive confidence cutoff, default **0.7**. Speech and
  lower-confidence classifications stay.
- `--model`: defaults to **`jev-latest`**. Supply an explicit model such as
  `--model jev-1.13.0` for a pinned experiment.
- `--verbose` / `-v`: show keep/remove decisions, labels, confidence, and selected
  class probabilities on stderr. Confidence, not class probability, controls removal.

Omitting the output argument writes `{input file stem}.keshigomu.srt` beside the
input (for example, `subs/episode.ja.ass` becomes `subs/episode.ja.keshigomu.srt`).
Existing outputs are refused unless `--overwrite` is supplied. The input is only
modified when explicitly selected as the output with `--overwrite`.

Output is UTF-8, with the format selected by its extension. SRT, ASS, and VTT have offline tests; other
pysubs2 formats have not been exercised. Prefer the same input/output format:
serialization can change layout, numbering, and format-specific metadata.

`uv run python -m keshigomu ...` invokes the same CLI. Summaries and diagnostics go to
stderr; stdout remains empty.

## Python API

```python
import keshigomu

# Remove both categories by default.
cleaned = keshigomu.clean_text("（ミツオ）怖(こえ)えよ！")

# Remove only SDH, keeping readings.
sdh_only = keshigomu.clean_text("（ミツオ）怖(こえ)えよ！", remove_furigana=False)

# Remove only readings, keeping SDH.
readings_only = keshigomu.clean_text("（ミツオ）怖(こえ)えよ！", remove_sdh=False)

changed, removed = keshigomu.clean_file("input.srt", "cleaned.srt")
```

Both functions accept keyword-only `remove_sdh` and `remove_furigana` booleans,
both defaulting to `True`, plus `min_confidence` and `model`.

`clean_text` returns a string. `clean_file` accepts strings or `pathlib.Path`
objects and returns `(cues_changed, cues_removed)`. Changed includes cues later
dropped because cleaning emptied their visible text. These are **cleaning
counts**, not input/output cue counts or format-conversion losses.

For multiple calls, reuse a client you own:

```python
import keshigomu
import typesafe_sdk

with typesafe_sdk.TypeSafeClient(timeout=30.0) as client:
    cleaned = keshigomu.clean_text("（声）はい", client=client)
    changed, removed = keshigomu.clean_file("input.ass", "cleaned.ass", client=client)
```

- Without `client`, Keshigomu creates and closes a client using `TYPESAFE_API_KEY`.
  File cleaning reuses one client for the whole file. Disabling both removal
  options skips client creation.
- A supplied client is never closed. The `model` argument applies only when
  Keshigomu creates a client; otherwise configure the SDK client itself.
- Non-finite/out-of-range thresholds raise `ValueError` before inference or file I/O.
- Library functions do not print or exit. They propagate Python, SDK, and parser
  exceptions and emit optional DEBUG records under `keshigomu.cleaner`; the caller
  controls logging. There is no library `verbose` parameter.
- Importing Keshigomu needs no credentials, makes no requests, and does not import
  Typer or configure the root logger. The SDK may configure its own named logger.

## How it works

All cleaning logic lives in `cleaner.py`; `cli.py` handles command-line arguments,
logging, and errors.

1. `clean_text` finds candidates delimited by `() （） [] 〔〕`. It sends each
   span's plain text, its **original containing line's** plain text, and the
   immediately preceding/following lines to a TypeSafe Choice question, which
   returns `annotation`, `furigana`, or `speech`. Uncertainty is handled through
   the returned confidence, not a separate choice.
2. A selected category is removed only at or above the confidence threshold.
   The remaining text and existing ASS tags are retained.
3. `clean_file` loads and saves with pysubs2 and uses the same per-match cleaner
   across dialogue cues. It skips comments/drawings and drops a cue only when
   cleaning empties its visible text. Retained timings are preserved.

Each regex match requires one sequential API request, even when identical spans
repeat on the same line or elsewhere in the file. Decisions are not shared.
The state has four string fields: `sentence` is the original containing line,
`to_check` is the candidate span, and `previousLine`/`nextLine` supply one original
line on either side. The neighboring lines are context only, not deletion targets.

For `clean_file`, neighbors cross dialogue cue boundaries in loaded-file order;
comments and drawings are excluded from context. For `clean_text`, neighbors are
limited to the supplied text. Blank lines are not skipped, and a missing or blank
neighbor is `""`. Context always comes from the original text, before any removals.
ASS `\N`/`\n` and literal line breaks delimit context; breaks inside complete ASS
tags do not. A cross-line match uses the lines it spans as `sentence`, with
`previousLine` before the first and `nextLine` after the last.
Verbose logs include all four fields.

With removal enabled, cues without candidates make no requests but still create
an authenticated client. The SDK handles retries; Keshigomu-created clients use a
30-second timeout.

Classification and serialization finish before opening the output for writing.
Existing outputs are refused, including creation races, unless `--overwrite` (CLI)
or `overwrite=True` (`clean_file`) is supplied. API failures leave existing outputs
unchanged and create no new output. A local disk-write failure can leave an
incomplete output file, including when overwriting.

## Deliberate limits

The current focus is a simple, readable pipeline, without separate analysis
objects or policy-replay APIs. Repeated cleaning calls classify again.

- No unbracketed SDH/music cleanup, speaker dictionary, batching, parallelism,
  or recursive parsing.
- Quotation and other markers such as `「」 『』 《》 〈〉 ［］ 【】` are not candidates.
  Supported spans inside them still qualify, and removal can leave empty wrappers.
- One level of same-bracket nesting is supported. Retained outer candidates are
  not revisited, so `--keep-sdh` can retain a reading inside a speaker label.
- Separate ASS ruby events, HTML ruby markup, and robust tag-aware extraction
  are not supported. Bracket punctuation inside embedded ASS tags remains a known
  extraction limitation.
- Identical spans on the same line have identical model state: requests do not
  include occurrence offsets. Repeated cleaning is not guaranteed idempotent
  because line context changes.
- Confidence is not a calibrated accuracy percentage. The 0.7 default is a removal
  policy, not a promise of zero dialogue loss. A cutoff of zero removes the
  confidence safeguard.

## Development

```sh
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run basedpyright
```

Tests use mocked HTTP responses to exercise the actual SDK and processing code.
They cover both removal options, confidence thresholds, client ownership, timing,
output safety, cleaning counts, and CLI streams. They do **not** measure classifier
accuracy. Public functions use Google-style docstrings; the
[Google Python Style Guide](https://google.github.io/styleguide/pyguide.html)
is the readability reference.

## Historical evaluation

[Prompt/threshold tuning](docs/tuning.md) and the
[initial evaluation](docs/evaluation.md) retain earlier live measurements. Those
runs used `jev-1.13.0`, a broader extractor, and SDH-only deletion. They are not
validation of today's `jev-latest` alias or the default of removing both
categories. The tuning report also includes a now-removed `uncertain` choice;
those results do not validate the current three-choice prompt or its cutoff.
Use `remove_furigana=False` or `--keep-furigana` for SDH-only runs.

Use an explicit model for reproducible evaluation and record the model identifier
returned by the service. The historical harnesses and corpus live outside this
repository and may need adaptation to the current API.
