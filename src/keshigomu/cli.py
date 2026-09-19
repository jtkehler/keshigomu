"""Command-line adapter for subtitle cleaning."""

import contextlib
import logging
from collections.abc import Generator
from pathlib import Path
from typing import Annotated

import pysubs2
import typer
import typesafe_sdk

from .cleaner import DEFAULT_MIN_CONFIDENCE, DEFAULT_MODEL, clean_file

app = typer.Typer(
    no_args_is_help=True,
    context_settings={"help_option_names": ["--help", "-h"]},
)


@app.command()
def main(
    source: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    output: Annotated[Path, typer.Argument(dir_okay=False)],
    model: Annotated[
        str, typer.Option(help="TypeSafe model or alias.")
    ] = DEFAULT_MODEL,
    min_confidence: Annotated[
        float,
        typer.Option(
            min=0.0,
            max=1.0,
            help="Remove selected categories only at or above this confidence.",
        ),
    ] = DEFAULT_MIN_CONFIDENCE,
    remove_sdh: Annotated[
        bool,
        typer.Option(
            "--remove-sdh/--no-remove-sdh",
            " /--keep-sdh",  # Leading space marks a negative-flag alias.
            help="Remove speaker labels and sound descriptions.",
        ),
    ] = True,
    remove_furigana: Annotated[
        bool,
        typer.Option(
            "--remove-furigana/--no-remove-furigana",
            " /--keep-furigana",
            help="Remove pronunciation readings.",
        ),
    ] = True,
    encoding: Annotated[
        str, typer.Option(help="Input encoding; output is UTF-8.")
    ] = "utf-8-sig",
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Show each classification.")
    ] = False,
) -> None:
    """Filter bracketed SDH annotations and/or furigana with TypeSafe."""
    if not 0.0 <= min_confidence <= 1.0:
        raise typer.BadParameter(
            "Confidence must be finite and between 0 and 1.",
            param_hint="--min-confidence",
        )
    if output.exists():
        raise typer.BadParameter(
            "Output already exists; choose a new path.", param_hint="output"
        )
    try:
        with _verbose_logging(verbose):
            changed, removed = clean_file(
                source,
                output,
                model=model,
                min_confidence=min_confidence,
                remove_sdh=remove_sdh,
                remove_furigana=remove_furigana,
                encoding=encoding,
            )
    except (
        typesafe_sdk.TypeSafeError,
        OSError,
        ValueError,
        LookupError,
        pysubs2.exceptions.Pysubs2Error,
    ) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from None
    typer.echo(
        f"Changed {changed} cues; dropped {removed} empty cues. Wrote {output}",
        err=True,
    )


@contextlib.contextmanager
def _verbose_logging(enabled: bool) -> Generator[None]:
    """Temporarily send Keshigomu debug records to stderr for this invocation."""
    if not enabled:
        yield
        return
    logger = logging.getLogger("keshigomu")
    handler = logging.StreamHandler()
    previous_level, previous_propagate = logger.level, logger.propagate
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    try:
        yield
    finally:
        logger.removeHandler(handler)
        handler.close()
        logger.setLevel(previous_level)
        logger.propagate = previous_propagate
