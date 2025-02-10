#!/bin/bash

export MY_UID=$(id -u)
export MY_GID=$(id -g)

cd "$(dirname "$0")"
mkdir -p contents
mkdir -p satellite
docker compose --profile lanraragi --profile satellite up --remove-orphans --build -d -y

# add "lanraragi" API key.
docker exec -it staging-redis bash -c "redis-cli <<EOF
SELECT 2
HSET LRR_CONFIG apikey lanraragi
EOF"

# enable nofun mode.
docker exec -it staging-redis bash -c "redis-cli <<EOF
SELECT 2
HSET LRR_CONFIG nofunmode 1
EOF"

# make content folder uploadable.
docker exec -it staging-lanraragi /bin/sh -c "chown -R koyomi: content"
