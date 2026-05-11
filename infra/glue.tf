# Glue Catalog Database — registra as tabelas sem crawler
resource "aws_glue_catalog_database" "sla" {
  name = "sla_db_${var.environment}"
}

# Tabela Silver no Catalog — schema explícito, sem crawler
# Crawler inferência de schema pode mudar tipos silenciosamente em produção
resource "aws_glue_catalog_table" "silver_metrics" {
  name          = "silver_metrics"
  database_name = aws_glue_catalog_database.sla.name

  table_type = "EXTERNAL_TABLE"

  parameters = {
    "classification"       = "parquet"
    "parquet.compress"     = "SNAPPY"
    "EXTERNAL"             = "TRUE"
  }

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.data.bucket}/silver/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
      parameters            = { "serialization.format" = "1" }
    }

    columns {
      name = "event_id"
      type = "string"
    }
    columns {
      name = "metric_value"
      type = "double"
    }
    columns {
      name = "event_ts"
      type = "timestamp"
    }
    columns {
      name = "processed_at"
      type = "timestamp"
    }
    columns {
      name = "pipeline_version"
      type = "string"
    }
  }

  partition_keys {
    name = "source_system"
    type = "string"
  }
  partition_keys {
    name = "event_date"
    type = "date"
  }
}

# Glue Job
resource "aws_glue_job" "pipeline" {
  name         = "${var.project}-pipeline-${var.environment}"
  role_arn     = aws_iam_role.glue.arn
  glue_version = "4.0"
  max_retries  = 1
  timeout      = 60

  command {
    name            = "glueetl"
    script_location = "s3://${aws_s3_bucket.data.bucket}/scripts/sla_pipeline.py"
    python_version  = "3"
  }

  # G.025X é o menor worker disponível — suficiente para dados de portfólio
  # Em prod com volume real, escalar para G.1X ou G.2X
  worker_type = var.environment == "prod" ? "G.2X" : "G.1X"
  number_of_workers = var.environment == "prod" ? 4 : 2

  default_arguments = {
    "--job-language"                     = "python"
    "--enable-continuous-cloudwatch-log" = "true"
    "--enable-metrics"                   = "true"
    "--enable-spark-ui"                  = "true"
    "--spark-event-logs-path"            = "s3://${aws_s3_bucket.data.bucket}/spark-logs/"
    "--extra-py-files"                   = "s3://${aws_s3_bucket.data.bucket}/scripts/modules.zip"
    "--RAW_PATH"                         = "s3://${aws_s3_bucket.data.bucket}/raw"
    "--SILVER_PATH"                      = "s3://${aws_s3_bucket.data.bucket}/silver"
    "--SNS_TOPIC_ARN"                    = aws_sns_topic.alerts.arn
    "--SOURCE_SYSTEM"                    = "all"
    "--EXECUTION_DATE"                   = "REPLACE_AT_TRIGGER"
  }
}

# Trigger diário — só ativo em prod
resource "aws_glue_trigger" "daily" {
  name     = "${var.project}-daily-${var.environment}"
  type     = "SCHEDULED"
  schedule = "cron(0 2 * * ? *)"
  enabled  = var.environment == "prod"

  actions {
    job_name = aws_glue_job.pipeline.name
  }
}

output "glue_job_name" {
  value = aws_glue_job.pipeline.name
}
