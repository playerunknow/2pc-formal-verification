--------------------------- MODULE TwoPhaseProofs ---------------------------
(***************************************************************************)
(* Машинно перевірене доведення (TLAPS) того, що в правильній версії       *)
(* протоколу НЕМАЄ частково зафіксованого стану - для БУДЬ-ЯКОЇ скінченної *)
(* множини сервісів RM, а не лише для 2-5, як у TLC та Apalache.          *)
(*                                                                         *)
(* Схема - класична індукція по кроках:                                    *)
(*   1) Init => IndInv                    (база)                           *)
(*   2) IndInv /\ [Next]_vars => IndInv'  (крок; розбито по діях)          *)
(*   3) IndInv => Consistency             (наслідок)                       *)
(* Звідси Spec => []Consistency, де Spec == Init /\ [][Next]_vars.         *)
(*                                                                         *)
(* Перевірка:  tlapm --cleanfp -I <шлях до TLAPS.tla> spec/TwoPhaseProofs.tla *)
(* Модуль не впливає на TLC/Apalache: він лише використовує TwoPhase.      *)
(***************************************************************************)
EXTENDS TwoPhase, TLAPS

\* Доводимо для правильного протоколу (не мутанта).
ASSUME NotMutant == Mutant = FALSE

\* Специфікація без справедливості: для safety вона не потрібна.
Spec == Init /\ [][Next]_vars

-----------------------------------------------------------------------------
\* 1) База: початковий стан задовольняє індуктивний інваріант.
LEMMA InitIndInv == Init => IndInv
  BY DEF Init, IndInv, TypeOK, Messages, PreparedMsg, CommitMsg, AbortMsg

\* 2) Крок: кожна дія Next (і крок «на місці») зберігає IndInv.
LEMMA StepIndInv == IndInv /\ [Next]_vars => IndInv'
<1> SUFFICES ASSUME IndInv, [Next]_vars PROVE IndInv'
  OBVIOUS
<1> USE DEF IndInv, TypeOK, Messages, PreparedMsg, CommitMsg, AbortMsg, NoRM, Final
<1>1. CASE TMCommit
  BY <1>1, NotMutant DEF TMCommit
<1>2. CASE TMAbort
  BY <1>2 DEF TMAbort, Timeout
<1>3. CASE TMResend
  BY <1>3 DEF TMResend
<1>4. CASE TMRecover
  BY <1>4 DEF TMRecover
<1>5. CASE TMCrash
  BY <1>5 DEF TMCrash
<1>6. CASE LoseMsg
  BY <1>6 DEF LoseMsg
<1>7. ASSUME NEW r \in RM, TMRcvPrepared(r) PROVE IndInv'
  BY <1>7 DEF TMRcvPrepared
<1>8. ASSUME NEW r \in RM, RMPrepare(r) PROVE IndInv'
  BY <1>8 DEF RMPrepare
<1>9. ASSUME NEW r \in RM, RMChooseToAbort(r) PROVE IndInv'
  BY <1>9 DEF RMChooseToAbort
<1>10. ASSUME NEW r \in RM, RMResend(r) PROVE IndInv'
  BY <1>10 DEF RMResend
<1>11. ASSUME NEW r \in RM, RMRcvCommit(r) PROVE IndInv'
  BY <1>11 DEF RMRcvCommit
<1>12. ASSUME NEW r \in RM, RMRcvAbort(r) PROVE IndInv'
  BY <1>12 DEF RMRcvAbort
<1>13. ASSUME NEW r \in RM, RMRecover(r) PROVE IndInv'
  BY <1>13 DEF RMRecover
<1>14. ASSUME NEW r \in RM, RMCrash(r) PROVE IndInv'
  BY <1>14 DEF RMCrash
<1>15. CASE Done
  BY <1>15 DEF Done, vars
<1>16. CASE UNCHANGED vars
  BY <1>16 DEF vars
<1>. QED
  BY <1>1, <1>2, <1>3, <1>4, <1>5, <1>6, <1>7, <1>8, <1>9, <1>10, <1>11,
     <1>12, <1>13, <1>14, <1>15, <1>16
  DEF Next, ProtocolStep, FailureStep

\* 3) Наслідки: з IndInv випливають S2, S3, S5.
LEMMA IndInvImpliesSafety == IndInv => Consistency /\ CommitValidity /\ FollowsTM
  BY DEF IndInv, TypeOK, Consistency, CommitValidity, FollowsTM

-----------------------------------------------------------------------------
\* Головна теорема: у жодному досяжному стані немає часткового коміту (S2),
\* а також виконуються S3 і S5 - для довільної множини сервісів RM.
THEOREM SafetyTheorem == Spec => [](Consistency /\ CommitValidity /\ FollowsTM)
<1>1. Spec => []IndInv
  BY InitIndInv, StepIndInv, PTL DEF Spec
<1>. QED
  BY <1>1, IndInvImpliesSafety, PTL

=============================================================================
