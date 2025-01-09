import abc
from pathlib import Path
import re
from typing import List, Union

import aiosqlite

from satellite_server.models import ArchiveMetadata


class MetadataService(abc.ABC):
    """
    Metadata interface for a downloader or metadata server.
    """

    @staticmethod
    @abc.abstractmethod
    def get_id_from_title(file_path: Union[str, Path]) -> str:
        ...

    @abc.abstractmethod
    async def get_metadata_from_id(self, *args, **kwargs) -> ArchiveMetadata:
        ...

class NhentaiArchivistMetadataService(MetadataService):
    """
    Metadata client for [Nhentai Archivist](https://github.com/9-FS/nhentai_archivist.git)
    """

    def __init__(self, db: Path):
        if not db:
            raise KeyError("Nhentai Archivist db not configured!")
        if not db.exists():
            raise FileNotFoundError(f"Nhentai Archivist db not found: {db}")
        self.db = db

    @staticmethod
    def get_id_from_title(file_path: str | Path) -> str:
        if isinstance(file_path, str):
            file_path = Path(file_path)
        if isinstance(file_path, Path):
            archive_id = file_path.name.split()[0]
            return archive_id
        else:
            raise TypeError(f"Unsupported input: {type(file_path)}") 

    async def get_metadata_from_id(self, nhentai_id: str) -> ArchiveMetadata:
        """
        Get metadata from the nhentai_archivist database, given the nhentai ID.
        """
        metadata = ArchiveMetadata()
        async with aiosqlite.connect(self.db) as conn, conn.cursor() as cursor:
            titles = await (await cursor.execute("SELECT title_pretty FROM Hentai WHERE id=?", (nhentai_id,))).fetchone()
            title = titles[0] if titles else None
            groups = await (await cursor.execute('''
                WITH groups AS (SELECT * FROM tag WHERE type = ?)
                SELECT groups.name FROM hentai_tag JOIN groups ON hentai_tag.tag_id = groups.id
                WHERE hentai_tag.hentai_id = ?
            ''', ('group', nhentai_id))).fetchall()
            artists = await (await cursor.execute('''
                WITH artists AS (SELECT * FROM tag WHERE type = ?)
                SELECT artists.name FROM hentai_tag JOIN artists ON hentai_tag.tag_id = artists.id
                WHERE hentai_tag.hentai_id = ?
            ''', ('artist', nhentai_id))).fetchall()
            tags = await (await cursor.execute('''
                WITH true_tags AS (SELECT * FROM tag WHERE type = ?)
                SELECT true_tags.name FROM hentai_tag JOIN true_tags ON hentai_tag.tag_id = true_tags.id
                WHERE hentai_tag.hentai_id = ?
            ''', ('tag', nhentai_id))).fetchall()
            characters = await (await cursor.execute('''
                WITH characters AS (SELECT * FROM tag WHERE type = ?)
                SELECT characters.name FROM hentai_tag JOIN characters ON hentai_tag.tag_id = characters.id
                WHERE hentai_tag.hentai_id = ?
            ''', ('character', nhentai_id))).fetchall()
            parodies = await (await cursor.execute('''
                WITH parodies AS (SELECT * FROM tag WHERE type = ?)
                SELECT parodies.name FROM hentai_tag JOIN parodies ON hentai_tag.tag_id = parodies.id
                WHERE hentai_tag.hentai_id = ?
            ''', ('parody', nhentai_id))).fetchall()
            languages = await (await cursor.execute('''
                WITH languages AS (SELECT * FROM tag WHERE type = ?)
                SELECT languages.name FROM hentai_tag JOIN languages ON hentai_tag.tag_id = languages.id
                WHERE hentai_tag.hentai_id = ?
            ''', ('language', nhentai_id))).fetchall()
            categories = await (await cursor.execute('''
                WITH categories AS (SELECT * FROM tag WHERE type = ?)
                SELECT categories.name FROM hentai_tag JOIN categories ON hentai_tag.tag_id = categories.id
                WHERE hentai_tag.hentai_id = ?
            ''', ('category', nhentai_id))).fetchall()

        tag_list = []
        for tag in tags:
            tag_list.append(tag[0])
        for character in characters:
            tag_list.append(f"character:{character[0]}")
        for parody in parodies:
            tag_list.append(f"parody:{parody[0]}")
        for language in languages:
            tag_list.append(f"language:{language[0]}")
        for category in categories:
            tag_list.append(f"category:{category[0]}")
        for artist in artists:
            tag_list.append(f"artist:{artist[0]}")
        for group in groups:
            tag_list.append(f"group:{group[0]}")
        
        tag_list.append(f"source:nhentai.net/g/{nhentai_id}")
        # validate tag list
        for item in tag_list:
            assert ',' not in item, f'Item {item} contains comma.'

        final_tag_string = ",".join(tag_list)
        metadata.title = title
        metadata.tags = final_tag_string
        return metadata

class PixivUtil2MetadataService(MetadataService):
    """
    Metadata client for [PixivUtil2](https://github.com/Nandaka/PixivUtil2.git)
    """
    
    def __init__(self, db: Path, allowed_translation_types: List[str]=None) -> None:
        if not db:
            raise KeyError("PixivUtil2 db not configured!")
        if not db.exists():
            raise FileNotFoundError(f"PixivUtil2 db not found: {db}")
        self.db = db
        if not allowed_translation_types:
            allowed_translation_types = ["en"]
        self.allowed_translation_types = allowed_translation_types

    @staticmethod
    def get_id_from_title(file_path: str | Path) -> str:
        """
        Get ID from a PixivUtil2 file, according to the LANraragi Pixiv metadata ID extraction:

        Examples: "{Id} Title" or "pixiv_{Id} Title".
        """
        if isinstance(file_path, str):
            file_path = Path(file_path)
        if not isinstance(file_path, Path):
            raise TypeError(f"Unsupported file type: {type(file_path)}.")
        file_name = file_path.name
        if file_name.startswith("pixiv_"):
            file_name = file_name[6:] # remove "pixiv_"
        
        # try getting the filename.
        match = re.match(r"\{(\d+)\}", file_name)
        pixiv_id = match.group(1) if match else ""
        return pixiv_id

    async def get_metadata_from_id(self, pixiv_id: int) -> ArchiveMetadata:
        """
        Get metadata from PixivUtil2 database, given the Pixiv illust ID.
        """
        metadata = ArchiveMetadata()
        async with aiosqlite.connect(self.db) as conn, conn.cursor() as cursor:
            titles = await (await cursor.execute("SELECT title FROM pixiv_master_image WHERE image_id = ?", (pixiv_id,))).fetchone()
            title = titles[0] if titles else None

            # get pixiv artist
            artists = await (await cursor.execute('''
                                                  SELECT pixiv_master_member.member_id, pixiv_master_member.name 
                                                  FROM pixiv_master_member 
                                                  JOIN pixiv_master_image ON pixiv_master_member.member_id = pixiv_master_image.member_id
                                                  WHERE pixiv_master_image.image_id = ?
            ''', (pixiv_id,))).fetchall()

            # get tags (and tag translations)
            original_tags = await (await cursor.execute('SELECT tag_id FROM pixiv_image_to_tag WHERE image_id = ?', (pixiv_id,))).fetchall()
            all_tags = []
            for original_tag in original_tags:
                original_tag_id = original_tag[0]
                all_tags.append(original_tag_id)
                translations = await (await cursor.execute('SELECT translation_type, translation FROM pixiv_tag_translation WHERE tag_id = ?', (original_tag_id,))).fetchall()
                for translation in translations:
                    translation_type = translation[0]
                    if translation_type in self.allowed_translation_types:
                        # handle tag translations.
                        # some translations contain commas, which need to be either ignored or processed.
                        translated_tag_id = translation[1].replace(',', '')
                        all_tags.append(translated_tag_id)

            # get summary
            summary = await (await cursor.execute('SELECT caption from pixiv_master_image WHERE image_id = ?', (pixiv_id,))).fetchall()

            # assemble tags
            tag_list = all_tags # start with all tags.
            for artist in artists:
                tag_list.append(f"artist:{artist[1]}")
                tag_list.append(f"pixiv_user_id:{artist[0]}")
            tag_list.append(f"source:https://pixiv.net/artworks/{pixiv_id}")
            # validate tag list
            for item in tag_list:
                assert ',' not in item, f'Item {item} contains comma.'

        final_tag_string = ",".join(tag_list)
        metadata.title = title
        metadata.tags = final_tag_string
        if summary:
            metadata.summary = summary
        return metadata
