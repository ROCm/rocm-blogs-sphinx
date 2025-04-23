"""
File: _blog_holder.py

BlogHolder class to hold the blogs.
"""

import os
import csv
import traceback
from datetime import datetime
from sphinx.util import logging as sphinx_logging

from .blog import Blog

# Initialize logger
sphinx_diagnostics = sphinx_logging.getLogger(__name__)

class BlogHolder:
    def __init__(self) -> None:
        """Initialize the BlogHolder class."""

        self.blogs: dict[str, Blog] = {}
        self.blogs_categories: dict[str, list[Blog]] = {}
        self.blogs_authors: dict[str, list[Blog]] = {}
        self.blogs_featured: dict[str, list[Blog]] = {}

    def _make_key(self, blog: Blog) -> str:
        """Make a key for the blog."""

        if not isinstance(blog, Blog):
            sphinx_diagnostics.error(
                f"Expected Blog instance but got {type(blog)}"
            )
            raise TypeError("The blog must be an instance of the 'Blog' class.")

        # Get title with fallback
        if hasattr(blog, "blog_title") and blog.blog_title:
            title = blog.blog_title
        else:
            # Use file path as fallback
            if hasattr(blog, "file_path"):
                filename = os.path.basename(blog.file_path)
                title = os.path.splitext(filename)[0].replace("-", " ").replace("_", " ").title()
                sphinx_diagnostics.warning(
                    f"Blog missing blog_title attribute, using filename: {title}"
                )
            else:
                title = "Untitled Blog"
                sphinx_diagnostics.warning(
                    f"Blog missing both blog_title and file_path, using default: {title}"
                )

        # Get date with fallback
        if hasattr(blog, "date") and blog.date:
            date = blog.date
        else:
            # Use current date as fallback
            date = datetime.now()
            sphinx_diagnostics.warning(
                f"Blog '{title}' missing date attribute, using current date: {date}"
            )

        sphinx_diagnostics.debug(
            f"Created key for blog: ({title}, {date})"
        )
        return title

    def add_blog(self, blog: Blog) -> None:
        """Add a blog to the list of blogs."""

        key = self._make_key(blog)
        if key in self.blogs:
            sphinx_diagnostics.warning(
                f"Duplicate blog detected: '{key}'"
            )
            raise KeyError(
                f"Blog with title '{key}' already exists."
            )
        self.blogs[key] = blog
        sphinx_diagnostics.info(
            f"Added blog: '{blog}'"
        )
        if hasattr(blog, "author"):
            sphinx_diagnostics.debug(
                f"Adding blog '{key}' to author '{blog.author}'"
            )
            for author in blog.grab_authors_list():
                if author not in self.blogs_authors:
                    self.blogs_authors[author] = []
                    sphinx_diagnostics.debug(
                        f"Initialized author list for: {author}, {self.blogs_authors}"
                    )
                # Append blog to the author's list
                if blog not in self.blogs_authors[author]:
                    sphinx_diagnostics.debug(
                        f"Adding blog '{key}' to author '{author}'"
                    )
                    self.blogs_authors[author].append(blog)
                else:
                    sphinx_diagnostics.warning(
                        f"Blog '{key}' already exists in author's list: {author}"
                    )
        else:
            sphinx_diagnostics.warning(
                f"Blog '{key}' has no author specified"
            )

    def remove_blog(self, blog: Blog) -> None:
        """Remove a blog from the list of blogs."""

        if not hasattr(blog, "blog_title"):
            sphinx_diagnostics.error(
                "Cannot remove blog: missing blog_title attribute"
            )
            raise AttributeError("The blog must have a 'blog_title' attribute.")
        title = blog.blog_title

        if not hasattr(blog, "date"):
            sphinx_diagnostics.error(
                f"Cannot remove blog '{title}': missing date attribute"
            )
            raise AttributeError("The blog must have a 'date' attribute.")
        date = blog.date

        key = (title, date)
        if key in self.blogs:
            del self.blogs[key]
            sphinx_diagnostics.info(
                f"Removed blog: '{title}' with date '{date}'"
            )
        else:
            sphinx_diagnostics.warning(
                f"Cannot remove blog: '{title}' with date '{date}' not found"
            )
            raise KeyError("Blog not found.")
        
    def write_to_file(self, filename: str = "blogs.csv") -> None:
        """Write blog information to a CSV file."""
        try:
            with open(filename, "w", newline='') as file:
                writer = csv.writer(file)
                # Write header row
                writer.writerow(["title", "date", "author", "category", "tags", "thumbnail", "file_path"])
                
                # Write data rows
                for blog in self.blogs.values():
                    title = blog.blog_title if hasattr(blog, "blog_title") else "Untitled"
                    date = blog.date.strftime("%Y-%m-%d") if hasattr(blog, "date") and blog.date else ""
                    author = blog.author if hasattr(blog, "author") else ""
                    category = blog.category if hasattr(blog, "category") else ""
                    tags = blog.tags if hasattr(blog, "tags") else ""
                    thumbnail = blog.thumbnail if hasattr(blog, "thumbnail") else ""
                    file_path = blog.file_path if hasattr(blog, "file_path") else ""
                    
                    writer.writerow([title, date, author, category, tags, thumbnail, file_path])
                    
            sphinx_diagnostics.info(
                f"Successfully wrote {len(self.blogs)} blog entries to {filename}"
            )
        except Exception as error:
            sphinx_diagnostics.error(
                f"Error writing blogs to file: {error}"
            )
            raise
            
    def create_features_template(self, filename: str = "features_template.csv") -> None:
        """Create a template featured-blogs.csv file with all available blog titles."""
        try:
            with open(filename, "w", newline='') as file:
                writer = csv.writer(file)
                
                # Add a comment line explaining how to use the file
                writer.writerow(["# Features template - Remove this line and uncomment the blog titles you want to feature"])
                writer.writerow(["# One blog title per line - Titles must match exactly"])
                writer.writerow(["# "])
                
                # Write all available blog titles, commented out
                for blog in self.blogs.values():
                    if hasattr(blog, "blog_title") and blog.blog_title:
                        # Comment out each title with # so users can uncomment the ones they want
                        writer.writerow([f"# {blog.blog_title}"])
                
            sphinx_diagnostics.info(
                f"Successfully created features template at {filename}"
            )
            sphinx_diagnostics.info(
                f"Edit this file to select which blogs to feature, then rename it to 'featured-blogs.csv'"
            )
            
            return filename
            
        except Exception as error:
            sphinx_diagnostics.error(
                f"Error creating features template: {error}"
            )
            raise
            
    def load_featured_blogs_from_csv(self, filename: str = "featured-blogs.csv") -> list[Blog]:
        """Load featured blog titles from a CSV file and return the corresponding blogs."""
        featured_blogs = []
        
        try:
            if not os.path.exists(filename):
                sphinx_diagnostics.warning(
                    f"Featured blogs file not found: {filename}"
                )
                return featured_blogs
            
            sphinx_diagnostics.info(
                f"Reading featured blogs from: {os.path.abspath(filename)}"
            )
                
            with open(filename, "r", newline='') as file:
                reader = csv.reader(file)
                raw_rows = list(reader)
                sphinx_diagnostics.debug(
                    f"Raw CSV content: {raw_rows}"
                )
                
                featured_titles = [row[0] for row in raw_rows if row]  # Get the first column (title)
                
            sphinx_diagnostics.info(
                f"Found {len(featured_titles)} featured blog titles in {filename}"
            )
            
            # Log all available blog titles for comparison
            available_blog_titles = [blog.blog_title for blog in self.blogs.values() 
                                    if hasattr(blog, "blog_title") and blog.blog_title]
            sphinx_diagnostics.debug(
                f"Available blog titles in system: {available_blog_titles}"
            )
            
            for index, title in enumerate(featured_titles):
                sphinx_diagnostics.debug(
                    f"Featured title {index+1}: '{title}' (length: {len(title)})"
                )
            
            # Find blogs with matching titles
            for title in featured_titles:
                blog = self.get_blog_by_title(title)
                if blog:
                    if blog not in featured_blogs:
                        sphinx_diagnostics.debug(
                            f"Adding blog '{title}' to featured blogs"
                        )
                        featured_blogs.append(blog)
                    else:
                        sphinx_diagnostics.warning(
                            f"Duplicate featured blog found: '{title}'"
                        )
                    sphinx_diagnostics.debug(
                        f"Found featured blog: '{title}'"
                    )
                else:
                    close_matches = []
                    for available_title in available_blog_titles:
                        if title.lower() in available_title.lower() or available_title.lower() in title.lower():
                            close_matches.append(available_title)
                    
                    if close_matches:
                        sphinx_diagnostics.warning(
                            f"Featured blog not found: '{title}'. Possible close matches: {close_matches}"
                        )
                        title = close_matches[0]
                        blog = self.get_blog_by_title(title)
                        if blog:
                            if blog not in featured_blogs:
                                sphinx_diagnostics.debug(
                                    f"Adding blog '{title}' to featured blogs"
                                )
                                featured_blogs.append(blog)
                            else:
                                sphinx_diagnostics.warning(
                                    f"Duplicate featured blog found: '{title}'"
                                )
                            sphinx_diagnostics.debug(
                                f"Found featured blog: '{title}'"
                            )
                    else:
                        sphinx_diagnostics.warning(
                            f"Featured blog not found: '{title}'. No close matches found."
                        )
            
            sphinx_diagnostics.info(
                f"Loaded {len(featured_blogs)} featured blogs out of {len(featured_titles)} titles"
            )
            
            if not featured_blogs:
                sphinx_diagnostics.warning(
                    "No featured blogs found. Please check the CSV file."
                )
            self.blogs_featured["featured"] = featured_blogs
            
            return featured_blogs
            
        except Exception as error:
            sphinx_diagnostics.error(
                f"Error loading featured blogs from file: {error}"
            )
            sphinx_diagnostics.debug(
                f"Traceback: {traceback.format_exc()}"
            )
            return []

    def get_blog_by_key(self, key: tuple[str, datetime]) -> Blog:
        """Get a blog by its key."""

        if key in self.blogs:
            sphinx_diagnostics.debug(
                f"Found blog with key: {key}"
            )
            return self.blogs[key]

        sphinx_diagnostics.debug(
            f"No blog found with key: {key}"
        )
        return None

    def get_blogs(self) -> list[Blog]:
        """Return the list of blogs."""
        
        blog_count = len(self.blogs)
        sphinx_diagnostics.debug(
            f"Returning {blog_count} blogs"
        )
        return list(self.blogs.values())

    def clear_blogs(self) -> None:
        """Clear the list of blogs."""
        
        blog_count = len(self.blogs)

        sphinx_diagnostics.info(
            f"Clearing {blog_count} blogs from the blog holder"
        )
        self.blogs.clear()
        sphinx_diagnostics.debug(
            "Blog holder cleared"
        )

    def sort_blogs_by_date(self, reverse: bool = True) -> list[Blog]:
        """Sort the blogs by date."""
        
        sphinx_diagnostics.info(
            f"Sorting {len(self.blogs)} blogs by date (reverse={reverse})"
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
        
        sphinx_diagnostics.debug("Blogs sorted by date")
        return list(self.blogs.values())
    
    def sort_blogs_by_category(self, categories) -> list[Blog]:
        """Sort the blogs by category."""
        
        sphinx_diagnostics.info(
            f"Sorting {len(self.blogs)} blogs into {len(categories)} categories"
        )
        
        # Clear existing category lists
        self.blogs_categories = {}
        
        # Initialize category lists
        for category in categories:
            self.blogs_categories[category] = []
            sphinx_diagnostics.debug(
                f"Initialized category: {category}"
            )

        # Sort blogs into categories
        category_counts = {}
        for blog in self.blogs.values():
            if blog.category in categories:
                self.blogs_categories[blog.category].append(blog)
                category_counts[blog.category] = category_counts.get(blog.category, 0) + 1
        
        # Log category counts
        for category, count in category_counts.items():
            sphinx_diagnostics.info(
                f"Category '{category}' has {count} blogs"
            )
        
        # Log categories with no blogs
        for category in categories:
            if category not in category_counts:
                sphinx_diagnostics.warning(
                    f"Category '{category}' has no blogs"
                )

    def get_latest_blogs(self, count: int = 15) -> list[Blog]:
        """Get the latest blogs based on the count."""
        
        available_count = min(count, len(self.blogs))
        sphinx_diagnostics.debug(
            f"Getting {available_count} latest blogs (requested: {count})"
        )
        return list(self.blogs.values())[:available_count]

    def get_blog_by_title(self, title: str) -> Blog:
        """Get a blog by its title."""
        
        sphinx_diagnostics.debug(
            f"Searching for blog with title: '{title}'"
        )
        
        # First try exact match
        for blog in self.blogs.values():
            if hasattr(blog, "blog_title") and blog.blog_title == title:
                sphinx_diagnostics.debug(
                    f"Found exact match for blog title: '{title}'"
                )
                return blog
        
        # Try case-insensitive match
        title_lower = title.lower()
        for blog in self.blogs.values():
            if hasattr(blog, "blog_title") and blog.blog_title.lower() == title_lower:
                sphinx_diagnostics.debug(
                    f"Found case-insensitive match for blog title: '{title}' -> '{blog.blog_title}'"
                )
                return blog
        
        # Try normalized match (remove extra whitespace, special chars)
        def normalize_title(t):
            if not t:
                return ""
            # Replace multiple spaces with single space
            t = ' '.join(t.split())
            # Remove common punctuation
            for char in [',', '.', ':', ';', '!', '?', '"', "'", '(', ')', '[', ']', '{', '}']:
                t = t.replace(char, '')
            return t.lower().strip()
        
        normalized_title = normalize_title(title)
        for blog in self.blogs.values():
            if hasattr(blog, "blog_title"):
                normalized_blog_title = normalize_title(blog.blog_title)
                if normalized_blog_title == normalized_title:
                    sphinx_diagnostics.debug(
                        f"Found normalized match for blog title: '{title}' -> '{blog.blog_title}'"
                    )
                    return blog
        
        sphinx_diagnostics.debug(
            f"No blog found with title: '{title}' (tried exact, case-insensitive, and normalized matching)"
        )
        return None
    
    def get_blogs_by_author(self, author: str) -> list[Blog]:
        """Get blogs by author."""
        
        if author in self.blogs_authors:
            blog_count = len(self.blogs_authors[author])
            sphinx_diagnostics.debug(
                f"Found {blog_count} blogs by author: {author}"
            )
            return self.blogs_authors[author]

        sphinx_diagnostics.debug(
            f"No blogs found by author: {author}"
        )
        return []

    def get_blogs_by_category(self, category: str) -> list[Blog]:
        """Get blogs by category."""
        
        if category in self.blogs_categories:
            blog_count = len(self.blogs_categories[category])
            sphinx_diagnostics.debug(
                f"Found {blog_count} blogs in category: {category}"
            )
            return self.blogs_categories[category]

        sphinx_diagnostics.debug(
            f"No blogs found in category: {category}"
        )
        return []

    def __iter__(self) -> iter:
        """Iterate over the list of blogs."""

        return iter(self.blogs.values())

    def __len__(self) -> int:
        """Return the number of blogs."""

        return len(self.blogs)

    def __repr__(self) -> str:
        """Return a string representation of the class."""

        return f"BlogHolder(blogs={self.blogs})"
