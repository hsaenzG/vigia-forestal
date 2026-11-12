# Vigía Forestal — comandos de la demo
# Uso: make deploy AWS_PROFILE=<tu-perfil>
AWS_PROFILE ?= default
AWS_REGION  ?= us-east-2
STACK       ?= vigia-forestal
PY          := .venv/bin/python
export AWS_PROFILE AWS_REGION

.PHONY: setup local build deploy site domain ingest outputs logs destroy

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

site: ## publica el frontend en AWS Amplify Hosting (deploy manual con zip)
	@APP=$(call out,WebAppId); API=$(call out,ApiUrl); DATA=datos; \
	rm -rf .build-web && mkdir -p .build-web && cp -R frontend/ .build-web/ && rm -f .build-web/.DS_Store && \
	printf 'window.VIGIA_CONFIG = {"apiUrl": "%s", "dataUrl": "%s", "mode": "aws"};\n' "$$API" "$$DATA" > .build-web/config.js && \
	(cd .build-web && zip -qr ../web.zip .) && \
	JOB=$$(aws amplify create-deployment --app-id "$$APP" --branch-name main --region $(AWS_REGION) --profile $(AWS_PROFILE) --output json) && \
	JOB_ID=$$(echo "$$JOB" | python3 -c "import json,sys;print(json.load(sys.stdin)['jobId'])") && \
	URL=$$(echo "$$JOB" | python3 -c "import json,sys;print(json.load(sys.stdin)['zipUploadUrl'])") && \
	curl -sf -T web.zip "$$URL" && \
	aws amplify start-deployment --app-id "$$APP" --branch-name main --job-id "$$JOB_ID" --region $(AWS_REGION) --profile $(AWS_PROFILE) --query "jobSummary.status" --output text && \
	rm -rf .build-web web.zip
	@echo "Sitio: $(call out,SiteUrl)  ·  dominio propio: https://$(SUBDOMAIN).$(DOMAIN)"

DOMAIN    ?= apps.vigiaforestal.hazelsaenz.tech
SUBDOMAIN ?= www
domain: ## asocia el dominio propio en Amplify y muestra los registros DNS a crear
	-aws amplify create-domain-association --app-id $(call out,WebAppId) --domain-name $(DOMAIN) \
		--sub-domain-settings prefix=$(SUBDOMAIN),branchName=main --region $(AWS_REGION) --profile $(AWS_PROFILE) \
		--query "domainAssociation.domainStatus" --output text
	aws amplify get-domain-association --app-id $(call out,WebAppId) --domain-name $(DOMAIN) --region $(AWS_REGION) \
		--profile $(AWS_PROFILE) --query "domainAssociation.{estado:domainStatus,certificado:certificateVerificationDNSRecord,subdominios:subDomains[].dnsRecord}"

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
