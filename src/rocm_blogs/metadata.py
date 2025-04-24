import json
import os
import re
import sys
import traceback
from datetime import datetime
from pathlib import Path

from sphinx.util import logging as sphinx_logging
from .utils import calculate_day_of_week
from rocm_blogs import ROCmBlogs
from rocm_blogs.constants import SUPPORTED_FORMATS

sphinx_diagnostics = sphinx_logging.getLogger(__name__)

def metadata_generator(rocm_blogs_instance: ROCmBlogs) -> None:
    """Generate metadata for the ROCm blogs with Open Graph support."""
    generation_start_time = datetime.now()
    sphinx_diagnostics.info(
        f"Starting metadata generation at {generation_start_time.isoformat()}"
    )
    sphinx_diagnostics.info("=" * 80)
    sphinx_diagnostics.info(
        "Generating metadata for ROCm blogs with Open Graph protocol support..."
    )
    sphinx_diagnostics.info("-" * 80)

    open_graph_metadata_template = """---
blogpost: true
blog_title: "{blog_title}"
date: {date}
author: "{author}"
thumbnail: '{thumbnail}'
tags: {tags}
category: {category}
language: English
myst:
    html_meta:
        "author": "{author}"
        "description lang=en": "{description}"
        "keywords": "{keywords}"
        "amd_category": "Developer Resources"
        "amd_asset_type": "Blog"
        "amd_technical_blog_type": "{amd_technical_blog_type}"
        "amd_blog_hardware_platforms": "{amd_blog_hardware_platforms}"
        "amd_blog_development_tools": "{amd_blog_deployment_tools}"
        "amd_blog_applications": "{amd_applications}"
        "amd_blog_topic_categories": "{amd_blog_category_topic}"
        "amd_blog_authors": "{release_author}"
        "amd_release_date": "{amd_blog_releasedate}"
        "property=og:title": "{blog_title}"
        "property=og:description": "{description}"
        "property=og:type": "article"
        "property=og:url": "https://rocm.blogs.amd.com{blog_url}"
        "property=og:site_name": "ROCm Blogs"
        "property=og:locale": "en_US"
        "property=og:image": "https://rocm.blogs.amd.com/_images/{og_image}"
        "property=article:published_time": "{amd_blog_releasedate}"
        "property=article:author": "{release_author}"
        "property=article:tag": "{keywords}"
---
"""

    total_blogs_processed = 0
    total_blogs_successful = 0
    total_blogs_error = 0
    total_blogs_warning = 0
    total_blogs_skipped = 0
    total_non_blog_files = 0

    all_error_details = []

    logs_directory = Path("logs")
    logs_directory.mkdir(exist_ok=True)

    metadata_log_filepath = logs_directory / "metadata_generation.log"
    sphinx_diagnostics.info(
        f"Detailed logs will be written to: {metadata_log_filepath}"
    )

    with open(metadata_log_filepath, "w", encoding="utf-8") as metadata_log_file_handle:
        metadata_log_file_handle.write(
            f"ROCm Blogs Metadata Generation Log - {generation_start_time.isoformat()}\n"
        )
        metadata_log_file_handle.write("=" * 80 + "\n\n")

        for current_blog_index, blog_filepath in enumerate(rocm_blogs_instance.blog_paths):
            current_blog_start_time = datetime.now()
            current_blog_path = Path(blog_filepath)
            blog_identifier = f"Blog {current_blog_index + 1}/{len(rocm_blogs_instance.blog_paths)}"

            try:
                sphinx_diagnostics.info(
                    f"Processing {blog_identifier}: {current_blog_path.name}"
                )
                metadata_log_file_handle.write(
                    f"\n{'-' * 40}\nProcessing: {blog_filepath}\n{'-' * 40}\n"
                )

                if not current_blog_path.exists():
                    error_message = f"Blog file does not exist: {blog_filepath}"
                    sphinx_diagnostics.error(
                        f"{error_message}"
                    )
                    metadata_log_file_handle.write(f"ERROR: {error_message}\n")
                    all_error_details.append({"blog": blog_filepath, "error": error_message})
                    total_blogs_error += 1
                    continue

                if not os.access(blog_filepath, os.R_OK):
                    error_message = f"Blog file is not readable: {blog_filepath}"
                    sphinx_diagnostics.error(
                        f"{error_message}"
                    )
                    metadata_log_file_handle.write(f"ERROR: {error_message}\n")
                    all_error_details.append({"blog": blog_filepath, "error": error_message})
                    total_blogs_error += 1
                    continue

                with open(blog_filepath, "r", encoding="utf-8", errors="replace") as blog_file_handle:
                    blog_file_content = blog_file_handle.read()

                metadata_regex_pattern = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
                metadata_match = metadata_regex_pattern.search(blog_file_content)

                if not metadata_match:
                    sphinx_diagnostics.info(
                        f"Skipping {blog_identifier}: No metadata section found, not a blog post"
                    )
                    metadata_log_file_handle.write(
                        f"INFO: No metadata section found, skipping as not a blog post\n"
                    )
                    total_non_blog_files += 1
                    total_blogs_skipped += 1
                    continue

                metadata_content_extracted = metadata_match.group(1)
                blogpost_regex_pattern = re.compile(r"blogpost:\s*true", re.IGNORECASE)
                if not blogpost_regex_pattern.search(metadata_content_extracted):
                    sphinx_diagnostics.info(
                        f"Skipping {blog_identifier}: Not marked as a blog post (blogpost: true not found)"
                    )
                    metadata_log_file_handle.write(
                        f"INFO: Not marked as a blog post in metadata, skipping\n"
                    )
                    total_non_blog_files += 1
                    total_blogs_skipped += 1
                    continue

                try:
                    extracted_metadata = rocm_blogs_instance.extract_metadata_from_file(blog_filepath)
                    metadata_log_file_handle.write(
                        f"Extracted metadata: {json.dumps(extracted_metadata, indent=2)}\n"
                    )
                except Exception as metadata_extraction_exception:
                    error_message = f"Failed to extract metadata from {blog_filepath}: {metadata_extraction_exception}"
                    sphinx_diagnostics.error(
                        f"{error_message}"
                    )
                    sphinx_diagnostics.debug(
                        f"Traceback: {traceback.format_exc()}"
                    )
                    metadata_log_file_handle.write(f"ERROR: {error_message}\n")
                    metadata_log_file_handle.write(f"Traceback: {traceback.format_exc()}\n")
                    all_error_details.append({"blog": blog_filepath, "error": error_message})
                    total_blogs_error += 1
                    continue

                if not extracted_metadata:
                    sphinx_diagnostics.warning(
                        f"No metadata found for blog: {blog_filepath}"
                    )
                    metadata_log_file_handle.write(f"WARNING: No metadata found for blog\n")
                    total_blogs_warning += 1
                    total_blogs_skipped += 1
                    continue

                if not extracted_metadata.get("blogpost"):
                    sphinx_diagnostics.info(
                        f"Skipping {blog_identifier}: Not marked as a blog post in extracted metadata"
                    )
                    metadata_log_file_handle.write(
                        f"INFO: Not marked as a blog post in extracted metadata, skipping\n"
                    )
                    total_non_blog_files += 1
                    total_blogs_skipped += 1
                    continue

                total_blogs_processed += 1

                try:
                    myst_section = extracted_metadata.get("myst", {})
                    html_metadata = myst_section.get("html_meta", {})
                    blog_description = html_metadata.get("description lang=en", "")
                    if not blog_description:
                        sphinx_diagnostics.warning(
                            f"No description found for blog: {blog_filepath}"
                        )
                        metadata_log_file_handle.write(f"WARNING: No description found\n")
                        total_blogs_warning += 1
                        blog_description = "ROCm Blog post"

                    if len(blog_description) > 50:
                        sphinx_diagnostics.debug(
                            f"Description: {blog_description[:50]}..."
                        )
                        metadata_log_file_handle.write(f"Description: {blog_description[:50]}...\n")
                    else:
                        sphinx_diagnostics.debug(
                            f"Description: {blog_description}"
                        )
                        metadata_log_file_handle.write(f"Description: {blog_description}\n")

                    blog_keywords = html_metadata.get("keywords", "")
                    if not blog_keywords:
                        sphinx_diagnostics.debug(
                            f"No keywords found for blog: {blog_filepath}"
                        )
                        metadata_log_file_handle.write(f"INFO: No keywords found\n")
                    else:
                        sphinx_diagnostics.debug(
                            f"Keywords: {blog_keywords}"
                        )
                        metadata_log_file_handle.write(f"Keywords: {blog_keywords}\n")

                    title_regex_pattern = re.compile(r"^# (.+)$", re.MULTILINE)
                    title_match = title_regex_pattern.search(blog_file_content)
                    if title_match:
                        extracted_title = title_match.group(1)
                        extracted_title = extracted_title.replace('"', "'")
                        extracted_metadata["blog_title"] = extracted_title
                        sphinx_diagnostics.debug(
                            f"Extracted title from markdown: {extracted_title}"
                        )
                        metadata_log_file_handle.write(f"Extracted title: {extracted_title}\n")
                    else:
                        fallback_description = blog_description.replace("'", '"')
                        extracted_metadata["blog_title"] = fallback_description
                        sphinx_diagnostics.warning(
                            f"No title found in markdown for {blog_filepath}, using description as title"
                        )
                        metadata_log_file_handle.write(
                            f"WARNING: No title found in markdown, using description as title: {fallback_description[:30]}...\n"
                        )
                        total_blogs_warning += 1
                except Exception as metadata_field_exception:
                    error_message = f"Error extracting metadata from {blog_filepath}: {metadata_field_exception}"
                    sphinx_diagnostics.error(
                        f"{error_message}"
                    )
                    sphinx_diagnostics.debug(
                        f"Traceback: {traceback.format_exc()}"
                    )
                    metadata_log_file_handle.write(f"ERROR: {error_message}\n")
                    metadata_log_file_handle.write(f"Traceback: {traceback.format_exc()}\n")
                    all_error_details.append({"blog": blog_filepath, "error": error_message})
                    total_blogs_error += 1
                    continue

                try:
                    if "author" not in extracted_metadata:
                        extracted_metadata["author"] = "No author"
                        sphinx_diagnostics.warning(
                            f"No author found for blog: {blog_filepath}, using default"
                        )
                        metadata_log_file_handle.write(
                            f"WARNING: No author found, using default: 'No author'\n"
                        )
                        total_blogs_warning += 1
                    else:
                        extracted_metadata["author"] = extracted_metadata["author"].replace("'", "''")
                        sphinx_diagnostics.debug(
                            f"Author: {extracted_metadata['author']}"
                        )
                        release_author = ";".join(extracted_metadata.get("author", "").split(","))
                        metadata_log_file_handle.write(f"Author: {extracted_metadata['author']}\n")

                    if not extracted_metadata.get("thumbnail"):
                        sphinx_diagnostics.info(
                            f"Blog: {blog_filepath} does not have a thumbnail specified: {extracted_metadata}"
                        )
                        extracted_thumbnail = "generic.webp"
                        og_image_extracted = "generic.webp"
                        sphinx_diagnostics.debug(
                            f"No thumbnail specified for blog: {blog_filepath}"
                        )
                        metadata_log_file_handle.write(f"INFO: No thumbnail specified\n")
                    else:
                        sphinx_diagnostics.debug(
                            f"Thumbnail: {extracted_metadata['thumbnail']}"
                        )
                        
                        # Store original thumbnail for og:image (non-webp)
                        extracted_og_image = extracted_metadata["thumbnail"]
                        extracted_thumbnail = extracted_metadata["thumbnail"]
                        
                        # Convert thumbnail to webp for regular use
                        for f_format in SUPPORTED_FORMATS:
                            if f_format in extracted_metadata["thumbnail"]:
                                og_image_extracted = extracted_metadata["thumbnail"].replace(f_format, ".webp")
                                break

                        if ".webp" not in og_image_extracted:
                            og_image_extracted = og_image_extracted.split(".")[0] + ".webp"
                        
                        metadata_log_file_handle.write(f"Thumbnail: {og_image_extracted}\n")
                        metadata_log_file_handle.write(f"OG Image: {extracted_og_image}\n")

                    if "date" not in extracted_metadata:
                        extracted_metadata["date"] = datetime.now().strftime("%d %B %Y")
                        sphinx_diagnostics.warning(
                            f"No date found for blog: {blog_filepath}, using current date"
                        )
                        metadata_log_file_handle.write(
                            f"WARNING: No date found, using current date: {extracted_metadata['date']}\n"
                        )
                        total_blogs_warning += 1
                    else:
                        sphinx_diagnostics.debug(
                            f"Date: {extracted_metadata['date']}"
                        )
                        metadata_log_file_handle.write(f"Date: {extracted_metadata['date']}\n")

                    if "tags" not in extracted_metadata:
                        extracted_metadata["tags"] = ""
                        sphinx_diagnostics.debug(
                            f"No tags specified for blog: {blog_filepath}"
                        )
                        metadata_log_file_handle.write(f"INFO: No tags specified\n")
                    else:
                        sphinx_diagnostics.debug(
                            f"Tags: {extracted_metadata['tags']}"
                        )
                        metadata_log_file_handle.write(f"Tags: {extracted_metadata['tags']}\n")

                    if "category" not in extracted_metadata:
                        extracted_metadata["category"] = "ROCm Blog"
                        sphinx_diagnostics.debug(
                            f"No category specified for blog: {blog_filepath}, using default"
                        )
                        metadata_log_file_handle.write(
                            f"INFO: No category specified, using default: 'ROCm Blog'\n"
                        )
                    else:
                        sphinx_diagnostics.debug(
                            f"Category: {extracted_metadata['category']}"
                        )
                        metadata_log_file_handle.write(f"Category: {extracted_metadata['category']}\n")

                    metadata_log_file_handle.write(f"HTML Metadata: {json.dumps(html_metadata, indent=2)}\n")
                        
                    # Extract AMD-specific metadata fields with default values if missing
                    amd_technical_blog_type = html_metadata.get("amd_technical_blog_type", "Applications and Models")
                    
                    amd_blog_hardware_platforms = html_metadata.get("amd_blog_hardware_platforms", "Instinct GPUs")
                    
                    amd_blog_deployment_tools = html_metadata.get("amd_blog_development_tools", "ROCm Software")
                    
                    amd_applications = html_metadata.get("amd_blog_applications", html_metadata.get("amd_applications", "AI & Intelligent Systems; Industry Applications & Use Cases"))
                    
                    amd_blog_category_topic = html_metadata.get("amd_blog_topic_categories", "AI & Intelligent Systems; Industry Applications & Use Cases")

                    # any input with commas will cause errors
                    weird_inputs_amd_blog_applications = ['Design, Simulation & Modeling']

                    if any(weird_input in amd_applications for weird_input in weird_inputs_amd_blog_applications):
                        # Replace commas with /%2c/ in the input string
                        for weird_input in weird_inputs_amd_blog_applications:
                            if weird_input in amd_applications:
                                amd_applications = amd_applications.replace(weird_input, weird_input.replace(",", "/%2c/"))
                                amd_applications = ";".join(amd_applications.split(","))
                                amd_applications = amd_applications.replace("/%2c/", ",")
                                metadata_log_file_handle.write(f"AMD Blog Applications: {amd_applications}\n")
                                break
                    else:
                        amd_applications = ";".join(amd_applications.split(","))
                        metadata_log_file_handle.write(f"AMD Blog Applications: {amd_applications}\n")

                    amd_technical_blog_type = ";".join(amd_technical_blog_type.split(","))
                    metadata_log_file_handle.write(f"AMD Technical Blog Type: {amd_technical_blog_type}\n")

                    amd_blog_hardware_platforms = ";".join(amd_blog_hardware_platforms.split(","))
                    metadata_log_file_handle.write(f"AMD Blog Hardware Platforms: {amd_blog_hardware_platforms}\n")

                    amd_blog_deployment_tools = ";".join(amd_blog_deployment_tools.split(","))
                    metadata_log_file_handle.write(f"AMD Blog Deployment Tools: {amd_blog_deployment_tools}\n")

                    amd_blog_category_topic = ";".join(amd_blog_category_topic.split(","))
                    metadata_log_file_handle.write(f"AMD Blog Category Topic: {amd_blog_category_topic}\n")

                    release_author = ";".join(release_author.split(","))
                    metadata_log_file_handle.write(f"Release Author: {release_author}\n")

                except KeyError as key_error:
                    error_message = f"KeyError: {key_error} in {blog_filepath}"
                    sphinx_diagnostics.error(
                        f"{error_message}"
                    )
                    sphinx_diagnostics.debug(
                        f"Traceback: {traceback.format_exc()}"
                    )
                    metadata_log_file_handle.write(f"ERROR: {error_message}\n")
                    metadata_log_file_handle.write(f"Traceback: {traceback.format_exc()}\n")
                    all_error_details.append({"blog": blog_filepath, "error": error_message})
                    total_blogs_error += 1
                    continue
                    
                except Exception as default_field_exception:
                    error_message = f"Error setting default values for {blog_filepath}: {default_field_exception}"
                    sphinx_diagnostics.error(
                        f"{error_message}"
                    )
                    sphinx_diagnostics.debug(
                        f"Traceback: {traceback.format_exc()}"
                    )
                    metadata_log_file_handle.write(f"ERROR: {error_message}\n")
                    metadata_log_file_handle.write(f"Traceback: {traceback.format_exc()}\n")
                    all_error_details.append({"blog": blog_filepath, "error": error_message})
                    total_blogs_error += 1
                    continue

                if "Sept" in extracted_metadata["date"]:
                    extracted_metadata["date"] = extracted_metadata["date"].replace("Sept", "Sep")
                    sphinx_diagnostics.debug(
                        f"Normalized date format: {extracted_metadata['date']}"
                    )
                    metadata_log_file_handle.write(
                        f"INFO: Normalized date format: {extracted_metadata['date']}\n"
                    )

                try:
                    # Check if release date is already present in metadata
                    amd_blog_releasedate = ""
                    
                    # If no release date exists, generate one from the blog's date
                    if not amd_blog_releasedate:
                        
                        blog_date = extracted_metadata.get("date", "")
                        
                        # Normalize date format - remove leading zeros to avoid octal literals
                        if blog_date.startswith("0"):
                            day_part = blog_date.split()[0].lstrip("0")
                            blog_date = " ".join([day_part] + blog_date.split()[1:])

                        month_day_year_regex = re.compile(r'([A-Za-z]{3,9})\s+(\d{1,2})\s+(\d{4})')
                        mmm_dd_yyyy_match = month_day_year_regex.search(blog_date)

                        if mmm_dd_yyyy_match:
                            month, day, year = mmm_dd_yyyy_match.groups()
                            
                            # Map month names to numbers (case insensitive)
                            month_mapping = {
                                'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
                                'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12
                            }
                            
                            # Get month number
                            month_num = month_mapping.get(month.lower()[:3])
                            
                            if month_num:
                                # Create a date object
                                parsed_date = datetime(int(year), month_num, int(day))
                            
                        # Date parsing with multiple formats
                        date_formats = [
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
                        
                        parsed_date = None
                        for date_format in date_formats:
                            try:
                                parsed_date = datetime.strptime(blog_date, date_format)
                                break
                            except ValueError:
                                continue

                        if not parsed_date:
                            parsed_date = datetime.now()
                            sphinx_diagnostics.warning(
                                f"Could not parse date '{blog_date}' for {blog_filepath}, using current date"
                            )
                            metadata_log_file_handle.write(
                                f"WARNING: Could not parse date '{blog_date}', using current date\n"
                            )
                            total_blogs_warning += 1
                        
                        # Extract day, month, year components
                        day = parsed_date.day
                        month = parsed_date.month
                        year = parsed_date.year
                        
                        day_of_week = calculate_day_of_week(year, parsed_date.month, day)
                        
                        amd_blog_releasedate = f"{year}/{month}/{day}"
                        
                        sphinx_diagnostics.debug(f"Generated release date: {amd_blog_releasedate}")
                        metadata_log_file_handle.write(f"Generated release date: {amd_blog_releasedate}\n")

                        # Handle the release date - first try to find it in the blog metadata
                        release_date_str = ""

                        valid_release_date = False
                        valid_release_date_format = "%Y/%m/%d@%H:%M:%S"

                        if release_date_str:
                                
                            try:
                                parsed_date = datetime.strptime(release_date_str, valid_release_date_format)
                                valid_release_date = True
                                break
                            except ValueError:
                                continue
                        
                        if not valid_release_date:
                            # No release date found, use the blog's date
                            try:
                                for fmt in date_formats:
                                    try:
                                        date_string = datetime.strptime(extracted_metadata["date"], fmt).strftime(
                                            "%d %B %Y"
                                        )
                                        break
                                    except ValueError:
                                        continue
                                day, month, year = date_string.split(" ")

                                month = month[:3]

                                date_formats = ["%b", "%B"]

                                for fmt in date_formats:
                                    try:
                                        d_month = datetime.strptime(month, fmt).month
                                        break
                                    except ValueError:
                                        continue

                                day = int(day)
                                year = int(year)
                                month = int(d_month)

                                day_of_week = calculate_day_of_week(year, d_month, day)

                                amd_blog_releasedate = datetime.strptime(
                                    f"{year}/{month}/{day}",
                                    "%Y/%m/%d@%H:%M:%S",
                                ).strftime("%Y/%m/%d@%H:%M:%S")

                            except ValueError:
                                sphinx_diagnostics.warning(
                                    f"Could not parse date '{extracted_metadata['date']}' for {blog_filepath}, using current time"
                                )
                                metadata_log_file_handle.write(
                                    f"WARNING: Could not parse date '{extracted_metadata['date']}', using current time: {amd_blog_releasedate}\n"
                                )
                                total_blogs_warning += 1
                    
                    sphinx_diagnostics.debug(f"Generated AMD Release Date: {amd_blog_releasedate}")
                    metadata_log_file_handle.write(f"Generated AMD Release Date: {amd_blog_releasedate}\n")

                    try:
                        relative_blog_path = os.path.relpath(blog_filepath, rocm_blogs_instance.blogs_directory)
                        blog_directory = os.path.dirname(relative_blog_path)
                        generated_blog_url = f"/{blog_directory}/README.html"
                        sphinx_diagnostics.debug(
                            f"Generated blog URL: {generated_blog_url}"
                        )
                        metadata_log_file_handle.write(f"Generated blog URL: {generated_blog_url}\n")
                    except Exception as blog_url_exception:
                        error_message = f"Error generating blog URL for {blog_filepath}: {blog_url_exception}"
                        sphinx_diagnostics.error(
                            f"{error_message}"
                        )
                        sphinx_diagnostics.debug(
                            f"Traceback: {traceback.format_exc()}"
                        )
                        metadata_log_file_handle.write(f"ERROR: {error_message}\n")
                        metadata_log_file_handle.write(f"Traceback: {traceback.format_exc()}\n")
                        generated_blog_url = "/blogs"
                        sphinx_diagnostics.warning(
                            f"Using fallback blog URL: {generated_blog_url}"
                        )
                        metadata_log_file_handle.write(
                            f"WARNING: Using fallback blog URL: {generated_blog_url}\n"
                        )
                        total_blogs_warning += 1
                except Exception as og_metadata_exception:
                    error_message = f"Error generating Open Graph metadata for {blog_filepath}: {og_metadata_exception}"
                    sphinx_diagnostics.error(
                        f"{error_message}"
                    )
                    sphinx_diagnostics.debug(
                        f"Traceback: {traceback.format_exc()}"
                    )
                    metadata_log_file_handle.write(f"ERROR: {error_message}\n")
                    metadata_log_file_handle.write(f"Traceback: {traceback.format_exc()}\n")
                    all_error_details.append({"blog": blog_filepath, "error": error_message})
                    total_blogs_error += 1
                    continue

                try:
                    formatted_metadata_content = open_graph_metadata_template.format(
                        blog_title=extracted_metadata["blog_title"],
                        date=extracted_metadata["date"],
                        author=extracted_metadata["author"],
                        thumbnail=extracted_thumbnail,
                        og_image=og_image_extracted,
                        tags=extracted_metadata.get("tags", ""),
                        category=extracted_metadata.get("category", "ROCm Blog"),
                        description=blog_description,
                        keywords=blog_keywords,
                        blog_url=generated_blog_url,
                        amd_technical_blog_type=amd_technical_blog_type,
                        amd_blog_hardware_platforms=amd_blog_hardware_platforms,
                        amd_blog_deployment_tools=amd_blog_deployment_tools,
                        amd_applications=amd_applications,
                        amd_blog_category_topic=amd_blog_category_topic,
                        amd_blog_releasedate=amd_blog_releasedate,
                        release_author=release_author,
                    )
                    sphinx_diagnostics.debug(
                        f"Generated metadata content for {blog_filepath}"
                    )
                    metadata_log_file_handle.write(
                        f"Generated metadata content: {formatted_metadata_content}\n"
                    )
                    metadata_log_file_handle.write(
                        f"Successfully generated metadata content\n"
                    )
                except Exception as format_exception:
                    error_message = f"Error formatting metadata content for {blog_filepath}: {format_exception}"
                    sphinx_diagnostics.error(
                        f"{error_message}"
                    )
                    sphinx_diagnostics.debug(
                        f"Traceback: {traceback.format_exc()}"
                    )
                    metadata_log_file_handle.write(f"ERROR: {error_message}\n")
                    metadata_log_file_handle.write(f"Traceback: {traceback.format_exc()}\n")
                    all_error_details.append({"blog": blog_filepath, "error": error_message})
                    total_blogs_error += 1
                    continue

                try:
                    metadata_regex_pattern = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
                    if metadata_regex_pattern.search(blog_file_content):
                        blog_file_content = re.sub(
                            r"^---\s*\n(.*?)\n---\s*\n",
                            formatted_metadata_content,
                            blog_file_content,
                            flags=re.DOTALL,
                        )
                        sphinx_diagnostics.debug(
                            f"Replaced existing metadata in {blog_filepath}"
                        )
                        metadata_log_file_handle.write(f"Replaced existing metadata\n")
                    else:
                        blog_file_content = formatted_metadata_content + blog_file_content
                        sphinx_diagnostics.debug(
                            f"Added new metadata to {blog_filepath}"
                        )
                        metadata_log_file_handle.write(f"Added new metadata\n")
                    blog_file_content = blog_file_content.strip() + "\n"
                    with open(blog_filepath, "w", encoding="utf-8", errors="replace") as blog_file_handle_write:
                        blog_file_handle_write.write(blog_file_content)
                    sphinx_diagnostics.info(
                        f"Metadata successfully added to {blog_filepath}"
                    )
                    metadata_log_file_handle.write(f"Metadata successfully added to file\n")
                    total_blogs_successful += 1
                except Exception as write_exception:
                    error_message = f"Error writing metadata to {blog_filepath}: {write_exception}"
                    sphinx_diagnostics.error(
                        f"{error_message}"
                    )
                    sphinx_diagnostics.debug(
                        f"Traceback: {traceback.format_exc()}"
                    )
                    metadata_log_file_handle.write(f"ERROR: {error_message}\n")
                    metadata_log_file_handle.write(f"Traceback: {traceback.format_exc()}\n")
                    all_error_details.append({"blog": blog_filepath, "error": error_message})
                    total_blogs_error += 1
                    continue

                current_blog_end_time = datetime.now()
                current_blog_duration = (current_blog_end_time - current_blog_start_time).total_seconds()
                sphinx_diagnostics.debug(
                    f"Processed {blog_identifier} in {current_blog_duration:.2f} seconds"
                )
                metadata_log_file_handle.write(
                    f"Processing completed in {current_blog_duration:.2f} seconds\n"
                )

            except Exception as blog_processing_exception:
                error_message = f"Unexpected error processing {blog_filepath}: {blog_processing_exception}"
                sphinx_diagnostics.error(
                    f"{error_message}"
                )
                sphinx_diagnostics.debug(
                    f"Traceback: {traceback.format_exc()}"
                )
                metadata_log_file_handle.write(f"ERROR: {error_message}\n")
                metadata_log_file_handle.write(f"Traceback: {traceback.format_exc()}\n")
                all_error_details.append({"blog": blog_filepath, "error": error_message})
                total_blogs_error += 1

        end_time = datetime.now()
        total_generation_duration = (end_time - generation_start_time).total_seconds()

        metadata_log_file_handle.write("\n" + "=" * 80 + "\n")
        metadata_log_file_handle.write("METADATA GENERATION SUMMARY\n")
        metadata_log_file_handle.write("-" * 80 + "\n")
        metadata_log_file_handle.write(f"Total README files found: {len(rocm_blogs_instance.blog_paths)}\n")
        metadata_log_file_handle.write(f"Files not marked as blogs (skipped): {total_non_blog_files}\n")
        metadata_log_file_handle.write(f"Total blogs processed: {total_blogs_processed}\n")
        metadata_log_file_handle.write(f"Successful: {total_blogs_successful}\n")
        metadata_log_file_handle.write(f"Errors: {total_blogs_error}\n")
        metadata_log_file_handle.write(f"Warnings: {total_blogs_warning}\n")
        metadata_log_file_handle.write(f"Skipped: {total_blogs_skipped}\n")
        metadata_log_file_handle.write(f"Total time: {total_generation_duration:.2f} seconds\n")

        if all_error_details:
            metadata_log_file_handle.write("\nERROR DETAILS:\n")
            metadata_log_file_handle.write("-" * 80 + "\n")
            for index, error_detail in enumerate(all_error_details):
                metadata_log_file_handle.write(f"{index+1}. Blog: {error_detail['blog']}\n")
                metadata_log_file_handle.write(f"   Error: {error_detail['error']}\n\n")

    sphinx_diagnostics.info("=" * 80)
    sphinx_diagnostics.info("METADATA GENERATION SUMMARY")
    sphinx_diagnostics.info("-" * 80)
    sphinx_diagnostics.info(f"Total README files found: {len(rocm_blogs_instance.blog_paths)}")
    sphinx_diagnostics.info(f"Files not marked as blogs (skipped): {total_non_blog_files}")
    sphinx_diagnostics.info(f"Total blogs processed: {total_blogs_processed}")
    sphinx_diagnostics.info(f"Successful: {total_blogs_successful}")
    sphinx_diagnostics.info(f"Errors: {total_blogs_error}")
    sphinx_diagnostics.info(f"Warnings: {total_blogs_warning}")
    sphinx_diagnostics.info(f"Skipped: {total_blogs_skipped}")
    sphinx_diagnostics.info(f"Total time: {total_generation_duration:.2f} seconds")

    if total_blogs_error > 0:
        sphinx_diagnostics.error(
            f"Encountered {total_blogs_error} errors during metadata generation"
        )
        sphinx_diagnostics.error(
            "See log file for details: " + str(metadata_log_filepath)
        )
    else:
        sphinx_diagnostics.info(
            "Metadata generation completed successfully with no errors"
        )

    sphinx_diagnostics.info("=" * 80)
