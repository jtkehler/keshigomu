# Initial live Jimaku corpus check (historical baseline)

These experiments predate the rename from Mikan to Keshigomu. Historical commands,
imports, and external artifact paths below retain the original name.

This report describes the original three-class, no-threshold implementation.
The current prompt and confidence-gated behavior are documented in [tuning.md](tuning.md).

## Verdict: PARTIAL

The requested regex → TypeSafe → deletion pipeline works, including the known
whispered `（この２つで）` case, but cue-only classification can still delete speech.
The original playground question was used unchanged; no prompt tuning or threshold
selection was performed on this sample.

## Scope

Run on 2026-09-18 with the real TypeSafe API, pinned to `jev-1.13.0`.

- 28 selected spans across 5 source files/titles from `/mnt/hermes/jimaku_subtitles`:
  Uchimura Summers Second, Shin Kamen Rider, Tsukuritai Onna to Tabetai Onna,
  Berserk Golden Age Arc II, and Ultraman Omega.
- 27 scored reference labels: 13 annotation, 5 furigana, 9 speech.
- One quoted social-media comment was provisionally labeled speech and excluded
  from scoring because subtitle-only context does not establish whether it was
  read aloud. The model preserved it.
- Labels were curated from Japanese subtitle context, not checked against audio.
  This is a selected safety smoke sample, not a random or human-certified benchmark.
- Every sample was re-verified against its original parsed cue and exact candidate.
  All five files parsed; source hashes were unchanged after testing. No whole-corpus
  parse or accuracy claim is made.

## Classification results

| Reference | Correct | Total |
| --- | ---: | ---: |
| annotation | 13 | 13 |
| furigana | 5 | 5 |
| speech | 8 | 9 |
| Total | 26 | 27 |

The sole scored error was Uchimura cue 1022:

```text
sentence: （内村）（胃リンパ腫）
to_check: （胃リンパ腫）
expected: speech
actual: annotation
probabilities: annotation 0.63, speech 0.34, furigana 0.03
confidence: 0.45
```

The surrounding cues establish that the disease name is being whispered in a
message-passing game. The model receives only the current cue, so it lacks that
context. A separate live call through `clean_text` confirmed that the complete
cue becomes empty. Do not treat a working pipeline as safe unattended cleaning.

Two furigana cases are nested inside removable speaker labels. They were evaluated
separately as classifier probes; the CLI extracts the enclosing label as a whole,
not both overlapping spans. Their removal with the enclosing annotation is intended.

## Real cleaning checks

The actual cleaner was exercised on seven selected raw cues, including nested
speaker labels, furigana, the whisper case, and tag-heavy ASS. These probes were
unchanged on a second pass. The whisper cue produced:

```text
Before: （内村）（この２つで）\N（みゆ）はい
After:  （この２つで）\Nはい
```

A complete, byte-identical copy of Tsukuritai episode 01 was processed using the
actual `uv run mikan` CLI:

- Input: 118 cues. Output: 114 cues.
- 29 classifications in the first pass; approximately 3.89 seconds for the CLI run.
- 15 source cues changed: 11 retained cues lost speaker annotations and 4 sound-only
  cues were removed. Inspection found only speaker/sound annotations in those edits.
- Retained timestamps were verified against the input in order.
- Second pass: 13 classifications, no cue changes, byte-identical serialized output.
- Unbracketed music symbols and spans crossing cue boundaries remain, as expected.

This is evidence for those files and cases only. Neither idempotence nor a low
confidence score proves that speech will be preserved on other subtitles.

## Local evidence and reproduction

Artifacts are outside the minimal project, at `/home/hermes/reports/mikan-typesafe/`:

- `evaluate.py`: live evaluation script; uses the project's actual question/cleaner.
- `cases.json`: exact source paths, 1-based cue indices, spans, labels, and rationales.
- `results.json`: actual API responses, request IDs, confusion counts, source hashes,
  raw cleaning probes, and per-cue complete-file diffs.
- `input.srt`, `cleaned.srt`, `second-pass.srt`: complete-file input/output copies.
- `cleaned.srt.log`, `second-pass.srt.log`: actual CLI classification logs.

The archived harness targets an earlier API. Before repeating this paid experiment,
adapt old `mikan.cli` helper imports and library `verbose` arguments. Set
`remove_furigana=False` (or CLI `--keep-furigana`) to retain the SDH-only policy;
both categories are now removed by default. Then copy
`evaluate.py` and `cases.json` to a fresh directory and run
`uv run python /path/to/fresh/evaluate.py` from this project.
It deliberately refuses to overwrite existing outputs. Original corpus paths must
still exist. The script imports the current project prompt/cleaner, so rerunning it
now tests the tuned version, not this archived baseline. Results may vary across
requests/model versions. The tuning harness also freezes the baseline question.

## Recommendation from this initial experiment

Try neighboring-cue context and a conservative keep-on-uncertainty policy on a
larger held-out sample. The one error had low confidence, but choosing a cutoff
from that single example would overstate the evidence. The proof of concept
intentionally retains the requested three-class argmax behavior.
