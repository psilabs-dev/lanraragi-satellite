import importlib.resources

def get_roberta_regular_font():
    return importlib.resources.files("manycbz.resources.fonts.Roboto") / "Roboto-Regular.ttf"