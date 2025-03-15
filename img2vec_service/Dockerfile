FROM python:3.12
ARG MODEL_NAME

COPY requirements.txt       /app/requirements.txt
RUN apt-get update && \
    pip install -U pip && \
    pip install -r /app/requirements.txt && \
    mkdir -m 777 /.cache

COPY img2vec_service        /app/img2vec_service
COPY README.md              /app/README.md
COPY pyproject.toml         /app/pyproject.toml

RUN cd /app && \
    pip install . && \
    cd / && rm -rf /app && \
    python -m img2vec_service.serve

ENTRYPOINT [ "uvicorn", "img2vec_service.serve:app" ]
HEALTHCHECK CMD [ "curl", "127.0.0.1:8000/api/healthcheck" ]
