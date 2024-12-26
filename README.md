# lanraragi-satellite

Satellite is an opinionated auxilliary microservice for [LANraragi](https://github.com/Difegue/LANraragi) to perform various tasks, such as:

- **Archive Processing**: Scan for, and move or remove, corrupted (incomplete) Archives from the LRR contents folder.
    > RW access to the contents folder is required.
- **Updating Metadata from Downloader**: Downloaders such as PixivUtil2 and nhentai_archivist also save metadata from their corresponding sources. This metadata will be applied to the respective archives in the server.
    > API access and R access to the downloader's metadata is required.
- **Updating Metadata by invoking the plugin**: Invokes LANraragi's metadata API remotely on untagged (and previously tagged) archives. Useful when you want a browser-free way to update your archives.
    > API access is required.
- **Upload Archives**: Package and upload archives from a folder to the server.
    > API access and R access to the downloader's database is required (sometimes W is required for sqlite databases).

This program is intended to run as a containerized web server, with cron jobs calling its APIs to perform (potentially very expensive) background tasks periodically.

## Usage
Build the image:
```sh
docker build -t satellite .
```
Run the image:
```sh
docker run -it --rm -p 127.0.0.1:8000:8000 satellite --host 0.0.0.0
```
> **Note**: this is intended to be accessible only by the host machine, as it is a *privileged* server.

Alternatively run the server locally from source for development:
```sh
uvicorn satellite.app:app --host 0.0.0.0 --port 8000 --reload
```

### Example Docker Compose
```yaml
services:

  redis:
    image: redis:7.2
    container_name: redis

  lanraragi:
    image: difegue/lanraragi
    container_name: lanraragi
    depends_on:
      - redis
    environment:
      - "LRR_REDIS_ADDRESS=redis:6379"
    volumes:
      - /path/to/db:/home/koyomi/lanraragi/database
      - /path/to/content:/home/koyomi/lanraragi/content:ro

  satellite:
    build: .
    command: [ "--host", "0.0.0.0" ]
    container_name: satellite
    depends_on:
      - lanraragi
    environment:
      - SATELLITE_API_KEY=satellite
      - SATELLITE_HOME=/satellite
      - LRR_HOST=http://lanraragi:3000
      - LRR_API_KEY=lanraragi
      - LRR_CONTENTS_DIR=/home/koyomi/lanraragi/content
    volumes:
      - /path/to/content:/home/koyomi/lanraragi/content:rw
    ports:
      - 127.0.0.1:8000:8000
```

## Configuration
Satellite configuration is environment variable-driven.

| key | description | default |
| - | - | - |
| `SATELLITE_API_KEY` | API key for the `satellite` server. | satellite |
| `SATELLITE_HOME` | Home directory for the `satellite` server. The database is located in `$SATELLITE_HOME/db/db.sqlite`. | `$HOME/.satellite` |
| - | - | - |
| `LRR_HOST` | Abs. URL for LANraragi (e.g. "http://localhost:3000" or "https://lanraragi.server") | http://localhost:3000 |
| `LRR_API_KEY` | API key for the LANraragi server. This key will be registered in the database as a salt and hash, so the variable does not need to be set in the future. | |
| `LRR_CONTENTS_DIR` | LRR server Archive directory. | |
| - | - | - |
| `METADATA_NHENTAI_ARCHIVIST_DB` | Path to [nhentai archivist](https://github.com/9-FS/nhentai_archivist)'s sqlite database. | |
| `METADATA_PIXIVUTIL2_DB` | Path to [PixivUtil2](https://github.com/Nandaka/PixivUtil2/tree/master) sqlite database. | |
| - | - | - |
| `UPLOAD_DIR` | Directory to upload from. | |

## Development
Requirements: Python, Docker

## Architecture

Although this can be run on the host with Python, this is a *Docker server-first* repository for the following reasons:
- be able to run the tasks periodically using cron
- easy to view logs ([Dozzle](https://dozzle.dev))
- benefits of being a container (isolation, control, convenience)
- integration with my existing Docker homeserver stack
- not enough free time

**No multiple choice**: Configuration will be implemented only with environment variables. Environment variables are easily configurable in Docker with compose. 

No accommodations shall be made for choice: the user has only **one** way to do things. Therefore, no (or minimal) configuration via alternative means, e.g. command line or configuration files. As a consequence, Archive uploads will not contain metadata, as this role is already supplied.

**Long running task resilience**: Uploading Archives and identifying corrupted files are expensive and long-running tasks. FastAPI's Background tasks with sqlite caching will achieve this.

**Simplicity**: The more things to do/consider, the worse my code gets. No more celery/rabbitmq.

Bind mounts are the choice of mounting any host contents into the server.

`satellite` is a FastAPI web server. It connects to LANraragi and uploads files asynchronously using aiohttp, and to database using aiosqlite.
