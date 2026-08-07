"""Модель данных — §4 ТЗ, плюс схема конфигурации §6.

Здесь описаны только структуры данных и перечисления. Вычислений нет.

Соглашения, обязательные для всего пакета (§10, §12 ТЗ):

* денежные величины — только :class:`decimal.Decimal`, квантование до 2 знаков,
  ``ROUND_HALF_UP``; ``float`` в расчётах сумм запрещён;
* внутренние сравнения сумм — в копейках (``int``), где это упрощает точность
  (subset-sum §7.3 обязательно в копейках);
* пользовательские строки — русские, коды находок — латиница (§12).

`Config` живёт в этом модуле, а не в отдельном `config.py`: §10 ТЗ фиксирует
состав пакета, и добавлять модули сверх списка нельзя.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

RULES_VERSION = "1.0"
"""Версия правил из ТЗ; попадает в метаданные каждого отчёта (§12)."""

__all__ = [
    "RULES_VERSION",
    "AnalysisResult",
    "AuditLogEntry",
    "BalanceTrace",
    "BlockLayout",
    "CalendarAggregation",
    "CalendarConfig",
    "Category",
    "CategoryRecon",
    "CausalLine",
    "ChangePointWindow",
    "ChangepointConfig",
    "ClassifyResult",
    "CollapseResult",
    "Config",
    "DocType",
    "FallbackVerification",
    "FileMeta",
    "Finding",
    "FindingCode",
    "IngestResult",
    "LagResult",
    "LedgerEntry",
    "LedgerTotals",
    "LocalizationResult",
    "LocalizationStatus",
    "Materiality",
    "MaterialityConfig",
    "MaterialityThresholds",
    "NonNegativityReport",
    "NormalizeResult",
    "OpsClass",
    "OpsEntry",
    "OpsKind",
    "ParseIssue",
    "PatternsConfig",
    "PostingMode",
    "ReversalResult",
    "Severity",
    "Signature",
    "SignaturesConfig",
    "StatisticsConfig",
    "SubsetSumConfig",
    "SubsetSumGateReport",
    "SweepPoint",
    "TargetBalanceRule",
    "Thresholds",
    "ValidationCheck",
    "ValidationReport",
    "Waterfall",
    "WindowFlows",
    "config_sha256",
    "load_config",
]


# --------------------------------------------------------------------------- #
# Перечисления
# --------------------------------------------------------------------------- #


class Category(StrEnum):
    """Категория денежного потока по корреспондирующему счёту — §3.5, §5.4."""

    INCOME = "ПРИХОД"
    COLLECTION = "ИНКАССАЦИЯ"
    REFUND = "ВОЗВРАТ"
    EXCHANGE = "РАЗМЕН"
    OTHER = "ПРОЧЕЕ"


class DocType(StrEnum):
    """Тип документа 1С по тексту колонки C — §3.2."""

    PKO = "ПКО"
    RKO = "РКО"
    REVERSAL = "СТОРНО"
    TRANSFER = "ПЕРЕВОД"
    OTHER = "ПРОЧЕЕ"


class OpsKind(StrEnum):
    """Блок опер-лога, из которого пришла запись — §3.3."""

    PKO = "ПКО"
    RKO = "РКО"


class OpsClass(StrEnum):
    """Классификация записи опер-лога — §3.6."""

    COLLECTION = "ИНКАССАЦИЯ"
    REFUND = "ВОЗВРАТ"
    SERVICE = "СЛУЖЕБНАЯ"
    INCOME = "ПРИХОД"


class Severity(StrEnum):
    """Уровень находки — §8."""

    ERROR = "ОШИБКА"
    REVIEW = "ПРОВЕРИТЬ"
    NORMAL = "НОРМА"
    INFO = "ИНФО"


class Materiality(StrEnum):
    """Материальность находки — §7.5."""

    MATERIAL = "СУЩЕСТВЕННО"
    IMMATERIAL = "НЕСУЩЕСТВЕННО"
    TRIVIAL = "ТРИВИАЛЬНО"


class FindingCode(StrEnum):
    """Таксономия находок — §8. Коды латиницей (§12)."""

    RKO_WITHOUT_PAYOUT = "RKO_WITHOUT_PAYOUT"
    RKO_OVERSTATED = "RKO_OVERSTATED"
    PKO_DOUBLE_BOOKED = "PKO_DOUBLE_BOOKED"
    PAYOUT_NOT_BOOKED = "PAYOUT_NOT_BOOKED"
    REVERSAL_PAIR = "REVERSAL_PAIR"
    REVERSAL_UNMATCHED = "REVERSAL_UNMATCHED"
    REVERSAL_WITHOUT_REBOOK = "REVERSAL_WITHOUT_REBOOK"
    SERVICE_MISCLASSIFIED = "SERVICE_MISCLASSIFIED"
    POSTING_DELAY = "POSTING_DELAY"
    SHIFT_ROUNDING = "SHIFT_ROUNDING"
    PERIOD_CUTOFF = "PERIOD_CUTOFF"
    LOG_IMBALANCE = "LOG_IMBALANCE"
    REPEAT_PAYOUT = "REPEAT_PAYOUT"
    LATE_TIME_DOC = "LATE_TIME_DOC"
    SEQUENCE_GAP = "SEQUENCE_GAP"
    DUPLICATE_DOC = "DUPLICATE_DOC"
    UNKNOWN_ACCOUNT = "UNKNOWN_ACCOUNT"


class PostingMode(StrEnum):
    """Режим проведения по категории — §5.9.1."""

    PER_DOCUMENT = "ПОДОКУМЕНТНЫЙ"
    DAILY_AGGREGATE = "ДНЕВНЫЕ_АГРЕГАТЫ"


class LocalizationStatus(StrEnum):
    """Итог локализации — §5.9, §7.3.

    ``NOT_LOCALIZED`` и ``REFUSED_*`` реализуют принцип «отказ вместо догадки»
    (§0.3): недоказанная улика хуже отсутствия результата.

    ``EXPLAINED_BY_REVERSAL`` — день объяснён, но своего кода §8 не имеет:
    расхождение целиком принадлежит находке §5.5, и второй раз называть те же
    рубли нельзя.
    """

    LOCALIZED = "ЛОКАЛИЗОВАНО"
    PROBABLE = "ВЕРОЯТНО"
    AMBIGUOUS = "AMBIGUOUS"
    EXPLAINED_BY_REVERSAL = "ОБЪЯСНЕНО_СТОРНО"
    NOT_LOCALIZED = "НЕ_ЛОКАЛИЗОВАНО"
    REFUSED_CANDIDATE_COUNT = "ОТКАЗ_ЧИСЛО_КАНДИДАТОВ"
    REFUSED_DENSITY = "ОТКАЗ_ПЛОТНОСТЬ"
    REFUSED_PERMUTATION = "ОТКАЗ_ПЕРЕСТАНОВОЧНЫЙ_ТЕСТ"
    REFUSED_BELOW_Z_REPORT = "ОТКАЗ_НИЖЕ_АГРЕГАТА_ПРОДАЖ"


# --------------------------------------------------------------------------- #
# Базовый класс
# --------------------------------------------------------------------------- #


class _Frozen(BaseModel):
    """Неизменяемая модель: стадии конвейера не мутируют вход (§5)."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class _Mutable(BaseModel):
    """Изменяемая модель — только там, где §4 ТЗ явно не требует ``frozen``."""

    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- #
# §4.1–4.2 — нормализованные записи
# --------------------------------------------------------------------------- #


class LedgerEntry(_Frozen):
    """Нормализованная проводка 1С — §4.1 ТЗ.

    ``counter_account`` берётся из колонки G для дебетовых проводок и из
    колонки E для кредитовых (§3.2) — перепутанные счета ломают классификацию.
    """

    row: int
    date: date
    debit: Decimal
    credit: Decimal
    counter_account: str
    category: Category
    doc_text: str
    doc_number: str
    doc_type: DocType
    is_reversal: bool
    running_balance: Decimal = Decimal("0.00")


class OpsEntry(_Frozen):
    """Запись опер-лога — §4.2 ТЗ.

    ``classified_by`` хранит способ классификации (``"counterparty"`` либо
    ``"time_fallback"``) для аудиторского следа §12.
    """

    row: int
    dt: datetime
    amount: Decimal
    counterparty: str
    kind: OpsKind
    classification: OpsClass
    classified_by: str


# --------------------------------------------------------------------------- #
# §5.1 — ingest
# --------------------------------------------------------------------------- #


class BlockLayout(_Frozen):
    """Найденные позиции блоков опер-лога — §3.3.

    Индексы колонок ``(дата, сумма, контрагент)``; ``None`` означает, что блок
    в файле отсутствует (вариант D) либо колонки контрагента нет (вариант C).
    """

    header_row: int
    rko: tuple[int, int, int | None] | None
    pko: tuple[int, int, int | None] | None
    variant: str


class FileMeta(_Frozen):
    """Метаданные входного файла — §4.4, §5.1, §12."""

    path: Path
    sha256: str
    pvz_id: str | None
    stated_period: tuple[date, date] | None
    actual_period: tuple[date, date] | None
    rules_version: str
    config_sha256: str
    run_timestamp: datetime


class ParseIssue(_Frozen):
    """Строка, которую не удалось разобрать — §12, «никаких тихих пропусков»."""

    row: int
    column: int | None
    reason: str
    raw_value: str


class IngestResult(_Frozen):
    """Выход стадии INGEST — §5.1."""

    meta: FileMeta
    raw_rows: tuple[tuple[object, ...], ...]
    layout: BlockLayout
    issues: tuple[ParseIssue, ...]


# --------------------------------------------------------------------------- #
# §5.2 — normalize
# --------------------------------------------------------------------------- #


class LedgerTotals(_Frozen):
    """Контрольные суммы из служебных строк карточки — §3.2.

    ``opening`` и ``closing_stated`` читаются из колонки 4 (E), не из 9 —
    ловушка §3.2, стоившая ошибки на Щучине.
    """

    opening: Decimal
    closing_stated: Decimal
    turnover_debit: Decimal | None
    turnover_credit: Decimal | None


class NormalizeResult(_Frozen):
    """Выход стадии NORMALIZE — §5.2."""

    ledger: tuple[LedgerEntry, ...]
    ops: tuple[OpsEntry, ...]
    totals: LedgerTotals
    issues: tuple[ParseIssue, ...]


# --------------------------------------------------------------------------- #
# §5.3 — validate
# --------------------------------------------------------------------------- #


class ValidationCheck(_Frozen):
    """Результат одного контроля V1–V6 — §5.3."""

    code: str
    passed: bool
    skipped: bool
    expected: Decimal | None
    actual: Decimal | None
    message: str


class ValidationReport(_Frozen):
    """Отчёт стадии VALIDATE — §5.3.

    Нарушение V1–V3 = остановка со статусом ошибки, а не предупреждение.
    """

    checks: tuple[ValidationCheck, ...]
    hard_failed: bool
    daily_reconciliation_enabled: bool
    unknown_accounts: tuple[str, ...]
    cutoff_suspected: bool


# --------------------------------------------------------------------------- #
# §5.4 — classify
# --------------------------------------------------------------------------- #


class FallbackVerification(_Frozen):
    """Верификация time-fallback варианта C — §3.3.

    Гипотеза принимается только при ``exact_day_share >= 0.90``; иначе
    приложение обязано остановиться со статусом ``BLOCK_CLASSIFICATION_FAILED``.
    """

    accepted: bool
    days_total: int
    days_exact: int
    exact_day_share: float
    collection_delta: Decimal
    refund_delta: Decimal


class ClassifyResult(_Frozen):
    """Выход стадии CLASSIFY — §5.4."""

    ledger: tuple[LedgerEntry, ...]
    ops: tuple[OpsEntry, ...]
    fallback: FallbackVerification | None
    unknown_accounts: tuple[str, ...]


# --------------------------------------------------------------------------- #
# §5.5 — reversals
# --------------------------------------------------------------------------- #


class ReversalResult(_Frozen):
    """Выход стадии NEUTRALIZE_REVERSALS — §5.5.

    ``neutralized_rows`` — номера строк, исключаемых из сверки §5.6.
    """

    neutralized_rows: frozenset[int]
    findings: tuple[Finding, ...]
    audit_log: tuple[AuditLogEntry, ...]


# --------------------------------------------------------------------------- #
# §5.6 — reconcile
# --------------------------------------------------------------------------- #


class CategoryRecon(_Frozen):
    """Сверка по одной категории — §5.6.

    ``ratio = |нетто| / брутто``: 0 — чистый churn, 1 — односторонний сдвиг.
    Возвраты присутствуют в двух вариантах: «как есть» и «скорректировано»
    (за вычетом служебных записей §3.6).

    Дневные ряды хранятся целиком (``acc_series``, ``ops_series``): они нужны
    детектору лага §5.7.1 и календарной агрегации §5.7.3, которые работают с
    самими рядами, а не с их разностью. Ряды упорядочены по дате.

    **Какой ряд считается сверяемым.** ``ops_series`` — вариант «как есть»,
    ``ops_series_adjusted`` — «скорректировано» (§3.6). Сверка ведётся по
    :meth:`reconciled_ops_series`: служебной выдаче в 1С не соответствует
    проводки по определению, поэтому включать её в расхождение значило бы
    объявить расхождением заведомо мнимое (§5.6). Стадии §5.7 и §5.9 обязаны
    брать один и тот же ряд — иначе свёртка оставляет день в остатке, а
    локализация не находит на нём ничего.
    """

    category: Category
    acc_total: Decimal
    ops_total: Decimal
    net: Decimal
    gross: Decimal
    ratio: float | None
    days_with_difference: int
    acc_series: tuple[tuple[date, Decimal], ...]
    ops_series: tuple[tuple[date, Decimal], ...]
    ops_series_adjusted: tuple[tuple[date, Decimal], ...] | None = None
    daily_differences: tuple[tuple[date, Decimal], ...]
    adjusted_net: Decimal | None
    adjusted_gross: Decimal | None

    def reconciled_ops_series(self) -> tuple[tuple[date, Decimal], ...]:
        """Ряд опер-лога, по которому ведётся сверка — §5.6, §3.6."""
        return self.ops_series if self.ops_series_adjusted is None else self.ops_series_adjusted


# --------------------------------------------------------------------------- #
# §5.7 — timing
# --------------------------------------------------------------------------- #


class LagResult(_Frozen):
    """Детектор лага — §5.7.1.

    Лаг значим при ``lagScore(best) < LAG_SIGNIFICANT_RATIO * lagScore(0)``.
    Диагностический вывод: свёртку не меняет, объясняет её пользователю.
    """

    best_lag: int
    scores: tuple[Decimal, ...]
    significant: bool


class CalendarAggregation(_Frozen):
    """Распознанный паттерн «понедельник агрегирует выходные» — §5.7.3."""

    posting_date: date
    source_dates: tuple[date, ...]
    acc_amount: Decimal
    ops_amount: Decimal


class CollapseResult(_Frozen):
    """Результат свёртки тайминга — §5.7.2.

    ``redated`` считается отдельно: проход 3 намеренно консервативен, но может
    свести две разные операции, случайно равные по сумме. Остаток маркируется
    «для разбора», а не «ошибка».
    """

    residual: Decimal
    collapsed: int
    redated: int
    total: int
    residual_days: tuple[tuple[date, Decimal], ...]
    lag: LagResult | None
    calendar_aggregations: tuple[CalendarAggregation, ...]
    audit_log: tuple[AuditLogEntry, ...]


# --------------------------------------------------------------------------- #
# §5.8 — balance
# --------------------------------------------------------------------------- #


class NonNegativityReport(_Frozen):
    """Инвариант неотрицательности относительно T — §5.8.2."""

    first_below_target: date | None
    never_recovered_after: date | None
    minimum: Decimal
    minimum_date: date | None
    share_of_days_below: float


class SweepPoint(_Frozen):
    """Точка «пола кассы» — §5.8.3.

    ``is_full`` = False означает частичную выемку: такие точки помечаются
    «частичная выемка — не показатель» и в ряд пола не входят.
    """

    date: date
    floor: Decimal
    collection: Decimal
    income: Decimal
    is_full: bool


class ChangePointWindow(_Frozen):
    """Датирование level shift окном, а не точкой — §5.8.4.

    ``method`` — ``"pelt"`` (основной, ruptures), подтверждающие — ``"cusum"``,
    ``"ewma"``.
    """

    method: str
    index: int
    window: tuple[date, date]
    confirmed_by: tuple[str, ...]


class WindowFlows(_Frozen):
    """Сопоставление потоков внутри окна смещения — §5.8.5."""

    window: tuple[date, date]
    ledger_flow: Decimal
    ops_flow: Decimal
    dominant_category: Category | None


class BalanceTrace(_Frozen):
    """Выход стадии BALANCE_TRACE — §5.8."""

    opening: Decimal
    closing_computed: Decimal
    target: Decimal
    nonnegativity: NonNegativityReport
    sweep_points: tuple[SweepPoint, ...]
    change_points: tuple[ChangePointWindow, ...]
    shift_windows: tuple[WindowFlows, ...]
    quarterly_balances: tuple[tuple[str, Decimal], ...]


# --------------------------------------------------------------------------- #
# §5.9 / §7 — localize
# --------------------------------------------------------------------------- #


class SubsetSumGateReport(_Frozen):
    """Протокол четырёх гейтов доказательности — §7.3.

    Находка принимается только при ``all(...)`` четырёх флагов. Протокол
    сохраняется всегда, включая отказы: пользователь должен видеть причину.
    """

    candidate_count: int
    solutions_found: int
    """Сколько подмножеств попало в допуск.

    Отличает «решений нет» от «решений несколько»: первое — не неоднозначность,
    а отсутствие объяснения, и статус у них разный (``NOT_LOCALIZED`` против
    ``AMBIGUOUS``).
    """

    gate_count_passed: bool
    gate_unique_passed: bool
    gate_density_passed: bool
    gate_permutation_passed: bool
    expected_solutions: float | None
    p_value: float | None
    permutation_b: int
    seed: int
    refusal_reason: str | None


class LocalizationResult(_Frozen):
    """Результат локализации одного проблемного дня/окна — §5.9.

    ``code`` — находка §8, к которой сводится результат; ``None`` для отказов:
    у отказа нет находки, есть причина в ``explanation`` и протокол в
    ``gates`` (§0.3).

    ``balance_impact`` отделён от ``amount`` намеренно (§4.3): выдача без
    проводки на сальдо не влияет, потому что этой проводки в 1С нет вовсе.
    """

    date: date
    category: Category
    mode: PostingMode
    status: LocalizationStatus
    code: FindingCode | None
    amount: Decimal
    balance_impact: Decimal
    ledger_rows: tuple[int, ...]
    ops_rows: tuple[int, ...]
    doc_numbers: tuple[str, ...]
    gates: SubsetSumGateReport | None
    confidence: float
    explanation: str


# --------------------------------------------------------------------------- #
# §4.3 / §5.10–5.11 — находки, раскладка, ранжирование
# --------------------------------------------------------------------------- #


class Finding(_Mutable):
    """Находка — §4.3 ТЗ.

    ``amount`` и ``balance_impact`` различаются намеренно: 35 непроведённых
    выдач Солигорска на 8 411,73 имеют ``balance_impact = 0``, потому что этих
    проводок в 1С нет вовсе. Путать пробел контроля с причиной отклонения
    нельзя.
    """

    code: FindingCode
    severity: Severity
    date: date | tuple[date, date]
    amount: Decimal
    ledger_rows: list[int] = Field(default_factory=list)
    ops_rows: list[int] = Field(default_factory=list)
    doc_numbers: list[str] = Field(default_factory=list)
    title: str
    explanation: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    confidence: float
    materiality: Materiality
    balance_impact: Decimal


class MaterialityThresholds(_Frozen):
    """Пороги материальности — §7.5."""

    benchmark: Decimal
    overall: Decimal
    performance: Decimal
    trivial: Decimal


class CausalLine(_Frozen):
    """Строка причинной раскладки — §5.10.

    Каждая строка обязана ссылаться на ``Finding`` с трассировкой.
    """

    amount: Decimal
    title: str
    finding_index: int | None
    doc_numbers: tuple[str, ...]


class Waterfall(_Frozen):
    """Раскладка отклонения без остатка — §5.10.

    ``log_imbalance`` (ПКО − РКО_инкассация − РКО_возвраты) выводится отдельной
    строкой: это дефект первички, а не учёта, и смешивать его с расхождениями
    1С запрещено. Требование приёмки: ``|unresolved| < EPS_TIE``.
    """

    closing: Decimal
    target: Decimal
    income_delta: Decimal
    collection_delta: Decimal
    refund_delta: Decimal
    other_delta: Decimal
    log_imbalance: Decimal
    unresolved: Decimal
    causal_lines: tuple[CausalLine, ...]


# --------------------------------------------------------------------------- #
# §8.1–8.2 — сигнатуры
# --------------------------------------------------------------------------- #


class Signature(_Frozen):
    """Сигнатура риска — §8.1–8.2.

    ``baseline`` обязателен для повторов: базовая частота по ПКО включается в
    отчёт как контекст, иначе сигнатура читается как обвинение (§8.1).

    ``severity`` — необязательное понижение уровня относительно таблицы §8.
    Понадобилось ради §8.2: при сквозной по организации нумерации «тест
    понижается до информационного». ``None`` означает «уровень по коду».
    """

    code: FindingCode
    title: str
    date: date | None
    amount: Decimal | None
    rows: tuple[int, ...]
    baseline: str | None
    explanation: str
    severity: Severity | None = None


# --------------------------------------------------------------------------- #
# §12 — аудиторский след
# --------------------------------------------------------------------------- #


class AuditLogEntry(_Frozen):
    """Запись журнала автогашения — §12.

    Для каждого автоматического гашения: что погашено, чем, каким правилом.
    Журнал попадает в JSON и в лист Excel по флагу ``--audit-log``.
    """

    stage: str
    rule: str
    subject_rows: tuple[int, ...]
    counterpart_rows: tuple[int, ...]
    amount: Decimal
    note: str


# --------------------------------------------------------------------------- #
# §4.4 — результат анализа
# --------------------------------------------------------------------------- #


class AnalysisResult(_Mutable):
    """Полный результат анализа — §4.4 ТЗ.

    Сериализуется в JSON (§9.2) как эталон для регрессионных тестов §11.3.
    Повторный прогон обязан давать побитово идентичный JSON (§13.5).
    """

    meta: FileMeta
    validation: ValidationReport
    reconciliation: dict[Category, CategoryRecon]
    timing: dict[Category, CollapseResult]
    balance_trace: BalanceTrace
    waterfall: Waterfall
    findings: list[Finding]
    signatures: list[Signature]
    localizations: list[LocalizationResult] = Field(default_factory=list)
    audit_log: list[AuditLogEntry] = Field(default_factory=list)
    unresolved: Decimal


# --------------------------------------------------------------------------- #
# §6 — конфигурация
# --------------------------------------------------------------------------- #


class TargetBalanceRule(_Frozen):
    """Элемент ``target_balance_schedule`` — §6."""

    from_: date = Field(alias="from")
    value: Decimal


class Thresholds(_Frozen):
    """Секция ``thresholds`` — §6."""

    EPS_FLOOR: Decimal
    EPS_SUM: Decimal
    EPS_TIE: Decimal
    DATE_WIN: int
    LONG_WIN: int
    MAX_LAG: int
    LAG_SIGNIFICANT_RATIO: float
    MODAL_BAD: float
    MIN_DAYS: int
    SWEEP_MIN_RATIO: float
    ROUND_MAX: Decimal
    AGGREGATE_RATIO: float


class SubsetSumConfig(_Frozen):
    """Секция ``subset_sum`` — §6, гейты §7.3."""

    MAX_CANDIDATES: int
    HARD_MAX: int
    REQUIRE_UNIQUE: bool
    MAX_SUBSET_SIZE: int | None
    PERMUTATION_B: int
    PERMUTATION_ALPHA: float
    TOLERANCE: Decimal


class ChangepointConfig(_Frozen):
    """Секция ``changepoint`` — §6, метод §5.8.4."""

    method: str
    model: str
    penalty: str
    min_size: int
    cusum_k: float
    cusum_h: float
    ewma_lambda: float
    ewma_L: float


class StatisticsConfig(_Frozen):
    """Секция ``statistics`` — §6.

    ``benford_min_n``: закон Бенфорда не применяется при N < ~1700 (§15).
    """

    mod_z_threshold: float
    iqr_soft: float
    iqr_extreme: float
    benford_min_n: int
    fuzzy_name_threshold: float


class SignaturesConfig(_Frozen):
    """Секция ``signatures`` — §6, §8.1."""

    repeat_window_minutes: int
    repeat_min_count: int
    late_time: str
    business_hours: tuple[str, str]


class MaterialityConfig(_Frozen):
    """Секция ``materiality`` — §6, §7.5."""

    benchmark: str
    overall_pct: float
    performance_pct: float
    trivial_pct: float


class CalendarConfig(_Frozen):
    """Секция ``calendar`` — §6, §5.7.3."""

    holidays_file: Path


class PatternsConfig(_Frozen):
    r"""Секция ``patterns`` — §6, §3.6.

    ``service_recipients`` обязан быть заякорен (``^суд\b``): версия без якоря
    отбрасывала выдачу «Правосуд Дмитрий» (§3.6).
    """

    central_cash: str
    service_recipients: str
    reversal_doc: str


class Config(_Frozen):
    """Единый YAML-конфиг — §6 ТЗ.

    Версионируется вместе с кодом; хеш конфига попадает в отчёт (§12).
    """

    source_path: Path | None = None
    """Откуда прочитан конфиг. Заполняется :func:`load_config`, не из YAML."""

    source_sha256: str | None = None
    """Хеш файла конфига — попадает в ``FileMeta`` каждого отчёта (§12)."""

    version: str
    cash_account: str
    target_balance: Decimal
    target_balance_schedule: tuple[TargetBalanceRule, ...] = ()
    seed: int
    accounts: dict[str, tuple[str, ...]]
    patterns: PatternsConfig
    thresholds: Thresholds
    subset_sum: SubsetSumConfig
    changepoint: ChangepointConfig
    statistics: StatisticsConfig
    signatures: SignaturesConfig
    materiality: MaterialityConfig
    calendar: CalendarConfig


class _DecimalLoader(yaml.SafeLoader):
    """YAML-загрузчик, поднимающий дробные скаляры как ``Decimal``.

    Штатный ``SafeLoader`` отдаёт ``float``, и ``TOLERANCE: 0.005`` превращается
    в двоичную дробь, не равную 0,005. Дальше это уезжает в допуск subset-sum
    (§7.3) и в пороги свёртки (§5.7.2), где сравнение идёт по копейке.

    Конструктор берёт **исходную строку** скаляра, поэтому значение в конфиге и
    значение в памяти совпадают посимвольно.
    """


def _construct_decimal(loader: yaml.SafeLoader, node: yaml.ScalarNode) -> Decimal | float:
    """Собрать ``Decimal`` из исходного текста скаляра — см. :class:`_DecimalLoader`."""
    raw = loader.construct_scalar(node)
    try:
        return Decimal(raw)
    except InvalidOperation:
        # .inf / .nan и прочие специальные значения YAML — отдаём штатному float.
        return float(raw)


_DecimalLoader.add_constructor("tag:yaml.org,2002:float", _construct_decimal)


def load_config(path: Path) -> Config:
    """Загрузить и провалидировать YAML-конфиг §6.

    Дробные значения читаются как :class:`~decimal.Decimal` (см.
    :class:`_DecimalLoader`); поля, объявленные ``float``, пересчитываются
    pydantic — там точность до копейки не нужна.

    Args:
        path: путь к ``config/default.yaml`` или пользовательскому конфигу.

    Returns:
        Разобранный :class:`Config`.

    Raises:
        FileNotFoundError: конфига нет по указанному пути.
        pydantic.ValidationError: конфиг не соответствует §6 — лишний ключ,
            отсутствующая секция, неразбираемое значение.
    """
    raw = yaml.load(path.read_text(encoding="utf-8"), Loader=_DecimalLoader)  # noqa: S506
    config = Config.model_validate(raw)
    return config.model_copy(
        update={"source_path": path, "source_sha256": config_sha256(path)},
    )


def config_sha256(path: Path) -> str:
    """Хеш конфига для метаданных отчёта — §12, «версионирование правил».

    Считается по байтам файла: в отчёт должно попадать то, что реально лежало на
    диске, а не результат нормализации YAML.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()
