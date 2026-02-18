"""
Benchmark grid generation and image lookup performance.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from rocm_blogs._rocmblogs import ROCmBlogs
from rocm_blogs.blog import (
    _image_manifest_cache,
    _image_manifest_paths_cache,
    _relative_path_cache,
)
from rocm_blogs.grid import _grid_cache, generate_grid


def resolve_blogs_directory(arg_value: str | None) -> Path | None:
    if arg_value:
        return Path(arg_value).expanduser().resolve()

    package_root = Path(__file__).resolve().parent.parent
    candidates = [package_root / "blogs", package_root / "test_blogs"]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()

    return None


def clear_caches(blogs) -> None:
    _grid_cache.clear()
    _image_manifest_cache.clear()
    _image_manifest_paths_cache.clear()
    _relative_path_cache.clear()
    for blog in blogs:
        if hasattr(blog, "_image_cache"):
            blog._image_cache.clear()


def time_grab_images(rocm_blogs, blogs, iterations: int, use_cache: bool) -> float:
    timings = []
    for _ in range(iterations):
        if not use_cache:
            clear_caches(blogs)
        start = time.perf_counter()
        for blog in blogs:
            if not use_cache and hasattr(blog, "_image_cache"):
                blog._image_cache.clear()
            blog.grab_image(rocm_blogs)
        timings.append(time.perf_counter() - start)
    return sum(timings) / len(timings)


def time_generate_grid(
    rocm_blogs,
    blogs,
    iterations: int,
    use_cache: bool,
    lazy_load: bool,
    use_og: bool,
) -> float:
    timings = []
    for _ in range(iterations):
        if not use_cache:
            clear_caches(blogs)
        start = time.perf_counter()
        for blog in blogs:
            if not use_cache and hasattr(blog, "_image_cache"):
                blog._image_cache.clear()
            generate_grid(rocm_blogs, blog, lazy_load=lazy_load, use_og=use_og)
        timings.append(time.perf_counter() - start)
    return sum(timings) / len(timings)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark Blog.grab_image and grid.generate_grid performance."
    )
    parser.add_argument(
        "--blogs-dir",
        help="Path to the blogs directory containing README.md files",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=3,
        help="Number of iterations to average",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limit number of blogs to benchmark (0 = all)",
    )
    parser.add_argument(
        "--lazy-load",
        action="store_true",
        help="Enable lazy-load when benchmarking generate_grid",
    )
    parser.add_argument(
        "--use-og",
        action="store_true",
        help="Enable OpenGraph mode when benchmarking generate_grid",
    )

    args = parser.parse_args()
    blogs_directory = resolve_blogs_directory(args.blogs_dir)

    if blogs_directory is None or not blogs_directory.exists():
        print(
            "No blogs directory found. Provide one with --blogs-dir.",
            file=sys.stderr,
        )
        return 1

    rocm_blogs = ROCmBlogs()
    rocm_blogs.blogs_directory = str(blogs_directory)
    rocm_blogs.find_readme_files()

    blogs = []
    for blog_path in rocm_blogs.blog_paths:
        blog = rocm_blogs.process_blog(blog_path)
        if blog:
            blogs.append(blog)

    if args.limit:
        blogs = blogs[: args.limit]

    if not blogs:
        print("No blogs available to benchmark.", file=sys.stderr)
        return 1

    print(f"Blogs directory: {blogs_directory}")
    print(f"Blogs used: {len(blogs)}")
    print(f"Iterations: {args.iterations}")
    print(f"Grid options - lazy_load: {args.lazy_load}, use_og: {args.use_og}")
    print("-")

    clear_caches(blogs)
    grab_no_cache = time_grab_images(
        rocm_blogs, blogs, args.iterations, use_cache=False
    )
    clear_caches(blogs)
    grab_cache = time_grab_images(rocm_blogs, blogs, args.iterations, use_cache=True)

    print("Blog.grab_image")
    print(f"  without cache: {grab_no_cache:.4f}s avg")
    print(f"  with cache:    {grab_cache:.4f}s avg")

    clear_caches(blogs)
    grid_no_cache = time_generate_grid(
        rocm_blogs,
        blogs,
        args.iterations,
        use_cache=False,
        lazy_load=args.lazy_load,
        use_og=args.use_og,
    )
    clear_caches(blogs)
    grid_cache = time_generate_grid(
        rocm_blogs,
        blogs,
        args.iterations,
        use_cache=True,
        lazy_load=args.lazy_load,
        use_og=args.use_og,
    )

    print("Grid.generate_grid")
    print(f"  without cache: {grid_no_cache:.4f}s avg")
    print(f"  with cache:    {grid_cache:.4f}s avg")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
