"""Рендер усіх діаграм PlantUML (diagrams/**/*.puml) у PNG і SVG.

Результат кладеться в diagrams/rendered/ (для згенерованих з контрприкладів -
з префіксом generated_, щоб імена не перетиналися з ручними версіями).
Graphviz не потрібен: у state/activity/component-діаграмах увімкнено
`!pragma layout smetana`, а sequence/mindmap PlantUML малює сам.

Запуск:
    python scripts/render_diagrams.py              # усі діаграми
    python scripts/render_diagrams.py architecture # лише ті, що містять «architecture»
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common  # noqa: E402


def find_diagrams(pattern: str | None) -> list[Path]:
    """Повертає всі .puml у diagrams/ (крім службових *.iuml)."""
    files = sorted(common.DIAGRAMS_DIR.glob("*.puml")) + sorted(common.GENERATED_DIR.glob("*.puml"))
    if pattern:
        files = [f for f in files if pattern in f.stem]
    return files


def output_name(src: Path) -> str:
    """Ім'я результату без розширення: architecture або generated_Mutant."""
    if src.parent == common.GENERATED_DIR:
        return f"generated_{src.stem}"
    return src.stem


def render(src: Path, fmt: str) -> tuple[bool, str]:
    """Рендерить один файл у формат fmt ("png" або "svg").

    PlantUML кладе результат поруч з -o папкою під іменем вихідного файлу,
    тому рендеримо в тимчасову папку і переносимо з потрібним іменем.
    Повертає (успіх, текст помилки).
    """
    with tempfile.TemporaryDirectory(prefix="puml-") as tmp:
        cmd = [
            common.java_cmd(),
            "-Djava.awt.headless=true",
            "-DPLANTUML_LIMIT_SIZE=16384",
            "-jar",
            str(common.PLANTUML_JAR),
            "-charset",
            "UTF-8",
            "-failfast2",
            f"-t{fmt}",
            "-o",
            tmp,
            str(src),
        ]
        proc = common.run_process(cmd, cwd=src.parent, timeout=300)
        produced = Path(tmp) / f"{src.stem}.{fmt}"
        if proc.returncode != 0 or not produced.exists():
            output = "\n".join(
                line for line in proc.output.splitlines() if not line.startswith("Picked up")
            )
            return False, output.strip() or f"код повернення {proc.returncode}"
        common.RENDERED_DIR.mkdir(parents=True, exist_ok=True)
        shutil.move(str(produced), common.RENDERED_DIR / f"{output_name(src)}.{fmt}")
    return True, ""


def main() -> int:
    """Точка входу."""
    common.enable_utf8_stdout()
    parser = argparse.ArgumentParser(description="Рендер діаграм PlantUML у PNG/SVG")
    parser.add_argument("pattern", nargs="?", help="рендерити лише файли, ім'я яких містить цей рядок")
    parser.add_argument("--formats", default="png,svg", help="формати через кому (png,svg)")
    args = parser.parse_args()

    if not common.PLANTUML_JAR.exists():
        common.die("tools/plantuml.jar не знайдено. Спершу: python scripts/setup_tools.py")
    files = find_diagrams(args.pattern)
    if not files:
        common.die("не знайдено жодного .puml")

    failed: list[str] = []
    for src in files:
        rel = src.relative_to(common.ROOT)
        for fmt in args.formats.split(","):
            ok, error = render(src, fmt.strip())
            if ok:
                print(f"✔ {rel} -> rendered/{output_name(src)}.{fmt}")
            else:
                print(f"✘ {rel} ({fmt}): помилка рендеру\n{error}\n")
                failed.append(f"{rel} ({fmt})")
    if failed:
        print(f"\nНе вдалося відрендерити: {', '.join(failed)}")
        return 1
    print(f"\nГотово: {len(files)} діаграм у {common.RENDERED_DIR.relative_to(common.ROOT)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
