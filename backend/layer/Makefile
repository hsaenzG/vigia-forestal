# sam build invoca este target. Descarga wheels Linux/arm64 aunque compiles en macOS.
build-StrandsLayer:
	uv pip install -r requirements.txt \
		--target "$(ARTIFACTS_DIR)/python" \
		--python-platform aarch64-manylinux2014 \
		--python-version 3.13 \
		--only-binary :all:
