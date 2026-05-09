# SLA Data Platform

> Pipeline de detecção de inconsistências em métricas operacionais entre múltiplos sistemas (CRM, ERP, Billing).

---

## 🎯 Problema

Empresas com alto volume de processos sofrem com divergência de métricas entre sistemas distintos — causando decisões baseadas em dados incorretos. Este pipeline detecta, quantifica e alerta sobre essas inconsistências automaticamente.

---

## 🏗 Arquitetura

```
S3 raw/  (JSON particionado por data)
    │
    ▼  AWS Glue Job (PySpark)
    │  • deduplicação por event_id (row_number)
    │  • normalização de tipos e source_system
    │  • validação por regras declarativas
    │
S3 silver/  (Parquet, SNAPPY, particionado por source_system + event_date)
    │
    ▼  AWS Athena + Glue Catalog
    │  • queries analíticas e cross-system comparison
    │  • schema registrado explicitamente (sem crawler)
    │
    ▼  SNS Topic (se issues detectados)
    │
    ├──▶ Email subscription  (alerta imediato)
    │
    └──▶ Lambda
         • valida e enriquece o payload
         • emite métrica customizada no CloudWatch (IssuesCount por sistema)
         • loga alerta estruturado (JSON) → consultável via Logs Insights
         • envia para Slack via Webhook (opcional)
         • CloudWatch Alarm dispara novo SNS se IssuesCount > 500
```

---

## 📁 Estrutura

```
sla-platform/
├── jobs/
│   └── sla_pipeline.py        # Glue Job entrypoint — SparkSession criada aqui
├── modules/
│   ├── io.py                  # DataReader / DataWriter com injeção de SparkSession
│   ├── transformations.py     # SLATransformer — dedup, cast, normalize, metadata
│   ├── validations.py         # SLAValidator — motor de regras declarativo
│   └── notifier.py            # InconsistencyNotifier — publica no SNS
├── lambda/
│   └── handler.py             # CloudWatch metrics + Slack + log estruturado
├── sql/
│   └── queries.sql            # Setup do Catalog + consolidação + cross-system
├── infra/
│   ├── main.tf                # Provider + backend S3
│   ├── variables.tf
│   ├── s3.tf                  # Bucket + versionamento + lifecycle
│   ├── iam.tf                 # Roles com least privilege
│   ├── glue.tf                # Job + Catalog Database + Table + Trigger
│   └── sns_lambda.tf          # SNS + Lambda + CloudWatch Alarm + Athena Workgroup
├── tests/
│   └── test_pipeline.py       # pytest + pyspark local (sem AWS)
├── data/
│   └── sample.jsonl           # Dados de exemplo com cenários de erro
├── Makefile
├── requirements.txt
└── README.md
```

---

## ⚙️ Stack e decisões técnicas

| Componente | Escolha | Trade-off |
|---|---|---|
| Processamento | Glue + PySpark | Serverless, integrado com S3/Catalog. EMR seria mais barato em jobs longos, mas requer gestão de cluster. |
| Storage analítico | **Athena** | Paga por query ($5/TB). Sem custo idle. Redshift Serverless cobra por RPU-hora mesmo parado — inviável para portfólio. |
| Schema | Glue Catalog sem crawler | Crawler pode alterar tipos silenciosamente em produção. Schema explícito = controle total. |
| Alertas | SNS | Desacopla o pipeline dos consumidores. Adicionar Slack/PagerDuty = nova subscription, sem tocar no Glue. |
| Enriquecimento | Lambda | Email via SNS é texto plano. Lambda emite métricas CloudWatch (gratuito no free tier), permite formatação rica e integração com qualquer destino. |
| IaC | Terraform | Reproduzível, multi-ambiente, versionável. |
| DynamoDB | **Removido** | CloudWatch Logs Insights substitui para consultar histórico de alertas sem custo adicional de DB. |
| Redshift | **Removido** | Athena cobre 100% do caso de uso analítico com custo ~$0 para dados de portfólio. |

---

## 🚀 Como rodar

### Pré-requisitos
- AWS CLI configurado (`aws configure`)
- Terraform >= 1.5
- Python 3.10+

### 1. Instalar dependências

```bash
pip install -r requirements.txt
```

### 2. Testes locais (sem AWS, sem custo)

```bash
make test
```

### 3. Criar bucket de estado do Terraform

```bash
aws s3 mb s3://sla-tfstate-SEU-NOME --region us-east-1
# Atualize infra/main.tf com esse nome
```

### 4. Provisionar infraestrutura

```bash
make tf-init
make tf-plan  ENV=dev EMAIL=seu@email.com SLACK_URL=""
make tf-apply ENV=dev EMAIL=seu@email.com SLACK_URL=""
```

### 5. Deploy dos scripts

```bash
make deploy-scripts BUCKET=sla-platform-dev
make zip-lambda
```

### 6. Registrar tabela no Catalog (1x só)

No Athena Query Editor, execute `sql/queries.sql` — a seção `CREATE EXTERNAL TABLE`.

### 7. Executar o pipeline

```bash
aws glue start-job-run \
  --job-name sla-platform-pipeline-dev \
  --arguments '{"--EXECUTION_DATE":"2024-01-15","--SOURCE_SYSTEM":"all"}'
```

### 8. Sincronizar partições e consultar

```sql
-- No Athena, após a execução do Glue:
MSCK REPAIR TABLE sla_db_dev.silver_metrics;

-- Executar a query de consolidação (sql/queries.sql)
```

### 9. Destruir quando não estiver usando

```bash
make tf-destroy ENV=dev EMAIL=seu@email.com SLACK_URL=""
```

---

## 💰 Custo estimado (dev)

| Serviço | Custo |
|---|---|
| Glue Job (G.025X, 2 workers, 10 min) | ~$0.09/execução |
| S3 | ~$0.02/GB/mês |
| Athena | ~$0.00 (dados de exemplo < 1 MB) |
| SNS | $0.00 (free tier) |
| Lambda | $0.00 (free tier) |
| CloudWatch Metrics | ~$0.30/métrica/mês |
| **Total estimado** | **< $1/mês** |
