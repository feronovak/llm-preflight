"""Plain-terminal selection and readiness preview for the CLI."""

from __future__ import annotations

import json
import shlex
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contracts import check_contract, contract_fixtures_declared
from .profiles import BUILTIN_PROFILES
from .redaction import redact_secrets, without_private_fields
from .runner import select_test_profiles


@dataclass(frozen=True)
class InteractiveServices:
    resolve_models: Callable[..., Any]
    make_plan: Callable[..., Any]
    format_plan: Callable[..., str]
    format_contract: Callable[..., str]
    confirm_budget: Callable[..., bool]
    selected_numbers: Callable[..., list[int]]
    heading: Callable[..., str]
    style: Callable[..., str]
    write_json: Callable[..., None]
    command: str


class _Cancelled(Exception):
    pass


class _Back(Exception):
    pass


class _Repeat(Exception):
    pass


@dataclass
class _Edit(Exception):
    choices: dict[int, Any]
    models: list[dict[str, Any]]


def _choice(
    question: str,
    parse: Callable[[str], Any],
    input_fn: Callable[[str], str],
    output_fn: Callable[[str], None],
) -> Any:
    while True:
        answer = input_fn(question).strip()
        if answer.casefold() == "back":
            raise _Back
        try:
            return parse(answer)
        except _Repeat:
            continue
        except ValueError as exc:
            output_fn(f"Try again: {redact_secrets(str(exc))}")


def _choose_models(
    models: list[dict[str, Any]],
    services: InteractiveServices,
    input_fn: Callable[[str], str],
    output_fn: Callable[[str], None],
    color: bool,
    previous: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    def show(query: str = "") -> None:
        matches = 0
        for index, model in enumerate(models, 1):
            provider = model.get("provider", "openai_compatible")
            if query.casefold() not in f"{provider}:{model['model']}".casefold():
                continue
            matches += 1
            output_fn(
                f"  {services.style(str(index) + '.', '1;33', color)} "
                f"{services.style(provider, '36', color)}: {model['model']}"
            )
        output_fn(
            f"Showing {matches} of {len(models)} models; numbers keep their original meaning."
        )

    output_fn(services.heading("Models", "36", color))
    show()
    output_fn("Use search TEXT to filter the list; q cancels, back revisits a choice.")
    if previous is not None:
        output_fn("Enter keeps your selected models; all selects the full list.")

    def parse(model_answer: str) -> list[dict[str, Any]]:
        if (
            model_answer.casefold().startswith("search ")
            or model_answer.casefold() == "search"
        ):
            show(model_answer[6:].strip())
            raise _Repeat
        _selected_numbers = services.selected_numbers
        if not model_answer and previous is not None:
            return previous
        if not model_answer or model_answer.casefold() == "all":
            return models
        else:
            selected_indexes: set[int] = set()
            selectors = [
                item.strip() for item in model_answer.split(",") if item.strip()
            ]
            if not selectors:
                raise ValueError("choose at least one model")
            for selector in selectors:
                if selector.isdigit():
                    selected_indexes.update(_selected_numbers(selector, len(models)))
                    continue
                provider, separator, family = selector.casefold().partition("/")
                provider_matches = {
                    index
                    for index, model in enumerate(models)
                    if model.get("provider", "openai_compatible").casefold() == provider
                }
                exact_matches = {
                    index
                    for index in provider_matches
                    if separator and models[index]["model"].casefold() == family
                }
                matches = exact_matches or {
                    index
                    for index in provider_matches
                    if not separator
                    or models[index]["model"].casefold().startswith(family + "/")
                    or models[index]["model"].casefold().startswith(family + "-")
                }
                if not matches:
                    raise ValueError(f"model selector {selector!r} matched no models")
                selected_indexes.update(matches)
            return [
                model for index, model in enumerate(models) if index in selected_indexes
            ]

    chosen = _choice(
        "Select models (numbers, provider, provider/family, or all): ",
        parse,
        input_fn,
        output_fn,
    )
    output_fn(f"Selected models: {len(chosen)} of {len(models)}")
    return chosen


def _choose_tests(
    config: dict[str, Any],
    services: InteractiveServices,
    input_fn: Callable[[str], str],
    output_fn: Callable[[str], None],
    color: bool,
    previous: str | None = None,
) -> str | None:
    output_fn("")
    output_fn(services.heading("Tests", "35", color))
    output_fn(
        "  Recommended: agent-smoke — five production-shaped functional checks; excludes load."
    )
    tests = [(profile["name"], profile["description"]) for profile in BUILTIN_PROFILES]
    custom = config.get("prompts", [])
    if previous:
        output_fn(f"Previous tests: {previous}; type keep to reuse them.")
    tests.extend(
        (prompt["name"], prompt.get("description", "Custom prompt test."))
        for prompt in custom
    )
    for index, (name, description) in enumerate(tests, 1):
        output_fn(
            f"  {services.style(str(index) + '.', '1;33', color)} "
            f"{services.style(name, '1', color)} — {description}"
        )

    def parse(answer: str) -> str | None:
        if answer.casefold() == "keep" and previous:
            return previous
        if answer.casefold() == "all":
            names = [
                p["name"] for p in BUILTIN_PROFILES if "concurrency_levels" not in p
            ]
            names.extend(p["name"] for p in custom)
        elif answer:
            names = []
            for item in (part.strip() for part in answer.split(",") if part.strip()):
                if item.isdigit():
                    names.extend(
                        tests[index][0]
                        for index in services.selected_numbers(item, len(tests))
                    )
                else:
                    names.append(item)
        else:
            if "prompt" not in config:
                raise ValueError("select a custom prompt name or built-in profile")
            return None
        selector = ",".join(names)
        select_test_profiles(config, selector)
        return selector

    return _choice(
        "Select tests (numbers/names/agent-smoke/all) or Enter for the config prompt: ",
        parse,
        input_fn,
        output_fn,
    )


def _choose_repetitions(
    default: int,
    services: InteractiveServices,
    input_fn: Callable[[str], str],
    output_fn: Callable[[str], None],
    color: bool,
) -> int:
    output_fn("")
    output_fn(services.heading("Repetitions", "34", color))

    def parse(answer: str) -> int:
        try:
            value = int(answer) if answer else default
        except ValueError:
            raise ValueError("repetitions must be a positive integer") from None
        if value < 1:
            raise ValueError("repetitions must be a positive integer")
        return value

    return _choice(f"Repetitions per test [{default}]: ", parse, input_fn, output_fn)


def _choose_stop(
    services: InteractiveServices,
    input_fn: Callable[[str], str],
    output_fn: Callable[[str], None],
    color: bool,
    default: str | None = "any-fail",
) -> str | None:
    output_fn("")
    output_fn(services.heading("Stop Mode", "31", color))
    output_fn("  1. any-fail — stop after API error or TEST FAIL")
    output_fn("  2. api-error — stop only if the provider/request breaks")
    output_fn("  3. test-fail — stop on model output failure, ignore API-ok passes")
    output_fn("  4. never — run every selected model")

    def parse(answer: str) -> str | None:
        modes = {
            "": default,
            "1": "any-fail",
            "any-fail": "any-fail",
            "2": "api-error",
            "api-error": "api-error",
            "3": "test-fail",
            "test-fail": "test-fail",
            "4": None,
            "never": None,
            "none": None,
        }
        # Stop-mode answers cannot authorize execution; retain the separate confirmation.
        modes.update(dict.fromkeys(("y", "yes", "n", "no"), "any-fail"))
        if answer.casefold() not in modes:
            raise ValueError(
                "stop mode must be 1, 2, 3, 4, any-fail, api-error, test-fail, or never"
            )
        return modes[answer.casefold()]

    number = {"any-fail": "1", "api-error": "2", "test-fail": "3", None: "4"}[default]
    return _choice(f"Stop on [{number}]: ", parse, input_fn, output_fn)


def _export_config(config: dict[str, Any]) -> dict[str, Any]:
    payload = redact_secrets(without_private_fields(config))
    scopes = [(config, payload)]
    scopes.extend(zip(config.get("prompts", []), payload.get("prompts", [])))
    for original, exported in scopes:
        for field in ("validation", "validation_fixtures", "tools"):
            if field not in original:
                continue
            # Schema property names are application data, including names such
            # as password or _private. Only redact credential-shaped text here;
            # refuse a changed contract rather than export different semantics.
            safe = json.loads(redact_secrets(json.dumps(original[field])))
            if safe != original[field]:
                raise ValueError(
                    "redaction would change the contract; use synthetic fixtures "
                    "and non-secret validator values before saving"
                )
            exported[field] = safe
    return payload


def select_interactively(
    config: dict[str, Any],
    services: InteractiveServices,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
    color: bool = False,
    clear_fn: Callable[[], None] | None = None,
    selected_models: list[dict[str, Any]] | None = None,
    selected_profile_selector: str | None = None,
    prepare_only: bool = False,
    workflow: bool = False,
) -> tuple[dict[str, Any], str | None] | None:
    emit = output_fn
    output_fn = lambda message: emit(redact_secrets(message))

    def read(question: str) -> str:
        answer = input_fn(question)
        if answer.strip().casefold() in {"q", "cancel"}:
            raise _Cancelled
        return answer

    previous_choices = None
    available_models = None
    while True:
        try:
            return _select_once(
                config,
                services,
                input_fn=read,
                output_fn=output_fn,
                color=color,
                clear_fn=clear_fn,
                selected_models=selected_models,
                selected_profile_selector=selected_profile_selector,
                prepare_only=prepare_only,
                workflow=workflow,
                previous_choices=previous_choices,
                available_models=available_models,
            )
        except _Edit as edit:
            previous_choices, available_models = edit.choices, edit.models
            clear_fn = None
        except _Cancelled:
            output_fn("Cancelled.")
            return None


def _select_once(
    config: dict[str, Any],
    services: InteractiveServices,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
    color: bool = False,
    clear_fn: Callable[[], None] | None = None,
    selected_models: list[dict[str, Any]] | None = None,
    selected_profile_selector: str | None = None,
    prepare_only: bool = False,
    workflow: bool = False,
    previous_choices: dict[int, Any] | None = None,
    available_models: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], str | None] | None:
    resolve_models = services.resolve_models
    dry_run_plan = services.make_plan
    _format_dry_run_plan = services.format_plan
    _format_contract_check = services.format_contract
    confirm_interactive_budget = services.confirm_budget
    _stage_heading = services.heading
    _style = services.style
    if clear_fn:
        clear_fn()
    models = (
        available_models
        if available_models is not None
        else selected_models
        if selected_models is not None
        else resolve_models(config)
    )
    if not models:
        raise ValueError("model discovery returned no models")
    stage = 0
    choices: dict[int, Any] = dict(previous_choices or {})
    while stage < 4:
        try:
            if stage == 0:
                choices[0] = (
                    selected_models
                    if selected_models is not None
                    else _choose_models(
                        models, services, input_fn, output_fn, color, choices.get(0)
                    )
                )
            elif stage == 1:
                choices[1] = (
                    selected_profile_selector
                    if selected_profile_selector is not None
                    else _choose_tests(
                        config, services, input_fn, output_fn, color, choices.get(1)
                    )
                )
            elif stage == 2:
                selector = choices[1]
                default = choices.get(
                    2,
                    int(
                        config.get(
                            "suite_repetitions" if selector else "repetitions",
                            1 if selector else 5,
                        )
                    ),
                )
                choices[2] = _choose_repetitions(
                    default, services, input_fn, output_fn, color
                )
            else:
                choices[3] = _choose_stop(
                    services, input_fn, output_fn, color, choices.get(3, "any-fail")
                )
        except _Back:
            available = [
                index
                for index in range(stage)
                if not (index == 0 and selected_models is not None)
                and not (index == 1 and selected_profile_selector is not None)
            ]
            stage = available[-1] if available else stage
            continue
        stage += 1
    selected_models, profile_selector, repetitions, stop_on = (
        choices[index] for index in range(4)
    )

    selected_config = dict(config)
    selected_config["models"] = selected_models
    selected_config["discovery"] = []
    selected_config["repetitions"] = repetitions
    selected_config["suite_repetitions"] = repetitions
    selected_config.pop("fail_fast", None)
    if profile_selector:
        selected_config["profiles"] = profile_selector
    else:
        selected_config.pop("profiles", None)
    if stop_on:
        selected_config["stop_on"] = stop_on
    else:
        selected_config.pop("stop_on", None)
    selected_config.setdefault("save_responses", "failures")
    plan = dry_run_plan(selected_config, profile_selector)
    output_fn("")
    output_fn(_stage_heading("Run Plan", "36", color))
    for line in _format_dry_run_plan(plan).splitlines()[1:]:
        output_fn(line)
    output_fn(
        "  "
        + _style("Status:", "1;36", color)
        + " API OK means the provider returned a response; "
        + "TEST OK/FAIL means the evaluator accepted or rejected it."
    )
    if profile_selector:
        output_fn("")
        output_fn("Request breakdown per model:")
        for breakdown_item in plan["test_breakdown"]:
            output_fn(
                f"  {breakdown_item['name']}: "
                f"{breakdown_item['requests_per_model']} ({breakdown_item['details']})"
            )
        output_fn("")
    contract_ok = True
    if contract_fixtures_declared(selected_config):
        contract = check_contract(selected_config)
        output_fn(
            ("FAIL: " if not contract["ok"] else "") + _format_contract_check(contract)
        )
        contract_ok = contract["ok"]
        if not contract_ok and not (workflow or prepare_only):
            raise ValueError(
                "validation fixtures failed; correct the contract before running"
            )
    else:
        output_fn(
            "Contract fixtures: not configured; consumer correctness is unproven."
        )
    if prepare_only:
        selected_config["_interactive_action"] = "preview"
        return selected_config, profile_selector
    mock_only = all(model.get("provider") == "mock" for model in selected_models)
    if workflow:
        while True:
            output_fn(
                "Next actions: [p] preview, [s] save config, [x] export plan, [e] edit, "
                + ("[r] run local mock" if mock_only else "[r] review paid run")
                + ", [q] cancel."
            )
            action = input_fn("Next action [p]: ").strip().casefold()
            if action in {"", "p", "preview"}:
                selected_config["_interactive_action"] = "preview"
                return selected_config, profile_selector
            if action in {"q", "cancel"}:
                output_fn("Cancelled.")
                return None
            if action in {"e", "edit", "back"}:
                raise _Edit(choices, models)
            if action in {"s", "save", "x", "export"}:
                saving_config = action in {"s", "save"}
                name = "Config" if saving_config else "Plan"
                destination = input_fn(
                    f"{name} export path (Enter to go back): "
                ).strip()
                if not destination:
                    continue
                target = Path(destination).expanduser()
                try:
                    if saving_config:
                        source = config.get("_source_config_path")
                        if (
                            source
                            and target.resolve().parent != Path(source).resolve().parent
                        ):
                            raise ValueError(
                                "save the config beside the source config to preserve relative file references"
                            )
                        payload = _export_config(selected_config)
                    else:
                        payload = redact_secrets(plan)
                    services.write_json(target, payload)
                except (OSError, ValueError) as exc:
                    output_fn(f"Cannot export: {redact_secrets(str(exc))}")
                    continue
                output_fn(f"Saved {name.lower()} to {target}")
                if saving_config:
                    output_fn(
                        f"Preview again: {services.command} {shlex.quote(str(target))} --dry-run --no-env-file"
                    )
                    output_fn(
                        "Inline credentials and headers were redacted; keep credentials in environment variables for execution."
                    )
                continue
            if action in {"r", "run"}:
                if not contract_ok:
                    output_fn(
                        "Cannot run: validation fixtures failed; correct the contract or edit the selection."
                    )
                    continue
                break
            output_fn("Choose p, s, x, e, r, or q.")
    if not confirm_interactive_budget(
        selected_config,
        profile_selector,
        input_fn=input_fn,
        output_fn=output_fn,
        color=color,
    ):
        return None
    question = (
        "Run local mock benchmark? [y/N]: "
        if mock_only
        else "Run paid benchmark? [y/N]: "
    )
    confirmation_answer = input_fn(question).strip().casefold()
    if confirmation_answer not in {"y", "yes"}:
        output_fn(_style("Cancelled.", "1;33", color))
        return None
    return selected_config, profile_selector
