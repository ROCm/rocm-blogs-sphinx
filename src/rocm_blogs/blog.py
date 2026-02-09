"""
Blog class for ROCmBlogs package.
"""

import hashlib
import io
import json
import os
import pathlib
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Union

from PIL import Image
from sphinx.util import logging as sphinx_logging

from .logger.logger import *

# Global caches for performance optimization during blog processing
_author_bio_cache: Dict[str, Dict[str, bool]] = {}
_image_manifest_cache: Dict[str, Dict[str, List[str]]] = {}
_image_manifest_paths_cache: Dict[str, Set[str]] = {}
_relative_path_cache: Dict[str, str] = {}


def build_image_manifest(blogs_directory: str) -> Dict[str, List[str]]:
    """Build manifest of available images in blogs directory."""
    global _image_manifest_cache
    global _image_manifest_paths_cache

    if blogs_directory in _image_manifest_cache:
        return _image_manifest_cache[blogs_directory]

    manifest: Dict[str, List[str]] = {}
    manifest_paths: Set[str] = set()

    if not blogs_directory:
        _image_manifest_cache[blogs_directory] = manifest
        _image_manifest_paths_cache[blogs_directory] = manifest_paths
        return manifest

    start_time = time.perf_counter()
    blogs_path = pathlib.Path(blogs_directory)

    # Define supported image file extensions for processing
    image_extensions = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
    skip_dirs = {"_static", "__pycache__", ".git"}

    def add_image(image_file: pathlib.Path) -> None:
        if not image_file.is_file():
            return
        if image_file.suffix.lower() not in image_extensions:
            return
        if image_file.parent.name in skip_dirs:
            return

        path_str = str(image_file)
        path_key = path_str.lower()
        if path_key in manifest_paths:
            return

        name_key = image_file.name.lower()
        manifest.setdefault(name_key, []).append(path_str)
        manifest_paths.add(path_key)

    images_directory = blogs_path / "images"
    if images_directory.exists():
        for image_file in images_directory.iterdir():
            add_image(image_file)

    for image_file in blogs_path.rglob("*"):
        add_image(image_file)

    _image_manifest_cache[blogs_directory] = manifest
    _image_manifest_paths_cache[blogs_directory] = manifest_paths

    duration = time.perf_counter() - start_time
    log_message(
        "info",
        f"Built image manifest for {blogs_directory}: {len(manifest_paths)} images, {len(manifest)} names in {duration:.2f}s",
        "general",
        "blog",
    )
    return manifest


def register_image_in_manifest(
    blogs_directory: str, image_path: Union[str, pathlib.Path]
) -> None:
    """Register a newly created image in the manifest caches."""
    if not blogs_directory:
        return

    manifest = _image_manifest_cache.get(blogs_directory)
    manifest_paths = _image_manifest_paths_cache.get(blogs_directory)
    if manifest is None or manifest_paths is None:
        return

    path_obj = pathlib.Path(image_path)
    if not path_obj.is_file():
        return

    if path_obj.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        return

    path_str = str(path_obj)
    path_key = path_str.lower()
    if path_key in manifest_paths:
        return

    manifest_paths.add(path_key)
    name_key = path_obj.name.lower()
    manifest.setdefault(name_key, []).append(path_str)


def cache_author_bio_existence(blogs_directory: str) -> Dict[str, bool]:
    """Cache existence status of author biography pages."""
    global _author_bio_cache

    if blogs_directory in _author_bio_cache:
        return _author_bio_cache[blogs_directory]

    author_cache = {}
    authors_directory = pathlib.Path(blogs_directory) / "authors"

    if authors_directory.exists():
        for author_file in authors_directory.glob("*.md"):
            if author_file.is_file():
                # Extract author name from filename and normalize formatting
                author_name = author_file.stem.replace("-", " ").title()
                author_cache[author_name.lower()] = True

    _author_bio_cache[blogs_directory] = author_cache
    return author_cache


class Blog:
    """Represents a blog post with metadata and images."""

    # Define date formats once as a class variable to avoid recreation
    DATE_FORMATS = [
        "%d-%m-%Y",  # e.g. 8-08-2024
        "%d/%m/%Y",  # e.g. 8/08/2024
        "%d-%B-%Y",  # e.g. 8-August-2024
        "%d-%b-%Y",  # e.g. 8-Aug-2024
        "%d %B %Y",  # e.g. 8 August 2024
        "%d %b %Y",  # e.g. 8 Aug 2024
        "%d %B, %Y",  # e.g. 8 August, 2024
        "%d %b, %Y",  # e.g. 8 Aug, 2024
        "%B %d, %Y",  # e.g. August 8, 2024
        "%b %d, %Y",  # e.g. Aug 8, 2024
        "%B %d %Y",  # e.g. August 8 2024
        "%b %d %Y",  # e.g. Aug 8 2024
    ]

    # Month name normalization mapping
    MONTH_NORMALIZATION = {"Sept": "Sep"}

    def __init__(
        self, file_path: str, metadata: Dict[str, Any], image: Optional[bytes] = None
    ):
        """Initialize Blog instance."""
        self.file_path = file_path
        self.metadata = metadata
        self.image = image
        self.image_paths = []
        self.word_count = 0
        self._image_cache: Dict[tuple[str, str], pathlib.Path] = {}

        # Dynamically assign attributes based on metadata dictionary contents
        for key, value in metadata.items():
            setattr(self, key, value)

        self.date = (
            self.parse_date(metadata.get("date")) if "date" in metadata else None
        )

    def set_word_count(self, word_count: int) -> None:
        """Set word count."""
        self.word_count = word_count

    def set_file_path(self, file_path: str) -> None:
        """Set file path."""
        self.file_path = file_path

    def normalize_date_string(self, date_str: str) -> str:
        """Normalize date string formatting."""
        for original, replacement in self.MONTH_NORMALIZATION.items():
            date_str = date_str.replace(original, replacement)

        return date_str

    def grab_og_image(self) -> str:
        """Get OpenGraph image, falling back to regular image if not available."""
        try:
            myst_data = self.metadata.get("myst", {})
            html_meta = myst_data.get("html_meta", {})
            og_image = html_meta.get("property=og:image")

            if og_image:
                return og_image
        except (AttributeError, TypeError):
            pass

        # Fallback: use the regular image path logic
        # Convert the relative path from grab_image to absolute URL
        try:
            # Create a temporary ROCmBlogs-like object for grab_image
            class TempROCmBlogs:
                def __init__(self):
                    self.blogs_directory = (
                        os.path.dirname(self.file_path)
                        if hasattr(self, "file_path")
                        else ""
                    )

            temp_rocmblogs = TempROCmBlogs()
            image_path = self.grab_image(temp_rocmblogs)

            # Convert relative path to absolute URL
            if str(image_path).startswith("./"):
                image_url = f"https://rocm.blogs.amd.com/{str(image_path)[2:]}"
            else:
                image_url = f"https://rocm.blogs.amd.com/_images/{os.path.basename(str(image_path))}"

            return image_url
        except Exception:
            return "https://rocm.blogs.amd.com/_images/generic.jpg"

    def grab_og_description(self) -> str:
        """Get OpenGraph description, falling back to a default if not available."""
        try:
            myst_data = self.metadata.get("myst", {})
            html_meta = myst_data.get("html_meta", {})
            og_description = html_meta.get("property=og:description")

            if og_description:
                return og_description

            # Try alternative description fields
            description = html_meta.get("description lang=en")
            if description:
                return description

        except (AttributeError, TypeError):
            pass

        return "No description available."

    def grab_og_href(self) -> str:
        """Get OpenGraph URL, falling back to regular href if not available."""
        try:
            myst_data = self.metadata.get("myst", {})
            html_meta = myst_data.get("html_meta", {})
            og_url = html_meta.get("property=og:url")

            if og_url:
                return og_url
        except (AttributeError, TypeError):
            pass

        # Fallback: use the regular href logic
        try:
            href = self.grab_href()
            # Convert relative path to absolute URL
            if href.startswith("./"):
                return f"https://rocm.blogs.amd.com{href[1:]}"
            elif href.startswith("/"):
                return f"https://rocm.blogs.amd.com{href}"
            else:
                return f"https://rocm.blogs.amd.com/{href}"
        except Exception:
            return "https://rocm.blogs.amd.com/"

    def grab_metadata(self) -> Dict[str, Any]:
        """Get metadata."""
        return self.metadata

    def load_image_to_memory(self, image_path: str, format: str = "PNG") -> None:
        """Load image into memory."""
        try:
            with Image.open(image_path) as img:
                buffer = io.BytesIO()
                img.save(buffer, format=format)
                buffer.seek(0)
                self.image = buffer.getvalue()
                log_message(
                    "info",
                    f"Image loaded into memory; size: {len(self.image)} bytes.",
                    "general",
                    "blog",
                )
        except Exception as error:
            log_message(
                "error", f"Error loading image to memory: {error}", "general", "blog"
            )

    def to_json(self) -> str:
        """Convert metadata to JSON."""
        try:
            return json.dumps(self.metadata, indent=4)
        except Exception as error:
            log_message(
                "error",
                f"Error converting metadata to JSON: {error}",
                "general",
                "blog",
            )
            return "{}"

    def save_image(self, output_path: str) -> None:
        """Save image to disk."""
        if self.image is None:
            log_message(
                "warning",
                "No image data available in memory to save.",
                "general",
                "blog",
            )
            return

        try:
            with open(output_path, "wb") as file:
                file.write(self.image)
                log_message(
                    "info", "Image saved to disk at: {output_path}", "general", "blog"
                )
        except Exception as error:
            log_message(
                "error", f"Error saving image to disk: {error}", "general", "blog"
            )

    def save_image_path(self, image_path: str) -> None:
        """Save image path."""
        if image_path not in self.image_paths:
            self.image_paths.append(image_path)

    def parse_date(self, date_str: Optional[str]) -> Optional[datetime]:
        """Parse date string to datetime object."""
        if not date_str:
            return None

        # Normalize the date string
        date_str = self.normalize_date_string(date_str)

        # Try each date format
        for fmt in self.DATE_FORMATS:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue

        log_message("warning", f"Invalid date format in {self.file_path}: {date_str}")
        return None

    def grab_href(self) -> str:
        """Generate HTML href for blog."""
        return self.file_path.replace(".md", ".html").replace("\\", "/")

    def grab_authors_list(self) -> List[str]:
        """Extract authors from metadata."""

        log_message(
            "info",
            f"Extracting authors from metadata: {self.file_path}",
            "general",
            "blog",
        )

        log_message("info", f"Authors metadata: {self.author}", "general", "blog")

        if not self.author:
            return []

        log_message("info", f"Author type: {type(self.author)}", "general", "blog")

        # Ensure authors is a list
        if isinstance(self.author, str):
            authors = list(self.author.split(", "))

        log_message("info", f"Authors after split: {authors}", "general", "blog")

        return authors

    def grab_authors(
        self, authors_list: List[Union[str, List[str]]], rocm_blogs
    ) -> str:
        """Generate HTML links for authors with bio files."""
        # Filter out invalid authors
        valid_authors = []
        for author in authors_list:
            if isinstance(author, list):
                author_str = " ".join(author).strip()
            else:
                author_str = str(author).strip()

            if author_str and author_str.lower() != "no author":
                valid_authors.append(author_str)

        if not valid_authors:
            return ""

        # Use cached author bio existence information
        author_cache = cache_author_bio_existence(rocm_blogs.blogs_directory)

        # Process each author
        author_elements = []
        for author in valid_authors:
            # Check if author has a page using cached information
            author_key = author.lower()
            if author_key in author_cache:
                author_link = f"https://rocm.blogs.amd.com/authors/{author.replace(' ', '-').lower()}.html"
                author_elements.append(f'<a href="{author_link}">{author}</a>')
            else:
                # Use plain text if no author file exists
                author_elements.append(author)

        return ", ".join(author_elements)

    def grab_image(self, rocmblogs) -> pathlib.Path:
        """Find and return blog image path."""
        image = getattr(self, "thumbnail", None)
        blogs_directory = getattr(rocmblogs, "blogs_directory", "") or ""
        image_key = image if image else "__generic__"
        cache_key = (blogs_directory, str(image_key))

        cached_path = self._image_cache.get(cache_key)
        if cached_path is not None:
            log_message(
                "debug",
                f"Image cache hit for {image_key} in {blogs_directory}",
                "general",
                "blog",
            )
            return cached_path

        if not image:
            # First check if generic.webp exists in blogs/images directory
            blogs_generic_webp = None
            if blogs_directory:
                blogs_generic_webp_path = os.path.join(
                    blogs_directory, "images", "generic.webp"
                )
                if os.path.exists(blogs_generic_webp_path):
                    blogs_generic_webp = blogs_generic_webp_path

            # Then check if generic.webp exists in static/images directory
            static_generic_webp_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                "static",
                "images",
                "generic.webp",
            )
            static_generic_webp = os.path.exists(static_generic_webp_path)

            # Use blogs/images/generic.webp if available, otherwise use
            # static/images/generic.webp
            if blogs_generic_webp:
                self.image = "generic.webp"
                self.save_image_path("generic.webp")
                result = pathlib.Path("./images/generic.webp")
                self._image_cache[cache_key] = result
                return result
            elif static_generic_webp:
                self.image = "generic.webp"
                self.save_image_path("generic.webp")
                result = pathlib.Path("./images/generic.webp")
                self._image_cache[cache_key] = result
                return result
            else:
                # Fall back to generic.jpg if no WebP version is available
                self.image = "generic.jpg"
                self.save_image_path("generic.jpg")
                result = pathlib.Path("./images/generic.jpg")
                self._image_cache[cache_key] = result
                return result

        # Extract just the filename if a path is provided
        if "/" in image or "\\" in image:
            image = os.path.basename(image)

        # Check if it's an absolute path
        if os.path.isabs(image) and os.path.exists(image):
            full_image_path = pathlib.Path(image)
            self.save_image_path(os.path.basename(str(full_image_path)))
            result = self._get_relative_path(full_image_path, blogs_directory)
            self._image_cache[cache_key] = result
            return result

        # Find the image in various locations
        full_image_path = self._find_image_in_directories(
            image, blogs_directory
        )

        if not full_image_path:
            # Check if generic.webp exists
            generic_webp_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                "static",
                "images",
                "generic.webp",
            )
            if os.path.exists(generic_webp_path):
                self.image = "generic.webp"
                self.save_image_path("generic.webp")
                result = pathlib.Path("./images/generic.webp")
                self._image_cache[cache_key] = result
                return result
            else:
                self.image = "generic.jpg"
                self.save_image_path("generic.jpg")
                result = pathlib.Path("./images/generic.jpg")
                self._image_cache[cache_key] = result
                return result

        # Save the image path and return the relative path
        image_name = os.path.basename(str(full_image_path))
        self.save_image_path(image_name)

        result = self._get_relative_path(full_image_path, blogs_directory)
        self._image_cache[cache_key] = result
        return result

    def _find_image_in_directories(
        self, image: str, blogs_directory: str
    ) -> Optional[pathlib.Path]:
        """Search for image in various directories."""
        blog_dir = pathlib.Path(self.file_path).parent
        blogs_dir = pathlib.Path(blogs_directory)
        manifest = build_image_manifest(blogs_directory)
        manifest_paths = _image_manifest_paths_cache.get(blogs_directory, set())

        def path_exists(path: pathlib.Path) -> bool:
            if manifest_paths:
                path_key = str(path).lower()
                if path_key in manifest_paths:
                    return True
                if path.exists() and path.is_file():
                    register_image_in_manifest(blogs_directory, path)
                    return True
                return False
            return path.exists() and path.is_file()

        def find_partial_in_manifest(
            base_name: str, base_dir: pathlib.Path, extension: Optional[str] = None
        ) -> Optional[pathlib.Path]:
            if not manifest_paths:
                return None
            base_prefix = str(base_dir).lower() + os.sep
            base_name = base_name.lower()
            extension = extension.lower() if extension else None

            for name_key, candidates in manifest.items():
                if extension and not name_key.endswith(extension):
                    continue
                if base_name not in name_key:
                    continue
                for candidate in candidates:
                    if candidate.lower().startswith(base_prefix):
                        return pathlib.Path(candidate)
            return None

        def prefer_hashed_image(path: pathlib.Path) -> pathlib.Path:
            """Prefer hashed _images variant if it exists."""
            try:
                if not blogs_directory:
                    return path
                rel_key = os.path.relpath(str(path), blogs_directory).replace("\\", "/")
                digest = hashlib.md5(rel_key.encode("utf-8")).hexdigest()[:10]
                name_root, ext = os.path.splitext(path.name)
                hashed_name = f"{name_root}-{digest}{ext}"
                hashed_path = blogs_dir / "_images" / hashed_name
                if hashed_path.exists():
                    return hashed_path
            except Exception:
                pass
            return path

        # Check if there's a WebP version of the image
        image_base, image_ext = os.path.splitext(image)
        webp_image = image_base + ".webp"

        # Define search paths in order of priority
        search_paths = [
            blog_dir / webp_image,
            blog_dir / "images" / webp_image,
            blog_dir / image,
            blog_dir / "images" / image,
            blog_dir.parent / webp_image,
            blog_dir.parent / "images" / webp_image,
            blog_dir.parent / image,
            blog_dir.parent / "images" / image,
            blogs_dir / "_images" / webp_image,
            blogs_dir / "_images" / image,
        ]

        parent2 = blog_dir.parent.parent
        if parent2 != blogs_dir:
            search_paths.extend(
                [
                    parent2 / webp_image,
                    parent2 / "images" / webp_image,
                    parent2 / image,
                    parent2 / "images" / image,
                ]
            )

            parent3 = parent2.parent
            if parent3 != blogs_dir:
                search_paths.extend(
                    [
                        parent3 / webp_image,
                        parent3 / "images" / webp_image,
                        parent3 / image,
                        parent3 / "images" / image,
                    ]
                )

        search_paths.extend(
            [
                blog_dir.parent / "images" / webp_image,
                blogs_dir / "images" / webp_image,
                blogs_dir / "images" / webp_image.lower(),
                blog_dir.parent / "images" / image,
                blogs_dir / "images" / image,
                blogs_dir / "images" / image.lower(),
            ]
        )

        # Check each path
        for path in search_paths:
            if path_exists(path):
                if str(path).lower().endswith(".webp"):
                    log_message(
                        "info",
                        f"Using WebP version for image: {path}",
                        "general",
                        "blog",
                    )
                return prefer_hashed_image(path)

        # Try partial matching in the global images directory
        images_dir = blogs_dir / "images"
        if manifest_paths:
            webp_base = os.path.splitext(image)[0].lower()
            manifest_webp = find_partial_in_manifest(webp_base, images_dir, ".webp")
            if manifest_webp is not None:
                log_message(
                    "info",
                    f"Found WebP version by partial matching: {manifest_webp}",
                    "general",
                    "blog",
                )
                return prefer_hashed_image(manifest_webp)

            image_base = os.path.splitext(image)[0].lower()
            manifest_image = find_partial_in_manifest(image_base, images_dir)
            if manifest_image is not None:
                if not str(manifest_image).lower().endswith(".webp"):
                    try:
                        with Image.open(manifest_image) as img:
                            original_width, original_height = img.size

                            webp_img = img
                            if img.mode not in ("RGB", "RGBA"):
                                webp_img = img.convert("RGB")

                            if original_width > 1200 or original_height > 700:
                                scaling_factor = min(
                                    1200 / original_width, 700 / original_height
                                )

                                new_width = int(original_width * scaling_factor)
                                new_height = int(original_height * scaling_factor)

                                webp_img = webp_img.resize(
                                    (new_width, new_height), resample=Image.LANCZOS
                                )
                                log_message(
                                    "info",
                                    f"Resized image from {original_width}x{original_height} to {new_width}x{new_height}",
                                    "general",
                                    "blog",
                                )

                            webp_path = (
                                os.path.splitext(str(manifest_image))[0] + ".webp"
                            )
                            webp_img.save(
                                webp_path, format="WEBP", quality=98, method=6
                            )
                            register_image_in_manifest(blogs_directory, webp_path)

                            # Return the WebP version
                            log_message(
                                "info",
                                f"Successfully converted {manifest_image} to WebP: {webp_path}",
                                "general",
                                "blog",
                            )
                            return pathlib.Path(webp_path)
                    except Exception as e:
                        log_message(
                            "warning",
                            f"Failed to convert {manifest_image} to WebP: {e}",
                        )

                return prefer_hashed_image(manifest_image)

        hashed_dir = blogs_dir / "_images"
        if manifest_paths:
            webp_base = os.path.splitext(image)[0].lower()
            manifest_webp = find_partial_in_manifest(webp_base, hashed_dir, ".webp")
            if manifest_webp is not None:
                log_message(
                    "info",
                    f"Found hashed WebP by partial matching: {manifest_webp}",
                    "general",
                    "blog",
                )
                return pathlib.Path(manifest_webp)

            image_base = os.path.splitext(image)[0].lower()
            manifest_image = find_partial_in_manifest(image_base, hashed_dir)
            if manifest_image is not None:
                log_message(
                    "info",
                    f"Found hashed image by partial matching: {manifest_image}",
                    "general",
                    "blog",
                )
                return pathlib.Path(manifest_image)

        if images_dir.exists():
            webp_base = os.path.splitext(image)[0].lower()
            for img_file in images_dir.glob("*.webp"):
                if img_file.is_file() and webp_base in img_file.name.lower():
                    log_message(
                        "info",
                        f"Found WebP version by partial matching: {img_file}",
                        "general",
                        "blog",
                    )
                    return prefer_hashed_image(img_file)

            # If no WebP version found, try to find original image by partial
            # matching
            image_base = os.path.splitext(image)[0].lower()
            for img_file in images_dir.glob("*"):
                if img_file.is_file() and image_base in img_file.name.lower():
                    if not str(img_file).lower().endswith(".webp"):
                        try:
                            with Image.open(img_file) as img:
                                original_width, original_height = img.size

                                webp_img = img
                                if img.mode not in ("RGB", "RGBA"):
                                    webp_img = img.convert("RGB")

                                if original_width > 1200 or original_height > 700:
                                    scaling_factor = min(
                                        1200 / original_width, 700 / original_height
                                    )

                                    new_width = int(original_width * scaling_factor)
                                    new_height = int(original_height * scaling_factor)

                                    webp_img = webp_img.resize(
                                        (new_width, new_height), resample=Image.LANCZOS
                                    )
                                    log_message(
                                        "info",
                                        f"Resized image from {original_width}x{original_height} to {new_width}x{new_height}",
                                        "general",
                                        "blog",
                                    )

                                webp_path = os.path.splitext(str(img_file))[0] + ".webp"
                                webp_img.save(
                                    webp_path, format="WEBP", quality=98, method=6
                                )
                                register_image_in_manifest(blogs_directory, webp_path)

                                # Return the WebP version
                                log_message(
                                    "info",
                                    f"Successfully converted {img_file} to WebP: {webp_path}",
                                    "general",
                                    "blog",
                                )
                                return pathlib.Path(webp_path)
                        except Exception as e:
                            log_message(
                                "warning", f"Failed to convert {img_file} to WebP: {e}"
                            )

                    return img_file

        if hashed_dir.exists():
            webp_base = os.path.splitext(image)[0].lower()
            for img_file in hashed_dir.glob("*.webp"):
                if img_file.is_file() and webp_base in img_file.name.lower():
                    log_message(
                        "info",
                        f"Found hashed WebP by partial matching: {img_file}",
                        "general",
                        "blog",
                    )
                    return img_file

            image_base = os.path.splitext(image)[0].lower()
            for img_file in hashed_dir.glob("*"):
                if img_file.is_file() and image_base in img_file.name.lower():
                    log_message(
                        "info",
                        f"Found hashed image by partial matching: {img_file}",
                        "general",
                        "blog",
                    )
                    return img_file

        return None

    def _get_relative_path(
        self, full_path: pathlib.Path, base_dir: str
    ) -> pathlib.Path:
        """Convert an absolute path to a relative path."""
        cache_key = f"{full_path}|{base_dir}"
        cached_path = _relative_path_cache.get(cache_key)
        if cached_path:
            return pathlib.Path(cached_path)

        relative_path = os.path.relpath(str(full_path), str(base_dir))
        relative_path = relative_path.replace("\\", "/")

        if not relative_path.startswith("./"):
            relative_path = "./" + relative_path

        _relative_path_cache[cache_key] = relative_path
        return pathlib.Path(relative_path)

    def __repr__(self) -> str:
        """Return a string representation of the class."""
        return f"Blog(file_path='{self.file_path}', metadata={self.metadata})"
