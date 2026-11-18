# Як проводити демонстрацію

Текст, який читати, — у [presentation_script.md](presentation_script.md). Тут — що
відкривати, в якому порядку і що робити, якщо щось пішло не так.

## Підготовка (вдома, напередодні)

1. Клонувати репозиторій і встановити інструменти:
   ```bash
   git clone https://github.com/playerunknow/2pc-formal-verification
   cd 2pc-formal-verification
   python scripts/setup_tools.py
   ```
   Потрібні Python 3.10+ і Java 17+ (Ubuntu: `sudo apt install openjdk-21-jre-headless`;
   Windows: Temurin 21 з adoptium.net). Інструменти (~150 МБ) завантажуються один раз у
   `tools/`.
2. Прогнати три демо-команди, щоб «прогріти» JVM і переконатися, що все працює:
   ```bash
   python scripts/run_one.py Full
   python scripts/run_one.py NoTMRecovery_Deadlock
   python scripts/run_one.py Mutant
   ```
3. Відкрити заздалегідь (вкладками у VS Code або браузері):
   - `README.md` (у GitHub або з прев'ю Markdown);
   - `spec/TwoPhase.tla`;
   - папку `diagrams/rendered/` (PNG);
   - `results/summary.md`.
4. Збільшити шрифт термінала (на проекторі дрібне не видно): ~18–20 pt.

## Режим 1: з живим запуском (~9,5 хв)

| # | Час | Що відкрити / виконати | Що має бути видно |
|---|---|---|---|
| 1 | 0:00 | `README.md` | тема, «Коротко», таблиця результатів |
| 2 | 0:45 | `diagrams/rendered/architecture.png` → `2pc_happy_path.png` | сервіси, координатор, дві фази |
| 3 | 1:35 | `rm_state_machine.png` → `tm_state_machine.png` → `failure_model.png` | стани і збої |
| 4 | 2:30 | `spec/TwoPhase.tla`: карта дій зверху, `RMPrepare`, `TMCommit`, `TMCrash`, `Consistency` (Ctrl+F) | код специфікації |
| 5 | 3:50 | `properties_map.png` | S1–S5, L1–L4 |
| 6 | 4:20 | `verification_pipeline.png` | TLC + Apalache |
| 7 | 4:40 | `python scripts/run_one.py Full` (~4 с) → таблиця TLC у `README.md` | `NO ERROR`, `Різних станів: 28 832`; у таблиці `Full_2` / `Full` / `Full_4`: 1 840 → 28 832 → 477 760 |
| 8 | 5:55 | `python scripts/run_one.py NoTMRecovery_Deadlock` (~1 с) → `generated_NoTMRecovery_Deadlock.png` | `ПОРУШЕННЯ`, 5 кроків, останній — `TMCrash` |
| 9 | 6:35 | `python scripts/run_one.py Mutant` (~1 с) → `generated_Mutant.png` | `ПОРУШЕННЯ Consistency`, `payment=committed inventory=aborted` |
| 10 | 7:10 | `inductive_invariant.png` → таблиця Apalache у `results/summary.md` | 15 × NoError, мутант — Error |
| 11 | 8:20 | `README.md`, таблиця результатів | висновок |

Кожна команда `run_one.py` виконується до 10 секунд (більшість — 1–4 с). Контрприклади
детерміновані: на парі буде та сама траса, що й у документації.

Довгу перевірку `Full_4` (~1 хв) і повний `run_all.py` (~2 хв) наживо **не запускати** —
показати готові результати в `results/summary.md`.

## Режим 2: без запуску (~6–7 хв)

Якщо немає Java, інтернету, часу або проектор «не дружить» із терміналом:

- кроки 1–6 і 10–11 — ті самі;
- замість кроків 7–9 відкрити готові файли:
  - `results/summary.md` — рядки `Full`, `NoTMRecovery_Deadlock`, `Mutant`;
  - `results/tlc/Full.txt` — останні рядки: `Model checking completed. No error has been
    found.` і `28832 distinct states found`;
  - `diagrams/rendered/generated_NoTMRecovery_Deadlock.png` і `generated_Mutant.png` —
    автоматично згенеровані з цих логів діаграми.

У тексті замість «запускаю» сказати «ось результат запуску».

## Якщо щось пішло не так

| Проблема | Що робити |
|---|---|
| Немає інтернету на парі | Інтернет потрібен лише для `setup_tools.py`. Якщо `tools/` уже заповнена — усе працює офлайн |
| Немає Java на комп'ютері в аудиторії | Режим 2. Або заздалегідь записати відео/скріншоти трьох запусків |
| `run_one.py` друкує `tools/tla2tools.jar не знайдено` | `python scripts/setup_tools.py` (потрібен інтернет) або перейти в режим 2 |
| Українські літери в терміналі Windows — «кракозябри» | `chcp 65001` перед запуском або Windows Terminal замість cmd |
| TLC довго думає | Перша команда після запуску JVM повільніша; тому й «прогріти» заздалегідь |
| GitHub не відкривається | Показувати локальні файли: PNG у `diagrams/rendered/`, Markdown у VS Code (Ctrl+Shift+V — прев'ю) |

## Корисні додаткові команди

```bash
python scripts/run_one.py --list               # усі конфігурації з очікуваннями
python scripts/run_one.py NoTMRecovery_Termination
python scripts/run_all.py --quick              # усе, крім Full_4 (~1 хв)
python scripts/run_all.py --only apalache      # лише Apalache (~50 с)
python scripts/render_diagrams.py              # перерендерити діаграми
```
