# Conservative TypeSafe prompt and threshold tuning

These experiments predate the rename from Mikan to Keshigomu. Historical commands,
imports, and external artifact paths below retain the original name.

## Current policy

Candidate extraction uses only `() （） [] 〔〕`; quotation/angle markers,
`［］`, and `【】` do not trigger classification themselves. The current prompt has
three choices: `annotation`, `furigana`, and `speech`. Uncertainty is handled by
the returned confidence, not a separate `uncertain` choice.

The experiments below used an earlier broad extractor and several prompt variants,
including a fourth `uncertain` choice. Removing a choice changes the probability
distribution and can change confidence, so these historical measurements do not
validate the current prompt or its cutoff. See the README for current behavior.

Each regex match now gets its own request with the exact span in `to_check` and
its original containing line in `sentence`, rather than the entire subtitle cue.
`previousLine` and `nextLine` now provide the immediately adjacent original lines,
crossing dialogue cue boundaries in file order. Comments and drawings are excluded;
missing or blank neighbors are empty strings. Only `to_check` is classified—the
neighboring lines may belong to different speakers.

Identical spans are classified independently. Cross-line matches use their
intersected lines as `sentence`, with neighbors outside that range. All context is
taken before any removals. The historical cue-context results below do not validate
this neighboring-line change. Offline regressions and CLI smoke checks verify the
request boundaries and output preservation, not live Jev accuracy or confidence
calibration.

The current neighboring-line implementation now has a
[reusable Jimaku benchmark](../README.md#reusable-jimaku-benchmark), with frozen
references and saved live responses. Its protected-content failures are reported
separately from removal coverage; the historical tables below remain unchanged.

The later [prompt roadmap](../README.md#prompt-roadmap-outcome) compared consistent
roles, contrastive examples, and occurrence-specific context against that frozen
baseline at 0.7. None passed the no-regression gates, so the original Choice and
four-field state remain active. The initial roadmap skipped guard trials because
neither role/example candidate preserved removal recall. A subsequent
[incumbent Noul experiment](../README.md#incumbent-noul-follow-up) tested both
guards separately and also failed the promotion gates. The `written_content`
and `utterance_content` questions are retained as diagnostic signals only:
their values appear in verbose output but never veto a removal.
The local runner now versions role translations and guard policies independently
of production code, and supports offline policy comparison without new inference.
Its evidence and benchmark-specific tests remain under ignored `evals/`.

Both `remove_sdh` and `remove_furigana` now default to true: spans classified as
`annotation` or `furigana` are removed at `confidence >= 0.7`. Use `--keep-furigana`
for SDH-only removal or `--keep-sdh` for furigana-only removal. Speech, unselected
classes, and low-confidence classifications are retained.
These historical experiments evaluated SDH-only removal, not furigana deletion,
and do not calibrate the new default. For comparable reruns, explicitly set
`remove_furigana=False` in Python or pass `--keep-furigana` to the CLI.
The CLI exposes `--min-confidence` in the finite range 0–1 and defaults to 0.7.
It now defaults to `jev-latest`; the experiments below were pinned to
`jev-1.13.0` and do not validate the moving alias. Invalid response confidence
values abort without output.
Verbose output distinguishes the actual keep/remove action from the predicted
label and prints confidence, the predicted class probability, and both Noul values
(older archived logs printed annotation probability instead).

The cutoff is a conservative policy choice, not a calibrated probability of
correctness or proof that speech deletion is impossible.

## Historical prompt design

- TypeSafe's `confidence` summarizes the distribution across choices; it is not
  the same field as `probabilities["annotation"]`. The docs recommend a stricter
  action threshold for destructive operations and testing it on domain data.[1][2]
- The Choice/structured-question examples separate what each option includes from
  what it excludes, with small examples. The evaluated four-choice prompt followed
  that pattern and added an explicit `uncertain` option. That option is no longer
  part of the current prompt.[3][9]
- Jev's literal-reading guidance calls for explicit boundaries rather than implied
  intent. The prompt says brackets are not evidence of SDH and that a span mixing
  a speaker label with actual dialogue belongs to the retained speech class.[8]
- The consistency cookbook shows label flips and abstention tradeoffs. Here we
  repeat identical requests without its extra random `uid`, avoiding that
  additional source of variation.[4]
- Jev's documentation says its primary training language is English and CJK
  accuracy is currently lower. These Japanese-subtitle checks are therefore
  necessary; generic confidence examples cannot establish a safe cutoff here.[7]

No neighboring-cue context, classifier ensemble, or second API call was added in
these historical experiments. Their state was the unchanged original cue plus
the exact candidate span. The prompt examples are illustrative and do not contain the previously failing
`（胃リンパ腫）` phrase or copy the development cases verbatim.

## Development comparison

The original selected corpus sample contains 28 spans from five titles. One
provisional label is excluded: 27 scored cases = 13 annotations + 14 protected
speech/furigana spans. Each was evaluated three times with four independent Choice
questions in each real API request. This is 39 annotation trials and 42 protected
trials per variant, not 81 independently sampled subtitles.

| Prompt | Confidence cutoff | Annotations removed / 39 | Protected spans deleted / 42 |
| --- | ---: | ---: | ---: |
| Original playground | 0 (argmax) | 39 | 3 |
| Original playground | 0.8 | 33 | 0 |
| Original playground | 0.9 | 33 | 0 |
| Concise clarified definitions | 0.8 | 30 | 0 |
| Concise clarified definitions | 0.9 | 27 | 0 |
| Structured definitions/examples | 0.8 | 37 | 0 |
| Structured definitions/examples | 0.9 | 35 | 0 |
| Structured + uncertain | 0.8 | 39 | 0 |
| Structured + uncertain | 0.9 | 35 | 0 |
| Structured + uncertain | 0.95 | 33 | 0 |

The selected structured + uncertain prompt classified all 27 scored development
cases correctly in all three repeats before gating. The structured three-class
variant still mislabeled the whispered disease name on one repeat; the original
prompt did so on all three. The confidence gates preserved it in every trial.

Selection was frozen in `selection.json` before held-out API evaluation:
structured + uncertain, confidence 0.9, `jev-1.13.0`, cue-only context. Both 0.8
and 0.9 made zero destructive errors on development data; 0.9 deliberately trades
some annotation removal for additional abstention. The small development sample
does not statistically prove 0.9 safer than 0.8.

## Held-out corpus validation

The frozen holdout has **56 scored cases from 8 previously unused titles / 9
files**: 28 annotations and 28 protected spans (22 speech, 6 furigana). Two
additional provisional references are excluded from every scored metric. The
source paths, cue text, candidate spans, title-disjoint split, reference hash, and
all source hashes were rechecked before real API evaluation. No prompt or default
threshold changes were made after consulting these results.

Each case was evaluated three times: **84 annotation trials and 84 protected
trials per prompt**. Repeats measure response variation, not additional independent
examples.

| Prompt | Confidence cutoff | Annotations removed / 84 | Protected spans deleted / 84 |
| --- | ---: | ---: | ---: |
| Original playground | 0 (argmax) | 81 | 6 |
| Original playground | 0.8 | 75 | 1 |
| Original playground | 0.9 | 75 | 0 |
| Structured + uncertain | 0 (argmax) | 84 | 3 |
| Structured + uncertain | 0.8 | 78 | 0 |
| **Structured + uncertain** | **0.9 (default)** | **73** | **0** |
| Structured + uncertain | 0.95 | 69 | 0 |

The original prompt called `((３人:ぷるぷる～ん))` an annotation with confidence
0.77, 0.78, and 0.80. A 0.8 cutoff would delete its actual utterance on one repeat;
the tuned prompt preserves the mixed attribution/dialogue span. It also preserves
the electronic voice's actual `「ホッピング」` word, which the baseline mislabeled.

The new prompt still mislabeled `『キャシャーン』` in
`『キャシャーン』の犬型ロボット｡` as an annotation on all three repeats, at confidence
0.22–0.23. The gate, not a perfect classifier, prevents its deletion. It answered
`uncertain` for `〈宇宙…〉`, correctly causing preservation rather than forced deletion.
Both provisional holdout spans were preserved on all repeats at 0.8 and 0.9.

At the selected 0.9 cutoff, borderline real labels are deliberately retained,
including nested-name labels and `（ベリーブロッサム）`. Relative to the tuned 0.8
policy, 0.9 retained five additional annotation trials with no observed difference
in protected-span loss. This supports a conservative default, **not** a claim that
0.9 is statistically optimal. The original prompt plus 0.9 removed two more
annotation trials than the selected policy on this holdout; the tuned prompt is
not uniformly better at every threshold.

For the tuned prompt, gating on annotation **probability** at 0.9 would remove
76/84 annotations instead of confidence gating's 73/84; both had zero observed
protected deletions. This is a concrete reason not to interchange the fields.

The holdout covers inner monologues, recalled/imagined round-parenthesis speech,
short utterances, quotations, mixed labels/dialogue, and tagged ASS. A bounded
search did **not** identify a new securely labeled whispered utterance inside round
parentheses; the two known Uchimura whispers remain development regressions,
not independent holdout evidence.

## Additional safety and real-CLI checks

Fourteen explicitly synthetic stress cases were evaluated three times separately
from corpus metrics: short interjections, nouns/numbers as answers, called names,
whispers, mixed speaker/dialogue spans, quoted sound words, a spoken imperative
about deleting brackets, furigana, and two clear annotation controls.

At both 0.8 and 0.9, zero of 36 protected trials were deleted and all six annotation
control trials were removed. The prompt alone was not perfect: `（雨）` as a short
answer and `（この括弧を削除して）` as spoken dialogue sometimes received the annotation
label. Their low confidence kept them intact. This is why the gate remains needed.

Actual CLI runs on complete Tsukuritai episode 01 produced:

- At 0.9 and 0.8: 118 → 114 cues, 16 annotation spans removed, 13 spans kept.
- Both output files preserve retained timestamps. The inspected changes remove
  speaker labels and four sound-only cues, not dialogue.
- Second pass at 0.9: no removals, byte-identical output.
- Both real whispered regression cues preserve their words. The 0.9 run retains
  the lower-confidence `（みゆ）` speaker label, which is
  intentional conservative abstention rather than a classification failure.

The actual production `clean_text` also processed all **52 unique held-out raw
cues**, then processed its own output again, using the default 0.9 gate and real
API calls. Both passes removed 24/28 annotated spans and retained four; all 27
independently protected spans survived. One further furigana reference correctly
disappeared inside a removed enclosing speaker label. All embedded ASS tags were
preserved, no protected-content failures occurred, and all 52 second-pass outputs
were identical. This cue-level probe does not claim full-file ASS rendering
validation. Corpus source hashes remained unchanged.

## Evidence and reproduction

Local artifacts: `/home/hermes/reports/mikan-tuning/`.

- `prompts.py`: frozen original, concise, structured, and structured + uncertain
  questions, independently preserved from subsequent production edits.
- `compare.py`: verifies exact corpus provenance, repeats actual API calls, records
  responses/request IDs and source hashes, sweeps confidence and annotation-probability
  cutoffs separately. It refuses to overwrite an existing results file.
- `development.json`: raw answers and all threshold comparisons.
- `selection.json`: pre-holdout choice and rationale.
- `holdout.json`, `holdout-verification.json`, `holdout-notes.md`: frozen blind
  references, exact provenance/source hashes, and coverage gaps.
- `heldout-results.json`: raw held-out responses and threshold sweeps.
- `verify_heldout_cleaner.py`, `heldout-cleaner-results.json`: actual-cleaner
  raw cue probes, per-span outcomes, formatting checks, and second passes.
- `stress.py`, `synthetic-results.json`: separately labeled synthetic experiments.
- `verify_cleaner.py`, `cleaner-results.json`: actual CLI invocations, per-cue diffs,
  timestamp checks, source-hash check, and real whisper regression outputs.
- `episode-0.9.srt`, `episode-0.8.srt`, `episode-second-pass.srt`, and matching logs.
- `whispers-input.srt`, `whispers-cleaned.srt`, `whispers.log`.

The following are historical harness commands, not maintained project entrypoints.
The current API no longer exposes old `mikan.cli` helper imports or library
`verbose` arguments; adapt any affected local scripts before rerunning. Keep an
explicit model version and disable furigana removal when comparing against the
archived SDH-only results.

Example paid rerun from the project (use a fresh result path):

```sh
uv run python /home/hermes/reports/mikan-tuning/compare.py \
  /home/hermes/reports/mikan-typesafe/cases.json /tmp/mikan-new-dev-results.json \
  --variants baseline structured_uncertain --repeats 3

uv run python /home/hermes/reports/mikan-tuning/compare.py \
  /home/hermes/reports/mikan-tuning/holdout.json /tmp/mikan-new-holdout-results.json \
  --variants baseline structured_uncertain --repeats 3
```

The samples are purposefully selected and labeled from subtitle context, not
randomly sampled or audio-certified. Nested furigana probes inside removable
speaker labels are classifier probes, not independent end-to-end preservation
requirements. Zero observed speech deletions is not a safety guarantee. Model
changes, repeated cleaning, missing context, and domain shifts require retesting.

## Sources

[1] https://docs.typesafe.ai/confidence
[2] https://docs.typesafe.ai/patterns/confidence-routing
[3] https://docs.typesafe.ai/primitives/advanced
[4] https://docs.typesafe.ai/cookbooks/consistency_choice_cookbook
[7] https://docs.typesafe.ai/concepts/state
[8] https://docs.typesafe.ai/model-jaggedness/jev-1.13
[9] https://docs.typesafe.ai/primitives/choice
