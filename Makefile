.PHONY: test zip-modules zip-lambda deploy-scripts tf-init tf-plan tf-apply tf-destroy

test:
	pytest tests/ -v --cov=modules --cov-report=term-missing

zip-modules:
	zip -r modules.zip modules/
	aws s3 cp modules.zip s3://$(BUCKET)/scripts/modules.zip
	rm modules.zip

zip-lambda:
	cd lambda && zip lambda.zip handler.py
	@echo "lambda/lambda.zip criado"

deploy-scripts: zip-modules
	aws s3 cp jobs/sla_pipeline.py s3://$(BUCKET)/scripts/sla_pipeline.py
	aws s3 cp data/sample.jsonl    s3://$(BUCKET)/raw/event_date=2024-01-15/sample.jsonl
	@echo "Deploy concluído → s3://$(BUCKET)"

tf-init:
	cd infra && terraform init

tf-plan:
	cd infra && terraform plan \
	  -var="environment=$(ENV)" \
	  -var="alert_email=$(EMAIL)" \
	  -var="slack_webhook_url=$(SLACK_URL)"

tf-apply:
	cd infra && terraform apply \
	  -var="environment=$(ENV)" \
	  -var="alert_email=$(EMAIL)" \
	  -var="slack_webhook_url=$(SLACK_URL)"

tf-destroy:
	cd infra && terraform destroy \
	  -var="environment=$(ENV)" \
	  -var="alert_email=$(EMAIL)" \
	  -var="slack_webhook_url=$(SLACK_URL)"
