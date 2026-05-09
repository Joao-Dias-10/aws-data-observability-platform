"""
modules/notifier.py — Publica evento de inconsistência no SNS.
SNS desacopla o Glue Job dos consumidores (Lambda, email, Slack, etc.).
Adicionar um novo destino = nova subscription no SNS, sem tocar no pipeline.
"""

import json
import logging
import boto3

logger = logging.getLogger(__name__)


class InconsistencyNotifier:

    def __init__(self, topic_arn: str):
        self.topic_arn = topic_arn
        self._sns      = boto3.client("sns")

    def notify(self, issues_count: int, execution_date: str, source_system: str) -> None:
        severity = "CRITICAL" if issues_count > 100 else "WARNING"

        payload = {
            "event":          "SLA_INCONSISTENCY_DETECTED",
            "execution_date": execution_date,
            "source_system":  source_system,
            "issues_count":   issues_count,
            "severity":       severity,
        }

        logger.info("Publicando SNS | topic=%s | severity=%s | issues=%d",
                    self.topic_arn, severity, issues_count)

        self._sns.publish(
            TopicArn=self.topic_arn,
            Subject=f"[SLA] {issues_count} inconsistências detectadas | {execution_date}",
            Message=json.dumps(payload, ensure_ascii=False, indent=2),
            # MessageAttribute permite que subscriptions filtrem por severidade
            # sem precisar processar o payload completo
            MessageAttributes={
                "severity": {"DataType": "String", "StringValue": severity},
            },
        )
