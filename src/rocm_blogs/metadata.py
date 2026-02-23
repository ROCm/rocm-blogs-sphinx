import json
import os
import re
import sys
import traceback
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from rocm_blogs import ROCmBlogs
from sphinx.util import logging as sphinx_logging

from .logger.logger import (create_step_log_file,
                            is_logging_enabled_from_config, log_message,
                            safe_log_close, safe_log_write)
from .utils import calculate_day_of_week

# Blog classification constants
PRIMARY_TAGS = {
    "AI": ["LLM", "GenAI", "Diffusion Model", "Reinforcement Learning"],
    "HPC": ["HPC", "System-Tuning", "OpenMP"],
    "Data Science": [
        "Time Series",
        "Linear Algebra",
        "Computer Vision",
        "Speech",
        "Scientific Computing",
    ],
    "Systems": ["Kubernetes", "Memory", "Serving", "Partner Applications"],
    "Developers": ["C++", "Compiler", "JAX", "Developers"],
    "Robotics": ["Robotics"],
}

SECONDARY_TAGS = {
    "AI": [
        "PyTorch",
        "TensorFlow",
        "AI/ML",
        "Multimodal",
        "Recommendation Systems",
        "Fine-Tuning",
    ],
    "HPC": ["Performance", "Profiling", "Hardware"],
    "Data Science": ["Optimization"],
    "Systems": ["Installation"],
    "Developers": [],
}

TAG_WEIGHTS = {
    "LLM": 1.0,
    "GenAI": 1.0,
    "Diffusion Model": 1.0,
    "Reinforcement Learning": 1.0,
    "HPC": 2.0,
    "System-Tuning": 1.0,
    "OpenMP": 1.0,
    "Time Series": 1.0,
    "Linear Algebra": 1.0,
    "Computer Vision": 1.0,
    "Speech": 1.0,
    "Scientific Computing": 1.0,
    "Kubernetes": 1.0,
    "Memory": 1.0,
    "Serving": 1.0,
    "Partner Applications": 1.0,
    "C++": 1.0,
    "Compiler": 1.0,
    "JAX": 1.0,
    "Developers": 2.0,
    "Robotics": 2.0,
    "PyTorch": 1.0,
    "TensorFlow": 1.0,
    "Multimodal": 1.0,
    "Recommendation Systems": 1.0,
    "Performance": 1.0,
    "Profiling": 1.0,
    "Hardware": 1.0,
    "Optimization": 1.0,
    "AI/ML": 2.0,
    "Installation": 1.0,
    "Fine-Tuning": 1.0,
    "Data Science": 2.0,
    "Systems": 2.0,
}

VERTICAL_IMPORTANCE = {
    "AI": 1.0,
    "HPC": 1.0,
    "Data Science": 1.0,
    "Systems": 1.0,
    "Developers": 1.0,
    "Robotics": 1.0,
}


def _sanitize_image_output_name(name: str) -> str:
    """Convert a filename into a filesystem-safe output name."""
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "-", name)
    sanitized = re.sub(r"-{2,}", "-", sanitized).strip("-")
    return sanitized


def _build_canonical_og_image_name(
    blogs_directory: str, blog_filepath: str, thumbnail_value: str
) -> str:
    """Build canonical _images filename for OpenGraph image metadata."""
    thumbnail_normalized = str(thumbnail_value or "").strip().replace("\\", "/")
    if not thumbnail_normalized:
        return "generic.webp"

    if thumbnail_normalized.startswith(("http://", "https://")):
        external_tail = thumbnail_normalized.split("?", 1)[0].split("#", 1)[0]
        external_basename = os.path.basename(external_tail)
        if not external_basename:
            return "generic.webp"
        root, _ = os.path.splitext(_sanitize_image_output_name(external_basename))
        return f"{root}.webp"

    while thumbnail_normalized.startswith("./"):
        thumbnail_normalized = thumbnail_normalized[2:]

    blog_directory = os.path.dirname(blog_filepath)
    thumbnail_basename = os.path.basename(thumbnail_normalized)
    source_candidates = [
        os.path.join(blogs_directory, thumbnail_normalized),
        os.path.join(blog_directory, thumbnail_normalized),
        os.path.join(blog_directory, "images", thumbnail_basename),
        os.path.join(blogs_directory, "images", thumbnail_basename),
    ]

    source_path = next((path for path in source_candidates if os.path.exists(path)), None)
    if source_path:
        relative_key = os.path.relpath(source_path, blogs_directory).replace("\\", "/")
    else:
        relative_blog_path = os.path.relpath(blog_filepath, blogs_directory).replace(
            "\\", "/"
        )
        relative_blog_dir = os.path.dirname(relative_blog_path)
        if "/" in thumbnail_normalized:
            relative_key = thumbnail_normalized
        else:
            relative_key = f"{relative_blog_dir}/images/{thumbnail_basename}"

    if relative_key.startswith("_images/"):
        relative_key = relative_key[len("_images/") :]

    relative_parts = [
        part for part in relative_key.split("/") if part and part not in {".", ".."}
    ]
    if not relative_parts:
        relative_parts = [thumbnail_basename]

    candidate = _sanitize_image_output_name("-".join(relative_parts))
    root, _ = os.path.splitext(candidate)
    return f"{root}.webp"


# Pre-compiled regular expressions
METADATA_REGEX_PATTERN = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
BLOGPOST_REGEX_PATTERN = re.compile(r"blogpost:\s*true", re.IGNORECASE)
TITLE_REGEX_PATTERN = re.compile(r"^# (.+)$", re.MULTILINE)

# Date parsing formats
DATE_FORMATS = [
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%d-%B-%Y",
    "%d-%b-%Y",
    "%d %B %Y",
    "%d %b %Y",
    "%d %B, %Y",
    "%d %b, %Y",
    "%B %d, %Y",
    "%b %d, %Y",
    "%B %d %Y",
    "%b %d %Y",
]

# Special cases for handling commas in metadata
WEIRD_INPUTS_AMD_BLOG_APPLICATIONS = ["Design, Simulation & Modeling"]
WEIRD_INPUTS_TECHNICAL_BLOG_TYPE = ["Tools, Features, and Optimizations"]


def classify_blog_tags(
    blog_tags: Any, metadata_log_file_handle: Optional[Any] = None
) -> Dict[str, Any]:
    """Classify blog tags into market verticals."""

    # Initialize vertical classification data structures
    vertical_scores = defaultdict(float)
    vertical_counts = {
        "AI": 0,
        "HPC": 0,
        "Data Science": 0,
        "Systems": 0,
        "Developers": 0,
    }
    primary_matches = defaultdict(list)
    secondary_matches = defaultdict(list)

    # Normalize input tags to consistent list format
    if isinstance(blog_tags, str):
        tags = [tag.strip() for tag in blog_tags.split(",") if tag.strip()]
    elif isinstance(blog_tags, list):
        tags = blog_tags
    else:
        if metadata_log_file_handle:
            safe_log_write(
                metadata_log_file_handle,
                f"ERROR: Invalid blog_tags format: {type(blog_tags)}\n",
            )
        return {}

    if metadata_log_file_handle:
        safe_log_write(metadata_log_file_handle, f"Blog Tags: {tags}\n")
        safe_log_write(
            metadata_log_file_handle,
            f"Checking Blog Tags: {', '.join(tags)} for market verticals.\n",
        )

    # Process each tag for vertical classification
    for tag in tags:
        normalized_tag = tag.strip()
        tag_matched = False

        if metadata_log_file_handle:
            safe_log_write(
                metadata_log_file_handle, f"Checking tag: {normalized_tag}\n"
            )

        if normalized_tag not in TAG_WEIGHTS:
            if metadata_log_file_handle:
                safe_log_write(
                    metadata_log_file_handle,
                    f"WARNING: Tag '{normalized_tag}' not found in tag weights.\n",
                )
            continue

        # Check for primary tag matches first
        for vertical, primary_tag_list in PRIMARY_TAGS.items():
            if normalized_tag in primary_tag_list:
                weight = TAG_WEIGHTS.get(normalized_tag, 1.0)
                vertical_weight = VERTICAL_IMPORTANCE[vertical]
                score = weight * vertical_weight

                vertical_scores[vertical] += score
                primary_matches[vertical].append(normalized_tag)
                tag_matched = True

                if metadata_log_file_handle:
                    safe_log_write(
                        metadata_log_file_handle,
                        f"Tag: {tag} is a PRIMARY tag for vertical: {vertical} with score: {score:.2f}\n",
                    )
                break

        # Check for secondary tag matches when no primary match found
        if not tag_matched:
            for vertical, secondary_tag_list in SECONDARY_TAGS.items():
                if normalized_tag in secondary_tag_list:
                    weight = TAG_WEIGHTS.get(normalized_tag, 1.0)
                    vertical_weight = VERTICAL_IMPORTANCE[vertical]
                    score = weight * vertical_weight * 1.0

                    vertical_scores[vertical] += score
                    secondary_matches[vertical].append(normalized_tag)
                    tag_matched = True

                    if metadata_log_file_handle:
                        safe_log_write(
                            metadata_log_file_handle,
                            f"Tag: {tag} is a SECONDARY tag for vertical: {vertical} with score: {score:.2f}\n",
                        )
                    break

    # Apply bonus scoring for multiple tag matches within verticals
    for vertical in vertical_scores.keys():
        primary_count = len(primary_matches[vertical])
        secondary_count = len(secondary_matches[vertical])

        # Apply bonus for multiple primary tags within the same vertical
        if primary_count > 1:
            primary_bonus = 0.3 * (primary_count - 1)
            vertical_scores[vertical] *= 1 + primary_bonus

            if metadata_log_file_handle:
                safe_log_write(
                    metadata_log_file_handle,
                    f"Applied primary tag bonus of {primary_bonus:.2f} to {vertical}\n",
                )

        # Apply bonus for secondary tags within the same vertical
        if secondary_count > 0:
            secondary_bonus = 0.1 * secondary_count
            vertical_scores[vertical] *= 1 + secondary_bonus

            if metadata_log_file_handle:
                safe_log_write(
                    metadata_log_file_handle,
                    f"Applied secondary tag bonus of {secondary_bonus:.2f} to {vertical}\n",
                )

    # Determine final vertical classifications based on scoring thresholds
    top_verticals = sorted(
        [(vertical, score) for vertical, score in vertical_scores.items() if score > 0],
        key=lambda x: x[1],
        reverse=True,
    )

    min_score_threshold = 1.0
    selected_verticals = [
        (vertical, score)
        for vertical, score in top_verticals
        if score >= min_score_threshold
    ]

    max_verticals = 99
    if len(selected_verticals) > max_verticals:
        selected_verticals = selected_verticals[:max_verticals]

    # Determine primary market vertical and apply relative threshold filtering
    if selected_verticals:
        top_vertical, top_score = selected_verticals[0]
        relative_threshold = 0.35

        # Initialize all vertical counts to zero
        for vertical_key in vertical_counts:
            vertical_counts[vertical_key] = 0

        # Apply relative threshold filtering to determine final vertical assignments
        for vertical, score in selected_verticals:
            if score >= top_score * relative_threshold:
                vertical_counts[vertical] = score

        # Ensure the top vertical is always included
        vertical_counts[top_vertical] = top_score
        market_vertical = top_vertical

        if metadata_log_file_handle:
            safe_log_write(
                metadata_log_file_handle,
                f"Primary market vertical: {market_vertical} (score: {top_score:.2f})\n",
            )

            # Log additional verticals within threshold
            additional_verticals = [
                (vertical, score)
                for vertical, score in vertical_counts.items()
                if score > 0 and vertical != market_vertical
            ]
            if additional_verticals:
                additional_str = ", ".join(
                    [
                        f"{vertical} (score: {score:.2f})"
                        for vertical, score in additional_verticals
                    ]
                )
                safe_log_write(
                    metadata_log_file_handle,
                    f"Additional verticals within threshold: {additional_str}\n",
                )
    else:
        market_vertical = None
        if metadata_log_file_handle:
            safe_log_write(
                metadata_log_file_handle, "No verticals matched this blog.\n"
            )

    if metadata_log_file_handle:
        safe_log_write(
            metadata_log_file_handle, f"Final vertical counts: {vertical_counts}\n"
        )

    # Prepare comprehensive classification results
    classification_details = {
        "vertical_counts": vertical_counts,
        "scores": {
            vertical: score for vertical, score in vertical_scores.items() if score > 0
        },
        "primary_matches": dict(primary_matches),
        "secondary_matches": dict(secondary_matches),
        "selected_verticals": selected_verticals,
        "market_vertical": market_vertical,
    }

    return classification_details


def metadata_generator(rocm_blogs_instance: ROCmBlogs) -> None:
    """Generate metadata for ROCm blogs."""

    generation_start_time = datetime.now()
    log_message(
        "info",
        f"Starting metadata generation at {generation_start_time.isoformat()}",
        "general",
        "metadata",
    )
    log_message("info", "=" * 80, "general", "metadata")
    log_message(
        "info",
        "Generating metadata for ROCm blogs with Open Graph protocol support...",
        "general",
        "metadata",
    )
    log_message("info", "-" * 80, "general", "metadata")

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
        "vertical": {market_vertical}
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

    # Get blogs list early so it's accessible throughout the function
    blogs = rocm_blogs_instance.blogs.get_blogs()

    # Create universal log file handle
    metadata_log_filepath, metadata_log_file_handle = create_step_log_file(
        "metadata_generation"
    )

    if metadata_log_filepath:
        log_message(
            "info",
            f"Detailed logs will be written to: {metadata_log_filepath}",
            "general",
            "metadata",
        )

    try:
        if metadata_log_file_handle:
            safe_log_write(
                metadata_log_file_handle,
                f"ROCm Blogs Metadata Generation Log - {generation_start_time.isoformat()}\n",
            )
            safe_log_write(metadata_log_file_handle, "=" * 80 + "\n\n")

        for current_blog_index, blog in enumerate(blogs):
            current_blog_start_time = datetime.now()
            blog_filepath = blog.file_path
            current_blog_path = Path(blog_filepath)
            blog_identifier = f"Blog {current_blog_index + 1}/{len(blogs)}"

            try:
                log_message(
                    "info",
                    "Processing {blog_identifier}: {current_blog_path.name}",
                    "general",
                    "metadata",
                )
                safe_log_write(
                    metadata_log_file_handle,
                    f"\n{'-' * 40}\nProcessing: {blog_filepath}\n{'-' * 40}\n",
                )

                if not current_blog_path.exists():
                    error_message = f"Blog file does not exist: {blog_filepath}"
                    log_message("error", error_message, "general", "metadata")
                    safe_log_write(
                        metadata_log_file_handle, f"ERROR: {error_message}\n"
                    )
                    all_error_details.append(
                        {"blog": blog_filepath, "error": error_message}
                    )
                    total_blogs_error += 1
                    continue

                if not os.access(blog_filepath, os.R_OK):
                    error_message = f"Blog file is not readable: {blog_filepath}"
                    log_message("error", error_message, "general", "metadata")
                    safe_log_write(
                        metadata_log_file_handle, f"ERROR: {error_message}\n"
                    )
                    all_error_details.append(
                        {"blog": blog_filepath, "error": error_message}
                    )
                    total_blogs_error += 1
                    continue

                with open(
                    blog_filepath, "r", encoding="utf-8", errors="replace"
                ) as blog_file_handle:
                    blog_file_content = blog_file_handle.read()

                metadata_match = METADATA_REGEX_PATTERN.search(blog_file_content)

                if not metadata_match:
                    log_message(
                        "info",
                        "Skipping {blog_identifier}: No metadata section found, not a blog post",
                        "general",
                        "metadata",
                    )
                    safe_log_write(
                        metadata_log_file_handle,
                        f"INFO: No metadata section found, skipping as not a blog post\n",
                    )
                    total_non_blog_files += 1
                    total_blogs_skipped += 1
                    continue

                metadata_content_extracted = metadata_match.group(1)
                if not BLOGPOST_REGEX_PATTERN.search(metadata_content_extracted):
                    log_message(
                        "info",
                        f"Skipping {blog_identifier}: Not marked as a blog post (blogpost: true not found)",
                        "general",
                        "metadata",
                    )
                    safe_log_write(
                        metadata_log_file_handle,
                        f"INFO: Not marked as a blog post in metadata, skipping\n",
                    )
                    total_non_blog_files += 1
                    total_blogs_skipped += 1
                    continue

                try:
                    extracted_metadata = rocm_blogs_instance.extract_metadata_from_file(
                        blog_filepath
                    )
                    safe_log_write(
                        metadata_log_file_handle,
                        f"Extracted metadata: {json.dumps(extracted_metadata, indent=2)}\n",
                    )
                except Exception as metadata_extraction_exception:
                    error_message = f"Failed to extract metadata from {blog_filepath}: {metadata_extraction_exception}"
                    log_message("error", error_message, "general", "metadata")
                    log_message(
                        "debug",
                        f"Traceback: {traceback.format_exc()}",
                        "general",
                        "metadata",
                    )
                    safe_log_write(
                        metadata_log_file_handle, f"ERROR: {error_message}\n"
                    )
                    safe_log_write(
                        metadata_log_file_handle,
                        f"Traceback: {traceback.format_exc()}\n",
                    )
                    all_error_details.append(
                        {"blog": blog_filepath, "error": error_message}
                    )
                    total_blogs_error += 1
                    continue

                if not extracted_metadata:
                    log_message(
                        "warning",
                        f"No metadata found for blog: {blog_filepath}",
                        "general",
                        "metadata",
                    )
                    safe_log_write(
                        metadata_log_file_handle,
                        f"WARNING: No metadata found for blog\n",
                    )
                    total_blogs_warning += 1
                    total_blogs_skipped += 1
                    continue

                if not extracted_metadata.get("blogpost"):
                    log_message(
                        "info",
                        "Skipping {blog_identifier}: Not marked as a blog post in extracted metadata",
                        "general",
                        "metadata",
                    )
                    safe_log_write(
                        metadata_log_file_handle,
                        f"INFO: Not marked as a blog post in extracted metadata, skipping\n",
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
                        log_message(
                            "warning",
                            f"No description found for blog: {blog_filepath}",
                            "general",
                            "metadata",
                        )
                        safe_log_write(
                            metadata_log_file_handle, f"WARNING: No description found\n"
                        )
                        total_blogs_warning += 1
                        blog_description = "ROCm Blog post"
                    else:
                        log_message(
                            "debug",
                            f"Description: {blog_description}",
                            "general",
                            "metadata",
                        )
                        safe_log_write(
                            metadata_log_file_handle,
                            f"Description: {blog_description}\n",
                        )

                    blog_keywords = html_metadata.get("keywords", "")
                    if not blog_keywords:
                        log_message(
                            "debug",
                            f"No keywords found for blog: {blog_filepath}",
                            "general",
                            "metadata",
                        )
                        safe_log_write(
                            metadata_log_file_handle, f"INFO: No keywords found\n"
                        )
                    else:
                        log_message(
                            "debug", f"Keywords: {blog_keywords}", "general", "metadata"
                        )
                        safe_log_write(
                            metadata_log_file_handle, f"Keywords: {blog_keywords}\n"
                        )

                    title_regex_pattern = re.compile(r"^# (.+)$", re.MULTILINE)
                    title_match = title_regex_pattern.search(blog_file_content)
                    if title_match:
                        extracted_title = title_match.group(1)
                        extracted_title = extracted_title.replace('"', "'")
                        extracted_metadata["blog_title"] = extracted_title
                        log_message(
                            "debug",
                            f"Extracted title from markdown: {extracted_title}",
                            "general",
                            "metadata",
                        )
                        safe_log_write(
                            metadata_log_file_handle,
                            f"Extracted title: {extracted_title}\n",
                        )
                    else:
                        fallback_description = blog_description.replace("'", '"')
                        extracted_metadata["blog_title"] = fallback_description
                        log_message(
                            "warning",
                            f"No title found in markdown for {blog_filepath}, using description as title",
                            "general",
                            "metadata",
                        )
                        safe_log_write(
                            metadata_log_file_handle,
                            f"WARNING: No title found in markdown, using description as title: {fallback_description[:30]}...\n",
                        )
                        total_blogs_warning += 1
                except Exception as metadata_field_exception:
                    error_message = f"Error extracting metadata from {blog_filepath}: {metadata_field_exception}"
                    log_message("error", error_message, "general", "metadata")
                    log_message(
                        "debug",
                        f"Traceback: {traceback.format_exc()}",
                        "general",
                        "metadata",
                    )
                    safe_log_write(
                        metadata_log_file_handle, f"ERROR: {error_message}\n"
                    )
                    safe_log_write(
                        metadata_log_file_handle,
                        f"Traceback: {traceback.format_exc()}\n",
                    )
                    all_error_details.append(
                        {"blog": blog_filepath, "error": error_message}
                    )
                    total_blogs_error += 1
                    continue

                try:
                    if "author" not in extracted_metadata:
                        extracted_metadata["author"] = "No author"
                        log_message(
                            "warning",
                            f"No author found for blog: {blog_filepath}, using default",
                            "general",
                            "metadata",
                        )
                        safe_log_write(
                            metadata_log_file_handle,
                            f"WARNING: No author found, using default: {extracted_metadata['author']}\n",
                        )
                        total_blogs_warning += 1
                    else:
                        extracted_metadata["author"] = extracted_metadata["author"]
                        log_message(
                            "debug",
                            f"Author: {extracted_metadata['author']}",
                            "general",
                            "metadata",
                        )
                        release_author = ";".join(
                            extracted_metadata.get("author", "").split(",")
                        )
                        safe_log_write(
                            metadata_log_file_handle,
                            f"Author: {extracted_metadata['author']}\n",
                        )

                    if not extracted_metadata.get("thumbnail"):
                        log_message(
                            "info",
                            "Blog: {blog_filepath} does not have a thumbnail specified: {extracted_metadata}",
                            "general",
                            "metadata",
                        )
                        extracted_thumbnail = "generic.webp"
                        og_image_extracted = "generic.webp"
                        log_message(
                            "debug",
                            f"No thumbnail specified for blog: {blog_filepath}",
                            "general",
                            "metadata",
                        )
                        safe_log_write(
                            metadata_log_file_handle, f"INFO: No thumbnail specified\n"
                        )
                    else:
                        log_message(
                            "debug",
                            f"Thumbnail: {extracted_metadata['thumbnail']}",
                            "general",
                            "metadata",
                        )
                        safe_log_write(
                            metadata_log_file_handle,
                            f"Thumbnail: {extracted_metadata['thumbnail']}\n",
                        )

                        # Store original thumbnail for logging and diagnostics.
                        extracted_og_image = extracted_metadata["thumbnail"]
                        extracted_thumbnail = extracted_metadata["thumbnail"]

                        # Build canonical OpenGraph image filename that matches
                        # generated _images naming (path-aware, always .webp).
                        og_image_extracted = _build_canonical_og_image_name(
                            rocm_blogs_instance.blogs_directory,
                            blog_filepath,
                            extracted_metadata["thumbnail"],
                        )

                        safe_log_write(
                            metadata_log_file_handle,
                            f"Thumbnail: {og_image_extracted}\n",
                        )
                        safe_log_write(
                            metadata_log_file_handle,
                            f"OG Image: {extracted_og_image}\n",
                        )

                    if "date" not in extracted_metadata:
                        extracted_metadata["date"] = datetime.now().strftime("%d %B %Y")
                        log_message(
                            "warning",
                            f"No date found for blog: {blog_filepath}, using current date",
                            "general",
                            "metadata",
                        )
                        safe_log_write(
                            metadata_log_file_handle,
                            f"WARNING: No date found, using current date: {extracted_metadata['date']}\n",
                        )
                        total_blogs_warning += 1
                    else:
                        log_message(
                            "debug",
                            f"Date: {extracted_metadata['date']}",
                            "general",
                            "metadata",
                        )
                        safe_log_write(
                            metadata_log_file_handle,
                            f"Date: {extracted_metadata['date']}\n",
                        )

                    safe_log_write(metadata_log_file_handle, f"-" * 40 + "\n")
                    safe_log_write(
                        metadata_log_file_handle, f"Beginning Check for tags\n"
                    )
                    safe_log_write(metadata_log_file_handle, f"-" * 40 + "\n")

                    if "tags" not in extracted_metadata:
                        extracted_metadata["tags"] = ""
                        log_message(
                            "debug",
                            f"No tags specified for blog: {blog_filepath}",
                            "general",
                            "metadata",
                        )
                        safe_log_write(
                            metadata_log_file_handle, f"ERROR: No tags specified\n"
                        )
                    else:
                        log_message(
                            "debug",
                            f"Blog Tags Specified: {extracted_metadata['tags']}",
                            "general",
                            "metadata",
                        )
                        safe_log_write(
                            metadata_log_file_handle,
                            f"INFO: Blog Tags Specified: {extracted_metadata['tags']}\n",
                        )
                        blog_tags = extracted_metadata["tags"]

                    safe_log_write(metadata_log_file_handle, f"-" * 40 + "\n")
                    safe_log_write(
                        metadata_log_file_handle,
                        f"Beginning Check for market vertical\n",
                    )
                    safe_log_write(metadata_log_file_handle, f"-" * 40 + "\n")

                    if "tags" in extracted_metadata and "vertical" not in html_metadata:

                        safe_log_write(
                            metadata_log_file_handle,
                            f"INFO: No vertical specified, classifying blog tags\n",
                        )

                        vertical_counts = classify_blog_tags(
                            blog_tags, metadata_log_file_handle
                        )

                        safe_log_write(
                            metadata_log_file_handle,
                            f"Vertical Count: {vertical_counts.get('vertical_counts')} for blog: {blog_filepath}\n",
                        )

                        # Get the primary market vertical directly from the
                        # function return value
                        vertical_dict = vertical_counts.get("market_vertical")

                        # If market_vertical is None, try to find the highest
                        # scored vertical
                        if vertical_dict is not None:
                            vertical_scores = vertical_counts.get("vertical_counts", {})

                            non_zero_verticals = {
                                k: v for k, v in vertical_scores.items() if v > 0
                            }

                            if non_zero_verticals:
                                market_vertical = ", ".join(non_zero_verticals.keys())
                            else:
                                market_vertical = "Unknown"
                        else:
                            market_vertical = "Unknown"

                        market_vertical = f'"{market_vertical}"'

                        safe_log_write(
                            metadata_log_file_handle,
                            f"Market Vertical: {market_vertical}\n",
                        )
                        safe_log_write(
                            metadata_log_file_handle,
                            f"Tags: {extracted_metadata['tags']}\n",
                        )

                    else:
                        safe_log_write(
                            metadata_log_file_handle,
                            f"Market Vertical found in metadata: {html_metadata['vertical']}\n",
                        )
                        market_vertical = html_metadata["vertical"]
                        market_vertical = f'"{market_vertical}"'
                        log_message(
                            "debug",
                            f"Market Vertical: {market_vertical}",
                            "general",
                            "metadata",
                        )
                        safe_log_write(
                            metadata_log_file_handle,
                            f"Market Vertical: {market_vertical}\n",
                        )

                    safe_log_write(
                        metadata_log_file_handle, f"Blog Tags: {blog_tags}\n"
                    )
                    if not blog_tags and not market_vertical:
                        log_message(
                            "debug",
                            f"No tags found for blog: {blog_filepath}",
                            "general",
                            "metadata",
                        )
                        safe_log_write(
                            metadata_log_file_handle, f"INFO: No tags found\n"
                        )
                        blog_tags = ""
                        market_vertical = "Unknown"

                    if "category" not in extracted_metadata:
                        extracted_metadata["category"] = "ROCm Blog"
                        log_message(
                            "debug",
                            f"No category specified for blog: {blog_filepath}, using default",
                            "general",
                            "metadata",
                        )
                        safe_log_write(
                            metadata_log_file_handle,
                            f"INFO: No category specified, using default: 'ROCm Blog'\n",
                        )
                    else:
                        log_message(
                            "debug",
                            f"Category: {extracted_metadata['category']}",
                            "general",
                            "metadata",
                        )
                        safe_log_write(
                            metadata_log_file_handle,
                            f"Category: {extracted_metadata['category']}\n",
                        )

                    safe_log_write(
                        metadata_log_file_handle,
                        f"HTML Metadata: {json.dumps(html_metadata, indent=2)}\n",
                    )

                    safe_log_write(
                        metadata_log_file_handle,
                        f"Extracted Metadata: {json.dumps(extracted_metadata, indent=2)}\n",
                    )

                    # Extract AMD-specific metadata fields with default values if missing
                    amd_technical_blog_type = html_metadata.get(
                        "amd_technical_blog_type", "Applications and Models"
                    )

                    amd_blog_hardware_platforms = html_metadata.get(
                        "amd_blog_hardware_platforms", "Instinct GPUs"
                    )

                    amd_blog_deployment_tools = html_metadata.get(
                        "amd_blog_development_tools", "ROCm Software"
                    )

                    amd_applications = html_metadata.get(
                        "amd_blog_applications",
                        html_metadata.get(
                            "amd_applications",
                            "AI & Intelligent Systems; Industry Applications & Use Cases",
                        ),
                    )

                    amd_blog_category_topic = html_metadata.get(
                        "amd_blog_topic_categories",
                        "AI & Intelligent Systems; Industry Applications & Use Cases",
                    )

                    # Handle special cases with commas using imported constants
                    if any(
                        weird_input in amd_applications
                        for weird_input in WEIRD_INPUTS_AMD_BLOG_APPLICATIONS
                    ):
                        for weird_input in WEIRD_INPUTS_AMD_BLOG_APPLICATIONS:
                            if weird_input in amd_applications:
                                amd_applications = amd_applications.replace(
                                    weird_input, weird_input.replace(",", "/%2c/")
                                )
                                amd_applications = ";".join(amd_applications.split(","))
                                amd_applications = amd_applications.replace(
                                    "/%2c/", ","
                                )
                                safe_log_write(
                                    metadata_log_file_handle,
                                    f"AMD Blog Applications: {amd_applications}\n",
                                )
                                break
                    else:
                        amd_applications = ";".join(amd_applications.split(","))
                        safe_log_write(
                            metadata_log_file_handle,
                            f"AMD Blog Applications: {amd_applications}\n",
                        )

                    if any(
                        weird_input in amd_technical_blog_type
                        for weird_input in WEIRD_INPUTS_TECHNICAL_BLOG_TYPE
                    ):
                        for weird_input in WEIRD_INPUTS_TECHNICAL_BLOG_TYPE:
                            if weird_input in amd_technical_blog_type:
                                amd_technical_blog_type = (
                                    amd_technical_blog_type.replace(
                                        weird_input, weird_input.replace(",", "/%2c/")
                                    )
                                )
                                amd_technical_blog_type = ";".join(
                                    amd_technical_blog_type.split(",")
                                )
                                amd_technical_blog_type = (
                                    amd_technical_blog_type.replace("/%2c/", ",")
                                )
                                safe_log_write(
                                    metadata_log_file_handle,
                                    f"AMD Technical Blog Type: {amd_technical_blog_type}\n",
                                )
                                break

                    amd_blog_hardware_platforms = ";".join(
                        amd_blog_hardware_platforms.split(",")
                    )
                    safe_log_write(
                        metadata_log_file_handle,
                        f"AMD Blog Hardware Platforms: {amd_blog_hardware_platforms}\n",
                    )

                    amd_blog_deployment_tools = ";".join(
                        amd_blog_deployment_tools.split(",")
                    )
                    safe_log_write(
                        metadata_log_file_handle,
                        f"AMD Blog Deployment Tools: {amd_blog_deployment_tools}\n",
                    )

                    amd_blog_category_topic = ";".join(
                        amd_blog_category_topic.split(",")
                    )
                    safe_log_write(
                        metadata_log_file_handle,
                        f"AMD Blog Category Topic: {amd_blog_category_topic}\n",
                    )

                    release_author = ";".join(release_author.split(","))
                    safe_log_write(
                        metadata_log_file_handle, f"Release Author: {release_author}\n"
                    )

                except KeyError as key_error:
                    error_message = f"KeyError: {key_error} in {blog_filepath}"
                    log_message("error", error_message, "general", "metadata")
                    log_message(
                        "debug",
                        f"Traceback: {traceback.format_exc()}",
                        "general",
                        "metadata",
                    )
                    safe_log_write(
                        metadata_log_file_handle, f"ERROR: {error_message}\n"
                    )
                    safe_log_write(
                        metadata_log_file_handle,
                        f"Traceback: {traceback.format_exc()}\n",
                    )
                    all_error_details.append(
                        {"blog": blog_filepath, "error": error_message}
                    )
                    total_blogs_error += 1
                    continue

                except Exception as default_field_exception:
                    error_message = f"Error setting default values for {blog_filepath}: {default_field_exception}"
                    log_message("error", error_message, "general", "metadata")
                    log_message(
                        "debug",
                        f"Traceback: {traceback.format_exc()}",
                        "general",
                        "metadata",
                    )
                    safe_log_write(
                        metadata_log_file_handle, f"ERROR: {error_message}\n"
                    )
                    safe_log_write(
                        metadata_log_file_handle,
                        f"Traceback: {traceback.format_exc()}\n",
                    )
                    all_error_details.append(
                        {"blog": blog_filepath, "error": error_message}
                    )
                    total_blogs_error += 1
                    continue

                if "Sept" in extracted_metadata["date"]:
                    extracted_metadata["date"] = extracted_metadata["date"].replace(
                        "Sept", "Sep"
                    )
                    log_message(
                        "debug",
                        f"Normalized date format: {extracted_metadata['date']}",
                        "general",
                        "metadata",
                    )
                    safe_log_write(
                        metadata_log_file_handle,
                        f"INFO: Normalized date format: {extracted_metadata['date']}\n",
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

                        # Use imported date formats for consistency
                        parsed_date = None
                        for date_format in DATE_FORMATS:
                            try:
                                parsed_date = datetime.strptime(blog_date, date_format)
                                break
                            except ValueError:
                                continue

                        if not parsed_date:
                            parsed_date = datetime.now()
                            log_message(
                                "warning",
                                f"Could not parse date '{blog_date}' for {blog_filepath}, using current date",
                                "general",
                                "metadata",
                            )
                            safe_log_write(
                                metadata_log_file_handle,
                                f"WARNING: Could not parse date '{blog_date}', using current date\n",
                            )
                            total_blogs_warning += 1

                        # Extract day, month, year components
                        day = parsed_date.day
                        month = parsed_date.month
                        year = parsed_date.year

                        day_of_week = calculate_day_of_week(
                            year, parsed_date.month, day
                        )
                        amd_blog_releasedate = f"{year}/{month}/{day}"

                        log_message(
                            "debug",
                            f"Generated release date: {amd_blog_releasedate}",
                            "general",
                            "metadata",
                        )
                        safe_log_write(
                            metadata_log_file_handle,
                            f"Generated release date: {amd_blog_releasedate}\n",
                        )

                    log_message(
                        "debug",
                        f"Generated AMD Release Date: {amd_blog_releasedate}",
                        "general",
                        "metadata",
                    )
                    safe_log_write(
                        metadata_log_file_handle,
                        f"Generated AMD Release Date: {amd_blog_releasedate}\n",
                    )

                    try:
                        relative_blog_path = os.path.relpath(
                            blog_filepath, rocm_blogs_instance.blogs_directory
                        )
                        blog_directory = os.path.dirname(relative_blog_path)
                        # Convert Windows backslashes to forward slashes for URLs
                        blog_directory = blog_directory.replace("\\", "/")
                        generated_blog_url = f"/{blog_directory}/README.html"
                        log_message(
                            "debug",
                            f"Generated blog URL: {generated_blog_url}",
                            "general",
                            "metadata",
                        )
                        safe_log_write(
                            metadata_log_file_handle,
                            f"Generated blog URL: {generated_blog_url}\n",
                        )
                    except Exception as blog_url_exception:
                        error_message = f"Error generating blog URL for {blog_filepath}: {blog_url_exception}"
                        log_message("error", error_message, "general", "metadata")
                        log_message(
                            "debug",
                            f"Traceback: {traceback.format_exc()}",
                            "general",
                            "metadata",
                        )
                        safe_log_write(
                            metadata_log_file_handle, f"ERROR: {error_message}\n"
                        )
                        safe_log_write(
                            metadata_log_file_handle,
                            f"Traceback: {traceback.format_exc()}\n",
                        )
                        generated_blog_url = "/blogs"
                        log_message(
                            "warning",
                            f"Using fallback blog URL: {generated_blog_url}",
                            "general",
                            "metadata",
                        )
                        safe_log_write(
                            metadata_log_file_handle,
                            f"WARNING: Using fallback blog URL: {generated_blog_url}\n",
                        )
                        total_blogs_warning += 1
                except Exception as og_metadata_exception:
                    error_message = f"Error generating Open Graph metadata for {blog_filepath}: {og_metadata_exception}"
                    log_message("error", error_message, "general", "metadata")
                    log_message(
                        "debug",
                        f"Traceback: {traceback.format_exc()}",
                        "general",
                        "metadata",
                    )
                    safe_log_write(
                        metadata_log_file_handle, f"ERROR: {error_message}\n"
                    )
                    safe_log_write(
                        metadata_log_file_handle,
                        f"Traceback: {traceback.format_exc()}\n",
                    )
                    all_error_details.append(
                        {"blog": blog_filepath, "error": error_message}
                    )
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
                        market_vertical=market_vertical,
                    )
                    log_message(
                        "debug",
                        f"Generated metadata content for {blog_filepath}",
                        "general",
                        "metadata",
                    )
                    safe_log_write(
                        metadata_log_file_handle,
                        f"Generated metadata content: {formatted_metadata_content}\n",
                    )
                    safe_log_write(
                        metadata_log_file_handle,
                        f"Successfully generated metadata content\n",
                    )
                except Exception as format_exception:
                    error_message = f"Error formatting metadata content for {blog_filepath}: {format_exception}"
                    log_message("error", error_message, "general", "metadata")
                    log_message(
                        "debug",
                        f"Traceback: {traceback.format_exc()}",
                        "general",
                        "metadata",
                    )
                    safe_log_write(
                        metadata_log_file_handle, f"ERROR: {error_message}\n"
                    )
                    safe_log_write(
                        metadata_log_file_handle,
                        f"Traceback: {traceback.format_exc()}\n",
                    )
                    all_error_details.append(
                        {"blog": blog_filepath, "error": error_message}
                    )
                    total_blogs_error += 1
                    continue

                try:
                    metadata_regex_pattern = re.compile(
                        r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL
                    )
                    match = metadata_regex_pattern.search(blog_file_content)
                    if match:
                        # Use string slicing instead of regex substitution to avoid escape sequence issues
                        blog_file_content = (
                            blog_file_content[: match.start()]
                            + formatted_metadata_content
                            + blog_file_content[match.end() :]
                        )
                        log_message(
                            "debug",
                            f"Replaced existing metadata in {blog_filepath}",
                            "general",
                            "metadata",
                        )
                        safe_log_write(
                            metadata_log_file_handle, f"Replaced existing metadata\n"
                        )
                    else:
                        blog_file_content = (
                            formatted_metadata_content + blog_file_content
                        )
                        log_message(
                            "debug",
                            f"Added new metadata to {blog_filepath}",
                            "general",
                            "metadata",
                        )
                        safe_log_write(
                            metadata_log_file_handle, f"Added new metadata\n"
                        )
                    blog_file_content = blog_file_content.strip() + "\n"
                    with open(
                        blog_filepath, "w", encoding="utf-8", errors="replace"
                    ) as blog_file_handle_write:
                        blog_file_handle_write.write(blog_file_content)
                    log_message(
                        "info",
                        "Metadata successfully added to {blog_filepath}",
                        "general",
                        "metadata",
                    )
                    safe_log_write(
                        metadata_log_file_handle,
                        f"Metadata successfully added to file\n",
                    )

                    try:
                        updated_metadata = (
                            rocm_blogs_instance.extract_metadata_from_file(
                                blog_filepath
                            )
                        )
                        safe_log_write(
                            metadata_log_file_handle,
                            f"Re-extracted metadata from updated file: {json.dumps(updated_metadata, indent=2)}\n",
                        )

                        # Use the current blog object directly since we already have it
                        blog_object = blog

                        if blog_object:
                            # Update the blog object's metadata attribute
                            blog_object.metadata = updated_metadata
                            safe_log_write(
                                metadata_log_file_handle,
                                f"Updated blog object metadata attribute\n",
                            )

                            # Update specific attributes that are used by vertical pages
                            if updated_metadata:
                                myst_section = updated_metadata.get("myst", {})
                                html_metadata = myst_section.get("html_meta", {})
                                vertical_str = html_metadata.get("vertical", "")

                                safe_log_write(
                                    metadata_log_file_handle,
                                    f"Raw vertical string from metadata: '{vertical_str}'\n",
                                )

                                if vertical_str:
                                    # Update the blog object's vertical attribute first
                                    blog_object.vertical = vertical_str

                                    if hasattr(
                                        rocm_blogs_instance.blogs, "blogs_verticals"
                                    ):
                                        if isinstance(blog_object.vertical, str):
                                            if (
                                                blog_object.vertical
                                                not in rocm_blogs_instance.blogs.blogs_verticals
                                            ):
                                                rocm_blogs_instance.blogs.blogs_verticals[
                                                    blog_object.vertical
                                                ] = []
                                            if (
                                                blog_object
                                                not in rocm_blogs_instance.blogs.blogs_verticals[
                                                    blog_object.vertical
                                                ]
                                            ):
                                                rocm_blogs_instance.blogs.blogs_verticals[
                                                    blog_object.vertical
                                                ].append(
                                                    blog_object
                                                )
                                        elif isinstance(blog_object.vertical, list):
                                            for vert in blog_object.vertical:
                                                if (
                                                    vert
                                                    not in rocm_blogs_instance.blogs.blogs_verticals
                                                ):
                                                    rocm_blogs_instance.blogs.blogs_verticals[
                                                        vert
                                                    ] = []
                                                if (
                                                    blog_object
                                                    not in rocm_blogs_instance.blogs.blogs_verticals[
                                                        vert
                                                    ]
                                                ):
                                                    rocm_blogs_instance.blogs.blogs_verticals[
                                                        vert
                                                    ].append(
                                                        blog_object
                                                    )

                                    safe_log_write(
                                        metadata_log_file_handle,
                                        f"Updated blogs_verticals collection with blog\n",
                                    )
                                else:
                                    safe_log_write(
                                        metadata_log_file_handle,
                                        f"No vertical found in metadata\n",
                                    )

                                # Update all attributes from metadata (same as Blog.__init__)
                                for key, value in updated_metadata.items():
                                    setattr(blog_object, key, value)

                                # Ensure date is properly parsed if present
                                if "date" in updated_metadata:
                                    blog_object.date = blog_object.parse_date(
                                        updated_metadata["date"]
                                    )

                                safe_log_write(
                                    metadata_log_file_handle,
                                    f"Successfully synchronized in-memory blog object with updated file metadata\n",
                                )

                                # Debug: Print final state of blog object
                                safe_log_write(
                                    metadata_log_file_handle,
                                    f"FINAL BLOG OBJECT STATE:\n",
                                )
                                safe_log_write(
                                    metadata_log_file_handle,
                                    f"  - blog_title: {getattr(blog_object, 'blog_title', 'NOT SET')}\n",
                                )
                                safe_log_write(
                                    metadata_log_file_handle,
                                    f"  - vertical: {getattr(blog_object, 'vertical', 'NOT SET')}\n",
                                )
                                safe_log_write(
                                    metadata_log_file_handle,
                                    f"  - category: {getattr(blog_object, 'category', 'NOT SET')}\n",
                                )
                                safe_log_write(
                                    metadata_log_file_handle,
                                    f"  - metadata.myst.html_meta.vertical: {html_metadata.get('vertical', 'NOT SET')}\n",
                                )

                                log_message(
                                    "info",
                                    f"Successfully updated in-memory blog object for {blog_filepath} with vertical: {getattr(blog_object, 'vertical', 'NOT SET')}",
                                    "general",
                                    "metadata",
                                )
                        else:
                            safe_log_write(
                                metadata_log_file_handle,
                                f"WARNING: Could not find corresponding blog object for {blog_filepath}\n",
                            )
                            log_message(
                                "warning",
                                f"Could not find corresponding blog object for {blog_filepath}",
                                "general",
                                "metadata",
                            )

                    except Exception as sync_error:
                        error_message = f"Error synchronizing in-memory blog object for {blog_filepath}: {sync_error}"
                        log_message("warning", error_message, "general", "metadata")
                        safe_log_write(
                            metadata_log_file_handle, f"WARNING: {error_message}\n"
                        )
                        safe_log_write(
                            metadata_log_file_handle,
                            f"Traceback: {traceback.format_exc()}\n",
                        )
                        # Don't fail the entire process for sync errors, just log them

                    total_blogs_successful += 1
                except Exception as write_exception:
                    error_message = (
                        f"Error writing metadata to {blog_filepath}: {write_exception}"
                    )
                    log_message("error", error_message, "general", "metadata")
                    log_message(
                        "debug",
                        f"Traceback: {traceback.format_exc()}",
                        "general",
                        "metadata",
                    )
                    safe_log_write(
                        metadata_log_file_handle, f"ERROR: {error_message}\n"
                    )
                    safe_log_write(
                        metadata_log_file_handle,
                        f"Traceback: {traceback.format_exc()}\n",
                    )
                    all_error_details.append(
                        {"blog": blog_filepath, "error": error_message}
                    )
                    total_blogs_error += 1
                    continue

                current_blog_end_time = datetime.now()
                current_blog_duration = (
                    current_blog_end_time - current_blog_start_time
                ).total_seconds()
                log_message(
                    "debug",
                    f"Processed {blog_identifier} in {current_blog_duration:.2f} seconds",
                    "general",
                    "metadata",
                )
                safe_log_write(
                    metadata_log_file_handle,
                    f"Processing completed in {current_blog_duration:.2f} seconds\n",
                )

            except Exception as blog_processing_exception:
                error_message = f"Unexpected error processing {blog_filepath}: {blog_processing_exception}"
                log_message("error", error_message, "general", "metadata")
                log_message(
                    "debug",
                    f"Traceback: {traceback.format_exc()}",
                    "general",
                    "metadata",
                )
                safe_log_write(metadata_log_file_handle, f"ERROR: {error_message}\n")
                safe_log_write(
                    metadata_log_file_handle, f"Traceback: {traceback.format_exc()}\n"
                )
                all_error_details.append(
                    {"blog": blog_filepath, "error": error_message}
                )
                total_blogs_error += 1

        if metadata_log_file_handle:
            safe_log_write(metadata_log_file_handle, "\n" + "=" * 80 + "\n")
            safe_log_write(metadata_log_file_handle, "METADATA GENERATION SUMMARY\n")
            safe_log_write(metadata_log_file_handle, "-" * 80 + "\n")
            safe_log_write(
                metadata_log_file_handle,
                f"Total README files found: {len(blogs)}\n",
            )
            safe_log_write(
                metadata_log_file_handle,
                f"Files not marked as blogs (skipped): {total_non_blog_files}\n",
            )
            safe_log_write(
                metadata_log_file_handle,
                f"Total blogs processed: {total_blogs_processed}\n",
            )
            safe_log_write(
                metadata_log_file_handle, f"Successful: {total_blogs_successful}\n"
            )
            safe_log_write(metadata_log_file_handle, f"Errors: {total_blogs_error}\n")
            safe_log_write(
                metadata_log_file_handle, f"Warnings: {total_blogs_warning}\n"
            )
            safe_log_write(
                metadata_log_file_handle, f"Skipped: {total_blogs_skipped}\n"
            )

            if all_error_details:
                safe_log_write(metadata_log_file_handle, "\nERROR DETAILS:\n")
                safe_log_write(metadata_log_file_handle, "-" * 80 + "\n")
                for index, error_detail in enumerate(all_error_details):
                    safe_log_write(
                        metadata_log_file_handle,
                        f"{index+1}. Blog: {error_detail['blog']}\n",
                    )
                    safe_log_write(
                        metadata_log_file_handle,
                        f"   Error: {error_detail['error']}\n\n",
                    )

    except Exception as general_error:
        # Handle any unexpected errors during metadata generation
        log_message(
            "error",
            f"Unexpected error during metadata generation: {general_error}",
            "general",
            "metadata",
        )
        log_message(
            "debug", f"Traceback: {traceback.format_exc()}", "general", "metadata"
        )
        if metadata_log_file_handle:
            safe_log_write(
                metadata_log_file_handle, f"CRITICAL ERROR: {general_error}\n"
            )
            safe_log_write(
                metadata_log_file_handle, f"Traceback: {traceback.format_exc()}\n"
            )
    finally:
        # Close the log file handle if it was opened
        if metadata_log_file_handle:
            safe_log_close(metadata_log_file_handle)

    # Calculate total generation duration outside the try block to ensure it's always available
    end_time = datetime.now()
    total_generation_duration = (end_time - generation_start_time).total_seconds()

    log_message("info", "=" * 80, "general", "metadata")
    log_message("info", "METADATA GENERATION SUMMARY", "general", "metadata")
    log_message("info", "-" * 80, "general", "metadata")
    log_message(
        "info",
        f"Total README files found: {len(blogs)}",
        "general",
        "metadata",
    )
    log_message(
        "info",
        f"Files not marked as blogs (skipped): {total_non_blog_files}",
        "general",
        "metadata",
    )
    log_message(
        "info", f"Total blogs processed: {total_blogs_processed}", "general", "metadata"
    )
    log_message("info", f"Successful: {total_blogs_successful}", "general", "metadata")
    log_message("info", f"Errors: {total_blogs_error}", "general", "metadata")
    log_message("info", f"Warnings: {total_blogs_warning}", "general", "metadata")
    log_message("info", f"Skipped: {total_blogs_skipped}", "general", "metadata")
    log_message(
        "info",
        f"Total time: {total_generation_duration:.2f} seconds",
        "general",
        "metadata",
    )

    if total_blogs_error > 0:
        log_message(
            "error",
            f"Encountered {total_blogs_error} errors during metadata generation",
            "general",
            "metadata",
        )
    else:
        log_message(
            "info",
            "Metadata generation completed successfully with no errors",
            "general",
            "metadata",
        )

    log_message("info", "=" * 80, "general", "metadata")
