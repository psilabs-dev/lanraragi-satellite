# lanraragi-satellite

A Python library that provides an auxilliary microservice (satellite) for LANraragi, among other utilities that might be useful.

## Libraries/Contents
1. [Installation](#installation)
1. [Satellite Server](#satellite-server): multi-purpose, opinionated server
1. [LANraragi Python SDK](#lanraragi-python-sdk): includes an async LANraragi API client
1. [ManyCBZ](#manycbz): synthetic archive generation toolkit

## Installation
Requirements: Linux, Python and Docker. The server is intended to run only in a Docker container in production, but it can be developed locally as well.
```sh
pip install ".[dev]"
```

## Satellite Server
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

### Usage
Build the image:
```sh
docker build -t satellite --build-arg SATELLITE_GIT_COMMIT_HASH=$(git rev-parse HEAD) .
```
Run the image:
```sh
docker run -it --rm -p 127.0.0.1:8000:8000 satellite --host 0.0.0.0
```
> **Note**: this is intended to be accessible only by the host machine, as it is a *privileged* server.

Alternatively run the server locally from source for development, after building from source:
```sh
uvicorn satellite_server.app:app --host 0.0.0.0 --port 8000 --reload
```

#### Example Docker Compose
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

#### API Usage Examples
Example of calling the API to perform tasks via curl. Assume that API key is "satellite", host is localhost, and port is 8000.

Scan archives for corrupted images:
```sh
curl -X POST -H "Authorization: Bearer satellite" http://localhost:8000/api/archives/scan
```
Get archives that have been corrupted (corrupted archives have status 1):
```sh
curl -H "Authorization: Bearer satellite" http://localhost:8000/api/archives?status=1
```
Apply metadata plugin (pixivmetadata or nhplugin) on all untagged archives. Following is example with Pixiv.
```sh
curl -H "Authorization: Bearer satellite" http://localhost:8000/api/metadata/plugins/pixivmetadata
```
Upload archives from the folder.
```sh
curl -X POST -H "Authorization: Bearer satellite" http://localhost:8000/api/upload
```
If archives are folders (like from PixivUtil2), add a `?archive_is_dir=true` query parameter at the end.

### Configuration
Satellite configuration is environment variable-driven.

| key | description | default |
| - | - | - |
| `SATELLITE_API_KEY` | API key for the `satellite` server. This key will be registered in the database as a salt and hash, so the variable does not need to be set in the future. | satellite |
| `SATELLITE_HOME` | Home directory for the `satellite` server. The database is located in `$SATELLITE_HOME/db/db.sqlite`. | `$HOME/.satellite` |
| - | - | - |
| `LRR_HOST` | Abs. URL for LANraragi (e.g. "http://localhost:3000" or "https://lanraragi.server") | http://localhost:3000 |
| `LRR_API_KEY` | API key for the LANraragi server. | |
| `LRR_CONTENTS_DIR` | LRR server Archive directory. | |
| - | - | - |
| `METADATA_NHENTAI_ARCHIVIST_DB` | Path to [nhentai archivist](https://github.com/9-FS/nhentai_archivist)'s sqlite database. | |
| `METADATA_PIXIVUTIL2_DB` | Path to [PixivUtil2](https://github.com/Nandaka/PixivUtil2/tree/master) sqlite database. | |
| - | - | - |
| `UPLOAD_DIR` | Directory to upload from. | |

### Development
Requirements: Python, Docker

### Architecture

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

## LANraragi Python SDK
A basic Python SDK for LANraragi. Includes miscellaneous utilities, such as calculating upload checksum for a file, computing archive ID, and calculating and validating an archive's magic number.

### Make Asynchronous API calls
Usage of LRRClient: an asynchronous API client for LANraragi:
```python
import asyncio
from lanraragi import LRRClient

client = LRRClient(lrr_host="http://localhost:3000", lrr_api_key="lanraragi")

async def main():
    response = await client.get_server_info()
    print(response)

asyncio.run(main())
```
See the implementation for more details.

## ManyCBZ

Synthetic archive generation tool, intended mainly for testing purposes and making bugs involving large LRR repositories more reproducible.

> ManyCBZ uses the [Roboto Regular](src/manycbz/resources/fonts/Roboto/Roboto-Regular.ttf) font to create text (see [LICENSE.txt](src/manycbz/resources/fonts/Roboto/LICENSE.txt)).

### Usage
Create a test page:
```python
from manycbz.page import Page
page = Page(1280, 1780)
page.whiten_panel()
page.add_panel_boundary()
page.write_text('test text')
page.save("test.png")
```
We can also produce a corrupted image:
```python
from manycbz.page import Page
page = Page(1280, 1780, first_n_bytes=1000)
page.save("test-corrupted-image.png")
```

Create a test comic:
```python
from manycbz.comic import create_comic
create_comic("test.cbz", "test-comic", 1280, 1780, 55)
```
By default, `create_comic` creates zip files, but it can be used to create tar.gz files or folders instead:
```python
from manycbz.comic import create_comic
from manycbz.enums import ArchivalStrategyEnum

create_comic("test.tar.gz", "test-comic", 1280, 1780, 55, archival_strategy=ArchivalStrategyEnum.TAR_GZ)
create_comic("test-comic", "test-comic", 1280, 1780, 55, archival_strategy=ArchivalStrategyEnum.NO_ARCHIVE)
```

**Notes on testing**: haven't found a good way to test image creation, this appears to be OS dependent.
