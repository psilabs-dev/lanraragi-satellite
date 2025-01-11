from pathlib import Path
import tarfile
import tempfile
from typing import List, Union
import zipfile

from manycbz.enums import ArchivalStrategyEnum
from manycbz.page import Page

def create_comic(output: Union[str, Path], comic_id: str, width: int, height: int, num_pages: int, archival_strategy: ArchivalStrategyEnum=ArchivalStrategyEnum.ZIP) -> List[Path]:
    """
    Create comic pages in a specified output directory with given metadata,
    and returns the list of paths of the images.
    """
    if isinstance(output, str):
        output = Path(output)

    if archival_strategy == ArchivalStrategyEnum.NO_ARCHIVE:
        output.mkdir(parents=True, exist_ok=True)
        saved = []
        for page_id in range(num_pages):
            page_name = f"pg-{str(page_id+1).zfill(len(str(num_pages)))}"
            page_save_path = output / f"{page_name}.png"
            page = Page(width, height)
            page.whiten_panel()
            page.add_panel_boundary()
            page.write_text(f"{comic_id}-{page_name}")
            page.save(page_save_path)
            page.close()
            saved.append(page_save_path)
        return saved

    # All other strategies involve creating a temp directory, creating images in that tempdir,
    # then moving these images into the appropriate compressed file.
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_comic_dir = Path(tmpdir) / comic_id
        create_comic(tmp_comic_dir, comic_id, width, height, num_pages, archival_strategy=ArchivalStrategyEnum.NO_ARCHIVE)

        if archival_strategy == ArchivalStrategyEnum.ZIP:
            with zipfile.ZipFile(output, mode='w', compression=zipfile.ZIP_DEFLATED) as zipobj:
                for path in tmp_comic_dir.iterdir():
                    filename = path.name
                    zipobj.write(path, filename)
            return output
        elif archival_strategy == ArchivalStrategyEnum.TAR_GZ:
            with tarfile.open(output, mode='w:gz') as tarobj:
                for path in tmp_comic_dir.iterdir():
                    tarobj.add(path, arcname=path.name)
            return output
        elif archival_strategy == ArchivalStrategyEnum.XZ:
            with tarfile.open(output, mode='w:xz') as tarobj:
                for path in tmp_comic_dir.iterdir():
                    tarobj.add(path, arcname=path.name)
            return output
        else:
            raise NotImplementedError(f"The compression strategy is not implemented: {archival_strategy.name}")
