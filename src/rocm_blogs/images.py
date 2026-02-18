"""
Image processing utilities for ROCm Blogs.

This module contains functions for image optimization, WebP conversion,
and other image-related operations used in the ROCm Blogs package.
"""

import os
import shutil
from datetime import datetime

from PIL import Image
from sphinx.util import logging as sphinx_logging

from ._rocmblogs import ROCmBlogs
from .constants import *
from .logger.logger import create_step_log_file, log_message, safe_log_write

WEBP_CONVERSION_STATISTICS = {
    "converted": 0,
    "skipped": 0,
    "failed": 0,
    "total_size_original": 0,
    "total_size_webp": 0,
}


def convert_to_webp(source_image_path, destination_image_path=None):
    """Convert an image to WebP format with proper resizing.

    If ``destination_image_path`` is provided, write the converted WebP to that
    path. Otherwise, write next to the source image using the same basename.
    """
    source_image_filename = os.path.basename(source_image_path)
    webp_image_path = (
        destination_image_path
        if destination_image_path
        else os.path.splitext(source_image_path)[0] + ".webp"
    )

    if not os.path.exists(source_image_path):
        log_message("warning", f"Image file not found: {source_image_path}")
        return False, None

    _, file_extension = os.path.splitext(source_image_path)
    if file_extension.lower() not in SUPPORTED_FORMATS:
        log_message(
            "warning",
            f"Unsupported image format: {file_extension} for {source_image_path}",
        )
        return False, None

    # WebP-only policy: do not fall back to excluded non-WebP formats.
    if file_extension.lower() in EXCLUDED_EXTENSIONS:
        log_message(
            "warning",
            f"Excluded image format cannot be used for WebP-only output: {source_image_path}",
            "general",
            "images",
        )
        return False, None

    if file_extension.lower() == ".webp":
        if destination_image_path:
            try:
                if os.path.abspath(source_image_path) != os.path.abspath(webp_image_path):
                    shutil.copy2(source_image_path, webp_image_path)
                    return True, webp_image_path
            except Exception as copy_error:
                log_message("warning", f"Error copying existing WebP image: {copy_error}")
        log_message("debug", f"Image is already in WebP format: {source_image_path}")
        return True, source_image_path

    destination_dir = os.path.dirname(webp_image_path)
    if destination_dir:
        os.makedirs(destination_dir, exist_ok=True)

    if os.path.exists(webp_image_path):
        log_message("debug", f"WebP version already exists: {webp_image_path}")
        return True, webp_image_path

    try:
        with Image.open(source_image_path) as pil_image:
            original_width, original_height = pil_image.size
            original_mode = pil_image.mode

            webp_image = (
                pil_image
                if original_mode in ("RGB", "RGBA")
                else pil_image.convert("RGB")
            )

            is_banner_image = "banner" in str(source_image_path).lower()
            if is_banner_image:
                webp_image = _resize_image(
                    webp_image,
                    BANNER_DIMENSIONS[0],
                    BANNER_DIMENSIONS[1],
                    force_exact=True,
                    source_image_filename=source_image_filename,
                )
                log_message(
                    "info",
                    "Resized banner image to {BANNER_DIMENSIONS[0]}x{BANNER_DIMENSIONS[1]}: {source_image_filename}",
                    "general",
                    "images",
                )
            else:
                webp_image = _resize_content_image(
                    webp_image,
                    original_width,
                    original_height,
                    source_image_filename=source_image_filename,
                )
                if webp_image.size != (original_width, original_height):
                    new_width, new_height = webp_image.size
                    log_message(
                        "info",
                        "Resized image from {original_width}x{original_height} to {new_width}x{new_height}: {source_image_filename}",
                        "general",
                        "images",
                    )

            webp_image.save(
                webp_image_path, format="WEBP", quality=WEBP_QUALITY, method=WEBP_METHOD
            )

            log_message(
                "info",
                f"Created WebP version: {os.path.basename(webp_image_path)}",
                "general",
                "images",
            )

            return True, webp_image_path

    except Exception as webp_conversion_error:
        log_message("warning", f"Error creating WebP version: {webp_conversion_error}")
        if os.path.exists(webp_image_path):
            os.remove(webp_image_path)
        return False, None


def optimize_image(source_image_path, blog_thumbnail_filenames=None):
    """Optimize images for web display and convert to WebP format."""
    source_image_filename = os.path.basename(source_image_path)
    backup_image_path = f"{source_image_path}.bak"
    webp_image_path = os.path.splitext(source_image_path)[0] + ".webp"

    if not _should_optimize_image(
        source_image_path, source_image_filename, blog_thumbnail_filenames
    ):
        return False, None

    if not _create_backup(source_image_path, backup_image_path):
        return False, None

    original_file_size = os.path.getsize(source_image_path)

    try:
        with Image.open(source_image_path) as pil_image:
            source_image_width, source_image_height = pil_image.size
            source_image_format = pil_image.format
            source_image_mode = pil_image.mode

            log_message(
                "debug",
                f"Image details: {source_image_filename}, Format: {source_image_format}, Mode: {source_image_mode}, Size: {source_image_width}x{source_image_height}",
            )

            if not _verify_image_integrity(
                pil_image, source_image_path, backup_image_path, source_image_filename
            ):
                return False, None

            if source_image_filename in PROBLEMATIC_IMAGES:
                success, webp_image_path = _handle_problematic_image(
                    pil_image,
                    source_image_path,
                    backup_image_path,
                    source_image_filename,
                )
                return success, webp_image_path

            optimized_image = _process_image(
                pil_image,
                source_image_path,
                source_image_mode,
                source_image_width,
                source_image_height,
                backup_image_path,
                source_image_filename,
            )
            if optimized_image is None:
                return False, None

            if not _save_optimized_image(
                optimized_image,
                source_image_path,
                backup_image_path,
                source_image_filename,
            ):
                return False, None

            webp_conversion_success = _create_webp_version(
                optimized_image, webp_image_path, source_image_path, original_file_size
            )

            if not _verify_and_check_size_reduction(
                source_image_path,
                backup_image_path,
                original_file_size,
                source_image_format,
                source_image_filename,
            ):
                pass

        if os.path.exists(backup_image_path):
            os.remove(backup_image_path)

        return True, webp_image_path if webp_conversion_success else None

    except Exception as optimize_error:
        log_message(
            "warning",
            f"Error optimizing image {source_image_filename}: {optimize_error}",
        )
        _restore_from_backup(
            backup_image_path, source_image_path, source_image_filename
        )
        WEBP_CONVERSION_STATISTICS["failed"] += 1
        return False, None


def _should_optimize_image(
    source_image_path, source_image_filename, blog_thumbnail_filenames
):
    """Check if the image should be optimized."""
    if blog_thumbnail_filenames is not None:
        if (
            source_image_filename not in blog_thumbnail_filenames
            and source_image_filename.lower()
            not in [thumbnail.lower() for thumbnail in blog_thumbnail_filenames]
        ):
            log_message("debug", f"Skipping non-thumbnail image: {source_image_path}")
            return False

    if not os.path.exists(source_image_path):
        log_message("warning", f"Image file not found: {source_image_path}")
        return False

    _, file_extension = os.path.splitext(source_image_path)
    if file_extension.lower() not in SUPPORTED_FORMATS:
        log_message(
            "warning",
            f"Unsupported image format: {file_extension} for {source_image_path}",
        )
        return False

    return True


def _create_backup(source_image_path, backup_image_path):
    """Create a backup of the original image."""
    try:
        shutil.copy2(source_image_path, backup_image_path)
        return True
    except Exception as backup_error:
        log_message(
            "warning", f"Failed to create backup of {source_image_path}: {backup_error}"
        )
        return False


def _restore_from_backup(backup_image_path, source_image_path, source_image_filename):
    """Restore the original image from backup."""
    if os.path.exists(backup_image_path):
        log_message(
            "info",
            "Restoring original image from backup for {source_image_filename}",
            "general",
            "images",
        )
        try:
            shutil.copy2(backup_image_path, source_image_path)
            os.remove(backup_image_path)
        except Exception as restore_error:
            log_message("warning", f"Error restoring from backup: {restore_error}")


def _verify_image_integrity(
    pil_image, source_image_path, backup_image_path, source_image_filename
):
    """Verify the image is not corrupted."""
    try:
        pil_image.verify()
        return True
    except Exception as verify_error:
        log_message(
            "warning", f"Corrupted image detected: {source_image_path} - {verify_error}"
        )
        _restore_from_backup(
            backup_image_path, source_image_path, source_image_filename
        )
        return False


def _handle_problematic_image(
    pil_image, source_image_path, backup_image_path, source_image_filename
):
    """Handle problematic images with more conservative optimization."""
    log_message(
        "info",
        "Using conservative optimization for {source_image_filename}",
        "general",
        "images",
    )
    webp_image_path = os.path.splitext(source_image_path)[0] + ".webp"

    try:
        _, file_extension = os.path.splitext(source_image_path)
        file_extension = file_extension.lower()

        pil_image = Image.open(source_image_path)

        if file_extension in [".jpg", ".jpeg"]:
            pil_image.save(
                source_image_path, format="JPEG", **CONSERVATIVE_SETTINGS["JPEG"]
            )
        elif file_extension == ".png":
            pil_image.save(
                source_image_path, format="PNG", **CONSERVATIVE_SETTINGS["PNG"]
            )
        else:
            pil_image.save(source_image_path)

        webp_image = (
            pil_image if pil_image.mode in ("RGB", "RGBA") else pil_image.convert("RGB")
        )
        webp_image.save(webp_image_path, format="WEBP", **CONSERVATIVE_SETTINGS["WEBP"])

        WEBP_CONVERSION_STATISTICS["converted"] += 1
        WEBP_CONVERSION_STATISTICS["total_size_original"] += os.path.getsize(
            source_image_path
        )
        WEBP_CONVERSION_STATISTICS["total_size_webp"] += os.path.getsize(
            webp_image_path
        )

        log_message(
            "info",
            "Conservative optimization completed for {source_image_filename} with WebP version",
            "general",
            "images",
        )

        if os.path.exists(backup_image_path):
            os.remove(backup_image_path)

        return True, webp_image_path
    except Exception as conservative_error:
        log_message(
            "warning",
            f"Conservative optimization failed for {source_image_filename}: {conservative_error}",
        )
        _restore_from_backup(
            backup_image_path, source_image_path, source_image_filename
        )
        WEBP_CONVERSION_STATISTICS["failed"] += 1
        return False, None


def _create_webp_version(
    optimized_image, webp_image_path, original_image_path, original_file_size
):
    """Create a WebP version of the image."""

    # check if file extension is in excluded list
    _, file_extension = os.path.splitext(original_image_path)
    file_extension = file_extension.lower()
    if file_extension in EXCLUDED_EXTENSIONS:
        log_message(
            "info",
            "Skipping WebP conversion for excluded image format: {file_extension} for {original_image_path}",
            "general",
            "images",
        )
        return False
    try:
        webp_image = (
            optimized_image
            if optimized_image.mode in ("RGB", "RGBA")
            else optimized_image.convert("RGB")
        )

        webp_image.save(
            webp_image_path, format="WEBP", quality=WEBP_QUALITY, method=WEBP_METHOD
        )

        webp_file_size = os.path.getsize(webp_image_path)
        size_reduction_percentage = (
            (1 - webp_file_size / original_file_size) * 100
            if original_file_size > 0
            else 0
        )

        if (
            webp_file_size >= original_file_size
            or size_reduction_percentage < MIN_SIZE_REDUCTION_PCT
        ):
            log_message(
                "info",
                f"WebP conversion not beneficial (size reduction: {size_reduction_percentage:.1f}%), skipping: {os.path.basename(webp_image_path)}",
                "general",
                "images",
            )

            if os.path.exists(webp_image_path):
                os.remove(webp_image_path)
            WEBP_CONVERSION_STATISTICS["skipped"] += 1
            return False

        WEBP_CONVERSION_STATISTICS["converted"] += 1
        WEBP_CONVERSION_STATISTICS["total_size_original"] += original_file_size
        WEBP_CONVERSION_STATISTICS["total_size_webp"] += os.path.getsize(
            webp_image_path
        )

        log_message(
            "info",
            f"Created WebP version: {os.path.basename(webp_image_path)}",
            "general",
            "images",
        )
        log_message(
            "info",
            f"Original: {original_file_size/1024:.1f}KB -> WebP: {os.path.getsize(webp_image_path)/1024:.1f}KB ({size_reduction_percentage:.1f}% reduction)",
            "general",
            "images",
        )

        return True

    except Exception as webp_conversion_error:
        log_message("warning", f"Error creating WebP version: {webp_conversion_error}")
        if os.path.exists(webp_image_path):
            os.remove(webp_image_path)
        WEBP_CONVERSION_STATISTICS["failed"] += 1
        return False


def _process_image(
    pil_image,
    source_image_path,
    source_image_mode,
    source_image_width,
    source_image_height,
    backup_image_path,
    source_image_filename,
):
    """Process the image by stripping metadata and resizing if needed."""

    # check if file extension is in excluded list
    _, file_extension = os.path.splitext(source_image_path)
    file_extension = file_extension.lower()
    if file_extension in EXCLUDED_EXTENSIONS:
        log_message(
            "info",
            "Skipping optimization for excluded image format: {file_extension} for {source_image_path}",
            "general",
            "images",
        )
        return None
    try:
        image_data = list(pil_image.getdata())
        target_mode = "RGBA" if pil_image.mode in ("RGB", "RGBA") else "RGB"
        image_without_exif = Image.new(target_mode, pil_image.size)

        if source_image_mode != target_mode:
            pil_image = pil_image.convert(target_mode)
            image_data = list(pil_image.getdata())

        image_without_exif.putdata(image_data)

        is_banner_image = "banner" in str(source_image_path).lower()
        if is_banner_image:
            image_without_exif = _resize_image(
                image_without_exif,
                BANNER_DIMENSIONS[0],
                BANNER_DIMENSIONS[1],
                force_exact=True,
                source_image_filename=source_image_filename,
            )
        else:
            image_without_exif = _resize_content_image(
                image_without_exif,
                source_image_width,
                source_image_height,
                source_image_filename=source_image_filename,
            )

        return image_without_exif

    except Exception as process_error:
        log_message("warning", f"Error processing image: {process_error}")
        _restore_from_backup(
            backup_image_path, source_image_path, source_image_filename
        )
        return None


def _resize_image(
    pil_image,
    target_width,
    target_height,
    force_exact=False,
    source_image_filename=None,
):
    """Resize image to target dimensions."""
    try:
        if force_exact:
            resized_image = pil_image.resize(
                (target_width, target_height), resample=Image.LANCZOS
            )
            if source_image_filename:
                log_message(
                    "debug",
                    f"Resized image to exact dimensions: {target_width}x{target_height}",
                )
            return resized_image
        return pil_image
    except Exception as resize_error:
        log_message("warning", f"Error resizing image: {resize_error}")
        return pil_image


def _resize_content_image(
    pil_image, source_image_width, source_image_height, source_image_filename=None
):
    """Resize content image maintaining aspect ratio if needed."""
    max_width, max_height = CONTENT_MAX_DIMENSIONS

    if source_image_width <= max_width and source_image_height <= max_height:
        return pil_image

    if source_image_width > 0 and source_image_height > 0:
        scaling_factor = min(
            max_width / source_image_width, max_height / source_image_height
        )
        if scaling_factor < 1:
            new_width = int(source_image_width * scaling_factor)
            new_height = int(source_image_height * scaling_factor)
            try:
                resized_image = pil_image.resize(
                    (new_width, new_height), resample=Image.LANCZOS
                )
                if source_image_filename:
                    log_message(
                        "debug",
                        f"Resized image: {source_image_width}x{source_image_height} -> {new_width}x{new_height}",
                    )
                return resized_image
            except Exception as resize_error:
                log_message("warning", f"Error resizing content image: {resize_error}")

    return pil_image


def _save_optimized_image(
    optimized_image, optimized_image_path, backup_image_path, source_image_filename
):
    """Save the optimized image with format-specific settings."""
    try:
        _, file_extension = os.path.splitext(optimized_image_path)
        file_extension = file_extension.lower()

        if file_extension in [".jpg", ".jpeg"]:
            optimized_image.save(
                optimized_image_path, format="JPEG", **FORMAT_SETTINGS["JPEG"]
            )
        elif file_extension == ".png":
            has_transparency = (
                "A" in optimized_image.mode or "transparency" in optimized_image.info
            )
            if has_transparency:
                optimized_image.save(
                    optimized_image_path, format="PNG", **FORMAT_SETTINGS["PNG"]
                )
            else:
                if optimized_image.mode != "RGB":
                    optimized_image = optimized_image.convert("RGB")
                optimized_image.save(
                    optimized_image_path, format="PNG", **FORMAT_SETTINGS["PNG"]
                )
        elif file_extension == ".webp":
            optimized_image.save(
                optimized_image_path, format="WEBP", **FORMAT_SETTINGS["WEBP"]
            )
        elif file_extension in EXCLUDED_EXTENSIONS:
            # skip GIF optimization
            log_message(
                "info",
                "Skipping optimization for {source_image_filename}",
                "general",
                "images",
            )
        else:
            optimized_image.save(optimized_image_path)

        return True

    except Exception as save_error:
        log_message(
            "warning",
            f"Error saving optimized image {optimized_image_path}: {save_error}",
        )
        _restore_from_backup(
            backup_image_path, optimized_image_path, source_image_filename
        )
        return False


def _verify_and_check_size_reduction(
    optimized_image_path,
    backup_image_path,
    original_file_size,
    source_image_format,
    source_image_filename,
):
    """Verify the optimized image and check if size reduction is beneficial."""
    try:
        with Image.open(optimized_image_path) as verify_image:
            verify_image.verify()
    except Exception as verify_error:
        log_message("warning", f"Optimized image verification failed: {verify_error}")
        _restore_from_backup(
            backup_image_path, optimized_image_path, source_image_filename
        )
        return False

    try:
        new_file_size = os.path.getsize(optimized_image_path)
        size_reduction_percentage = (
            (1 - new_file_size / original_file_size) * 100
            if original_file_size > 0
            else 0
        )

        if (
            new_file_size > original_file_size
            or size_reduction_percentage < MIN_SIZE_REDUCTION_PCT
        ):
            log_message(
                "info",
                f"Optimization not beneficial (size reduction: {size_reduction_percentage:.1f}%), reverting",
                "general",
                "images",
            )

            _restore_from_backup(
                backup_image_path, optimized_image_path, source_image_filename
            )
            return True

        log_message(
            "info",
            f"Optimized {source_image_filename}: {source_image_format} {original_file_size/1024:.1f}KB -> {new_file_size/1024:.1f}KB ({size_reduction_percentage:.1f}% reduction)",
            "general",
            "images",
        )

        return True

    except Exception as size_error:
        log_message("warning", f"Error calculating file size: {size_error}")
        _restore_from_backup(
            backup_image_path, optimized_image_path, source_image_filename
        )
        return False


def optimize_generic_image(sphinx_app=None):
    """Optimize the generic.jpg image and convert it to WebP format."""
    start_time = datetime.now()
    static_generic_image_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "static",
        "images",
        "generic.jpg",
    )

    if os.path.exists(static_generic_image_path):
        log_message(
            "info",
            "Optimizing generic image in static directory: {static_generic_image_path}",
            "general",
            "images",
        )
        optimization_success, webp_image_path = optimize_image(
            static_generic_image_path
        )
        if optimization_success and webp_image_path:
            log_message(
                "info",
                "Successfully optimized static generic image and created WebP version: {webp_image_path}",
                "general",
                "images",
            )
        else:
            log_message(
                "warning",
                f"Failed to optimize static generic image or create WebP version",
            )
    else:
        log_message(
            "warning",
            f"Generic image not found in static directory: {static_generic_image_path}",
        )

    if sphinx_app:
        try:
            rocm_blogs_instance = ROCmBlogs()
            blogs_directory = rocm_blogs_instance.find_blogs_directory(
                sphinx_app.srcdir
            )
            if blogs_directory:
                blogs_generic_image_path = os.path.join(
                    blogs_directory, "images", "generic.jpg"
                )
                if os.path.exists(blogs_generic_image_path):
                    log_message(
                        "info",
                        "Optimizing generic image in blogs directory: {blogs_generic_image_path}",
                        "general",
                        "images",
                    )
                    optimization_success, webp_image_path = optimize_image(
                        blogs_generic_image_path
                    )
                    if optimization_success and webp_image_path:
                        log_message(
                            "info",
                            "Successfully optimized blogs generic image and created WebP version: {webp_image_path}",
                            "general",
                            "images",
                        )
                    else:
                        log_message(
                            "warning",
                            f"Failed to optimize blogs generic image or create WebP version",
                        )
                else:
                    log_message(
                        "warning",
                        f"Generic image not found in blogs directory: {blogs_generic_image_path}",
                    )
        except Exception as generic_optimize_error:
            log_message(
                "warning",
                f"Error optimizing generic image in blogs directory: {generic_optimize_error}",
            )

    end_time = datetime.now()
    total_time = (end_time - start_time).total_seconds()
    total_original_kb = WEBP_CONVERSION_STATISTICS["total_size_original"] / 1024
    total_webp_kb = WEBP_CONVERSION_STATISTICS["total_size_webp"] / 1024
    size_saved_kb = total_original_kb - total_webp_kb

    log_message("info", "=" * 80, "general", "images")
    log_message("info", "IMAGE OPTIMIZATION SUMMARY", "general", "images")
    log_message("info", "-" * 80, "general", "images")
    log_message(
        "info",
        "Total WebP conversions: {WEBP_CONVERSION_STATISTICS['converted']}",
        "general",
        "images",
    )
    log_message(
        "info",
        "Total WebP conversions skipped: {WEBP_CONVERSION_STATISTICS['skipped']}",
        "general",
        "images",
    )
    log_message(
        "info",
        "Total WebP conversions failed: {WEBP_CONVERSION_STATISTICS['failed']}",
        "general",
        "images",
    )
    log_message(
        "info",
        "Total original image size: {total_original_kb:.1f} KB",
        "general",
        "images",
    )
    log_message(
        "info", f"Total WebP image size: {total_webp_kb:.1f} KB", "general", "images"
    )
    log_message(
        "info", f"Total size saved: {size_saved_kb:.1f} KB", "general", "images"
    )
    log_message(
        "info", f"Total time taken: {total_time:.2f} seconds", "general", "images"
    )
    log_message("info", "-" * 80, "general", "images")
    log_message("info", "END OF IMAGE OPTIMIZATION SUMMARY", "general", "images")
    log_message("info", "=" * 80, "general", "images")
