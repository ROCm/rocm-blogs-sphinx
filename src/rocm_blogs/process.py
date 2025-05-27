from datetime import datetime
import importlib.resources as pkg_resources
import os
import time
import traceback
import inspect
import re
import json
import shutil
from concurrent.futures import ThreadPoolExecutor

from pathlib import Path

from sphinx.util import logging as sphinx_logging
from sphinx.errors import SphinxError

from ._rocmblogs import *
from .constants import *
from .images import *
from .utils import *
from .grid import *

sphinx_diagnostics = sphinx_logging.getLogger(__name__)

def quickshare(blog_entry) -> str:
    """Generate social media sharing buttons for a blog post."""
    try:
        # Load template files
        social_css = import_file("rocm_blogs.static.css", "social-bar.css")
        social_html = import_file("rocm_blogs.templates", "social-bar.html")
        
        # Create base template with CSS
        social_bar_template = """
<style>
{CSS}
</style>
{HTML}
"""
        social_bar = social_bar_template.format(CSS=social_css, HTML=social_html)
        
        # Determine the blog URL
        if hasattr(blog_entry, "file_path"):
            blog_directory = os.path.basename(os.path.dirname(blog_entry.file_path))
            share_url = f"http://rocm.blogs.amd.com/artificial-intelligence/{blog_directory}/README.html"
        else:
            share_url = f"http://rocm.blogs.amd.com{blog_entry.grab_href()[1:]}"
        
        # Get blog title and description
        blog_title = getattr(blog_entry, "blog_title", "No Title")
        title_with_suffix = f"{blog_title} | ROCm Blogs"
        
        blog_description = "No Description"
        if hasattr(blog_entry, "myst"):
            blog_description = blog_entry.myst.get("html_meta", {}).get("description lang=en", blog_description)
        
        # Add debug info for test blogs
        if hasattr(blog_entry, "file_path") and "test" in str(blog_entry.file_path).lower():
            social_bar += f"\n<!-- {title_with_suffix} -->\n<!-- {blog_description} -->\n"
        
        # Replace placeholders with actual content
        social_bar = (
            social_bar.replace("{URL}", share_url)
            .replace("{TITLE}", title_with_suffix)
            .replace("{TEXT}", blog_description)
        )
        
        sphinx_diagnostics.debug(
            f"Generated quickshare buttons for blog: {getattr(blog_entry, 'blog_title', 'Unknown')}"
        )
        
        return social_bar
    except Exception as quickshare_error:
        sphinx_diagnostics.error(
            f"Error generating quickshare buttons for blog {getattr(blog_entry, 'blog_title', 'Unknown')}: {quickshare_error}"
        )
        sphinx_diagnostics.debug(
            f"Traceback: {traceback.format_exc()}"
        )
        return ""
    
def _create_pagination_controls(pagination_template, current_page, total_pages, base_name):
    """Create pagination controls for navigation between pages."""
    # Create previous button
    if current_page > 1:
        previous_page = current_page - 1
        previous_file = f"{base_name}-page{previous_page}.html" if previous_page > 1 else f"{base_name}.html"
        previous_button = f'<a href="{previous_file}" class="pagination-button previous"> Prev</a>'
    else:
        previous_button = '<span class="pagination-button disabled"> Prev</span>'
    
    # Create next button
    if current_page < total_pages:
        next_page = current_page + 1
        next_file = f"{base_name}-page{next_page}.html"
        next_button = f'<a href="{next_file}" class="pagination-button next">Next </a>'
    else:
        next_button = '<span class="pagination-button disabled">Next </span>'
    
    # Fill in pagination template
    return (
        pagination_template
        .replace("{prev_button}", previous_button)
        .replace("{current_page}", str(current_page))
        .replace("{total_pages}", str(total_pages))
        .replace("{next_button}", next_button)
    )

def _process_category(category_info, rocm_blogs, blogs_directory, pagination_template, css_content, pagination_css, current_datetime, category_template, category_blogs=None, log_file_handle=None):
    """Process a page with a specific filter criteria."""
    category_name = category_info["name"]
    template_name = category_info["template"]
    output_base = category_info["output_base"]
    category_key = category_info["category_key"]
    page_title = category_info["title"]
    page_description = category_info["description"]
    page_keywords = category_info["keywords"]

    filter_criteria = category_info.get("filter_criteria", {})
    
    sphinx_diagnostics.info(
        f"Generating paginated pages for category: {category_name}"
    )
    
    if log_file_handle:
        log_file_handle.write(f"Generating paginated pages for category: {category_name}\n")

    template_html = import_file("rocm_blogs.templates", template_name)
    
    # If category_blogs is not provided, filter blogs based on filter_criteria
    if category_blogs is None:
        category_blogs = []
        all_blogs = rocm_blogs.blogs.get_blogs()
        
        # If no filter criteria, use category_key to filter blogs
        if not filter_criteria:
            category_blogs = rocm_blogs.blogs.get_blogs_by_category(category_key)
            sphinx_diagnostics.info(
                f"Using category_key '{category_key}' to filter blogs. Found {len(category_blogs)} blogs."
            )
            if log_file_handle:
                log_file_handle.write(
                    f"Using category_key '{category_key}' to filter blogs. Found {len(category_blogs)} blogs.\n"
                )
        else:
            sphinx_diagnostics.info(
                f"Using filter_criteria to filter blogs: {filter_criteria}"
            )
            if log_file_handle:
                log_file_handle.write(
                    f"Using filter_criteria to filter blogs: {filter_criteria}\n"
                )
            for blog in all_blogs:
                matches_all_criteria = True
                
                for field, values in filter_criteria.items():
                    # Convert single value to list for consistent handling
                    if not isinstance(values, list):
                        values = [values]
                    
                    # Get blog field value
                    if field == "category":
                        blog_value = getattr(blog, "category", "")
                        if blog_value not in values:
                            matches_all_criteria = False
                            sphinx_diagnostics.debug(
                                f"Blog '{getattr(blog, 'blog_title', 'Unknown')}' category '{blog_value}' does not match any of {values}"
                            )
                            if log_file_handle:
                                log_file_handle.write(
                                    f"Blog '{getattr(blog, 'blog_title', 'Unknown')}' category '{blog_value}' does not match any of {values}\n"
                                )
                            break
                        else:
                            sphinx_diagnostics.debug(
                                f"Blog '{getattr(blog, 'blog_title', 'Unknown')}' category '{blog_value}' matches one of {values}"
                            )
                            if log_file_handle:
                                log_file_handle.write(
                                    f"Blog '{getattr(blog, 'blog_title', 'Unknown')}' category '{blog_value}' matches one of {values}\n"
                                )
                    elif field == "vertical":
                        if not hasattr(blog, "metadata") or not blog.metadata:
                            matches_all_criteria = False
                            sphinx_diagnostics.debug(
                                f"Blog '{getattr(blog, 'blog_title', 'Unknown')}' has no metadata"
                            )
                            if log_file_handle:
                                log_file_handle.write(
                                    f"Blog '{getattr(blog, 'blog_title', 'Unknown')}' has no metadata\n"
                                )
                            break

                        try:
                            myst_data = blog.metadata.get("myst", {})
                            html_meta = myst_data.get("html_meta", {})
                            vertical_str = html_meta.get("vertical", "")

                            if not vertical_str and hasattr(blog, "vertical"):
                                vertical_str = getattr(blog, "vertical", "")
                            
                            # Split vertical string into list and strip whitespace
                            blog_verticals = [v.strip() for v in vertical_str.split(",") if v.strip()]
                            
                            # Debug log
                            sphinx_diagnostics.debug(
                                f"Blog '{getattr(blog, 'blog_title', 'Unknown')}' verticals: {blog_verticals}"
                            )
                            if log_file_handle:
                                log_file_handle.write(
                                    f"Blog '{getattr(blog, 'blog_title', 'Unknown')}' verticals: {blog_verticals}\n"
                                )
                            
                            # Check if any of the blog's verticals match any of the specified verticals
                            if not blog_verticals or not any(bv in values for bv in blog_verticals):
                                matches_all_criteria = False
                                sphinx_diagnostics.debug(
                                    f"Blog '{getattr(blog, 'blog_title', 'Unknown')}' verticals {blog_verticals} do not match any of {values}"
                                )
                                if log_file_handle:
                                    log_file_handle.write(
                                        f"Blog '{getattr(blog, 'blog_title', 'Unknown')}' verticals {blog_verticals} do not match any of {values}\n"
                                    )
                                break
                            else:
                                sphinx_diagnostics.debug(
                                    f"Blog '{getattr(blog, 'blog_title', 'Unknown')}' verticals {blog_verticals} match one of {values}"
                                )
                                if log_file_handle:
                                    log_file_handle.write(
                                        f"Blog '{getattr(blog, 'blog_title', 'Unknown')}' verticals {blog_verticals} match one of {values}\n"
                                    )
                        except (AttributeError, KeyError) as e:
                            matches_all_criteria = False
                            sphinx_diagnostics.debug(
                                f"Error getting vertical for blog '{getattr(blog, 'blog_title', 'Unknown')}': {e}"
                            )
                            if log_file_handle:
                                log_file_handle.write(
                                    f"Error getting vertical for blog '{getattr(blog, 'blog_title', 'Unknown')}': {e}\n"
                                )
                            break
                    elif field == "tags":
                        if not hasattr(blog, "tags") or not blog.tags:
                            matches_all_criteria = False
                            sphinx_diagnostics.debug(
                                f"Blog '{getattr(blog, 'blog_title', 'Unknown')}' has no tags"
                            )
                            if log_file_handle:
                                log_file_handle.write(
                                    f"Blog '{getattr(blog, 'blog_title', 'Unknown')}' has no tags\n"
                                )
                            break

                        blog_tags = blog.tags
                        if isinstance(blog_tags, str):
                            blog_tags = [tag.strip() for tag in blog_tags.split(",") if tag.strip()]

                        if not blog_tags or not any(tag in blog_tags for tag in values):
                            matches_all_criteria = False
                            sphinx_diagnostics.debug(
                                f"Blog '{getattr(blog, 'blog_title', 'Unknown')}' tags {blog_tags} do not match any of {values}"
                            )
                            if log_file_handle:
                                log_file_handle.write(
                                    f"Blog '{getattr(blog, 'blog_title', 'Unknown')}' tags {blog_tags} do not match any of {values}\n"
                                )
                            break
                        else:
                            sphinx_diagnostics.debug(
                                f"Blog '{getattr(blog, 'blog_title', 'Unknown')}' tags {blog_tags} match one of {values}"
                            )
                            if log_file_handle:
                                log_file_handle.write(
                                    f"Blog '{getattr(blog, 'blog_title', 'Unknown')}' tags {blog_tags} match one of {values}\n"
                                )
                    else:
                        blog_value = getattr(blog, field, None)
                        if blog_value is None or blog_value not in values:
                            matches_all_criteria = False
                            sphinx_diagnostics.debug(
                                f"Blog '{getattr(blog, 'blog_title', 'Unknown')}' field '{field}' value '{blog_value}' does not match any of {values}"
                            )
                            if log_file_handle:
                                log_file_handle.write(
                                    f"Blog '{getattr(blog, 'blog_title', 'Unknown')}' field '{field}' value '{blog_value}' does not match any of {values}\n"
                                )
                            break
                        else:
                            sphinx_diagnostics.debug(
                                f"Blog '{getattr(blog, 'blog_title', 'Unknown')}' field '{field}' value '{blog_value}' matches one of {values}"
                            )
                            if log_file_handle:
                                log_file_handle.write(
                                    f"Blog '{getattr(blog, 'blog_title', 'Unknown')}' field '{field}' value '{blog_value}' matches one of {values}\n"
                                )
                
                # If blog matches all criteria, add it to category_blogs
                if matches_all_criteria:
                    category_blogs.append(blog)
                    sphinx_diagnostics.debug(
                        f"Blog '{getattr(blog, 'blog_title', 'Unknown')}' matches all filter criteria, adding to category_blogs"
                    )
                    if log_file_handle:
                        log_file_handle.write(
                            f"Blog '{getattr(blog, 'blog_title', 'Unknown')}' matches all filter criteria, adding to category_blogs\n"
                        )
            
            sphinx_diagnostics.info(
                f"Found {len(category_blogs)} blogs matching filter criteria"
            )
            if log_file_handle:
                log_file_handle.write(
                    f"Found {len(category_blogs)} blogs matching filter criteria\n"
                )

    # If no blogs were found for the category, log a warning and return
    if not category_blogs and not filter_criteria:
        sphinx_diagnostics.warning(
            f"No blogs found for category: {category_name} and no filter criteria provided"
        )
        if log_file_handle:
            log_file_handle.write(
                f"No blogs found for category: {category_name} and no filter criteria provided\n"
            )
        return
    elif not category_blogs:
        sphinx_diagnostics.warning(
            f"No blogs found for category: {category_name}"
        )
        if log_file_handle:
            log_file_handle.write(f"No blogs found for category: {category_name}\n")
        return
    
    # Calculate total number of pages
    total_pages = max(1, (len(category_blogs) + CATEGORY_BLOGS_PER_PAGE - 1) // CATEGORY_BLOGS_PER_PAGE)
    
    sphinx_diagnostics.info(
        f"Category {category_name} has {len(category_blogs)} blogs, creating {total_pages} pages"
    )
    if log_file_handle:
        log_file_handle.write(
            f"Category {category_name} has {len(category_blogs)} blogs, creating {total_pages} pages\n"
        )

    all_grid_items = _generate_lazy_loaded_grid_items(rocm_blogs, category_blogs)
    
    # Check if any grid items were generated
    if not all_grid_items:
        sphinx_diagnostics.warning(
            f"No grid items were generated for category: {category_name}. Skipping page generation."
        )
        return
    
    # Generate each page
    for page_num in range(1, total_pages + 1):
        start_index = (page_num - 1) * CATEGORY_BLOGS_PER_PAGE
        end_index = min(start_index + CATEGORY_BLOGS_PER_PAGE, len(all_grid_items))
        page_grid_items = all_grid_items[start_index:end_index]
        
        fixed_grid_items = []
        for grid_item in page_grid_items:
            grid_item = grid_item.replace(':img-top: ./', ':img-top: /')
            grid_item = grid_item.replace(':img-top: ./ecosystems', ':img-top: /ecosystems')
            grid_item = grid_item.replace(':img-top: ./applications', ':img-top: /applications')
            fixed_grid_items.append(grid_item)
        
        grid_content = "\n".join(fixed_grid_items)

        pagination_controls = _create_pagination_controls(
            pagination_template, page_num, total_pages, output_base
        )
        
        # Add page suffix for pages after the first
        page_title_suffix = f" - Page {page_num}" if page_num > 1 else ""
        page_description_suffix = f" (Page {page_num} of {total_pages})" if page_num > 1 else ""
        
        # Replace placeholders in the template
        updated_html = template_html.replace("{grid_items}", grid_content).replace("{datetime}", current_datetime)

        final_content = category_template.format(
            title=page_title,
            description=page_description,
            keywords=page_keywords,
            CSS=css_content,
            PAGINATION_CSS=pagination_css,
            HTML=updated_html,
            pagination_controls=pagination_controls,
            page_title_suffix=page_title_suffix,
            page_description_suffix=page_description_suffix,
            current_page=page_num,
        )

        output_filename = f"{output_base}.md" if page_num == 1 else f"{output_base}-page{page_num}.md"
        output_path = Path(blogs_directory) / output_filename

        if log_file_handle:
            log_file_handle.write(f"Generated {output_filename} with {len(page_grid_items)} grid items\n")
            log_file_handle.write(f"Page being written: {output_path} with file name: {output_filename}\n")
        
        try:
            with output_path.open("w", encoding="utf-8") as output_file:
                output_file.write(final_content)

            if log_file_handle:
                log_file_handle.write(f"Successfully wrote to file {output_path}\n")

        except FileNotFoundError as fnf_error:
            sphinx_diagnostics.error(
                f"File not found error while writing to {output_path}: {fnf_error}"
            )
            if log_file_handle:
                log_file_handle.write(f"File not found error while writing to {output_path}: {fnf_error}\n")
            raise SphinxError(f"File not found error while writing to {output_path}: {fnf_error}") from fnf_error
        except Exception as write_error:
            sphinx_diagnostics.error(
                f"Error writing to file {output_path}: {write_error}"
            )
            sphinx_diagnostics.debug(
                f"Traceback: {traceback.format_exc()}"
            )

            if log_file_handle:
                log_file_handle.write(f"Error writing to file {output_path}: {write_error}\n")
                log_file_handle.write(f"Traceback: {traceback.format_exc()}\n")

            raise SphinxError(f"Error writing to file {output_path}: {write_error}") from write_error

        # verify the file was created successfully
        if not output_path.exists():
            sphinx_diagnostics.error(
                f"File {output_path} was not created successfully"
            )
            if log_file_handle:
                log_file_handle.write(f"File {output_path} was not created successfully\n")
            raise SphinxError(f"File {output_path} was not created successfully")

        sphinx_diagnostics.info(
            f"Created {output_path} with {len(page_grid_items)} grid items (page {page_num}/{total_pages})"
        )

def _generate_grid_items(rocm_blogs, blog_list, max_items, used_blogs, skip_used=False, use_og=False):
    """Generate grid items in parallel using thread pool."""

    try:
        grid_items = []
        item_count = 0
        error_count = 0
        
        grid_params = inspect.signature(generate_grid).parameters
        if 'ROCmBlogs' not in grid_params or 'blog' not in grid_params:
            sphinx_diagnostics.critical(
                "generate_grid function does not have the expected parameters. Grid items may not be generated correctly."
            )
            sphinx_diagnostics.debug(
                f"Available parameters: {list(grid_params.keys())}"
            )
            sphinx_diagnostics.debug(
                f"Traceback: {traceback.format_exc()}"
            )
        
        # Generate grid items in parallel
        with ThreadPoolExecutor() as executor:
            grid_futures = {}

            for blog_entry in blog_list:

                if skip_used and blog_entry in used_blogs:
                    sphinx_diagnostics.debug(
                        f"Skipping blog '{getattr(blog_entry, 'blog_title', 'Unknown')}' because it's already used"
                    )
                    continue
                
                # Check if we've reached the maximum number of items
                if item_count >= max_items:
                    sphinx_diagnostics.debug(
                        f"Reached maximum number of items ({max_items}), skipping remaining blogs"
                    )
                    continue
                    
                if skip_used and blog_entry not in used_blogs:
                    used_blogs.append(blog_entry)
                    
                grid_futures[executor.submit(generate_grid, rocm_blogs, blog_entry, False, use_og)] = blog_entry
                item_count += 1

            for future in grid_futures:
                try:
                    grid_result = future.result()
                    if not grid_result or not grid_result.strip():
                        blog_entry = grid_futures[future]
                        sphinx_diagnostics.warning(
                            f"Empty grid HTML generated for blog: {getattr(blog_entry, 'blog_title', 'Unknown')}"
                        )
                        sphinx_diagnostics.debug(
                            f"Traceback: {traceback.format_exc()}"
                        )
                        error_count += 1
                        continue
                    
                    grid_items.append(grid_result)
                except Exception as future_error:
                    error_count += 1
                    blog_entry = grid_futures[future]
                    sphinx_diagnostics.error(
                        f"Error generating grid item for blog {getattr(blog_entry, 'blog_title', 'Unknown')}: {future_error}"
                    )
                    sphinx_diagnostics.debug(
                        f"Traceback: {traceback.format_exc()}"
                    )
        
        # Handle the case where no grid items were generated
        if not grid_items:
            # If there were no blogs to process or all were skipped, just return an empty list
            if item_count == 0:
                sphinx_diagnostics.warning(
                    "No blogs were available to generate grid items. Returning empty list."
                )
                return []
            
            # If we tried to process blogs but none succeeded, log a warning but don't raise an error
            sphinx_diagnostics.warning(
                "No grid items were generated despite having blogs to process. Check for errors in the generate_grid function."
            )
            sphinx_diagnostics.debug(
                f"Traceback: {traceback.format_exc()}"
            )
            return []
        
        # Log errors and completion status
        elif error_count > 0:
            sphinx_diagnostics.warning(
                f"Generated {len(grid_items)} grid items with {error_count} errors"
            )
            sphinx_diagnostics.debug(
                f"Traceback: {traceback.format_exc()}"
            )
        else:
            sphinx_diagnostics.info(
                f"Successfully generated {len(grid_items)} grid items"
            )
            
        return grid_items
    except ROCmBlogsError:
        sphinx_diagnostics.debug(
            f"Traceback: {traceback.format_exc()}"
        )
        raise
    except Exception as grid_error:
        sphinx_diagnostics.error(
            f"Error generating grid items: {grid_error}"
        )
        sphinx_diagnostics.debug(
            f"Traceback: {traceback.format_exc()}"
        )
        return []

def _generate_lazy_loaded_grid_items(rocm_blogs, blog_list):
    """Generate grid items with lazy loading for images."""
    try:
        lazy_grid_items = []
        error_count = 0

        grid_params = inspect.signature(generate_grid).parameters
        if 'lazy_load' not in grid_params:
            sphinx_diagnostics.critical(
                "generate_grid function does not support lazy_load parameter. Grid items may not be generated correctly."
            )
            sphinx_diagnostics.debug(
                f"Available parameters: {list(grid_params.keys())}"
            )
            
            # If lazy_load is not supported, fall back to regular grid generation
            sphinx_diagnostics.info(
                "Falling back to regular grid generation without lazy loading"
            )
            # Create a temporary empty list for used_blogs since we don't want to mark blogs as used
            temp_used_blogs = []
            return _generate_grid_items(rocm_blogs, blog_list, len(blog_list), temp_used_blogs, skip_used=False)
        
        for blog_entry in blog_list:
            try:
                # Generate a grid item with lazy loading
                sphinx_diagnostics.debug(
                    f"Generating lazy-loaded grid item for blog: {getattr(blog_entry, 'blog_title', 'Unknown')}"
                )
                grid_html = generate_grid(rocm_blogs, blog_entry, lazy_load=True)
                
                if not grid_html or not grid_html.strip():
                    sphinx_diagnostics.warning(
                        f"Empty grid HTML generated for blog: {getattr(blog_entry, 'blog_title', 'Unknown')}"
                    )
                    error_count += 1
                    continue
                    
                lazy_grid_items.append(grid_html)
                sphinx_diagnostics.debug(
                    f"Successfully generated lazy-loaded grid item for blog: {getattr(blog_entry, 'blog_title', 'Unknown')}"
                )
            except Exception as blog_error:
                error_count += 1
                sphinx_diagnostics.error(
                    f"Error generating grid item for blog {getattr(blog_entry, 'blog_title', 'Unknown')}: {blog_error}"
                )
                sphinx_diagnostics.debug(
                    f"Traceback: {traceback.format_exc()}"
                )
        
        # Handle the case where no grid items were generated
        if not lazy_grid_items:
            # If there were no blogs to process, just return an empty list
            if not blog_list:
                sphinx_diagnostics.warning(
                    "No blogs were provided to generate lazy-loaded grid items. Returning empty list."
                )
                return []
            
            # If we tried to process blogs but none succeeded, log a warning but don't raise an error
            sphinx_diagnostics.warning(
                "No lazy-loaded grid items were generated despite having blogs to process. Check for errors in the generate_grid function."
            )
            sphinx_diagnostics.debug(
                f"Traceback: {traceback.format_exc()}"
            )
            return []
            
        # Log errors and completion status
        elif error_count > 0:
            sphinx_diagnostics.warning(
                f"Generated {len(lazy_grid_items)} lazy-loaded grid items with {error_count} errors"
            )
            sphinx_diagnostics.debug(
                f"Traceback: {traceback.format_exc()}"
            )
        else:
            sphinx_diagnostics.info(
                f"Successfully generated {len(lazy_grid_items)} lazy-loaded grid items"
            )
            
        return lazy_grid_items
    except ROCmBlogsError:
        sphinx_diagnostics.debug(
            f"Traceback: {traceback.format_exc()}"
        )
        raise
    except Exception as lazy_load_error:
        sphinx_diagnostics.error(
            f"Error generating lazy-loaded grid items: {lazy_load_error}"
        )
        sphinx_diagnostics.debug(
            f"Traceback: {traceback.format_exc()}"
        )
        raise ROCmBlogsError(f"Error generating lazy-loaded grid-items: {lazy_load_error}") from lazy_load_error

def process_single_blog(blog_entry, rocm_blogs):
    """Process a single blog file."""
    try:
        processing_start_time = time.time()
        readme_file_path = blog_entry.file_path
        blog_directory = os.path.dirname(readme_file_path)

        if not hasattr(blog_entry, "author") or not blog_entry.author:
            sphinx_diagnostics.warning(
                f"Skipping blog {readme_file_path} without author"
            )
            return

        with open(readme_file_path, "r", encoding="utf-8", errors="replace") as source_file:
            file_content = source_file.read()

            content_lines = file_content.splitlines(True)

        webp_versions = {}

        if hasattr(blog_entry, "thumbnail") and blog_entry.thumbnail:
            try:
                blog_entry.grab_image(rocm_blogs)
                sphinx_diagnostics.info(
                    f"Found thumbnail image: {blog_entry.image_paths[0] if blog_entry.image_paths else 'None'}"
                )

                thumbnail_images = [os.path.basename(path) for path in blog_entry.image_paths] if blog_entry.image_paths else []

                if thumbnail_images:
                    for image_filename in thumbnail_images:
                        possible_image_paths = []

                        blog_dir_image = os.path.join(blog_directory, image_filename)
                        blog_dir_images_image = os.path.join(blog_directory, "images", image_filename)

                        blogs_directory = rocm_blogs.blogs_directory
                        global_image = os.path.join(blogs_directory, "images", image_filename)
                        
                        possible_image_paths.extend([blog_dir_image, blog_dir_images_image, global_image])

                        for image_path in possible_image_paths:
                            if os.path.exists(image_path) and os.path.isfile(image_path):
                                try:
                                    sphinx_diagnostics.info(
                                        f"Converting image to WebP: {image_path}"
                                    )
                                    webp_success, webp_path = convert_to_webp(image_path)

                                    path_to_optimize = webp_path if webp_success and webp_path else image_path

                                    sphinx_diagnostics.info(
                                        f"Optimizing image: {path_to_optimize}"
                                    )
                                    optimization_success, optimized_webp_path = optimize_image(path_to_optimize, thumbnail_images)

                                    if webp_success and webp_path:
                                        webp_versions[os.path.basename(image_path)] = os.path.basename(webp_path)
                                    elif optimization_success and optimized_webp_path:
                                        webp_versions[os.path.basename(image_path)] = os.path.basename(optimized_webp_path)
                                except Exception as image_error:
                                    sphinx_diagnostics.warning(
                                        f"Error processing image {image_path}: {image_error}"
                                    )
                                    sphinx_diagnostics.debug(
                                        f"Traceback: {traceback.format_exc()}"
                                    )
                                break

                blog_images_directory = os.path.join(blog_directory, "images")
                if os.path.exists(blog_images_directory) and os.path.isdir(blog_images_directory):
                    sphinx_diagnostics.info(
                        f"Checking for images in blog images directory: {blog_images_directory}"
                    )
                    for filename in os.listdir(blog_images_directory):
                        image_path = os.path.join(blog_images_directory, filename)
                        if os.path.isfile(image_path):
                            _, file_extension = os.path.splitext(filename)
                            if file_extension.lower() in ['.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff', '.tif']:
                                try:
                                    sphinx_diagnostics.info(
                                        f"Converting image to WebP: {image_path}"
                                    )
                                    webp_success, webp_path = convert_to_webp(image_path)

                                    path_to_optimize = webp_path if webp_success and webp_path else image_path

                                    sphinx_diagnostics.info(
                                        f"Optimizing image: {path_to_optimize}"
                                    )
                                    optimization_success, optimized_webp_path = optimize_image(path_to_optimize, thumbnail_images)

                                    if webp_success and webp_path:
                                        webp_versions[os.path.basename(image_path)] = os.path.basename(webp_path)
                                    elif optimization_success and optimized_webp_path:
                                        webp_versions[os.path.basename(image_path)] = os.path.basename(optimized_webp_path)
                                except Exception as image_error:
                                    sphinx_diagnostics.warning(
                                        f"Error processing image {image_path}: {image_error}"
                                    )
                                    sphinx_diagnostics.debug(
                                        f"Traceback: {traceback.format_exc()}"
                                    )

                if blog_entry.image_paths and webp_versions:
                    for i, img_path in enumerate(blog_entry.image_paths):
                        image_name = os.path.basename(img_path)
                        if image_name in webp_versions:
                            webp_name = webp_versions[image_name]
                            blog_entry.image_paths[i] = img_path.replace(image_name, webp_name)
                            sphinx_diagnostics.info(
                                f"Using WebP version for blog image: {webp_name}"
                            )

                            if hasattr(blog_entry, "thumbnail") and blog_entry.thumbnail:
                                thumbnail_name = os.path.basename(blog_entry.thumbnail)
                                if thumbnail_name == image_name:
                                    blog_entry.thumbnail = blog_entry.thumbnail.replace(thumbnail_name, webp_name)
                                    sphinx_diagnostics.info(
                                        f"Updated blog thumbnail to use WebP: {webp_name}"
                                    )

                                    for j, line in enumerate(content_lines):
                                        if image_name in line:
                                            content_lines[j] = line.replace(image_name, webp_name)
                                            sphinx_diagnostics.info(
                                                f"Updated image reference in blog content: {image_name} -> {webp_name}"
                                            )
            except Exception as thumbnail_error:
                sphinx_diagnostics.warning(
                    f"Error processing thumbnail for blog {readme_file_path}: {thumbnail_error}"
                )
                sphinx_diagnostics.debug(
                    f"Traceback: {traceback.format_exc()}"
                )

        try:
            word_count = count_words_in_markdown(file_content)
            blog_entry.set_word_count(word_count)
            sphinx_diagnostics.info(
                f"\033[33mWord count for {readme_file_path}: {word_count}\033[0m"
            )
        except Exception as word_count_error:
            sphinx_diagnostics.warning(
                f"Error counting words for blog {readme_file_path}: {word_count_error}"
            )
            sphinx_diagnostics.debug(
                f"Traceback: {traceback.format_exc()}"
            )

        try:
            authors_list = blog_entry.author.split(",")
            formatted_date = blog_entry.date.strftime("%B %d, %Y") if blog_entry.date else "No Date"
            blog_language = getattr(blog_entry, "language", "en")
            blog_category = getattr(blog_entry, "category", "blog")
            blog_tags = getattr(blog_entry, "tags", "")
            market_verticals = blog_entry.metadata.get("myst").get("html_meta", {}).get("vertical", "").split(", ") if hasattr(blog_entry, "metadata") and blog_entry.metadata else []

            # sanitize and format market verticals
            # output_filename = vertical.replace(" ", "-").lower()
            # output_filename = re.sub(r'[^a-z0-9-]', '', output_filename)

            if not market_verticals:
                market_vertical = "No Market Vertical"
            else:
                market_vertical = ", ".join([
                    f'<a href="https://rocm.blogs.amd.com/{vertical.lower().replace(" ", "-")}.html">{vertical}</a>' for vertical in market_verticals if vertical.strip()
                ])

            tag_html_list = []
            if blog_tags:
                tags_list = [tag.strip() for tag in blog_tags.split(",")]
                for tag in tags_list:
                    tag_link = truncate_string(tag)
                    tag_html = f'<a href="https://rocm.blogs.amd.com/blog/tag/{tag_link}.html">{tag}</a>'
                    tag_html_list.append(tag_html)

            tags_html = ", ".join(tag_html_list)

            category_link = truncate_string(blog_category)
            category_html = f'<a href="https://rocm.blogs.amd.com/blog/category/{category_link}.html">{blog_category.strip()}</a>'

            blog_read_time = (
                str(calculate_read_time(getattr(blog_entry, "word_count", 0)))
                if hasattr(blog_entry, "word_count")
                else "No Read Time"
            )

            authors_html = blog_entry.grab_authors(authors_list)
            if authors_html:
                authors_html = authors_html.replace("././", "../../").replace(
                    ".md", ".html"
                )

            has_valid_author = authors_html and "No author" not in authors_html

            title_line, title_line_number = None, None
            for i, line in enumerate(content_lines):
                if line.startswith("#") and line.count("#") == 1:
                    title_line = line
                    title_line_number = i
                    break

            if not title_line or title_line_number is None:
                sphinx_diagnostics.warning(
                    f"Could not find title in blog {readme_file_path}"
                )
                return

            try:
                quickshare_button = quickshare(blog_entry)
                image_css = import_file("rocm_blogs.static.css", "image_blog.css")
                image_html = import_file("rocm_blogs.templates", "image_blog.html")
                blog_css = import_file("rocm_blogs.static.css", "blog.css")
                author_attribution_template = import_file(
                    "rocm_blogs.templates", "author_attribution.html"
                )
                giscus_html = import_file("rocm_blogs.templates", "giscus.html")
            except Exception as template_error:
                sphinx_diagnostics.error(
                    f"Error loading templates for blog {readme_file_path}: {template_error}"
                )
                sphinx_diagnostics.debug(
                    f"Traceback: {traceback.format_exc()}"
                )
                raise

            if has_valid_author:
                modified_author_template = author_attribution_template
            else:
                # Create a modified template without "by {authors_string}"
                modified_author_template = author_attribution_template.replace(
                    "<span> {date} by {authors_string}.</span>", "<span> {date}</span>"
                )

            authors_html_filled = (
                modified_author_template.replace("{authors_string}", authors_html)
                .replace("{date}", formatted_date)
                .replace("{language}", blog_language)
                .replace("{category}", category_html)
                .replace("{tags}", tags_html)
                .replace("{read_time}", blog_read_time)
                .replace("{word_count}", str(getattr(blog_entry, "word_count", "No Word Count")))
                .replace("{market_vertical}", market_vertical)
            )

            try:
                blog_path = Path(blog_entry.file_path)
                blogs_directory_path = Path(rocm_blogs.blogs_directory)
                
                try:
                    relative_path = blog_path.relative_to(blogs_directory_path)

                    directory_depth = len(relative_path.parts) - 1
                    sphinx_diagnostics.info(
                        f"Blog depth: {directory_depth} for {blog_entry.file_path}"
                    )

                    parent_directories = "../" * directory_depth
                    
                    sphinx_diagnostics.info(
                        f"Using {parent_directories} for blog at depth {directory_depth}: {blog_entry.file_path}"
                    )

                    if blog_entry.image_paths:
                        image_filename = os.path.basename(blog_entry.image_paths[0])
                    else:
                        image_filename = "generic.jpg"

                    blog_image_path = f"{parent_directories}_images/{image_filename}"
                    
                    sphinx_diagnostics.info(
                        f"Using image path for blog: {blog_image_path}"
                    )

                except ValueError:
                    sphinx_diagnostics.warning(
                        f"Could not determine relative path for {blog_entry.file_path}, using default image path"
                    )
                    if blog_entry.image_paths:
                        blog_image_path = f"../../_images/{blog_entry.image_paths[0]}"
                    else:
                        blog_image_path = "../../_images/generic.jpg"

                image_template_filled = (
                    image_html.replace("{IMAGE}", blog_image_path)
                    .replace("{TITLE}", getattr(blog_entry, "blog_title", ""))
                )
            except Exception as image_path_error:
                sphinx_diagnostics.error(
                    f"Error determining image path for blog {readme_file_path}: {image_path_error}"
                )
                sphinx_diagnostics.debug(
                    f"Traceback: {traceback.format_exc()}"
                )
                raise

            blog_template = f"""
<style>
{blog_css}
</style>
"""
            image_template = f"""
<style>
{image_css}
</style>
{image_template_filled}
"""

            try:
                updated_lines = content_lines.copy()
                updated_lines.insert(title_line_number + 1, f"\n{blog_template}\n")
                updated_lines.insert(title_line_number + 2, f"\n{image_template}\n")
                updated_lines.insert(title_line_number + 3, f"\n{authors_html_filled}\n")
                updated_lines.insert(title_line_number + 4, f"\n{quickshare_button}\n")

                updated_lines.append(f"\n\n{giscus_html}\n")

                with open(readme_file_path, "w", encoding="utf-8", errors="replace") as output_file:
                    output_file.writelines(updated_lines)
            except Exception as write_error:
                sphinx_diagnostics.error(
                    f"Error writing to blog file {readme_file_path}: {write_error}"
                )
                sphinx_diagnostics.debug(
                    f"Traceback: {traceback.format_exc()}"
                )
                raise

            processing_end_time = time.time()
            processing_duration = processing_end_time - processing_start_time
            sphinx_diagnostics.info(
                f"\033[33mSuccessfully processed blog {readme_file_path} in \033[96m{processing_duration:.2f} milliseconds\033[33m\033[0m"
            )
        except Exception as metadata_error:
            sphinx_diagnostics.warning(
                f"Error processing metadata for blog {readme_file_path}: {metadata_error}"
            )
            sphinx_diagnostics.debug(
                f"Traceback: {traceback.format_exc()}"
            )
            raise

    except Exception as process_error:
        sphinx_diagnostics.error(
            f"Error processing blog {getattr(blog_entry, 'file_path', 'Unknown')}: {process_error}"
        )
        sphinx_diagnostics.debug(
            f"Traceback: {traceback.format_exc()}"
        )
        raise