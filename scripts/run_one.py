"""Запуск однієї конфігурації TLC для демонстрації наживо.

Друкує великий вердикт, статистику і, якщо TLC знайшов контрприклад,
пояснює його по кроках українською:

    крок 5  TMCrash   координатор впав
            payment=prepared inventory=prepared order=prepared | TM=init (впав)

Приклади:
    python scripts/run_one.py Full
    python scripts/run_one.py NoTMRecovery_Deadlock
    python scripts/run_one.py Mutant
    python scripts/run_one.py Mutant --save      # також оновити results/ і діаграму
    python scripts/run_one.py --list             # список конфігурацій
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common  # noqa: E402
import trace_to_puml  # noqa: E402

BIG_PASS = r"""
  ███  NO ERROR  ███   Усі властивості виконуються в кожному досяжному стані
"""
BIG_FAIL = r"""
  ███  ПОРУШЕННЯ  ███  TLC знайшов контрприклад
"""


def print_counterexample(log: str) -> None:
    """Друкує контрприклад по кроках: дія, пояснення, компактний стан."""
    steps = common.parse_trace(log)
    if not steps:
        return
    print("\nКонтрприклад (найкоротший шлях до порушення):\n")
    for step in steps:
        label = common.action_label(step)
        print(f"  крок {step.number:<3} {label:<30} {common.describe_step(step)}")
        if step.state:
            print(f"  {'':8} {common.compact_state(step.state)}")
    print()


def main() -> int:
    """Точка входу."""
    common.enable_utf8_stdout()
    parser = argparse.ArgumentParser(description="Запуск однієї конфігурації TLC (демо)")
    parser.add_argument("config", nargs="?", help="ім'я конфігурації, напр. Full або Mutant")
    parser.add_argument("--list", action="store_true", help="показати доступні конфігурації")
    parser.add_argument("--save", action="store_true", help="записати лог у results/tlc і діаграму")
    parser.add_argument("--xmx", default="4g", help="пам'ять JVM (за замовчуванням 4g)")
    args = parser.parse_args()

    if args.list or not args.config:
        print("Доступні конфігурації:")
        for c in common.TLC_CHECKS:
            exp = "No error" if c.expected == "pass" else f"порушення {c.expected_property}"
            print(f"  {c.name:<26} {c.services} серв.  очікується: {exp:<38} {c.purpose}")
        return 0

    check = common.tlc_check_by_name(args.config)
    print(f"TLC: {check.name} — {check.purpose}")
    print(f"Конфігурація: spec/configs/{check.name}.cfg   (сервісів: {check.services})")
    print("Перевіряю...", flush=True)

    proc = common.run_tlc(check.name, xmx=args.xmx)
    log = "\n".join(
        line for line in proc.output.splitlines() if not line.startswith("Picked up JAVA_TOOL_OPTIONS")
    )
    summary = common.parse_tlc_output(log)
    if summary.verdict == "violation" and summary.violated is None:
        summary.violated = common.guess_violated_property(log, common.configs_text(check.name))

    if summary.verdict == "pass":
        print(BIG_PASS)
    elif summary.verdict == "violation":
        print(BIG_FAIL)
        kind = {"invariant": "інваріант", "property": "темпоральна властивість"}.get(
            summary.kind or "", "властивість"
        )
        print(f"  Порушено: {kind} {summary.violated}")
    else:
        print("\n  ⚠ TLC завершився з помилкою. Останні рядки виводу:\n")
        print("\n".join(log.splitlines()[-20:]))
        return 1

    if summary.distinct is not None:
        print(f"  Різних станів: {summary.distinct:,}".replace(",", " "))
    if summary.depth is not None and summary.verdict == "pass":
        print(f"  Глибина графа станів: {summary.depth}")
    print(f"  Час: {proc.seconds:.1f} с")

    if summary.verdict == "violation":
        print_counterexample(log)

    expected_ok = summary.verdict == check.expected and (
        check.expected != "violation" or summary.violated == check.expected_property
    )
    if check.expected == "violation":
        note = "це ОЧІКУВАНЕ порушення" if expected_ok else "очікувалось інше порушення!"
    else:
        note = "як і очікувалось" if expected_ok else "очікувався результат No error!"
    print(f"  {'✔' if expected_ok else '✘'} {note}")

    if args.save:
        out = common.RESULTS_DIR / "tlc" / f"{check.name}.txt"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(log + "\n", encoding="utf-8")
        print(f"  Лог: {out.relative_to(common.ROOT)}")
        if summary.verdict == "violation":
            puml = trace_to_puml.trace_to_puml(log, f"Контрприклад TLC: {check.name}", summary.violated)
            dest = common.GENERATED_DIR / f"{check.name}.puml"
            dest.write_text(puml, encoding="utf-8")
            print(f"  Діаграма: {dest.relative_to(common.ROOT)}")
    return 0 if expected_ok else 1


if __name__ == "__main__":
    sys.exit(main())
