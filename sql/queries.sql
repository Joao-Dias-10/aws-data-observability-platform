-- sql/setup_catalog.sql
-- Executar UMA VEZ após o terraform apply para registrar as tabelas no Glue Catalog.
-- Athena usa o Catalog para saber schema e localização dos dados — sem crawler.
-- Sem crawler: schema controlado explicitamente (melhor para produção).

-- ──────────────────────────────────────────────────────────────────────────────
-- 1. Database
-- ──────────────────────────────────────────────────────────────────────────────
CREATE DATABASE IF NOT EXISTS sla_db
LOCATION 's3://BUCKET_NAME/';

-- ──────────────────────────────────────────────────────────────────────────────
-- 2. Tabela Silver — aponta para os parquets gerados pelo Glue
--    Partições declaradas explicitamente (sem crawler = schema estável)
-- ──────────────────────────────────────────────────────────────────────────────
CREATE EXTERNAL TABLE IF NOT EXISTS sla_db.silver_metrics (
    event_id         STRING,
    metric_value     DOUBLE,
    event_ts         TIMESTAMP,
    processed_at     TIMESTAMP,
    pipeline_version STRING
)
PARTITIONED BY (
    source_system STRING,
    event_date    DATE
)
STORED AS PARQUET
LOCATION 's3://BUCKET_NAME/silver/'
TBLPROPERTIES ('parquet.compress' = 'SNAPPY');

-- Após cada execução do Glue, sincronize as novas partições:
-- MSCK REPAIR TABLE sla_db.silver_metrics;
-- (ou use ALTER TABLE ADD PARTITION para controle granular)


-- ──────────────────────────────────────────────────────────────────────────────
-- sql/consolidation.sql
-- Consolidação incremental — roda via Athena após o Glue Job
-- Substitua :execution_date pela data desejada ex: '2024-01-15'
-- ──────────────────────────────────────────────────────────────────────────────

-- Resumo por sistema e data
SELECT
    source_system,
    event_date,
    COUNT(*)                                                AS record_count,
    ROUND(AVG(metric_value), 2)                            AS avg_value,
    MIN(metric_value)                                      AS min_value,
    MAX(metric_value)                                      AS max_value,
    SUM(CASE WHEN metric_value < 0    THEN 1 ELSE 0 END)  AS negative_count,
    SUM(CASE WHEN metric_value > 1e6  THEN 1 ELSE 0 END)  AS outlier_count,
    ROUND(
        100.0 * SUM(CASE WHEN metric_value < 0 THEN 1 ELSE 0 END)
        / NULLIF(COUNT(*), 0), 2
    )                                                      AS issues_pct,
    CASE
        WHEN SUM(CASE WHEN metric_value < 0 THEN 1 ELSE 0 END) = 0 THEN 'OK'
        WHEN 100.0 * SUM(CASE WHEN metric_value < 0 THEN 1 ELSE 0 END)
             / NULLIF(COUNT(*), 0) < 5.0                  THEN 'WARNING'
        ELSE                                                    'CRITICAL'
    END                                                    AS health_status
FROM sla_db.silver_metrics
WHERE event_date = DATE ':execution_date'
GROUP BY source_system, event_date
ORDER BY health_status DESC, record_count DESC;


-- ──────────────────────────────────────────────────────────────────────────────
-- Comparação cross-system — detecta divergência entre sistemas
-- Útil para o caso de uso central: CRM reporta X, ERP reporta Y para o mesmo período
-- ──────────────────────────────────────────────────────────────────────────────
WITH daily_summary AS (
    SELECT
        source_system,
        event_date,
        ROUND(AVG(metric_value), 2) AS avg_value,
        COUNT(*)                    AS record_count
    FROM sla_db.silver_metrics
    WHERE event_date = DATE ':execution_date'
    GROUP BY source_system, event_date
)
SELECT
    a.event_date,
    a.source_system                                          AS system_a,
    b.source_system                                          AS system_b,
    a.avg_value                                              AS avg_a,
    b.avg_value                                              AS avg_b,
    ABS(a.avg_value - b.avg_value)                           AS absolute_diff,
    ROUND(
        100.0 * ABS(a.avg_value - b.avg_value)
        / NULLIF(a.avg_value, 0), 2
    )                                                        AS pct_diff
FROM daily_summary a
JOIN daily_summary b
  ON  a.event_date    = b.event_date
  AND a.source_system < b.source_system   -- evita duplicar pares (CRM vs ERP = ERP vs CRM)
WHERE ABS(a.avg_value - b.avg_value) > 10
ORDER BY pct_diff DESC;
