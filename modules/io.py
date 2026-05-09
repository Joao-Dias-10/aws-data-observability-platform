"""
modules/io.py — Leitura e escrita com particionamento real.
SparkSession recebida como dependência — nunca instanciada aqui.
"""

import logging
from typing import Optional

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

logger = logging.getLogger(__name__)


class DataReader:
    def __init__(self, spark: SparkSession, raw_path: str):
        self.spark    = spark
        self.raw_path = raw_path

    def read(self, execution_date: str, source_system: Optional[str] = "all") -> DataFrame:
        """
        Lê apenas a partição do dia (partition pruning).
        Registros com schema inválido vão para _quarantine/ em vez de derrubar o job.
        """
        path = f"{self.raw_path}/event_date={execution_date}"
        logger.info("Lendo: %s", path)

        df = (
            self.spark.read
            .option("badRecordsPath", f"{self.raw_path}/_quarantine/{execution_date}")
            .json(path)
        )

        if source_system != "all":
            df = df.filter(F.col("source_system") == source_system)

        return df


class DataWriter:
    def __init__(self, spark: SparkSession, silver_path: str):
        self.spark       = spark
        self.silver_path = silver_path

    def write(self, df: DataFrame, execution_date: str) -> None:
        """
        Parquet particionado por source_system + event_date.
        Dynamic partition overwrite: sobrescreve só o dia, não o dataset inteiro.
        Isso garante idempotência — reprocessar a mesma data é seguro.
        """
        logger.info("Escrevendo silver | path=%s | date=%s", self.silver_path, execution_date)

        (
            df.write
            .mode("overwrite")
            .partitionBy("source_system", "event_date")
            .parquet(self.silver_path)
        )
