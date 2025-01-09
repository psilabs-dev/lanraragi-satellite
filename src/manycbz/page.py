import importlib.resources
import io
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from typing import Tuple, Union

def get_roberta_regular_font():
    return importlib.resources.files("manycbz.resources.fonts.Roboto") / "Roboto-Regular.ttf"

class Page:

    def __init__(
            self, width: int, height: int, 
            background_color: Union[str, Tuple[int, int, int]]=None,
            first_n_bytes: int=None, image_format: str='PNG'
    ):
        """
        Creates a page.

        first_n_bytes: when saving, save only the first n bytes. Used for creating corrupted images.
        """
        if not background_color:
            background_color = (200, 200, 200) # light gray background
        margin = int(min(width, height) * 0.05)

        self.width = width
        self.height = height
        self.left_boundary = margin
        self.right_boundary = width - margin
        self.upper_boundary = margin
        self.lower_boundary = height - margin
        self.margin = margin
        self.font_size = int(margin * 0.7)
        self.image = Image.new("RGBA", (self.width, self.height), background_color)
        self.first_n_bytes = first_n_bytes
        self.image_format = image_format

    def add_panel_boundary(self):
        """
        Draw panel boundaries that are the specified margin away from the border.
        """
        draw = ImageDraw.Draw(self.image)
        draw.line([(self.left_boundary, self.upper_boundary), (self.left_boundary, self.lower_boundary)], fill='black', width=1)
        draw.line([(self.left_boundary, self.upper_boundary), (self.right_boundary, self.upper_boundary)], fill='black', width=1)
        draw.line([(self.right_boundary, self.upper_boundary), (self.right_boundary, self.lower_boundary)], fill='black', width=1)
        draw.line([(self.left_boundary, self.lower_boundary), (self.right_boundary, self.lower_boundary)], fill='black', width=1)

    def whiten_panel(self):
        """
        Make panel white according to boundaries.
        """
        draw = ImageDraw.Draw(self.image)
        draw.polygon([
            (self.left_boundary, self.upper_boundary), (self.right_boundary, self.upper_boundary),
            (self.right_boundary, self.lower_boundary), (self.left_boundary, self.lower_boundary)
        ], fill='white')

    def write_text(self, text: str):
        """
        Write a line of text from bottom right boundary corner.
        """
        font = ImageFont.truetype(get_roberta_regular_font(), size=self.font_size)
        draw = ImageDraw.Draw(self.image)
        draw.text((self.right_boundary - 10, self.lower_boundary - 10), text, fill='black', anchor="rb", font=font)

    def save(self, save_path: Path):
        """
        Saves the image. if first_n_bytes is not None, save only the first bytes given by this attribute.
        """
        if not self.first_n_bytes:
            return self.image.save(save_path, format=self.image_format)
        
        if not isinstance(self.first_n_bytes, int):
            raise TypeError(f"Invalid data type: {type(self.first_n_bytes)}")
        if self.first_n_bytes < 1:
            raise TypeError(f"First n bytes {self.first_n_bytes} cannot be non-positive.")
        byte_array = io.BytesIO()
        self.image.save(byte_array, format=self.image_format)
        byte_array.seek(0)
        data = byte_array.read(self.first_n_bytes)
        with open(save_path, 'wb') as writer:
            writer.write(data)
        return

    def close(self):
        if isinstance(self.image, Image.Image):
            self.image.close()
        self.image = None
