"""
Blog class for ROCmBlogs package.
"""

import io
import json
import os
import pathlib
from datetime import datetime
from typing import Optional, List, Union, Dict, Any

from PIL import Image
from sphinx.util import logging as sphinx_logging

# Initialize logger
sphinx_diagnostics = sphinx_logging.getLogger(__name__)

class Blog:
    """
    Represents a blog post with metadata, content, and associated images.
    
    This class handles blog metadata, image processing, author information,
    and date parsing for the ROCmBlogs package.
    """
    
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
    MONTH_NORMALIZATION = {
        "Sept": "Sep"
    }
    
    def __init__(self, file_path: str, metadata: Dict[str, Any], image: Optional[bytes] = None):
        """Initialize a Blog instance."""
        self.file_path = file_path
        self.metadata = metadata
        self.image = image
        self.image_paths = []
        self.word_count = 0
        
        # Dynamically set attributes based on metadata
        for key, value in metadata.items():
            setattr(self, key, value)
            
        # Parse date if available
        self.date = self.parse_date(metadata.get("date")) if "date" in metadata else None

    def set_word_count(self, word_count: int) -> None:
        """Set the word count for the blog."""
        self.word_count = word_count

    def set_file_path(self, file_path: str) -> None:
        """Set the file path for the blog."""
        self.file_path = file_path

    def normalize_date_string(self, date_str: str) -> str:
        """Normalize the date string for consistent parsing."""
        # Apply all normalizations from the mapping
        for original, replacement in self.MONTH_NORMALIZATION.items():
            date_str = date_str.replace(original, replacement)
            
        return date_str
    
    def grab_og_image(self) -> str:
        return self.metadata.get("myst").get("html_meta").get("property=og:image", "https://rocm.blogs.amd.com/_images/generic.jpg")
    
    def grab_og_description(self) -> str:
        return self.metadata.get("myst").get("html_meta").get("property=og:description", "No description available.")
    
    def grab_og_href(self) -> str:
        return self.metadata.get("myst").get("html_meta").get("property=og:url", "https://rocm.blogs.amd.com/")

    def load_image_to_memory(self, image_path: str, format: str = "PNG") -> None:
        """Load an image into memory."""
        try:
            with Image.open(image_path) as img:
                buffer = io.BytesIO()
                img.save(buffer, format=format)
                buffer.seek(0)
                self.image = buffer.getvalue()
                sphinx_diagnostics.info(
                    f"Image loaded into memory; size: {len(self.image)} bytes."
                )
        except Exception as error:
            sphinx_diagnostics.error(
                f"Error loading image to memory: {error}"
            )

    def to_json(self) -> str:
        """Convert the blog metadata to JSON format."""
        # Convert metadata dictionary to JSON string
        try:
            return json.dumps(self.metadata, indent=4)
        except Exception as error:
            sphinx_diagnostics.error(
                f"Error converting metadata to JSON: {error}"
            )
            return "{}"

    def save_image(self, output_path: str) -> None:
        """Save the image to disk."""
        if self.image is None:
            sphinx_diagnostics.warning(
                "No image data available in memory to save."
            )
            return
            
        try:
            # Use binary mode without encoding parameter (encoding is for text files)
            with open(output_path, "wb") as file:
                file.write(self.image)
                sphinx_diagnostics.info(
                    f"Image saved to disk at: {output_path}"
                )
        except Exception as error:
            sphinx_diagnostics.error(
                f"Error saving image to disk: {error}"
            )

    def save_image_path(self, image_path: str) -> None:
        """Save the image path for later use."""
        self.image_paths.append(image_path)

    def parse_date(self, date_str: Optional[str]) -> Optional[datetime]:
        """Parse the date string into a datetime object."""
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
                
        sphinx_diagnostics.warning(
            f"Invalid date format in {self.file_path}: {date_str}"
        )
        return None

    def grab_href(self) -> str:
        """Generate the HTML href for the blog."""
        return self.file_path.replace(".md", ".html").replace("\\", "/")
    
    def grab_authors_list(self) -> List[str]:
        """Extract authors from the metadata."""
        
        sphinx_diagnostics.info(
            f"Extracting authors from metadata: {self.file_path}"
        )

        sphinx_diagnostics.info(
            f"Authors metadata: {self.author}"
        )

        if not self.author:
            return []
        
        sphinx_diagnostics.info(
            f"Author type: {type(self.author)}"
        )
            
        # Ensure authors is a list
        if isinstance(self.author, str):
            authors = list(self.author.split(", "))

        sphinx_diagnostics.info(
            f"Authors after split: {authors}"
        )
            
        return authors

    def grab_authors(self, authors_list: List[Union[str, List[str]]]) -> str:
        """Generate HTML links for authors, but only if their bio file exists."""
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
            
        # Process each author
        author_elements = []
        for author in valid_authors:
            author_file_path = self._find_author_file(author)
            
            if author_file_path:
                # Create HTML link if author file exists
                file_basename = os.path.basename(author_file_path).replace(".md", ".html")
                author_elements.append(
                    f'<a href="https://rocm.blogs.amd.com/authors/{file_basename}">{author}</a>'
                )
            else:
                # Use plain text if no author file exists
                author_elements.append(author)
                
        return ", ".join(author_elements)
        
    def _find_author_file(self, author: str) -> Optional[str]:
        """Find the author's bio file."""
        if not hasattr(self, "file_path"):
            sphinx_diagnostics.warning(
                f"Blog has no file_path, cannot check for author file: {author}"
            )
            return None
            
        # Get authors directory
        blog_dir = os.path.dirname(self.file_path)
        blogs_dir = os.path.dirname(os.path.dirname(blog_dir))
        authors_dir = os.path.join(blogs_dir, "authors")
        
        if not os.path.exists(authors_dir):
            sphinx_diagnostics.warning(
                f"Authors directory not found: {authors_dir}"
            )
            return None
            
        # Special case for Yu Wang
        if author.lower() == "yu wang":
            special_paths = [
                os.path.join(authors_dir, variation) 
                for variation in ["Yu-Wang.md", "yu-wang.md", "YuWang.md", "yuwang.md"]
            ]
            
            for path in special_paths:
                if os.path.exists(path):
                    return path
        
        # Generate filename variations
        name_variations = self._generate_author_filename_variations(author)
        
        # Check for exact matches
        for variation in name_variations:
            author_file_path = os.path.join(authors_dir, variation)
            if os.path.exists(author_file_path):
                return author_file_path
                
        # Try flexible matching with name parts
        try:
            name_parts = author.lower().split()
            for file in os.listdir(authors_dir):
                if not file.lower().endswith(".md"):
                    continue
                    
                file_lower = file.lower()
                if all(part in file_lower for part in name_parts):
                    return os.path.join(authors_dir, file)
        except Exception as e:
            sphinx_diagnostics.error(
                f"Error during flexible author matching: {e}"
            )
            
        return None
        
    def _generate_author_filename_variations(self, author: str) -> List[str]:
        """Generate possible filename variations for an author."""
        variations = [
            "-".join(author.split(" ")).lower() + ".md",
            author.replace(" ", "-").lower() + ".md",
            author.lower().replace(" ", "-") + ".md",
            author.replace(" ", "").lower() + ".md",
            author.replace(" ", "_").lower() + ".md",
            author.replace("-", " ").replace(" ", "-").lower() + ".md",
            author.replace(" ", "-").title().replace(" ", "").lower() + ".md",
            author.replace(" ", "-").lower() + ".md",
            author.lower() + ".md",
        ]
        
        # Remove duplicates and return
        return list(set(variations))

    def grab_image(self, rocmblogs) -> pathlib.Path:
        """Find the image for the blog and return its path."""
        # Get the thumbnail from metadata
        image = getattr(self, "thumbnail", None)
        
        if not image:
            # First check if generic.webp exists in blogs/images directory
            blogs_generic_webp = None
            if hasattr(rocmblogs, "blogs_directory") and rocmblogs.blogs_directory:
                blogs_generic_webp_path = os.path.join(rocmblogs.blogs_directory, "images", "generic.webp")
                if os.path.exists(blogs_generic_webp_path):
                    blogs_generic_webp = blogs_generic_webp_path
            
            # Then check if generic.webp exists in static/images directory
            static_generic_webp_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "images", "generic.webp")
            static_generic_webp = os.path.exists(static_generic_webp_path)
            
            # Use blogs/images/generic.webp if available, otherwise use static/images/generic.webp
            if blogs_generic_webp:
                self.image = "generic.webp"
                self.save_image_path("generic.webp")
                return pathlib.Path("./images/generic.webp")
            elif static_generic_webp:
                self.image = "generic.webp"
                self.save_image_path("generic.webp")
                return pathlib.Path("./images/generic.webp")
            else:
                # Fall back to generic.jpg if no WebP version is available
                self.image = "generic.jpg"
                self.save_image_path("generic.jpg")
                return pathlib.Path("./images/generic.jpg")
            
        # Extract just the filename if a path is provided
        if "/" in image or "\\" in image:
            image = os.path.basename(image)
            
        # Check if it's an absolute path
        if os.path.isabs(image) and os.path.exists(image):
            full_image_path = pathlib.Path(image)
            self.save_image_path(os.path.basename(str(full_image_path)))
            return self._get_relative_path(full_image_path, rocmblogs.blogs_directory)
            
        # Find the image in various locations
        full_image_path = self._find_image_in_directories(image, rocmblogs.blogs_directory)
        
        if not full_image_path:
            # Check if generic.webp exists
            generic_webp_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "images", "generic.webp")
            if os.path.exists(generic_webp_path):
                self.image = "generic.webp"
                self.save_image_path("generic.webp")
                return pathlib.Path("./images/generic.webp")
            else:
                self.image = "generic.jpg"
                self.save_image_path("generic.jpg")
                return pathlib.Path("./images/generic.jpg")
            
        # Save the image path and return the relative path
        image_name = os.path.basename(str(full_image_path))
        self.save_image_path(image_name)
        
        return self._get_relative_path(full_image_path, rocmblogs.blogs_directory)
        
    def _find_image_in_directories(self, image: str, blogs_directory: str) -> Optional[pathlib.Path]:
        """Search for an image in various directories."""
        blog_dir = pathlib.Path(self.file_path).parent
        blogs_dir = pathlib.Path(blogs_directory)
        
        # Check if there's a WebP version of the image
        image_base, image_ext = os.path.splitext(image)
        webp_image = image_base + '.webp'
        
        # Define search paths in order of priority
        search_paths = [
            # First check for WebP version in blog directory and its images subdirectory
            blog_dir / webp_image,
            blog_dir / "images" / webp_image,
            
            # Then check for original image in blog directory and its images subdirectory
            blog_dir / image,
            blog_dir / "images" / image,
            
            # Parent directories (up to 3 levels) - WebP first, then original
            blog_dir.parent / webp_image,
            blog_dir.parent / "images" / webp_image,
            blog_dir.parent / image,
            blog_dir.parent / "images" / image,
        ]
        
        # Add parent2 paths if they exist and aren't the blogs_dir
        parent2 = blog_dir.parent.parent
        if parent2 != blogs_dir:
            search_paths.extend([
                # WebP versions first
                parent2 / webp_image,
                parent2 / "images" / webp_image,
                # Then original images
                parent2 / image,
                parent2 / "images" / image,
            ])
            
            # Add parent3 paths if they exist and aren't the blogs_dir
            parent3 = parent2.parent
            if parent3 != blogs_dir:
                search_paths.extend([
                    # WebP versions first
                    parent3 / webp_image,
                    parent3 / "images" / webp_image,
                    # Then original images
                    parent3 / image,
                    parent3 / "images" / image,
                ])
        
        # Add global image directories
        search_paths.extend([
            # WebP versions first
            blog_dir.parent / "images" / webp_image,
            blogs_dir / "images" / webp_image,
            blogs_dir / "images" / webp_image.lower(),
            # Then original images
            blog_dir.parent / "images" / image,
            blogs_dir / "images" / image,
            blogs_dir / "images" / image.lower(),
        ])
        
        # Check each path
        for path in search_paths:
            if path.exists() and path.is_file():
                # If we found a WebP version, log it
                if str(path).lower().endswith('.webp'):
                    sphinx_diagnostics.info(
                        f"Using WebP version for image: {path}"
                    )
                return path
                
        # Try partial matching in the global images directory
        images_dir = blogs_dir / "images"
        if images_dir.exists():
            # First try to find WebP version by partial matching
            webp_base = os.path.splitext(image)[0].lower()
            for img_file in images_dir.glob("*.webp"):
                if img_file.is_file() and webp_base in img_file.name.lower():
                    sphinx_diagnostics.info(
                        f"Found WebP version by partial matching: {img_file}"
                    )
                    return img_file
            
            # If no WebP version found, try to find original image by partial matching
            image_base = os.path.splitext(image)[0].lower()
            for img_file in images_dir.glob("*"):
                if img_file.is_file() and image_base in img_file.name.lower():
                    # If we found an image, try to convert it to WebP
                    if not str(img_file).lower().endswith('.webp'):
                        try:
                            from PIL import Image
                            
                            # Open the image
                            with Image.open(img_file) as img:
                                # Get image properties
                                original_width, original_height = img.size
                                
                                # Convert to RGB or RGBA if needed for WebP
                                webp_img = img
                                if img.mode not in ('RGB', 'RGBA'):
                                    webp_img = img.convert('RGB')
                                
                                # Resize image if needed - maintain aspect ratio for content images
                                if original_width > 1280 or original_height > 720:
                                    # Calculate scaling factor to maintain aspect ratio
                                    scaling_factor = min(1280 / original_width, 720 / original_height)
                                    
                                    new_width = int(original_width * scaling_factor)
                                    new_height = int(original_height * scaling_factor)
                                    
                                    webp_img = webp_img.resize((new_width, new_height), resample=Image.LANCZOS)
                                    sphinx_diagnostics.info(
                                        f"Resized image from {original_width}x{original_height} to {new_width}x{new_height}"
                                    )
                                
                                # Save as WebP
                                webp_path = os.path.splitext(str(img_file))[0] + '.webp'
                                webp_img.save(webp_path, format="WEBP", quality=85, method=6)
                                
                                # Return the WebP version
                                sphinx_diagnostics.info(
                                    f"Successfully converted {img_file} to WebP: {webp_path}"
                                )
                                return pathlib.Path(webp_path)
                        except Exception as e:
                            sphinx_diagnostics.warning(
                                f"Failed to convert {img_file} to WebP: {e}"
                            )
                    
                    return img_file
                    
        return None
        
    def _get_relative_path(self, full_path: pathlib.Path, base_dir: str) -> pathlib.Path:
        """Convert an absolute path to a relative path."""
        relative_path = os.path.relpath(str(full_path), str(base_dir))
        relative_path = relative_path.replace("\\", "/")
        
        if not relative_path.startswith("./"):
            relative_path = "./" + relative_path
            
        return pathlib.Path(relative_path)

    def __repr__(self) -> str:
        """Return a string representation of the class."""
        return f"Blog(file_path='{self.file_path}', metadata={self.metadata})"