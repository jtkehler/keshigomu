# Keshigomu

An experimental Python library and CLI for removing bracketed Japanese subtitle
SDH annotations and furigana with [TypeSafe](https://docs.typesafe.ai/).
TypeSafe classifies spans; ordinary Python code decides which to remove.

The policy retains dialogue, narration, whispers, sung words, inner monologue,
and meaningful written content such as signs, on-screen messages, and translator
notes. SDH covers speaker labels and sound, music, or vocal-delivery descriptions.
Only supported bracketed spans are candidates; unbracketed captions are unchanged.

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
- `--verbose` / `-v`: show keep/remove decisions, labels, confidence, selected
  class probabilities, and the `speech_content` Noul probability on stderr.
  The Noul is diagnostic only and never prevents removal.

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
   The protected `speech` category also includes meaningful written-only content.
2. A selected category is removed only at or above the confidence threshold.
   The remaining text and existing ASS tags are retained.
3. `clean_file` loads and saves with pysubs2 and uses the same per-match cleaner
   across dialogue cues. It skips comments/drawings and drops a cue only when
   cleaning empties its visible text. Retained timings are preserved.

Each request also includes one independent Noul, `speech_content`:

> Does `to_check` contain any transcribed speech, sung words, or inner monologue?

High values mean the target contains such words, including brief replies,
interjections, stutters, whispers, narration, audible broadcasts, and mixed
dialogue/metadata spans. Low values mean only speaker or sound labels, music
descriptions, attached pronunciation readings, written-only text, or other caption
metadata. "Meaningful" does not mean important to the plot. For this Noul, words
read aloud from a sign count; the sign's written-only caption does not.

The wording is informed by the
[Netflix Japanese guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/215767517-Japanese-Timed-Text-Style-Guide)
(parentheses can mark both whispered words and SDH labels) and
[BBC guidance on preserving short speech](https://www.bbc.co.uk/accessibility/forproducts/guides/subtitles/#Prefer-verbatim).
The Noul is narrower than the Choice's protected `speech` category: written-only
text can be classified as `speech` while `speech_content` is low.

The Noul value is a probability of yes, not an extra confidence score or a
measurement of importance. It is requested even without verbose logging, adding
token usage but no extra API calls. It does not participate in removal decisions.
Verbose logs expose `speech_content`; a missing answer appears as `None` and does
not block cleaning.

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
uv run --no-env-file pytest -q tests
uv run --no-env-file ruff check src tests
uv run --no-env-file ruff format --check src tests
uv run --no-env-file basedpyright src tests
```

Tests use mocked HTTP responses to exercise the actual SDK and processing code.
They cover both removal options, confidence thresholds, client ownership, timing,
output safety, cleaning counts, and CLI streams. They do **not** measure classifier
accuracy. Public functions use Google-style docstrings; the
[Google Python Style Guide](https://google.github.io/styleguide/pyguide.html)
is the readability reference.

## Reusable Jimaku benchmark

These frozen references protect meaningful written-only content, including signs
and on-screen text, matching the restored Choice policy. Keep the historical
evidence unchanged; each prompt/model configuration still needs its own live run.

The entire `evals/` directory, including the runner and its tests, is ignored and
local-only; neither the benchmark code nor copyrighted subtitles is distributed.
When those local files are available, run their independent suite with
`uv run --no-env-file pytest -q evals/test_benchmark.py`.

[`evals/jimaku/cases.json`](evals/jimaku/cases.json) freezes **3,173 reviewed spans
from 16 complete files / 14 titles**: 2,919 annotations, 132 readings, and 122
protected-content spans. References include exact raw offsets, original cue
context, source hashes, review provenance, and label rationales. New labels were
curated by coding assistants before inference; other cases reuse historical
fixtures. These are subtitle-context judgments, not audio/video-certified ground
truth. Selection
deliberately includes difficult content; these are not random corpus accuracy
estimates. Previously reviewed cases are identified as regressions, not fresh
holdouts.

To benchmark the current cleaner against those frozen references:

```sh
uv run --env-file .env python evals/run.py run \
  /tmp/keshigomu-jimaku-new evals/jimaku/cases.json \
  --corpus-root "$HOME/Documents/jimaku_subtitles" \
  --model jev-1.13.0 --min-confidence 0.7
```

The runner verifies every source hash and complete extraction coverage **before
any API calls**, then cleans byte-identical frozen copies. Source subtitles stay
untouched. Requests are sequential within each file; `--workers` defaults to four
concurrent files. Omitted model/cutoff options follow the production defaults.
`--categories sdh` or `--categories furigana` selects just that removal category.

Each run saves frozen references/sources, the actual question and code/version
fingerprints, raw request/response records with request IDs, resolved models,
confidence/probabilities, reported token usage, latency, cleaned files, reference
outputs, and per-case/file/class/split metrics. Partial or failed files are
reported separately and excluded from accuracy. Latencies count logical SDK
calls, including retries; intermediate retry usage/attempt counts are unavailable.
Raw capture uses the private `_request` hook in `typesafe-sdk` 0.7.0; revalidate
the recorder when upgrading the SDK.

Change only the cutoff or removal categories without spending more inference:

```sh
uv run --no-env-file python evals/run.py score \
  /tmp/keshigomu-jimaku-new --min-confidence 0.9
```

`score` needs neither the original corpus nor credentials, and uses the recorded
question/responses rather than today's prompt. Run directories and score files
refuse overwrite. Exit status 1 means action errors or failed files; inspect the
report to distinguish model mistakes from operational failures.

New runs use schema 2: they freeze the complete question map, its model-role to
archival-label translation, and active preservation-guard cutoffs. The archival
labels stay `annotation`, `furigana`, and `speech`; `speech` includes **all**
protected content, not only utterances. Missing-schema/schema-1 runs retain
identity labels, no guards, and their original report shape.

Compare complete runs offline without changing the confidence policy:

```sh
TYPESAFE_API_KEY= uv run --no-env-file python evals/run.py compare \
  evals/jimaku/baseline-neighbors-0.7 /tmp/keshigomu-jimaku-new \
  /tmp/keshigomu-comparison.json
```

`compare` requires matching references/source bytes, resolved `jev-1.13.0`,
complete responses, and passing recorded-action replay. At confidence 0.7 it
checks both-enabled, SDH-only, and furigana-only modes. Promotion requires strictly
fewer protected deletions, no new false-deletion IDs in any mode, and no loss of
true removals per removable gold class or single-category mode. Eligible policies
rank by protected losses, SDH recall, reading recall, fewer questions, then lower
guard cutoffs. A completed comparison exits 0 even when no policy qualifies;
invalid/incomplete evidence exits 2. Its output file must not exist.

For historical runs that recorded a `written_content` or `utterance_content` guard,
`compare --sweep-guard QUESTION_ID` evaluates cutoffs 0.00 through 0.49 while
holding every other cutoff fixed. It loads evidence once and makes no API calls.
`score --max-written-content VALUE` and `--max-utterance-content VALUE` override
only already-recorded guards. Schema-2 score filenames include the policy digest;
schema-1 filenames remain unchanged. Production records only the diagnostic
`speech_content` Noul and has **no active guards**. Diagnostic-only runs cannot use
guard cutoff overrides.

The recorded [0.7 baseline](evals/jimaku/baseline-neighbors-0.7/report.json) used
`jev-latest`, resolved to `jev-1.13.0`: **2,913/3,051 desired removals**, but
**38/122 protected spans deleted** (36 screen-text/translation-note spans, one
whisper, one lyric). Rescoring at 0.9 retains more annotations and still deletes
23 protected spans. High aggregate accuracy does not establish speech safety.
See [the benchmark summary](evals/jimaku/summary.json) for threshold comparisons,
exact failures, and corpus coverage. Changing the prompt/model requires a new
live run. Changing the intended policy also requires separately reviewed reference
labels; do not overwrite the frozen fixture.

### Prompt roadmap outcome

The [local roadmap evidence](evals/jimaku/prompt-roadmap-ekak_zph/selection.json)
retained the then-incumbent Choice and four-field context. Every live candidate completed
all 16 files and 3,173 spans, pinned to `jev-1.13.0` at confidence 0.7:

| Configuration | Protected deletions, both | True SDH removals, SDH-only | True reading removals, reading-only | Decision |
| --- | ---: | ---: | ---: | --- |
| Incumbent baseline | 38 | 2,788 | 125 | Retained |
| Consistent roles, original examples | 8 | 2,483 | 130 | Rejected: recall loss and new disabled-category deletion |
| Contrastive examples | 8 | 2,439 | 130 | Rejected: recall loss and new disabled-category deletion |
| Occurrence context on incumbent | 39 | 2,770 | 128 | Rejected: recall loss and two new protected deletion IDs |

Neither role/example candidate met the recall floors, so the written-content and
utterance veto experiments were skipped: a veto cannot recover missed removals.
Occurrence context passed the synthetic repeated-target check but failed its
separate zero-corpus-regression gate. Identical same-line targets therefore remain
ambiguous in production. The incumbent was replayed through actual `clean_file`
with saved SDK responses across all 16 files and three category modes; request
state/questions, rendered output, counts, and source hashes matched.

### Incumbent Noul follow-up

The [follow-up evidence](evals/jimaku/incumbent-nouls-e1p7dikh/selection.json)
tested each Noul separately on the incumbent Choice and state, again on all
3,173 spans with `jev-1.13.0` and confidence 0.7:

| Configuration | Correct removals | Protected deletions |
| --- | ---: | ---: |
| Frozen incumbent | 2,913 | 38 |
| Written-content veto at 0.49 | 2,910 | 29 |
| Utterance-content veto at 0.49 | 2,671 | 39 |

Neither guard passed the strict promotion gates at any cutoff from 0.00 to 0.49.
Choice answers varied from the archive despite unchanged instructions and state.
Holding each run's Choice answers fixed, the written veto saved nine protected
spans without blocking a correct removal; the utterance veto saved one but blocked
241 correct removals. Both old questions have since been replaced by the single
diagnostic `speech_content` Noul, **without a veto**. The Choice has been restored
to the incumbent wording above; its combination with `speech_content` has not had
a full benchmark run. The later speech-content gating experiment used the
now-reverted written-text-as-SDH wording and excluded written-only spans.

These are development/regression measurements on the same assistant-curated
subtitle-context labels, not a new blind holdout, audio/video-certified truth, a
general safety guarantee, or validation of future `jev-latest` versions.

## Historical evaluation

[Prompt/threshold tuning](docs/tuning.md) and the
[initial evaluation](docs/evaluation.md) retain earlier live measurements. Those
runs used `jev-1.13.0`, a broader extractor, and SDH-only deletion. They are not
validation of today's `jev-latest` alias or the default of removing both
categories. The tuning report also includes a now-removed `uncertain` choice;
those results do not validate the current three-choice prompt or its cutoff.
Use `remove_furigana=False` or `--keep-furigana` for SDH-only runs.

Use an explicit model for reproducible evaluation and record the model identifier
returned by the service. Some older historical harnesses live outside this
repository and may need adaptation; `evals/run.py` is the maintained runner.
