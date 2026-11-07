"""Перетворює контрприклад TLC у PlantUML sequence-діаграму.

Вхід:  лог TLC із контрприкладом (наприклад results/tlc/Mutant.txt).
Вихід: .puml файл (наприклад diagrams/generated/Mutant.puml).

Кожна дія з траси стає стрілкою або нотаткою:
    RMPrepare(r)   -> r -> Координатор: Prepared (так)
    TMCommit       -> Координатор -> усім: Commit
    TMCrash        -> червона нотатка «Координатор впав»
    LoseMsg        -> «повідомлення загублено»
    Stuttering     -> «далі нічого не відбувається (нескінченно)»
    Back to state  -> «цикл»
У кінці - нотатка з підсумковим станом і назвою порушеної властивості.

Запуск:
    python scripts/trace_to_puml.py results/tlc/Mutant.txt -o diagrams/generated/Mutant.puml
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common  # noqa: E402

TM = "TM"  # аліас учасника «Координатор» на діаграмі
NET = "NET"  # аліас учасника «Мережа»


def alias(service: str) -> str:
    """Безпечний аліас PlantUML для імені сервісу."""
    return "RM_" + "".join(ch if ch.isalnum() else "_" for ch in service)


def services_from_trace(steps: list[common.TraceStep]) -> list[str]:
    """Повертає імена сервісів у порядку, в якому їх друкує TLC."""
    for step in steps:
        rm = common.parse_function(step.state.get("rmState", ""))
        if rm:
            return list(rm)
    return []


def step_lines(step: common.TraceStep, services: list[str]) -> list[str]:
    """Повертає рядки PlantUML для одного кроку траси."""
    r = step.args[0] if step.args else None
    a = alias(r) if r else None
    num = f"<b>{step.number}.</b> "
    act = step.action
    everyone = [alias(s) for s in services]

    if act == "Initial predicate":
        return [f"note over {TM}, {everyone[-1]}: {num}Старт: усі сервіси у стані working"]
    if act == "RMPrepare":
        return [
            f"note over {a}: {num}записав PREPARED у журнал",
            f"{a} -> {NET}: Prepared (так)",
        ]
    if act == "RMResend":
        return [f"{a} -> {NET}: {num}Prepared (повторно)"]
    if act == "RMChooseToAbort":
        return [f"note over {a} #FFE0B2: {num}голос «ні» → aborted"]
    if act == "TMRcvPrepared":
        return [f"{NET} -> {TM}: {num}Prepared від {r}"]
    if act == "TMCommit":
        return [
            f"note over {TM} #C8E6C9: {num}рішення COMMIT записано в журнал",
            f"{TM} -> {NET}: Commit (усім)",
        ]
    if act == "TMAbort":
        return [
            f"note over {TM} #FFE0B2: {num}тайм-аут: рішення ABORT",
            f"{TM} -> {NET}: Abort (усім)",
        ]
    if act == "TMResend":
        return [f"{TM} -> {NET}: {num}рішення повторно"]
    if act == "RMRcvCommit":
        return [
            f"{NET} -> {a}: {num}Commit",
            f"note over {a} #C8E6C9: committed",
        ]
    if act == "RMRcvAbort":
        return [
            f"{NET} -> {a}: {num}Abort",
            f"note over {a} #FFE0B2: aborted",
        ]
    if act == "TMCrash":
        return [f"note over {TM} #FFCDD2: {num}<color:#B71C1C><b>Координатор впав</b></color>"]
    if act == "TMRecover":
        return [f"note over {TM} #BBDEFB: {num}Координатор відновився з журналу"]
    if act == "RMCrash":
        return [f"note over {a} #FFCDD2: {num}<color:#B71C1C><b>{r} впав</b></color>"]
    if act == "RMRecover":
        return [f"note over {a} #BBDEFB: {num}{r} відновився з журналу"]
    if act == "LoseMsg":
        what = r or "?"
        return [f"note over {NET} #FFCDD2: {num}повідомлення {what} загублено"]
    if act == "Done":
        return [f"note over {TM}, {everyone[-1]}: {num}транзакцію завершено"]
    if act == "Stuttering":
        return [
            f"... <b>{step.number}.</b> далі нічого не відбувається (нескінченно) ...",
        ]
    if act == "Back to state":
        back = step.back_to if step.back_to is not None else "?"
        return [f"... <b>{step.number}.</b> цикл: повернення до стану {back} і так без кінця ..."]
    return [f"note over {TM}: {num}{act}"]


def final_note(steps: list[common.TraceStep], services: list[str], violated: str) -> list[str]:
    """Нотатка з підсумковим станом і назвою порушеної властивості."""
    last = next((s for s in reversed(steps) if s.state), None)
    lines = [f"note across #FFF9C4", f"<b>Порушено: {violated}</b>"]
    if last is not None:
        rm = common.parse_function(last.state.get("rmState", ""))
        up = common.parse_function(last.state.get("rmUp", ""))
        for name in services:
            mark = "" if up.get(name, "TRUE") == "TRUE" else " (впав)"
            lines.append(f"{name} = {rm.get(name, '?')}{mark}")
        tm = last.state.get("tmState", "?").strip('"')
        tm_mark = "" if last.state.get("tmUp", "TRUE") == "TRUE" else " (впав)"
        lines.append(f"координатор = {tm}{tm_mark}")
    lines.append("end note")
    return lines


def trace_to_puml(text: str, title: str, violated: str | None = None) -> str:
    """Будує текст .puml із логу TLC. Повертає порожній рядок, якщо траси немає."""
    steps = common.parse_trace(text)
    if not steps:
        return ""
    if violated is None:
        violated = common.parse_tlc_output(text).violated or "?"
    services = services_from_trace(steps)

    out = [
        "@startuml",
        "!include ../_style.iuml",
        f"title {title}\\n<size:14>згенеровано автоматично з контрприкладу TLC</size>",
        "",
        f'participant "Координатор" as {TM}',
        f'queue "Мережа" as {NET}',
    ]
    out += [f'participant "{s}" as {alias(s)}' for s in services]
    out.append("")
    for step in steps:
        out += step_lines(step, services)
    if violated.startswith("DeadlockFree"):
        # Інваріант відсутності блокування порушено в останньому стані:
        # з нього не можливий жоден крок протоколу.
        out.append("... жоден крок протоколу більше неможливий: сервіси чекають вічно ...")
    out.append("")
    out += final_note(steps, services, violated)
    out.append("@enduml")
    return "\n".join(out) + "\n"


def main() -> int:
    """Точка входу."""
    common.enable_utf8_stdout()
    parser = argparse.ArgumentParser(description="Контрприклад TLC -> PlantUML sequence diagram")
    parser.add_argument("log", type=Path, help="лог TLC із контрприкладом")
    parser.add_argument("-o", "--output", type=Path, help="куди записати .puml")
    parser.add_argument("--title", help="заголовок діаграми")
    args = parser.parse_args()

    text = args.log.read_text(encoding="utf-8", errors="replace")
    title = args.title or f"Контрприклад: {args.log.stem}"
    puml = trace_to_puml(text, title)
    if not puml:
        print(f"У {args.log} немає контрприкладу.", file=sys.stderr)
        return 1
    out = args.output or common.GENERATED_DIR / f"{args.log.stem}.puml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(puml, encoding="utf-8")
    print(f"Записано {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
