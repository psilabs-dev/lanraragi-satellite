FROM python:3.12

ARG SATELLITE_GIT_COMMIT_HASH
ENV SATELLITE_GIT_COMMIT_HASH=${SATELLITE_GIT_COMMIT_HASH}

ARG OPTIONAL_DEPENDENCIES=".[server]"

WORKDIR /workdir
COPY requirements.txt   /workdir/requirements.txt

# create a modifiable /.cache directory for pytorch models, otherwise
# you will encounter permission denied errors when running NHDD.
RUN pip3 install -r requirements.txt && \
    mkdir -m 777 /.cache && mkdir -m 777 /.satellite

COPY src                    /workdir/src
COPY pyproject.toml         /workdir/pyproject.toml

RUN pip3 install "${OPTIONAL_DEPENDENCIES}" && \
    rm -rf requirements.txt src pyproject.toml

HEALTHCHECK CMD [ "curl", "127.0.0.1:8000/api/healthcheck" ]
ENTRYPOINT [ "uvicorn", "satellite.server.app:app" ]
