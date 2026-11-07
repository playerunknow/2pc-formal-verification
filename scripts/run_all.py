"""Запускає всі перевірки моделі 2PC і записує результати в results/.

Що робиться:
1. TLC: 8 конфігурацій зі spec/configs/ (перебір усіх станів моделі).
2. Apalache: 15 перевірок індуктивного інваріанта (3, 4, 5 сервісів)
   + 1 перевірка мутанта, яка ПОВИННА знайти помилку.
   TLAPS (якщо встановлено tlapm): доведення для довільної кількості сервісів.
3. Для кожної перевірки порівнюємо отриманий вердикт з очікуваним.
4. Пишемо:
   results/tlc/<Config>.txt        - сирі логи TLC
   results/apalache/<check>.txt    - сирі логи Apalache
   results/tlaps/TwoPhaseProofs.txt - лог TLAPS
   results/summary.json            - усе в машиночитаному вигляді
   results/summary.md              - таблиці для людей
   diagrams/generated/<Config>.puml - діаграми з контрприкладів

Код повернення: 0 - усі вердикти збіглися з очікуваними, 1 - ні.

Приклади:
    python scripts/run_all.py                 # усе
    python scripts/run_all.py --quick         # без Full_4 (~2 хв)
    python scripts/run_all.py --only tlc      # лише TLC
    python scripts/run_all.py --config Mutant # одна перевірка
"""

from __future__ import annotations

import argparse
import json
import platform
import re
import subprocess
import sys
from datetime import datetime
from datetime import timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common  # noqa: E402
import trace_to_puml  # noqa: E402

SUMMARY_JSON = common.RESULTS_DIR / "summary.json"
SUMMARY_MD = common.RESULTS_DIR / "summary.md"


def clean_log(text: str) -> str:
    """Прибирає з логу службовий рядок JVM «Picked up JAVA_TOOL_OPTIONS».

    Він залежить від машини (проксі тощо) і не має стосунку до перевірки.
    """
    return "\n".join(
        line for line in text.splitlines() if not line.startswith("Picked up JAVA_TOOL_OPTIONS")
    ) + "\n"


def run_tlc_check(check: common.TlcCheck, xmx: str, timeout: int) -> dict:
    """Запускає одну конфігурацію TLC і повертає запис для summary.json."""
    print(f"▶ TLC {check.name:<26}", end="", flush=True)
    proc = common.run_tlc(check.name, xmx=xmx, timeout=timeout)
    log = clean_log(proc.output)
    log_path = common.RESULTS_DIR / "tlc" / f"{check.name}.txt"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(log, encoding="utf-8")

    summary = common.parse_tlc_output(log)
    if proc.timed_out:
        summary.verdict = "timeout"
    if summary.verdict == "violation" and summary.violated is None:
        summary.violated = common.guess_violated_property(log, common.configs_text(check.name))

    matched = summary.verdict == check.expected
    if check.expected == "violation":
        matched = matched and summary.violated == check.expected_property
    states_match = None
    if check.reference_distinct is not None and summary.distinct is not None:
        states_match = summary.distinct == check.reference_distinct
        matched = matched and states_match

    diagram = None
    if summary.verdict == "violation":
        title = f"Контрприклад TLC: {check.name}"
        puml = trace_to_puml.trace_to_puml(log, title, summary.violated)
        if puml:
            out = common.GENERATED_DIR / f"{check.name}.puml"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(puml, encoding="utf-8")
            diagram = str(out.relative_to(common.ROOT))

    got = summary.verdict if summary.verdict != "violation" else f"violation: {summary.violated}"
    print(f"{proc.seconds:7.1f} с  {got:<40} {'✔' if matched else '✘ НЕ ЗБІГЛОСЯ'}")
    return {
        "name": check.name,
        "services": check.services,
        "purpose": check.purpose,
        "expected": check.expected,
        "expected_property": check.expected_property,
        "verdict": summary.verdict,
        "violated": summary.violated,
        "violation_kind": summary.kind,
        "distinct_states": summary.distinct,
        "generated_states": summary.generated,
        "depth": summary.depth,
        "reference_distinct": check.reference_distinct,
        "states_match": states_match,
        "seconds": round(proc.seconds, 1),
        "matched": matched,
        "log": str(log_path.relative_to(common.ROOT)),
        "diagram": diagram,
        "tlc_version": summary.tlc_version,
    }


def run_apalache_check(check: common.ApalacheCheck, timeout: int) -> dict:
    """Запускає одну перевірку Apalache і повертає запис для summary.json."""
    print(f"▶ Apalache {check.name:<38}", end="", flush=True)
    proc = common.run_apalache(check, timeout=timeout)
    log = clean_log(proc.output)
    log_path = common.RESULTS_DIR / "apalache" / f"{check.name}.txt"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(log, encoding="utf-8")
    outcome = "Timeout" if proc.timed_out else common.parse_apalache_outcome(log)
    matched = outcome == check.expected
    print(f"{proc.seconds:7.1f} с  {outcome:<10} {'✔' if matched else '✘ НЕ ЗБІГЛОСЯ'}")
    return {
        "name": check.name,
        "cinit": check.cinit,
        "services": check.services,
        "init": check.init,
        "next": check.next,
        "inv": check.inv,
        "length": check.length,
        "meaning": check.meaning,
        "expected": check.expected,
        "outcome": outcome,
        "seconds": round(proc.seconds, 1),
        "matched": matched,
        "log": str(log_path.relative_to(common.ROOT)),
    }


def run_tlaps_check(timeout: int) -> dict:
    """Перевіряє доведення spec/TwoPhaseProofs.tla (TLAPS) і повертає запис."""
    print(f"▶ TLAPS {common.PROOF_MODULE:<41}", end="", flush=True)
    proc = common.run_tlapm(timeout=timeout)
    log = clean_log(proc.output)
    log_path = common.RESULTS_DIR / "tlaps" / "TwoPhaseProofs.txt"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(log, encoding="utf-8")
    verdict, proved, total = common.parse_tlapm_output(log)
    if proc.timed_out:
        verdict = "Timeout"
    matched = verdict == "Proved"
    obligations = f"{proved}/{total}" if total is not None else "?"
    print(f"{proc.seconds:7.1f} с  {verdict} ({obligations} зобов'язань) {'✔' if matched else '✘ НЕ ЗБІГЛОСЯ'}")
    return {
        "name": "TwoPhaseProofs",
        "theorem": "Spec => [](Consistency /\\ CommitValidity /\\ FollowsTM)",
        "scope": "довільна скінченна множина RM, Mutant = FALSE",
        "expected": "Proved",
        "verdict": verdict,
        "obligations_proved": proved,
        "obligations_total": total,
        "seconds": round(proc.seconds, 1),
        "matched": matched,
        "log": str(log_path.relative_to(common.ROOT)),
        "tlapm_version": common.TLAPM_VERSION,
    }


def tool_versions() -> dict:
    """Збирає версії Java, TLC, Apalache для шапки звіту."""
    versions = {"python": platform.python_version()}
    java = common.java_cmd()
    proc = subprocess.run([java, "-version"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    m = re.search(r'version "([^"]+)"', proc.stdout)
    versions["java"] = m.group(1) if m else "?"
    versions["tlc_release"] = common.TLC_VERSION
    versions["apalache"] = common.APALACHE_VERSION
    return versions


def load_previous() -> dict:
    """Читає попередній summary.json (щоб частковий прогін не стирав решту)."""
    if SUMMARY_JSON.exists():
        try:
            return json.loads(SUMMARY_JSON.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"tlc": [], "apalache": []}


def merge(old: list[dict], new: list[dict], order: list[str]) -> list[dict]:
    """Об'єднує старі й нові записи, зберігаючи канонічний порядок перевірок."""
    by_name = {r["name"]: r for r in old}
    by_name.update({r["name"]: r for r in new})
    return [by_name[n] for n in order if n in by_name]


def fmt_int(value: int | None) -> str:
    """Число з пробілами між тисячами (28 832) або «—»."""
    return f"{value:,}".replace(",", " ") if value is not None else "—"


def write_markdown(data: dict) -> None:
    """Пише results/summary.md з таблицями результатів."""
    v = data["versions"]
    tlc_ver = next((r.get("tlc_version") for r in data["tlc"] if r.get("tlc_version")), "?")
    lines = [
        "# Результати перевірки моделі 2PC",
        "",
        "> Файл згенеровано скриптом `scripts/run_all.py` — не редагуйте вручну.",
        "",
        f"- Дата прогону: {data['generated_at']}",
        f"- TLC {tlc_ver} (реліз `{v['tlc_release']}`), Apalache {v['apalache']}, "
        f"Java {v['java']}, Python {v['python']}",
        "",
        "## TLC — перебір усіх досяжних станів",
        "",
        "| Конфігурація | Сервісів | Що перевіряє | Distinct states | Generated | Глибина | Час, с "
        "| Очікувано | Отримано | Збіг |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in data["tlc"]:
        expected = "No error" if r["expected"] == "pass" else f"порушено `{r['expected_property']}`"
        if r["verdict"] == "pass":
            got = "✔ No error"
        elif r["verdict"] == "violation":
            got = f"✘ `{r['violated']}` violated"
        else:
            got = f"⚠ {r['verdict']}"
        # Для порушень кількість станів залежить від порядку обходу воркерами.
        pass_run = r["verdict"] == "pass"
        distinct = fmt_int(r["distinct_states"]) if pass_run else "—"
        generated = fmt_int(r["generated_states"]) if pass_run else "—"
        depth = str(r["depth"]) if pass_run and r["depth"] is not None else "—"
        lines.append(
            f"| {r['name']} | {r['services']} | {r['purpose']} | {distinct} | {generated} | {depth} "
            f"| {r['seconds']} | {expected} | {got} | {'✔' if r['matched'] else '✘'} |"
        )
    lines += [
        "",
        "Для конфігурацій із порушенням кількість станів залежить від порядку обходу "
        "воркерами TLC, тому вона не наводиться (див. сирі логи в `results/tlc/`).",
        "",
        "## Apalache — індуктивний інваріант",
        "",
        "| Перевірка | Сервісів | Що доводить | init | next | inv | length | Час, с "
        "| Очікувано | Отримано | Збіг |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in data["apalache"]:
        meaning = r["meaning"].replace("|", "\\|")
        lines.append(
            f"| {r['name']} | {r['services']} | {meaning} | {r['init']} | {r['next'] or '—'} "
            f"| {r['inv']} | {r['length']} | {r['seconds']} | {r['expected']} | {r['outcome']} "
            f"| {'✔' if r['matched'] else '✘'} |"
        )
    lines += ["", "## TLAPS — доведення для довільної кількості сервісів", ""]
    tlaps = data.get("tlaps") or []
    if tlaps:
        lines += [
            "| Модуль | Теорема | Для яких RM | Зобов'язань | Час, с | Очікувано | Отримано | Збіг |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for r in tlaps:
            theorem = r["theorem"].replace("|", "\\|")
            lines.append(
                f"| {r['name']} | `{theorem}` | {r['scope']} "
                f"| {r['obligations_proved']}/{r['obligations_total']} | {r['seconds']} "
                f"| {r['expected']} | {r['verdict']} | {'✔' if r['matched'] else '✘'} |"
            )
    else:
        lines.append(
            "Не запускалось (tlapm не встановлено: `python scripts/setup_tools.py --tlaps`)."
        )
    total = data["tlc"] + data["apalache"] + tlaps
    ok = sum(1 for r in total if r["matched"])
    lines += [
        "",
        "## Підсумок",
        "",
        f"Збіглося з очікуваним: **{ok} з {len(total)}** перевірок.",
        "",
        "Порушення в `NoTMRecovery_Deadlock`, `NoTMRecovery_Termination`, `Mutant` і "
        "помилка Apalache на мутанті — **очікувані**: вони показують, що властивості "
        "сформульовані не тривіально і що без відновлення координатора 2PC блокується.",
        "",
    ]
    diagrams = [r for r in data["tlc"] if r.get("diagram")]
    if diagrams:
        lines += ["## Діаграми контрприкладів", ""]
        lines += [f"- `{r['name']}` → [`{r['diagram']}`](../{r['diagram']})" for r in diagrams]
        lines.append("")
    SUMMARY_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    """Точка входу."""
    common.enable_utf8_stdout()
    parser = argparse.ArgumentParser(description="Прогін усіх перевірок моделі 2PC")
    parser.add_argument(
        "--only", choices=["tlc", "apalache", "tlaps"], help="запустити лише один інструмент"
    )
    parser.add_argument("--quick", action="store_true", help="пропустити довгі перевірки (Full_4)")
    parser.add_argument("--config", help="запустити лише одну перевірку (ім'я TLC-конфігурації або Apalache)")
    parser.add_argument("--xmx", default="4g", help="пам'ять JVM для TLC (за замовчуванням 4g)")
    parser.add_argument(
        "--timeout", type=int, default=common.CHECK_TIMEOUT, help="тайм-аут однієї перевірки, с"
    )
    args = parser.parse_args()

    tlc_checks = list(common.TLC_CHECKS) if args.only in (None, "tlc") else []
    ap_checks = list(common.APALACHE_CHECKS) if args.only in (None, "apalache") else []
    # TLAPS - розширення: запускається, лише якщо tlapm встановлено.
    run_tlaps = args.only in (None, "tlaps") and not args.config
    if run_tlaps and not common.TLAPM_BIN.exists():
        print("ℹ TLAPS пропущено: tlapm не встановлено (python scripts/setup_tools.py --tlaps)\n")
        if args.only == "tlaps":
            return 1
        run_tlaps = False
    if args.quick:
        tlc_checks = [c for c in tlc_checks if not c.slow]
    if args.config:
        tlc_checks = [c for c in tlc_checks if c.name == args.config]
        ap_checks = [c for c in ap_checks if c.name == args.config]
        if not tlc_checks and not ap_checks:
            names = [c.name for c in common.TLC_CHECKS] + [c.name for c in common.APALACHE_CHECKS]
            common.die(f"невідома перевірка '{args.config}'. Доступні:\n  " + "\n  ".join(names))

    common.RESULTS_DIR.mkdir(exist_ok=True)
    tlc_results = []
    if tlc_checks:
        print(f"=== TLC: {len(tlc_checks)} конфігурацій ===")
        tlc_results = [run_tlc_check(c, args.xmx, args.timeout) for c in tlc_checks]
    ap_results = []
    if ap_checks:
        print(f"\n=== Apalache: {len(ap_checks)} перевірок ===")
        ap_results = [run_apalache_check(c, args.timeout) for c in ap_checks]

    tlaps_results = []
    if run_tlaps:
        print("\n=== TLAPS: доведення для довільного N ===")
        tlaps_results = [run_tlaps_check(args.timeout)]

    previous = load_previous()
    data = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "versions": tool_versions(),
        "tlc": merge(previous.get("tlc", []), tlc_results, [c.name for c in common.TLC_CHECKS]),
        "apalache": merge(
            previous.get("apalache", []), ap_results, [c.name for c in common.APALACHE_CHECKS]
        ),
        "tlaps": merge(previous.get("tlaps", []), tlaps_results, ["TwoPhaseProofs"]),
    }
    SUMMARY_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_markdown(data)

    ran = tlc_results + ap_results + tlaps_results
    bad = [r["name"] for r in ran if not r["matched"]]
    print(f"\nЗвіт: {SUMMARY_MD.relative_to(common.ROOT)}")
    if bad:
        print(f"✘ Не збіглося з очікуваним: {', '.join(bad)}")
        return 1
    print(f"✔ Усі {len(ran)} вердиктів збіглися з очікуваними.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
