"""Run explicit live extraction evaluations against one or more Ollama models.

This is a live runner, not a pytest test. It sends real model requests through
the production ``PydanticExtractorWorker`` and compares returned values with a
small synthetic English/Polish evaluation set.

Examples:
    uv run --env-file .env python scripts/evaluate_extractor_models.py
    uv run --env-file .env python scripts/evaluate_extractor_models.py \
        --model qwen3:1.7b --model qwen3:4b --repeat 3
    uv run python scripts/evaluate_extractor_models.py --list-cases
"""

from __future__ import annotations

import argparse
import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Literal

from local_agent.config import ExtractorConfigError, load_extractor_config
from local_agent.models import WorkerRequest
from local_agent.workers.extractor import PydanticExtractorWorker

Language = Literal["en", "pl"]
Difficulty = Literal["easy", "medium", "hard"]

LOGGER = logging.getLogger("extractor-live-eval")


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    """One synthetic extraction scenario with an exact expected value."""

    case_id: str
    language: Language
    difficulty: Difficulty
    task: str
    input_text: str
    expected_value: str


@dataclass(slots=True)
class ModelSummary:
    """Aggregate results collected for one evaluated model."""

    total: int = 0
    passed: int = 0
    wrong_value: int = 0
    worker_error: int = 0
    exception: int = 0
    elapsed_seconds: float = 0.0


CASES: tuple[EvaluationCase, ...] = (
    EvaluationCase(
        case_id="en_easy_invoice",
        language="en",
        difficulty="easy",
        task="Extract the invoice number.",
        input_text="The invoice number is FV/2026/10/0042.",
        expected_value="FV/2026/10/0042",
    ),
    EvaluationCase(
        case_id="en_easy_email",
        language="en",
        difficulty="easy",
        task="Extract the email address.",
        input_text="For assistance, contact anna.smith+sales@example.com.",
        expected_value="anna.smith+sales@example.com",
    ),
    EvaluationCase(
        case_id="en_easy_order",
        language="en",
        difficulty="easy",
        task="Extract the complete order identifier.",
        input_text='The order identifier is "ORD-000742".',
        expected_value="ORD-000742",
    ),
    EvaluationCase(
        case_id="pl_easy_invoice",
        language="pl",
        difficulty="easy",
        task="Wyodrębnij numer faktury.",
        input_text="Numer faktury to FV/2026/10/0042.",
        expected_value="FV/2026/10/0042",
    ),
    EvaluationCase(
        case_id="pl_easy_email",
        language="pl",
        difficulty="easy",
        task="Wyodrębnij adres e-mail.",
        input_text="W razie pytań napisz na biuro.test+faktury@example.pl.",
        expected_value="biuro.test+faktury@example.pl",
    ),
    EvaluationCase(
        case_id="pl_easy_order",
        language="pl",
        difficulty="easy",
        task="Wyodrębnij kompletny identyfikator zamówienia.",
        input_text='Identyfikator zamówienia to "ZAM-000742".',
        expected_value="ZAM-000742",
    ),
    EvaluationCase(
        case_id="en_medium_tracking_not_order",
        language="en",
        difficulty="medium",
        task="Extract the shipment tracking identifier, not the order number.",
        input_text=(
            "Order ORD-2026-4815 was dispatched today. "
            "Its tracking identifier is TRK-0091-XY."
        ),
        expected_value="TRK-0091-XY",
    ),
    EvaluationCase(
        case_id="en_medium_gross_amount",
        language="en",
        difficulty="medium",
        task="Extract the complete gross amount, including its currency.",
        input_text="Net amount: PLN 1,000.00; gross amount: PLN 1,230.00.",
        expected_value="PLN 1,230.00",
    ),
    EvaluationCase(
        case_id="en_medium_delivery_date",
        language="en",
        difficulty="medium",
        task="Extract the promised delivery date, not the order creation date.",
        input_text=(
            "The order was created on 2026-10-22 and its promised delivery "
            "date is 2026-11-03."
        ),
        expected_value="2026-11-03",
    ),
    EvaluationCase(
        case_id="pl_medium_tracking_not_order",
        language="pl",
        difficulty="medium",
        task="Wyodrębnij numer przesyłki, a nie numer zamówienia.",
        input_text=(
            "Zamówienie ZAM-2026-4815 zostało wysłane. "
            "Numer przesyłki to PRZ-0091-XY."
        ),
        expected_value="PRZ-0091-XY",
    ),
    EvaluationCase(
        case_id="pl_medium_gross_amount",
        language="pl",
        difficulty="medium",
        task="Wyodrębnij pełną kwotę brutto razem z walutą.",
        input_text="Kwota netto: 1 000,00 PLN; kwota brutto: 1 230,00 PLN.",
        expected_value="1 230,00 PLN",
    ),
    EvaluationCase(
        case_id="pl_medium_delivery_date",
        language="pl",
        difficulty="medium",
        task="Wyodrębnij planowaną datę dostawy, a nie datę zamówienia.",
        input_text=(
            "Zamówienie utworzono 22.10.2026, natomiast planowana data "
            "dostawy to 03.11.2026."
        ),
        expected_value="03.11.2026",
    ),
    EvaluationCase(
        case_id="en_hard_replaced_reference",
        language="en",
        difficulty="hard",
        task="Extract the currently valid reference identifier.",
        input_text=(
            "Do not use reference OLD-8841. It was replaced by the currently "
            "valid reference NEW-2026-0047."
        ),
        expected_value="NEW-2026-0047",
    ),
    EvaluationCase(
        case_id="en_hard_internal_periods",
        language="en",
        difficulty="hard",
        task="Extract the complete release label without surrounding punctuation.",
        input_text='The approved release label is "release.2026.04".',
        expected_value="release.2026.04",
    ),
    EvaluationCase(
        case_id="en_hard_approved_invoice",
        language="en",
        difficulty="hard",
        task="Extract the approved invoice identifier.",
        input_text=(
            "Draft FV/2026/0019 was rejected; FV/2026/0020 was approved, "
            "while FV/2026/0021 is still awaiting review."
        ),
        expected_value="FV/2026/0020",
    ),
    EvaluationCase(
        case_id="pl_hard_replaced_reference",
        language="pl",
        difficulty="hard",
        task="Wyodrębnij aktualnie obowiązujący identyfikator referencyjny.",
        input_text=(
            "Nie używaj identyfikatora STARY-8841. Został zastąpiony przez "
            "aktualnie obowiązujący identyfikator NOWY-2026-0047."
        ),
        expected_value="NOWY-2026-0047",
    ),
    EvaluationCase(
        case_id="pl_hard_internal_periods",
        language="pl",
        difficulty="hard",
        task="Wyodrębnij pełną etykietę wydania bez otaczającej interpunkcji.",
        input_text='Zatwierdzona etykieta wydania to "wydanie.2026.04".',
        expected_value="wydanie.2026.04",
    ),
    EvaluationCase(
        case_id="pl_hard_approved_invoice",
        language="pl",
        difficulty="hard",
        task="Wyodrębnij identyfikator zatwierdzonej faktury.",
        input_text=(
            "Odrzucono szkic FV/2026/0019; zatwierdzono FV/2026/0020, "
            "a FV/2026/0021 nadal czeka na weryfikację."
        ),
        expected_value="FV/2026/0020",
    ),
)


def positive_integer(value: str) -> int:
    """Parse a command-line value that must be a positive integer."""
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be at least 1")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line interface for the live evaluation runner."""
    parser = argparse.ArgumentParser(
        description=(
            "Run live English/Polish extraction cases against one or more "
            "Ollama models. This performs real model requests."
        )
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(os.getenv("EXTRACTOR_CONFIG_PATH", "config/extractor.json")),
        help="Extractor JSON config path (default: EXTRACTOR_CONFIG_PATH or config/extractor.json).",
    )
    parser.add_argument(
        "--model",
        action="append",
        dest="models",
        help=(
            "Ollama model to evaluate. Repeat for multiple models. "
            "Defaults to the model from the JSON config."
        ),
    )
    parser.add_argument(
        "--language",
        choices=("all", "en", "pl"),
        default="all",
        help="Run cases for one language (default: all).",
    )
    parser.add_argument(
        "--difficulty",
        choices=("all", "easy", "medium", "hard"),
        default="all",
        help="Run one difficulty level (default: all).",
    )
    parser.add_argument(
        "--case",
        action="append",
        dest="case_ids",
        help="Run only this case ID. Repeat to select multiple cases.",
    )
    parser.add_argument(
        "--repeat",
        type=positive_integer,
        default=1,
        help="Number of times to run every selected case (default: 1).",
    )
    parser.add_argument(
        "--list-cases",
        action="store_true",
        help="List available cases and exit without contacting Ollama.",
    )
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default="INFO",
        help="Logging verbosity (default: INFO).",
    )
    return parser


def select_cases(args: argparse.Namespace) -> tuple[EvaluationCase, ...]:
    """Return evaluation cases matching command-line filters."""
    selected = CASES

    if args.language != "all":
        selected = tuple(case for case in selected if case.language == args.language)

    if args.difficulty != "all":
        selected = tuple(
            case for case in selected if case.difficulty == args.difficulty
        )

    if args.case_ids:
        requested_ids = set(args.case_ids)
        known_ids = {case.case_id for case in CASES}
        unknown_ids = requested_ids - known_ids
        if unknown_ids:
            unknown = ", ".join(sorted(unknown_ids))
            raise ValueError(f"Unknown case ID(s): {unknown}")
        selected = tuple(case for case in selected if case.case_id in requested_ids)

    return selected


def list_cases(cases: Sequence[EvaluationCase]) -> None:
    """Print selected case metadata without making model requests."""
    for case in cases:
        print(f"{case.case_id:34} {case.language} {case.difficulty}")


def unique_models(models: Sequence[str]) -> tuple[str, ...]:
    """Remove duplicate model names while preserving command-line order."""
    return tuple(dict.fromkeys(models))


def format_result_line(
    *,
    request_number: int,
    total_requests: int,
    status: str,
    elapsed: float | None,
    model: str,
    model_width: int,
    case: EvaluationCase,
    case_width: int,
    repetition: int,
    repeat_count: int,
) -> str:
    """Format stable, padded columns for one live evaluation event."""
    progress_width = len(str(total_requests))
    progress = f"[{request_number:0{progress_width}d}/{total_requests}]"
    duration = f"{elapsed:7.3f}s" if elapsed is not None else " " * 8
    category = f"{case.language.upper()}/{case.difficulty.upper()}"

    return (
        f"{progress} | {status:<12} | {duration} | "
        f"{model:<{model_width}} | {category:<9} | "
        f"{case.case_id:<{case_width}} | {repetition}/{repeat_count}"
    )


def run_case(
    *,
    worker: PydanticExtractorWorker,
    model: str,
    model_width: int,
    case: EvaluationCase,
    case_width: int,
    repetition: int,
    repeat_count: int,
    request_number: int,
    total_requests: int,
    summary: ModelSummary,
) -> None:
    """Execute and score one live model request."""
    LOGGER.debug(
        format_result_line(
            request_number=request_number,
            total_requests=total_requests,
            status="RUNNING",
            elapsed=None,
            model=model,
            model_width=model_width,
            case=case,
            case_width=case_width,
            repetition=repetition,
            repeat_count=repeat_count,
        )
    )

    started_at = perf_counter()
    try:
        result = worker.run(WorkerRequest(task=case.task, input_text=case.input_text))
    except Exception:
        elapsed = perf_counter() - started_at
        summary.total += 1
        summary.exception += 1
        summary.elapsed_seconds += elapsed
        LOGGER.exception(
            format_result_line(
                request_number=request_number,
                total_requests=total_requests,
                status="EXCEPTION",
                elapsed=elapsed,
                model=model,
                model_width=model_width,
                case=case,
                case_width=case_width,
                repetition=repetition,
                repeat_count=repeat_count,
            )
        )
        return

    elapsed = perf_counter() - started_at
    summary.total += 1
    summary.elapsed_seconds += elapsed

    if not result.success:
        summary.worker_error += 1
        LOGGER.error(
            "%s | error=%r",
            format_result_line(
                request_number=request_number,
                total_requests=total_requests,
                status="WORKER_ERROR",
                elapsed=elapsed,
                model=model,
                model_width=model_width,
                case=case,
                case_width=case_width,
                repetition=repetition,
                repeat_count=repeat_count,
            ),
            result.error,
        )
        return

    actual_value = result.data.get("value") if result.data is not None else None
    if actual_value == case.expected_value:
        summary.passed += 1
        LOGGER.info(
            "%s | value=%r",
            format_result_line(
                request_number=request_number,
                total_requests=total_requests,
                status="PASS",
                elapsed=elapsed,
                model=model,
                model_width=model_width,
                case=case,
                case_width=case_width,
                repetition=repetition,
                repeat_count=repeat_count,
            ),
            actual_value,
        )
        return

    summary.wrong_value += 1
    LOGGER.warning(
        "%s | expected=%r | actual=%r",
        format_result_line(
            request_number=request_number,
            total_requests=total_requests,
            status="WRONG_VALUE",
            elapsed=elapsed,
            model=model,
            model_width=model_width,
            case=case,
            case_width=case_width,
            repetition=repetition,
            repeat_count=repeat_count,
        ),
        case.expected_value,
        actual_value,
    )


def run_model(
    *,
    model: str,
    model_width: int,
    cases: Sequence[EvaluationCase],
    case_width: int,
    repeat_count: int,
    instructions: str,
    output_retries: int,
    request_timeout_seconds: float,
) -> ModelSummary:
    """Run all selected evaluations against one model."""
    total_requests = len(cases) * repeat_count
    LOGGER.info("")
    LOGGER.info(
        "MODEL %-*s | cases=%d | repeat=%d | requests=%d",
        model_width,
        model,
        len(cases),
        repeat_count,
        total_requests,
    )
    LOGGER.info("-" * (91 + model_width + case_width))
    worker = PydanticExtractorWorker(
        model=model,
        instructions=instructions,
        output_retries=output_retries,
        request_timeout_seconds=request_timeout_seconds,
    )
    summary = ModelSummary()

    request_number = 0
    for case in cases:
        for repetition in range(1, repeat_count + 1):
            request_number += 1
            run_case(
                worker=worker,
                model=model,
                model_width=model_width,
                case=case,
                case_width=case_width,
                repetition=repetition,
                repeat_count=repeat_count,
                request_number=request_number,
                total_requests=total_requests,
                summary=summary,
            )

    pass_rate = 100 * summary.passed / summary.total if summary.total else 0.0
    average_seconds = summary.elapsed_seconds / summary.total if summary.total else 0.0
    LOGGER.info(
        "DONE  %-*s | pass=%d/%d (%.1f%%) | wrong=%d | worker_error=%d | "
        "exception=%d | total=%.1fs | avg=%.1fs",
        model_width,
        model,
        summary.passed,
        summary.total,
        pass_rate,
        summary.wrong_value,
        summary.worker_error,
        summary.exception,
        summary.elapsed_seconds,
        average_seconds,
    )
    return summary


def log_comparison(summaries: dict[str, ModelSummary], *, model_width: int) -> None:
    """Log a compact comparison table after every model has finished."""
    LOGGER.info("")
    LOGGER.info("MODEL COMPARISON")
    LOGGER.info(
        "%-*s | %9s | %7s | %5s | %12s | %9s | %8s",
        model_width,
        "MODEL",
        "PASS",
        "RATE",
        "WRONG",
        "WORKER_ERROR",
        "EXCEPTION",
        "AVG TIME",
    )
    LOGGER.info("-" * (model_width + 73))

    for model, summary in summaries.items():
        pass_rate = 100 * summary.passed / summary.total if summary.total else 0.0
        average_seconds = (
            summary.elapsed_seconds / summary.total if summary.total else 0.0
        )
        LOGGER.info(
            "%-*s | %4d/%-4d | %6.1f%% | %5d | %12d | %9d | %7.1fs",
            model_width,
            model,
            summary.passed,
            summary.total,
            pass_rate,
            summary.wrong_value,
            summary.worker_error,
            summary.exception,
            average_seconds,
        )


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments, execute live evaluations, and return a process status."""
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%H:%M:%S",
    )
    LOGGER.setLevel(getattr(logging, args.log_level))
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpx2").setLevel(logging.WARNING)

    try:
        cases = select_cases(args)
    except ValueError as exc:
        parser.error(str(exc))

    if not cases:
        parser.error("No cases match the selected filters.")

    if args.list_cases:
        list_cases(cases)
        return 0

    try:
        config = load_extractor_config(args.config)
    except ExtractorConfigError as exc:
        LOGGER.error("CONFIG_ERROR path=%s error=%s", args.config, exc)
        return 2

    models = unique_models(args.models or (config.model,))
    model_width = max(20, *(len(model) for model in models))
    case_width = max(len(case.case_id) for case in cases)
    LOGGER.info(
        "EVALUATION | config=%s | models=%d | cases=%d | repeat=%d | requests=%d",
        args.config,
        len(models),
        len(cases),
        args.repeat,
        len(models) * len(cases) * args.repeat,
    )

    summaries: dict[str, ModelSummary] = {}
    try:
        for model in models:
            summaries[model] = run_model(
                model=model,
                model_width=model_width,
                cases=cases,
                case_width=case_width,
                repeat_count=args.repeat,
                instructions=config.instructions,
                output_retries=config.output_retries,
                request_timeout_seconds=config.request_timeout_seconds,
            )
    except KeyboardInterrupt:
        LOGGER.warning("EVALUATION_INTERRUPTED")
        return 130

    failed_runs = sum(
        summary.wrong_value + summary.worker_error + summary.exception
        for summary in summaries.values()
    )
    log_comparison(summaries, model_width=model_width)
    LOGGER.info(
        "COMPLETE | models=%d | failed_runs=%d",
        len(summaries),
        failed_runs,
    )
    return 1 if failed_runs else 0


if __name__ == "__main__":
    raise SystemExit(main())
