#!/bin/bash

export MY_UID=$(id -u)
export MY_GID=$(id -g)
mkdir -p integration/contents
mkdir -p integration/satellite
docker compose -f integration/docker-compose.yml --profile lanraragi --profile satellite up --remove-orphans --build -d

# add "lanraragi" API key.
docker exec -it redis bash -c "redis-cli <<EOF
SELECT 2
HSET LRR_CONFIG apikey lanraragi
EOF"

# enable nofun mode.
docker exec -it redis bash -c "redis-cli <<EOF
SELECT 2
HSET LRR_CONFIG nofunmode 1
EOF"

# make content folder uploadable.
docker exec -it lanraragi /bin/sh -c "chown -R koyomi: content"
