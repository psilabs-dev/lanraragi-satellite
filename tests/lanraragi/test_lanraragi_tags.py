from lanraragi.utils import get_source_from_tags


def test_get_source():
    tags = "date_added:1714727657,test,pixiv_user_id:11,source:https://pixiv.net/artworks/114245433"
    expected_source = "https://pixiv.net/artworks/114245433"
    actual_source = get_source_from_tags(tags)
    assert actual_source == expected_source

def test_get_source_none():
    tags = "date_added:1714727657,test,pixiv_user_id:11"
    expected_source = None
    actual_source = get_source_from_tags(tags)
    assert actual_source == expected_source
