import os
from os.path import splitext, exists, join

from . import config


def format_bytes(size_bytes):
    """Format integer bytes into a human-readable string (e.g., '14.2 MB')."""
    if size_bytes is None or size_bytes < 0:
        return "0 B"
    for unit in ["B", "KB", "MB", "GB", "TB", "PB"]:
        if size_bytes < 1024.0:
            if unit == "B":
                return str(int(size_bytes)) + " B"
            return str(round(size_bytes, 1)) + " " + unit
        size_bytes /= 1024.0
    return str(round(size_bytes, 1)) + " PB"


def ensure_dir(path):
    """Create the directory (and parents) if it doesn't already exist."""
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)


def make_unique(dest_dir, name):
    """Return a filename that doesn't collide with anything in dest_dir."""
    filename, extension = splitext(name)
    count = 1
    new_name = name

    while exists(join(dest_dir, new_name)):
        new_name = filename + "_" + str(count) + extension
        count += 1

    return new_name


def get_category(extension):
    """Map a file extension to a category name, e.g. '.png' -> 'Images'."""
    ext = extension.lower()

    for category, extensions in config.CATEGORY_EXTENSIONS.items():
        if ext in extensions:
            return category

    return config.MISC_CATEGORY


def extension_folder_name(extension):
    """Fallback subfolder name for an extension with no subcategory rule.

    '.xyz' -> 'XYZ'. Anything that isn't alphanumeric is dropped so the name
    is always safe to create on Windows, macOS and Linux alike.
    """
    cleaned = "".join(ch for ch in extension.lstrip(".") if ch.isalnum())
    return cleaned.upper() if cleaned else "Other"


def get_subcategory(extension):
    """Map an extension to the subfolder it belongs in, e.g. '.xlsx' -> 'Spreadsheets'.

    Rules come from the "subcategories" block of categories.json, keyed by
    category. Extensions with no rule fall back to a folder named after the
    extension itself ('.heic' -> 'HEIC'), so every file still lands somewhere
    predictable instead of piling up loose in the category folder.
    """
    ext = extension.lower()
    category = get_category(ext)

    for sub_name, extensions in config.SUBCATEGORY_EXTENSIONS.get(category, {}).items():
        if ext in extensions:
            return sub_name

    return extension_folder_name(ext)


def get_dest(extension, base_dir, subfolders=False):
    """
    Return the destination folder for a file with this extension,
    rooted under base_dir (works for both SOURCE_DIR and DOWNLOADS_DIR).

    subfolders=True adds a second level inside the category folder,
    e.g. <base>/Documents/Spreadsheets instead of <base>/Documents.
    """
    category = get_category(extension)
    if subfolders:
        return os.path.join(base_dir, category, get_subcategory(extension))
    return os.path.join(base_dir, category)