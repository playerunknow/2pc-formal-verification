----------------------------- MODULE TwoPhase -----------------------------
(***************************************************************************)
(* Формальна модель протоколу двофазного коміту (Two-Phase Commit)        *)
(* для розподіленої транзакції між мікросервісами.                         *)
(*                                                                         *)
(* Учасники (RM)  - мікросервіси, напр. payment, inventory, order.         *)
(* Координатор (TM) - менеджер транзакцій.                                 *)
(*                                                                         *)
(* Модель середовища:                                                      *)
(*  - асинхронна мережа: повідомлення - це множина, тому вони можуть       *)
(*    доставлятися з будь-якою затримкою, у будь-якому порядку і           *)
(*    повторно;                                                            *)
(*  - втрата повідомлень (LoseMsg) з повторною відправкою (Resend);        *)
(*  - падіння і відновлення будь-якого вузла; стан, записаний у журнал     *)
(*    (prepared / committed / aborted, рішення TM), переживає падіння.     *)
(*                                                                         *)
(* У цьому модулі лише safety-частина (її перевіряють TLC і Apalache).    *)
(* Справедливість і liveness-властивості - у модулі MCTwoPhase.            *)
(***************************************************************************)

(***************************************************************************)
(* КАРТА: дія TLA+  ->  подія в системі мікросервісів                     *)
(*                                                                         *)
(* Приклад транзакції «оформити замовлення»: списати гроші (payment),      *)
(* зарезервувати товар (inventory), створити замовлення (order).           *)
(*                                                                         *)
(* RMPrepare("payment")     сервіс оплати зарезервував кошти, записав      *)
(*                          PREPARED у свій журнал і відповів              *)
(*                          координатору «так»                             *)
(* RMChooseToAbort("inventory")  складу бракує товару: сервіс відкотив     *)
(*                          локальні зміни і голосує «ні»                  *)
(* RMResend(r)              сервіс r не дочекався відповіді і повторно     *)
(*                          надсилає «так» (retry)                         *)
(* TMRcvPrepared(r)         координатор прочитав відповідь «так» від r     *)
(* TMCommit                 координатор має «так» від УСІХ, записав        *)
(*                          COMMIT у свій журнал (WAL) і розсилає Commit   *)
(* TMAbort                  координатор за тайм-аутом (хтось відмовився    *)
(*                          або недоступний) записав ABORT і розсилає його *)
(* TMResend                 координатор повторно розсилає рішення          *)
(* RMRcvCommit(r)           сервіс r отримав Commit: фіксує транзакцію,    *)
(*                          знімає блокування                              *)
(* RMRcvAbort(r)            сервіс r отримав Abort: відкочує транзакцію    *)
(* TMCrash / RMCrash(r)     процес координатора / сервісу r впав           *)
(*                          (kill -9, OOM, перезапуск поду)                *)
(* TMRecover / RMRecover(r) процес піднявся і прочитав свій журнал         *)
(* LoseMsg                  мережа загубила запит або відповідь            *)
(* Done                     транзакція завершена, далі нічого не змінюється*)
(*                                                                         *)
(* Змінні:                                                                 *)
(*   rmState[r] - стан сервісу r: working / prepared / committed / aborted *)
(*   tmState    - рішення координатора: init / committed / aborted        *)
(*   tmPrepared - сервіси, чиє «так» координатор уже прочитав              *)
(*   msgs       - повідомлення «в дорозі»; це множина, тож порядок         *)
(*                довільний, а прочитане повідомлення не зникає (дублі)    *)
(*   tmUp, rmUp - чи працює процес (FALSE = впав)                          *)
(***************************************************************************)
EXTENDS FiniteSets

CONSTANTS
    \* @type: Set(Str);
    RM,          \* множина мікросервісів-учасників
    \* @type: Bool;
    Mutant       \* TRUE - навмисно зламана версія протоколу (мутаційна перевірка)

VARIABLES
    \* @type: Str -> Str;
    rmState,     \* стан кожного учасника
    \* @type: Str;
    tmState,     \* стан (рішення) координатора
    \* @type: Set(Str);
    tmPrepared,  \* від кого координатор отримав голос «так»
    \* @type: Set({type: Str, rm: Str});
    msgs,        \* повідомлення в мережі
    \* @type: Bool;
    tmUp,        \* координатор працює (не впав)
    \* @type: Str -> Bool;
    rmUp         \* учасник працює (не впав)

vars == <<rmState, tmState, tmPrepared, msgs, tmUp, rmUp>>

NoRM == "-"   \* заглушка для повідомлень координатора, що не адресовані одному RM

PreparedMsg(r) == [type |-> "Prepared", rm |-> r]
CommitMsg      == [type |-> "Commit",   rm |-> NoRM]
AbortMsg       == [type |-> "Abort",    rm |-> NoRM]

Messages == {PreparedMsg(r) : r \in RM} \cup {CommitMsg, AbortMsg}

Final == {"committed", "aborted"}

(***************************************************************************)
(* S1. TypeOK - коректність типів                                          *)
(***************************************************************************)
TypeOK ==
    /\ rmState \in [RM -> {"working", "prepared", "committed", "aborted"}]
    /\ tmState \in {"init", "committed", "aborted"}
    /\ tmPrepared \in SUBSET RM
    /\ msgs \in SUBSET Messages
    /\ tmUp \in BOOLEAN
    /\ rmUp \in [RM -> BOOLEAN]

Init ==
    /\ rmState = [r \in RM |-> "working"]
    /\ tmState = "init"
    /\ tmPrepared = {}
    /\ msgs = {}
    /\ tmUp = TRUE
    /\ rmUp = [r \in RM |-> TRUE]

-----------------------------------------------------------------------------
(***************************************************************************)
(* Дії координатора                                                        *)
(***************************************************************************)

\* Координатор отримує голос «так» від учасника r
TMRcvPrepared(r) ==
    /\ tmUp
    /\ tmState = "init"
    /\ PreparedMsg(r) \in msgs
    /\ tmPrepared' = tmPrepared \cup {r}
    /\ UNCHANGED <<rmState, tmState, msgs, tmUp, rmUp>>

\* Координатор приймає рішення COMMIT: записує його в журнал і розсилає.
\* Правильна версія: лише коли проголосували ВСІ учасники.
\* Мутант: досить голосу хоча б одного учасника (навмисна помилка).
TMCommit ==
    /\ tmUp
    /\ tmState = "init"
    /\ IF Mutant THEN tmPrepared # {} ELSE tmPrepared = RM
    /\ tmState' = "committed"
    /\ msgs' = msgs \cup {CommitMsg}
    /\ UNCHANGED <<rmState, tmPrepared, tmUp, rmUp>>

\* Тайм-аут спрацьовує лише тоді, коли для нього є реальна причина:
\* хтось із учасників відмовився (aborted) або недоступний (впав).
Timeout == \E r \in RM : rmState[r] = "aborted" \/ ~rmUp[r]

\* Координатор приймає рішення ABORT
TMAbort ==
    /\ tmUp
    /\ tmState = "init"
    /\ Timeout
    /\ tmState' = "aborted"
    /\ msgs' = msgs \cup {AbortMsg}
    /\ UNCHANGED <<rmState, tmPrepared, tmUp, rmUp>>

\* Повторне розсилання прийнятого рішення (якщо повідомлення загубилось)
TMResend ==
    /\ tmUp
    /\ tmState # "init"
    /\ LET m == IF tmState = "committed" THEN CommitMsg ELSE AbortMsg
       IN  /\ m \notin msgs
           /\ msgs' = msgs \cup {m}
    /\ UNCHANGED <<rmState, tmState, tmPrepared, tmUp, rmUp>>

\* Падіння координатора
TMCrash ==
    /\ tmUp
    /\ tmUp' = FALSE
    /\ UNCHANGED <<rmState, tmState, tmPrepared, msgs, rmUp>>

\* Відновлення координатора з журналу:
\* якщо рішення записане - воно зберігається (і буде розіслане через TMResend);
\* якщо рішення не записане - координатор приймає рішення ABORT (presumed abort).
TMRecover ==
    /\ ~tmUp
    /\ tmUp' = TRUE
    /\ IF tmState = "init"
          THEN /\ tmState' = "aborted"
               /\ msgs' = msgs \cup {AbortMsg}
          ELSE UNCHANGED <<tmState, msgs>>
    /\ UNCHANGED <<rmState, tmPrepared, rmUp>>

-----------------------------------------------------------------------------
(***************************************************************************)
(* Дії учасників (мікросервісів)                                           *)
(***************************************************************************)

\* Учасник виконав локальну частину, записав PREPARED у журнал і голосує «так»
RMPrepare(r) ==
    /\ rmUp[r]
    /\ rmState[r] = "working"
    /\ rmState' = [rmState EXCEPT ![r] = "prepared"]
    /\ msgs' = msgs \cup {PreparedMsg(r)}
    /\ UNCHANGED <<tmState, tmPrepared, tmUp, rmUp>>

\* Учасник відмовляється (голос «ні») - напр., бракує коштів або товару
RMChooseToAbort(r) ==
    /\ rmUp[r]
    /\ rmState[r] = "working"
    /\ rmState' = [rmState EXCEPT ![r] = "aborted"]
    /\ UNCHANGED <<tmState, tmPrepared, msgs, tmUp, rmUp>>

\* Повторне надсилання голосу «так» (якщо повідомлення загубилось)
RMResend(r) ==
    /\ rmUp[r]
    /\ rmState[r] = "prepared"
    /\ PreparedMsg(r) \notin msgs
    /\ msgs' = msgs \cup {PreparedMsg(r)}
    /\ UNCHANGED <<rmState, tmState, tmPrepared, tmUp, rmUp>>

\* Учасник отримує рішення COMMIT
RMRcvCommit(r) ==
    /\ rmUp[r]
    /\ CommitMsg \in msgs
    /\ rmState' = [rmState EXCEPT ![r] = "committed"]
    /\ UNCHANGED <<tmState, tmPrepared, msgs, tmUp, rmUp>>

\* Учасник отримує рішення ABORT
RMRcvAbort(r) ==
    /\ rmUp[r]
    /\ AbortMsg \in msgs
    /\ rmState' = [rmState EXCEPT ![r] = "aborted"]
    /\ UNCHANGED <<tmState, tmPrepared, msgs, tmUp, rmUp>>

\* Падіння учасника
RMCrash(r) ==
    /\ rmUp[r]
    /\ rmUp' = [rmUp EXCEPT ![r] = FALSE]
    /\ UNCHANGED <<rmState, tmState, tmPrepared, msgs, tmUp>>

\* Відновлення учасника з журналу: стан prepared/committed/aborted
\* зберігається; незавершена робота (working) відкочується.
RMRecover(r) ==
    /\ ~rmUp[r]
    /\ rmUp' = [rmUp EXCEPT ![r] = TRUE]
    /\ rmState' = IF rmState[r] = "working"
                     THEN [rmState EXCEPT ![r] = "aborted"]
                     ELSE rmState
    /\ UNCHANGED <<tmState, tmPrepared, msgs, tmUp>>

\* Мережа губить повідомлення
LoseMsg ==
    /\ \E m \in msgs : msgs' = msgs \ {m}
    /\ UNCHANGED <<rmState, tmState, tmPrepared, tmUp, rmUp>>

\* Транзакція завершена: явний кінцевий стан (щоб TLC не вважав його тупиком)
AllDone == \A r \in RM : rmState[r] \in Final
Done == AllDone /\ UNCHANGED vars

-----------------------------------------------------------------------------
(***************************************************************************)
(* Відношення переходів                                                    *)
(***************************************************************************)

\* Кроки самого протоколу (включно з відновленням після збою)
ProtocolStep ==
    \/ TMCommit \/ TMAbort \/ TMResend \/ TMRecover
    \/ \E r \in RM : \/ TMRcvPrepared(r)
                     \/ RMPrepare(r) \/ RMChooseToAbort(r) \/ RMResend(r)
                     \/ RMRcvCommit(r) \/ RMRcvAbort(r) \/ RMRecover(r)

\* Збої середовища
FailureStep ==
    \/ TMCrash \/ LoseMsg
    \/ \E r \in RM : RMCrash(r)

\* Повна модель: протокол + збої
Next == ProtocolStep \/ FailureStep \/ Done

\* Модель без збоїв (для перевірки нетривіальності L4)
NextNoFailures == ProtocolStep \/ Done

\* Модель, у якій координатор після падіння НЕ відновлюється
ProtocolStepNoTMRecovery ==
    \/ TMCommit \/ TMAbort \/ TMResend
    \/ \E r \in RM : \/ TMRcvPrepared(r)
                     \/ RMPrepare(r) \/ RMChooseToAbort(r) \/ RMResend(r)
                     \/ RMRcvCommit(r) \/ RMRcvAbort(r) \/ RMRecover(r)

NextNoTMRecovery == ProtocolStepNoTMRecovery \/ FailureStep \/ Done

-----------------------------------------------------------------------------
(***************************************************************************)
(* Властивості безпеки (safety)                                            *)
(***************************************************************************)

\* S2. Consistency - немає частково зафіксованого стану
Consistency ==
    \A r1, r2 \in RM : ~(rmState[r1] = "aborted" /\ rmState[r2] = "committed")

\* S3. CommitValidity - commit лише якщо всі проголосували «так»
CommitValidity ==
    (\E r \in RM : rmState[r] = "committed")
        => (\A r \in RM : rmState[r] \in {"prepared", "committed"})

\* S5. FollowsTM - учасники не діють всупереч рішенню координатора
FollowsTM ==
    /\ \A r \in RM : rmState[r] = "committed" => tmState = "committed"
    /\ tmState = "committed" => \A r \in RM : rmState[r] # "aborted"

\* S4. Stability - властивості дій: рішення не змінюються
DecisionStable == [][tmState # "init" => tmState' = tmState]_vars
RMStable == [][\A r \in RM : rmState[r] \in Final => rmState'[r] = rmState[r]]_vars

(***************************************************************************)
(* Індуктивний інваріант (перевіряється в Apalache)                        *)
(* Він сильніший за Consistency і зберігається будь-яким кроком Next,      *)
(* тому Consistency виконується в УСІХ досяжних станах.                    *)
(***************************************************************************)
IndInv ==
    /\ TypeOK
    /\ CommitMsg \in msgs => tmState = "committed"
    /\ AbortMsg  \in msgs => tmState = "aborted"
    /\ \A r \in RM : PreparedMsg(r) \in msgs => rmState[r] # "working"
    /\ \A r \in RM : r \in tmPrepared => rmState[r] # "working"
    \* хто проголосував «так», може відкотитись лише за рішенням координатора
    /\ \A r \in RM : (PreparedMsg(r) \in msgs \/ r \in tmPrepared) /\ rmState[r] = "aborted"
                        => tmState = "aborted"
    /\ tmState = "committed" => tmPrepared = RM
    /\ tmState = "committed" => \A r \in RM : rmState[r] \in {"prepared", "committed"}
    /\ \A r \in RM : rmState[r] = "committed" => tmState = "committed"

\* Ініціалізація констант для Apalache
ConstInit ==
    /\ RM = {"payment", "inventory", "order"}
    /\ Mutant = FALSE

ConstInit4 ==
    /\ RM = {"payment", "inventory", "order", "delivery"}
    /\ Mutant = FALSE

ConstInit5 ==
    /\ RM = {"payment", "inventory", "order", "delivery", "notification"}
    /\ Mutant = FALSE

ConstInitMutant ==
    /\ RM = {"payment", "inventory", "order"}
    /\ Mutant = TRUE

=============================================================================

