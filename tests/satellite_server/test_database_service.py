

from satellite_server.service.metadata import NhentaiArchivistMetadataService, PixivUtil2MetadataService


def test_nhentai_archivist_id_extraction():
    test_file = "123456 test title.cbz"
    expected_nhentai_id = "123456"
    assert expected_nhentai_id == NhentaiArchivistMetadataService.get_id_from_title(test_file)

def test_pixiv_id_extraction():
    test_file = "{11342} test title"
    expected_pixiv_id = "11342"
    assert expected_pixiv_id == PixivUtil2MetadataService.get_id_from_title(test_file)

def test_pixiv_id_extraction_2():
    test_file = "pixiv_{11342} test title"
    expected_pixiv_id = "11342"
    assert expected_pixiv_id == PixivUtil2MetadataService.get_id_from_title(test_file)
