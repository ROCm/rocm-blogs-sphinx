"""
__init__.py for the rocm_blogs package.

"""

from datetime import datetime
import importlib.resources as pkg_resources
import os
import pathlib
import time
import functools
import traceback
import logging

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from jinja2 import Template
from sphinx.application import Sphinx
from sphinx.util import logging as sphinx_logging
from sphinx.errors import SphinxError

from ._rocmblogs import ROCmBlogs
from ._version import __version__
from .metadata import *
from .banner import *
from .constants import *
from .images import *
from .utils import *
from .process import _generate_grid_items, _generate_lazy_loaded_grid_items, _create_pagination_controls, process_single_blog, _process_category

__all__ = ["Blog", "BlogHolder", "ROCmBlogs", "grid_generation", "metadata_generator", "utils",]

def setup_file_logging():
    """Set up file logging for debug messages while preserving Sphinx logging."""
    try:
        # Create logs directory if it doesn't exist
        logs_dir = Path("../logs")
        logs_dir.mkdir(exist_ok=True)
        
        # Create a file handler that logs debug and higher level messages
        log_file = logs_dir / "rocm_blogs_debug.log"
        file_handler = logging.FileHandler(str(log_file), mode='w')
        file_handler.setLevel(logging.DEBUG)
        
        # Create a formatter and set it for the handler
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)

        # Add handler to the root logger to capture all logs
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)
        root_logger.addHandler(file_handler)

        for _, logger in logging.Logger.manager.loggerDict.items():
            if isinstance(logger, logging.Logger):
                logger.propagate = True

        # Return the log file path
        return log_file
    except Exception as error:
        print(f"Error setting up file logging: {error}")
        traceback.print_exc()
        return None

def create_step_log_file(step_name):
    """Create a log file for a specific build step."""
    try:
        # Create logs directory if it doesn't exist
        logs_dir = Path("logs")
        logs_dir.mkdir(exist_ok=True)
        
        # Create a log file for this step
        log_filepath = logs_dir / f"{step_name}.log"
        log_file_handle = open(log_filepath, "w", encoding="utf-8")
        
        # Write header to the log file
        current_time = datetime.now()
        log_file_handle.write(
            f"ROCm Blogs {step_name.replace('_', ' ').title()} Log - {current_time.isoformat()}\n"
        )
        log_file_handle.write("=" * 80 + "\n\n")
        
        sphinx_diagnostics.info(
            f"Detailed logs for {step_name} will be written to: {log_filepath}"
        )
        
        return log_filepath, log_file_handle
    except Exception as error:
        sphinx_diagnostics.error(
            f"Error creating log file for {step_name}: {error}"
        )
        sphinx_diagnostics.debug(
            f"Traceback: {traceback.format_exc()}"
        )
        return None, None

# Set up the logger
sphinx_diagnostics = sphinx_logging.getLogger(__name__)
log_file = setup_file_logging()
if log_file:
    sphinx_diagnostics.info(
        f"Debug logs will be written to {log_file} while maintaining Sphinx console output"
    )

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
            sphinx_diagnostics.error(
                f"Build completed with errors: {build_exception}"
            )

        if _CRITICAL_ERROR_OCCURRED:
            sphinx_diagnostics.critical(
                "Critical errors occurred during the build process"
            )
            raise ROCmBlogsError("Critical errors occurred during the build process")
    except Exception as error:
        sphinx_diagnostics.critical(
            f"Error in log_total_build_time: {error}"
        )
        sphinx_diagnostics.debug(
            f"Traceback: {traceback.format_exc()}"
        )
        raise


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
            ("other", "Other processing")
        ]
        
        # Log the header
        sphinx_diagnostics.info(
            "=" * 80
        )
        sphinx_diagnostics.info(
            "BUILD PROCESS TIMING SUMMARY:"
        )
        sphinx_diagnostics.info(
            "-" * 80
        )
        
        # Log each phase
        for phase_key, phase_display_name in phases_to_display:
            if phase_key in _BUILD_PHASES:
                phase_duration = _BUILD_PHASES[phase_key]
                percentage = (phase_duration / total_elapsed_time * 100) if total_elapsed_time > 0 else 0
                # Format the phase name to align all timing values
                padded_name = f"{phase_display_name}:".ljust(30)
                sphinx_diagnostics.info(
                    f"{padded_name} \033[96m{phase_duration:.2f} seconds\033[0m ({percentage:.1f}%)"
                )
        
        # Log the footer and total time
        sphinx_diagnostics.info(
            "-" * 80
        )
        sphinx_diagnostics.info(
            f"Total build process completed in \033[92m{total_elapsed_time:.2f} seconds\033[0m"
        )
        sphinx_diagnostics.info(
            "=" * 80
        )
    except Exception as error:
        sphinx_diagnostics.error(
            f"Error logging timing summary: {error}"
        )
        sphinx_diagnostics.debug(
            f"Traceback: {traceback.format_exc()}"
        )

def log_time(func):
    """Decorator to log execution time of functions."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            function_start_time = time.time()
            result = func(*args, **kwargs)
            execution_time = time.time() - function_start_time
            sphinx_diagnostics.info(
                f"{func.__name__} completed in \033[96m{execution_time:.4f} seconds\033[0m"
            )
            return result
        except Exception as error:
            sphinx_diagnostics.error(
                f"Error in {func.__name__}: {error}"
            )
            sphinx_diagnostics.debug(
                f"Traceback: {traceback.format_exc()}"
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

    if log_file_handle:
            log_file_handle.write(f"Starting {phase_name} process\n")

    for blog in rocm_blogs.blogs.get_blogs():
        log_file_handle.write(f"Blog: {blog}\n")

    sphinx_diagnostics.info(
        f"Author files to be updated: {rocm_blogs.author_paths}"
    )

    sphinx_diagnostics.info(
        f"Authors found: {rocm_blogs.blogs.blogs_authors}"
    )

    for author in rocm_blogs.blogs.blogs_authors:
        sphinx_diagnostics.info(
            f"Processing author: {author}"
        )

        name = "-".join(author.split(" ")).lower()

        author_file_path = Path(rocm_blogs.blogs_directory) / f"authors/{name}.md"

        if not author_file_path.exists():
            sphinx_diagnostics.warning(
                f"Author file not found: {author_file_path}"
            )
        else:
            sphinx_diagnostics.info(
                f"Updating author file: {author_file_path}"
            )

            with author_file_path.open("r", encoding="utf-8") as author_file:
                author_content = author_file.read()

            author_blogs = rocm_blogs.blogs.get_blogs_by_author(author)

            author_blogs.sort(key=lambda x: x.date, reverse=True)

            author_grid_items = _generate_grid_items(rocm_blogs, author_blogs, 999, [], False, True)

            # copy all blog images to authors/images directory
            for blog in author_blogs:
                blog_images = blog.image_paths
                for image in blog_images:
                    image_path = Path(image)
                    if image_path.exists():
                        destination_path = Path(rocm_blogs.blogs_directory) / f"authors/images/{image}"
                        destination_path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy(image_path, destination_path)
            try:
                sphinx_diagnostics.info(
                    f"Generating grid items for author: {author}"
                )

                author_css = import_file("rocm_blogs.static.css", "index.css")

                author_content = author_content + "\n" + AUTHOR_TEMPLATE

                updated_author_content = \
                    author_content \
                        .replace("{author_blogs}", "".join(author_grid_items)) \
                        .replace("{author}", author) \
                        .replace("{author_css}", author_css) \

                if "{author_blogs}" in updated_author_content:
                    sphinx_diagnostics.warning(
                        f"Error: replacement failed for {author_file_path}"
                    )
                else:
                    sphinx_diagnostics.info(
                        f"Successfully updated author file: {author_file_path}"
                    )
            except Exception as error:
                sphinx_diagnostics.error(
                    f"Error processing author file: {error}"
                )
                sphinx_diagnostics.debug(
                    f"Traceback: {traceback.format_exc()}"
                )
                _CRITICAL_ERROR_OCCURRED = True
                raise ROCmBlogsError(f"Error processing author file: {error}")

            with author_file_path.open("w", encoding="utf-8") as author_file:
                author_file.write(updated_author_content)

                if author_content != updated_author_content:
                    sphinx_diagnostics.info(
                        f"Author file updated successfully: {author_file_path}"
                    )
                else:
                    sphinx_diagnostics.warning(
                        f"Author file content unchanged: {author_file_path}"
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
            log_file_handle.write("Starting blog statistics generation process\n")
            log_file_handle.write("-" * 80 + "\n\n")
            
        sphinx_diagnostics.info("Generating blog statistics page...")
        
        # Load templates and styles
        blog_statistics_css = import_file("rocm_blogs.static.css", "blog_statistics.css")
        blog_statistics_template = import_file("rocm_blogs.templates", "blog_statistics_template.html")
        
        if log_file_handle:
            log_file_handle.write("Successfully loaded templates and styles\n")
        
        # Get all blogs
        all_blogs = rocm_blogs.blogs.get_blogs()
        
        if log_file_handle:
            log_file_handle.write(f"Retrieved {len(all_blogs)} total blogs\n")
        
        # Filter blogs to only include real blog posts
        filtered_blogs = []
        skipped_count = 0
        
        for blog in all_blogs:
            # Check if this is a genuine blog post (has the blogpost flag set to true)
            if hasattr(blog, "blogpost") and blog.blogpost:
                filtered_blogs.append(blog)
                if log_file_handle:
                    log_file_handle.write(f"Including blog: {getattr(blog, 'file_path', 'Unknown')}\n")
            else:
                skipped_count += 1
                sphinx_diagnostics.debug(
                    f"Skipping non-blog README file for statistics page: {getattr(blog, 'file_path', 'Unknown')}"
                )
                if log_file_handle:
                    log_file_handle.write(f"Skipping non-blog README file: {getattr(blog, 'file_path', 'Unknown')}\n")
        
        sphinx_diagnostics.info(
            f"Filtered out {skipped_count} non-blog README files for statistics page, kept {len(filtered_blogs)} genuine blog posts"
        )
        
        if log_file_handle:
            log_file_handle.write(f"Filtered out {skipped_count} non-blog README files, kept {len(filtered_blogs)} genuine blog posts\n")
        
        # Replace all_blogs with filtered_blogs
        all_blogs = filtered_blogs
        
        if not all_blogs:
            warning_message = "No valid blogs found to generate statistics"
            sphinx_diagnostics.warning(warning_message)
            
            if log_file_handle:
                log_file_handle.write(f"WARNING: {warning_message}\n")
            return
        
        # Generate author statistics
        author_stats = []
        
        if log_file_handle:
            log_file_handle.write("Generating author statistics\n")
        
        for author, blogs in rocm_blogs.blogs.blogs_authors.items():
            # Include all authors, even those with no blogs
            # Sort blogs by date
            sorted_blogs = sorted(blogs, key=lambda b: b.date if b.date else datetime.min, reverse=True)
            
            # Get latest and first blog
            latest_blog = sorted_blogs[0] if sorted_blogs else None
            first_blog = sorted_blogs[-1] if sorted_blogs else None

            if author == "No author":
                author = "ROCm Blogs Team"

            log_file_handle.write(f"Processing author: {author}\n")

            # check if author has a page
            if pathlib.Path.exists(Path(rocm_blogs.blogs_directory) / f"authors/{author.replace(' ', '-').lower()}.md"):
                author_link = f"https://rocm.blogs.amd.com/authors/{author.replace(' ', '-').lower()}.html"
            else:
                author_link = "None"

            log_file_handle.write(f"Author link: {author_link}\n")
            
            # Create author statistics

            author_stat = {
                "name": {
                    "name": author,
                    "href": author_link.format(author=author.replace(" ", "-").lower()),
                },
                "blog_count": len(blogs),
                "latest_blog": {
                    "title": latest_blog.blog_title if latest_blog else "N/A",
                    "date": latest_blog.date.strftime("%B %d, %Y") if latest_blog and latest_blog.date else "N/A",
                    "href": latest_blog.grab_og_href() if latest_blog else "#"
                },
                "first_blog": {
                    "title": first_blog.blog_title if first_blog else "N/A",
                    "date": first_blog.date.strftime("%B %d, %Y") if first_blog and first_blog.date else "N/A",
                    "href": first_blog.grab_og_href() if first_blog else "#"
                }
            }

            if author_link == "None":
                author_stat["name"]["href"] = ""
            
            author_stats.append(author_stat)
        
        # Sort authors by blog count (descending)
        author_stats.sort(key=lambda x: x["blog_count"], reverse=True)
        
        if log_file_handle:
            log_file_handle.write(f"Generated statistics for {len(author_stats)} authors\n")
        
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
            
            # Create blog count cell
            blog_count_cell = f'<td class="blog-count">{blog_count}</td>'
            
            # Create latest blog cell with link (with blog-title class for webkit-clamp)
            latest_blog_cell = f'<td class="date"><a href="{latest_blog["href"]}" class="blog-title">{latest_blog["title"]}</a><br><span class="date-text">{latest_blog["date"]}</span></td>'
            
            # Create first blog cell with link (with blog-title class for webkit-clamp)
            first_blog_cell = f'<td class="date"><a href="{first_blog["href"]}" class="blog-title">{first_blog["title"]}</a><br><span class="date-text">{first_blog["date"]}</span></td>'
            
            # Combine cells into a row
            row = f"<tr>{author_cell}{blog_count_cell}{latest_blog_cell}{first_blog_cell}</tr>"
            author_rows.append(row)
        
        if log_file_handle:
            log_file_handle.write(f"Generated {len(author_rows)} author table rows\n")
        
        # We'll use the monthly data for growth chart as well, so we don't need separate growth data generation
        # The growth chart will calculate cumulative sums from the monthly data in JavaScript
        
        # Generate monthly blog data
        if log_file_handle:
            log_file_handle.write("Generating monthly blog data\n")
        
        # Count blogs by month
        monthly_counts = {}
        
        for blog in all_blogs:
            if hasattr(blog, "date") and blog.date:
                month_key = blog.date.strftime("%Y-%m")
                monthly_counts[month_key] = monthly_counts.get(month_key, 0) + 1
        
        # Get all months of data
        sorted_months = sorted(monthly_counts.keys())
        
        # Format month labels
        monthly_labels = [datetime.strptime(month, "%Y-%m").strftime("%b %Y") for month in sorted_months]
        monthly_data = [monthly_counts[month] for month in sorted_months]
        
        monthly_blog_data = {"labels": monthly_labels, "data": monthly_data}
        
        if log_file_handle:
            log_file_handle.write(f"Generated monthly blog data with {len(monthly_blog_data['labels'])} months\n")
        
        # Generate category distribution data
        if log_file_handle:
            log_file_handle.write("Generating category distribution data\n")
        
        # Count blogs by category
        category_counts = {}
        
        for blog in all_blogs:
            if hasattr(blog, "category") and blog.category:
                category = blog.category
                category_counts[category] = category_counts.get(category, 0) + 1
            else:
                category_counts["Uncategorized"] = category_counts.get("Uncategorized", 0) + 1
        
        # Sort categories by count (descending)
        sorted_categories = sorted(category_counts.items(), key=lambda x: x[1], reverse=True)
        
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
            log_file_handle.write(f"Generated category distribution data with {len(category_distribution['labels'])} categories\n")
        
        # Generate monthly blog data
        if log_file_handle:
            log_file_handle.write("Generating monthly blog data\n")
        
        # Count blogs by month
        monthly_counts = {}
        
        for blog in all_blogs:
            if hasattr(blog, "date") and blog.date:
                month_key = blog.date.strftime("%Y-%m")
                monthly_counts[month_key] = monthly_counts.get(month_key, 0) + 1
        
        # Get all months of data
        sorted_months = sorted(monthly_counts.keys())
        
        # Format month labels
        monthly_labels = [datetime.strptime(month, "%Y-%m").strftime("%b %Y") for month in sorted_months]
        monthly_data = [monthly_counts[month] for month in sorted_months]
        
        monthly_blog_data = {"labels": monthly_labels, "data": monthly_data}
        
        if log_file_handle:
            log_file_handle.write(f"Generated monthly blog data with {len(monthly_blog_data['labels'])} months\n")
        
        # Generate tag distribution data
        if log_file_handle:
            log_file_handle.write("Generating tag distribution data\n")
        
        # Count blogs by tag
        tag_counts = {}
        
        for blog in all_blogs:
            if hasattr(blog, "tags") and blog.tags:
                # Handle tags as a list or as a comma-separated string
                if isinstance(blog.tags, list):
                    tags = blog.tags
                else:
                    tags = [tag.strip() for tag in blog.tags.split(',')]
                
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
            log_file_handle.write(f"Generated tag distribution data with {len(tag_distribution['labels'])} tags\n")
        
        # Combine all statistics data
        statistics_data = {
            "authors": author_stats,
            "categories": category_distribution,
            "monthly": monthly_blog_data,
            "tags": tag_distribution
        }
        
        # Replace placeholders in the template
        if log_file_handle:
            log_file_handle.write("Replacing placeholders in the template\n")
        
        updated_html = blog_statistics_template.replace("{author_rows}", "\n".join(author_rows))
        updated_html = updated_html.replace("{statistics_data}", json.dumps(statistics_data))
        
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
            CSS=blog_statistics_css,
            HTML=updated_html
        )
        
        # Write the statistics page
        output_path = Path(rocm_blogs.blogs_directory) / "blog_statistics.md"
        
        if log_file_handle:
            log_file_handle.write(f"Writing statistics page to {output_path}\n")
        
        with output_path.open("w", encoding="utf-8") as output_file:
            output_file.write(final_content)
        
        # Record timing information
        phase_duration = time.time() - phase_start_time
        _BUILD_PHASES["blog_statistics"] = phase_duration
        sphinx_diagnostics.info(
            f"Successfully generated blog statistics page at {output_path} in \033[96m{phase_duration:.2f} seconds\033[0m"
        )
        
        if log_file_handle:
            log_file_handle.write(f"Successfully generated blog statistics page in {phase_duration:.2f} seconds\n")
        
    except Exception as stats_error:
        error_message = f"Failed to generate blog statistics page: {stats_error}"
        sphinx_diagnostics.error(error_message)
        sphinx_diagnostics.debug(f"Traceback: {traceback.format_exc()}")
        
        if log_file_handle:
            log_file_handle.write(f"ERROR: {error_message}\n")
            log_file_handle.write(f"Traceback: {traceback.format_exc()}\n")
            
        _BUILD_PHASES["blog_statistics"] = time.time() - phase_start_time
        _CRITICAL_ERROR_OCCURRED = True
        raise ROCmBlogsError(error_message) from stats_error
    finally:
        # Write summary to log file
        if log_file_handle:
            end_time = time.time()
            total_duration = end_time - phase_start_time
            
            log_file_handle.write("\n" + "=" * 80 + "\n")
            log_file_handle.write("BLOG STATISTICS GENERATION SUMMARY\n")
            log_file_handle.write("-" * 80 + "\n")
            log_file_handle.write(f"Total time: {total_duration:.2f} seconds\n")
            
            log_file_handle.close()

def update_index_file(sphinx_app: Sphinx) -> None:
    """Update the index file with new blog posts."""
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

    try:
        if log_file_handle:
            log_file_handle.write("Starting index file update process\n")
            log_file_handle.write("-" * 80 + "\n\n")
        
        # Load templates and styles
        template_html = import_file("rocm_blogs.templates", "index.html")
        css_content = import_file("rocm_blogs.static.css", "index.css")
        banner_css_content = import_file("rocm_blogs.static.css", "banner-slider.css")

        if log_file_handle:
            log_file_handle.write("Successfully loaded templates and styles\n")

        # Format the index template
        index_template = INDEX_TEMPLATE.format(
            CSS=css_content, BANNER_CSS=banner_css_content, HTML=template_html
        )
        
        # Initialize ROCmBlogs and load blog data
        rocm_blogs = ROCmBlogs()
        blogs_directory = rocm_blogs.find_blogs_directory(sphinx_app.srcdir)
        
        if not blogs_directory:
            error_message = "Could not find blogs directory"
            sphinx_diagnostics.error(error_message)
            sphinx_diagnostics.debug(f"Traceback: {traceback.format_exc()}")
            
            if log_file_handle:
                log_file_handle.write(f"ERROR: {error_message}\n")
                log_file_handle.write(f"Traceback: {traceback.format_exc()}\n")
                
            _CRITICAL_ERROR_OCCURRED = True
            raise ROCmBlogsError(error_message)
            
        rocm_blogs.blogs_directory = str(blogs_directory)
        
        if log_file_handle:
            log_file_handle.write(f"Found blogs directory: {blogs_directory}\n")
        
        readme_count = rocm_blogs.find_readme_files()
        
        if log_file_handle:
            log_file_handle.write(f"Found {readme_count} README files\n")
            
        rocm_blogs.create_blog_objects()

        rocm_blogs.blogs.write_to_file()

        rocm_blogs.find_author_files()

        update_author_files(sphinx_app, rocm_blogs)

        blog_statistics(sphinx_app, rocm_blogs)
        
        if log_file_handle:
            log_file_handle.write(f"Created blog objects\n")
        
        # Write blogs to CSV file for reference
        blogs_csv_path = Path(blogs_directory) / "blogs.csv"
        rocm_blogs.blogs.write_to_file(str(blogs_csv_path))
        
        if log_file_handle:
            log_file_handle.write(f"Wrote blog information to {blogs_csv_path}\n")
        
        features_csv_path = Path(blogs_directory) / "featured-blogs.csv"
        featured_blogs = []
        
        if features_csv_path.exists():
            if log_file_handle:
                log_file_handle.write(f"Found featured-blogs.csv file at {features_csv_path}\n")
                
            featured_blogs = rocm_blogs.blogs.load_featured_blogs_from_csv(str(features_csv_path))
            
            if log_file_handle:
                log_file_handle.write(f"Loaded {len(featured_blogs)} featured blogs from {features_csv_path}\n")
        else:
            if log_file_handle:
                log_file_handle.write(f"featured-blogs.csv file not found at {features_csv_path}, no featured blogs will be displayed\n")
        
        # Sort the blogs (this happens on all blogs before filtering)
        rocm_blogs.blogs.sort_blogs_by_date()
        
        if log_file_handle:
            log_file_handle.write("Sorted blogs by date\n")
        
        # Extract category keys from BLOG_CATEGORIES to use for sorting
        category_keys = [category_info.get("category_key", category_info["name"]) for category_info in BLOG_CATEGORIES]
        sphinx_diagnostics.info(
            f"Using category keys for sorting: {category_keys}"
        )
        
        if log_file_handle:
            log_file_handle.write(f"Using category keys for sorting: {category_keys}\n")
            
        rocm_blogs.blogs.sort_blogs_by_category(category_keys)
        
        if log_file_handle:
            log_file_handle.write("Sorted blogs by category\n")
        
        # Get all blogs
        all_blogs = rocm_blogs.blogs.get_blogs()
        
        if log_file_handle:
            log_file_handle.write(f"Retrieved {len(all_blogs)} total blogs\n")
        
        # Filter blogs to only include real blog posts
        filtered_blogs = []
        skipped_count = 0
        
        for blog in all_blogs:
            # Check if this is a genuine blog post (has the blogpost flag set to true)
            if hasattr(blog, "blogpost") and blog.blogpost:
                filtered_blogs.append(blog)
                total_blogs_processed += 1
                if log_file_handle:
                    log_file_handle.write(f"Including blog: {getattr(blog, 'file_path', 'Unknown')}\n")
            else:
                skipped_count += 1
                total_blogs_skipped += 1
                sphinx_diagnostics.debug(
                    f"Skipping non-blog README file for index page: {getattr(blog, 'file_path', 'Unknown')}"
                )
                if log_file_handle:
                    log_file_handle.write(f"Skipping non-blog README file: {getattr(blog, 'file_path', 'Unknown')}\n")
        
        sphinx_diagnostics.info(
            f"Filtered out {skipped_count} non-blog README files for index page, kept {len(filtered_blogs)} genuine blog posts"
        )
        
        if log_file_handle:
            log_file_handle.write(f"Filtered out {skipped_count} non-blog README files, kept {len(filtered_blogs)} genuine blog posts\n")
        
        # Replace all_blogs with filtered_blogs
        all_blogs = filtered_blogs
        
        if not all_blogs:
            warning_message = "No valid blogs found to display on index page"
            sphinx_diagnostics.warning(warning_message)
            
            if log_file_handle:
                log_file_handle.write(f"WARNING: {warning_message}\n")
                
            total_blogs_warning += 1
            return
        
        # Track blogs that have been used to avoid duplication
        used_blogs = []

        if featured_blogs:
            max_banner_blogs = min(len(featured_blogs), BANNER_BLOGS_COUNT)
            banner_blogs = featured_blogs[:max_banner_blogs]
        else:
            banner_blogs = all_blogs[:BANNER_BLOGS_COUNT]
        
        if log_file_handle:
            log_file_handle.write(f"Generating banner slider with {len(banner_blogs)} blogs (using featured blogs: {bool(featured_blogs)})\n")
            if featured_blogs:
                log_file_handle.write(f"Using {len(banner_blogs)} featured blogs for banner slider (limited to BANNER_BLOGS_COUNT={BANNER_BLOGS_COUNT})\n")
            else:
                log_file_handle.write(f"No featured blogs found, using first {BANNER_BLOGS_COUNT} blogs for banner slider\n")
            
        # Generate banner slider content
        banner_content = _generate_banner_slider(rocm_blogs, banner_blogs, used_blogs)
        
        if log_file_handle:
            log_file_handle.write("Banner slider generation completed\n")
        
        # Generate grid items for different sections
        sphinx_diagnostics.info(
            "Generating grid items for index page sections"
        )
        
        if log_file_handle:
            log_file_handle.write("Generating grid items for index page sections\n")

        # Create a list of featured blog IDs to exclude them from the main grid
        featured_blog_ids = [id(blog) for blog in featured_blogs]
        
        # Main grid items - will exclude banner blogs and featured blogs
        if log_file_handle:
            log_file_handle.write(f"Generating main grid items with up to {MAIN_GRID_BLOGS_COUNT} blogs\n")
            log_file_handle.write(f"Excluding {len(featured_blog_ids)} featured blogs from main grid\n")
            
        # Filter out featured blogs from the main grid
        non_featured_blogs = [blog for blog in all_blogs if id(blog) not in featured_blog_ids]
        main_grid_items = _generate_grid_items(rocm_blogs, non_featured_blogs, MAIN_GRID_BLOGS_COUNT, used_blogs, True, False)
        
        if log_file_handle:
            log_file_handle.write(f"Generated {len(main_grid_items)} main grid items\n")
        
        # Filter blogs by category and ensure they're all blog posts
        ecosystem_blogs = [blog for blog in all_blogs if hasattr(blog, "category") and blog.category == "Ecosystems and Partners"]
        application_blogs = [blog for blog in all_blogs if hasattr(blog, "category") and blog.category == "Applications & models"]
        software_blogs = [blog for blog in all_blogs if hasattr(blog, "category") and blog.category == "Software tools & optimizations"]
        
        if log_file_handle:
            log_file_handle.write(f"Filtered blogs by category:\n")
            log_file_handle.write(f"  - Ecosystems and Partners: {len(ecosystem_blogs)} blogs\n")
            log_file_handle.write(f"  - Applications & models: {len(application_blogs)} blogs\n")
            log_file_handle.write(f"  - Software tools & optimizations: {len(software_blogs)} blogs\n")
        
        # Generate grid items for each category
        if log_file_handle:
            log_file_handle.write(f"Generating category grid items with up to {CATEGORY_GRID_BLOGS_COUNT} blogs per category\n")
            
        ecosystem_grid_items = _generate_grid_items(rocm_blogs, ecosystem_blogs, CATEGORY_GRID_BLOGS_COUNT, used_blogs, True, False)
        application_grid_items = _generate_grid_items(rocm_blogs, application_blogs, CATEGORY_GRID_BLOGS_COUNT, used_blogs, True, False)
        software_grid_items = _generate_grid_items(rocm_blogs, software_blogs, CATEGORY_GRID_BLOGS_COUNT, used_blogs, True, False)
        
        if log_file_handle:
            log_file_handle.write(f"Generated category grid items:\n")
            log_file_handle.write(f"  - Ecosystems and Partners: {len(ecosystem_grid_items)} grid items\n")
            log_file_handle.write(f"  - Applications & models: {len(application_grid_items)} grid items\n")
            log_file_handle.write(f"  - Software tools & optimizations: {len(software_grid_items)} grid items\n")
        
        # Generate featured grid items if we have featured blogs
        featured_grid_items = []
        if featured_blogs:
            if log_file_handle:
                log_file_handle.write(f"Generating featured grid items with {len(featured_blogs)} featured blogs\n")
                
            try:
                # Only generate grid items if we have at least one featured blog
                if len(featured_blogs) > 0:
                    featured_grid_items = _generate_grid_items(rocm_blogs, featured_blogs, len(featured_blogs), used_blogs, False, False)
                    
                    if log_file_handle:
                        log_file_handle.write(f"Generated {len(featured_grid_items)} featured grid items\n")
                else:
                    if log_file_handle:
                        log_file_handle.write("Featured blogs list is empty, skipping grid item generation\n")
            except Exception as featured_error:
                # Log the error but continue with the build
                sphinx_diagnostics.warning(
                    f"Error generating featured grid items: {featured_error}. Continuing without featured blogs."
                )
                sphinx_diagnostics.debug(
                    f"Traceback: {traceback.format_exc()}"
                )
                
                if log_file_handle:
                    log_file_handle.write(f"WARNING: Error generating featured grid items: {featured_error}\n")
                    log_file_handle.write(f"Traceback: {traceback.format_exc()}\n")
                    log_file_handle.write("Continuing without featured blogs\n")
        else:
            if log_file_handle:
                log_file_handle.write("No featured blogs to display\n")
        
        # Replace placeholders in the template
        if log_file_handle:
            log_file_handle.write("Replacing placeholders in the template\n")
            
        updated_html = (
            index_template
            .replace("{grid_items}", "\n".join(main_grid_items))
            .replace("{eco_grid_items}", "\n".join(ecosystem_grid_items) if ecosystem_grid_items else "")
            .replace("{application_grid_items}", "\n".join(application_grid_items))
            .replace("{software_grid_items}", "\n".join(software_grid_items))
            .replace("{featured_grid_items}", "\n".join(featured_grid_items))
            .replace("{banner_slider}", banner_content)
        )
        
        # Write the updated HTML to blogs/index.md
        output_path = Path(blogs_directory) / "index.md"
        
        if log_file_handle:
            log_file_handle.write(f"Writing updated HTML to {output_path}\n")
            
        with output_path.open("w", encoding="utf-8") as output_file:
            output_file.write(updated_html)
            
        total_blogs_successful += 1
        
        # Record timing information
        phase_duration = time.time() - phase_start_time
        _BUILD_PHASES[phase_name] = phase_duration
        sphinx_diagnostics.info(
            f"Successfully updated {output_path} with new content in \033[96m{phase_duration:.2f} seconds\033[0m"
        )
        
        if log_file_handle:
            log_file_handle.write(f"Successfully updated {output_path} with new content in {phase_duration:.2f} seconds\n")
        
    except ROCmBlogsError:
        # Re-raise ROCmBlogsError to stop the build
        _BUILD_PHASES[phase_name] = time.time() - phase_start_time
        
        if log_file_handle:
            log_file_handle.write(f"ERROR: ROCmBlogsError occurred\n")
            log_file_handle.write(f"Traceback: {traceback.format_exc()}\n")
            
        raise
    except Exception as error:
        error_message = f"Error updating index file: {error}"
        sphinx_diagnostics.critical(error_message)
        sphinx_diagnostics.debug(f"Traceback: {traceback.format_exc()}")
        
        if log_file_handle:
            log_file_handle.write(f"CRITICAL ERROR: {error_message}\n")
            log_file_handle.write(f"Traceback: {traceback.format_exc()}\n")
            
        _BUILD_PHASES[phase_name] = time.time() - phase_start_time
        _CRITICAL_ERROR_OCCURRED = True
        raise ROCmBlogsError(error_message) from error
    finally:
        # Write summary to log file
        if log_file_handle:
            end_time = time.time()
            total_duration = end_time - phase_start_time
            
            log_file_handle.write("\n" + "=" * 80 + "\n")
            log_file_handle.write("INDEX UPDATE SUMMARY\n")
            log_file_handle.write("-" * 80 + "\n")
            log_file_handle.write(f"Total blogs processed: {total_blogs_processed}\n")
            log_file_handle.write(f"Successful: {total_blogs_successful}\n")
            log_file_handle.write(f"Errors: {total_blogs_error}\n")
            log_file_handle.write(f"Warnings: {total_blogs_warning}\n")
            log_file_handle.write(f"Skipped: {total_blogs_skipped}\n")
            log_file_handle.write(f"Total time: {total_duration:.2f} seconds\n")
            
            if all_error_details:
                log_file_handle.write("\nERROR DETAILS:\n")
                log_file_handle.write("-" * 80 + "\n")
                for index, error_detail in enumerate(all_error_details):
                    log_file_handle.write(f"{index+1}. Blog: {error_detail['blog']}\n")
                    log_file_handle.write(f"   Error: {error_detail['error']}\n\n")
            
            log_file_handle.close()

def blog_generation(sphinx_app: Sphinx) -> None:
    """Generate blog pages with styling and metadata."""
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
            log_file_handle.write("Starting blog generation process\n")
            log_file_handle.write("-" * 80 + "\n\n")
            
        # Initialize ROCmBlogs and load blog data
        build_env = sphinx_app.builder.env
        source_dir = Path(build_env.srcdir)
        rocm_blogs = ROCmBlogs()

        rocm_blogs.sphinx_app = sphinx_app
        rocm_blogs.sphinx_env = build_env
        
        # Find and process blogs
        blogs_directory = rocm_blogs.find_blogs_directory(str(source_dir))
        if not blogs_directory:
            error_message = "Could not find blogs directory"
            sphinx_diagnostics.error(error_message)
            sphinx_diagnostics.debug(f"Traceback: {traceback.format_exc()}")
            
            if log_file_handle:
                log_file_handle.write(f"ERROR: {error_message}\n")
                log_file_handle.write(f"Traceback: {traceback.format_exc()}\n")
                
            _CRITICAL_ERROR_OCCURRED = True
            raise ROCmBlogsError(error_message)
            
        rocm_blogs.blogs_directory = str(blogs_directory)

        rocm_blogs.find_author_files()
        
        if log_file_handle:
            log_file_handle.write(f"Found blogs directory: {blogs_directory}\n")
            
        readme_count = rocm_blogs.find_readme_files()
        
        if log_file_handle:
            log_file_handle.write(f"Found {readme_count} README files\n")
            
        rocm_blogs.create_blog_objects()
        
        if log_file_handle:
            log_file_handle.write("Created blog objects\n")
            
        rocm_blogs.blogs.sort_blogs_by_date()
        
        if log_file_handle:
            log_file_handle.write("Sorted blogs by date\n")
        
        # Get all blogs
        blog_list = rocm_blogs.blogs.get_blogs()
        total_blogs = len(blog_list)
        
        if not blog_list:
            warning_message = "No blogs found to process"
            sphinx_diagnostics.warning(warning_message)
            
            if log_file_handle:
                log_file_handle.write(f"WARNING: {warning_message}\n")
                
            total_blogs_warning += 1
            return
            
        max_workers = os.cpu_count()
        sphinx_diagnostics.info(
            f"Processing {total_blogs} blogs with {max_workers} workers"
        )
        
        if log_file_handle:
            log_file_handle.write(f"Processing {total_blogs} blogs with {max_workers} workers\n")

        # Process blogs with thread pool
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Create a list of futures
            processing_futures = []
            
            if log_file_handle:
                log_file_handle.write("Submitting blog processing tasks to thread pool\n")
                
            for blog_index, blog in enumerate(blog_list):
                future = executor.submit(process_single_blog, blog, rocm_blogs)
                processing_futures.append((blog_index, blog, future))
                total_blogs_processed += 1
                
                if log_file_handle:
                    log_file_handle.write(f"Submitted blog {blog_index + 1}/{total_blogs}: {getattr(blog, 'file_path', 'Unknown')}\n")

            # Process results as they complete
            if log_file_handle:
                log_file_handle.write("Processing results as they complete\n")
                
            for blog_index, blog, future in processing_futures:
                try:
                    future.result()  # This will raise any exceptions from the thread
                    total_blogs_successful += 1
                    
                    if log_file_handle:
                        log_file_handle.write(f"Successfully processed blog {blog_index + 1}/{total_blogs}: {getattr(blog, 'file_path', 'Unknown')}\n")
                        
                except Exception as processing_error:
                    error_message = f"Error processing blog: {processing_error}"
                    sphinx_diagnostics.warning(error_message)
                    
                    if log_file_handle:
                        log_file_handle.write(f"WARNING: Error processing blog {blog_index + 1}/{total_blogs}: {getattr(blog, 'file_path', 'Unknown')}\n")
                        log_file_handle.write(f"  Error: {processing_error}\n")
                        log_file_handle.write(f"  Traceback: {traceback.format_exc()}\n")
                        
                    total_blogs_error += 1
                    all_error_details.append({"blog": getattr(blog, 'file_path', 'Unknown'), "error": str(processing_error)})

        # Log completion statistics
        phase_end_time = time.time()
        phase_duration = phase_end_time - phase_start_time
        _BUILD_PHASES["blog_generation"] = phase_duration

        # If total errors account for more than 25% of total blogs, raise a critical error
        error_threshold = total_blogs * 0.25
        if total_blogs_error > error_threshold:
            error_message = f"Too many errors occurred during blog generation: {total_blogs_error} errors"
            sphinx_diagnostics.critical(error_message)
            sphinx_diagnostics.debug(f"Traceback: {traceback.format_exc()}")
            
            if log_file_handle:
                log_file_handle.write(f"CRITICAL ERROR: {error_message}\n")
                
            _CRITICAL_ERROR_OCCURRED = True
            raise ROCmBlogsError(error_message)
        
        sphinx_diagnostics.info(
            f"Blog generation completed: {total_blogs_successful} successful, {total_blogs_error} failed, "
            f"in \033[96m{phase_duration:.2f} seconds\033[0m"
        )
        
        if log_file_handle:
            log_file_handle.write(f"Blog generation completed: {total_blogs_successful} successful, {total_blogs_error} failed, in {phase_duration:.2f} seconds\n")
            
    except ROCmBlogsError:
        _BUILD_PHASES["blog_generation"] = time.time() - phase_start_time
        
        if log_file_handle:
            log_file_handle.write(f"ERROR: ROCmBlogsError occurred\n")
            log_file_handle.write(f"Traceback: {traceback.format_exc()}\n")
            
        raise
    except Exception as generation_error:
        error_message = f"Error generating blog pages: {generation_error}"
        sphinx_diagnostics.critical(error_message)
        sphinx_diagnostics.debug(f"Traceback: {traceback.format_exc()}")
        
        if log_file_handle:
            log_file_handle.write(f"CRITICAL ERROR: {error_message}\n")
            log_file_handle.write(f"Traceback: {traceback.format_exc()}\n")
            
        _BUILD_PHASES["blog_generation"] = time.time() - phase_start_time
        _CRITICAL_ERROR_OCCURRED = True
        raise ROCmBlogsError(error_message) from generation_error
    finally:
        # Write summary to log file
        if log_file_handle:
            end_time = time.time()
            total_duration = end_time - phase_start_time
            
            log_file_handle.write("\n" + "=" * 80 + "\n")
            log_file_handle.write("BLOG GENERATION SUMMARY\n")
            log_file_handle.write("-" * 80 + "\n")
            log_file_handle.write(f"Total blogs processed: {total_blogs_processed}\n")
            log_file_handle.write(f"Successful: {total_blogs_successful}\n")
            log_file_handle.write(f"Errors: {total_blogs_error}\n")
            log_file_handle.write(f"Warnings: {total_blogs_warning}\n")
            log_file_handle.write(f"Skipped: {total_blogs_skipped}\n")
            log_file_handle.write(f"Total time: {total_duration:.2f} seconds\n")
            
            if all_error_details:
                log_file_handle.write("\nERROR DETAILS:\n")
                log_file_handle.write("-" * 80 + "\n")
                for index, error_detail in enumerate(all_error_details):
                    log_file_handle.write(f"{index+1}. Blog: {error_detail['blog']}\n")
                    log_file_handle.write(f"   Error: {error_detail['error']}\n\n")
            
            log_file_handle.close()
    
def _generate_banner_slider(rocmblogs, banner_blogs, used_blogs):
    """ Generate banner slider content for the index page. """
    try:
        banner_start_time = time.time()
        sphinx_diagnostics.info("Generating banner slider content")
        
        # Generate banner slides and navigation items directly without parameter checking
        # The functions are already defined with the correct parameters
        
        banner_slides = []
        banner_navigation = []
        error_count = 0
        
        # Generate banner slides and navigation items
        for i, blog in enumerate(banner_blogs):
            try:
                slide_html = generate_banner_slide(blog, rocmblogs, i, i == 0)
                nav_html = generate_banner_navigation_item(blog, i, i == 0)
                
                if not slide_html or not slide_html.strip():
                    sphinx_diagnostics.warning(f"Empty banner slide HTML generated for blog: {getattr(blog, 'blog_title', 'Unknown')}")
                    error_count += 1
                    continue
                
                if not nav_html or not nav_html.strip():
                    sphinx_diagnostics.warning(f"Empty banner navigation HTML generated for blog: {getattr(blog, 'blog_title', 'Unknown')}")
                    error_count += 1
                    continue
                
                banner_slides.append(slide_html)
                banner_navigation.append(nav_html)
                # Add banner blogs to the used list to avoid duplication
                used_blogs.append(blog)
                sphinx_diagnostics.debug(f"Successfully generated banner slide for blog: {getattr(blog, 'blog_title', 'Unknown')}")
            except Exception as blog_error:
                error_count += 1
                sphinx_diagnostics.error(f"Error generating banner slide for blog {getattr(blog, 'blog_title', 'Unknown')}: {blog_error}")
                sphinx_diagnostics.debug(f"Traceback: {traceback.format_exc()}")
        
        # Check if any slides were generated
        if not banner_slides:
            sphinx_diagnostics.critical("No banner slides were generated. Check for errors in the banner slide generation functions.")
            sphinx_diagnostics.debug(f"Traceback: {traceback.format_exc()}")
            raise ROCmBlogsError("No banner slides were generated")
        
        # Load banner slider template
        try:
            banner_slider_template = import_file("rocm_blogs.templates", "banner-slider.html")
            sphinx_diagnostics.debug("Successfully loaded banner slider template")
        except Exception as template_error:
            sphinx_diagnostics.critical(f"Failed to load banner slider template: {template_error}")
            sphinx_diagnostics.debug(f"Traceback: {traceback.format_exc()}")
            return ""
        
        # Fill in the banner slider template
        banner_html = (
            banner_slider_template
            .replace("{banner_slides}", "\n".join(banner_slides))
            .replace("{banner_navigation}", "\n".join(banner_navigation))
        )

        banner_slider_content = f"""
```{{raw}} html
{banner_html}
```
"""
        
        banner_elapsed_time = time.time() - banner_start_time
        
        if error_count > 0:
            sphinx_diagnostics.warning(f"Generated {len(banner_slides)} banner slides with {error_count} errors")
            sphinx_diagnostics.debug(f"Traceback: {traceback.format_exc()}")
        else:
            sphinx_diagnostics.info(f"Successfully generated {len(banner_slides)} banner slides")
            
        sphinx_diagnostics.info(f"Banner slider generation completed in \033[96m{banner_elapsed_time:.4f} seconds\033[0m")
        
        return banner_slider_content
    except ROCmBlogsError:
        raise
    except Exception as error:
        sphinx_diagnostics.error(f"Error generating banner slider: {error}")
        sphinx_diagnostics.debug(f"Traceback: {traceback.format_exc()}")
        return ""

def run_metadata_generator(sphinx_app: Sphinx) -> None:
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
            log_file_handle.write("Starting metadata generation process\n")
            log_file_handle.write("-" * 80 + "\n\n")
            
        sphinx_diagnostics.info(
            "Running metadata generator..."
        )

        # Initialize ROCmBlogs and load blog data
        rocm_blogs = ROCmBlogs()
        blogs_directory = rocm_blogs.find_blogs_directory(sphinx_app.srcdir)
        
        if not blogs_directory:
            error_message = "Could not find blogs directory"
            sphinx_diagnostics.error(error_message)
            
            if log_file_handle:
                log_file_handle.write(f"ERROR: {error_message}\n")
                
            _CRITICAL_ERROR_OCCURRED = True
            raise ROCmBlogsError(error_message)
            
        rocm_blogs.blogs_directory = str(blogs_directory)
        
        if log_file_handle:
            log_file_handle.write(f"Found blogs directory: {blogs_directory}\n")
        
        # Find and process readme files
        readme_count = rocm_blogs.find_readme_files()
        sphinx_diagnostics.info(
            f"Found {readme_count} readme files to process"
        )
        
        if log_file_handle:
            log_file_handle.write(f"Found {readme_count} readme files to process\n")
        
        # Generate metadata
        if log_file_handle:
            log_file_handle.write("Calling metadata_generator function\n")
            
        # The metadata_generator function already creates its own log file
        metadata_generator(rocm_blogs)
        
        if log_file_handle:
            log_file_handle.write("Metadata generation completed\n")
        
        # Record timing information
        phase_duration = time.time() - phase_start_time
        _BUILD_PHASES[phase_name] = phase_duration
        sphinx_diagnostics.info(
            f"Metadata generation completed in \033[96m{phase_duration:.2f} seconds\033[0m"
        )
        
        if log_file_handle:
            log_file_handle.write(f"Metadata generation completed in {phase_duration:.2f} seconds\n")
        
    except ROCmBlogsError:
        # Re-raise ROCmBlogsError to stop the build
        _BUILD_PHASES[phase_name] = time.time() - phase_start_time
        
        if log_file_handle:
            log_file_handle.write(f"ERROR: ROCmBlogsError occurred\n")
            log_file_handle.write(f"Traceback: {traceback.format_exc()}\n")
            
        raise
    except Exception as metadata_error:
        error_message = f"Failed to generate metadata: {metadata_error}"
        sphinx_diagnostics.critical(error_message)
        sphinx_diagnostics.debug(f"Traceback: {traceback.format_exc()}")
        
        if log_file_handle:
            log_file_handle.write(f"CRITICAL ERROR: {error_message}\n")
            log_file_handle.write(f"Traceback: {traceback.format_exc()}\n")
            
        _BUILD_PHASES[phase_name] = time.time() - phase_start_time
        _CRITICAL_ERROR_OCCURRED = True
        raise ROCmBlogsError(error_message) from metadata_error
    finally:
        # Write summary to log file
        if log_file_handle:
            end_time = time.time()
            total_duration = end_time - phase_start_time
            
            log_file_handle.write("\n" + "=" * 80 + "\n")
            log_file_handle.write("METADATA GENERATION SUMMARY\n")
            log_file_handle.write("-" * 80 + "\n")
            log_file_handle.write(f"Total time: {total_duration:.2f} seconds\n")
            log_file_handle.write("Note: Detailed metadata generation logs are available in metadata_generation.log\n")
            
            log_file_handle.close()

def process_templates_for_vertical(vertical, main_grid_items, ecosystem_grid_items, 
                                  application_grid_items, software_grid_items,
                                  template_string):
    """Process template for a specific vertical category using Jinja2."""

    context = {
        'vertical': vertical,
        'PAGE_TITLE': f"{vertical} Blogs",
        'PAGE_DESCRIPTION': f"Blogs related to {vertical} market vertical",
        'grid_items': "\n".join(main_grid_items) if main_grid_items else "",
        'eco_grid_items': "\n".join(ecosystem_grid_items) if ecosystem_grid_items else "",
        'application_grid_items': "\n".join(application_grid_items) if application_grid_items else "",
        'software_grid_items': "\n".join(software_grid_items) if software_grid_items else ""
    }
    
    # Create a Jinja2 template from the template string
    jinja_template = Template(template_string)
    
    # Render the template with the context
    return jinja_template.render(**context)

def update_posts_file(sphinx_app: Sphinx) -> None:
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
            log_file_handle.write("Starting posts file generation process\n")
            log_file_handle.write("-" * 80 + "\n\n")
            
        # Load templates and styles
        template_html = import_file("rocm_blogs.templates", "posts.html")
        pagination_template = import_file("rocm_blogs.templates", "pagination.html")
        css_content = import_file("rocm_blogs.static.css", "index.css")
        pagination_css = import_file("rocm_blogs.static.css", "pagination.css")
        
        if log_file_handle:
            log_file_handle.write("Successfully loaded templates and styles\n")
        
        # Initialize ROCmBlogs and load blog data
        rocm_blogs = ROCmBlogs()
        blogs_directory = rocm_blogs.find_blogs_directory(sphinx_app.srcdir)
        
        if not blogs_directory:
            error_message = "Could not find blogs directory"
            sphinx_diagnostics.error(error_message)
            
            if log_file_handle:
                log_file_handle.write(f"ERROR: {error_message}\n")
                
            _CRITICAL_ERROR_OCCURRED = True
            raise ROCmBlogsError(error_message)
            
        rocm_blogs.blogs_directory = str(blogs_directory)
        
        if log_file_handle:
            log_file_handle.write(f"Found blogs directory: {blogs_directory}\n")
            
        readme_count = rocm_blogs.find_readme_files()
        
        if log_file_handle:
            log_file_handle.write(f"Found {readme_count} README files\n")
            
        rocm_blogs.create_blog_objects()
        
        if log_file_handle:
            log_file_handle.write("Created blog objects\n")
        
        # Get all blogs first
        all_blogs = rocm_blogs.blogs.get_blogs()
        
        if log_file_handle:
            log_file_handle.write(f"Retrieved {len(all_blogs)} total blogs\n")
        
        # Filter blogs to only include real blog posts
        filtered_blogs = []
        skipped_count = 0
        for blog in all_blogs:
            # Check if this is a genuine blog post (has the blogpost flag set to true)
            if hasattr(blog, "blogpost") and blog.blogpost:
                filtered_blogs.append(blog)
                total_blogs_processed += 1
                
                if log_file_handle:
                    log_file_handle.write(f"Including blog: {getattr(blog, 'file_path', 'Unknown')}\n")
            else:
                skipped_count += 1
                total_blogs_skipped += 1
                sphinx_diagnostics.debug(
                    f"Skipping non-blog README file: {getattr(blog, 'file_path', 'Unknown')}"
                )
                
                if log_file_handle:
                    log_file_handle.write(f"Skipping non-blog README file: {getattr(blog, 'file_path', 'Unknown')}\n")
        
        sphinx_diagnostics.info(
            f"Filtered out {skipped_count} non-blog README files, kept {len(filtered_blogs)} genuine blog posts"
        )
        
        if log_file_handle:
            log_file_handle.write(f"Filtered out {skipped_count} non-blog README files, kept {len(filtered_blogs)} genuine blog posts\n")

        sorted_blogs = sorted(filtered_blogs, 
                             key=lambda blog: getattr(blog, 'date', datetime.now()), 
                             reverse=True)
        
        if log_file_handle:
            log_file_handle.write("Sorted blogs by date (newest first)\n")
        
        # Get all filtered blogs and calculate pagination
        all_blogs = sorted_blogs
        total_blogs = len(all_blogs)
        total_pages = max(1, (total_blogs + BLOGS_PER_PAGE - 1) // BLOGS_PER_PAGE)
        
        sphinx_diagnostics.info(
            f"Generating {total_pages} paginated posts pages with {BLOGS_PER_PAGE} blogs per page"
        )
        
        if log_file_handle:
            log_file_handle.write(f"Generating {total_pages} paginated posts pages with {BLOGS_PER_PAGE} blogs per page\n")
        
        # Generate all grid items in parallel with lazy loading
        if log_file_handle:
            log_file_handle.write("Generating lazy-loaded grid items for all blogs\n")
            
        all_grid_items = _generate_lazy_loaded_grid_items(rocm_blogs, all_blogs)
        
        # Check if any grid items were generated
        if not all_grid_items:
            warning_message = "No grid items were generated for posts pages. Skipping page generation."
            sphinx_diagnostics.warning(warning_message)
            
            if log_file_handle:
                log_file_handle.write(f"WARNING: {warning_message}\n")
                
            total_blogs_warning += 1
            return
        
        if log_file_handle:
            log_file_handle.write(f"Generated {len(all_grid_items)} grid items\n")
        
        # Current datetime for template
        current_datetime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        
        # Generate each page
        if log_file_handle:
            log_file_handle.write("Generating individual pages\n")
            
        for page_num in range(1, total_pages + 1):
            # Get grid items for this page
            start_index = (page_num - 1) * BLOGS_PER_PAGE
            end_index = min(start_index + BLOGS_PER_PAGE, len(all_grid_items))
            page_grid_items = all_grid_items[start_index:end_index]
            grid_content = "\n".join(page_grid_items)
            
            if log_file_handle:
                log_file_handle.write(f"Processing page {page_num}/{total_pages} with {len(page_grid_items)} grid items\n")
            
            # Create pagination controls
            pagination_controls = _create_pagination_controls(
                pagination_template, page_num, total_pages, "posts"
            )
            
            # Add page suffix for pages after the first
            page_title_suffix = f" - Page {page_num}" if page_num > 1 else ""
            page_description_suffix = f" (Page {page_num} of {total_pages})" if page_num > 1 else ""
            
            # Create the final page content
            page_content = POSTS_TEMPLATE.format(
                CSS=css_content,
                PAGINATION_CSS=pagination_css,
                HTML=template_html.replace("{grid_items}", grid_content).replace("{datetime}", current_datetime),
                pagination_controls=pagination_controls,
                page_title_suffix=page_title_suffix,
                page_description_suffix=page_description_suffix,
                current_page=page_num,
            )
            
            # Determine output filename and write the file
            output_filename = "posts.md" if page_num == 1 else f"posts-page{page_num}.md"
            output_path = Path(blogs_directory) / output_filename
            
            if log_file_handle:
                log_file_handle.write(f"Writing page to {output_path}\n")
            
            with output_path.open("w", encoding="utf-8") as output_file:
                output_file.write(page_content)
            
            total_pages_created += 1
            total_blogs_successful += len(page_grid_items)
            
            sphinx_diagnostics.info(
                f"Created {output_path} with {len(page_grid_items)} grid items (page {page_num}/{total_pages})"
            )
        
        # Record timing information
        phase_duration = time.time() - phase_start_time
        _BUILD_PHASES["update_posts"] = phase_duration
        sphinx_diagnostics.info(
            f"Successfully created {total_pages} paginated posts pages in \033[96m{phase_duration:.2f} seconds\033[0m"
        )
        
        if log_file_handle:
            log_file_handle.write(f"Successfully created {total_pages} paginated posts pages in {phase_duration:.2f} seconds\n")
        
    except Exception as page_error:
        error_message = f"Failed to create posts files: {page_error}"
        sphinx_diagnostics.critical(error_message)
        sphinx_diagnostics.debug(f"Traceback: {traceback.format_exc()}")
        
        if log_file_handle:
            log_file_handle.write(f"CRITICAL ERROR: {error_message}\n")
            log_file_handle.write(f"Traceback: {traceback.format_exc()}\n")
            
        _BUILD_PHASES["update_posts"] = time.time() - phase_start_time
        _CRITICAL_ERROR_OCCURRED = True
        raise ROCmBlogsError(error_message) from page_error
    finally:
        # Write summary to log file
        if log_file_handle:
            end_time = time.time()
            total_duration = end_time - phase_start_time
            
            log_file_handle.write("\n" + "=" * 80 + "\n")
            log_file_handle.write("POSTS GENERATION SUMMARY\n")
            log_file_handle.write("-" * 80 + "\n")
            log_file_handle.write(f"Total blogs processed: {total_blogs_processed}\n")
            log_file_handle.write(f"Total pages created: {total_pages_created}\n")
            log_file_handle.write(f"Blogs included in pages: {total_blogs_successful}\n")
            log_file_handle.write(f"Errors: {total_blogs_error}\n")
            log_file_handle.write(f"Warnings: {total_blogs_warning}\n")
            log_file_handle.write(f"Skipped: {total_blogs_skipped}\n")
            log_file_handle.write(f"Total time: {total_duration:.2f} seconds\n")
            
            if all_error_details:
                log_file_handle.write("\nERROR DETAILS:\n")
                log_file_handle.write("-" * 80 + "\n")
                for index, error_detail in enumerate(all_error_details):
                    log_file_handle.write(f"{index+1}. Blog: {error_detail['blog']}\n")
                    log_file_handle.write(f"   Error: {error_detail['error']}\n\n")
            
            log_file_handle.close()

def clean_html(html_content):
    """Clean HTML content by removing orphaned grid attributes and empty sections"""
    
    # Remove any standalone ":margin 2" lines that might be orphaned
    html_content = re.sub(r'\n:margin 2\n', '\n', html_content)
    
    # Remove any malformed or empty grid sections completely
    # This pattern matches grid sections with no content between the tags
    html_content = re.sub(r'::::{grid}[^\n]*\n:margin 2\n\n::::', '', html_content)
    
    # Fix stacked colons in grid tags (like ::::::::{grid})
    html_content = re.sub(r':+{grid}', '::::{grid}', html_content)
    
    return html_content

def update_vertical_pages(sphinx_app: Sphinx) -> None:
    """Generate paginated vertical pages with improved conditional string replacement"""
    phase_name = "Update Vertical Pages"
    phase_start_time = time.time()

    log_filepath, log_file_handle = create_step_log_file(phase_name)

    # Import the raw HTML template
    template_html = import_file("rocm_blogs.templates", "vertical.html")
    css_content = import_file("rocm_blogs.static.css", "index.css")
    pagination_template = import_file("rocm_blogs.templates", "pagination.html")
    pagination_css = import_file("rocm_blogs.static.css", "pagination.css")

    # Create the full template with CSS
    index_template = VERTICAL_TEMPLATE.format(
        CSS=css_content, HTML=template_html
    )

    # Fix any malformed grid tags in the template
    index_template = index_template.replace(
        "{grid} 1 2 3 4\n:margin 2\n{application_grid_items}\n::::",
        "::::{grid} 1 2 3 4\n:margin 2\n{application_grid_items}\n::::"
    )

    rocm_blogs = ROCmBlogs()
    blogs_directory = rocm_blogs.find_blogs_directory(sphinx_app.srcdir)
    rocm_blogs.blogs_directory = str(blogs_directory)
        
    if log_file_handle:
        log_file_handle.write(f"Found blogs directory: {blogs_directory}\n")
        
    readme_count = rocm_blogs.find_readme_files()
    
    if log_file_handle:
        log_file_handle.write(f"Found {readme_count} README files\n")
        
    rocm_blogs.create_blog_objects()
    
    if log_file_handle:
        log_file_handle.write("Created blog objects\n")
        
    rocm_blogs.blogs.sort_blogs_by_date()
    
    if log_file_handle:
        log_file_handle.write("Sorted blogs by date\n")
        
    rocm_blogs.blogs.sort_blogs_by_vertical()
    
    if log_file_handle:
        log_file_handle.write("Sorted blogs by market vertical\n")

    if log_file_handle:
        log_file_handle.write(f"Vertical Blogs: {rocm_blogs.blogs.blogs_verticals}\n")
        log_file_handle.write("Generating vertical pages\n")

    try:
        posts_template_html = import_file("rocm_blogs.templates", "posts.html")
        
        # Get all blogs and filter to only include real blog posts
        all_blogs = rocm_blogs.blogs.get_blogs()
        filtered_blogs = [blog for blog in all_blogs if hasattr(blog, "blogpost") and blog.blogpost]
        
        # Sort blogs by date (newest first)
        sorted_blogs = sorted(filtered_blogs, 
                             key=lambda blog: getattr(blog, 'date', datetime.now()), 
                             reverse=True)

        verticals = rocm_blogs.blogs.blogs_verticals
        for vertical in verticals:
            vertical_blogs = []
            for blog in sorted_blogs:
                if hasattr(blog, "vertical") and blog.vertical:
                    if isinstance(blog.vertical, str):
                        blog_verticals = [v.strip() for v in blog.vertical.split(",") if v.strip()]
                    else:
                        blog_verticals = blog.vertical

                    if vertical in blog_verticals:
                        vertical_blogs.append(blog)
                elif hasattr(blog, "metadata") and blog.metadata:
                    try:
                        myst_data = blog.metadata.get("myst", {})
                        html_meta = myst_data.get("html_meta", {})
                        vertical_str = html_meta.get("vertical", "")
                        
                        blog_verticals = [v.strip() for v in vertical_str.split(",") if v.strip()]
                        if blog_verticals and vertical in blog_verticals:
                            vertical_blogs.append(blog)
                    except (AttributeError, KeyError) as e:
                        pass

            if not vertical_blogs:
                if log_file_handle:
                    log_file_handle.write(f"No blogs found for vertical: {vertical}\n")
                continue

            BLOGS_PER_PAGE = POST_BLOGS_PER_PAGE
            total_blogs = len(vertical_blogs)
            total_pages = max(1, (total_blogs + BLOGS_PER_PAGE - 1) // BLOGS_PER_PAGE)

            all_grid_items = _generate_lazy_loaded_grid_items(rocm_blogs, vertical_blogs)

            current_datetime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            
            # Format vertical name for filename
            formatted_vertical = vertical.replace(" ", "-").replace("&", "and").lower()
            formatted_vertical = re.sub(r'[^a-z0-9-]', '', formatted_vertical)
            formatted_vertical = re.sub(r'-+', '-', formatted_vertical)

            for page_num in range(1, total_pages + 1):
                start_index = (page_num - 1) * BLOGS_PER_PAGE
                end_index = min(start_index + BLOGS_PER_PAGE, len(all_grid_items))
                page_grid_items = all_grid_items[start_index:end_index]
                grid_content = "\n".join(page_grid_items)
                
                # Create pagination controls
                pagination_controls = _create_pagination_controls(
                    pagination_template, page_num, total_pages, f"verticals-{formatted_vertical}"
                )
                
                # Add page suffix for pages after the first
                page_title_suffix = f" - Page {page_num}" if page_num > 1 else ""
                page_description_suffix = f" (Page {page_num} of {total_pages})" if page_num > 1 else ""
                
                # Create the final page content
                page_content = POSTS_TEMPLATE.format(
                    CSS=css_content,
                    PAGINATION_CSS=pagination_css,
                    HTML=posts_template_html.replace("{grid_items}", grid_content).replace("{datetime}", current_datetime),
                    pagination_controls=pagination_controls,
                    page_title_suffix=page_title_suffix,
                    page_description_suffix=page_description_suffix,
                    current_page=page_num,
                )
                
                # Replace the title to include the vertical name
                page_content = page_content.replace("# Recent Posts", f"# {vertical} Blogs")
                
                # Determine output filename and write the file
                output_filename = f"verticals-{formatted_vertical}.md" if page_num == 1 else f"verticals-{formatted_vertical}-page{page_num}.md"
                output_path = Path(blogs_directory) / output_filename
                
                with output_path.open("w", encoding="utf-8") as output_file:
                    output_file.write(page_content)
                
                if log_file_handle:
                    log_file_handle.write(f"Created {output_path} with {len(page_grid_items)} grid items (page {page_num}/{total_pages})\n")
    except Exception as verticals_page_error:
        error_message = f"Failed to create verticals pages: {verticals_page_error}"
        sphinx_diagnostics.error(error_message)
        sphinx_diagnostics.debug(f"Traceback: {traceback.format_exc()}")
        
        if log_file_handle:
            log_file_handle.write(f"ERROR: {error_message}\n")
            log_file_handle.write(f"Traceback: {traceback.format_exc()}\n")

    # Generate individual vertical pages
    verticals = rocm_blogs.blogs.blogs_verticals
    for vertical in verticals:
        used_blogs = []

        vertical_blogs = rocm_blogs.blogs.get_blogs_by_vertical(vertical)
        vertical_blogs.sort(key=lambda blog: getattr(blog, 'date', datetime.now()), reverse=True)

        ecosystem_blogs = [blog for blog in vertical_blogs if hasattr(blog, "category") and blog.category == "Ecosystems and Partners"]
        application_blogs = [blog for blog in vertical_blogs if hasattr(blog, "category") and blog.category == "Applications & models"]
        software_blogs = [blog for blog in vertical_blogs if hasattr(blog, "category") and blog.category == "Software tools & optimizations"]

        main_grid_items = _generate_grid_items(rocm_blogs, vertical_blogs, MAIN_GRID_BLOGS_COUNT, used_blogs, True, False)
        ecosystem_grid_items = _generate_grid_items(rocm_blogs, ecosystem_blogs, CATEGORY_GRID_BLOGS_COUNT, used_blogs, True, False)
        application_grid_items = _generate_grid_items(rocm_blogs, application_blogs, CATEGORY_GRID_BLOGS_COUNT, used_blogs, True, False)
        software_grid_items = _generate_grid_items(rocm_blogs, software_blogs, CATEGORY_GRID_BLOGS_COUNT, used_blogs, True, False)

        if not main_grid_items and not ecosystem_grid_items and not application_grid_items and not software_grid_items:
            if log_file_handle:
                log_file_handle.write(f"No grid items found for vertical: {vertical}\n")
            continue

        # Format the vertical name for links
        formatted_vertical = vertical.replace(" ", "-").replace("&", "and").lower()
        formatted_vertical = re.sub(r'[^a-z0-9-]', '', formatted_vertical)
        formatted_vertical = re.sub(r'-+', '-', formatted_vertical)
        
        # Start with the basic template
        updated_html = index_template
        
        # Replace the basic placeholders
        updated_html = updated_html.replace("{page_title}", f"{vertical} Blogs")
        updated_html = updated_html.replace("{page_description}", f"Blogs related to {vertical} market vertical")
        updated_html = updated_html.replace("{grid_items}", "\n".join(main_grid_items) if main_grid_items else "")
        updated_html = updated_html.replace("{vertical}", formatted_vertical)
        
        if ecosystem_grid_items:
            updated_html = updated_html.replace("{eco_grid_items}", "\n".join(ecosystem_grid_items))
        else:
            eco_section_start = updated_html.find('<div class="container">\n    <h2>Ecosystems and partners</h2>')
            if eco_section_start != -1:
                grid_start = updated_html.find('::::{grid}', eco_section_start)
                if grid_start != -1:
                    grid_end = updated_html.find('::::', grid_start + 10)
                    if grid_end != -1:
                        next_line_end = updated_html.find('\n', grid_end) + 1
                        updated_html = updated_html[:eco_section_start] + updated_html[next_line_end:]
                    else:
                        updated_html = updated_html.replace("{eco_grid_items}", "")
                else:
                    updated_html = updated_html.replace("{eco_grid_items}", "")
            else:
                updated_html = updated_html.replace("{eco_grid_items}", "")

        if application_grid_items:
            updated_html = updated_html.replace("{application_grid_items}", "\n".join(application_grid_items))
        else:
            app_section_start = updated_html.find('<div class="container">\n    <h2>Applications & models</h2>')
            
            if app_section_start != -1:
                grid_start1 = updated_html.find('::::{grid}', app_section_start)
                grid_start2 = updated_html.find('{grid}', app_section_start)

                grid_start = grid_start1 if grid_start1 != -1 else grid_start2
                
                if grid_start != -1:
                    grid_end = updated_html.find('::::', grid_start + 5)
                    if grid_end != -1:
                        next_line_end = updated_html.find('\n', grid_end) + 1
                        updated_html = updated_html[:app_section_start] + updated_html[next_line_end:]
                    else:
                        updated_html = updated_html.replace("{application_grid_items}", "")
                else:
                    updated_html = updated_html.replace("{application_grid_items}", "")
            else:
                malformed_start = updated_html.find('{grid} 1 2 3 4\n:margin 2\n{application_grid_items}\n')
                if malformed_start != -1:
                    container_start = updated_html.rfind('<div class="container">', 0, malformed_start)
                    if container_start != -1 and (malformed_start - container_start) < 300:
                        grid_end = updated_html.find('::::', malformed_start)
                        if grid_end != -1:
                            next_line_end = updated_html.find('\n', grid_end) + 1
                            updated_html = updated_html[:container_start] + updated_html[next_line_end:]
                        else:
                            updated_html = updated_html.replace("{application_grid_items}", "")
                    else:
                        grid_end = updated_html.find('::::', malformed_start)
                        if grid_end != -1:
                            next_line_end = updated_html.find('\n', grid_end) + 1
                            updated_html = updated_html[:malformed_start] + updated_html[next_line_end:]
                        else:
                            updated_html = updated_html.replace("{application_grid_items}", "")
                else:
                    updated_html = updated_html.replace("{application_grid_items}", "")

        if software_grid_items:
            updated_html = updated_html.replace("{software_grid_items}", "\n".join(software_grid_items))
        else:
            software_section_start = updated_html.find('<div class="container">\n    <h2>Software tools & optimizations</h2>')
            if software_section_start != -1:
                grid_start = updated_html.find('::::{grid}', software_section_start)
                if grid_start != -1:
                    grid_end = updated_html.find('::::', grid_start + 10)
                    if grid_end != -1:
                        next_line_end = updated_html.find('\n', grid_end) + 1
                        updated_html = updated_html[:software_section_start] + updated_html[next_line_end:]
                    else:
                        updated_html = updated_html.replace("{software_grid_items}", "")
                else:
                    updated_html = updated_html.replace("{software_grid_items}", "")
            else:
                updated_html = updated_html.replace("{software_grid_items}", "")

        updated_html = clean_html(updated_html)

        output_filename = vertical.replace(" ", "-").lower()
        output_filename = re.sub(r'[^a-z0-9-]', '', output_filename)
        output_filename = f"{output_filename}.md"
        output_path = Path(blogs_directory) / output_filename

        with output_path.open("w", encoding="utf-8") as output_file:
            output_file.write(updated_html)
        
        if log_file_handle:
            log_file_handle.write(f"Generated vertical page for {vertical}\n")

    # Record timing information
    phase_duration = time.time() - phase_start_time
    _BUILD_PHASES["update_vertical_pages"] = phase_duration
    sphinx_diagnostics.info(
        f"Vertical pages generation completed in \033[96m{phase_duration:.2f} seconds\033[0m"
    )

    if log_file_handle:
        log_file_handle.write(f"Vertical pages generation completed in {phase_duration:.2f} seconds\n")
        log_file_handle.close()

def update_category_verticals(sphinx_app: Sphinx) -> None:
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
            log_file_handle.write("Starting multi-filter pages generation process\n")
            log_file_handle.write("-" * 80 + "\n\n")
            
        # Load templates and styles
        pagination_template = import_file("rocm_blogs.templates", "pagination.html")
        css_content = import_file("rocm_blogs.static.css", "index.css")
        pagination_css = import_file("rocm_blogs.static.css", "pagination.css")
        
        if log_file_handle:
            log_file_handle.write("Successfully loaded templates and styles\n")
        
        # Initialize ROCmBlogs and load blog data
        rocm_blogs = ROCmBlogs()
        blogs_directory = rocm_blogs.find_blogs_directory(sphinx_app.srcdir)
        
        if not blogs_directory:
            error_message = "Could not find blogs directory"
            sphinx_diagnostics.error(error_message)
            
            if log_file_handle:
                log_file_handle.write(f"ERROR: {error_message}\n")
                
            _CRITICAL_ERROR_OCCURRED = True
            raise ROCmBlogsError(error_message)
            
        rocm_blogs.blogs_directory = str(blogs_directory)
        
        if log_file_handle:
            log_file_handle.write(f"Found blogs directory: {blogs_directory}\n")
            
        readme_count = rocm_blogs.find_readme_files()
        
        if log_file_handle:
            log_file_handle.write(f"Found {readme_count} README files\n")
            
        rocm_blogs.create_blog_objects()
        
        if log_file_handle:
            log_file_handle.write("Created blog objects\n")
            
        rocm_blogs.blogs.sort_blogs_by_date()
        
        if log_file_handle:
            log_file_handle.write("Sorted blogs by date\n")

        # Get category keys from BLOG_CATEGORIES
        category_keys = [category_info.get("category_key", category_info["name"]) for category_info in BLOG_CATEGORIES]
            
        rocm_blogs.blogs.sort_blogs_by_category(category_keys)
        rocm_blogs.blogs.sort_categories_by_vertical(log_file_handle)
        rocm_blogs.blogs.sort_blogs_by_vertical()

        log_file_handle.write("Sorted blogs by category and vertical\n")

        # Get all vertical-category combinations
        keys = rocm_blogs.blogs.get_vertical_category_blog_keys()

        log_file_handle.write(f"Found {len(keys)} vertical-category combinations\n")
        
        # Process each vertical-category combination
        for key in keys:
            total_pages_processed += 1
            category, vertical = key
            
            log_file_handle.write(f"\nProcessing vertical-category: {vertical} - {category}\n")
            
            # Get blogs for this vertical-category combination
            category_vertical_blogs = rocm_blogs.blogs.get_vertical_category_blogs(category, vertical)
            
            if not category_vertical_blogs:
                log_file_handle.write(f"No blogs found for category {category} and vertical {vertical}\n")
                continue
                
            log_file_handle.write(f"Found {len(category_vertical_blogs)} blogs for category {category} and vertical {vertical}\n")
            
            page_name = f"{vertical}-{category}".lower()
            page_name = page_name.replace("&", "and")
            page_name = page_name.replace(" ", "-")
            page_name = re.sub(r'[^a-z0-9-]', '', page_name)
            page_name = re.sub(r'-+', '-', page_name)

            log_file_handle.write(f"Creating title from vertical and category: {vertical} - {category}\n")

            if vertical.lower() == "ai":
                vertical = "AI"
                title_vertical = vertical
            elif vertical.lower() == "hpc":
                vertical = "HPC"
                title_vertical = vertical
            else:
                title_vertical = vertical.capitalize()
            title_vertical = title_vertical.replace("and", "&").replace('And', '&')

            log_file_handle.write(f"Formatted vertical name: {title_vertical}\n")

            words_category = category.split(' ')
            title_category = " ".join(word.upper() if word.lower() == "ai" else word.capitalize() for word in words_category).replace('and', '&').replace('And', '&')

            if category.lower() == "ai" or category.lower() == "hpc":
                title_category = title_category.upper()
            title_category = category.replace('and', '&')

            filter_info = {
                "name": f"{vertical} - {category}",
                "template": "applications-models.html",
                "output_base": page_name,
                "category_key": category,
                "title": f"{title_vertical} - {title_category}",
                "description": f"AMD ROCm™ blogs related to {category} in the {vertical} market vertical",
                "keywords": f"{vertical}, {category}, AMD, ROCm".replace('and', '&'),
                "filter_criteria": {
                    "category": [category],
                    "vertical": [vertical]
                }
            }
            
            log_file_handle.write(f"Created filter info: {filter_info}\n")
            
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
                log_file_handle.write(f"Successfully processed vertical-category: {vertical} - {category}\n")
                
            except Exception as processing_error:
                error_message = f"Error processing vertical-category {vertical} - {category}: {processing_error}"
                sphinx_diagnostics.error(error_message)
                
                if log_file_handle:
                    log_file_handle.write(f"ERROR: {error_message}\n")
                    log_file_handle.write(f"Traceback: {traceback.format_exc()}\n")
                    
                total_pages_error += 1
                all_error_details.append({"page": f"{vertical} - {category}", "error": str(processing_error)})

        log_file_handle.write("\nNo additional custom filter pages will be generated\n")

        phase_duration = time.time() - phase_start_time
        _BUILD_PHASES[phase_name] = phase_duration
        sphinx_diagnostics.info(
            f"Multi-filter pages generation completed in \033[96m{phase_duration:.2f} seconds\033[0m"
        )
        
        if log_file_handle:
            log_file_handle.write(f"Multi-filter pages generation completed in {phase_duration:.2f} seconds\n")
        
    except Exception as generation_error:
        error_message = f"Failed to generate multi-filter pages: {generation_error}"
        sphinx_diagnostics.critical(error_message)
        sphinx_diagnostics.debug(f"Traceback: {traceback.format_exc()}")
        
        if log_file_handle:
            log_file_handle.write(f"CRITICAL ERROR: {error_message}\n")
            log_file_handle.write(f"Traceback: {traceback.format_exc()}\n")
            
        _BUILD_PHASES[phase_name] = time.time() - phase_start_time
        _CRITICAL_ERROR_OCCURRED = True
        raise ROCmBlogsError(error_message) from generation_error
    finally:
        # Write summary to log file
        if log_file_handle:
            end_time = time.time()
            total_duration = end_time - phase_start_time
            
            log_file_handle.write("\n" + "=" * 80 + "\n")
            log_file_handle.write("MULTI-FILTER PAGES GENERATION SUMMARY\n")
            log_file_handle.write("-" * 80 + "\n")
            log_file_handle.write(f"Total pages processed: {total_pages_processed}\n")
            log_file_handle.write(f"Total pages successful: {total_pages_successful}\n")
            log_file_handle.write(f"Total pages with errors: {total_pages_error}\n")
            log_file_handle.write(f"Total time: {total_duration:.2f} seconds\n")
            
            if all_error_details:
                log_file_handle.write("\nERROR DETAILS:\n")
                log_file_handle.write("-" * 80 + "\n")
                for index, error_detail in enumerate(all_error_details):
                    log_file_handle.write(f"{index+1}. Page: {error_detail['page']}\n")
                    log_file_handle.write(f"   Error: {error_detail['error']}\n\n")
            
            log_file_handle.close()

def update_category_pages(sphinx_app: Sphinx) -> None:
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
            log_file_handle.write("Starting category pages generation process\n")
            log_file_handle.write("-" * 80 + "\n\n")
            
        # Load templates and styles
        pagination_template = import_file("rocm_blogs.templates", "pagination.html")
        css_content = import_file("rocm_blogs.static.css", "index.css")
        pagination_css = import_file("rocm_blogs.static.css", "pagination.css")
        
        if log_file_handle:
            log_file_handle.write("Successfully loaded templates and styles\n")
        
        # Initialize ROCmBlogs and load blog data
        rocm_blogs = ROCmBlogs()
        blogs_directory = rocm_blogs.find_blogs_directory(sphinx_app.srcdir)
        
        if not blogs_directory:
            error_message = "Could not find blogs directory"
            sphinx_diagnostics.error(error_message)
            
            if log_file_handle:
                log_file_handle.write(f"ERROR: {error_message}\n")
                
            _CRITICAL_ERROR_OCCURRED = True
            raise ROCmBlogsError(error_message)
            
        rocm_blogs.blogs_directory = str(blogs_directory)
        
        if log_file_handle:
            log_file_handle.write(f"Found blogs directory: {blogs_directory}\n")
            
        readme_count = rocm_blogs.find_readme_files()
        
        if log_file_handle:
            log_file_handle.write(f"Found {readme_count} README files\n")
            
        rocm_blogs.create_blog_objects()
        
        if log_file_handle:
            log_file_handle.write("Created blog objects\n")
            
        rocm_blogs.blogs.sort_blogs_by_date()
        
        if log_file_handle:
            log_file_handle.write("Sorted blogs by date\n")
            
        rocm_blogs.blogs.sort_blogs_by_category(rocm_blogs.categories)
        
        if log_file_handle:
            log_file_handle.write("Sorted blogs by category\n")
        
        # Current datetime for template
        current_datetime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        
        # Process each category
        if log_file_handle:
            log_file_handle.write(f"Processing {len(BLOG_CATEGORIES)} categories\n")
            
        for category_info in BLOG_CATEGORIES:
            total_categories_processed += 1
            category_name = category_info["name"]
            
            if log_file_handle:
                log_file_handle.write(f"\nProcessing category: {category_name}\n")
                log_file_handle.write(f"  Output base: {category_info['output_base']}\n")
                log_file_handle.write(f"  Category key: {category_info['category_key']}\n")

            category_key = category_info["category_key"]
            category_blogs = rocm_blogs.blogs.blogs_categories.get(category_key, [])

            category_info["title"] = category_info.get("title", category_name).capitalize().replace('and', '&').replace('And', '&')
            
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
                    category_blogs
                )
                
                total_categories_successful += 1
                total_pages_created += 1  # This is a simplification, each category might have multiple pages
                
                if log_file_handle:
                    log_file_handle.write(f"Successfully processed category: {category_name}\n")
                    
            except Exception as category_processing_error:
                error_message = f"Error processing category {category_name}: {category_processing_error}"
                sphinx_diagnostics.error(error_message)
                
                if log_file_handle:
                    log_file_handle.write(f"ERROR: {error_message}\n")
                    log_file_handle.write(f"Traceback: {traceback.format_exc()}\n")
                    
                total_categories_error += 1
                all_error_details.append({"category": category_name, "error": str(category_processing_error)})
        
        # Record timing information
        phase_duration = time.time() - phase_start_time
        _BUILD_PHASES["update_category_pages"] = phase_duration
        sphinx_diagnostics.info(
            f"Category pages generation completed in \033[96m{phase_duration:.2f} seconds\033[0m"
        )
        
        if log_file_handle:
            log_file_handle.write(f"Category pages generation completed in {phase_duration:.2f} seconds\n")
        
    except Exception as category_error:
        error_message = f"Failed to generate category pages: {category_error}"
        sphinx_diagnostics.critical(error_message)
        sphinx_diagnostics.debug(f"Traceback: {traceback.format_exc()}")
        
        if log_file_handle:
            log_file_handle.write(f"CRITICAL ERROR: {error_message}\n")
            log_file_handle.write(f"Traceback: {traceback.format_exc()}\n")
            
        _BUILD_PHASES["update_category_pages"] = time.time() - phase_start_time
        _CRITICAL_ERROR_OCCURRED = True
        raise ROCmBlogsError(error_message) from category_error
    finally:
        # Write summary to log file
        if log_file_handle:
            end_time = time.time()
            total_duration = end_time - phase_start_time
            
            log_file_handle.write("\n" + "=" * 80 + "\n")
            log_file_handle.write("CATEGORY PAGES GENERATION SUMMARY\n")
            log_file_handle.write("-" * 80 + "\n")
            log_file_handle.write(f"Total categories processed: {total_categories_processed}\n")
            log_file_handle.write(f"Total categories successful: {total_categories_successful}\n")
            log_file_handle.write(f"Total categories with errors: {total_categories_error}\n")
            log_file_handle.write(f"Total pages created: {total_pages_created}\n")
            log_file_handle.write(f"Total time: {total_duration:.2f} seconds\n")
            
            if all_error_details:
                log_file_handle.write("\nERROR DETAILS:\n")
                log_file_handle.write("-" * 80 + "\n")
                for index, error_detail in enumerate(all_error_details):
                    log_file_handle.write(f"{index+1}. Category: {error_detail['category']}\n")
                    log_file_handle.write(f"   Error: {error_detail['error']}\n\n")
            
            log_file_handle.close()

def setup(sphinx_app: Sphinx) -> dict:
    """Set up the ROCm Blogs extension."""
    global _CRITICAL_ERROR_OCCURRED
    phase_start_time = time.time()
    phase_name = "setup"

    sphinx_diagnostics.info(
        f"Setting up ROCm Blogs extension, version: {__version__}"
    )
    sphinx_diagnostics.info(
        f"Build process started at: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(_BUILD_START_TIME))}"
    )

    try:
        sphinx_diagnostics.info(
            "Setting up ROCm Blogs extension..."
        )
        
        # Set up static files
        _setup_static_files(sphinx_app)
        
        # Register event handlers
        _register_event_handlers(sphinx_app)
        
        # Record timing information
        phase_duration = time.time() - phase_start_time
        _BUILD_PHASES[phase_name] = phase_duration
        sphinx_diagnostics.info(
            f"ROCm Blogs extension setup completed in \033[96m{phase_duration:.2f} seconds\033[0m"
        )
        
        # Return extension metadata
        return {
            "version": __version__,
            "parallel_read_safe": True,
            "parallel_write_safe": False,
        }
        
    except Exception as setup_error:
        sphinx_diagnostics.critical(
            f"Failed to set up ROCm Blogs extension: {setup_error}"
        )
        sphinx_diagnostics.debug(
            f"Traceback: {traceback.format_exc()}"
        )
        _BUILD_PHASES[phase_name] = time.time() - phase_start_time
        _CRITICAL_ERROR_OCCURRED = True
        raise ROCmBlogsError(f"Failed to set up ROCm Blogs extension: {setup_error}") from setup_error

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
                sphinx_diagnostics.warning(
                    f"Generic image not found at {generic_img_path}"
                )
        except Exception as image_error:
            sphinx_diagnostics.warning(
                f"Error optimizing generic image: {image_error}"
            )
            sphinx_diagnostics.debug(
                f"Traceback: {traceback.format_exc()}"
            )
            
        sphinx_diagnostics.info(
            "Static files setup completed"
        )
        
    except Exception as static_files_error:
        sphinx_diagnostics.error(
            f"Error setting up static files: {static_files_error}"
        )
        sphinx_diagnostics.debug(
            f"Traceback: {traceback.format_exc()}"
        )
        raise

def _register_event_handlers(sphinx_app: Sphinx) -> None:
    """Register event handlers for the ROCm Blogs extension."""
    try:
        # Register event handlers
        sphinx_app.connect("builder-inited", run_metadata_generator)
        sphinx_app.connect("builder-inited", update_index_file)
        sphinx_app.connect("builder-inited", blog_generation)
        sphinx_app.connect("builder-inited", update_posts_file)
        sphinx_app.connect("builder-inited", update_vertical_pages)
        sphinx_app.connect("builder-inited", update_category_pages)
        sphinx_app.connect("builder-inited", update_category_verticals)
        sphinx_app.connect("build-finished", log_total_build_time)
        
        sphinx_diagnostics.info(
            "Event handlers registered"
        )
        
    except Exception as handler_error:
        sphinx_diagnostics.error(
            f"Error registering event handlers: {handler_error}"
        )
        sphinx_diagnostics.debug(
            f"Traceback: {traceback.format_exc()}"
        )
