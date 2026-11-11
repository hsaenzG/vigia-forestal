# Vigía Forestal — comandos de la demo
# Uso: make deploy AWS_PROFILE=<tu-perfil>
AWS_PROFILE ?= default
AWS_REGION  ?= us-east-2
STACK       ?= vigia-forestal
PY          := .venv/bin/python
export AWS_PROFILE AWS_REGION

.PHONY: setup local build deploy site ingest analyze-watch outputs logs destroy

setup: ## entorno local (Python 3.13)
	uv venv -q -p 3.13 .venv
	uv pip install -q --python $(PY) -r local/requirements.txt

local: ## servidor local en http://localhost:8000 (mismo código que las Lambdas)
	$(PY) local/dev_server.py

build:
	sam build

deploy: build ## despliega toda la infraestructura + sitio + primera ingesta
	sam deploy --stack-name $(STACK) --region $(AWS_REGION) --profile $(AWS_PROFILE)
	$(MAKE) site
	$(MAKE) ingest

out = $(shell aws cloudformation describe-stacks --stack-name $(STACK) --region $(AWS_REGION) --profile $(AWS_PROFILE) --query "Stacks[0].Outputs[?OutputKey=='$(1)'].OutputValue" --output text)

site: ## sube el frontend a S3 y limpia la caché de CloudFront
	@BUCKET=$(call out,SiteBucketName); API=$(call out,ApiUrl); DIST=$(call out,DistributionId); \
	aws s3 sync frontend "s3://$$BUCKET" --exclude config.js --exclude ".DS_Store" && \
	printf 'window.VIGIA_CONFIG = {"apiUrl": "%s", "dataUrl": "data", "mode": "aws"};\n' "$$API" | \
		aws s3 cp - "s3://$$BUCKET/config.js" --content-type application/javascript --cache-control no-store && \
	aws cloudfront create-invalidation --distribution-id "$$DIST" --paths "/*" --query Invalidation.Id --output text
	@echo "Sitio: $(call out,SiteUrl)"

ingest: ## fuerza una ingesta ahora (normalmente corre sola cada semana)
	aws lambda invoke --function-name $(call out,IngestFunctionName) --payload '{"force": true}' \
		--cli-binary-format raw-in-base64-out --cli-read-timeout 200 /dev/stdout

outputs:
	aws cloudformation describe-stacks --stack-name $(STACK) --query "Stacks[0].Outputs" --output table

logs: ## logs del agente en vivo
	sam logs --stack-name $(STACK) --name AnalystFunction --tail

destroy: ## borra todo (vacía el bucket primero)
	aws s3 rm "s3://$(call out,SiteBucketName)" --recursive
	sam delete --stack-name $(STACK) --no-prompts
