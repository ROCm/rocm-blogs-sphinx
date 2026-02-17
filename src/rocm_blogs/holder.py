"""
File: _blog_holder.py

BlogHolder class to hold the blogs.
"""

import csv
import os
import traceback
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from sphinx.util import logging as sphinx_logging

from .blog import Blog
from .logger.logger import *


class BlogHolder:
    """Initialize the BlogHolder class."""

    def __init__(self) -> None:
        """Initialize blog collections and predefined market verticals."""
        self.blogs: Dict[str, Blog] = {}
        self.blogs_categories: Dict[str, List[Blog]] = {}
        self.blogs_authors: Dict[str, List[Blog]] = {}
        self.blogs_featured: Dict[str, List[Blog]] = {}
        self.blogs_verticals: Dict[str, List[Blog]] = {}
        self.blogs_categories_verticals: Dict[Tuple[str, str], List[Blog]] = {}
        self.verticals = [
            "AI",
            "HPC",
            "Data Science",
            "Systems",
            "Developers",
            "Robotics",
        ]
        self._seen_paths: Set[str] = set()
        self._seen_titles: Set[str] = set()
        self._duplicate_count = 0

    def _normalize_title(self, title: str) -> str:
        """Normalize title for consistent comparison."""
        if not title:
            return ""

        title = title.replace("\u202f", " ")
        title = title.replace("\u00a0", " ")
        title = title.replace("\u2009", " ")
        title = title.replace("\u200b", "")
        title = title.replace("\u2013", "-")
        title = title.replace("\u2014", "-")

        title = title.replace("\u2018", "'")
        title = title.replace("\u2019", "'")
        title = title.replace("\u201c", '"')
        title = title.replace("\u201d", '"')

        title = " ".join(title.split())

        title = title.lower()

        return title

    def _normalize_path(self, path: str) -> str:
        """Normalize file path for consistent comparison."""
        if not path:
            return ""

        try:
            path_obj = Path(path).resolve()
            normalized = str(path_obj).replace("\\", "/")
            return normalized.lower()
        except Exception as e:
            log_message("warning", f"Failed to normalize path {path}: {e}")
            return path.replace("\\", "/").lower()

    def _generate_blog_key(self, blog: Blog) -> str:
        """Generate unique identifier key for blog post with better deduplication."""
        if not isinstance(blog, Blog):
            log_message("error", f"Expected Blog instance but got {type(blog)}")
            raise TypeError("The blog must be an instance of the 'Blog' class.")

        if hasattr(blog, "blog_title") and blog.blog_title:
            title = self._normalize_title(blog.blog_title)
        else:
            if hasattr(blog, "file_path"):
                filename = os.path.basename(blog.file_path)
                title = (
                    os.path.splitext(filename)[0].replace("-", " ").replace("_", " ")
                )
                title = self._normalize_title(title)
                log_message(
                    "warning",
                    f"Blog missing blog_title attribute, using filename: {title}",
                )
            else:
                title = "untitled_blog"
                log_message(
                    "warning",
                    "Blog has no title or file path, using default 'untitled_blog'",
                )

        if hasattr(blog, "file_path") and blog.file_path:
            normalized_path = self._normalize_path(blog.file_path)
            path_parts = normalized_path.split("/")
            if len(path_parts) >= 3:
                relevant_path = "/".join(path_parts[-3:])
            else:
                relevant_path = normalized_path
            key = f"{title}||{relevant_path}"
        else:
            import time

            key = f"{title}||no_path_{time.time()}"

        log_message("debug", f"Created normalized key for blog: {key}")
        return key

    def add_blog(self, blog: Blog) -> None:
        """Add blog to collection with enhanced duplicate detection."""
        if hasattr(blog, "file_path") and blog.file_path:
            normalized_path = self._normalize_path(blog.file_path)
            if normalized_path in self._seen_paths:
                self._duplicate_count += 1
                log_message(
                    "warning",
                    f"Duplicate blog path detected (count: {self._duplicate_count}): '{normalized_path}'",
                    "general",
                    "holder",
                )
                raise KeyError(f"Blog with path '{normalized_path}' already exists.")
            self._seen_paths.add(normalized_path)

        if hasattr(blog, "blog_title") and blog.blog_title:
            normalized_title = self._normalize_title(blog.blog_title)
            if normalized_title in self._seen_titles:
                log_message(
                    "warning",
                    f"Blog with similar title already exists: '{blog.blog_title}'",
                    "general",
                    "holder",
                )
            self._seen_titles.add(normalized_title)

        key = self._generate_blog_key(blog)
        if key in self.blogs:
            self._duplicate_count += 1
            log_message(
                "warning",
                f"Duplicate blog key detected (count: {self._duplicate_count}): '{key}'",
                "general",
                "holder",
            )
            return

        self.blogs[key] = blog
        log_message("info", f"Added blog: '{key}'", "general", "holder")

        if hasattr(blog, "author"):
            log_message("debug", f"Adding blog '{key}' to author '{blog.author}'")
            for author in blog.grab_authors_list():
                if author not in self.blogs_authors:
                    self.blogs_authors[author] = []
                    log_message("debug", f"Initialized author list for: {author}")

                is_duplicate = False
                blog_title = getattr(blog, "blog_title", "")
                blog_path = getattr(blog, "file_path", "")

                for existing_blog in self.blogs_authors[author]:
                    existing_title = getattr(existing_blog, "blog_title", "")
                    existing_path = getattr(existing_blog, "file_path", "")

                    if (
                        blog_title and existing_title and blog_title == existing_title
                    ) or (blog_path and existing_path and blog_path == existing_path):
                        is_duplicate = True
                        log_message(
                            "warning",
                            f"Duplicate blog detected for author '{author}': '{blog_title}' (path: {blog_path})",
                        )
                        break

                if not is_duplicate:
                    log_message("debug", f"Adding blog '{key}' to author '{author}'")
                    self.blogs_authors[author].append(blog)
        else:
            log_message(
                "warning", f"Blog '{key}' has no author specified", "general", "holder"
            )

    def remove_blog(self, blog: Blog) -> None:
        """Remove blog from collection and all associated indices."""
        key = self._generate_blog_key(blog)
        if key in self.blogs:
            del self.blogs[key]
            log_message(
                "info",
                f"Removed blog: '{key}'",
                "general",
                "holder",
            )
        else:
            log_message("warning", f"Cannot remove blog: '{key}' not found")
            raise KeyError("Blog not found.")

    def write_to_file(self, filename: str = "blogs.csv") -> None:
        """Write blog information to CSV file."""
        try:
            with open(filename, "w", newline="", encoding="utf-8") as file:
                writer = csv.writer(file)

                writer.writerow(
                    [
                        "title",
                        "date",
                        "author",
                        "category",
                        "tags",
                        "thumbnail",
                        "file_path",
                    ]
                )

                for blog in self.blogs.values():
                    title = (
                        blog.blog_title if hasattr(blog, "blog_title") else "Untitled"
                    )
                    if title:
                        title = title.replace("\u202f", " ")
                        title = title.replace("\u00a0", " ")
                        title = title.replace("\u2009", " ")
                        title = title.replace("\u200b", "")

                    date = (
                        blog.date.strftime("%Y-%m-%d")
                        if hasattr(blog, "date") and blog.date
                        else ""
                    )
                    author = blog.author if hasattr(blog, "author") else ""
                    if author:
                        author = author.replace("\u202f", " ").replace("\u00a0", " ")

                    category = blog.category if hasattr(blog, "category") else ""
                    if category:
                        category = category.replace("\u202f", " ").replace(
                            "\u00a0", " "
                        )

                    tags = blog.tags if hasattr(blog, "tags") else ""
                    if tags:
                        tags = tags.replace("\u202f", " ").replace("\u00a0", " ")

                    thumbnail = blog.thumbnail if hasattr(blog, "thumbnail") else ""
                    file_path = blog.file_path if hasattr(blog, "file_path") else ""

                    writer.writerow(
                        [title, date, author, category, tags, thumbnail, file_path]
                    )

            log_message(
                "info",
                f"Successfully wrote {len(self.blogs)} blog entries to {filename}",
                "general",
                "holder",
            )
        except Exception as error:
            log_message("error", f"Error writing blogs to file: {error}")
            raise

    def load_featured_blogs_from_csv(
        self, filename: str = "featured-blogs.csv"
    ) -> list[Blog]:
        """Load featured blogs from CSV file with comprehensive logging."""
        featured_blogs = []

        try:
            log_message(
                "info",
                f"========== FEATURED BLOGS LOADING PROCESS STARTED ==========",
                "featured_blogs",
                "holder",
            )

            if not os.path.exists(filename):
                log_message(
                    "error",
                    f"Featured blogs file not found: {filename}",
                    "featured_blogs",
                    "holder",
                )
                return featured_blogs

            log_message(
                "info",
                f"Reading featured blogs from file: {filename}",
                "featured_blogs",
                "holder",
            )

            with open(filename, "r", newline="", encoding="utf-8") as file:
                reader = csv.reader(file)
                raw_rows = list(reader)
                log_message(
                    "debug",
                    f"Raw CSV rows read: {len(raw_rows)}",
                    "featured_blogs",
                    "holder",
                )
                log_message(
                    "debug", f"Raw CSV content: {raw_rows}", "featured_blogs", "holder"
                )

                featured_titles = []
                for i, row in enumerate(raw_rows):
                    if row and row[0].strip():
                        title = row[0].strip()

                        if title.lower() in ["no newline at end of file", "eof", ""]:
                            log_message(
                                "debug",
                                f"CSV row {i+1}: Skipping invalid entry: '{title}'",
                                "featured_blogs",
                                "holder",
                            )
                            continue

                        featured_titles.append(title)
                        log_message(
                            "debug",
                            f"CSV row {i+1}: '{title}' (length: {len(title)})",
                            "featured_blogs",
                            "holder",
                        )
                    else:
                        log_message(
                            "debug",
                            f"CSV row {i+1}: Empty or invalid row: {row}",
                            "featured_blogs",
                            "holder",
                        )

            log_message(
                "info",
                f"Extracted {len(featured_titles)} valid featured blog titles from {filename}",
                "featured_blogs",
                "holder",
            )

            available_blogs = [
                blog
                for blog in self.blogs.values()
                if hasattr(blog, "blog_title") and blog.blog_title
            ]
            available_blog_titles = [blog.blog_title for blog in available_blogs]

            log_message(
                "info",
                f"Total blogs available in system: {len(available_blog_titles)}",
                "featured_blogs",
                "holder",
            )
            log_message(
                "debug",
                f"Available blog titles: {available_blog_titles}",
                "featured_blogs",
                "holder",
            )

            log_message(
                "info",
                "========== PROCESSING FEATURED TITLES ==========",
                "featured_blogs",
                "holder",
            )
            for index, title in enumerate(featured_titles):
                log_message(
                    "info",
                    f"Processing featured title {index+1}/{len(featured_titles)}: '{title}'",
                    "featured_blogs",
                    "holder",
                )

                title_bytes = title.encode("utf-8")
                log_message(
                    "debug",
                    f"Title '{title}' - Length: {len(title)}, UTF-8 bytes: {len(title_bytes)}, Bytes: {title_bytes}",
                    "featured_blogs",
                    "holder",
                )

            log_message(
                "info",
                "========== BLOG MATCHING PROCESS ==========",
                "featured_blogs",
                "holder",
            )
            for index, title in enumerate(featured_titles):
                log_message(
                    "info",
                    f"Matching attempt {index+1}/{len(featured_titles)} for: '{title}'",
                    "featured_blogs",
                    "holder",
                )

                original_title = title
                clean_title = title.strip()
                log_message(
                    "debug",
                    f"Original title: '{original_title}'",
                    "featured_blogs",
                    "holder",
                )
                log_message(
                    "debug",
                    f"After strip(): '{clean_title}'",
                    "featured_blogs",
                    "holder",
                )

                before_normalization = clean_title
                clean_title = clean_title.replace("™", "™")
                clean_title = clean_title.replace("\u202f", " ")
                clean_title = clean_title.replace("\u00a0", " ")
                clean_title = clean_title.replace("\u2009", " ")

                if before_normalization != clean_title:
                    log_message(
                        "info",
                        f"Unicode normalization applied: '{before_normalization}' -> '{clean_title}'",
                        "featured_blogs",
                        "holder",
                    )
                else:
                    log_message(
                        "debug",
                        "No Unicode normalization needed",
                        "featured_blogs",
                        "holder",
                    )

                log_message(
                    "debug",
                    f"Attempting exact match with cleaned title: '{clean_title}'",
                    "featured_blogs",
                    "holder",
                )
                blog = self.get_blog_by_title(clean_title)

                if not blog:
                    log_message(
                        "debug",
                        f"Cleaned title failed, trying original: '{original_title}'",
                        "featured_blogs",
                        "holder",
                    )
                    blog = self.get_blog_by_title(original_title)

                if blog:
                    log_message(
                        "info",
                        f"[SUCCESS] MATCH FOUND for '{original_title}' -> Blog: '{blog.blog_title}'",
                        "featured_blogs",
                        "holder",
                    )

                    if blog not in featured_blogs:
                        featured_blogs.append(blog)
                        log_message(
                            "info",
                            f"[SUCCESS] Added blog to featured list: '{blog.blog_title}'",
                            "featured_blogs",
                            "holder",
                        )
                    else:
                        log_message(
                            "warning",
                            f"[WARNING] Duplicate featured blog found: '{blog.blog_title}' (skipping)",
                            "featured_blogs",
                            "holder",
                        )
                else:
                    log_message(
                        "warning",
                        f"[FAILED] NO EXACT MATCH found for: '{original_title}'",
                        "featured_blogs",
                        "holder",
                    )

                    log_message(
                        "debug",
                        "Attempting fuzzy matching...",
                        "featured_blogs",
                        "holder",
                    )
                    close_matches = []
                    for available_title in available_blog_titles:
                        if (
                            original_title.lower() in available_title.lower()
                            or available_title.lower() in original_title.lower()
                        ):
                            close_matches.append(available_title)
                            log_message(
                                "debug",
                                f"Fuzzy match candidate: '{available_title}'",
                                "featured_blogs",
                                "holder",
                            )

                    if close_matches:
                        log_message(
                            "info",
                            f"Found {len(close_matches)} fuzzy matches for '{original_title}': {close_matches}",
                            "featured_blogs",
                            "holder",
                        )

                        best_match = close_matches[0]
                        log_message(
                            "info",
                            f"Using best fuzzy match: '{best_match}'",
                            "featured_blogs",
                            "holder",
                        )

                        blog = self.get_blog_by_title(best_match)
                        if blog:
                            log_message(
                                "info",
                                f"[SUCCESS] FUZZY MATCH SUCCESS: '{original_title}' -> '{blog.blog_title}'",
                                "featured_blogs",
                                "holder",
                            )

                            if blog not in featured_blogs:
                                featured_blogs.append(blog)
                                log_message(
                                    "info",
                                    f"[SUCCESS] Added fuzzy matched blog: '{blog.blog_title}'",
                                    "featured_blogs",
                                    "holder",
                                )
                            else:
                                log_message(
                                    "warning",
                                    f"[WARNING] Duplicate fuzzy matched blog: '{blog.blog_title}' (skipping)",
                                    "featured_blogs",
                                    "holder",
                                )
                        else:
                            log_message(
                                "error",
                                f"[FAILED] Fuzzy match failed to retrieve blog for: '{best_match}'",
                                "featured_blogs",
                                "holder",
                            )
                    else:
                        log_message(
                            "error",
                            f"[FAILED] NO MATCHES FOUND (exact or fuzzy) for: '{original_title}'",
                            "featured_blogs",
                            "holder",
                        )

            log_message(
                "info",
                "========== FEATURED BLOGS MATCHING SUMMARY ==========",
                "featured_blogs",
                "holder",
            )
            log_message(
                "info",
                f"Successfully loaded {len(featured_blogs)} featured blogs out of {len(featured_titles)} requested titles",
                "featured_blogs",
                "holder",
            )

            if featured_blogs:
                log_message(
                    "info",
                    "Successfully matched featured blogs:",
                    "featured_blogs",
                    "holder",
                )
                for i, blog in enumerate(featured_blogs):
                    log_message(
                        "info",
                        f"  {i+1}. '{blog.blog_title}' (Path: {getattr(blog, 'file_path', 'N/A')})",
                        "featured_blogs",
                        "holder",
                    )
            else:
                log_message(
                    "error",
                    "[WARNING] NO FEATURED BLOGS MATCHED! Please check the CSV file and blog titles.",
                    "featured_blogs",
                    "holder",
                )

            self.blogs_featured["featured"] = featured_blogs
            log_message(
                "info",
                f"Stored {len(featured_blogs)} featured blogs in blogs_featured['featured']",
                "featured_blogs",
                "holder",
            )

            log_message(
                "info",
                f"========== FEATURED BLOGS LOADING PROCESS COMPLETED ==========",
                "featured_blogs",
                "holder",
            )

            return featured_blogs

        except Exception as error:
            log_message(
                "error",
                f"ERROR in load_featured_blogs_from_csv: {error}",
                "featured_blogs",
                "holder",
            )
            log_message(
                "error",
                f"Traceback: {traceback.format_exc()}",
                "featured_blogs",
                "holder",
            )
            return []

    def get_featured_blogs(self) -> list[Blog]:
        """Get featured blogs."""

        if "featured" in self.blogs_featured:
            blog_count = len(self.blogs_featured["featured"])
            log_message("debug", f"Found {blog_count} featured blogs")
            return self.blogs_featured["featured"]

        log_message("debug", "No featured blogs found")
        return []

    def get_blogs_by_author(self, author: str) -> list[Blog]:
        """Get blogs by author."""

        if author in self.blogs_authors:
            blog_count = len(self.blogs_authors[author])
            log_message("debug", f"Found {blog_count} blogs by author: {author}")
            return self.blogs_authors[author]

        log_message("debug", f"No blogs found by author: {author}")
        return []

    def get_blogs_by_vertical(self, vertical: str) -> list[Blog]:
        """Get blogs by vertical."""

        if vertical in self.blogs_verticals:
            blog_count = len(self.blogs_verticals[vertical])
            log_message("debug", f"Found {blog_count} blogs in vertical: {vertical}")
            return self.blogs_verticals[vertical]

        log_message("debug", f"No blogs found in vertical: {vertical}")
        return []

    def get_blog_by_key(self, key: tuple[str, datetime]) -> Blog:
        """Get blog by key."""

        if key in self.blogs:
            log_message("debug", f"Found blog with key: {key}")
            return self.blogs[key]

        log_message("debug", f"No blog found with key: {key}")
        return None

    def get_vertical_category_blogs(self, category: str, vertical: str) -> list[Blog]:
        """Get blogs by vertical and category."""

        if (category, vertical) in self.blogs_categories_verticals:
            blog_count = len(self.blogs_categories_verticals[(category, vertical)])
            log_message(
                "debug",
                f"Found {blog_count} blogs in vertical-category: {category}, {vertical}",
            )
            return self.blogs_categories_verticals[(category, vertical)]

    def get_vertical_category_blog_keys(self) -> list[tuple[str, str]]:
        """Return vertical-category blog keys."""
        keys = list(self.blogs_categories_verticals.keys())
        log_message("debug", f"Returning {len(keys)} vertical-category keys")
        return keys

    def get_blogs(self) -> list[Blog]:
        """Return all blogs."""

        blog_count = len(self.blogs)
        log_message("debug", f"Returning {blog_count} blogs")
        return list(self.blogs.values())

    def clear_blogs(self) -> None:
        """Clear all blogs."""

        blog_count = len(self.blogs)

        log_message(
            "info",
            "Clearing {blog_count} blogs from the blog holder",
            "general",
            "holder",
        )
        self.blogs.clear()
        self.blogs_categories.clear()
        self.blogs_authors.clear()
        self.blogs_featured.clear()
        self.blogs_verticals.clear()
        self.blogs_categories_verticals.clear()
        log_message("debug", "Blog holder cleared")

    def sort_blogs_by_date(self, reverse: bool = True) -> list[Blog]:
        """Sort blogs by date."""

        log_message(
            "info",
            f"Sorting {len(self.blogs)} blogs by date (reverse={reverse})",
            "general",
            "holder",
        )

        self.blogs = dict(
            sorted(
                self.blogs.items(),
                key=lambda item: (
                    item[1].date if item[1].date is not None else datetime.min
                ),
                reverse=reverse,
            )
        )

        log_message("debug", "Blogs sorted by date")
        return list(self.blogs.values())

    def sort_categories_by_vertical(self, log_file_handle) -> list[Blog]:
        """Sort the categories by vertical."""

        for category in self.blogs_categories:
            for blog in self.blogs_categories[category]:
                if not hasattr(blog, "metadata") or not blog.metadata:
                    if log_file_handle:
                        log_file_handle.write("Blog has no metadata\n")
                    continue
                else:
                    blog_vertical_str = (
                        blog.metadata.get("myst").get("html_meta").get("vertical")
                    )
                    if blog_vertical_str is None:
                        if log_file_handle:
                            log_file_handle.write(
                                f"Blog '{blog.blog_title}' has no vertical metadata\n"
                            )
                        continue
                    blog_vertical = [
                        v.strip() for v in blog_vertical_str.split(",") if v.strip()
                    ]
                    for vertical in blog_vertical:
                        if (category, vertical) not in self.blogs_categories_verticals:
                            self.blogs_categories_verticals[(category, vertical)] = []
                            log_message(
                                "debug",
                                f"Initialized vertical-category: {category}, {vertical}",
                            )

                        self.blogs_categories_verticals[(category, vertical)].append(
                            blog
                        )
                        log_message(
                            "debug",
                            f"Blog '{blog.blog_title}' added to vertical-category '{category}', '{vertical}'",
                        )

        return list(self.blogs_categories_verticals.values())

    def sort_blogs_by_vertical(self) -> list[Blog]:
        """Sort blogs by market vertical."""

        self.blogs_verticals = {}

        for vertical in self.verticals:
            self.blogs_verticals[vertical] = []

            log_message("debug", f"Initialized vertical: {vertical}")

        if is_logging_enabled_from_config():
            logs_directory = Path("logs")
            logs_directory.mkdir(exist_ok=True)

            log_filepath = logs_directory / "blogs_vertical.log"
            log_file_handle = open(log_filepath, "w", encoding="utf-8")
        else:
            log_file_handle = None

        try:
            vertical_counts = {}
            for blog in self.blogs.values():
                if log_file_handle:
                    log_file_handle.write(f"Blog: {blog}\n")
                    log_file_handle.write(f"Metadata: {blog.grab_metadata()}\n")

                if not hasattr(blog, "metadata") or not blog.metadata:
                    if log_file_handle:
                        log_file_handle.write("Blog has no metadata\n")
                    continue
                else:
                    myst_section = blog.metadata.get("myst", {})
                    html_meta = myst_section.get("html_meta", {})
                    blog_vertical_str = html_meta.get("vertical")

                    if log_file_handle:
                        log_file_handle.write(f"myst section: {myst_section}\n")
                        log_file_handle.write(f"html_meta section: {html_meta}\n")
                        log_file_handle.write(f"vertical value: {blog_vertical_str}\n")

                    if blog_vertical_str is None:
                        if log_file_handle:
                            log_file_handle.write(
                                f"Blog '{getattr(blog, 'blog_title', 'Unknown')}' has no vertical metadata\n"
                            )
                        continue
                    blog_vertical = [
                        v.strip() for v in blog_vertical_str.split(",") if v.strip()
                    ]
                    for vertical in blog_vertical:
                        if vertical not in self.blogs_verticals:
                            if log_file_handle:
                                log_file_handle.write(
                                    f"Vertical '{vertical}' not recognized\n"
                                )
                            continue
                        if vertical not in vertical_counts:
                            vertical_counts[vertical] = 0
                        vertical_counts[vertical] += 1
                        self.blogs_verticals[vertical].append(blog)
                        if log_file_handle:
                            log_file_handle.write(
                                f"Blog '{blog.blog_title}' added to vertical '{vertical}'\n"
                            )

            if log_file_handle:
                log_file_handle.write("\nVertical counts:\n")
                for vertical, count in vertical_counts.items():
                    log_file_handle.write(f"{vertical}: {count} blogs\n")
                    log_message(
                        "info",
                        "Vertical '{vertical}' has {count} blogs",
                        "general",
                        "holder",
                    )

                log_file_handle.write("\nBlogs in each vertical:\n")
                for vertical, blogs in self.blogs_verticals.items():
                    log_file_handle.write(f"{vertical}:\n")
                    for blog in blogs:
                        log_file_handle.write(f"  - {blog.blog_title}\n")
                        log_message(
                            "info",
                            "Blog '{blog.blog_title}' belongs to vertical '{vertical}'",
                            "general",
                            "holder",
                        )
                    if not blogs:
                        log_file_handle.write(f"  - No blogs in this vertical\n")
                        log_message("warning", f"Vertical '{vertical}' has no blogs")

        finally:
            if log_file_handle:
                log_file_handle.close()

    def sort_blogs_by_category(self, categories) -> list[Blog]:
        """Sort the blogs by category."""

        log_message(
            "info",
            f"Sorting {len(self.blogs)} blogs into {len(categories)} categories",
            "general",
            "holder",
        )

        self.blogs_categories = {}

        for category in categories:
            self.blogs_categories[category] = []
            log_message("debug", f"Initialized category: {category}")

        category_counts = {}
        for blog in self.blogs.values():
            if blog.category in categories:
                self.blogs_categories[blog.category].append(blog)
                category_counts[blog.category] = (
                    category_counts.get(blog.category, 0) + 1
                )

        for category, count in category_counts.items():
            log_message(
                "info", "Category '{category}' has {count} blogs", "general", "holder"
            )

        for category in categories:
            if category not in category_counts:
                log_message("warning", f"Category '{category}' has no blogs")

    def get_latest_blogs(self, count: int = 15) -> list[Blog]:
        """Get the latest blogs based on the count."""

        available_count = min(count, len(self.blogs))
        log_message(
            "debug", f"Getting {available_count} latest blogs (requested: {count})"
        )
        return list(self.blogs.values())[:available_count]

    def get_blog_by_title(self, title: str) -> Blog:
        """Get a blog by its title with detailed logging."""

        log_message(
            "debug",
            f"========== SEARCHING FOR BLOG: '{title}' ==========",
            "blog_search",
            "holder",
        )

        log_message(
            "debug",
            f"Step 1: Attempting exact match for: '{title}'",
            "blog_search",
            "holder",
        )
        exact_matches = 0
        for blog in self.blogs.values():
            if hasattr(blog, "blog_title") and blog.blog_title == title:
                exact_matches += 1
                log_message(
                    "info",
                    f"[SUCCESS] EXACT MATCH FOUND: '{title}' -> '{blog.blog_title}'",
                    "blog_search",
                    "holder",
                )
                return blog

        log_message(
            "debug", f"Exact matches found: {exact_matches}", "blog_search", "holder"
        )

        log_message(
            "debug",
            f"Step 2: Attempting case-insensitive match for: '{title}'",
            "blog_search",
            "holder",
        )
        title_lower = title.lower()
        case_insensitive_matches = 0
        for blog in self.blogs.values():
            if hasattr(blog, "blog_title") and blog.blog_title.lower() == title_lower:
                case_insensitive_matches += 1
                log_message(
                    "info",
                    f"[SUCCESS] CASE-INSENSITIVE MATCH FOUND: '{title}' -> '{blog.blog_title}'",
                    "blog_search",
                    "holder",
                )
                return blog

        log_message(
            "debug",
            f"Case-insensitive matches found: {case_insensitive_matches}",
            "blog_search",
            "holder",
        )

        def normalize_title(t):
            if not t:
                return ""

            log_message("debug", f"Normalizing title: '{t}'", "blog_search", "holder")
            original = t

            t = t.replace("™", "™")
            t = t.replace("\u202f", " ")
            t = t.replace("\u00a0", " ")
            t = t.replace("\u2009", " ")

            t = " ".join(t.split())
            for char in [
                ",",
                ".",
                ":",
                ";",
                "!",
                "?",
                '"',
                "'",
                "(",
                ")",
                "[",
                "]",
                "{",
                "}",
            ]:
                t = t.replace(char, "")

            result = t.lower().strip()

            if original != result:
                log_message(
                    "debug",
                    f"Title normalized: '{original}' -> '{result}'",
                    "blog_search",
                    "holder",
                )
            else:
                log_message(
                    "debug",
                    f"No normalization needed for: '{original}'",
                    "blog_search",
                    "holder",
                )

            return result

        log_message(
            "debug",
            f"Step 3: Attempting normalized match for: '{title}'",
            "blog_search",
            "holder",
        )
        normalized_title = normalize_title(title)
        normalized_matches = 0

        for blog in self.blogs.values():
            if hasattr(blog, "blog_title"):
                normalized_blog_title = normalize_title(blog.blog_title)
                log_message(
                    "debug",
                    f"Comparing normalized: '{normalized_title}' vs '{normalized_blog_title}'",
                    "blog_search",
                    "holder",
                )

                if normalized_blog_title == normalized_title:
                    normalized_matches += 1
                    log_message(
                        "info",
                        f"[SUCCESS] NORMALIZED MATCH FOUND: '{title}' -> '{blog.blog_title}' (normalized: '{normalized_title}')",
                        "blog_search",
                        "holder",
                    )
                    return blog

        log_message(
            "debug",
            f"Normalized matches found: {normalized_matches}",
            "blog_search",
            "holder",
        )

        log_message(
            "warning",
            f"[FAILED] NO BLOG FOUND for title: '{title}' (Exact: {exact_matches}, Case-insensitive: {case_insensitive_matches}, Normalized: {normalized_matches})",
            "blog_search",
            "holder",
        )

        available_titles = [
            blog.blog_title
            for blog in self.blogs.values()
            if hasattr(blog, "blog_title") and blog.blog_title
        ]
        log_message(
            "debug",
            f"Available blog titles ({len(available_titles)}): {available_titles[:10]}{'...' if len(available_titles) > 10 else ''}",
            "blog_search",
            "holder",
        )

        return None

    def get_blogs_by_category(self, category: str) -> list[Blog]:
        """Get blogs by category."""

        if category in self.blogs_categories:
            blog_count = len(self.blogs_categories[category])
            log_message("debug", f"Found {blog_count} blogs in category: {category}")
            return self.blogs_categories[category]

        log_message("debug", f"No blogs found in category: {category}")
        return []

    def __iter__(self) -> iter:
        """Iterate over the list of blogs."""

        return iter(self.blogs.values())

    def __len__(self) -> int:
        """Return the number of blogs."""

        return len(self.blogs)

    def get_duplicate_statistics(self) -> Dict[str, int]:
        """Get statistics about duplicate detection."""
        stats = {
            "total_blogs": len(self.blogs),
            "duplicate_attempts": self._duplicate_count,
            "unique_paths": len(self._seen_paths),
            "unique_titles": len(self._seen_titles),
        }

        log_message(
            "info",
            f"Duplicate Statistics - Total: {stats['total_blogs']}, Duplicates rejected: {stats['duplicate_attempts']}",
            "general",
            "holder",
        )

        return stats

    def find_potential_duplicates(self) -> List[Tuple[str, str, Blog, Blog]]:
        """Find blogs that might be duplicates based on similar titles or paths."""
        potential_duplicates = []
        blogs_list = list(self.blogs.values())

        for i, blog1 in enumerate(blogs_list):
            for blog2 in blogs_list[i + 1 :]:
                if hasattr(blog1, "blog_title") and hasattr(blog2, "blog_title"):
                    title1 = self._normalize_title(blog1.blog_title)
                    title2 = self._normalize_title(blog2.blog_title)

                    if title1 == title2:
                        potential_duplicates.append(
                            ("title_match", f"Title: {blog1.blog_title}", blog1, blog2)
                        )
                    elif title1 and title2:
                        if title1 in title2 or title2 in title1:
                            potential_duplicates.append(
                                (
                                    "title_similar",
                                    f"Titles: {blog1.blog_title} vs {blog2.blog_title}",
                                    blog1,
                                    blog2,
                                )
                            )

                if hasattr(blog1, "file_path") and hasattr(blog2, "file_path"):
                    file1 = os.path.basename(blog1.file_path).lower()
                    file2 = os.path.basename(blog2.file_path).lower()

                    if file1 == file2 and blog1.file_path != blog2.file_path:
                        potential_duplicates.append(
                            (
                                "filename_match",
                                f"Files: {blog1.file_path} vs {blog2.file_path}",
                                blog1,
                                blog2,
                            )
                        )

        if potential_duplicates:
            log_message(
                "warning",
                f"Found {len(potential_duplicates)} potential duplicate pairs",
                "general",
                "holder",
            )

        return potential_duplicates

    def __repr__(self) -> str:
        """Return a string representation of the class."""

        return f"BlogHolder(blogs={self.blogs})"
