"""
__init__.py for the rocm_blogs package.

"""

import functools
import importlib.resources as pkg_resources
import json
import os
import pathlib
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from jinja2 import Template
from sphinx.application import Sphinx
from sphinx.errors import SphinxError
from sphinx.util import logging as sphinx_logging
from .process import (_create_pagination_controls, _generate_grid_items,
                      _generate_lazy_loaded_grid_items, _process_category,
                      process_single_blog)

sphinx_diagnostics = sphinx_logging.getLogger(__name__)

try:
    from rocm_blogs_logging import *

    LOGGING_AVAILABLE = True
    PROFILING_AVAILABLE = True
except ImportError:
    # Fallback if logging package is not available
    LOGGING_AVAILABLE = False
    PROFILING_AVAILABLE = False
    get_logger = lambda *args, **kwargs: None
    configure_logging = lambda *args, **kwargs: None
    log_operation = lambda *args, **kwargs: lambda func: func
    is_logging_enabled = lambda: False
    profile_operation = lambda *args, **kwargs: lambda func: func
    profile_function = lambda *args, **kwargs: lambda func: func
    get_profiler = lambda *args, **kwargs: None

    class LogLevel:
        DEBUG = "DEBUG"
        INFO = "INFO"
        WARNING = "WARNING"
        ERROR = "ERROR"
        CRITICAL = "CRITICAL"

    class LogCategory:
        SYSTEM = "system"
        PERFORMANCE = "performance"


from ._rocmblogs import ROCmBlogs
from ._version import __version__
from .banner import *
from .constants import *
from .images import *
from .logger.logger import *
from .metadata import *
from .process import *
from .project.project_info import append_to_universal_log, log_project_info
from .utils import *

__all__ = [
    "Blog",
    "BlogHolder",
    "ROCmBlogs",
    "grid_generation",
    "metadata_generator",
    "utils",
]


structured_logger = None
if LOGGING_AVAILABLE and is_logging_enabled():
    try:
        log_file_path = Path("logs/rocm_blogs.log")
        structured_logger = configure_logging(
            level=LogLevel.INFO,
            log_file=log_file_path,
            enable_console=True,
            name="rocm_blogs",
        )
        if structured_logger:
            structured_logger.info(
                "Structured logging system initialized",
                "initialization",
                "logging_system",
                extra_data={"log_file": str(log_file_path)},
            )
    except Exception as logging_error:
        print(f"Failed to initialize structured logging: {logging_error}")
        structured_logger = None


_CRITICAL_ERROR_OCCURRED = False

_BUILD_START_TIME = time.time()

_BUILD_PHASES = {"setup": 0, "update_index": 0, "blog_generation": 0, "other": 0}


def log_total_build_time(sphinx_app, build_exception):
    """Log the total time taken for the entire build process."""
    try:
        global _CRITICAL_ERROR_OCCURRED

        build_end_time = time.time()
        total_elapsed_time = build_end_time - _BUILD_START_TIME

        accounted_time = sum(_BUILD_PHASES.values())
        _BUILD_PHASES["other"] = max(0, total_elapsed_time - accounted_time)

        # Format and log the timing summary
        _log_timing_summary(total_elapsed_time)

        if build_exception:
            log_message(
                "error",
                f"Build completed with errors: {build_exception}",
                "build_process",
                "log_total_build_time",
            )

        if _CRITICAL_ERROR_OCCURRED:
            log_message(
                "critical",
                "Critical errors occurred during the build process",
                "build_process",
                "log_total_build_time",
            )
            raise ROCmBlogsError("Critical errors occurred during the build process")
    except Exception as error:
        log_message(
            "critical",
            f"Error in log_total_build_time: {error}",
            "build_process",
            "log_total_build_time",
        )
        log_message(
            "debug",
            f"Traceback: {traceback.format_exc()}",
            "build_process",
            "log_total_build_time",
        )
        raise


def _create_build_timing_summary_file(total_elapsed_time, phases_to_display):
    """Create a detailed build timing summary file."""
    try:
        if not is_logging_enabled_from_config():
            return

        logs_dir = Path("logs")
        logs_dir.mkdir(exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        summary_file = logs_dir / f"build_timing_summary_{timestamp}.txt"

        with open(summary_file, "w", encoding="utf-8") as f:
            f.write("=" * 80 + "\n")
            f.write("ROCm Blogs Build Process Timing Summary\n")
            f.write("=" * 80 + "\n\n")

            f.write(
                f"Build completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            )
            f.write(f"Total build time: {total_elapsed_time:.2f} seconds\n\n")

            f.write("Phase Breakdown:\n")
            f.write("-" * 50 + "\n")

            for phase_key, phase_display_name in phases_to_display:
                if phase_key in _BUILD_PHASES:
                    phase_duration = _BUILD_PHASES[phase_key]
                    percentage = (
                        (phase_duration / total_elapsed_time * 100)
                        if total_elapsed_time > 0
                        else 0
                    )
                    padded_name = f"{phase_display_name}:".ljust(30)
                    f.write(
                        f"{padded_name} {phase_duration:.2f} seconds ({percentage:.1f}%)\n"
                    )

            # Write summary statistics
            f.write("\n" + "-" * 50 + "\n")
            f.write("Summary Statistics:\n")
            f.write("-" * 50 + "\n")

            # Calculate some basic statistics
            phase_times = [
                _BUILD_PHASES.get(phase_key, 0)
                for phase_key, _ in phases_to_display
                if phase_key in _BUILD_PHASES
            ]
            if phase_times:
                f.write(f"Fastest phase: {min(phase_times):.2f} seconds\n")
                f.write(f"Slowest phase: {max(phase_times):.2f} seconds\n")
                f.write(
                    f"Average phase time: {sum(phase_times) / len(phase_times):.2f} seconds\n"
                )

            # Write detailed phase data in JSON format for potential analysis
            f.write("\n" + "-" * 50 + "\n")
            f.write("Detailed Phase Data (JSON):\n")
            f.write("-" * 50 + "\n")

            phase_data = {
                "total_build_time": total_elapsed_time,
                "build_timestamp": datetime.now().isoformat(),
                "phases": {},
            }

            for phase_key, phase_display_name in phases_to_display:
                if phase_key in _BUILD_PHASES:
                    phase_duration = _BUILD_PHASES[phase_key]
                    percentage = (
                        (phase_duration / total_elapsed_time * 100)
                        if total_elapsed_time > 0
                        else 0
                    )
                    phase_data["phases"][phase_key] = {
                        "name": phase_display_name,
                        "duration_seconds": phase_duration,
                        "percentage": percentage,
                    }

            f.write(json.dumps(phase_data, indent=2))
            f.write("\n\n" + "=" * 80 + "\n")

        log_message(
            "info",
            f"Build timing summary saved to: {summary_file}",
            "timing_summary",
            "build_process",
            extra_data={"summary_file": str(summary_file)},
        )

    except Exception as error:
        log_message(
            "error",
            f"Error creating build timing summary file: {error}",
            "timing_summary",
            "build_process",
            error=error,
        )


def _log_timing_summary(total_elapsed_time):
    """Format and log the timing summary for all build phases."""
    try:
        # Define the phases to display and their display names
        phases_to_display = [
            ("setup", "Setup phase"),
            ("update_index", "Index update phase"),
            ("blog_generation", "Blog generation phase"),
            ("metadata_generation", "Metadata generation"),
            ("update_posts", "Posts generation"),
            ("update_category_pages", "Category pages generation"),
            ("other", "Other processing"),
        ]

        _create_build_timing_summary_file(total_elapsed_time, phases_to_display)

        log_message("info", "=" * 80, "timing_summary", "build_process")
        log_message(
            "info", "BUILD PROCESS TIMING SUMMARY:", "timing_summary", "build_process"
        )
        log_message("info", "-" * 80, "timing_summary", "build_process")

        for phase_key, phase_display_name in phases_to_display:
            if phase_key in _BUILD_PHASES:
                phase_duration = _BUILD_PHASES[phase_key]
                percentage = (
                    (phase_duration / total_elapsed_time * 100)
                    if total_elapsed_time > 0
                    else 0
                )
                padded_name = f"{phase_display_name}:".ljust(30)
                log_message(
                    "info",
                    f"{padded_name} \033[96m{phase_duration:.2f} seconds\033[0m ({percentage:.1f}%)",
                    "timing_summary",
                    "build_process",
                )

        log_message("info", "-" * 80, "timing_summary", "build_process")
        log_message(
            "info",
            f"Total build process completed in \033[92m{total_elapsed_time:.2f} seconds\033[0m",
            "timing_summary",
            "build_process",
        )
        log_message("info", "=" * 80, "timing_summary", "build_process")
    except Exception as error:
        log_message(
            "error",
            f"Error logging timing summary: {error}",
            "timing_summary",
            "build_process",
        )
        log_message(
            "debug",
            f"Traceback: {traceback.format_exc()}",
            "timing_summary",
            "build_process",
        )


def log_time(func):
    """Decorator to log execution time of functions."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            function_start_time = time.time()
            result = func(*args, **kwargs)
            execution_time = time.time() - function_start_time
            log_message(
                "info",
                "{func.__name__} completed in \033[96m{execution_time:.4f} seconds\033[0m",
                "general",
                "__init__",
            )
            return result
        except Exception as error:
            log_message(
                "error", f"Error in {func.__name__}: {error}", "general", "__init__"
            )
            log_message(
                "debug", f"Traceback: {traceback.format_exc()}", "general", "__init__"
            )
            raise

    return wrapper


def update_author_files(sphinx_app: Sphinx, rocm_blogs: ROCmBlogs) -> None:
    """Update author files with blog information."""

    global _CRITICAL_ERROR_OCCURRED
    phase_start_time = time.time()
    phase_name = "update_author_files"

    # find author files

    rocm_blogs.find_author_files()
    rocm_blogs.blogs.blogs_authors

    log_filepath, log_file_handle = create_step_log_file(phase_name)

    safe_log_write(log_file_handle, f"Starting {phase_name} process\n")

    for blog in rocm_blogs.blogs.get_blogs():
        safe_log_write(log_file_handle, f"Blog: {blog}\n")

    log_message(
        "info",
        "Author files to be updated: {rocm_blogs.author_paths}",
        "general",
        "__init__",
    )

    log_message(
        "info", "Authors found: {rocm_blogs.blogs.blogs_authors}", "general", "__init__"
    )

    for author in rocm_blogs.blogs.blogs_authors:
        log_message("info", f"Processing author: {author}", "general", "__init__")

        # COMPREHENSIVE AUTHOR DEBUGGING - START
        safe_log_write(log_file_handle, f"\n" + "=" * 80 + "\n")
        safe_log_write(
            log_file_handle, f"Preparing grid generation for author [{author}]\n"
        )
        safe_log_write(log_file_handle, f"=" * 80 + "\n")

        name = "-".join(author.split(" ")).lower()

        author_file_path = Path(rocm_blogs.blogs_directory) / f"authors/{name}.md"

        if not author_file_path.exists():
            log_message(
                "warning",
                f"Author file not found: {author_file_path}",
                "general",
                "__init__",
            )
            safe_log_write(
                log_file_handle, f"WARNING: Author file not found: {author_file_path}\n"
            )
        else:
            log_message(
                "info",
                "Updating author file: {author_file_path}",
                "general",
                "__init__",
            )
            safe_log_write(
                log_file_handle, f"Updating author file: {author_file_path}\n"
            )

            with author_file_path.open("r", encoding="utf-8") as author_file:
                author_content = author_file.read()

            # Get all blogs by author and filter to only include actual blog posts
            all_author_blogs = rocm_blogs.blogs.get_blogs_by_author(author)
            author_blogs = []
            skipped_count = 0

            author_thumbnail_url, metadata_end_position = extract_author_metadata(
                author_content, rocm_blogs.blogs_directory, author, log_file_handle
            )

            for blog in all_author_blogs:
                # Check if this is a genuine blog post (has the blogpost flag set to true)
                if hasattr(blog, "blogpost") and blog.blogpost:
                    author_blogs.append(blog)
                    safe_log_write(
                        log_file_handle,
                        f"Including blog for author [{author}]: {getattr(blog, 'file_path', 'Unknown')}\n",
                    )
                else:
                    skipped_count += 1
                    safe_log_write(
                        log_file_handle,
                        f"Skipping non-blog README file for author [{author}]: {getattr(blog, 'file_path', 'Unknown')}\n",
                    )

            log_message(
                "info",
                f"Filtered out {skipped_count} non-blog README files for author [{author}], kept {len(author_blogs)} genuine blog posts",
                "general",
                "__init__",
            )
            safe_log_write(
                log_file_handle,
                f"Filtered out {skipped_count} non-blog README files for author [{author}], kept {len(author_blogs)} genuine blog posts\n",
            )

            # Log the blogs for this author
            blog_titles = [
                getattr(blog, "blog_title", "Unknown Title") for blog in author_blogs
            ]
            safe_log_write(
                log_file_handle, f"[{author}] has these blogs: {blog_titles}\n"
            )
            safe_log_write(
                log_file_handle,
                f"Total blog count for [{author}]: {len(author_blogs)}\n\n",
            )

            author_blogs.sort(key=lambda x: x.date, reverse=True)

            # DETAILED BLOG OBJECT INSPECTION
            safe_log_write(
                log_file_handle, f"DETAILED BLOG INSPECTION FOR AUTHOR [{author}]:\n"
            )
            safe_log_write(log_file_handle, f"-" * 80 + "\n")

            for i, blog in enumerate(author_blogs):
                safe_log_write(log_file_handle, f"\nBLOG #{i+1} DETAILED INSPECTION:\n")
                safe_log_write(
                    log_file_handle,
                    f"Blog Title: {getattr(blog, 'blog_title', 'NO TITLE')}\n",
                )
                safe_log_write(
                    log_file_handle,
                    f"File Path: {getattr(blog, 'file_path', 'NO FILE PATH')}\n",
                )

                # Print ALL attributes of the blog object
                safe_log_write(log_file_handle, f"\nALL BLOG ATTRIBUTES:\n")
                for attr_name in dir(blog):
                    if not attr_name.startswith("_"):  # Skip private attributes
                        try:
                            attr_value = getattr(blog, attr_name)
                            if not callable(attr_value):  # Skip methods
                                safe_log_write(
                                    log_file_handle,
                                    f"  {attr_name}: {repr(attr_value)}\n",
                                )
                        except Exception as attr_error:
                            safe_log_write(
                                log_file_handle,
                                f"  {attr_name}: ERROR - {attr_error}\n",
                            )

                # Print the complete metadata structure
                safe_log_write(log_file_handle, f"\nCOMPLETE METADATA STRUCTURE:\n")
                if hasattr(blog, "metadata") and blog.metadata:
                    try:
                        import json

                        metadata_json = json.dumps(blog.metadata, indent=4, default=str)
                        safe_log_write(log_file_handle, f"{metadata_json}\n")
                    except Exception as json_error:
                        safe_log_write(
                            log_file_handle,
                            f"ERROR serializing metadata: {json_error}\n",
                        )
                        safe_log_write(
                            log_file_handle, f"Raw metadata: {repr(blog.metadata)}\n"
                        )
                else:
                    safe_log_write(log_file_handle, f"NO METADATA FOUND\n")

                # Test the OpenGraph functions directly
                safe_log_write(log_file_handle, f"\nTESTING OPENGRAPH FUNCTIONS:\n")
                try:
                    og_image = blog.grab_og_image()
                    safe_log_write(
                        log_file_handle, f"grab_og_image() returned: {og_image}\n"
                    )
                except Exception as og_image_error:
                    safe_log_write(
                        log_file_handle, f"grab_og_image() ERROR: {og_image_error}\n"
                    )

                try:
                    og_href = blog.grab_og_href()
                    safe_log_write(
                        log_file_handle, f"grab_og_href() returned: {og_href}\n"
                    )
                except Exception as og_href_error:
                    safe_log_write(
                        log_file_handle, f"grab_og_href() ERROR: {og_href_error}\n"
                    )

                try:
                    og_description = blog.grab_og_description()
                    safe_log_write(
                        log_file_handle,
                        f"grab_og_description() returned: {og_description[:100]}...\n",
                    )
                except Exception as og_desc_error:
                    safe_log_write(
                        log_file_handle,
                        f"grab_og_description() ERROR: {og_desc_error}\n",
                    )

                safe_log_write(log_file_handle, f"\n" + "-" * 60 + "\n")

            safe_log_write(
                log_file_handle,
                f"\nCalling _generate_grid_items with use_og=True for author [{author}]\n",
            )
            safe_log_write(log_file_handle, f"=" * 80 + "\n\n")

            author_grid_items = _generate_grid_items(
                rocm_blogs, author_blogs, 999, [], False, True
            )

            # copy all blog images to authors/images directory
            for blog in author_blogs:
                blog_images = blog.image_paths
                for image in blog_images:
                    image_path = Path(image)
                    if image_path.exists():
                        destination_path = (
                            Path(rocm_blogs.blogs_directory) / f"authors/images/{image}"
                        )
                        destination_path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy(image_path, destination_path)
            try:
                log_message(
                    "info",
                    "Generating grid items for author: {author}",
                    "general",
                    "__init__",
                )

                author_image_html = ""
                if author_thumbnail_url:
                    author_image_html = f"""
<div class="author-image-container">
    <picture>
        <img
            src="{author_thumbnail_url}"
            class="author-thumbnail-img"
            alt="{author}"
            decoding="async"
            loading="eager"
            onerror="this.onerror=null; this.classList.add('image-error'); console.warn('Author image failed:', this.src);"
        >
    </picture>
    <noscript>
        <img src="{author_thumbnail_url}" alt="{author}" class="author-thumbnail-img" loading="eager">
    </noscript>
</div>
"""

                author_css = import_file("rocm_blogs.static.css", "index.css")
                author_page_css = import_file("rocm_blogs.static.css", "author.css")
                combined_css = author_css + "\n\n" + author_page_css

                if author_image_html:
                    if metadata_end_position > 0:
                        before_metadata = author_content[:metadata_end_position]
                        after_metadata = author_content[metadata_end_position:]
                        author_content = (
                            before_metadata
                            + "\n"
                            + author_image_html
                            + "\n"
                            + after_metadata
                        )
                    else:
                        author_content = author_image_html + "\n\n" + author_content

                author_content = author_content + "\n" + AUTHOR_TEMPLATE

                updated_author_content = (
                    author_content.replace("{author_blogs}", "".join(author_grid_items))
                    .replace("{author}", author)
                    .replace("{author_css}", combined_css)
                    .replace("{author_image_html}", "")
                )
                if "{author_blogs}" in updated_author_content:
                    log_message(
                        "warning",
                        f"Error: replacement failed for {author_file_path}",
                        "general",
                        "__init__",
                    )
                else:
                    log_message(
                        "info",
                        "Successfully updated author file: {author_file_path}",
                        "general",
                        "__init__",
                    )
            except Exception as error:
                log_message(
                    "error",
                    f"Error processing author file: {error}",
                    "general",
                    "__init__",
                )
                log_message(
                    "debug",
                    f"Traceback: {traceback.format_exc()}",
                    "general",
                    "__init__",
                )
                _CRITICAL_ERROR_OCCURRED = True
                raise ROCmBlogsError(f"Error processing author file: {error}")

            with author_file_path.open("w", encoding="utf-8") as author_file:
                author_file.write(updated_author_content)

                if author_content != updated_author_content:
                    log_message(
                        "info",
                        "Author file updated successfully: {author_file_path}",
                        "general",
                        "__init__",
                    )
                else:
                    log_message(
                        "warning",
                        f"Author file content unchanged: {author_file_path}",
                        "general",
                        "__init__",
                    )


def blog_statistics(sphinx_app: Sphinx, rocm_blogs: ROCmBlogs) -> None:
    """Generate statistics page with blog author and category information."""
    global _CRITICAL_ERROR_OCCURRED
    phase_start_time = time.time()
    phase_name = "blog_statistics"

    # Create a log file for this step
    log_filepath, log_file_handle = create_step_log_file(phase_name)

    try:
        if log_file_handle:
            safe_log_write(
                log_file_handle, "Starting blog statistics generation process\n"
            )
            safe_log_write(log_file_handle, "-" * 80 + "\n\n")

        log_message("info", "Generating blog statistics page...", "general", "__init__")

        # Load templates and styles
        blog_statistics_css = import_file(
            "rocm_blogs.static.css", "blog_statistics.css"
        )
        blog_statistics_template = import_file(
            "rocm_blogs.templates", "blog_statistics_template.html"
        )

        if log_file_handle:
            safe_log_write(
                log_file_handle, "Successfully loaded templates and styles\n"
            )

        # Get all blogs
        all_blogs = rocm_blogs.blogs.get_blogs()

        if log_file_handle:
            safe_log_write(log_file_handle, f"Retrieved {len(all_blogs)} total blogs\n")

        # Filter blogs to only include real blog posts
        filtered_blogs = []
        skipped_count = 0

        for blog in all_blogs:
            # Check if this is a genuine blog post (has the blogpost flag set
            # to true)
            if hasattr(blog, "blogpost") and blog.blogpost:
                filtered_blogs.append(blog)
                if log_file_handle:
                    safe_log_write(
                        log_file_handle,
                        f"Including blog: {getattr(blog, 'file_path', 'Unknown')}\n",
                    )
            else:
                skipped_count += 1
                log_message(
                    "debug",
                    f"Skipping non-blog README file for statistics page: {getattr(blog, 'file_path', 'Unknown')}",
                    "general",
                    "__init__",
                )
                if log_file_handle:
                    safe_log_write(
                        log_file_handle,
                        f"Skipping non-blog README file: {getattr(blog, 'file_path', 'Unknown')}\n",
                    )

        log_message(
            "info",
            f"Filtered out {skipped_count} non-blog README files for statistics page, kept {len(filtered_blogs)} genuine blog posts",
            "general",
            "__init__",
        )

        if log_file_handle:
            safe_log_write(
                log_file_handle,
                f"Filtered out {skipped_count} non-blog README files, kept {len(filtered_blogs)} genuine blog posts\n",
            )

        # Replace all_blogs with filtered_blogs
        all_blogs = filtered_blogs

        if not all_blogs:
            warning_message = "No valid blogs found to generate statistics"
            log_message("warning", warning_message, "general", "__init__")

            if log_file_handle:
                safe_log_write(log_file_handle, f"WARNING: {warning_message}\n")
            return

        # Generate author statistics
        author_stats = []

        if log_file_handle:
            safe_log_write(log_file_handle, "Generating author statistics\n")

        for author, blogs in rocm_blogs.blogs.blogs_authors.items():
            # Filter to only include genuine blog posts with blogpost flag
            genuine_blogs = [
                blog for blog in blogs if hasattr(blog, "blogpost") and blog.blogpost
            ]

            if not genuine_blogs:
                log_message(
                    "info",
                    f"No genuine blog posts found for author: {author} (had {len(blogs)} non-blog READMEs)",
                    "general",
                    "__init__",
                )
                if log_file_handle:
                    safe_log_write(
                        log_file_handle,
                        f"INFO: No genuine blog posts found for author: {author} (had {len(blogs)} non-blog READMEs)\n",
                    )
                continue
            sorted_blogs = sorted(
                genuine_blogs,
                key=lambda b: b.date if b.date else datetime.min,
                reverse=True,
            )

            # Get latest and first blog
            latest_blog = sorted_blogs[0] if sorted_blogs else None
            first_blog = sorted_blogs[-1] if sorted_blogs else None

            if author == "No author":
                author = "ROCm Blogs Team"

            safe_log_write(log_file_handle, f"Processing author: {author}\n")

            # check if author has a page
            if pathlib.Path.exists(
                Path(rocm_blogs.blogs_directory)
                / f"authors/{author.replace(' ', '-').lower()}.md"
            ):
                author_link = f"https://rocm.blogs.amd.com/authors/{author.replace(' ', '-').lower()}.html"
            else:
                author_link = "None"

            safe_log_write(log_file_handle, f"Author link: {author_link}\n")

            # Create author statistics

            author_stat = {
                "name": {
                    "name": author,
                    "href": author_link.format(author=author.replace(" ", "-").lower()),
                },
                "blog_count": len(genuine_blogs),
                "latest_blog": {
                    "title": latest_blog.blog_title if latest_blog else "N/A",
                    "date": (
                        latest_blog.date.strftime("%B %d, %Y")
                        if latest_blog and latest_blog.date
                        else "N/A"
                    ),
                    "href": latest_blog.grab_og_href() if latest_blog else "#",
                },
                "first_blog": {
                    "title": first_blog.blog_title if first_blog else "N/A",
                    "date": (
                        first_blog.date.strftime("%B %d, %Y")
                        if first_blog and first_blog.date
                        else "N/A"
                    ),
                    "href": first_blog.grab_og_href() if first_blog else "#",
                },
            }

            if author_link == "None":
                author_stat["name"]["href"] = ""

            author_stats.append(author_stat)

        # Sort authors by blog count (descending)
        author_stats.sort(key=lambda x: x["blog_count"], reverse=True)

        if log_file_handle:
            safe_log_write(
                log_file_handle,
                f"Generated statistics for {len(author_stats)} authors\n",
            )

        # Generate author table rows
        author_rows = []

        for author_stat in author_stats:
            author_name = author_stat["name"]
            blog_count = author_stat["blog_count"]
            latest_blog = author_stat["latest_blog"]
            first_blog = author_stat["first_blog"]

            # Create author name cell

            if author_name["href"]:
                author_cell = f'<td class="author"><a href="{author_name["href"]}">{author_name["name"]}</a></td>'
            else:
                author_cell = f'<td class="author">{author_name["name"]}</td>'

            blog_count_cell = f'<td class="blog-count">{blog_count}</td>'

            latest_blog_cell = f'<td class="date"><a href="{latest_blog["href"]}" class="blog-title">{latest_blog["title"]}</a><br><span class="date-text">{latest_blog["date"]}</span></td>'

            first_blog_cell = f'<td class="date"><a href="{first_blog["href"]}" class="blog-title">{first_blog["title"]}</a><br><span class="date-text">{first_blog["date"]}</span></td>'

            # Combine cells into a row
            row = f"<tr>{author_cell}{blog_count_cell}{latest_blog_cell}{first_blog_cell}</tr>"
            author_rows.append(row)

        if log_file_handle:
            safe_log_write(
                log_file_handle, f"Generated {len(author_rows)} author table rows\n"
            )

        # Generate monthly blog data
        if log_file_handle:
            safe_log_write(log_file_handle, "Generating monthly blog data\n")

        # Count blogs by month
        monthly_counts = {}

        for blog in all_blogs:
            if hasattr(blog, "date") and blog.date:
                month_key = blog.date.strftime("%Y-%m")
                monthly_counts[month_key] = monthly_counts.get(month_key, 0) + 1

        # Get all months of data
        sorted_months = sorted(monthly_counts.keys())

        # Format month labels
        monthly_labels = [
            datetime.strptime(month, "%Y-%m").strftime("%b %Y")
            for month in sorted_months
        ]
        monthly_data = [monthly_counts[month] for month in sorted_months]

        monthly_blog_data = {"labels": monthly_labels, "data": monthly_data}

        if log_file_handle:
            safe_log_write(
                log_file_handle,
                f"Generated monthly blog data with {len(monthly_blog_data['labels'])} months\n",
            )

        # Generate category distribution data
        if log_file_handle:
            safe_log_write(log_file_handle, "Generating category distribution data\n")

        # Count blogs by category
        category_counts = {}

        for blog in all_blogs:
            if hasattr(blog, "category") and blog.category:
                category = blog.category
                category_counts[category] = category_counts.get(category, 0) + 1
            else:
                category_counts["Uncategorized"] = (
                    category_counts.get("Uncategorized", 0) + 1
                )

        # Sort categories by count (descending)
        sorted_categories = sorted(
            category_counts.items(), key=lambda x: x[1], reverse=True
        )

        # Combine small categories into "Other" if there are too many
        if len(sorted_categories) > 6:
            main_categories = sorted_categories[:5]
            other_count = sum(count for _, count in sorted_categories[5:])

            category_labels = [category for category, _ in main_categories]
            category_data = [count for _, count in main_categories]

            if other_count > 0:
                category_labels.append("Other")
                category_data.append(other_count)
        else:
            category_labels = [category for category, _ in sorted_categories]
            category_data = [count for _, count in sorted_categories]

        category_distribution = {"labels": category_labels, "data": category_data}

        if log_file_handle:
            safe_log_write(
                log_file_handle,
                f"Generated category distribution data with {len(category_distribution['labels'])} categories\n",
            )

        # Generate monthly blog data
        if log_file_handle:
            safe_log_write(log_file_handle, "Generating monthly blog data\n")

        # Count blogs by month
        monthly_counts = {}

        for blog in all_blogs:
            if hasattr(blog, "date") and blog.date:
                month_key = blog.date.strftime("%Y-%m")
                monthly_counts[month_key] = monthly_counts.get(month_key, 0) + 1

        # Get all months of data
        sorted_months = sorted(monthly_counts.keys())

        # Format month labels
        monthly_labels = [
            datetime.strptime(month, "%Y-%m").strftime("%b %Y")
            for month in sorted_months
        ]
        monthly_data = [monthly_counts[month] for month in sorted_months]

        monthly_blog_data = {"labels": monthly_labels, "data": monthly_data}

        if log_file_handle:
            safe_log_write(
                log_file_handle,
                f"Generated monthly blog data with {len(monthly_blog_data['labels'])} months\n",
            )

        # Generate tag distribution data
        if log_file_handle:
            safe_log_write(log_file_handle, "Generating tag distribution data\n")

        # Count blogs by tag
        tag_counts = {}

        for blog in all_blogs:
            if hasattr(blog, "tags") and blog.tags:
                # Handle tags as a list or as a comma-separated string
                if isinstance(blog.tags, list):
                    tags = blog.tags
                else:
                    tags = [tag.strip() for tag in blog.tags.split(",")]

                for tag in tags:
                    if tag:  # Skip empty tags
                        tag_counts[tag] = tag_counts.get(tag, 0) + 1

        # Sort tags by count (descending)
        sorted_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)

        # Combine small tags into "Other" if there are too many
        if len(sorted_tags) > 15:
            main_tags = sorted_tags[:15]
            other_count = sum(count for _, count in sorted_tags[15:])

            tag_labels = [tag for tag, _ in main_tags]
            tag_data = [count for _, count in main_tags]

            if other_count > 0:
                tag_labels.append("Other")
                tag_data.append(other_count)
        else:
            tag_labels = [tag for tag, _ in sorted_tags]
            tag_data = [count for _, count in sorted_tags]

        tag_distribution = {"labels": tag_labels, "data": tag_data}

        if log_file_handle:
            safe_log_write(
                log_file_handle,
                f"Generated tag distribution data with {len(tag_distribution['labels'])} tags\n",
            )

        # Combine all statistics data
        statistics_data = {
            "authors": author_stats,
            "categories": category_distribution,
            "monthly": monthly_blog_data,
            "tags": tag_distribution,
        }

        # Replace placeholders in the template
        if log_file_handle:
            safe_log_write(log_file_handle, "Replacing placeholders in the template\n")

        updated_html = blog_statistics_template.replace(
            "{author_rows}", "\n".join(author_rows)
        )
        updated_html = updated_html.replace(
            "{statistics_data}", json.dumps(statistics_data)
        )

        # Create the statistics page content
        statistics_template = """---
title: ROCm Blogs Statistics
myst:
  html_meta:
    "description lang=en": "Statistics and analytics for AMD ROCm™ software blogs"
    "keywords": "AMD GPU, MI300, MI250, ROCm, blog, statistics, analytics"
    "property=og:locale": "en_US"
---

# ROCm Blogs Statistics

<style>
{CSS}
</style>
{HTML}
"""

        final_content = statistics_template.format(
            CSS=blog_statistics_css, HTML=updated_html
        )

        # Write the statistics page
        output_path = Path(rocm_blogs.blogs_directory) / "blog_statistics.md"

        if log_file_handle:
            safe_log_write(
                log_file_handle, f"Writing statistics page to {output_path}\n"
            )

        with output_path.open("w", encoding="utf-8") as output_file:
            output_file.write(final_content)

        # Record timing information
        phase_duration = time.time() - phase_start_time
        _BUILD_PHASES["blog_statistics"] = phase_duration
        log_message(
            "info",
            "Successfully generated blog statistics page at {output_path} in \033[96m{phase_duration:.2f} seconds\033[0m",
            "general",
            "__init__",
        )

        if log_file_handle:
            safe_log_write(
                log_file_handle,
                f"Successfully generated blog statistics page in {phase_duration:.2f} seconds\n",
            )

    except Exception as stats_error:
        error_message = f"Failed to generate blog statistics page: {stats_error}"
        log_message("error", error_message, "general", "__init__")
        log_message(
            "debug", f"Traceback: {traceback.format_exc()}", "general", "__init__"
        )

        if log_file_handle:
            safe_log_write(log_file_handle, f"ERROR: {error_message}\n")
            safe_log_write(log_file_handle, f"Traceback: {traceback.format_exc()}\n")

        _BUILD_PHASES["blog_statistics"] = time.time() - phase_start_time
        _CRITICAL_ERROR_OCCURRED = True
        raise ROCmBlogsError(error_message) from stats_error
    finally:
        # Write summary to log file
        if log_file_handle:
            end_time = time.time()
            total_duration = end_time - phase_start_time

            safe_log_write(log_file_handle, "\n" + "=" * 80 + "\n")
            safe_log_write(log_file_handle, "BLOG STATISTICS GENERATION SUMMARY\n")
            safe_log_write(log_file_handle, "-" * 80 + "\n")
            safe_log_write(
                log_file_handle, f"Total time: {total_duration:.2f} seconds\n"
            )

            safe_log_close(log_file_handle)


@profile_function("update_index_file", save_report=True)
def update_index_file(sphinx_app: Sphinx, rocm_blogs: ROCmBlogs = None) -> None:
    """Update the index file with new blog posts"""
    global _CRITICAL_ERROR_OCCURRED
    phase_start_time = time.time()
    phase_name = "update_index"

    # Create a log file for this step
    log_filepath, log_file_handle = create_step_log_file(phase_name)

    # Track statistics for summary
    total_blogs_processed = 0
    total_blogs_successful = 0
    total_blogs_error = 0
    total_blogs_warning = 0
    total_blogs_skipped = 0
    all_error_details = []

    # Enhanced timing tracking for each major operation
    operation_timings = {}

    def track_operation_time(operation_name, start_time):
        """Track timing for individual operations within update_index_file."""
        duration = time.time() - start_time
        operation_timings[operation_name] = duration
        log_message(
            "info",
            f"INDEX OPERATION: {operation_name} completed in {duration:.4f} seconds",
            "update_index_timing",
            "update_index_file",
        )
        if log_file_handle:
            safe_log_write(
                log_file_handle, f"TIMING: {operation_name} = {duration:.4f}s\n"
            )
        return duration

    try:
        if log_file_handle:
            safe_log_write(log_file_handle, "Starting index file update process\n")
            safe_log_write(log_file_handle, "-" * 80 + "\n\n")

        # Load templates and styles
        operation_start = time.time()
        template_html = import_file("rocm_blogs.templates", "index.html")
        css_content = import_file("rocm_blogs.static.css", "index.css")
        banner_css_content = import_file("rocm_blogs.static.css", "banner-slider.css")
        track_operation_time("load_templates_and_styles", operation_start)

        if log_file_handle:
            safe_log_write(
                log_file_handle, "Successfully loaded templates and styles\n"
            )

        # Format the index template
        index_template = INDEX_TEMPLATE.format(
            CSS=css_content, BANNER_CSS=banner_css_content, HTML=template_html
        )

        # Initialize ROCmBlogs instance if not provided
        operation_start = time.time()
        if rocm_blogs is None:
            rocm_blogs = ROCmBlogs()
            blogs_directory = rocm_blogs.find_blogs_directory(sphinx_app.srcdir)
        else:
            blogs_directory = rocm_blogs.blogs_directory

        if not blogs_directory:
            error_message = "Could not find blogs directory"
            log_message("error", error_message, "general", "__init__")
            log_message(
                "debug", f"Traceback: {traceback.format_exc()}", "general", "__init__"
            )

            if log_file_handle:
                safe_log_write(log_file_handle, f"ERROR: {error_message}\n")
                safe_log_write(
                    log_file_handle, f"Traceback: {traceback.format_exc()}\n"
                )

            _CRITICAL_ERROR_OCCURRED = True
            raise ROCmBlogsError(error_message)

        rocm_blogs.blogs_directory = str(blogs_directory)
        track_operation_time("initialize_rocm_blogs_instance", operation_start)

        if log_file_handle:
            safe_log_write(
                log_file_handle, f"Found blogs directory: {blogs_directory}\n"
            )

        operation_start = time.time()
        readme_count = rocm_blogs.find_readme_files()
        track_operation_time("find_readme_files", operation_start)

        if log_file_handle:
            safe_log_write(log_file_handle, f"Found {readme_count} README files\n")

        operation_start = time.time()
        rocm_blogs.create_blog_objects()
        track_operation_time("create_blog_objects", operation_start)

        # Report duplicate statistics
        duplicate_stats = rocm_blogs.blogs.get_duplicate_statistics()
        log_message(
            "info",
            f"Blog collection statistics - Total blogs: {duplicate_stats['total_blogs']}, "
            f"Duplicate attempts blocked: {duplicate_stats['duplicate_attempts']}, "
            f"Unique paths: {duplicate_stats['unique_paths']}, "
            f"Unique titles: {duplicate_stats['unique_titles']}",
            "general",
            "__init__",
        )

        if log_file_handle:
            safe_log_write(
                log_file_handle,
                f"\nDuplicate Detection Report:\n"
                f"  - Total blogs in collection: {duplicate_stats['total_blogs']}\n"
                f"  - Duplicate attempts blocked: {duplicate_stats['duplicate_attempts']}\n"
                f"  - Unique file paths: {duplicate_stats['unique_paths']}\n"
                f"  - Unique blog titles: {duplicate_stats['unique_titles']}\n\n",
            )

        # Check for potential duplicates that might have slipped through
        potential_duplicates = rocm_blogs.blogs.find_potential_duplicates()
        if potential_duplicates:
            log_message(
                "warning",
                f"Found {len(potential_duplicates)} potential duplicate pairs that may need investigation",
                "general",
                "__init__",
            )
            if log_file_handle:
                safe_log_write(
                    log_file_handle,
                    f"Potential duplicates found ({len(potential_duplicates)} pairs):\n",
                )
                for dup_type, description, blog1, blog2 in potential_duplicates[
                    :10
                ]:  # Show first 10
                    safe_log_write(log_file_handle, f"  - {dup_type}: {description}\n")

        operation_start = time.time()
        rocm_blogs.blogs.write_to_file()
        track_operation_time("write_blogs_to_file", operation_start)

        operation_start = time.time()
        rocm_blogs.find_author_files()
        track_operation_time("find_author_files", operation_start)

        operation_start = time.time()
        update_author_files(sphinx_app, rocm_blogs)
        track_operation_time("update_author_files", operation_start)

        operation_start = time.time()
        blog_statistics(sphinx_app, rocm_blogs)
        track_operation_time("blog_statistics", operation_start)

        if log_file_handle:
            safe_log_write(log_file_handle, f"Created blog objects\n")

        # Write blogs to CSV file for reference
        blogs_csv_path = Path(blogs_directory) / "blogs.csv"
        rocm_blogs.blogs.write_to_file(str(blogs_csv_path))

        if log_file_handle:
            safe_log_write(
                log_file_handle, f"Wrote blog information to {blogs_csv_path}\n"
            )

        features_csv_path = Path(blogs_directory) / "featured-blogs.csv"
        featured_blogs = []

        if features_csv_path.exists():
            log_message(
                "info",
                f"Found featured-blogs.csv file at {features_csv_path}",
                "featured_blogs",
                "__init__",
            )
            if log_file_handle:
                safe_log_write(
                    log_file_handle,
                    f"Found featured-blogs.csv file at {features_csv_path}\n",
                )

            log_message(
                "info",
                "========== LOADING FEATURED BLOGS FROM CSV ==========",
                "featured_blogs",
                "__init__",
            )
            featured_blogs = rocm_blogs.blogs.load_featured_blogs_from_csv(
                str(features_csv_path)
            )

            log_message(
                "info",
                f"Loaded {len(featured_blogs)} featured blogs from {features_csv_path}",
                "featured_blogs",
                "__init__",
            )
            if log_file_handle:
                safe_log_write(
                    log_file_handle,
                    f"Loaded {len(featured_blogs)} featured blogs from {features_csv_path}\n",
                )

            # Log details of loaded featured blogs
            if featured_blogs:
                log_message(
                    "info",
                    "Successfully loaded featured blogs:",
                    "featured_blogs",
                    "__init__",
                )
                for i, blog in enumerate(featured_blogs):
                    blog_title = getattr(blog, "blog_title", "No Title")
                    blog_path = getattr(blog, "file_path", "No Path")
                    log_message(
                        "info",
                        f"  {i+1}. '{blog_title}' (Path: {blog_path})",
                        "featured_blogs",
                        "__init__",
                    )
                    if log_file_handle:
                        safe_log_write(
                            log_file_handle,
                            f"  {i+1}. '{blog_title}' (Path: {blog_path})\n",
                        )
            else:
                log_message(
                    "error",
                    "[WARNING] No featured blogs were successfully loaded from CSV!",
                    "featured_blogs",
                    "__init__",
                )
                if log_file_handle:
                    safe_log_write(
                        log_file_handle,
                        "[WARNING] No featured blogs were successfully loaded from CSV!\n",
                    )
        else:
            if log_file_handle:
                safe_log_write(
                    log_file_handle,
                    f"featured-blogs.csv file not found at {features_csv_path}, no featured blogs will be displayed\n",
                )

        rocm_blogs.blogs.sort_blogs_by_date()

        if log_file_handle:
            safe_log_write(log_file_handle, "Sorted blogs by date\n")

        category_keys = [
            category_info.get("category_key", category_info["name"])
            for category_info in BLOG_CATEGORIES
        ]
        log_message(
            "info",
            "Using category keys for sorting: {category_keys}",
            "general",
            "__init__",
        )

        if log_file_handle:
            safe_log_write(
                log_file_handle, f"Using category keys for sorting: {category_keys}\n"
            )

        rocm_blogs.blogs.sort_blogs_by_category(category_keys)

        if log_file_handle:
            safe_log_write(log_file_handle, "Sorted blogs by category\n")

        # Get all blogs
        all_blogs = rocm_blogs.blogs.get_blogs()

        log_message(
            "info",
            f"========== BLOG INVENTORY CHECK ==========",
            "blog_loading",
            "__init__",
        )
        log_message(
            "info",
            f"Total blogs retrieved from BlogHolder: {len(all_blogs)}",
            "blog_loading",
            "__init__",
        )

        if len(all_blogs) == 0:
            log_message(
                "critical",
                "[WARNING] NO BLOGS LOADED IN SYSTEM! This will prevent banner slider generation.",
                "blog_loading",
                "__init__",
            )
            log_message(
                "info",
                "Checking BlogHolder internal state...",
                "blog_loading",
                "__init__",
            )

            # Debug the BlogHolder state
            blog_keys = list(rocm_blogs.blogs.blogs.keys())
            log_message(
                "info",
                f"BlogHolder internal blog keys count: {len(blog_keys)}",
                "blog_loading",
                "__init__",
            )
            if blog_keys:
                log_message(
                    "info",
                    f"Sample blog keys: {blog_keys[:5]}",
                    "blog_loading",
                    "__init__",
                )
        else:
            log_message(
                "info",
                "[SUCCESS] Blogs successfully loaded in system",
                "blog_loading",
                "__init__",
            )
            # Log sample blog titles
            sample_titles = [
                getattr(blog, "blog_title", "No Title") for blog in all_blogs[:5]
            ]
            log_message(
                "info",
                f"Sample blog titles: {sample_titles}",
                "blog_loading",
                "__init__",
            )

        if log_file_handle:
            safe_log_write(log_file_handle, f"Retrieved {len(all_blogs)} total blogs\n")

        # Filter blogs to only include real blog posts
        filtered_blogs = []
        skipped_count = 0

        for blog in all_blogs:
            if hasattr(blog, "blogpost") and blog.blogpost:
                filtered_blogs.append(blog)
                total_blogs_processed += 1
                if log_file_handle:
                    safe_log_write(
                        log_file_handle,
                        f"Including blog: {getattr(blog, 'file_path', 'Unknown')}\n",
                    )
            else:
                skipped_count += 1
                total_blogs_skipped += 1
                log_message(
                    "debug",
                    f"Skipping non-blog README file for index page: {getattr(blog, 'file_path', 'Unknown')}",
                    "general",
                    "__init__",
                )
                if log_file_handle:
                    safe_log_write(
                        log_file_handle,
                        f"Skipping non-blog README file: {getattr(blog, 'file_path', 'Unknown')}\n",
                    )

        log_message(
            "info",
            f"Filtered out {skipped_count} non-blog README files for index page, kept {len(filtered_blogs)} genuine blog posts",
            "general",
            "__init__",
        )

        if log_file_handle:
            safe_log_write(
                log_file_handle,
                f"Filtered out {skipped_count} non-blog README files, kept {len(filtered_blogs)} genuine blog posts\n",
            )

        # Replace all_blogs with filtered_blogs
        all_blogs = filtered_blogs

        if not all_blogs:
            warning_message = "No valid blogs found to display on index page"
            log_message("warning", warning_message, "general", "__init__")

            if log_file_handle:
                safe_log_write(log_file_handle, f"WARNING: {warning_message}\n")

            total_blogs_warning += 1
            return

        used_blogs = []
        used_blog_ids = set()

        if log_file_handle:
            safe_log_write(
                log_file_handle, "Implementing comprehensive deduplication system\n"
            )

        log_message(
            "info",
            "========== BANNER BLOGS SELECTION AND FALLBACK LOGIC ==========",
            "banner_blogs",
            "__init__",
        )
        log_message(
            "info",
            f"BANNER_BLOGS_COUNT constant: {BANNER_BLOGS_COUNT}",
            "banner_blogs",
            "__init__",
        )
        log_message(
            "info",
            f"Total blogs available in system: {len(all_blogs)}",
            "banner_blogs",
            "__init__",
        )
        safe_log_write(
            log_file_handle, f"BANNER_BLOGS_COUNT constant: {BANNER_BLOGS_COUNT}\n"
        )
        safe_log_write(
            log_file_handle, f"Total blogs available in system: {len(all_blogs)}\n"
        )

        if featured_blogs:
            log_message(
                "info",
                f"Featured blogs available: {len(featured_blogs)}",
                "banner_blogs",
                "__init__",
            )
            safe_log_write(
                log_file_handle, f"Featured blogs available: {len(featured_blogs)}\n"
            )

            # Log details of featured blogs
            for i, blog in enumerate(featured_blogs):
                blog_title = getattr(blog, "blog_title", "No Title")
                log_message(
                    "debug",
                    f"Featured blog {i+1}: '{blog_title}'",
                    "banner_blogs",
                    "__init__",
                )
                safe_log_write(
                    log_file_handle, f"Featured blog {i+1}: '{blog_title}'\n"
                )

            max_banner_blogs = min(len(featured_blogs), BANNER_BLOGS_COUNT)
            log_message(
                "info",
                f"Calculating max_banner_blogs: min({len(featured_blogs)}, {BANNER_BLOGS_COUNT}) = {max_banner_blogs}",
                "banner_blogs",
                "__init__",
            )
            safe_log_write(
                log_file_handle,
                f"Calculating max_banner_blogs: min({len(featured_blogs)}, {BANNER_BLOGS_COUNT}) = {max_banner_blogs}\n",
            )

            banner_blogs = featured_blogs[:max_banner_blogs]

            log_message(
                "info",
                f"Selected {len(banner_blogs)} featured blogs for banner (max allowed: {BANNER_BLOGS_COUNT})",
                "banner_blogs",
                "__init__",
            )
            safe_log_write(
                log_file_handle,
                f"Selected {len(banner_blogs)} featured blogs for banner (max allowed: {BANNER_BLOGS_COUNT})\n",
            )

            # Log the selected banner blogs in detail
            log_message("info", "Selected banner blogs:", "banner_blogs", "__init__")
            for i, blog in enumerate(banner_blogs):
                blog_title = getattr(blog, "blog_title", "No Title")
                log_message(
                    "info",
                    f"  Selected banner blog {i+1}: '{blog_title}'",
                    "banner_blogs",
                    "__init__",
                )
                safe_log_write(
                    log_file_handle, f"  Selected banner blog {i+1}: '{blog_title}'\n"
                )

            # Check if we need fallback due to missing or already-used blogs
            log_message(
                "info",
                f"Checking fallback conditions for {len(banner_blogs)} featured blogs",
                "banner_blogs",
                "__init__",
            )

            # Only use fallback if:
            # 1. We couldn't find all featured blogs from CSV (some blogs don't exist)
            # 2. Some featured blogs are already used elsewhere on homepage

            # Count original featured entries from CSV more safely
            original_featured_count = 0
            if features_csv_path.exists():
                try:
                    with open(str(features_csv_path), "r", encoding="utf-8") as f:
                        import csv

                        reader = csv.reader(f)
                        original_featured_count = len(
                            [row for row in reader if row and row[0].strip()]
                        )
                except Exception as e:
                    log_message(
                        "warning",
                        f"Error counting CSV entries: {e}",
                        "banner_blogs",
                        "__init__",
                    )
                    original_featured_count = 4  # fallback to expected count
            log_message(
                "info",
                f"Original featured CSV entries: {original_featured_count}, Successfully matched: {len(banner_blogs)}",
                "banner_blogs",
                "__init__",
            )

            # Check if we're missing blogs due to non-existence or other usage conflicts
            if len(banner_blogs) < original_featured_count:
                missing_count = original_featured_count - len(banner_blogs)
                log_message(
                    "warning",
                    f"Missing {missing_count} featured blogs - some may not exist or have conflicts",
                    "banner_blogs",
                    "__init__",
                )
                safe_log_write(
                    log_file_handle,
                    f"Missing {missing_count} featured blogs - some may not exist or have conflicts\n",
                )

                # Only add fallback blogs to replace missing ones, not to reach BANNER_BLOGS_COUNT
                featured_titles = {
                    blog.blog_title
                    for blog in banner_blogs
                    if hasattr(blog, "blog_title")
                }
                log_message(
                    "debug",
                    f"Featured titles already selected: {featured_titles}",
                    "banner_blogs",
                    "__init__",
                )
                safe_log_write(
                    log_file_handle,
                    f"Featured titles already selected: {featured_titles}\n",
                )

                # Find blogs not already in featured and not used elsewhere
                eligible_blogs = []
                for blog in all_blogs:
                    if (
                        hasattr(blog, "blog_title")
                        and blog.blog_title not in featured_titles
                    ):
                        # Check if blog is used elsewhere on homepage by checking used_blogs list
                        blog_used_elsewhere = any(
                            hasattr(used_blog, "blog_title")
                            and getattr(used_blog, "blog_title") == blog.blog_title
                            for used_blog in used_blogs
                        )

                        if not blog_used_elsewhere:
                            eligible_blogs.append(blog)
                        else:
                            log_message(
                                "debug",
                                f"Skipping blog already used elsewhere: '{blog.blog_title}'",
                                "banner_blogs",
                                "__init__",
                            )

                log_message(
                    "info",
                    f"Found {len(eligible_blogs)} eligible blogs for fallback",
                    "banner_blogs",
                    "__init__",
                )
                safe_log_write(
                    log_file_handle,
                    f"Found {len(eligible_blogs)} eligible blogs for fallback\n",
                )

                # Only add the missing count, not to reach BANNER_BLOGS_COUNT
                additional_blogs = eligible_blogs[:missing_count]

                log_message(
                    "info",
                    f"Adding {len(additional_blogs)} fallback blogs to replace missing featured blogs",
                    "banner_blogs",
                    "__init__",
                )
                safe_log_write(
                    log_file_handle,
                    f"Adding {len(additional_blogs)} fallback blogs to replace missing featured blogs\n",
                )

                # Log details of additional blogs
                for i, blog in enumerate(additional_blogs):
                    blog_title = getattr(blog, "blog_title", "No Title")
                    log_message(
                        "info",
                        f"Fallback blog {i+1}: '{blog_title}'",
                        "banner_blogs",
                        "__init__",
                    )
                    safe_log_write(
                        log_file_handle, f"Fallback blog {i+1}: '{blog_title}'\n"
                    )

                banner_blogs.extend(additional_blogs)

                log_message(
                    "info",
                    f"[SUCCESS] Fallback completed: Final banner blog count = {len(banner_blogs)}",
                    "banner_blogs",
                    "__init__",
                )
                safe_log_write(
                    log_file_handle,
                    f"[SUCCESS] Fallback completed: Final banner blog count = {len(banner_blogs)}\n",
                )
            else:
                log_message(
                    "info",
                    "[SUCCESS] All featured blogs found successfully, no fallback needed",
                    "banner_blogs",
                    "__init__",
                )
                safe_log_write(
                    log_file_handle,
                    "[SUCCESS] All featured blogs found successfully, no fallback needed\n",
                )
        else:
            log_message(
                "warning",
                "No featured blogs found, using recent blogs for banner",
                "banner_blogs",
                "__init__",
            )
            safe_log_write(
                log_file_handle,
                "No featured blogs found, using recent blogs for banner\n",
            )
            banner_blogs = all_blogs[:BANNER_BLOGS_COUNT]

            log_message(
                "info",
                f"Selected {len(banner_blogs)} recent blogs for banner",
                "banner_blogs",
                "__init__",
            )
            safe_log_write(
                log_file_handle,
                f"Selected {len(banner_blogs)} recent blogs for banner\n",
            )

        # Final summary
        log_message(
            "info",
            f"========== FINAL BANNER BLOGS SELECTION SUMMARY ==========",
            "banner_blogs",
            "__init__",
        )
        log_message(
            "info", f"Expected banner blogs from CSV: 4", "banner_blogs", "__init__"
        )
        log_message(
            "info",
            f"Total banner blogs selected: {len(banner_blogs)}",
            "banner_blogs",
            "__init__",
        )
        log_message(
            "info",
            f"Selection method: {'Featured blogs only' if len(banner_blogs) == 4 else 'Featured + Fallback'}",
            "banner_blogs",
            "__init__",
        )
        safe_log_write(
            log_file_handle,
            f"========== FINAL BANNER BLOGS SELECTION SUMMARY ==========\n",
        )
        safe_log_write(log_file_handle, f"Expected: 4, Selected: {len(banner_blogs)}\n")

        for i, blog in enumerate(banner_blogs):
            blog_title = getattr(blog, "blog_title", "No Title")
            blog_path = getattr(blog, "file_path", "No Path")
            log_message(
                "info",
                f"Banner blog {i+1}: '{blog_title}' (Path: {blog_path})",
                "banner_blogs",
                "__init__",
            )
            safe_log_write(
                log_file_handle,
                f"Banner blog {i+1}: '{blog_title}' (Path: {blog_path})\n",
            )

        # Add banner blogs to used list
        for blog in banner_blogs:
            used_blogs.append(blog)
            used_blog_ids.add(id(blog))

        if log_file_handle:
            safe_log_write(
                log_file_handle,
                f"Banner slider: Using {len(banner_blogs)} blogs (featured: {bool(featured_blogs)})\n",
            )
            safe_log_write(
                log_file_handle,
                f"Added {len(banner_blogs)} banner blogs to deduplication list\n",
            )

        # Generate banner slider content
        banner_content = _generate_banner_slider(
            rocm_blogs, banner_blogs, []
        )  # Don't pass used_blogs to avoid double-adding

        if log_file_handle:
            safe_log_write(log_file_handle, "Banner slider generation completed\n")

        featured_grid_items = []
        if featured_blogs:
            if log_file_handle:
                safe_log_write(
                    log_file_handle,
                    f"Featured section: Processing {len(featured_blogs)} featured blogs\n",
                )

            try:
                # Generate featured grid items (these will also be marked as used)
                if len(featured_blogs) > 0:
                    featured_grid_items = _generate_grid_items(
                        rocm_blogs,
                        featured_blogs,
                        len(featured_blogs),
                        [],
                        False,
                        False,
                    )

                    for blog in featured_blogs:
                        if id(blog) not in used_blog_ids:
                            used_blogs.append(blog)
                            used_blog_ids.add(id(blog))

                    if log_file_handle:
                        safe_log_write(
                            log_file_handle,
                            f"Featured section: Generated {len(featured_grid_items)} grid items\n",
                        )
                        safe_log_write(
                            log_file_handle,
                            f"Total blogs in deduplication list: {len(used_blog_ids)}\n",
                        )
            except Exception as featured_error:
                log_message(
                    "warning",
                    f"Error generating featured grid items: {featured_error}. Continuing without featured blogs.",
                    "general",
                    "__init__",
                )
                if log_file_handle:
                    safe_log_write(
                        log_file_handle,
                        f"WARNING: Error generating featured grid items: {featured_error}\n",
                    )
        else:
            if log_file_handle:
                safe_log_write(log_file_handle, "No featured blogs to display\n")

        if log_file_handle:
            safe_log_write(
                log_file_handle,
                f"Generating Recent Posts section with up to {MAIN_GRID_BLOGS_COUNT} blogs (second priority)\n",
            )
            safe_log_write(
                log_file_handle,
                f"Excluding {len(used_blog_ids)} already used blogs from Recent Posts\n",
            )

        # Filter out already used blogs from Recent Posts
        non_used_blogs = [blog for blog in all_blogs if id(blog) not in used_blog_ids]

        main_grid_items = _generate_grid_items(
            rocm_blogs,
            non_used_blogs,
            MAIN_GRID_BLOGS_COUNT,
            used_blogs,
            True,  # Skip used blogs
            False,
        )

        # Update used_blog_ids with newly used blogs from Recent Posts section
        for blog in non_used_blogs[:MAIN_GRID_BLOGS_COUNT]:
            if id(blog) not in used_blog_ids:
                used_blog_ids.add(id(blog))

        if log_file_handle:
            safe_log_write(
                log_file_handle,
                f"Generated {len(main_grid_items)} Recent Posts grid items from {len(non_used_blogs)} available blogs\n",
            )
            safe_log_write(
                log_file_handle,
                f"Updated used blogs count after Recent Posts: {len(used_blog_ids)}\n",
            )

        if log_file_handle:
            safe_log_write(
                log_file_handle,
                "Filtering category blogs with deduplication (lowest priority)\n",
            )

        # Filter out used blogs from category lists (now includes Recent Posts)
        ecosystem_blogs = [
            blog
            for blog in all_blogs
            if hasattr(blog, "category")
            and blog.category == "Ecosystems and Partners"
            and id(blog) not in used_blog_ids
        ]
        application_blogs = [
            blog
            for blog in all_blogs
            if hasattr(blog, "category")
            and blog.category == "Applications & models"
            and id(blog) not in used_blog_ids
        ]
        software_blogs = [
            blog
            for blog in all_blogs
            if hasattr(blog, "category")
            and blog.category == "Software tools & optimizations"
            and id(blog) not in used_blog_ids
        ]

        if log_file_handle:
            safe_log_write(
                log_file_handle, f"Category blogs after Recent Posts deduplication:\n"
            )
            safe_log_write(
                log_file_handle,
                f"  - Ecosystems and Partners: {len(ecosystem_blogs)} blogs (excluded {len([b for b in all_blogs if hasattr(b, 'category') and b.category == 'Ecosystems and Partners']) - len(ecosystem_blogs)} duplicates)\n",
            )
            safe_log_write(
                log_file_handle,
                f"  - Applications & models: {len(application_blogs)} blogs (excluded {len([b for b in all_blogs if hasattr(b, 'category') and b.category == 'Applications & models']) - len(application_blogs)} duplicates)\n",
            )
            safe_log_write(
                log_file_handle,
                f"  - Software tools & optimizations: {len(software_blogs)} blogs (excluded {len([b for b in all_blogs if hasattr(b, 'category') and b.category == 'Software tools & optimizations']) - len(software_blogs)} duplicates)\n",
            )

        if log_file_handle:
            safe_log_write(
                log_file_handle,
                f"Generating category grid items with up to {CATEGORY_GRID_BLOGS_COUNT} blogs per category (lowest priority)\n",
            )

        # Generate ecosystem grid items first and update used list
        ecosystem_grid_items = _generate_grid_items(
            rocm_blogs,
            ecosystem_blogs,
            CATEGORY_GRID_BLOGS_COUNT,
            used_blogs,
            True,  # Skip used blogs
            False,
        )

        # Update used_blog_ids with newly used blogs from ecosystem section
        for blog in ecosystem_blogs[:CATEGORY_GRID_BLOGS_COUNT]:
            if id(blog) not in used_blog_ids:
                used_blog_ids.add(id(blog))

        # Re-filter application blogs to exclude newly used ecosystem blogs
        application_blogs_filtered = [
            blog for blog in application_blogs if id(blog) not in used_blog_ids
        ]

        application_grid_items = _generate_grid_items(
            rocm_blogs,
            application_blogs_filtered,
            CATEGORY_GRID_BLOGS_COUNT,
            used_blogs,
            True,  # Skip used blogs
            False,
        )

        # Update used_blog_ids with newly used blogs from application section
        for blog in application_blogs_filtered[:CATEGORY_GRID_BLOGS_COUNT]:
            if id(blog) not in used_blog_ids:
                used_blog_ids.add(id(blog))

        # Re-filter software blogs to exclude newly used blogs from previous sections
        software_blogs_filtered = [
            blog for blog in software_blogs if id(blog) not in used_blog_ids
        ]

        software_grid_items = _generate_grid_items(
            rocm_blogs,
            software_blogs_filtered,
            CATEGORY_GRID_BLOGS_COUNT,
            used_blogs,
            True,  # Skip used blogs
            False,
        )

        if log_file_handle:
            safe_log_write(
                log_file_handle,
                f"Generated category grid items with sequential deduplication (lowest priority):\n",
            )
            safe_log_write(
                log_file_handle,
                f"  - Ecosystems and Partners: {len(ecosystem_grid_items)} grid items from {len(ecosystem_blogs)} available\n",
            )
            safe_log_write(
                log_file_handle,
                f"  - Applications & models: {len(application_grid_items)} grid items from {len(application_blogs_filtered)} available (after ecosystem dedup)\n",
            )
            safe_log_write(
                log_file_handle,
                f"  - Software tools & optimizations: {len(software_grid_items)} grid items from {len(software_blogs_filtered)} available (after all dedup)\n",
            )
            safe_log_write(
                log_file_handle,
                f"Final deduplication summary: {len(used_blog_ids)} blogs used across all sections\n",
            )

        # Replace placeholders in the template
        if log_file_handle:
            safe_log_write(log_file_handle, "Replacing placeholders in the template\n")

        updated_html = (
            index_template.replace("{grid_items}", "\n".join(main_grid_items))
            .replace(
                "{eco_grid_items}",
                "\n".join(ecosystem_grid_items) if ecosystem_grid_items else "",
            )
            .replace("{application_grid_items}", "\n".join(application_grid_items))
            .replace("{software_grid_items}", "\n".join(software_grid_items))
            .replace("{featured_grid_items}", "\n".join(featured_grid_items))
            .replace("{banner_slider}", banner_content)
        )

        # Write the updated HTML to blogs/index.md
        output_path = Path(blogs_directory) / "index.md"

        if log_file_handle:
            safe_log_write(log_file_handle, f"Writing updated HTML to {output_path}\n")

        with output_path.open("w", encoding="utf-8") as output_file:
            output_file.write(updated_html)

        total_blogs_successful += 1

        # Record timing information
        phase_duration = time.time() - phase_start_time
        _BUILD_PHASES[phase_name] = phase_duration
        log_message(
            "info",
            "Successfully updated {output_path} with new content in \033[96m{phase_duration:.2f} seconds\033[0m",
            "general",
            "__init__",
        )

        if log_file_handle:
            safe_log_write(
                log_file_handle,
                f"Successfully updated {output_path} with new content in {phase_duration:.2f} seconds\n",
            )

    except ROCmBlogsError:
        # Re-raise ROCmBlogsError to stop the build
        _BUILD_PHASES[phase_name] = time.time() - phase_start_time

        if log_file_handle:
            safe_log_write(log_file_handle, f"ERROR: ROCmBlogsError occurred\n")
            safe_log_write(log_file_handle, f"Traceback: {traceback.format_exc()}\n")

        raise
    except Exception as error:
        error_message = f"Error updating index file: {error}"
        log_message("critical", error_message, "general", "__init__")
        log_message(
            "debug", f"Traceback: {traceback.format_exc()}", "general", "__init__"
        )

        if log_file_handle:
            safe_log_write(log_file_handle, f"CRITICAL ERROR: {error_message}\n")
            safe_log_write(log_file_handle, f"Traceback: {traceback.format_exc()}\n")

        _BUILD_PHASES[phase_name] = time.time() - phase_start_time
        _CRITICAL_ERROR_OCCURRED = True
        raise ROCmBlogsError(error_message) from error
    finally:
        # Write summary to log file
        if log_file_handle:
            end_time = time.time()
            total_duration = end_time - phase_start_time

            safe_log_write(log_file_handle, "\n" + "=" * 80 + "\n")
            safe_log_write(log_file_handle, "INDEX UPDATE SUMMARY\n")
            safe_log_write(log_file_handle, "-" * 80 + "\n")
            safe_log_write(
                log_file_handle, f"Total blogs processed: {total_blogs_processed}\n"
            )
            safe_log_write(log_file_handle, f"Successful: {total_blogs_successful}\n")
            safe_log_write(log_file_handle, f"Errors: {total_blogs_error}\n")
            safe_log_write(log_file_handle, f"Warnings: {total_blogs_warning}\n")
            safe_log_write(log_file_handle, f"Skipped: {total_blogs_skipped}\n")
            safe_log_write(
                log_file_handle, f"Total time: {total_duration:.2f} seconds\n"
            )

            if all_error_details:
                safe_log_write(log_file_handle, "\nERROR DETAILS:\n")
                safe_log_write(log_file_handle, "-" * 80 + "\n")
                for index, error_detail in enumerate(all_error_details):
                    safe_log_write(
                        log_file_handle, f"{index+1}. Blog: {error_detail['blog']}\n"
                    )
                    safe_log_write(
                        log_file_handle, f"   Error: {error_detail['error']}\n\n"
                    )

            safe_log_close(log_file_handle)


@profile_function("blog_generation", save_report=True)
def blog_generation(sphinx_app: Sphinx, rocm_blogs: ROCmBlogs = None) -> None:
    """Generate blog pages with styling and metadata - OPTIMIZED VERSION."""
    global _CRITICAL_ERROR_OCCURRED
    phase_start_time = time.time()
    phase_name = "blog_generation"

    # Create a log file for this step
    log_filepath, log_file_handle = create_step_log_file(phase_name)

    # Track statistics for summary
    total_blogs_processed = 0
    total_blogs_successful = 0
    total_blogs_error = 0
    total_blogs_warning = 0
    total_blogs_skipped = 0
    all_error_details = []

    try:
        if log_file_handle:
            safe_log_write(
                log_file_handle, "Starting OPTIMIZED blog generation process\n"
            )
            safe_log_write(log_file_handle, "-" * 80 + "\n\n")

        if rocm_blogs is None:
            build_env = sphinx_app.builder.env
            source_dir = Path(build_env.srcdir)
            rocm_blogs = ROCmBlogs()
            rocm_blogs.sphinx_app = sphinx_app
            rocm_blogs.sphinx_env = build_env
            blogs_directory = rocm_blogs.find_blogs_directory(str(source_dir))

            if not blogs_directory:
                error_message = "Could not find blogs directory"
                log_message("error", error_message, "general", "__init__")
                _CRITICAL_ERROR_OCCURRED = True
                raise ROCmBlogsError(error_message)

            rocm_blogs.blogs_directory = str(blogs_directory)
            rocm_blogs.find_author_files()
            readme_count = rocm_blogs.find_readme_files()
            rocm_blogs.create_blog_objects()
            rocm_blogs.blogs.sort_blogs_by_date()

            if log_file_handle:
                safe_log_write(
                    log_file_handle,
                    f"Initialized new ROCmBlogs instance with {readme_count} README files\n",
                )
        else:
            rocm_blogs.sphinx_app = sphinx_app
            rocm_blogs.sphinx_env = sphinx_app.builder.env
            blogs_directory = rocm_blogs.blogs_directory

            if log_file_handle:
                safe_log_write(
                    log_file_handle,
                    f"Using shared ROCmBlogs instance: {blogs_directory}\n",
                )

        all_blogs = rocm_blogs.blogs.get_blogs()

        seen_paths = set()
        seen_titles = set()
        blog_list = []
        dedup_lock = threading.Lock()

        for blog in all_blogs:
            if hasattr(blog, "blogpost") and blog.blogpost:
                blog_path = getattr(blog, "file_path", None)
                blog_title = getattr(blog, "blog_title", None)

                with dedup_lock:
                    is_duplicate = False

                    if blog_path and blog_path in seen_paths:
                        is_duplicate = True
                        if log_file_handle:
                            safe_log_write(
                                log_file_handle,
                                f"DUPLICATE PATH DETECTED: {blog_path}\n",
                            )

                    if blog_title and blog_title in seen_titles:
                        is_duplicate = True
                        if log_file_handle:
                            safe_log_write(
                                log_file_handle,
                                f"DUPLICATE TITLE DETECTED: {blog_title} (path: {blog_path})\n",
                            )

                    if not is_duplicate and blog_path:
                        seen_paths.add(blog_path)
                        if blog_title:
                            seen_titles.add(blog_title)
                        blog_list.append(blog)
                        if log_file_handle:
                            safe_log_write(
                                log_file_handle,
                                f"ADDED UNIQUE BLOG: {blog_title} (path: {blog_path})\n",
                            )

        total_blogs = len(blog_list)
        total_duplicates_removed = len(all_blogs) - total_blogs

        if log_file_handle:
            safe_log_write(log_file_handle, f"THREAD-SAFE DEDUPLICATION COMPLETE:\n")
            safe_log_write(log_file_handle, f"  - Original blogs: {len(all_blogs)}\n")
            safe_log_write(log_file_handle, f"  - Unique blogs: {total_blogs}\n")
            safe_log_write(
                log_file_handle, f"  - Duplicates removed: {total_duplicates_removed}\n"
            )
            safe_log_write(log_file_handle, f"  - Unique paths: {len(seen_paths)}\n")
            safe_log_write(log_file_handle, f"  - Unique titles: {len(seen_titles)}\n")

        if not blog_list:
            warning_message = "No blogs found to process"
            log_message("warning", warning_message, "general", "__init__")
            if log_file_handle:
                safe_log_write(log_file_handle, f"WARNING: {warning_message}\n")
            total_blogs_warning += 1
            return

        if total_blogs < 10:
            max_workers = min(4, os.cpu_count())
        elif total_blogs < 50:
            max_workers = min(8, os.cpu_count())
        else:
            max_workers = os.cpu_count()

        log_message(
            "info",
            f"Processing {total_blogs} blogs with {max_workers} workers (optimized)",
            "general",
            "__init__",
        )

        if log_file_handle:
            safe_log_write(
                log_file_handle,
                f"Using optimized thread pool: {max_workers} workers for {total_blogs} blogs\n",
            )

        processing_start = time.time()

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_blog = {
                executor.submit(process_single_blog, blog, rocm_blogs): (i, blog)
                for i, blog in enumerate(blog_list)
            }

            if log_file_handle:
                safe_log_write(
                    log_file_handle,
                    f"Submitted {len(future_to_blog)} blog processing tasks\n",
                )

            completed_count = 0
            for future in as_completed(future_to_blog):
                blog_index, blog = future_to_blog[future]
                completed_count += 1
                total_blogs_processed += 1

                try:
                    future.result()  # This will raise any exceptions from the thread
                    total_blogs_successful += 1

                    if log_file_handle and (
                        completed_count % 10 == 0 or completed_count == total_blogs
                    ):
                        safe_log_write(
                            log_file_handle,
                            f"Progress: {completed_count}/{total_blogs} blogs processed ({(completed_count/total_blogs)*100:.1f}%)\n",
                        )

                except Exception as processing_error:
                    error_message = f"Error processing blog: {processing_error}"
                    log_message("warning", error_message, "general", "__init__")

                    if log_file_handle:
                        safe_log_write(
                            log_file_handle,
                            f"ERROR: Blog {blog_index + 1}/{total_blogs}: {getattr(blog, 'file_path', 'Unknown')} - {processing_error}\n",
                        )

                    total_blogs_error += 1
                    all_error_details.append(
                        {
                            "blog": getattr(blog, "file_path", "Unknown"),
                            "error": str(processing_error),
                        }
                    )

        processing_duration = time.time() - processing_start

        if log_file_handle:
            safe_log_write(
                log_file_handle,
                f"Parallel processing completed in {processing_duration:.2f} seconds\n",
            )

        # Log completion statistics
        phase_end_time = time.time()
        phase_duration = phase_end_time - phase_start_time
        _BUILD_PHASES["blog_generation"] = phase_duration

        error_threshold = total_blogs * 0.5  # Increased from 0.25 to 0.5
        if total_blogs_error > error_threshold:
            error_message = f"Too many errors occurred during blog generation: {total_blogs_error} errors"
            log_message("critical", error_message, "general", "__init__")
            if log_file_handle:
                safe_log_write(log_file_handle, f"CRITICAL ERROR: {error_message}\n")
            _CRITICAL_ERROR_OCCURRED = True
            raise ROCmBlogsError(error_message)

        # Calculate performance metrics
        blogs_per_second = (
            total_blogs_successful / phase_duration if phase_duration > 0 else 0
        )

        log_message(
            "info",
            f"OPTIMIZED blog generation completed: {total_blogs_successful} successful, {total_blogs_error} failed, "
            f"in \033[96m{phase_duration:.2f} seconds\033[0m ({blogs_per_second:.1f} blogs/sec)",
            "general",
            "__init__",
        )

        if log_file_handle:
            safe_log_write(
                log_file_handle,
                f"OPTIMIZED blog generation completed: {total_blogs_successful} successful, {total_blogs_error} failed, "
                f"in {phase_duration:.2f} seconds ({blogs_per_second:.1f} blogs/sec)\n",
            )
            safe_log_write(
                log_file_handle,
                f"Performance improvement: Adaptive threading, batch processing, reduced logging overhead\n",
            )

    except ROCmBlogsError:
        _BUILD_PHASES["blog_generation"] = time.time() - phase_start_time

        if log_file_handle:
            safe_log_write(log_file_handle, f"ERROR: ROCmBlogsError occurred\n")
            safe_log_write(log_file_handle, f"Traceback: {traceback.format_exc()}\n")

        raise
    except Exception as generation_error:
        error_message = f"Error generating blog pages: {generation_error}"
        log_message("critical", error_message, "general", "__init__")
        log_message(
            "debug", f"Traceback: {traceback.format_exc()}", "general", "__init__"
        )

        if log_file_handle:
            safe_log_write(log_file_handle, f"CRITICAL ERROR: {error_message}\n")
            safe_log_write(log_file_handle, f"Traceback: {traceback.format_exc()}\n")

        _BUILD_PHASES["blog_generation"] = time.time() - phase_start_time
        _CRITICAL_ERROR_OCCURRED = True
        raise ROCmBlogsError(error_message) from generation_error
    finally:
        # Write summary to log file
        if log_file_handle:
            end_time = time.time()
            total_duration = end_time - phase_start_time

            safe_log_write(log_file_handle, "\n" + "=" * 80 + "\n")
            safe_log_write(log_file_handle, "BLOG GENERATION SUMMARY\n")
            safe_log_write(log_file_handle, "-" * 80 + "\n")
            safe_log_write(
                log_file_handle, f"Total blogs processed: {total_blogs_processed}\n"
            )
            safe_log_write(log_file_handle, f"Successful: {total_blogs_successful}\n")
            safe_log_write(log_file_handle, f"Errors: {total_blogs_error}\n")
            safe_log_write(log_file_handle, f"Warnings: {total_blogs_warning}\n")
            safe_log_write(log_file_handle, f"Skipped: {total_blogs_skipped}\n")
            safe_log_write(
                log_file_handle, f"Total time: {total_duration:.2f} seconds\n"
            )

            if all_error_details:
                safe_log_write(log_file_handle, "\nERROR DETAILS:\n")
                safe_log_write(log_file_handle, "-" * 80 + "\n")
                for index, error_detail in enumerate(all_error_details):
                    safe_log_write(
                        log_file_handle, f"{index+1}. Blog: {error_detail['blog']}\n"
                    )
                    safe_log_write(
                        log_file_handle, f"   Error: {error_detail['error']}\n\n"
                    )

            safe_log_close(log_file_handle)


def _generate_banner_slider(rocmblogs, banner_blogs, used_blogs):
    """Generate banner slider content for the index page."""
    try:
        banner_start_time = time.time()
        log_message(
            "info",
            "========== BANNER SLIDER GENERATION STARTED ==========",
            "banner_slider",
            "__init__",
        )
        log_message(
            "info",
            f"Input banner blogs count: {len(banner_blogs)}",
            "banner_slider",
            "__init__",
        )
        log_message(
            "info",
            f"Used blogs count (before banner): {len(used_blogs)}",
            "banner_slider",
            "__init__",
        )

        # Log details about input blogs
        for i, blog in enumerate(banner_blogs):
            blog_title = getattr(blog, "blog_title", "No Title")
            blog_path = getattr(blog, "file_path", "No Path")
            blog_category = getattr(blog, "category", "No Category")
            has_thumbnail = hasattr(blog, "thumbnail")
            has_image_paths = hasattr(blog, "image_paths") and blog.image_paths

            log_message(
                "info", f"Input blog {i+1} (index {i}):", "banner_slider", "__init__"
            )
            log_message("info", f"  Title: '{blog_title}'", "banner_slider", "__init__")
            log_message("info", f"  Path: {blog_path}", "banner_slider", "__init__")
            log_message(
                "info", f"  Category: {blog_category}", "banner_slider", "__init__"
            )
            log_message(
                "info", f"  Has thumbnail: {has_thumbnail}", "banner_slider", "__init__"
            )
            log_message(
                "info",
                f"  Has image_paths: {has_image_paths}",
                "banner_slider",
                "__init__",
            )

            # Check if this blog is already in used_blogs
            already_used = any(
                hasattr(used_blog, "blog_title")
                and getattr(used_blog, "blog_title") == blog_title
                for used_blog in used_blogs
            )
            log_message(
                "info",
                f"  Already used elsewhere: {already_used}",
                "banner_slider",
                "__init__",
            )

        banner_slides = []
        banner_navigation = []
        error_count = 0

        # Generate banner slides and navigation items
        log_message(
            "info",
            "========== PROCESSING BANNER BLOGS ==========",
            "banner_slider",
            "__init__",
        )

        # Track successful generations per index to maintain alignment
        successful_indices = []

        for i, blog in enumerate(banner_blogs):
            blog_title = getattr(blog, "blog_title", "Unknown")
            log_message(
                "info",
                f"\n--- Processing banner blog {i+1}/{len(banner_blogs)} (index {i}) ---",
                "banner_slider",
                "__init__",
            )
            log_message(
                "info", f"Blog title: '{blog_title}'", "banner_slider", "__init__"
            )

            try:
                log_message(
                    "info",
                    f"Step 1: Calling generate_banner_slide for index {i}",
                    "banner_slider",
                    "__init__",
                )
                slide_html = generate_banner_slide(blog, rocmblogs, i, i == 0)
                log_message(
                    "info",
                    f"Step 1 Result: slide_html type={type(slide_html)}, length={len(slide_html) if slide_html else 0}",
                    "banner_slider",
                    "__init__",
                )

                if slide_html:
                    # Log first 200 chars of slide HTML
                    preview = (
                        slide_html[:200] + "..."
                        if len(slide_html) > 200
                        else slide_html
                    )
                    log_message(
                        "debug",
                        f"Slide HTML preview: {preview}",
                        "banner_slider",
                        "__init__",
                    )

                log_message(
                    "info",
                    f"Step 2: Calling generate_banner_navigation_item for index {i}",
                    "banner_slider",
                    "__init__",
                )
                nav_html = generate_banner_navigation_item(blog, i, i == 0)
                log_message(
                    "info",
                    f"Step 2 Result: nav_html type={type(nav_html)}, length={len(nav_html) if nav_html else 0}",
                    "banner_slider",
                    "__init__",
                )

                if nav_html:
                    # Log navigation HTML
                    log_message(
                        "debug",
                        f"Navigation HTML: {nav_html}",
                        "banner_slider",
                        "__init__",
                    )

                # Verify the generated HTML contains expected index
                if nav_html and f'data-index="{i}"' not in nav_html:
                    log_message(
                        "warning",
                        f"Navigation HTML does not contain expected index {i}",
                        "banner_slider",
                        "__init__",
                    )

                # Validate slide HTML
                if not slide_html or not slide_html.strip():
                    log_message(
                        "error",
                        f"[FAILED] EMPTY SLIDE HTML for blog {i+1}: '{getattr(blog, 'blog_title', 'Unknown')}'",
                        "banner_slider",
                        "__init__",
                    )
                    log_message(
                        "error",
                        f"Blog details - Title: '{getattr(blog, 'blog_title', 'N/A')}', Path: '{getattr(blog, 'file_path', 'N/A')}', Has image: {bool(getattr(blog, 'image_paths', None))}",
                        "banner_slider",
                        "__init__",
                    )
                    error_count += 1
                    continue
                else:
                    log_message(
                        "debug",
                        f"[SUCCESS] Valid slide HTML generated (length: {len(slide_html)})",
                        "banner_slider",
                        "__init__",
                    )
                    # Check if slide contains essential elements
                    if '<div class="banner-slide' not in slide_html:
                        log_message(
                            "warning",
                            f"Slide {i+1} may be malformed - missing banner-slide div",
                            "banner_slider",
                            "__init__",
                        )

                # Validate navigation HTML
                if not nav_html or not nav_html.strip():
                    log_message(
                        "error",
                        f"[FAILED] EMPTY NAVIGATION HTML for blog {i+1}: '{getattr(blog, 'blog_title', 'Unknown')}'",
                        "banner_slider",
                        "__init__",
                    )
                    error_count += 1
                    continue
                else:
                    log_message(
                        "debug",
                        f"[SUCCESS] Valid navigation HTML generated (length: {len(nav_html)})",
                        "banner_slider",
                        "__init__",
                    )

                # Successfully generated both slide and navigation
                banner_slides.append(slide_html)
                banner_navigation.append(nav_html)
                successful_indices.append(i)
                # Add banner blogs to the used list to avoid duplication
                used_blogs.append(blog)

                log_message(
                    "info",
                    f"[SUCCESS] Successfully generated banner slide {i+1}: '{getattr(blog, 'blog_title', 'Unknown')}'",
                    "banner_slider",
                    "__init__",
                )
                log_message(
                    "debug",
                    f"Current slides count: {len(banner_slides)}, navigation count: {len(banner_navigation)}",
                    "banner_slider",
                    "__init__",
                )
                log_message(
                    "debug",
                    f"Successful indices so far: {successful_indices}",
                    "banner_slider",
                    "__init__",
                )

            except Exception as blog_error:
                error_count += 1
                log_message(
                    "error",
                    f"[FAILED] EXCEPTION generating banner slide {i+1} (index {i}) for blog '{getattr(blog, 'blog_title', 'Unknown')}': {blog_error}",
                    "banner_slider",
                    "__init__",
                )
                log_message(
                    "error",
                    f"Blog attributes - Title: {getattr(blog, 'blog_title', 'N/A')}, Category: {getattr(blog, 'category', 'N/A')}, Path: {getattr(blog, 'file_path', 'N/A')}",
                    "banner_slider",
                    "__init__",
                )
                log_message(
                    "error",
                    f"Traceback: {traceback.format_exc()}",
                    "banner_slider",
                    "__init__",
                )

                # Log which step failed
                # Clear any partial results to prevent misalignment
                slide_html = None
                nav_html = None

                log_message(
                    "error",
                    f"Skipping blog at index {i} due to error",
                    "banner_slider",
                    "__init__",
                )

        # Final validation and summary
        log_message(
            "info",
            "========== BANNER SLIDER GENERATION SUMMARY ==========",
            "banner_slider",
            "__init__",
        )
        log_message(
            "info", f"Input blogs: {len(banner_blogs)}", "banner_slider", "__init__"
        )
        log_message(
            "info",
            f"Total slides generated: {len(banner_slides)}",
            "banner_slider",
            "__init__",
        )
        log_message(
            "info",
            f"Total navigation items generated: {len(banner_navigation)}",
            "banner_slider",
            "__init__",
        )
        log_message(
            "info",
            f"Successful indices: {successful_indices}",
            "banner_slider",
            "__init__",
        )
        log_message(
            "info", f"Errors encountered: {error_count}", "banner_slider", "__init__"
        )

        # Log which blogs failed
        if len(banner_slides) < len(banner_blogs):
            failed_indices = [
                i for i in range(len(banner_blogs)) if i not in successful_indices
            ]
            log_message(
                "warning",
                f"Failed to generate slides for indices: {failed_indices}",
                "banner_slider",
                "__init__",
            )
            for idx in failed_indices:
                if idx < len(banner_blogs):
                    failed_blog = banner_blogs[idx]
                    log_message(
                        "warning",
                        f"Failed blog at index {idx}: '{getattr(failed_blog, 'blog_title', 'Unknown')}'",
                        "banner_slider",
                        "__init__",
                    )

        if not banner_slides:
            log_message(
                "critical",
                f"[FAILED] NO BANNER SLIDES GENERATED! Input blogs: {len(banner_blogs)}, Errors: {error_count}",
                "banner_slider",
                "__init__",
            )
            log_message(
                "debug",
                f"Traceback: {traceback.format_exc()}",
                "banner_slider",
                "__init__",
            )
            raise ROCmBlogsError("No banner slides were generated")
        elif len(banner_slides) != len(banner_blogs):
            log_message(
                "warning",
                f"[WARNING] MISMATCH: Expected {len(banner_blogs)} slides, generated {len(banner_slides)} slides",
                "banner_slider",
                "__init__",
            )
        else:
            log_message(
                "info",
                "[SUCCESS] All banner slides generated successfully",
                "banner_slider",
                "__init__",
            )

        # Load banner slider template
        try:
            banner_slider_template = import_file(
                "rocm_blogs.templates", "banner-slider.html"
            )
            log_message(
                "debug",
                "Successfully loaded banner slider template",
                "general",
                "__init__",
            )
        except Exception as template_error:
            log_message(
                "critical",
                f"Failed to load banner slider template: {template_error}",
                "general",
                "__init__",
            )
            log_message(
                "debug", f"Traceback: {traceback.format_exc()}", "general", "__init__"
            )
            return ""

        # Fill in the banner slider template
        log_message(
            "info",
            f"Banner HTML generation - Slides: {len(banner_slides)}, Navigation: {len(banner_navigation)}",
            "banner_slider",
            "__init__",
        )

        # Debug: Log first few characters of each slide to verify content
        for i, slide in enumerate(banner_slides):
            slide_preview = slide[:100] + "..." if len(slide) > 100 else slide
            log_message(
                "debug",
                f"Slide {i+1} preview: {slide_preview}",
                "banner_slider",
                "__init__",
            )

            # Check for active class
            if 'class="banner-slide active"' in slide:
                log_message(
                    "debug",
                    f"Slide {i+1} is marked as ACTIVE",
                    "banner_slider",
                    "__init__",
                )
            else:
                log_message(
                    "debug", f"Slide {i+1} is NOT active", "banner_slider", "__init__"
                )

        # Join the slides and navigation HTML
        joined_slides = "\n".join(banner_slides)
        joined_navigation = "\n".join(banner_navigation)

        log_message(
            "debug",
            f"Joined slides HTML length: {len(joined_slides)}",
            "banner_slider",
            "__init__",
        )
        log_message(
            "debug",
            f"Joined navigation HTML length: {len(joined_navigation)}",
            "banner_slider",
            "__init__",
        )

        # Count occurrences of banner-slide in joined content
        slide_count_in_joined = joined_slides.count('<div class="banner-slide')
        nav_count_in_joined = joined_navigation.count("data-index=")
        log_message(
            "info",
            f"Final joined content - Slides: {slide_count_in_joined}, Navigation items: {nav_count_in_joined}",
            "banner_slider",
            "__init__",
        )

        # Debug: Log each individual slide being joined
        for i, slide in enumerate(banner_slides):
            slide_class_count = slide.count('<div class="banner-slide')
            slide_preview = (
                slide[:200].replace("\n", " ") + "..."
                if len(slide) > 200
                else slide.replace("\n", " ")
            )
            log_message(
                "info",
                f"Slide {i}: Contains {slide_class_count} banner-slide divs, Preview: {slide_preview}",
                "banner_slider",
                "__init__",
            )

        banner_html = banner_slider_template.replace(
            "{banner_slides}", joined_slides
        ).replace("{banner_navigation}", joined_navigation)

        # Verify final HTML content
        final_slide_count = banner_html.count('<div class="banner-slide')
        final_nav_count = banner_html.count("data-index=")
        log_message(
            "info",
            f"Final banner HTML - Slides: {final_slide_count}, Navigation items: {final_nav_count}",
            "banner_slider",
            "__init__",
        )

        # Log first 1000 chars of final HTML for debugging
        html_preview = (
            banner_html[:1000] + "..." if len(banner_html) > 1000 else banner_html
        )
        log_message(
            "debug",
            f"Final banner HTML preview: {html_preview}",
            "banner_slider",
            "__init__",
        )

        # Log the actual slide content titles to verify all are present
        slide_titles = []
        for slide in banner_slides:
            title_start = slide.find('<h2 class="h--medium">')
            if title_start != -1:
                title_end = slide.find("</h2>", title_start)
                if title_end != -1:
                    title = slide[
                        title_start + len('<h2 class="h--medium">') : title_end
                    ].strip()
                    slide_titles.append(title)
                else:
                    slide_titles.append("[No title end found]")
            else:
                slide_titles.append("[No title found]")

        log_message(
            "info",
            f"Slide titles in final HTML: {slide_titles}",
            "banner_slider",
            "__init__",
        )

        banner_slider_content = f"""
```{{raw}} html
{banner_html}
```
"""

        banner_elapsed_time = time.time() - banner_start_time

        if error_count > 0:
            log_message(
                "warning",
                f"Generated {len(banner_slides)} banner slides with {error_count} errors",
                "general",
                "__init__",
            )
            log_message(
                "debug", f"Traceback: {traceback.format_exc()}", "general", "__init__"
            )
        else:
            log_message(
                "info",
                f"Successfully generated {len(banner_slides)} banner slides",
                "general",
                "__init__",
            )

        log_message(
            "info",
            "Banner slider generation completed in \033[96m{banner_elapsed_time:.4f} seconds\033[0m",
            "general",
            "__init__",
        )

        return banner_slider_content
    except ROCmBlogsError:
        raise
    except Exception as error:
        log_message(
            "error", f"Error generating banner slider: {error}", "general", "__init__"
        )
        log_message(
            "debug", f"Traceback: {traceback.format_exc()}", "general", "__init__"
        )
        return ""


@profile_function("metadata_generation", save_report=True)
def run_metadata_generator(sphinx_app: Sphinx, rocm_blogs: ROCmBlogs) -> None:
    """Run the metadata generator during the build process."""
    global _CRITICAL_ERROR_OCCURRED
    phase_start_time = time.time()
    phase_name = "metadata_generation"

    # Create a log file for this step
    log_filepath, log_file_handle = create_step_log_file(phase_name)

    # Track statistics for summary
    total_blogs_processed = 0
    total_blogs_successful = 0
    total_blogs_error = 0
    total_blogs_warning = 0
    total_blogs_skipped = 0
    all_error_details = []

    try:
        if log_file_handle:
            safe_log_write(log_file_handle, "Starting metadata generation process\n")
            safe_log_write(log_file_handle, "-" * 80 + "\n\n")

        log_message("info", "Running metadata generator...", "general", "__init__")

        # Use the shared ROCmBlogs instance
        blogs_directory = rocm_blogs.blogs_directory

        if log_file_handle:
            safe_log_write(
                log_file_handle, f"Using shared blogs directory: {blogs_directory}\n"
            )

        # Generate metadata
        if log_file_handle:
            safe_log_write(log_file_handle, "Calling metadata_generator function\n")

        # The metadata_generator function already creates its own log file
        metadata_generator(rocm_blogs)

        if log_file_handle:
            safe_log_write(log_file_handle, "Metadata generation completed\n")
            safe_log_write(
                log_file_handle, "Sorting blogs by vertical after metadata generation\n"
            )

        # Sort blogs by vertical after metadata generation is complete
        rocm_blogs.blogs.sort_blogs_by_vertical()
        log_message(
            "info",
            "Sorted blogs by vertical after metadata generation",
            "general",
            "__init__",
        )

        if log_file_handle:
            safe_log_write(log_file_handle, "Blog vertical sorting completed\n")

        # Record timing information
        phase_duration = time.time() - phase_start_time
        _BUILD_PHASES[phase_name] = phase_duration
        log_message(
            "info",
            "Metadata generation completed in \033[96m{phase_duration:.2f} seconds\033[0m",
            "general",
            "__init__",
        )

        if log_file_handle:
            safe_log_write(
                log_file_handle,
                f"Metadata generation completed in {phase_duration:.2f} seconds\n",
            )

    except ROCmBlogsError:
        # Re-raise ROCmBlogsError to stop the build
        _BUILD_PHASES[phase_name] = time.time() - phase_start_time

        if log_file_handle:
            safe_log_write(log_file_handle, f"ERROR: ROCmBlogsError occurred\n")
            safe_log_write(log_file_handle, f"Traceback: {traceback.format_exc()}\n")

        raise
    except Exception as metadata_error:
        error_message = f"Failed to generate metadata: {metadata_error}"
        log_message("critical", error_message, "general", "__init__")
        log_message(
            "debug", f"Traceback: {traceback.format_exc()}", "general", "__init__"
        )

        if log_file_handle:
            safe_log_write(log_file_handle, f"CRITICAL ERROR: {error_message}\n")
            safe_log_write(log_file_handle, f"Traceback: {traceback.format_exc()}\n")

        _BUILD_PHASES[phase_name] = time.time() - phase_start_time
        _CRITICAL_ERROR_OCCURRED = True
        raise ROCmBlogsError(error_message) from metadata_error
    finally:
        # Write summary to log file
        if log_file_handle:
            end_time = time.time()
            total_duration = end_time - phase_start_time

            safe_log_write(log_file_handle, "\n" + "=" * 80 + "\n")
            safe_log_write(log_file_handle, "METADATA GENERATION SUMMARY\n")
            safe_log_write(log_file_handle, "-" * 80 + "\n")
            safe_log_write(
                log_file_handle, f"Total time: {total_duration:.2f} seconds\n"
            )
            safe_log_write(
                log_file_handle,
                "Note: Detailed metadata generation logs are available in metadata_generation.log\n",
            )

            safe_log_close(log_file_handle)


def process_templates_for_vertical(
    vertical,
    main_grid_items,
    ecosystem_grid_items,
    application_grid_items,
    software_grid_items,
    template_string,
    formatted_vertical,
):
    """Process template for a specific vertical category using Jinja2."""

    context = {
        "vertical": vertical,
        "page_title": f"{vertical} Blogs",
        "page_description": f"Blogs related to {vertical} market vertical",
        "formatted_vertical": formatted_vertical,
        "grid_items": "\n".join(main_grid_items) if main_grid_items else "",
        "eco_grid_items": (
            "\n".join(ecosystem_grid_items) if ecosystem_grid_items else ""
        ),
        "application_grid_items": (
            "\n".join(application_grid_items) if application_grid_items else ""
        ),
        "software_grid_items": (
            "\n".join(software_grid_items) if software_grid_items else ""
        ),
        # Boolean flags for conditional rendering
        "has_recent_blogs": bool(main_grid_items),
        "has_eco_blogs": bool(ecosystem_grid_items),
        "has_application_blogs": bool(application_grid_items),
        "has_software_blogs": bool(software_grid_items),
    }

    # Create a Jinja2 template from the template string
    jinja_template = Template(template_string)

    # Render the template with the context
    return jinja_template.render(**context)


@profile_function("update_posts_file", save_report=True)
def update_posts_file(sphinx_app: Sphinx, rocm_blogs: ROCmBlogs) -> None:
    """Generate paginated posts.md files with lazy-loaded grid items for performance."""
    phase_start_time = time.time()
    phase_name = "update_posts"

    # Create a log file for this step
    log_filepath, log_file_handle = create_step_log_file(phase_name)

    # Track statistics for summary
    total_blogs_processed = 0
    total_blogs_successful = 0
    total_blogs_error = 0
    total_blogs_warning = 0
    total_blogs_skipped = 0
    total_pages_created = 0
    all_error_details = []

    # Configuration
    BLOGS_PER_PAGE = POST_BLOGS_PER_PAGE

    try:
        if log_file_handle:
            safe_log_write(log_file_handle, "Starting posts file generation process\n")
            safe_log_write(log_file_handle, "-" * 80 + "\n\n")

        # Load templates and styles
        template_html = import_file("rocm_blogs.templates", "posts.html")
        pagination_template = import_file("rocm_blogs.templates", "pagination.html")
        css_content = import_file("rocm_blogs.static.css", "index.css")
        pagination_css = import_file("rocm_blogs.static.css", "pagination.css")

        if log_file_handle:
            safe_log_write(
                log_file_handle, "Successfully loaded templates and styles\n"
            )

        # Use the shared ROCmBlogs instance
        blogs_directory = rocm_blogs.blogs_directory

        if log_file_handle:
            safe_log_write(
                log_file_handle, f"Using shared blogs directory: {blogs_directory}\n"
            )

        # Get all blogs first
        all_blogs = rocm_blogs.blogs.get_blogs()

        if log_file_handle:
            safe_log_write(log_file_handle, f"Retrieved {len(all_blogs)} total blogs\n")

        filtered_blogs = []
        skipped_count = 0
        for blog in all_blogs:
            if hasattr(blog, "blogpost") and blog.blogpost:
                filtered_blogs.append(blog)
                total_blogs_processed += 1

                if log_file_handle:
                    safe_log_write(
                        log_file_handle,
                        f"Including blog: {getattr(blog, 'file_path', 'Unknown')}\n",
                    )
            else:
                skipped_count += 1
                total_blogs_skipped += 1
                log_message(
                    "debug",
                    f"Skipping non-blog README file: {getattr(blog, 'file_path', 'Unknown')}",
                    "general",
                    "__init__",
                )

                if log_file_handle:
                    safe_log_write(
                        log_file_handle,
                        f"Skipping non-blog README file: {getattr(blog, 'file_path', 'Unknown')}\n",
                    )

        log_message(
            "info",
            f"Filtered out {skipped_count} non-blog README files, kept {len(filtered_blogs)} genuine blog posts",
            "general",
            "__init__",
        )

        if log_file_handle:
            safe_log_write(
                log_file_handle,
                f"Filtered out {skipped_count} non-blog README files, kept {len(filtered_blogs)} genuine blog posts\n",
            )

        sorted_blogs = sorted(
            filtered_blogs,
            key=lambda blog: getattr(blog, "date", datetime.now()),
            reverse=True,
        )

        if log_file_handle:
            safe_log_write(log_file_handle, "Sorted blogs by date (newest first)\n")

        # Get all filtered blogs and calculate pagination
        all_blogs = sorted_blogs
        total_blogs = len(all_blogs)
        total_pages = max(1, (total_blogs + BLOGS_PER_PAGE - 1) // BLOGS_PER_PAGE)

        log_message(
            "info",
            "Generating {total_pages} paginated posts pages with {BLOGS_PER_PAGE} blogs per page",
            "general",
            "__init__",
        )

        if log_file_handle:
            safe_log_write(
                log_file_handle,
                f"Generating {total_pages} paginated posts pages with {BLOGS_PER_PAGE} blogs per page\n",
            )

        if log_file_handle:
            safe_log_write(
                log_file_handle, "Generating lazy-loaded grid items for all blogs\n"
            )

        all_grid_items = _generate_lazy_loaded_grid_items(rocm_blogs, all_blogs)

        # Check if any grid items were generated
        if not all_grid_items:
            warning_message = "No grid items were generated for posts pages. Skipping page generation."
            log_message("warning", warning_message, "general", "__init__")

            if log_file_handle:
                safe_log_write(log_file_handle, f"WARNING: {warning_message}\n")

            total_blogs_warning += 1
            return

        if log_file_handle:
            safe_log_write(
                log_file_handle, f"Generated {len(all_grid_items)} grid items\n"
            )

        # Current datetime for template
        current_datetime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

        # Generate each page
        if log_file_handle:
            safe_log_write(log_file_handle, "Generating individual pages\n")

        for page_num in range(1, total_pages + 1):
            # Get grid items for this page
            start_index = (page_num - 1) * BLOGS_PER_PAGE
            end_index = min(start_index + BLOGS_PER_PAGE, len(all_grid_items))
            page_grid_items = all_grid_items[start_index:end_index]
            grid_content = "\n".join(page_grid_items)

            if log_file_handle:
                safe_log_write(
                    log_file_handle,
                    f"Processing page {page_num}/{total_pages} with {len(page_grid_items)} grid items\n",
                )

            # Create pagination controls
            pagination_controls = _create_pagination_controls(
                pagination_template, page_num, total_pages, "posts"
            )

            # Add page suffix for pages after the first
            page_title_suffix = f" - Page {page_num}" if page_num > 1 else ""
            page_description_suffix = (
                f" (Page {page_num} of {total_pages})" if page_num > 1 else ""
            )

            # Validate grid content before creating page
            if not page_grid_items:
                log_message(
                    "warning",
                    f"No grid items for page {page_num}/{total_pages}. Skipping page creation.",
                    "general",
                    "__init__",
                )
                if log_file_handle:
                    safe_log_write(
                        log_file_handle,
                        f"WARNING: No grid items for page {page_num}/{total_pages}. Skipping page creation.\n",
                    )
                continue

            # Additional validation: ensure grid content is meaningful
            if not grid_content or not grid_content.strip():
                log_message(
                    "warning",
                    f"Empty or whitespace-only grid content for page {page_num}/{total_pages}. Skipping page creation.",
                    "general",
                    "__init__",
                )
                if log_file_handle:
                    safe_log_write(
                        log_file_handle,
                        f"WARNING: Empty grid content for page {page_num}/{total_pages}. Skipping page creation.\n",
                    )
                continue

            # Create the final page content
            page_content = POSTS_TEMPLATE.format(
                CSS=css_content,
                PAGINATION_CSS=pagination_css,
                HTML=template_html.replace("{grid_items}", grid_content).replace(
                    "{datetime}", current_datetime
                ),
                pagination_controls=pagination_controls,
                page_title_suffix=page_title_suffix,
                page_description_suffix=page_description_suffix,
                current_page=page_num,
            )

            # Final validation: ensure page content is not empty
            if not page_content or len(page_content.strip()) < 100:
                log_message(
                    "warning",
                    f"Generated page content is too small or empty for page {page_num}/{total_pages}. Skipping file creation.",
                    "general",
                    "__init__",
                )
                if log_file_handle:
                    safe_log_write(
                        log_file_handle,
                        f"WARNING: Page content too small for page {page_num}/{total_pages}. Skipping file creation.\n",
                    )
                continue

            # Determine output filename and write the file
            output_filename = (
                "posts.md" if page_num == 1 else f"posts-page{page_num}.md"
            )
            output_path = Path(blogs_directory) / output_filename

            if log_file_handle:
                safe_log_write(log_file_handle, f"Writing page to {output_path}\n")

            with output_path.open("w", encoding="utf-8") as output_file:
                output_file.write(page_content)

            total_pages_created += 1
            total_blogs_successful += len(page_grid_items)

            log_message(
                "info",
                f"Created {output_path} with {len(page_grid_items)} grid items (page {page_num}/{total_pages})",
                "general",
                "__init__",
            )

        # Record timing information
        phase_duration = time.time() - phase_start_time
        _BUILD_PHASES["update_posts"] = phase_duration
        log_message(
            "info",
            "Successfully created {total_pages} paginated posts pages in \033[96m{phase_duration:.2f} seconds\033[0m",
            "general",
            "__init__",
        )

        if log_file_handle:
            safe_log_write(
                log_file_handle,
                f"Successfully created {total_pages} paginated posts pages in {phase_duration:.2f} seconds\n",
            )

    except Exception as page_error:
        error_message = f"Failed to create posts files: {page_error}"
        log_message("critical", error_message, "general", "__init__")
        log_message(
            "debug", f"Traceback: {traceback.format_exc()}", "general", "__init__"
        )

        if log_file_handle:
            safe_log_write(log_file_handle, f"CRITICAL ERROR: {error_message}\n")
            safe_log_write(log_file_handle, f"Traceback: {traceback.format_exc()}\n")

        _BUILD_PHASES["update_posts"] = time.time() - phase_start_time
        _CRITICAL_ERROR_OCCURRED = True
        raise ROCmBlogsError(error_message) from page_error
    finally:
        # Write summary to log file
        if log_file_handle:
            end_time = time.time()
            total_duration = end_time - phase_start_time

            safe_log_write(log_file_handle, "\n" + "=" * 80 + "\n")
            safe_log_write(log_file_handle, "POSTS GENERATION SUMMARY\n")
            safe_log_write(log_file_handle, "-" * 80 + "\n")
            safe_log_write(
                log_file_handle, f"Total blogs processed: {total_blogs_processed}\n"
            )
            safe_log_write(
                log_file_handle, f"Total pages created: {total_pages_created}\n"
            )
            safe_log_write(
                log_file_handle, f"Blogs included in pages: {total_blogs_successful}\n"
            )
            safe_log_write(log_file_handle, f"Errors: {total_blogs_error}\n")
            safe_log_write(log_file_handle, f"Warnings: {total_blogs_warning}\n")
            safe_log_write(log_file_handle, f"Skipped: {total_blogs_skipped}\n")
            safe_log_write(
                log_file_handle, f"Total time: {total_duration:.2f} seconds\n"
            )

            if all_error_details:
                safe_log_write(log_file_handle, "\nERROR DETAILS:\n")
                safe_log_write(log_file_handle, "-" * 80 + "\n")
                for index, error_detail in enumerate(all_error_details):
                    safe_log_write(
                        log_file_handle, f"{index+1}. Blog: {error_detail['blog']}\n"
                    )
                    safe_log_write(
                        log_file_handle, f"   Error: {error_detail['error']}\n\n"
                    )

            safe_log_close(log_file_handle)


def clean_html(html_content):
    """Clean HTML content by removing orphaned grid attributes and empty sections"""

    # Remove any standalone ":margin 2" lines that might be orphaned
    html_content = re.sub(r"\n:margin 2\n", "\n", html_content)

    # Remove any malformed or empty grid sections completely
    # This pattern matches grid sections with no content between the tags
    html_content = re.sub(r"::::{grid}[^\n]*\n:margin 2\n\n::::", "", html_content)

    # Fix stacked colons in grid tags (like ::::::::{grid})
    html_content = re.sub(r":+{grid}", "::::{grid}", html_content)

    return html_content


@profile_function("update_vertical_pages", save_report=True)
def update_vertical_pages(sphinx_app: Sphinx, rocm_blogs: ROCmBlogs) -> None:
    """Generate paginated vertical pages with improved conditional string replacement"""
    phase_name = "update_vertical_pages"
    phase_start_time = time.time()

    log_filepath, log_file_handle = create_step_log_file(phase_name)

    # Import the raw HTML template
    template_html = import_file("rocm_blogs.templates", "vertical.html")
    css_content = import_file("rocm_blogs.static.css", "index.css")
    pagination_template = import_file("rocm_blogs.templates", "pagination.html")
    pagination_css = import_file("rocm_blogs.static.css", "pagination.css")

    # Create the full template with CSS
    index_template = VERTICAL_TEMPLATE.format(CSS=css_content, HTML=template_html)

    # Fix any malformed grid tags in the template
    index_template = index_template.replace(
        "{grid} 1 2 3 4\n:margin 2\n{application_grid_items}\n::::",
        "::::{grid} 1 2 3 4\n:margin 2\n{application_grid_items}\n::::",
    )

    # Use the shared ROCmBlogs instance
    blogs_directory = rocm_blogs.blogs_directory

    if log_file_handle:
        safe_log_write(
            log_file_handle, f"Using shared blogs directory: {blogs_directory}\n"
        )
        safe_log_write(
            log_file_handle, f"Vertical Blogs: {rocm_blogs.blogs.blogs_verticals}\n"
        )
        safe_log_write(log_file_handle, "Generating vertical pages\n")

    try:
        posts_template_html = import_file("rocm_blogs.templates", "posts.html")

        all_blogs = rocm_blogs.blogs.get_blogs()
        filtered_blogs = [
            blog for blog in all_blogs if hasattr(blog, "blogpost") and blog.blogpost
        ]

        sorted_blogs = sorted(
            filtered_blogs,
            key=lambda blog: getattr(blog, "date", datetime.now()),
            reverse=True,
        )

        verticals = rocm_blogs.blogs.blogs_verticals
        for vertical in verticals:
            vertical_blogs = []
            for blog in sorted_blogs:
                if hasattr(blog, "vertical") and blog.vertical:
                    if isinstance(blog.vertical, str):
                        blog_verticals = [
                            v.strip() for v in blog.vertical.split(",") if v.strip()
                        ]
                    else:
                        blog_verticals = blog.vertical

                    if vertical in blog_verticals:
                        vertical_blogs.append(blog)
                elif hasattr(blog, "metadata") and blog.metadata:
                    try:
                        myst_data = blog.metadata.get("myst", {})
                        html_meta = myst_data.get("html_meta", {})
                        vertical_str = html_meta.get("vertical", "")

                        blog_verticals = [
                            v.strip() for v in vertical_str.split(",") if v.strip()
                        ]
                        if blog_verticals and vertical in blog_verticals:
                            vertical_blogs.append(blog)
                    except (AttributeError, KeyError) as e:
                        pass

            if not vertical_blogs:
                if log_file_handle:
                    safe_log_write(
                        log_file_handle, f"No blogs found for vertical: {vertical}\n"
                    )
                continue

            BLOGS_PER_PAGE = POST_BLOGS_PER_PAGE
            total_blogs = len(vertical_blogs)
            total_pages = max(1, (total_blogs + BLOGS_PER_PAGE - 1) // BLOGS_PER_PAGE)

            all_grid_items = _generate_lazy_loaded_grid_items(
                rocm_blogs, vertical_blogs
            )

            # Check if any grid items were generated for this vertical
            if not all_grid_items:
                log_message(
                    "warning",
                    f"No grid items were generated for vertical: {vertical}. Skipping page generation.",
                    "general",
                    "__init__",
                )
                if log_file_handle:
                    safe_log_write(
                        log_file_handle,
                        f"WARNING: No grid items for vertical: {vertical}. Skipping page generation.\n",
                    )
                continue

            current_datetime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

            formatted_vertical = vertical.replace(" ", "-").replace("&", "and").lower()
            formatted_vertical = re.sub(r"[^a-z0-9-]", "", formatted_vertical)
            formatted_vertical = re.sub(r"-+", "-", formatted_vertical)

            for page_num in range(1, total_pages + 1):
                start_index = (page_num - 1) * BLOGS_PER_PAGE
                end_index = min(start_index + BLOGS_PER_PAGE, len(all_grid_items))
                page_grid_items = all_grid_items[start_index:end_index]

                # Validate grid content before creating page
                if not page_grid_items:
                    log_message(
                        "warning",
                        f"No grid items for vertical {vertical} page {page_num}/{total_pages}. Skipping page creation.",
                        "general",
                        "__init__",
                    )
                    if log_file_handle:
                        safe_log_write(
                            log_file_handle,
                            f"WARNING: No grid items for vertical {vertical} page {page_num}/{total_pages}. Skipping page creation.\n",
                        )
                    continue

                grid_content = "\n".join(page_grid_items)

                # Additional validation: ensure grid content is meaningful
                if not grid_content or not grid_content.strip():
                    log_message(
                        "warning",
                        f"Empty grid content for vertical {vertical} page {page_num}/{total_pages}. Skipping page creation.",
                        "general",
                        "__init__",
                    )
                    if log_file_handle:
                        safe_log_write(
                            log_file_handle,
                            f"WARNING: Empty grid content for vertical {vertical} page {page_num}/{total_pages}. Skipping page creation.\n",
                        )
                    continue

                pagination_controls = _create_pagination_controls(
                    pagination_template,
                    page_num,
                    total_pages,
                    f"verticals-{formatted_vertical}",
                )

                # Add page suffix for pages after the first
                page_title_suffix = f" - Page {page_num}" if page_num > 1 else ""
                page_description_suffix = (
                    f" (Page {page_num} of {total_pages})" if page_num > 1 else ""
                )

                # Create the final page content
                page_content = POSTS_TEMPLATE.format(
                    CSS=css_content,
                    PAGINATION_CSS=pagination_css,
                    HTML=posts_template_html.replace(
                        "{grid_items}", grid_content
                    ).replace("{datetime}", current_datetime),
                    pagination_controls=pagination_controls,
                    page_title_suffix=page_title_suffix,
                    page_description_suffix=page_description_suffix,
                    current_page=page_num,
                )

                # Replace the title to include the vertical name
                page_content = page_content.replace(
                    "# Recent Posts", f"# {vertical} Blogs"
                )

                # Final validation: ensure page content is not empty
                if not page_content or len(page_content.strip()) < 100:
                    log_message(
                        "warning",
                        f"Generated page content is too small or empty for vertical {vertical} page {page_num}/{total_pages}. Skipping file creation.",
                        "general",
                        "__init__",
                    )
                    if log_file_handle:
                        safe_log_write(
                            log_file_handle,
                            f"WARNING: Page content too small for vertical {vertical} page {page_num}/{total_pages}. Skipping file creation.\n",
                        )
                    continue

                # Determine output filename and write the file
                output_filename = (
                    f"verticals-{formatted_vertical}.md"
                    if page_num == 1
                    else f"verticals-{formatted_vertical}-page{page_num}.md"
                )
                output_path = Path(blogs_directory) / output_filename

                with output_path.open("w", encoding="utf-8") as output_file:
                    output_file.write(page_content)

                if log_file_handle:
                    safe_log_write(
                        log_file_handle,
                        f"Created {output_path} with {len(page_grid_items)} grid items (page {page_num}/{total_pages})\n",
                    )
    except Exception as verticals_page_error:
        error_message = f"Failed to create verticals pages: {verticals_page_error}"
        log_message("error", error_message, "general", "__init__")
        log_message(
            "debug", f"Traceback: {traceback.format_exc()}", "general", "__init__"
        )

        if log_file_handle:
            safe_log_write(log_file_handle, f"ERROR: {error_message}\n")
            safe_log_write(log_file_handle, f"Traceback: {traceback.format_exc()}\n")

    # Generate individual vertical pages using Jinja2 templating
    verticals = rocm_blogs.blogs.blogs_verticals
    for vertical in verticals:
        used_blogs = []

        vertical_blogs = rocm_blogs.blogs.get_blogs_by_vertical(vertical)
        vertical_blogs.sort(
            key=lambda blog: getattr(blog, "date", datetime.now()), reverse=True
        )

        ecosystem_blogs = [
            blog
            for blog in vertical_blogs
            if hasattr(blog, "category") and blog.category == "Ecosystems and Partners"
        ]
        application_blogs = [
            blog
            for blog in vertical_blogs
            if hasattr(blog, "category") and blog.category == "Applications & models"
        ]
        software_blogs = [
            blog
            for blog in vertical_blogs
            if hasattr(blog, "category")
            and blog.category == "Software tools & optimizations"
        ]

        main_grid_items = _generate_grid_items(
            rocm_blogs, vertical_blogs, MAIN_GRID_BLOGS_COUNT, used_blogs, True, False
        )
        ecosystem_grid_items = _generate_grid_items(
            rocm_blogs,
            ecosystem_blogs,
            CATEGORY_GRID_BLOGS_COUNT,
            used_blogs,
            True,
            False,
        )
        application_grid_items = _generate_grid_items(
            rocm_blogs,
            application_blogs,
            CATEGORY_GRID_BLOGS_COUNT,
            used_blogs,
            True,
            False,
        )
        software_grid_items = _generate_grid_items(
            rocm_blogs,
            software_blogs,
            CATEGORY_GRID_BLOGS_COUNT,
            used_blogs,
            True,
            False,
        )

        # Check if we have any content at all for this vertical
        if (
            not main_grid_items
            and not ecosystem_grid_items
            and not application_grid_items
            and not software_grid_items
        ):
            if log_file_handle:
                safe_log_write(
                    log_file_handle, f"No grid items found for vertical: {vertical}\n"
                )
            continue

        # Format the vertical name for links
        formatted_vertical = vertical.replace(" ", "-").replace("&", "and").lower()
        formatted_vertical = re.sub(r"[^a-z0-9-]", "", formatted_vertical)
        formatted_vertical = re.sub(r"-+", "-", formatted_vertical)

        # Use Jinja2 template rendering instead of string manipulation
        updated_html = process_templates_for_vertical(
            vertical,
            main_grid_items,
            ecosystem_grid_items,
            application_grid_items,
            software_grid_items,
            index_template,
            formatted_vertical,
        )

        output_filename = vertical.replace(" ", "-").lower()
        output_filename = re.sub(r"[^a-z0-9-]", "", output_filename)
        output_filename = f"{output_filename}.md"
        output_path = Path(blogs_directory) / output_filename

        with output_path.open("w", encoding="utf-8") as output_file:
            output_file.write(updated_html)

        if log_file_handle:
            safe_log_write(
                log_file_handle,
                f"Generated vertical page for {vertical} using Jinja2 templating\n",
            )

    # Record timing information
    phase_duration = time.time() - phase_start_time
    _BUILD_PHASES["update_vertical_pages"] = phase_duration
    log_message(
        "info",
        "Vertical pages generation completed in \033[96m{phase_duration:.2f} seconds\033[0m",
        "general",
        "__init__",
    )

    if log_file_handle:
        safe_log_write(
            log_file_handle,
            f"Vertical pages generation completed in {phase_duration:.2f} seconds\n",
        )
        safe_log_close(log_file_handle)


def update_category_verticals(sphinx_app: Sphinx, rocm_blogs: ROCmBlogs) -> None:
    """Generate pages filtered by multiple criteria (category, tags, and market vertical)."""
    phase_start_time = time.time()
    phase_name = "update_category_verticals"

    # Create a log file for this step
    log_filepath, log_file_handle = create_step_log_file(phase_name)

    # Track statistics for summary
    total_pages_processed = 0
    total_pages_successful = 0
    total_pages_error = 0
    all_error_details = []

    try:
        if log_file_handle:
            safe_log_write(
                log_file_handle, "Starting multi-filter pages generation process\n"
            )
            safe_log_write(log_file_handle, "-" * 80 + "\n\n")

        # Load templates and styles
        pagination_template = import_file("rocm_blogs.templates", "pagination.html")
        css_content = import_file("rocm_blogs.static.css", "index.css")
        pagination_css = import_file("rocm_blogs.static.css", "pagination.css")

        if log_file_handle:
            safe_log_write(
                log_file_handle, "Successfully loaded templates and styles\n"
            )

        # Use the shared ROCmBlogs instance
        blogs_directory = rocm_blogs.blogs_directory

        if log_file_handle:
            safe_log_write(
                log_file_handle, f"Using shared blogs directory: {blogs_directory}\n"
            )

        # Sort categories by vertical if not already done
        rocm_blogs.blogs.sort_categories_by_vertical(log_file_handle)

        safe_log_write(
            log_file_handle, "Using shared blog data sorted by category and vertical\n"
        )

        # Get all vertical-category combinations
        keys = rocm_blogs.blogs.get_vertical_category_blog_keys()

        safe_log_write(
            log_file_handle, f"Found {len(keys)} vertical-category combinations\n"
        )

        # Process each vertical-category combination
        for key in keys:
            total_pages_processed += 1
            category, vertical = key

            safe_log_write(
                log_file_handle,
                f"\nProcessing vertical-category: {vertical} - {category}\n",
            )

            # Get blogs for this vertical-category combination
            category_vertical_blogs = rocm_blogs.blogs.get_vertical_category_blogs(
                category, vertical
            )

            if not category_vertical_blogs:
                safe_log_write(
                    log_file_handle,
                    f"No blogs found for category {category} and vertical {vertical}\n",
                )
                continue

            safe_log_write(
                log_file_handle,
                f"Found {len(category_vertical_blogs)} blogs for category {category} and vertical {vertical}\n",
            )

            page_name = f"{vertical}-{category}".lower()
            page_name = page_name.replace("&", "and")
            page_name = page_name.replace(" ", "-")
            page_name = re.sub(r"[^a-z0-9-]", "", page_name)
            page_name = re.sub(r"-+", "-", page_name)

            safe_log_write(
                log_file_handle,
                f"Creating title from vertical and category: {vertical} - {category}\n",
            )

            if vertical.lower() == "ai":
                vertical = "AI"
                title_vertical = vertical
            elif vertical.lower() == "hpc":
                vertical = "HPC"
                title_vertical = vertical
            else:
                # Apply title case to each word
                words_vertical = vertical.split(" ")
                title_vertical = " ".join(word.capitalize() for word in words_vertical)
            title_vertical = title_vertical.replace("and", "&").replace("And", "&")

            safe_log_write(
                log_file_handle, f"Formatted vertical name: {title_vertical}\n"
            )

            words_category = category.split(" ")
            title_category = (
                " ".join(
                    word.upper() if word.lower() == "ai" else word.capitalize()
                    for word in words_category
                )
                .replace("and", "&")
                .replace("And", "&")
            )

            if category.lower() == "ai" or category.lower() == "hpc":
                title_category = title_category.upper()

            if category.lower() == "ai":
                title_category = "AI"
            elif category.lower() == "hpc":
                title_category = "HPC"
            else:
                words_category = category.split(" ")
                title_category = " ".join(word.capitalize() for word in words_category)
            title_category = title_category.replace("and", "&").replace("And", "&")

            filter_info = {
                "name": f"{title_vertical} - {title_category}",
                "template": "category_vertical.html",
                "output_base": page_name,
                "category_key": category,
                "title": f"{title_vertical} - {title_category}",
                "description": f"Explore the latest blogs about {title_category.lower()} in the {title_vertical} market vertical, including case studies, implementations, and best practices.",
                "keywords": f"{vertical}, {category}, AMD, ROCm".replace("and", "&"),
                "filter_criteria": {"category": [category], "vertical": [vertical]},
            }

            safe_log_write(log_file_handle, f"Created filter info: {filter_info}\n")

            try:
                _process_category(
                    filter_info,
                    rocm_blogs,
                    blogs_directory,
                    pagination_template,
                    css_content,
                    pagination_css,
                    time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                    CATEGORY_TEMPLATE,
                    None,
                    log_file_handle,
                )

                total_pages_successful += 1
                safe_log_write(
                    log_file_handle,
                    f"Successfully processed vertical-category: {vertical} - {category}\n",
                )

            except Exception as processing_error:
                error_message = f"Error processing vertical-category {vertical} - {category}: {processing_error}"
                log_message("error", error_message, "general", "__init__")

                if log_file_handle:
                    safe_log_write(log_file_handle, f"ERROR: {error_message}\n")
                    safe_log_write(
                        log_file_handle, f"Traceback: {traceback.format_exc()}\n"
                    )

                total_pages_error += 1
                all_error_details.append(
                    {"page": f"{vertical} - {category}", "error": str(processing_error)}
                )

        safe_log_write(
            log_file_handle, "\nNo additional custom filter pages will be generated\n"
        )

        phase_duration = time.time() - phase_start_time
        _BUILD_PHASES[phase_name] = phase_duration
        log_message(
            "info",
            "Multi-filter pages generation completed in \033[96m{phase_duration:.2f} seconds\033[0m",
            "general",
            "__init__",
        )

        if log_file_handle:
            safe_log_write(
                log_file_handle,
                f"Multi-filter pages generation completed in {phase_duration:.2f} seconds\n",
            )

    except Exception as generation_error:
        error_message = f"Failed to generate multi-filter pages: {generation_error}"
        log_message("critical", error_message, "general", "__init__")
        log_message(
            "debug", f"Traceback: {traceback.format_exc()}", "general", "__init__"
        )

        if log_file_handle:
            safe_log_write(log_file_handle, f"CRITICAL ERROR: {error_message}\n")
            safe_log_write(log_file_handle, f"Traceback: {traceback.format_exc()}\n")

        _BUILD_PHASES[phase_name] = time.time() - phase_start_time
        _CRITICAL_ERROR_OCCURRED = True
        raise ROCmBlogsError(error_message) from generation_error
    finally:
        # Write summary to log file
        if log_file_handle:
            end_time = time.time()
            total_duration = end_time - phase_start_time

            safe_log_write(log_file_handle, "\n" + "=" * 80 + "\n")
            safe_log_write(log_file_handle, "MULTI-FILTER PAGES GENERATION SUMMARY\n")
            safe_log_write(log_file_handle, "-" * 80 + "\n")
            safe_log_write(
                log_file_handle, f"Total pages processed: {total_pages_processed}\n"
            )
            safe_log_write(
                log_file_handle, f"Total pages successful: {total_pages_successful}\n"
            )
            safe_log_write(
                log_file_handle, f"Total pages with errors: {total_pages_error}\n"
            )
            safe_log_write(
                log_file_handle, f"Total time: {total_duration:.2f} seconds\n"
            )

            if all_error_details:
                safe_log_write(log_file_handle, "\nERROR DETAILS:\n")
                safe_log_write(log_file_handle, "-" * 80 + "\n")
                for index, error_detail in enumerate(all_error_details):
                    safe_log_write(
                        log_file_handle, f"{index+1}. Page: {error_detail['page']}\n"
                    )
                    safe_log_write(
                        log_file_handle, f"   Error: {error_detail['error']}\n\n"
                    )

            safe_log_close(log_file_handle)


@profile_function("update_category_pages", save_report=True)
def update_category_pages(sphinx_app: Sphinx, rocm_blogs: ROCmBlogs) -> None:
    """Generate paginated category pages with lazy-loaded grid items for performance."""
    phase_start_time = time.time()
    phase_name = "update_category_pages"

    # Create a log file for this step
    log_filepath, log_file_handle = create_step_log_file(phase_name)

    # Track statistics for summary
    total_categories_processed = 0
    total_categories_successful = 0
    total_categories_error = 0
    total_pages_created = 0
    all_error_details = []

    try:
        if log_file_handle:
            safe_log_write(
                log_file_handle, "Starting category pages generation process\n"
            )
            safe_log_write(log_file_handle, "-" * 80 + "\n\n")

        # Load templates and styles
        pagination_template = import_file("rocm_blogs.templates", "pagination.html")
        css_content = import_file("rocm_blogs.static.css", "index.css")
        pagination_css = import_file("rocm_blogs.static.css", "pagination.css")

        if log_file_handle:
            safe_log_write(
                log_file_handle, "Successfully loaded templates and styles\n"
            )

        # Use the shared ROCmBlogs instance
        blogs_directory = rocm_blogs.blogs_directory

        if log_file_handle:
            safe_log_write(
                log_file_handle, f"Using shared blogs directory: {blogs_directory}\n"
            )

        # Current datetime for template
        current_datetime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

        # Process each category
        if log_file_handle:
            safe_log_write(
                log_file_handle, f"Processing {len(BLOG_CATEGORIES)} categories\n"
            )

        for category_info in BLOG_CATEGORIES:
            total_categories_processed += 1
            category_name = category_info["name"]

            if log_file_handle:
                safe_log_write(
                    log_file_handle, f"\nProcessing category: {category_name}\n"
                )
                safe_log_write(
                    log_file_handle, f"  Output base: {category_info['output_base']}\n"
                )
                safe_log_write(
                    log_file_handle,
                    f"  Category key: {category_info['category_key']}\n",
                )

            category_key = category_info["category_key"]
            category_blogs = rocm_blogs.blogs.blogs_categories.get(category_key, [])

            category_info["title"] = (
                category_info.get("title", category_name)
                .capitalize()
                .replace("and", "&")
                .replace("And", "&")
            )

            try:
                _process_category(
                    category_info,
                    rocm_blogs,
                    blogs_directory,
                    pagination_template,
                    css_content,
                    pagination_css,
                    current_datetime,
                    CATEGORY_TEMPLATE,
                    category_blogs,
                )

                total_categories_successful += 1

                total_pages_created += 1

                if log_file_handle:
                    safe_log_write(
                        log_file_handle,
                        f"Successfully processed category: {category_name}\n",
                    )

            except Exception as category_processing_error:
                error_message = f"Error processing category {category_name}: {category_processing_error}"
                log_message("error", error_message, "general", "__init__")

                if log_file_handle:
                    safe_log_write(log_file_handle, f"ERROR: {error_message}\n")
                    safe_log_write(
                        log_file_handle, f"Traceback: {traceback.format_exc()}\n"
                    )

                total_categories_error += 1
                all_error_details.append(
                    {"category": category_name, "error": str(category_processing_error)}
                )

        # Record timing information
        phase_duration = time.time() - phase_start_time
        _BUILD_PHASES["update_category_pages"] = phase_duration
        log_message(
            "info",
            "Category pages generation completed in \033[96m{phase_duration:.2f} seconds\033[0m",
            "general",
            "__init__",
        )

        if log_file_handle:
            safe_log_write(
                log_file_handle,
                f"Category pages generation completed in {phase_duration:.2f} seconds\n",
            )

    except Exception as category_error:
        error_message = f"Failed to generate category pages: {category_error}"
        log_message("critical", error_message, "general", "__init__")
        log_message(
            "debug", f"Traceback: {traceback.format_exc()}", "general", "__init__"
        )

        if log_file_handle:
            safe_log_write(log_file_handle, f"CRITICAL ERROR: {error_message}\n")
            safe_log_write(log_file_handle, f"Traceback: {traceback.format_exc()}\n")

        _BUILD_PHASES["update_category_pages"] = time.time() - phase_start_time
        _CRITICAL_ERROR_OCCURRED = True
        raise ROCmBlogsError(error_message) from category_error
    finally:
        # Write summary to log file
        if log_file_handle:
            end_time = time.time()
            total_duration = end_time - phase_start_time

            safe_log_write(log_file_handle, "\n" + "=" * 80 + "\n")
            safe_log_write(log_file_handle, "CATEGORY PAGES GENERATION SUMMARY\n")
            safe_log_write(log_file_handle, "-" * 80 + "\n")
            safe_log_write(
                log_file_handle,
                f"Total categories processed: {total_categories_processed}\n",
            )
            safe_log_write(
                log_file_handle,
                f"Total categories successful: {total_categories_successful}\n",
            )
            safe_log_write(
                log_file_handle,
                f"Total categories with errors: {total_categories_error}\n",
            )
            safe_log_write(
                log_file_handle, f"Total pages created: {total_pages_created}\n"
            )
            safe_log_write(
                log_file_handle, f"Total time: {total_duration:.2f} seconds\n"
            )

            if all_error_details:
                safe_log_write(log_file_handle, "\nERROR DETAILS:\n")
                safe_log_write(log_file_handle, "-" * 80 + "\n")
                for index, error_detail in enumerate(all_error_details):
                    safe_log_write(
                        log_file_handle,
                        f"{index+1}. Category: {error_detail['category']}\n",
                    )
                    safe_log_write(
                        log_file_handle, f"   Error: {error_detail['error']}\n\n"
                    )

            safe_log_close(log_file_handle)


@log_project_info
def setup(sphinx_app: Sphinx) -> dict:
    """Set up the ROCm Blogs extension."""
    global _CRITICAL_ERROR_OCCURRED, structured_logger
    phase_start_time = time.time()
    phase_name = "setup"

    sphinx_diagnostics.info(f"Setting up ROCm Blogs extension, version: {__version__}")
    sphinx_diagnostics.info(
        f"Build process started at: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(_BUILD_START_TIME))}"
    )
    append_to_universal_log(f"ROCm Blogs Extension Setup - Version {__version__}")

    # Add configuration values for ROCm Blogs extension
    sphinx_app.add_config_value("rocm_blogs_debug", False, "env", [bool])
    sphinx_app.add_config_value("rocm_blogs_log_level", "INFO", "env", [str])
    sphinx_app.add_config_value("rocm_blogs_log_file", None, "env", [str, type(None)])
    sphinx_app.add_config_value(
        "rocm_blogs_enable_performance_tracking", False, "env", [bool]
    )

    # Initialize logging based on configuration
    _initialize_logging_from_config(sphinx_app)

    log_message(
        "info",
        f"Setting up ROCm Blogs extension, version: {__version__}",
        "setup",
        "extension",
    )
    log_message(
        "info",
        f"Build process started at: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(_BUILD_START_TIME))}",
        "setup",
        "extension",
    )

    try:
        log_message("info", "Setting up ROCm Blogs extension...", "setup", "extension")

        # Set up static files
        _setup_static_files(sphinx_app)

        # Register event handlers
        _register_event_handlers(sphinx_app)

        # Record timing information
        phase_duration = time.time() - phase_start_time
        _BUILD_PHASES[phase_name] = phase_duration
        log_message(
            "info",
            f"ROCm Blogs extension setup completed in {phase_duration:.2f} seconds",
            "setup",
            "extension",
            extra_data={"duration_seconds": phase_duration},
        )

        # Log successful completion
        append_to_universal_log(
            f"Setup completed successfully in {phase_duration:.2f} seconds"
        )

        # Return extension metadata
        return {
            "version": __version__,
            "parallel_read_safe": True,
            "parallel_write_safe": False,
        }

    except Exception as setup_error:
        log_message(
            "critical",
            f"Failed to set up ROCm Blogs extension: {setup_error}",
            "setup",
            "extension",
            error=setup_error,
        )
        append_to_universal_log(f"SETUP FAILED: {setup_error}")
        _BUILD_PHASES[phase_name] = time.time() - phase_start_time
        _CRITICAL_ERROR_OCCURRED = True
        raise ROCmBlogsError(
            f"Failed to set up ROCm Blogs extension: {setup_error}"
        ) from setup_error


# Global variable to store the current Sphinx app for configuration access
_current_sphinx_app = None


def _initialize_logging_from_config(sphinx_app: Sphinx) -> None:
    """Initialize logging based on Sphinx configuration."""
    global structured_logger, _current_sphinx_app

    # Store the Sphinx app globally so other functions can access config
    _current_sphinx_app = sphinx_app

    try:
        # Get configuration values
        debug_enabled = getattr(sphinx_app.config, "rocm_blogs_debug", False)
        log_level = getattr(sphinx_app.config, "rocm_blogs_log_level", "INFO")
        log_file = getattr(sphinx_app.config, "rocm_blogs_log_file", None)
        performance_tracking = getattr(
            sphinx_app.config, "rocm_blogs_enable_performance_tracking", False
        )

        if debug_enabled:
            os.environ["ROCM_BLOGS_DISABLE_LOGGING"] = "false"
            os.environ["ROCM_BLOGS_ENABLE_LOGGING"] = "true"
            os.environ["ROCM_BLOGS_DEBUG"] = "true"
        else:
            os.environ["ROCM_BLOGS_DISABLE_LOGGING"] = "true"
            os.environ["ROCM_BLOGS_DEBUG"] = "false"

        # Set other configuration options
        if log_level:
            os.environ["ROCM_BLOGS_LOG_LEVEL"] = log_level.upper()

        if log_file:
            os.environ["ROCM_BLOGS_LOG_FILE"] = str(log_file)

        if not performance_tracking:
            os.environ["ROCM_BLOGS_ENABLE_PERFORMANCE"] = "false"

        # Reinitialize the structured logger with new configuration
        if LOGGING_AVAILABLE and debug_enabled:
            try:
                log_file_path = (
                    Path(log_file) if log_file else Path("logs/rocm_blogs.log")
                )
                log_level_enum = getattr(LogLevel, log_level.upper(), LogLevel.INFO)

                structured_logger = configure_logging(
                    level=log_level_enum,
                    log_file=log_file_path,
                    enable_console=True,
                    name="rocm_blogs",
                )

                if structured_logger:
                    structured_logger.info(
                        "Logging system reconfigured from Sphinx config",
                        "configuration",
                        "logging_system",
                        extra_data={
                            "debug_enabled": debug_enabled,
                            "log_level": log_level,
                            "log_file": str(log_file_path),
                            "performance_tracking": performance_tracking,
                        },
                    )
            except Exception as logging_error:
                print(f"Failed to reconfigure structured logging: {logging_error}")
                structured_logger = None
        else:
            structured_logger = None

    except Exception as config_error:
        print(f"Error initializing logging from config: {config_error}")
        # Fallback to environment-based configuration
        pass


def is_logging_enabled_from_config():
    """Check if logging is enabled based on Sphinx configuration (overrides environment variables)."""
    global _current_sphinx_app

    if _current_sphinx_app is not None:
        # Simple check: if rocm_blogs_debug = True, logging is enabled
        debug_enabled = getattr(_current_sphinx_app.config, "rocm_blogs_debug", False)
        return debug_enabled

    # Fallback to environment variable check
    import os

    return os.getenv("ROCM_BLOGS_DEBUG", "").lower() in ("true", "1", "yes", "on")


def _setup_static_files(sphinx_app: Sphinx) -> None:
    """Set up static files for the ROCm Blogs extension."""
    try:
        # Add static directory to Sphinx
        static_directory = (Path(__file__).parent / "static").resolve()
        sphinx_app.config.html_static_path.append(str(static_directory))

        # Add JavaScript files
        sphinx_app.add_js_file("js/performance.js")
        sphinx_app.add_js_file("js/image-loading.js")

        try:
            generic_img_path = static_directory / "images" / "generic.jpg"
            if generic_img_path.exists():
                optimize_generic_image(str(generic_img_path))
            else:
                log_message(
                    "warning",
                    f"Generic image not found at {generic_img_path}",
                    "static_files",
                    "__init__",
                )
        except Exception as image_error:
            log_message(
                "warning",
                f"Error optimizing generic image: {image_error}",
                "static_files",
                "__init__",
            )
            log_message(
                "debug",
                f"Traceback: {traceback.format_exc()}",
                "static_files",
                "__init__",
            )
        log_message(
            "info",
            "Static files setup completed successfully",
            "static_files",
            "__init__",
        )

        log_message("info", "Static files setup completed", "general", "__init__")

    except Exception as static_files_error:
        log_message(
            "error",
            f"Error setting up static files: {static_files_error}",
            "static_files",
            "__init__",
        )
        log_message(
            "debug", f"Traceback: {traceback.format_exc()}", "static_files", "__init__"
        )
        raise


def _initialize_shared_rocm_blogs(sphinx_app: Sphinx) -> ROCmBlogs:
    """Initialize a shared ROCmBlogs instance for all functions to use."""
    try:
        log_message(
            "info", "Initializing shared ROCmBlogs instance...", "general", "__init__"
        )

        # Create the shared instance
        rocm_blogs = ROCmBlogs()

        # Find blogs directory
        blogs_directory = rocm_blogs.find_blogs_directory(sphinx_app.srcdir)
        if not blogs_directory:
            error_message = "Could not find blogs directory during initialization"
            log_message("error", error_message, "general", "__init__")
            raise ROCmBlogsError(error_message)

        rocm_blogs.blogs_directory = str(blogs_directory)
        log_message(
            "info", "Found blogs directory: {blogs_directory}", "general", "__init__"
        )

        # Find README files
        readme_count = rocm_blogs.find_readme_files()
        log_message("info", f"Found {readme_count} README files", "general", "__init__")

        # Create blog objects
        rocm_blogs.create_blog_objects()
        log_message("info", "Created blog objects", "general", "__init__")

        # Find author files
        rocm_blogs.find_author_files()
        log_message("info", "Found author files", "general", "__init__")

        # Sort blogs
        rocm_blogs.blogs.sort_blogs_by_date()
        log_message("info", "Sorted blogs by date", "general", "__init__")

        # Extract category keys from BLOG_CATEGORIES to use for sorting
        category_keys = [
            category_info.get("category_key", category_info["name"])
            for category_info in BLOG_CATEGORIES
        ]
        rocm_blogs.blogs.sort_blogs_by_category(category_keys)
        log_message("info", "Sorted blogs by category", "general", "__init__")

        log_message(
            "info",
            "Shared ROCmBlogs instance initialized successfully",
            "general",
            "__init__",
        )
        return rocm_blogs

    except Exception as init_error:
        log_message(
            "error",
            f"Error initializing shared ROCmBlogs instance: {init_error}",
            "general",
            "__init__",
        )
        log_message(
            "debug", f"Traceback: {traceback.format_exc()}", "general", "__init__"
        )
        raise


def _create_event_handler_with_shared_instance(func, rocm_blogs):
    """Create an event handler that passes the shared ROCmBlogs instance to the function."""

    def handler(sphinx_app):
        return func(sphinx_app, rocm_blogs)

    return handler


def _register_event_handlers(sphinx_app: Sphinx) -> None:
    """Register event handlers for the ROCm Blogs extension."""
    try:
        # Initialize shared ROCmBlogs instance
        shared_rocm_blogs = _initialize_shared_rocm_blogs(sphinx_app)

        # Register event handlers with shared instance
        sphinx_app.connect(
            "builder-inited",
            _create_event_handler_with_shared_instance(
                run_metadata_generator, shared_rocm_blogs
            ),
        )

        sphinx_app.connect(
            "builder-inited",
            _create_event_handler_with_shared_instance(
                update_index_file, shared_rocm_blogs
            ),
        )
        sphinx_app.connect(
            "builder-inited",
            _create_event_handler_with_shared_instance(
                blog_generation, shared_rocm_blogs
            ),
        )
        sphinx_app.connect(
            "builder-inited",
            _create_event_handler_with_shared_instance(
                update_posts_file, shared_rocm_blogs
            ),
        )
        sphinx_app.connect(
            "builder-inited",
            _create_event_handler_with_shared_instance(
                update_vertical_pages, shared_rocm_blogs
            ),
        )
        sphinx_app.connect(
            "builder-inited",
            _create_event_handler_with_shared_instance(
                update_category_pages, shared_rocm_blogs
            ),
        )
        sphinx_app.connect(
            "builder-inited",
            _create_event_handler_with_shared_instance(
                update_category_verticals, shared_rocm_blogs
            ),
        )
        sphinx_app.connect("build-finished", log_total_build_time)

        log_message(
            "info",
            "Event handlers registered with shared ROCmBlogs instance",
            "general",
            "__init__",
        )

    except Exception as handler_error:
        log_message(
            "error",
            f"Error registering event handlers: {handler_error}",
            "general",
            "__init__",
        )
        log_message(
            "debug", f"Traceback: {traceback.format_exc()}", "general", "__init__"
        )
        raise
