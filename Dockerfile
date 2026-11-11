# Baseline development environment, not an all-dependencies production image.
# Pin this tag to a tested image digest before deployment.
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    git poppler-utils tesseract-ocr && rm -rf /var/lib/apt/lists/*
WORKDIR /workspace
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir -e .
ENTRYPOINT ["certpassly"]
CMD ["doctor"]
