#!/usr/bin/env python3
"""
llms.txt Generator — Creates and validates llms.txt files for AI crawler guidance.

llms.txt is reported as a forward-looking, low-confidence signal — NOT a
current ranking or citation lever (see skills/seo-geo/references/llmstxt-evidence.md).
Generation is gated by the aeo.llmstxt_mode config flag: audit | generate | off.
This module must refuse to generate anything when mode == "off".

Location: /llms.txt (root of domain)
Extended: /llms-full.txt (detailed version)
"""

import sys
import json
import re
import os
from urllib.parse import urljoin, urlparse

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("ERROR: Required packages not installed. Run: pip install -r requirements.txt")
    sys.exit(1)

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)
from fetch_page import fetch_page  # noqa: E402


class LlmsTxtGenerationDisabledError(RuntimeError):
    """Raised when generate_llmstxt() is called while aeo.llmstxt_mode == 'off'."""


def validate_llmstxt(url: str) -> dict:
    """Check if llms.txt exists and validate its format. Always allowed,
    even under mode == 'off' — auditing presence is not the same as
    generating new files."""
    parsed = urlparse(url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    llms_url = f"{base_url}/llms.txt"
    llms_full_url = f"{base_url}/llms-full.txt"

    result = {
        "url": llms_url,
        "exists": False,
        "format_valid": False,
        "has_title": False,
        "has_description": False,
        "has_sections": False,
        "has_links": False,
        "section_count": 0,
        "link_count": 0,
        "content": "",
        "issues": [],
        "suggestions": [],
        "full_version": {"url": llms_full_url, "exists": False},
    }

    fetched = fetch_page(llms_url)
    if not fetched["error"] and fetched["status_code"] == 200:
        result["exists"] = True
        content = fetched["content"] or ""
        result["content"] = content
        lines = content.strip().split("\n")

        if lines and lines[0].startswith("# "):
            result["has_title"] = True
        else:
            result["issues"].append("Missing title (should start with '# Site Name')")

        for line in lines:
            if line.startswith("> "):
                result["has_description"] = True
                break
        if not result["has_description"]:
            result["issues"].append("Missing description (use '> Brief description')")

        sections = [l for l in lines if l.startswith("## ")]
        result["section_count"] = len(sections)
        result["has_sections"] = len(sections) > 0
        if not result["has_sections"]:
            result["issues"].append("No sections found (use '## Section Name')")

        link_pattern = r"- \[.+\]\(.+\)"
        links = re.findall(link_pattern, content)
        result["link_count"] = len(links)
        result["has_links"] = len(links) > 0
        if not result["has_links"]:
            result["issues"].append("No page links found (use '- [Page Title](url): Description')")

        result["format_valid"] = (
            result["has_title"]
            and result["has_description"]
            and result["has_sections"]
            and result["has_links"]
        )

        if result["link_count"] < 5:
            result["suggestions"].append("Consider adding more key pages (aim for 10-20)")
        if result["section_count"] < 2:
            result["suggestions"].append("Add more sections to organize content types")
        if "contact" not in content.lower():
            result["suggestions"].append("Add a Contact section with email and location")
        if "key fact" not in content.lower() and "about" not in content.lower():
            result["suggestions"].append("Add key facts about your business/service")
    elif fetched["error"]:
        result["issues"].append(f"Error fetching llms.txt: {fetched['error']}")
    else:
        result["issues"].append(f"llms.txt returned status {fetched['status_code']}")

    full_fetched = fetch_page(llms_full_url)
    if not full_fetched["error"] and full_fetched["status_code"] == 200:
        result["full_version"]["exists"] = True

    return result


def generate_llmstxt(url: str, max_pages: int = 30, mode: str = "generate") -> dict:
    """Generate an llms.txt file by crawling the site.

    Raises LlmsTxtGenerationDisabledError if mode == 'off' — the caller
    (skills/seo-geo router) is responsible for passing the current
    aeo.llmstxt_mode config value through.
    """
    if mode == "off":
        raise LlmsTxtGenerationDisabledError(
            "llms.txt generation is disabled (aeo.llmstxt_mode = off). "
            "Set aeo.llmstxt_mode to 'generate' to enable."
        )

    parsed = urlparse(url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"

    result = {
        "generated_llmstxt": "",
        "generated_llmstxt_full": "",
        "pages_analyzed": 0,
        "sections": {},
    }

    homepage = fetch_page(url)
    if homepage["error"] or not homepage["content"]:
        result["error"] = f"Failed to fetch homepage: {homepage['error'] or 'empty response'}"
        return result

    soup = BeautifulSoup(homepage["content"], "lxml")

    title = soup.find("title")
    site_name = title.get_text(strip=True).split("|")[0].split("-")[0].strip() if title else parsed.netloc
    meta_desc = soup.find("meta", attrs={"name": "description"})
    site_description = meta_desc.get("content", "") if meta_desc else f"Official website of {site_name}"

    pages = {
        "Main Pages": [],
        "Products & Services": [],
        "Resources & Blog": [],
        "Company": [],
        "Support": [],
    }

    seen_urls = set()
    for link in soup.find_all("a", href=True):
        href = urljoin(base_url, link["href"])
        link_text = link.get_text(strip=True)

        if not link_text or len(link_text) < 2:
            continue
        parsed_href = urlparse(href)
        if parsed_href.netloc != parsed.netloc:
            continue
        if href in seen_urls:
            continue
        if any(ext in href for ext in [".pdf", ".jpg", ".png", ".gif", ".css", ".js"]):
            continue
        if "#" in href and href.split("#")[0] in seen_urls:
            continue

        seen_urls.add(href)
        path = parsed_href.path.lower()
        page_entry = {"url": href, "title": link_text}

        if any(kw in path for kw in ["/pricing", "/feature", "/product", "/solution", "/demo"]):
            pages["Products & Services"].append(page_entry)
        elif any(kw in path for kw in ["/blog", "/article", "/resource", "/guide", "/learn", "/docs", "/documentation"]):
            pages["Resources & Blog"].append(page_entry)
        elif any(kw in path for kw in ["/about", "/team", "/career", "/contact", "/press", "/partner"]):
            pages["Company"].append(page_entry)
        elif any(kw in path for kw in ["/help", "/support", "/faq", "/status"]):
            pages["Support"].append(page_entry)
        elif path in ["/", ""] or any(kw in path for kw in ["/home", "/index"]):
            if href != base_url and href != base_url + "/":
                pages["Main Pages"].append(page_entry)
        else:
            pages["Main Pages"].append(page_entry)

        if len(seen_urls) >= max_pages:
            break

    result["pages_analyzed"] = len(seen_urls)

    llms_lines = [f"# {site_name}", f"> {site_description}", ""]
    for section, section_pages in pages.items():
        if section_pages:
            llms_lines.append(f"## {section}")
            for page in section_pages[:10]:
                llms_lines.append(f"- [{page['title']}]({page['url']})")
            llms_lines.append("")
    llms_lines.extend([
        "## Contact",
        f"- Website: {base_url}",
        f"- Email: contact@{parsed.netloc}",
        "",
    ])
    result["generated_llmstxt"] = "\n".join(llms_lines)

    full_lines = [f"# {site_name}", f"> {site_description}", ""]
    for section, section_pages in pages.items():
        if section_pages:
            full_lines.append(f"## {section}")
            for page in section_pages:
                if urlparse(page["url"]).netloc != parsed.netloc:
                    full_lines.append(f"- [{page['title']}]({page['url']})")
                    continue
                page_fetched = fetch_page(page["url"], timeout=10)
                if not page_fetched["error"] and page_fetched["content"]:
                    page_soup = BeautifulSoup(page_fetched["content"], "lxml")
                    page_meta = page_soup.find("meta", attrs={"name": "description"})
                    page_desc = page_meta.get("content", "") if page_meta else ""
                    if page_desc:
                        full_lines.append(f"- [{page['title']}]({page['url']}): {page_desc}")
                    else:
                        full_lines.append(f"- [{page['title']}]({page['url']})")
                else:
                    full_lines.append(f"- [{page['title']}]({page['url']})")
            full_lines.append("")
    full_lines.extend([
        "## Contact",
        f"- Website: {base_url}",
        f"- Email: contact@{parsed.netloc}",
        "",
    ])
    result["generated_llmstxt_full"] = "\n".join(full_lines)
    result["sections"] = {k: len(v) for k, v in pages.items()}

    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python llmstxt_generator.py <url> [mode] [aeo_llmstxt_mode]")
        print("Modes: validate (default), generate")
        print("aeo_llmstxt_mode: audit | generate | off (default: generate)")
        sys.exit(1)

    target_url = sys.argv[1]
    cli_mode = sys.argv[2] if len(sys.argv) > 2 else "validate"
    aeo_mode = sys.argv[3] if len(sys.argv) > 3 else "generate"

    if cli_mode == "validate":
        data = validate_llmstxt(target_url)
    elif cli_mode == "generate":
        try:
            data = generate_llmstxt(target_url, mode=aeo_mode)
        except LlmsTxtGenerationDisabledError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        print(f"Unknown mode: {cli_mode}. Use 'validate' or 'generate'.")
        sys.exit(1)

    print(json.dumps(data, indent=2, default=str))
