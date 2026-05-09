"""
tests/test_pipeline.py — Testes unitários com pyspark local (sem AWS).
"""

import pytest
from datetime import datetime

from pyspark.sql import SparkSession
from pyspark.sql.types import (
    StructType, StructField, StringType, DoubleType, TimestampType
)

from modules.transformations import SLATransformer
from modules.validations import SLAValidator


@pytest.fixture(scope="session")
def spark():
    return (
        SparkSession.builder
        .master("local[1]")
        .appName("sla-tests")
        .config("spark.sql.shuffle.partitions", "1")
        .getOrCreate()
    )


SCHEMA = StructType([
    StructField("event_id",      StringType(),    True),
    StructField("source_system", StringType(),    True),
    StructField("metric_value",  DoubleType(),    True),
    StructField("event_ts",      TimestampType(), True),
])


def make_df(spark, rows):
    return spark.createDataFrame(rows, SCHEMA)


# ── Transformações ────────────────────────────────────────────────────────────

class TestTransformer:

    def test_dedup_keeps_latest(self, spark):
        rows = [
            ("ev1", "crm", 100.0, datetime(2024, 1, 15, 10, 0)),
            ("ev1", "crm", 200.0, datetime(2024, 1, 15, 12, 0)),  # mais recente
        ]
        result = SLATransformer().run(make_df(spark, rows))
        assert result.count() == 1
        assert result.first()["metric_value"] == 200.0

    def test_normalize_lowercases_source(self, spark):
        rows = [("ev1", "CRM", 100.0, datetime(2024, 1, 15))]
        result = SLATransformer().run(make_df(spark, rows))
        assert result.first()["source_system"] == "crm"

    def test_metadata_columns_added(self, spark):
        rows = [("ev1", "crm", 100.0, datetime(2024, 1, 15))]
        result = SLATransformer().run(make_df(spark, rows))
        cols = result.columns
        assert "event_date"       in cols
        assert "processed_at"     in cols
        assert "pipeline_version" in cols


# ── Validações ────────────────────────────────────────────────────────────────

class TestValidator:

    def test_negative_metric_flagged(self, spark):
        rows = [("ev1", "crm", -10.0, datetime(2024, 1, 15))]
        df = SLATransformer().run(make_df(spark, rows))
        issues = SLAValidator().run(df)
        rule_ids = [r["rule_id"] for r in issues.collect()]
        assert "VAL_001" in rule_ids

    def test_null_event_id_flagged(self, spark):
        rows = [(None, "crm", 100.0, datetime(2024, 1, 15))]
        df = SLATransformer().run(make_df(spark, rows))
        issues = SLAValidator().run(df)
        rule_ids = [r["rule_id"] for r in issues.collect()]
        assert "VAL_002" in rule_ids

    def test_clean_data_no_issues(self, spark):
        rows = [("ev1", "crm", 100.0, datetime(2024, 1, 15))]
        df = SLATransformer().run(make_df(spark, rows))
        assert SLAValidator().run(df).count() == 0
