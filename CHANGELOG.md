# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

## [v1.13.5] - 2026-02-19

### Fixed
- Removed hash-based image filename rewriting and aligned grid/blog page image resolution to deterministic non-hashed `_images` paths so both surfaces reference the same generated asset.
- Fixed blog page hero thumbnail behavior to enforce WebP-only resolution/conversion (no `.png`/`.jpg` fallback), matching grid thumbnail output expectations.
- Fixed author-page grid cards to resolve stale/internal `og:image` links through the same grid image pipeline so updated `_images` paths are used consistently.
- Enforced WebP-only image links on author-page grids by re-resolving internal and non-WebP `og:image` values through the canonical `_images/*.webp` pipeline.

## [v1.13.3] - 2026-02-09

### Fixed
- Fixed grid thumbnails still rendering with unhashed `_images/...` paths by enforcing hash conversion unless the `_images` filename is already hash-suffixed.

## [v1.13.2] - 2026-02-09

### Fixed
- Fixed grid thumbnails not appearing by improving hashed image and WebP resolution for grid card images.

## [v1.13.1] - 2026-02-08

### Added
- Grid card images are now clickable via the card link.
- Added `.gitignore` for Python bytecode and `__pycache__` artifacts.
- Added commit message checks (commitlint + Commitizen) in GitHub workflows.
- Added Python formatting and linting workflow (Black, isort, Ruff).

### Changed
- Grid layout updated to a more compact presentation:
  - Date moved to the top of the card content.
  - Title and description styling updated to be more prominent.
  - Spacing and card dimensions refined for tighter layout.
  - Card image height reduced and card height made flexible.
  - Card borders/shadows tuned for a cleaner look.
- Image optimization defaults adjusted for better size/quality balance:
  - `WEBP_QUALITY` set to 85.
  - `WEBP_CONSERVATIVE_QUALITY` set to 90.
  - JPEG quality set to 85 in `FORMAT_SETTINGS`.
- Grid lazy-loading now respects the `lazy_load` argument instead of always enabling it.
- Development tooling configured for Black/isort/Ruff formatting and linting.

### Removed
- Author attribution from grid cards.
