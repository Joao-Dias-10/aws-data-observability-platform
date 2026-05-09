"""
modules/transformations.py — Transformações do pipeline SLA.
Classe stateless: recebe DataFrame, retorna DataFrame.
Cada etapa é um método privado — facilita teste unitário individual.
"""

import logging

from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import DoubleType, TimestampType
from pyspark.sql.window import Window

logger = logging.getLogger(__name__)


class SLATransformer:

    def run(self, df: DataFrame) -> DataFrame:
        logger.info("Iniciando transformações")
        df = self._cast_types(df)
        df = self._deduplicate(df)
        df = self._normalize(df)
        df = self._add_metadata(df)
        logger.info("Transformações concluídas")
        return df

    def _cast_types(self, df: DataFrame) -> DataFrame:
        """Garante tipos corretos — evita erros silenciosos vindos de JSON."""
        return (
            df
            .withColumn("metric_value", F.col("metric_value").cast(DoubleType()))
            .withColumn("event_ts",     F.col("event_ts").cast(TimestampType()))
        )

    def _deduplicate(self, df: DataFrame) -> DataFrame:
        """
        Remove duplicatas por event_id mantendo o registro mais recente.
        Preferível ao dropDuplicates simples — controle sobre qual sobrevive.
        """
        window = Window.partitionBy("event_id").orderBy(F.col("event_ts").desc())
        return (
            df
            .withColumn("_rank", F.row_number().over(window))
            .filter(F.col("_rank") == 1)
            .drop("_rank")
        )

    def _normalize(self, df: DataFrame) -> DataFrame:
        """Padroniza source_system para lowercase — evita split por capitalização."""
        return df.withColumn("source_system", F.lower(F.trim(F.col("source_system"))))

    def _add_metadata(self, df: DataFrame) -> DataFrame:
        """Adiciona colunas de controle de pipeline para rastreabilidade."""
        return (
            df
            .withColumn("event_date",       F.to_date(F.col("event_ts")))
            .withColumn("processed_at",     F.current_timestamp())
            .withColumn("pipeline_version", F.lit("1.0.0"))
        )
