"""
SLA Data Platform — Glue Job entrypoint
SparkSession criada aqui, injetada nos módulos (nunca instanciada dentro deles).
"""

import sys
import logging

from awsglue.utils import getResolvedOptions
from pyspark.sql import SparkSession

from modules.io import DataReader, DataWriter
from modules.transformations import SLATransformer
from modules.validations import SLAValidator
from modules.notifier import InconsistencyNotifier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("sla_pipeline")


def get_args() -> dict:
    return getResolvedOptions(
        sys.argv,
        [
            "JOB_NAME",
            "RAW_PATH",
            "SILVER_PATH",
            "SNS_TOPIC_ARN",
            "EXECUTION_DATE",   # ex: 2024-01-15
            "SOURCE_SYSTEM",    # ex: crm | erp | all
        ],
    )


def build_spark(job_name: str) -> SparkSession:
    return (
        SparkSession.builder
        .appName(job_name)
        # Overwrite apenas a partição do dia — não o lake inteiro
        .config("spark.sql.sources.partitionOverwriteMode", "dynamic")
        # Adaptive Query Execution — melhora joins e shuffles automaticamente
        .config("spark.sql.adaptive.enabled", "true")
        .getOrCreate()
    )


def main():
    args = get_args()
    execution_date = args["EXECUTION_DATE"]
    source_system  = args["SOURCE_SYSTEM"]

    logger.info("Job iniciado | date=%s | source=%s", execution_date, source_system)

    spark = build_spark(args["JOB_NAME"])

    try:
        # 1. Leitura incremental (só a partição do dia)
        df_raw = DataReader(spark, args["RAW_PATH"]).read(
            execution_date=execution_date,
            source_system=source_system,
        )
        logger.info("Leitura ok | registros=%d", df_raw.count())

        # 2. Transformação
        df_silver = SLATransformer().run(df_raw)
        logger.info("Transformação ok")

        # 3. Validação — retorna DataFrame de issues
        issues_df    = SLAValidator().run(df_silver)
        issues_count = issues_df.count()
        logger.info("Validação ok | inconsistências=%d", issues_count)

        # 4. Escrita silver (parquet particionado)
        DataWriter(spark, args["SILVER_PATH"]).write(
            df_silver, execution_date=execution_date
        )
        logger.info("Escrita ok")

        # 5. Notifica via SNS se houver inconsistências
        if issues_count > 0:
            InconsistencyNotifier(args["SNS_TOPIC_ARN"]).notify(
                issues_count=issues_count,
                execution_date=execution_date,
                source_system=source_system,
            )
            logger.warning("SNS publicado | issues=%d", issues_count)

        logger.info("Job finalizado com sucesso")

    except Exception as exc:
        logger.exception("Job falhou: %s", exc)
        raise  # Glue marca como FAILED e registra no CloudWatch


if __name__ == "__main__":
    main()
