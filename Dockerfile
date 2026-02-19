FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt

# By default, force CPU-only PyTorch wheels to avoid huge CUDA dependency downloads.
# Override at build time if you need GPU wheels, e.g.:
#   docker build --build-arg PYTORCH_WHL_INDEX=https://download.pytorch.org/whl/cu124 .
ARG PYTORCH_WHL_INDEX=https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir \
    --index-url ${PYTORCH_WHL_INDEX} \
    --extra-index-url https://pypi.org/simple \
    -r requirements.txt

COPY ./src /app/src

# Optional: pre-download the embedding model at build time (off by default).
ARG PRELOAD_EMBEDDING_MODEL=false
RUN if [ "${PRELOAD_EMBEDDING_MODEL}" = "true" ]; then \
      python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"; \
    fi

WORKDIR /app/src
EXPOSE ${PORT:-8000}

CMD /bin/sh -c 'uvicorn main:api --host 0.0.0.0 --port ${PORT:-8000}'
