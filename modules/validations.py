"""
modules/validations.py — Motor de validação declarativo.
Regras são dataclasses — adicionar nova regra é uma linha no catálogo.
Retorna DataFrame de issues (não booleano) — permite análise downstream.
"""

import logging
from dataclasses import dataclass
from typing import List

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

logger = logging.getLogger(__name__)


@dataclass
class ValidationRule:
    rule_id:     str   # ex: VAL_001
    severity:    str   # CRITICAL | WARNING
    condition:   str   # expressão SQL — True = problema encontrado
    description: str


RULES: List[ValidationRule] = [
    ValidationRule("VAL_001", "CRITICAL", "metric_value < 0",
                   "metric_value não pode ser negativo"),
    ValidationRule("VAL_002", "CRITICAL", "event_id IS NULL",
                   "event_id obrigatório"),
    ValidationRule("VAL_003", "CRITICAL", "source_system IS NULL OR source_system = ''",
                   "source_system obrigatório"),
    ValidationRule("VAL_004", "WARNING",  "metric_value > 1000000",
                   "metric_value suspeito — acima de 1M"),
    ValidationRule("VAL_005", "WARNING",  "event_ts IS NULL",
                   "event_ts ausente — rastreabilidade comprometida"),
]


class SLAValidator:

    def __init__(self, rules: List[ValidationRule] = None):
        self.rules = rules or RULES

    def run(self, df: DataFrame) -> DataFrame:
        """
        Aplica cada regra e faz UNION dos issues encontrados.
        Schema de saída: event_id, source_system, event_date,
                         rule_id, severity, description, detected_at
        """
        issue_dfs = []

        for rule in self.rules:
            issues = (
                df.filter(rule.condition)
                .select(
                    F.col("event_id"),
                    F.col("source_system"),
                    F.col("event_date"),
                    F.lit(rule.rule_id).alias("rule_id"),
                    F.lit(rule.severity).alias("severity"),
                    F.lit(rule.description).alias("description"),
                    F.current_timestamp().alias("detected_at"),
                )
            )
            count = issues.count()
            if count > 0:
                logger.warning("Regra violada | %s | %s | count=%d",
                               rule.rule_id, rule.severity, count)
                issue_dfs.append(issues)

        if not issue_dfs:
            logger.info("Nenhuma inconsistência encontrada")
            return df.limit(0).select("event_id", "source_system", "event_date")

        result = issue_dfs[0]
        for other in issue_dfs[1:]:
            result = result.union(other)
        return result
