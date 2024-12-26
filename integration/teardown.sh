#!/bin/bash

export MY_UID=$(id -u)
export MY_GID=$(id -g)
docker compose -f integration/docker-compose.yml --profile lanraragi down --volumes
rm -rf integration/contents
