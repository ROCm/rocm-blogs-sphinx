"""Emit a robots.txt carrying an explicit Content Signals policy.

Read the Docs autogenerates a permissive robots.txt when a project does not
supply one. That default carries no AI-usage preference at all, which means
the posture is an accident rather than a decision. This module writes an
explicit policy into the build output instead.

Reference: https://contentsignals.org/

Content Signals express a preference about how content may be used after it
has been fetched. They are not a licence grant and do not alter any copyright
notice rendered on the page.

Note on precedence: under robots.txt rules a crawler that finds a group
matching its own user-agent reads that group and ignores the wildcard group
entirely. Named groups must therefore repeat the full policy, which is why
each entry below is emitted with its own Content-Signal and Allow lines.
"""

from pathlib import Path

from .logger.logger import log_message

# Overridable from conf.py via the `rocm_blogs_content_signal` config value.
# Set to an empty string to disable robots.txt emission entirely.
DEFAULT_CONTENT_SIGNAL = "search=yes, ai-input=yes, ai-train=yes"

# Crawlers named explicitly so the policy is unambiguous for each operator
# rather than relying on the wildcard group. Overridable from conf.py via
# `rocm_blogs_named_crawlers`; set to an empty list to emit only the wildcard
# group. Grouped by operator for readability.
DEFAULT_NAMED_CRAWLERS = (
    # OpenAI
    "GPTBot",
    "OAI-SearchBot",
    "ChatGPT-User",
    # Anthropic
    "ClaudeBot",
    "Claude-User",
    "Claude-SearchBot",
    "anthropic-ai",
    # Google
    "Google-Extended",
    # Common Crawl
    "CCBot",
    # Perplexity
    "PerplexityBot",
    "Perplexity-User",
    # Meta
    "meta-externalagent",
    # Apple
    "Applebot-Extended",
    # Amazon
    "Amazonbot",
    # ByteDance
    "Bytespider",
    # Others
    "cohere-ai",
    "DuckAssistBot",
    "YouBot",
    "Diffbot",
    "ImagesiftBot",
    "Timpibot",
    "Omgilibot",
)

_HEADER = """# AMD ROCm Blogs
# Content Signals Policy - https://contentsignals.org/
#
# search   : indexing and linking, excluding AI-generated summaries
# ai-input : retrieval, grounding, RAG at inference time
# ai-train : training and fine-tuning
#
# These are preference signals under a published convention. They are not
# a licence grant and do not alter the copyright notice on each page.
#
# A crawler that matches a named group below ignores the wildcard group
# entirely, so each named group repeats the full policy.

User-agent: *
Content-Signal: {signal}
Allow: /
"""

_NAMED_GROUP = """
User-agent: {agent}
Content-Signal: {signal}
Allow: /
"""

_FOOTER = """
Sitemap: {sitemap}
"""


def _resolve_sitemap_url(app) -> str:
    """Derive the sitemap URL from blog_baseurl, falling back to a relative path."""
    baseurl = (getattr(app.config, "blog_baseurl", "") or "").strip().rstrip("/")
    if not baseurl:
        return "sitemap.xml"
    if not baseurl.startswith(("http://", "https://")):
        baseurl = f"https://{baseurl}"
    return f"{baseurl}/sitemap.xml"


def _render(signal: str, crawlers, sitemap: str) -> str:
    """Render the full robots.txt body."""
    parts = [_HEADER.format(signal=signal)]
    seen = set()
    for agent in crawlers or ():
        agent = str(agent).strip()
        # Skip blanks, a redundant wildcard, and case-insensitive duplicates.
        if not agent or agent == "*" or agent.lower() in seen:
            continue
        seen.add(agent.lower())
        parts.append(_NAMED_GROUP.format(agent=agent, signal=signal))
    parts.append(_FOOTER.format(sitemap=sitemap))
    return "".join(parts)


def write_robots_txt(app, exception) -> None:
    """Write robots.txt into the HTML output directory on build-finished.

    No-ops when the build failed, when the builder is not an HTML builder,
    when the signal is configured empty, or when the project already supplied
    its own robots.txt (for example via html_extra_path).
    """
    if exception is not None:
        return

    builder_format = getattr(getattr(app, "builder", None), "format", None)
    if builder_format != "html":
        return

    signal = getattr(app.config, "rocm_blogs_content_signal", DEFAULT_CONTENT_SIGNAL)
    if not signal:
        log_message(
            "info",
            "rocm_blogs_content_signal is empty; skipping robots.txt emission",
            "robots",
            "extension",
        )
        return

    target = Path(app.outdir) / "robots.txt"
    if target.exists():
        log_message(
            "info",
            "robots.txt already present in build output; leaving project copy in place",
            "robots",
            "extension",
        )
        return

    crawlers = getattr(app.config, "rocm_blogs_named_crawlers", DEFAULT_NAMED_CRAWLERS)
    content = _render(signal, crawlers, _resolve_sitemap_url(app))

    try:
        target.write_text(content, encoding="utf-8")
        log_message(
            "info",
            f"Wrote robots.txt with Content-Signal: {signal} "
            f"({len(crawlers or ())} named crawler groups)",
            "robots",
            "extension",
        )
    except OSError as error:
        # Never fail a docs build over robots.txt.
        log_message(
            "warning",
            f"Could not write robots.txt: {error}",
            "robots",
            "extension",
        )
