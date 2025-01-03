FROM python:3.11

ARG SATELLITE_GIT_COMMIT_HASH
ENV SATELLITE_GIT_COMMIT_HASH=${SATELLITE_GIT_COMMIT_HASH}

WORKDIR /workdir
COPY requirements.txt   /workdir/requirements.txt
RUN pip3 install -r requirements.txt

COPY satellite          /workdir/satellite
COPY pyproject.toml     /workdir/pyproject.toml

RUN pip3 install .

HEALTHCHECK CMD [ "curl", "127.0.0.1:8000/api/healthcheck" ]
ENTRYPOINT [ "uvicorn", "satellite.app:app" ]
