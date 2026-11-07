"""Завантаження інструментів верифікації у папку tools/.

Що робить скрипт:
1. Перевіряє, що встановлена Java 17+ (вона потрібна лише як рантайм).
2. Завантажує (якщо ще немає):
   - TLC (tla2tools.jar) - перевірка моделі TLA+ перебором станів;
   - Apalache (apalache.tgz -> tools/apalache/) - символьна перевірка (SMT);
   - PlantUML (plantuml.jar) - рендер діаграм;
   - з прапорцем --tlaps: TLAPS (tlapm) - доведення теорем (лише Linux x86_64).
3. Друкує версії інструментів.

Запуск:
    python scripts/setup_tools.py          # завантажити те, чого немає
    python scripts/setup_tools.py --tlaps  # + TLAPS (доведення для довільного N)
    python scripts/setup_tools.py --force  # перезавантажити все
"""

from __future__ import annotations

import argparse
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common  # noqa: E402

MIN_JAVA = 17


def java_version() -> int | None:
    """Повертає основну версію Java (напр. 21) або None, якщо Java немає.

    `java -version` друкує в stderr; там також може бути рядок
    "Picked up JAVA_TOOL_OPTIONS", тому шукаємо саме `version "..."`.
    """
    java = shutil.which("java")
    if java is None:
        return None
    proc = subprocess.run(
        [java, "-version"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    m = re.search(r'version "(\d+)(?:\.(\d+))?', proc.stdout)
    if not m:
        return None
    major = int(m.group(1))
    if major == 1 and m.group(2):  # стара схема: 1.8 = Java 8
        major = int(m.group(2))
    return major


def check_java() -> None:
    """Зупиняє скрипт зрозумілою помилкою, якщо Java немає або вона стара."""
    version = java_version()
    if version is None:
        common.die(
            "Java не знайдено. Потрібна Java 17+.\n"
            "  Ubuntu/Debian: sudo apt install openjdk-21-jre-headless\n"
            "  Windows/macOS: https://adoptium.net (Temurin 21)"
        )
    if version < MIN_JAVA:
        common.die(
            f"Знайдено Java {version}, а потрібна {MIN_JAVA}+.\n"
            "  Ubuntu/Debian: sudo apt install openjdk-21-jre-headless"
        )
    print(f"✔ Java {version}")


def download(url: str, dest: Path) -> None:
    """Завантажує файл за URL у dest (спершу в тимчасовий файл, потім rename)."""
    print(f"  завантажую {url}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "2pc-formal-verification"})
    with urllib.request.urlopen(req, timeout=600) as resp, open(tmp, "wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if total:
                print(f"\r  {done / total:6.1%} з {total / 1e6:.1f} МБ", end="", flush=True)
    print()
    tmp.replace(dest)


def setup_tlc(force: bool) -> None:
    """Завантажує tla2tools.jar."""
    if common.TLC_JAR.exists() and not force:
        print(f"✔ TLC уже є: {common.TLC_JAR.relative_to(common.ROOT)}")
        return
    download(common.TLC_URL, common.TLC_JAR)


def setup_apalache(force: bool) -> None:
    """Завантажує й розпаковує Apalache у tools/apalache/."""
    if common.apalache_jar() and not force:
        print(f"✔ Apalache уже є: {common.APALACHE_DIR.relative_to(common.ROOT)}")
        return
    if common.APALACHE_DIR.exists():
        shutil.rmtree(common.APALACHE_DIR)
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "apalache.tgz"
        download(common.APALACHE_URL, archive)
        print("  розпаковую apalache.tgz")
        with tarfile.open(archive) as tar:
            try:
                tar.extractall(common.APALACHE_DIR, filter="data")
            except TypeError:  # Python < 3.12 не знає filter
                tar.extractall(common.APALACHE_DIR)
    if common.apalache_jar() is None:
        common.die("у архіві Apalache не знайдено apalache.jar")


def setup_plantuml(force: bool) -> None:
    """Завантажує plantuml.jar."""
    if common.PLANTUML_JAR.exists() and not force:
        print(f"✔ PlantUML уже є: {common.PLANTUML_JAR.relative_to(common.ROOT)}")
        return
    download(common.PLANTUML_URL, common.PLANTUML_JAR)


def setup_tlapm(force: bool) -> None:
    """Завантажує TLAPS (tlapm) у tools/tlapm/ - лише для Linux x86_64."""
    if common.TLAPM_BIN.exists() and not force:
        print(f"✔ TLAPS уже є: {common.TLAPM_DIR.relative_to(common.ROOT)}")
        return
    if not (sys.platform.startswith("linux") and platform.machine() in ("x86_64", "AMD64")):
        print("⚠ TLAPS: бінарний реліз є лише для Linux x86_64 (на Windows - WSL). Пропускаю.")
        return
    if common.TLAPM_DIR.exists():
        shutil.rmtree(common.TLAPM_DIR)
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "tlapm.tar.gz"
        download(common.TLAPM_URL, archive)
        print("  розпаковую tlapm")
        with tarfile.open(archive) as tar:
            try:
                tar.extractall(common.TLAPM_DIR, filter="tar")
            except TypeError:
                tar.extractall(common.TLAPM_DIR)


def first_line(cmd: list[str], pattern: str) -> str:
    """Запускає команду і повертає перший рядок виводу, що містить pattern."""
    try:
        proc = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=120
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"не вдалося запустити: {exc}"
    for line in proc.stdout.splitlines():
        line = re.sub(r"\x1b\[[0-9;]*m", "", line).strip()
        if line.startswith("Picked up"):  # службовий рядок JVM
            continue
        if pattern in line:
            return line
    return "версію не визначено"


def print_versions() -> None:
    """Друкує версії встановлених інструментів."""
    java = common.java_cmd()
    print("\nВерсії інструментів:")
    print("  TLC:      ", first_line([java, "-cp", str(common.TLC_JAR), "tlc2.TLC", "-h"], "Version"))
    jar = common.apalache_jar()
    if jar:
        print("  Apalache: ", first_line([java, "-jar", str(jar), "version"], "."))
    print("  PlantUML: ", first_line([java, "-jar", str(common.PLANTUML_JAR), "-version"], "PlantUML"))
    if common.TLAPM_BIN.exists():
        rev = first_line([str(common.TLAPM_BIN), "--version"], "")
        print(f"  TLAPS:      {common.TLAPM_VERSION} (rev {rev})")


def main() -> int:
    """Точка входу."""
    common.enable_utf8_stdout()
    parser = argparse.ArgumentParser(description="Завантажити TLC, Apalache і PlantUML у tools/")
    parser.add_argument("--force", action="store_true", help="перезавантажити, навіть якщо вже є")
    parser.add_argument(
        "--tlaps", action="store_true", help="також завантажити TLAPS (tlapm, ~50 МБ, лише Linux x86_64)"
    )
    args = parser.parse_args()

    check_java()
    common.TOOLS_DIR.mkdir(exist_ok=True)
    try:
        setup_tlc(args.force)
        setup_apalache(args.force)
        setup_plantuml(args.force)
        if args.tlaps:
            setup_tlapm(args.force)
    except OSError as exc:
        common.die(f"не вдалося завантажити інструмент: {exc}\nПеревірте інтернет або проксі.")
    print_versions()
    print("\nГотово. Далі: python scripts/run_all.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
