"""
Constants for the ROCm Blogs package.

This module contains all constants used throughout the ROCm Blogs package,
including configuration values, regex patterns, and default settings.
"""

import re

# Reading speed constants
AVERAGE_READING_SPEED_WPM = 245

# Regex patterns
SPECIAL_CHARS_PATTERN = re.compile(r"[!@#$%^&*?/|]")
WHITESPACE_PATTERN_FOR_SLUGS = re.compile(r"\s+")

# Markdown patterns for word counting
MARKDOWN_PATTERNS = {
    'yaml_front_matter': re.compile(r"^---\s*\n.*?\n---\s*\n", re.DOTALL),
    'fenced_code_blocks': re.compile(r"```[\s\S]*?```"),
    'indented_code_blocks': re.compile(r"(?m)^( {4}|\t).*$"),
    'html_tags': re.compile(r"<[^>]*>"),
    'urls': re.compile(r"https?://\S+"),
    'image_references': re.compile(r"!\[[^\]]*\]\([^)]*\)"),
    'link_references': re.compile(r"\[[^\]]*\]\([^)]*\)"),
    'headers': re.compile(r"(?m)^#.*$"),
    'horizontal_rules': re.compile(r"(?m)^(---|[*]{3}|[_]{3})$"),
    'blockquotes': re.compile(r"(?m)^>.*$"),
    'unordered_list_markers': re.compile(r"(?m)^[ \t]*[-*+][ \t]+"),
    'ordered_list_markers': re.compile(r"(?m)^[ \t]*\d+\.[ \t]+"),
    'whitespace': re.compile(r"\s+")
}

AUTHOR_TEMPLATE = """

<style>
{author_css}
</style>



<div class="container">
  <h2>Posts by {author}</h2>
</div>

::::{grid} 1 2 3 4
:margin 2
{author_blogs}
::::
"""

# Template constants
INDEX_TEMPLATE = """---
title: ROCm Blogs
myst:
html_meta:
"description lang=en": "AMD ROCm™ software blogs"
"keywords": "AMD GPU, MI300, MI250, ROCm, blog"
"property=og:locale": "en_US"
---

# ROCm Blogs

<style>
{CSS}
{BANNER_CSS}
</style>
{HTML}
"""

CATEGORY_TEMPLATE = """---
title: {title}{page_title_suffix}
myst:
html_meta:
"description lang=en": "{description}{page_description_suffix}"
"keywords": "AMD GPU, MI300, MI250, ROCm, blog, {keywords}, page {current_page}"
"property=og:locale": "en_US"
---

# {title}{page_title_suffix}

<style>
{CSS}
{PAGINATION_CSS}
</style>
{HTML}

{pagination_controls}
"""

POSTS_TEMPLATE = """---
title: All Posts{page_title_suffix}
myst:
html_meta:
"description lang=en": "All AMD ROCm™ software blogs{page_description_suffix}"
"keywords": "AMD GPU, MI300, MI250, ROCm, blog, posts, articles, page {current_page}"
"property=og:locale": "en_US"
---

# Recent Posts{page_title_suffix}

<style>
{CSS}
{PAGINATION_CSS}
</style>
{HTML}

{pagination_controls}
"""

# Blog count constants
BANNER_BLOGS_COUNT = 5
MAIN_GRID_BLOGS_COUNT = 4
CATEGORY_GRID_BLOGS_COUNT = 4
CATEGORY_BLOGS_PER_PAGE = 12
POST_BLOGS_PER_PAGE = 12

# Image constants
SUPPORTED_FORMATS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tiff', '.tif'}
PROBLEMATIC_IMAGES = {"2024-10-03-image_classification.jpg", "2024-10-10-seismic.jpeg"}
CONTENT_MAX_DIMENSIONS = (1280, 720)
BANNER_DIMENSIONS = (1280, 420)
MIN_SIZE_REDUCTION_PCT = 5.0

# Image format-specific optimization settings
FORMAT_SETTINGS = {
    'JPEG': {'quality': 85, 'optimize': True, 'progressive': True},
    'PNG': {'optimize': True, 'compress_level': 9},
    'GIF': {'optimize': True},
    'WEBP': {'quality': 85, 'method': 6},
}

# Conservative settings for problematic images
CONSERVATIVE_SETTINGS = {
    'JPEG': {'quality': 40, 'optimize': True, 'progressive': True},
    'PNG': {'optimize': True, 'compress_level': 10},
    'WEBP': {'quality': 40, 'method': 4},
}

# WebP conversion settings
WEBP_QUALITY = 85
WEBP_METHOD = 6  # Higher values = better quality but slower
WEBP_CONSERVATIVE_QUALITY = 40
WEBP_CONSERVATIVE_METHOD = 4

# Category definitions
BLOG_CATEGORIES = [
    {
        "name": "Applications & models",
        "template": "applications-models.html",
        "output_base": "applications-models",
        "category_key": "Applications & models",
        "title": "Applications & Models",
        "description": "AMD ROCm™ software blogs about applications and models",
        "keywords": "applications, models, AI, machine learning",
    },
    {
        "name": "Software tools & optimizations",
        "template": "software-tools.html",
        "output_base": "software-tools",
        "category_key": "Software tools & optimizations",
        "title": "Software Tools and Optimizations",
        "description": "AMD ROCm™ software blogs about tools and optimizations",
        "keywords": "software, tools, optimizations, performance",
    },
    {
        "name": "Ecosystems and Partners",
        "template": "ecosystem-partners.html",
        "output_base": "ecosystem-partners",
        "category_key": "Ecosystems and Partners",
        "title": "Ecosystem and Partners",
        "description": "AMD ROCm™ software blogs about ecosystem and partners",
        "keywords": "ecosystem, partners, integrations, collaboration",
    },
]
