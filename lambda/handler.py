"""
lambda/handler.py — Consumidor SNS com função real na arquitetura.

Responsabilidades:
  1. Parsear e validar o payload de inconsistência
  2. Emitir métrica customizada no CloudWatch (issues_count por sistema)
     → permite criar alarmes e dashboards sem custo adicional de DB
  3. Logar alerta estruturado (JSON) → consultável via CloudWatch Logs Insights
  4. Acionar alerta Slack/email mockado (extensível sem mudar o pipeline)

Por que Lambda aqui e não só email via SNS?
  - Email via SNS é texto plano — sem formatação, sem métricas, sem histórico.
  - Lambda permite enriquecer o evento, emitir métricas customizadas e
    integrar com qualquer destino (Slack, PagerDuty, etc.) sem tocar no Glue.
  - CloudWatch Metrics ficam disponíveis para alarmes automáticos.
"""

import json
import logging
import os
from datetime import datetime, timezone

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

CLOUDWATCH_NAMESPACE = os.environ.get("CLOUDWATCH_NAMESPACE", "SLAPlatform")
ENVIRONMENT          = os.environ.get("ENVIRONMENT", "dev")
SLACK_WEBHOOK_URL    = os.environ.get("SLACK_WEBHOOK_URL", "")  # opcional

cloudwatch = boto3.client("cloudwatch")


# ──────────────────────────────────────────────
# Entrypoint
# ──────────────────────────────────────────────
def lambda_handler(event: dict, context) -> dict:
    """
    Triggered por SNS. Cada Record contém um evento de inconsistência.
    Processa todos os records — retorna contagem de sucessos e erros.
    """
    records  = event.get("Records", [])
    results  = {"processed": 0, "errors": 0}

    for record in records:
        try:
            payload = _parse_sns_record(record)
            _handle_inconsistency(payload)
            results["processed"] += 1
        except Exception as exc:
            logger.exception("Erro ao processar record: %s", exc)
            results["errors"] += 1

    logger.info("Lambda finalizada | %s", results)
    return results


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────
def _parse_sns_record(record: dict) -> dict:
    """Extrai e valida o payload do envelope SNS."""
    raw = record["Sns"]["Message"]
    payload = json.loads(raw)

    required = {"event", "execution_date", "source_system", "issues_count", "severity"}
    missing  = required - payload.keys()
    if missing:
        raise ValueError(f"Payload incompleto — campos ausentes: {missing}")

    return payload


def _handle_inconsistency(payload: dict) -> None:
    """Orquestra as reações ao evento de inconsistência."""
    execution_date = payload["execution_date"]
    source_system  = payload["source_system"]
    issues_count   = payload["issues_count"]
    severity       = payload["severity"]

    # 1. Log estruturado — consultável via CloudWatch Logs Insights
    logger.info(json.dumps({
        "event":          payload["event"],
        "execution_date": execution_date,
        "source_system":  source_system,
        "issues_count":   issues_count,
        "severity":       severity,
        "environment":    ENVIRONMENT,
        "handled_at":     datetime.now(timezone.utc).isoformat(),
    }))

    # 2. Métrica customizada no CloudWatch
    # Permite criar alarmes como: "alertar se issues_count > 500 por 2 períodos"
    _emit_cloudwatch_metric(
        metric_name="IssuesCount",
        value=issues_count,
        dimensions={
            "SourceSystem": source_system,
            "Severity":     severity,
            "Environment":  ENVIRONMENT,
        },
    )

    # 3. Alerta formatado — Slack real se SLACK_WEBHOOK_URL configurado, log caso contrário
    alert_message = _format_alert(payload)
    if SLACK_WEBHOOK_URL:
        _send_slack(alert_message, severity)
    else:
        # Em dev/portfólio: log estruturado simula o alerta
        logger.warning("ALERTA | %s", json.dumps(alert_message))


def _emit_cloudwatch_metric(metric_name: str, value: float, dimensions: dict) -> None:
    """
    Emite métrica customizada no CloudWatch.
    Custo: $0.30 por métrica/mês — com 2-3 métricas fica <$1/mês.
    """
    cloudwatch.put_metric_data(
        Namespace=CLOUDWATCH_NAMESPACE,
        MetricData=[{
            "MetricName": metric_name,
            "Value":      value,
            "Unit":       "Count",
            "Dimensions": [
                {"Name": k, "Value": v} for k, v in dimensions.items()
            ],
        }],
    )
    logger.info("Métrica emitida | %s=%s | dims=%s", metric_name, value, dimensions)


def _format_alert(payload: dict) -> dict:
    """Formata o alerta estruturado — mesmo schema para Slack, email, PagerDuty."""
    severity     = payload["severity"]
    issues_count = payload["issues_count"]
    source       = payload["source_system"]
    date         = payload["execution_date"]

    emoji = "🔴" if severity == "CRITICAL" else "🟡"

    return {
        "title":   f"{emoji} SLA Platform — {severity}",
        "summary": f"{issues_count} inconsistências detectadas em '{source}' ({date})",
        "fields": {
            "Sistema":        source,
            "Data":           date,
            "Inconsistências": issues_count,
            "Severidade":     severity,
            "Ambiente":       ENVIRONMENT,
        },
    }


def _send_slack(alert: dict, severity: str) -> None:
    """
    Envia alerta formatado para Slack via Incoming Webhook.
    Configure SLACK_WEBHOOK_URL nas variáveis de ambiente da Lambda.
    """
    import urllib.request

    color   = "#FF0000" if severity == "CRITICAL" else "#FFA500"
    fields  = [
        {"title": k, "value": str(v), "short": True}
        for k, v in alert["fields"].items()
    ]
    payload = {
        "attachments": [{
            "color":    color,
            "title":    alert["title"],
            "text":     alert["summary"],
            "fields":   fields,
            "footer":   "SLA Data Platform",
            "ts":       int(datetime.now(timezone.utc).timestamp()),
        }]
    }

    req = urllib.request.Request(
        SLACK_WEBHOOK_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        logger.info("Slack response: %d", resp.status)
