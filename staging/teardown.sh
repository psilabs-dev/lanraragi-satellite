#!/bin/bash

export MY_UID=$(id -u)
export MY_GID=$(id -g)

cd "$(dirname "$0")"
docker compose --profile lanraragi --profile satellite down --volumes
rm -rf contents
rm -rf satellite