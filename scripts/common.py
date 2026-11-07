"""Спільні функції для скриптів репозиторію.

Тут зібрано все, що потрібно кільком скриптам одразу:
- шляхи до папок репозиторію та інструментів;
- версії та URL інструментів (TLC, Apalache, PlantUML);
- перелік перевірок і очікуваних вердиктів;
- запуск зовнішніх процесів (Java) з тайм-аутом;
- розбір логів TLC і Apalache;
- розбір контрприкладу TLC на кроки та словник «дія -> пояснення».

Лише стандартна бібліотека Python 3.10+.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

# ---------------------------------------------------------------------------
# Шляхи
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[1]
SPEC_DIR = ROOT / "spec"
CONFIG_DIR = SPEC_DIR / "configs"
TOOLS_DIR = ROOT / "tools"
RESULTS_DIR = ROOT / "results"
DIAGRAMS_DIR = ROOT / "diagrams"
GENERATED_DIR = DIAGRAMS_DIR / "generated"
RENDERED_DIR = DIAGRAMS_DIR / "rendered"

# ---------------------------------------------------------------------------
# Інструменти. Прямі URL на releases/download (API GitHub може віддавати 403).
# ---------------------------------------------------------------------------

TLC_VERSION = "v1.8.0"
TLC_URL = (
    "https://github.com/tlaplus/tlaplus/releases/download/"
    f"{TLC_VERSION}/tla2tools.jar"
)
TLC_JAR = TOOLS_DIR / "tla2tools.jar"

APALACHE_VERSION = "v0.50.3"
APALACHE_URL = (
    "https://github.com/apalache-mc/apalache/releases/download/"
    f"{APALACHE_VERSION}/apalache.tgz"
)
APALACHE_DIR = TOOLS_DIR / "apalache"

PLANTUML_VERSION = "1.2024.8"
PLANTUML_URL = (
    "https://github.com/plantuml/plantuml/releases/download/"
    f"v{PLANTUML_VERSION}/plantuml-{PLANTUML_VERSION}.jar"
)
PLANTUML_JAR = TOOLS_DIR / "plantuml.jar"

# TLAPS (tlapm) - необов'язковий інструмент для доведення для довільного N.
# Бінарний реліз є лише для Linux x86_64 (на Windows - через WSL).
TLAPM_VERSION = "1.6.0-pre"
TLAPM_URL = (
    "https://github.com/tlaplus/tlapm/releases/download/"
    f"{TLAPM_VERSION}/tlapm-{TLAPM_VERSION}-x86_64-linux-gnu.tar.gz"
)
TLAPM_DIR = TOOLS_DIR / "tlapm"
TLAPM_BIN = TLAPM_DIR / "tlapm" / "bin" / "tlapm"
PROOF_MODULE = "TwoPhaseProofs.tla"

# Тайм-аут однієї перевірки (секунди) - 15 хвилин.
CHECK_TIMEOUT = 15 * 60


def apalache_jar() -> Path | None:
    """Повертає шлях до jar-файлу Apalache у tools/apalache або None.

    Архів apalache.tgz розпаковується у tools/apalache/apalache/...,
    сам jar лежить у підпапці lib/. Шукаємо його рекурсивно, щоб не
    залежати від точної структури архіву.
    """
    if not APALACHE_DIR.exists():
        return None
    for jar in sorted(APALACHE_DIR.rglob("apalache.jar")):
        return jar
    return None


# ---------------------------------------------------------------------------
# Перелік перевірок і очікувані вердикти
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TlcCheck:
    """Одна конфігурація TLC.

    name      - ім'я конфігурації (файл spec/configs/<name>.cfg);
    services  - кількість мікросервісів у моделі;
    expected  - "pass" або "violation";
    expected_property - яка властивість має бути порушена (для "violation");
    slow      - True для довгих перевірок (пропускаються з --quick);
    purpose   - короткий опис українською;
    reference_distinct - еталонна кількість різних станів (лише для "pass":
                якщо перебір повний, число не залежить від порядку обходу).
    """

    name: str
    services: int
    expected: str
    expected_property: str | None
    slow: bool
    purpose: str
    reference_distinct: int | None = None


TLC_CHECKS: list[TlcCheck] = [
    TlcCheck("Full_2", 2, "pass", None, False, "повна модель, 2 сервіси: S1-S5, L1-L3", 1840),
    TlcCheck("Full", 3, "pass", None, False, "повна модель, 3 сервіси: S1-S5, L1-L3", 28832),
    TlcCheck("Full_4", 4, "pass", None, True, "повна модель, 4 сервіси: S1-S5, L1-L3", 477760),
    TlcCheck("NoFailures", 3, "pass", None, False, "без збоїв: усе + L4", 163),
    TlcCheck(
        "NoTMRecovery_Safety",
        3,
        "pass",
        None,
        False,
        "координатор не відновлюється: safety зберігається",
        28828,
    ),
    TlcCheck(
        "NoTMRecovery_Deadlock",
        3,
        "violation",
        "DeadlockFreeNoTMRecovery",
        False,
        "координатор не відновлюється: очікується блокування (L1)",
    ),
    TlcCheck(
        "NoTMRecovery_Termination",
        3,
        "violation",
        "Termination",
        False,
        "координатор не відновлюється: очікується незавершення (L2)",
    ),
    TlcCheck(
        "Mutant",
        3,
        "violation",
        "Consistency",
        False,
        "зламаний координатор: очікується частковий коміт (S2)",
    ),
]


@dataclass(frozen=True)
class ApalacheCheck:
    """Одна перевірка Apalache.

    name     - унікальне ім'я (файл results/apalache/<name>.txt);
    cinit    - оператор ініціалізації констант (ConstInit, ConstInit4, ...);
    services - кількість мікросервісів;
    init     - стартовий предикат (Init або IndInv);
    next     - відношення переходів або None (тоді --length=0);
    inv      - інваріант, що перевіряється;
    length   - довжина виконання (0 або 1);
    expected - "NoError" або "Error";
    meaning  - що саме доводить перевірка.
    """

    name: str
    cinit: str
    services: int
    init: str
    next: str | None
    inv: str
    length: int
    expected: str
    meaning: str


def _apalache_checks() -> list[ApalacheCheck]:
    """Будує список 15 + 1 перевірок Apalache з розділу 3.2 ТЗ."""
    checks: list[ApalacheCheck] = []
    for cinit, n in (("ConstInit", 3), ("ConstInit4", 4), ("ConstInit5", 5)):
        checks += [
            ApalacheCheck(
                f"{cinit}_InitImpliesIndInv", cinit, n, "Init", None, "IndInv", 0,
                "NoError", "Init => IndInv",
            ),
            ApalacheCheck(
                f"{cinit}_Inductive", cinit, n, "IndInv", "Next", "IndInv", 1,
                "NoError", "IndInv /\\ Next => IndInv'",
            ),
            ApalacheCheck(
                f"{cinit}_IndInvImpliesConsistency", cinit, n, "IndInv", None,
                "Consistency", 0, "NoError", "IndInv => Consistency",
            ),
            ApalacheCheck(
                f"{cinit}_IndInvImpliesCommitValidity", cinit, n, "IndInv", None,
                "CommitValidity", 0, "NoError", "IndInv => CommitValidity",
            ),
            ApalacheCheck(
                f"{cinit}_IndInvImpliesFollowsTM", cinit, n, "IndInv", None,
                "FollowsTM", 0, "NoError", "IndInv => FollowsTM",
            ),
        ]
    checks.append(
        ApalacheCheck(
            "ConstInitMutant_Inductive", "ConstInitMutant", 3, "IndInv", "Next",
            "IndInv", 1, "Error", "мутант: IndInv НЕ індуктивний (очікувано)",
        )
    )
    return checks


APALACHE_CHECKS: list[ApalacheCheck] = _apalache_checks()

# ---------------------------------------------------------------------------
# Запуск процесів
# ---------------------------------------------------------------------------


@dataclass
class ProcResult:
    """Результат запуску зовнішнього процесу."""

    returncode: int | None
    output: str
    seconds: float
    timed_out: bool = False


def run_process(cmd: list[str], cwd: Path, timeout: int = CHECK_TIMEOUT) -> ProcResult:
    """Запускає команду, збирає stdout+stderr в один рядок, міряє час.

    Якщо процес не встиг за timeout секунд - він зупиняється, а в
    результаті timed_out=True (сам скрипт при цьому не падає).
    """
    start = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return ProcResult(proc.returncode, proc.stdout, time.monotonic() - start)
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout or ""
        if isinstance(out, bytes):
            out = out.decode("utf-8", errors="replace")
        return ProcResult(None, out, time.monotonic() - start, timed_out=True)


def java_cmd() -> str:
    """Повертає шлях до java або завершує скрипт зрозумілою помилкою."""
    java = shutil.which("java")
    if java is None:
        die(
            "Java не знайдено. Потрібна Java 17+.\n"
            "  Ubuntu/Debian: sudo apt install openjdk-21-jre-headless"
        )
    return java


def die(message: str, code: int = 2) -> None:
    """Друкує помилку і завершує скрипт із заданим кодом."""
    print(f"ПОМИЛКА: {message}", file=sys.stderr)
    sys.exit(code)


# ---------------------------------------------------------------------------
# Запуск TLC
# ---------------------------------------------------------------------------


def tlc_workers(config: str) -> str:
    """Скільки потоків дати TLC для конфігурації.

    Там, де очікується порушення, - один потік: тоді обхід у ширину
    детермінований і TLC щоразу видає той самий найкоротший контрприклад
    (зручно для демонстрації і для документації). Такі перевірки тривають
    1-3 секунди, тож швидкість не страждає. Для решти - "auto".
    """
    for check in TLC_CHECKS:
        if check.name == config and check.expected == "violation":
            return "1"
    return "auto"


def run_tlc(config: str, xmx: str = "4g", timeout: int = CHECK_TIMEOUT) -> ProcResult:
    """Запускає TLC для конфігурації spec/configs/<config>.cfg.

    Запуск іде з папки spec/, щоб TLC знайшов модулі TwoPhase і
    MCTwoPhase. Службові файли TLC (states/, *_TTrace_*.tla) пишуться у
    тимчасову папку через -metadir, щоб не смітити в репозиторії.
    """
    if not TLC_JAR.exists():
        die("tools/tla2tools.jar не знайдено. Спершу: python scripts/setup_tools.py")
    with tempfile.TemporaryDirectory(prefix="tlc-meta-") as meta:
        cmd = [
            java_cmd(),
            "-XX:+UseParallelGC",
            f"-Xmx{xmx}",
            "-cp",
            str(TLC_JAR),
            "tlc2.TLC",
            "-workers",
            tlc_workers(config),
            # Фіксовані поліном відбитків і seed: інакше TLC обирає їх
            # випадково, і контрприклад liveness може відрізнятися між прогонами.
            "-fp",
            "1",
            "-seed",
            "1",
            "-metadir",
            meta,
            "-noGenerateSpecTE",
            "-config",
            f"configs/{config}.cfg",
            "MCTwoPhase.tla",
        ]
        return run_process(cmd, cwd=SPEC_DIR, timeout=timeout)


@dataclass
class TlcSummary:
    """Те, що ми витягаємо з логу TLC."""

    verdict: str  # "pass" | "violation" | "error" | "timeout"
    violated: str | None = None
    kind: str | None = None  # "invariant" | "property" | "deadlock"
    distinct: int | None = None
    generated: int | None = None
    depth: int | None = None
    seconds: float | None = None
    tlc_version: str | None = None


def parse_tlc_output(text: str) -> TlcSummary:
    """Розбирає лог TLC: вердикт, порушену властивість, статистику."""
    summary = TlcSummary(verdict="error")

    m = re.search(r"TLC2 Version (\S+(?: of \S+ \S+ \S+)?)", text)
    if m:
        summary.tlc_version = m.group(1)

    m = re.search(r"Invariant (\w+) is violated", text)
    if m:
        summary.verdict, summary.violated, summary.kind = "violation", m.group(1), "invariant"
    m = re.search(r"Temporal property (\w+) was violated", text)
    if m and summary.verdict != "violation":
        summary.verdict, summary.violated, summary.kind = "violation", m.group(1), "property"
    if "Temporal properties were violated" in text and summary.verdict != "violation":
        # Старіші версії TLC не називають властивість - його визначить
        # guess_violated_property() за конфігурацією.
        summary.verdict, summary.kind = "violation", "property"
    m = re.search(r"Action property (\w+) is violated", text)
    if m and summary.verdict != "violation":
        summary.verdict, summary.violated, summary.kind = "violation", m.group(1), "property"
    if "Deadlock reached" in text and summary.verdict != "violation":
        summary.verdict, summary.violated, summary.kind = "violation", "Deadlock", "deadlock"
    if "Model checking completed. No error has been found." in text:
        summary.verdict = "pass"

    m = re.findall(
        r"([\d,]+) states generated, ([\d,]+) distinct states found", text
    )
    if m:
        gen, dist = m[-1]
        summary.generated = int(gen.replace(",", ""))
        summary.distinct = int(dist.replace(",", ""))
    m = re.search(r"The depth of the complete state graph search is (\d+)", text)
    if m:
        summary.depth = int(m.group(1))
    return summary


def guess_violated_property(text: str, cfg_text: str) -> str | None:
    """Якщо TLC не назвав порушену темпоральну властивість явно - здогадуємось.

    Коли в конфігурації одна PROPERTY, порушена саме вона.
    """
    m = re.search(r"^PROPERTIES?\s+(.+)$", cfg_text, flags=re.MULTILINE)
    if m:
        props = m.group(1).split()
        if len(props) == 1:
            return props[0]
    return None


# ---------------------------------------------------------------------------
# Запуск Apalache
# ---------------------------------------------------------------------------


def run_apalache(check: ApalacheCheck, timeout: int = CHECK_TIMEOUT) -> ProcResult:
    """Запускає одну перевірку Apalache з власним --out-dir у тимчасовій папці."""
    jar = apalache_jar()
    if jar is None:
        die("Apalache не знайдено у tools/apalache. Спершу: python scripts/setup_tools.py")
    with tempfile.TemporaryDirectory(prefix="apalache-out-") as out_dir:
        cmd = [
            java_cmd(),
            "-Xmx4g",
            "-jar",
            str(jar),
            f"--out-dir={out_dir}",
            "check",
            f"--cinit={check.cinit}",
            f"--init={check.init}",
        ]
        if check.next:
            cmd.append(f"--next={check.next}")
        cmd += [f"--inv={check.inv}", f"--length={check.length}", "TwoPhase.tla"]
        return run_process(cmd, cwd=SPEC_DIR, timeout=timeout)


def parse_apalache_outcome(text: str) -> str:
    """Повертає NoError / Error / іншу стрічку з 'The outcome is: ...'."""
    m = re.search(r"The outcome is: (\w+)", text)
    return m.group(1) if m else "Unknown"


# ---------------------------------------------------------------------------
# Запуск TLAPS
# ---------------------------------------------------------------------------


def run_tlapm(timeout: int = CHECK_TIMEOUT) -> ProcResult:
    """Перевіряє доведення spec/TwoPhaseProofs.tla за допомогою tlapm.

    --cleanfp - не використовувати кеш попередніх доведень (перевірити все
    заново). Кеш .tlacache пишемо в тимчасову копію папки spec/, щоб не
    смітити в репозиторії.
    """
    if not TLAPM_BIN.exists():
        die("tlapm не знайдено. Встановіть: python scripts/setup_tools.py --tlaps")
    with tempfile.TemporaryDirectory(prefix="tlaps-") as tmp:
        for name in ("TwoPhase.tla", PROOF_MODULE):
            shutil.copy(SPEC_DIR / name, Path(tmp) / name)
        return run_process([str(TLAPM_BIN), "--cleanfp", PROOF_MODULE], cwd=Path(tmp), timeout=timeout)


def parse_tlapm_output(text: str) -> tuple[str, int | None, int | None]:
    """Повертає (вердикт, доведено, усього) з виводу tlapm.

    Вердикт: "Proved" (усі зобов'язання доведено) або "Failed".
    """
    m = re.search(r"All (\d+) obligations? proved", text)
    if m:
        n = int(m.group(1))
        return "Proved", n, n
    m = re.search(r"(\d+)/(\d+) obligations? failed", text)
    if m:
        failed, total = int(m.group(1)), int(m.group(2))
        return "Failed", total - failed, total
    return "Failed", None, None


# ---------------------------------------------------------------------------
# Розбір контрприкладу TLC
# ---------------------------------------------------------------------------


@dataclass
class TraceStep:
    """Один крок контрприкладу TLC.

    number  - номер стану (State N);
    action  - ім'я дії (TMCrash, RMPrepare, ...) або "Initial predicate";
    args    - аргументи дії, якщо їх вдалося відновити (напр. ["payment"]);
    state   - значення змінних після кроку (сирі рядки TLA+);
    special - None, "stuttering" або "back" (повернення в стан N - цикл).
    back_to - номер стану, до якого повертається цикл (для special="back").
    """

    number: int
    action: str
    args: list[str] = field(default_factory=list)
    state: dict[str, str] = field(default_factory=dict)
    special: str | None = None
    back_to: int | None = None


_STATE_HEADER = re.compile(r"^(\d+): <(.+?)>\s*$")
_STUTTER = re.compile(r"^(\d+): Stuttering\s*$")
_BACK = re.compile(r"^(\d+): Back to state:? ?(\d+)?")
_ACTION = re.compile(r"^(\w+)(?:\((.*?)\))?(?: line \d+.*)?$")
_VAR = re.compile(r"^(?:/\\ )?(\w+) = (.*)$")


def parse_trace(text: str) -> list[TraceStep]:
    """Розбирає контрприклад із логу TLC у список кроків.

    TLC друкує кожен стан як
        State N: <ActionName line L, col C to line L2, col C2 of module X>
        /\\ var1 = value
        /\\ var2 = value
    Для циклу в liveness-контрприкладі в кінці буде "Back to state: K",
    для «зупинки» - "Stuttering". Значення змінних можуть займати кілька
    рядків (довгі множини) - склеюємо їх до наступного "/\\ ".
    """
    steps: list[TraceStep] = []
    current: TraceStep | None = None
    last_var: str | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.replace("State ", "", 1) if line.startswith("State ") else None
        if stripped is not None:
            m = _STATE_HEADER.match(stripped)
            if m:
                header = m.group(2)
                args: list[str] = []
                if header.startswith("Initial predicate"):
                    action = "Initial predicate"
                else:
                    # Нові версії TLC друкують аргументи: RMPrepare("payment")
                    am = _ACTION.match(header)
                    action = am.group(1) if am else header.split(" ")[0]
                    if am and am.group(2):
                        args = [a.strip().strip('"') for a in am.group(2).split(",")]
                current = TraceStep(int(m.group(1)), action, args=args)
                steps.append(current)
                last_var = None
                continue
            m = _STUTTER.match(stripped)
            if m:
                steps.append(TraceStep(int(m.group(1)), "Stuttering", special="stuttering"))
                current, last_var = None, None
                continue
            m = _BACK.match(stripped)
            if m:
                back = int(m.group(2)) if m.group(2) else None
                steps.append(
                    TraceStep(int(m.group(1)), "Back to state", special="back", back_to=back)
                )
                current, last_var = None, None
                continue
        if current is None:
            continue
        if not line.strip():
            current, last_var = None, None
            continue
        m = _VAR.match(line.strip())
        if m and (line.startswith("/\\") or line.strip().startswith("/\\") or last_var is None):
            last_var = m.group(1)
            current.state[last_var] = m.group(2).strip()
        elif last_var is not None:
            current.state[last_var] += " " + line.strip()
    _infer_args(steps)
    return steps


def parse_function(value: str) -> dict[str, str]:
    """Розбирає функцію TLA+ виду [payment |-> "prepared", order |-> TRUE].

    Також підтримує форму (\"payment\" :> \"prepared\" @@ ...), яку TLC
    друкує для функцій з рядковими ключами.
    """
    result: dict[str, str] = {}
    for key, val in re.findall(r'"?(\w+)"?\s*\|->\s*("?[\w-]+"?)', value):
        result[key] = val.strip('"')
    if not result:
        for key, val in re.findall(r'"(\w+)"\s*:>\s*("?[\w-]+"?)', value):
            result[key] = val.strip('"')
    return result


def parse_set_of_strings(value: str) -> list[str]:
    """Розбирає множину рядків {"payment", "order"} у список."""
    return re.findall(r'"([\w-]+)"', value)


def parse_msgs(value: str) -> list[tuple[str, str]]:
    """Розбирає множину повідомлень у список (type, rm)."""
    result = []
    for rec in re.findall(r"\[([^\]]*)\]", value):
        t = re.search(r'type\s*\|->\s*"(\w+)"', rec)
        r = re.search(r'rm\s*\|->\s*"([\w-]+)"', rec)
        if t:
            result.append((t.group(1), r.group(1) if r else "-"))
    return result


def _infer_args(steps: list[TraceStep]) -> None:
    """Відновлює аргумент дії (який сервіс) за різницею сусідніх станів.

    TLC друкує лише ім'я дії без аргументів, тому для RMPrepare(r) тощо
    дивимось, у якого сервісу змінився rmState / rmUp, або яке
    повідомлення з'явилось/зникло, або хто додався в tmPrepared.
    """
    prev: TraceStep | None = None
    for step in steps:
        if step.special or not step.state:
            continue
        if step.args:  # TLC уже надрукував аргументи
            prev = step
            continue
        if prev is not None and step.action.startswith(("RM", "TMRcvPrepared", "LoseMsg")):
            changed: list[str] = []
            for var in ("rmState", "rmUp"):
                a = parse_function(prev.state.get(var, ""))
                b = parse_function(step.state.get(var, ""))
                changed += [k for k in b if a.get(k) != b.get(k) and k not in changed]
            if step.action == "TMRcvPrepared":
                a = set(parse_set_of_strings(prev.state.get("tmPrepared", "")))
                b = set(parse_set_of_strings(step.state.get("tmPrepared", "")))
                changed = sorted(b - a)
            if step.action == "RMResend":
                a = set(parse_msgs(prev.state.get("msgs", "")))
                b = set(parse_msgs(step.state.get("msgs", "")))
                changed = sorted(r for _, r in b - a)
            if step.action == "LoseMsg":
                a = set(parse_msgs(prev.state.get("msgs", "")))
                b = set(parse_msgs(step.state.get("msgs", "")))
                lost = sorted(a - b)
                changed = [f"{t}:{r}" if r != "-" else t for t, r in lost]
            step.args = changed[:1]
        prev = step


# Пояснення дій українською (для run_one.py і діаграм).
ACTION_TEXT: dict[str, str] = {
    "Initial predicate": "початковий стан: усі сервіси працюють, транзакція почалась",
    "TMRcvPrepared": "координатор отримав голос «так» від {r}",
    "TMCommit": "координатор вирішив COMMIT, записав у журнал і розіслав",
    "TMAbort": "координатор вирішив ABORT (тайм-аут) і розіслав",
    "TMResend": "координатор повторно розіслав своє рішення",
    "TMCrash": "координатор впав",
    "TMRecover": "координатор відновився з журналу",
    "RMPrepare": "{r} підготувався: записав PREPARED у журнал і голосує «так»",
    "RMChooseToAbort": "{r} відмовився (голос «ні»)",
    "RMResend": "{r} повторно надіслав голос «так»",
    "RMRcvCommit": "{r} отримав COMMIT і зафіксував транзакцію",
    "RMRcvAbort": "{r} отримав ABORT і відкотив транзакцію",
    "RMCrash": "{r} впав",
    "RMRecover": "{r} відновився з журналу",
    "LoseMsg": "мережа загубила повідомлення {r}",
    "Done": "транзакцію завершено, нічого не змінюється",
    "Stuttering": "далі нічого не відбувається (нескінченно)",
    "Back to state": "цикл: система повертається в стан {r} і так без кінця",
}


def describe_step(step: TraceStep) -> str:
    """Повертає українське пояснення кроку."""
    template = ACTION_TEXT.get(step.action, step.action)
    arg = step.args[0] if step.args else "?"
    if step.special == "back":
        arg = str(step.back_to) if step.back_to is not None else "?"
    return template.format(r=arg)


def action_label(step: TraceStep) -> str:
    """Повертає ім'я дії з аргументом, напр. RMPrepare("payment")."""
    if step.args and not step.special:
        return f'{step.action}("{step.args[0]}")'
    return step.action


def compact_state(state: dict[str, str]) -> str:
    """Компактний рядок стану: payment=prepared ... | TM=init (впав)."""
    rm = parse_function(state.get("rmState", ""))
    up = parse_function(state.get("rmUp", ""))
    parts = []
    for name, value in rm.items():
        mark = "" if up.get(name, "TRUE") == "TRUE" else " (впав)"
        parts.append(f"{name}={value}{mark}")
    tm = state.get("tmState", "?").strip('"')
    tm_mark = "" if state.get("tmUp", "TRUE") == "TRUE" else " (впав)"
    return " ".join(parts) + f" | TM={tm}{tm_mark}"


def configs_text(name: str) -> str:
    """Повертає текст конфігурації spec/configs/<name>.cfg."""
    return (CONFIG_DIR / f"{name}.cfg").read_text(encoding="utf-8")


def tlc_check_by_name(name: str) -> TlcCheck:
    """Шукає конфігурацію TLC за іменем або завершує скрипт з помилкою."""
    for check in TLC_CHECKS:
        if check.name == name:
            return check
    names = ", ".join(c.name for c in TLC_CHECKS)
    die(f"невідома конфігурація '{name}'. Доступні: {names}")
    raise AssertionError  # для type checker


def enable_utf8_stdout() -> None:
    """Вмикає UTF-8 для виводу в консоль (актуально для Windows)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
