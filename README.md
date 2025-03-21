# lanraragi-satellite

A Python library that provides an auxilliary microservice (satellite) for LANraragi, among other utilities that might be useful. Features are developed on an ad hoc basis, rather than to conform to best practices.

Currently many of these libraries are lumped together for convenience, but may be split into individual components if they prove useful to others.

## Libraries/Contents
1. [Installation](#installation)
1. [Satellite Server](#satellite-server): multi-purpose, opinionated server for auxilliary tasks
1. [Satellite NHDD](#satellite-nhdd): nHentai DeDuplication server
1. [LANraragi Python SDK](#lanraragi-python-sdk): Python SDK for LANraragi with async API client
1. [ManyCBZ (in testing)](#manycbz): mock archive and metadata generation toolkit

## Installation

General installation instructions.

### Requirements
Requirements depend on the library being used, with Satellite Server intended for containerized production deployment. Generally, the following are required:

- A recent version of Python,
- Docker, if you are using Satellite Server, or want to spin up a test LRR server.

Install the library from source:
```sh
pip install .
```

### Development
Install developer tools:
```sh
pip install ".[dev]"
```
Run tests:
```sh
export CI=true
pytest tests
```

### LANraragi Staging Environment
Set up a staging environment.
```sh
./staging/setup.sh
```
This will create a LRR server on port 3000, accompanied by a Redis server and a satellite server on port 8001. Additionally, this will inject "lanraragi" to Redis as the server API key, as well as provide a writable contents directory for Koyomi.

Clean up everything at the end:
```sh
./staging/teardown.sh
```

### LANraragi Integration Tests
Integration tests are located in the `./integration-tests` directory. A Docker engine is required. Integration tests are run with Pytest sessions. A LANraragi and Redis container will be spun up and torn down via the Python Docker client on each session, ensuring isolated testing environments.

Start integration tests with the `difegue/lanraragi` image:
```sh
export CI=true
pytest integration-tests
```
Start integration tests with another image:
```sh
pytest integration-tests --image custom-lrr-image
```

Start integration tests that build and deploy a local LANraragi git repo:
```sh
export CI=true
pytest integration-tests --build /path/to/lanraragi/project
```

**Note**: Proper configuration of Docker and its availability to Python clients is expected to avoid exceptions during test-time. Troubleshooting such exceptions is beyond the scope of the project.

## Satellite Server
Satellite is an opinionated auxilliary microservice* for [LANraragi](https://github.com/Difegue/LANraragi) to perform various tasks, such as:

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
pip install ".[satellite_server]"
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

## Satellite NHDD
An nHentai doujin deduplication library wrapped with server functionality. Uses Pytorch [img2vec](https://github.com/psilabs-dev/img2vec) with the resnet 18 model for image similarity in conjunction with a Postgres vector database.

Install:
```
pip install ".[nhdd,server]"
```

### Sequence Deduplication Theory
Deduplication is the task of identifying and removing duplicates. To identify duplicates, we need an algorithm to group items into buckets. To remove duplicates, we need an algorithm to impose an order on items within every bucket.

(*Lesser* and *equal* duplicates) An archive is a finite sequence of images. Every image has a vector representation by an image embedding model. Then, archives are representations of sequences of vectors. We can define one archive being a "lesser duplicate" of another if its representation is a proper subsequence of the other, and "equal duplicate" if both representations are exactly equal. However, this condition is too strong: it's rare to find two images which are *exactly* equal. So we change this condition to mean "similar to some degree". This similarity is represented by cosine similarity and is good enough for practical purposes.

Additionally, two archives are "not comparable" if neither is a subsequence of the other. "Not comparable" also means they lie in separate graphs. Archives which are not comparable with any other archive are "unique". Note the obvious result that equal-duplicates are not proper subsequences of each other.

The relation "is a lesser duplicate of" imposes a partial order "<" on the set of equivalence classes of equal-duplicate archives. It guarantees that any archive which is not maximal is a lesser duplicate. It also states that remaining archives, which belong in maximal vertices, are either unique or have equal duplicates. 

Metadata scoring: Equal duplicates cannot be removed by analyzing image content: to remove them, we may impose a finer ordering via metadata sorting or scoring.

## LANraragi Python SDK
A basic Python SDK for LANraragi. Includes miscellaneous utilities, such as calculating upload checksum for a file, computing archive ID, and calculating and validating an archive's magic number.

### Make Asynchronous API calls
Usage of LRRClient: an asynchronous API client for LANraragi:
```python
import asyncio
from lanraragi.client import LRRClient

async def main():
    async with LRRClient(lrr_host="http://localhost:3000", lrr_api_key="lanraragi"):
        response = await client.get_server_info()
        print(response)

asyncio.run(main())
```
See the implementation for more details.

## ManyCBZ

Mock archive and metadata generation tool, intended mainly for testing purposes and making bugs involving large LRR repositories more accessible and reproducible. No more bug reports with censored screenshots, or worrying about TOS when testing on cloud instances!

> ManyCBZ uses the [Roboto Regular](src/manycbz/resources/fonts/Roboto/Roboto-Regular.ttf) font under the [Apache 2.0 License](src/manycbz/resources/fonts/Roboto/LICENSE.txt).

### Create Archives
Create a test page with resolution 1280x1780 and text "test text", and save it at "./test.png":
```python
from pathlib import Path
from manycbz.models import CreatePageRequest
from manycbz.service.page import create_page, save_page_to_dir

request = CreatePageRequest(1280, 1780, 'test.png', text='test text')
page = create_page(request).page
save_page_to_dir(page, Path('.'))
```
We can also produce a corrupted image, which occurs when an image download is interrupted:
```python
from pathlib import Path
from manycbz.models import CreatePageRequest
from manycbz.service.page import create_page, save_page_to_dir

request = CreatePageRequest(1280, 1780, 'test.png', text='test text', first_n_bytes=1000)
page = create_page(request).page
save_page_to_dir(page, Path('.'))
```

Create a 55-page ZIP archive called "test.cbz" with text "test-comic-pg-$PAGE_NUMBER, where the page dimension is 1280x1780:
```python
from manycbz.service.archive import create_comic
create_comic("test.cbz", "test-comic", 1280, 1780, 55)
```
By default, `create_comic` creates zip files, but it can be used to create tar.gz files or folders instead:
```python
from manycbz.service.archive import create_comic
from manycbz.enums import ArchivalStrategyEnum

create_comic("test.tar.gz", "test-comic", 1280, 1780, 55, archival_strategy=ArchivalStrategyEnum.TAR_GZ)
create_comic("test-comic", "test-comic", 1280, 1780, 55, archival_strategy=ArchivalStrategyEnum.NO_ARCHIVE)
```
For greater control use `write_archive_to_disk`, which `create_comic` is based on.

**Notes on testing**: haven't found a good way to test image creation, this appears to be OS dependent.

### Create Tags
In the context of metadata mocking, a key assumption on tag assignment for archives is independent and identical distribution (IID). This is mainly to simplify mocking implementations. 

> It should be emphasized that IID does **not** hold in the real world, as many tags are highly correlated with each other. Nevertheless, IID is useful and often sufficient to generate mock test data where the distribution of tags across archives should resemble the real-world distribution.

Thanks to this assumption, we can follow that any particular tag has a fixed probability of being assigned to any given archive, rather than a probability that is associated with external factors, such as the presence of other tags, etc. The result is that we can assign tags to an archive by simply providing tag names and assignment probabilities:

```python
from manycbz.service.metadata import TagGenerator, get_tag_assignments

tg1 = TagGenerator('1', 1.0) # tag "1" with probability 1 of being assigned
tg2 = TagGenerator('2', 1.0) # tag "2" with probability 1 of being assigned
tg3 = TagGenerator('3', 0.0) # tag "3" with probability 0 of being assigned

print(get_tag_assignments([tg1, tg2, tg3]))
# ["1", "2"].
```

Then this can be automated to scale to, for example, create 10k tags via some probability mass function.
```python
import numpy as np
from manycbz.service.metadata import create_tag_generators, get_tag_assignments

# this is your probability mass function.
def pmf(x):
    return 1/10_000

generator = np.random.default_rng(42)
tag_generators = create_tag_generators(10_000, pmf)
tags = get_tag_assignments(tag_generators, generator=generator)
print(tags)
# ['tag-7491']
```
