"""Tools for galleries of computational studies: check, build the site, publish.

A gallery is a repository with ``gallery.yml`` at its root and one folder per study in
``studies/``. The command line is ``gallery`` (see ``gallery --help``).
"""

from gallery_tools.config import Gallery, GalleryError, load
from gallery_tools.study import KINDS, Study, discover

__all__ = ["KINDS", "Gallery", "GalleryError", "Study", "discover", "load"]
