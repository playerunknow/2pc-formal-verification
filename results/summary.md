# Результати перевірки моделі 2PC

> Файл згенеровано скриптом `scripts/run_all.py` — не редагуйте вручну.

- Дата прогону: 2026-11-07 22:33 UTC
- TLC 2026.11.06.222357 (реліз `v1.8.0`), Apalache v0.50.3, Java 21.0.12.1, Python 3.13.18

## TLC — перебір усіх досяжних станів

| Конфігурація | Сервісів | Що перевіряє | Distinct states | Generated | Глибина | Час, с | Очікувано | Отримано | Збіг |
|---|---|---|---|---|---|---|---|---|---|
| Full_2 | 2 | повна модель, 2 сервіси: S1-S5, L1-L3 | 1 840 | 10 525 | 15 | 1.1 | No error | ✔ No error | ✔ |
| Full | 3 | повна модель, 3 сервіси: S1-S5, L1-L3 | 28 832 | 218 369 | 20 | 3.7 | No error | ✔ No error | ✔ |
| Full_4 | 4 | повна модель, 4 сервіси: S1-S5, L1-L3 | 477 760 | 4 524 241 | 25 | 51.4 | No error | ✔ No error | ✔ |
| NoFailures | 3 | без збоїв: усе + L4 | 163 | 626 | 11 | 0.8 | No error | ✔ No error | ✔ |
| NoTMRecovery_Safety | 3 | координатор не відновлюється: safety зберігається | 28 828 | 203 906 | 21 | 1.4 | No error | ✔ No error | ✔ |
| NoTMRecovery_Deadlock | 3 | координатор не відновлюється: очікується блокування (L1) | — | — | — | 0.6 | порушено `DeadlockFreeNoTMRecovery` | ✘ `DeadlockFreeNoTMRecovery` violated | ✔ |
| NoTMRecovery_Termination | 3 | координатор не відновлюється: очікується незавершення (L2) | — | — | — | 3.6 | порушено `Termination` | ✘ `Termination` violated | ✔ |
| Mutant | 3 | зламаний координатор: очікується частковий коміт (S2) | — | — | — | 0.6 | порушено `Consistency` | ✘ `Consistency` violated | ✔ |

Для конфігурацій із порушенням кількість станів залежить від порядку обходу воркерами TLC, тому вона не наводиться (див. сирі логи в `results/tlc/`).

## Apalache — індуктивний інваріант

| Перевірка | Сервісів | Що доводить | init | next | inv | length | Час, с | Очікувано | Отримано | Збіг |
|---|---|---|---|---|---|---|---|---|---|---|
| ConstInit_InitImpliesIndInv | 3 | Init => IndInv | Init | — | IndInv | 0 | 2.7 | NoError | NoError | ✔ |
| ConstInit_Inductive | 3 | IndInv /\ Next => IndInv' | IndInv | Next | IndInv | 1 | 3.4 | NoError | NoError | ✔ |
| ConstInit_IndInvImpliesConsistency | 3 | IndInv => Consistency | IndInv | — | Consistency | 0 | 2.8 | NoError | NoError | ✔ |
| ConstInit_IndInvImpliesCommitValidity | 3 | IndInv => CommitValidity | IndInv | — | CommitValidity | 0 | 2.8 | NoError | NoError | ✔ |
| ConstInit_IndInvImpliesFollowsTM | 3 | IndInv => FollowsTM | IndInv | — | FollowsTM | 0 | 2.8 | NoError | NoError | ✔ |
| ConstInit4_InitImpliesIndInv | 4 | Init => IndInv | Init | — | IndInv | 0 | 2.6 | NoError | NoError | ✔ |
| ConstInit4_Inductive | 4 | IndInv /\ Next => IndInv' | IndInv | Next | IndInv | 1 | 3.6 | NoError | NoError | ✔ |
| ConstInit4_IndInvImpliesConsistency | 4 | IndInv => Consistency | IndInv | — | Consistency | 0 | 2.9 | NoError | NoError | ✔ |
| ConstInit4_IndInvImpliesCommitValidity | 4 | IndInv => CommitValidity | IndInv | — | CommitValidity | 0 | 2.8 | NoError | NoError | ✔ |
| ConstInit4_IndInvImpliesFollowsTM | 4 | IndInv => FollowsTM | IndInv | — | FollowsTM | 0 | 2.8 | NoError | NoError | ✔ |
| ConstInit5_InitImpliesIndInv | 5 | Init => IndInv | Init | — | IndInv | 0 | 2.7 | NoError | NoError | ✔ |
| ConstInit5_Inductive | 5 | IndInv /\ Next => IndInv' | IndInv | Next | IndInv | 1 | 3.8 | NoError | NoError | ✔ |
| ConstInit5_IndInvImpliesConsistency | 5 | IndInv => Consistency | IndInv | — | Consistency | 0 | 2.9 | NoError | NoError | ✔ |
| ConstInit5_IndInvImpliesCommitValidity | 5 | IndInv => CommitValidity | IndInv | — | CommitValidity | 0 | 2.9 | NoError | NoError | ✔ |
| ConstInit5_IndInvImpliesFollowsTM | 5 | IndInv => FollowsTM | IndInv | — | FollowsTM | 0 | 3.0 | NoError | NoError | ✔ |
| ConstInitMutant_Inductive | 3 | мутант: IndInv НЕ індуктивний (очікувано) | IndInv | Next | IndInv | 1 | 3.3 | Error | Error | ✔ |

## TLAPS — доведення для довільної кількості сервісів

| Модуль | Теорема | Для яких RM | Зобов'язань | Час, с | Очікувано | Отримано | Збіг |
|---|---|---|---|---|---|---|---|
| TwoPhaseProofs | `Spec => [](Consistency /\ CommitValidity /\ FollowsTM)` | довільна скінченна множина RM, Mutant = FALSE | 61/61 | 4.1 | Proved | Proved | ✔ |

## Підсумок

Збіглося з очікуваним: **25 з 25** перевірок.

Порушення в `NoTMRecovery_Deadlock`, `NoTMRecovery_Termination`, `Mutant` і помилка Apalache на мутанті — **очікувані**: вони показують, що властивості сформульовані не тривіально і що без відновлення координатора 2PC блокується.

## Діаграми контрприкладів

- `NoTMRecovery_Deadlock` → [`diagrams/generated/NoTMRecovery_Deadlock.puml`](../diagrams/generated/NoTMRecovery_Deadlock.puml)
- `NoTMRecovery_Termination` → [`diagrams/generated/NoTMRecovery_Termination.puml`](../diagrams/generated/NoTMRecovery_Termination.puml)
- `Mutant` → [`diagrams/generated/Mutant.puml`](../diagrams/generated/Mutant.puml)
