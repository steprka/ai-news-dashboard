#!/usr/bin/env python3
"""
Daily news updater for AI News Dashboard.
Uses Claude API with web search to research and summarize REAL AI news from the last 24 hours,
with strict allowlisting of trusted sources.
"""

import anthropic
import re
import json
import os
import sys
from datetime import datetime
from urllib.parse import urlparse

HISTORY_FILE = os.path.join(os.path.dirname(__file__), "headline_history.json")
DEBUG_DIR = os.path.join(os.path.dirname(__file__), "..", "debug")

# Allowlist of trusted news source domains.
ALLOWED_DOMAINS = {
    # Tier 1 — wire services & legacy press
    "reuters.com", "apnews.com", "bloomberg.com", "wsj.com", "nytimes.com",
    "ft.com", "economist.com", "washingtonpost.com",

    # Reputable tech press
    "theverge.com", "techcrunch.com", "wired.com", "arstechnica.com",
    "technologyreview.com",
    "theinformation.com", "axios.com", "404media.co",

    # Major broadcasters / additional reputable general news
    "bbc.com", "bbc.co.uk", "cnbc.com", "cnn.com", "theguardian.com",
    "forbes.com", "businessinsider.com", "fortune.com", "semafor.com",

    # AI lab & major company blogs
    "openai.com", "anthropic.com", "deepmind.google", "deepmind.com",
    "ai.meta.com", "ai.googleblog.com", "blog.google", "research.google",
    "microsoft.com", "blogs.microsoft.com", "nvidia.com", "blogs.nvidia.com",
    "apple.com", "machinelearning.apple.com", "amazon.science", "aboutamazon.com",
    "huggingface.co", "mistral.ai", "x.ai", "perplexity.ai",

    # Research & academic
    "arxiv.org", "nature.com", "science.org",

    # Official government & policy
    "whitehouse.gov", "europa.eu", "ec.europa.eu", "gov.uk", "congress.gov",
    "ftc.gov", "sec.gov", "nist.gov", "commerce.gov",
}


def load_headline_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            return json.load(f)
    return []


def save_headline_history(headlines):
    history = load_headline_history()
    history.extend(headlines)
    history = history[-50:]
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f)


def get_date_info():
    now = datetime.now()
    return {
        "weekday": now.strftime("%A"),
        "month": now.strftime("%B"),
        "day": now.strftime("%d"),
        "year": now.strftime("%Y"),
        "full": now.strftime("%A, %B %d, %Y"),
        "iso": now.strftime("%Y-%m-%d"),
    }


def domain_is_allowed(url):
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return False
    host = host.lower().lstrip(".")
    if host.startswith("www."):
        host = host[4:]
    for allowed in ALLOWED_DOMAINS:
        if host == allowed or host.endswith("." + allowed):
            return True
    return False


def filter_sections_by_allowlist(sections):
    cleaned = []
    for section in sections:
        valid_sources = [s for s in section.get("sources", []) if domain_is_allowed(s.get("url", ""))]
        if len(valid_sources) < 1:
            print(f"  ✗ Dropping '{section.get('headline', '?')}' — no allowlisted sources")
            continue
        section["sources"] = valid_sources
        cleaned.append(section)
    return cleaned


def extract_json(text):
    """
    Extract a JSON object from a string that might contain surrounding prose
    or markdown code fences. Returns the parsed dict, or raises with diagnostic info.
    """
    if not text:
        raise ValueError("Empty response from Claude.")

    cleaned = text.strip()

    # Strip markdown code fences if present
    if cleaned.startswith("```"):
        cleaned = re.sub(r'^```(?:json)?\s*\n?', '', cleaned)
        cleaned = re.sub(r'\n?```\s*$', '', cleaned)
        cleaned = cleaned.strip()

    # Try parsing the cleaned text directly
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Fall back: find the first balanced { ... } block in the text
    # This handles cases where Claude added a preamble or postscript.
    start = cleaned.find("{")
    if start == -1:
        raise ValueError("No JSON object found in Claude's response.")

    depth = 0
    in_string = False
    escape = False
    for i, ch in enumerate(cleaned[start:], start=start):
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = cleaned[start:i + 1]
                return json.loads(candidate)

    raise ValueError("Could not find a balanced JSON object in Claude's response.")


def save_debug_response(text, label):
    """Write Claude's raw response to a debug file for inspection on parse failure."""
    try:
        os.makedirs(DEBUG_DIR, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = os.path.join(DEBUG_DIR, f"{timestamp}-{label}.txt")
        with open(path, "w") as f:
            f.write(text or "<empty>")
        print(f"  Raw response saved to {path}")
        return path
    except Exception as e:
        print(f"  (could not save debug file: {e})")
        return None


def generate_news_content(client, date_info, previous_headlines):
    avoid_section = ""
    if previous_headlines:
        avoid_section = (
            "ALREADY-COVERED HEADLINES (do not repeat or use close variations):\n"
            + "\n".join(f"- {h}" for h in previous_headlines[-30:])
            + "\n"
        )

    sources_text = """TRUSTED SOURCE ALLOWLIST — every source URL MUST be from one of these domains:

Tier 1 news:
- reuters.com, apnews.com, bloomberg.com, wsj.com, nytimes.com,
  ft.com, economist.com, washingtonpost.com

Reputable tech press:
- theverge.com, techcrunch.com, wired.com, arstechnica.com,
  technologyreview.com (MIT Tech Review), theinformation.com,
  axios.com, 404media.co

Major broadcasters & general news:
- bbc.com, cnbc.com, cnn.com, theguardian.com, forbes.com,
  businessinsider.com, fortune.com, semafor.com

AI lab and major company blogs (primary sources):
- openai.com, anthropic.com, deepmind.google, ai.meta.com,
  blog.google, research.google, microsoft.com, blogs.microsoft.com,
  nvidia.com, machinelearning.apple.com, huggingface.co,
  mistral.ai, x.ai, amazon.science

Research & academic:
- arxiv.org, nature.com, science.org

Government & policy:
- whitehouse.gov, europa.eu, gov.uk, congress.gov, ftc.gov,
  sec.gov, nist.gov, commerce.gov

If a story only appears on outlets NOT on this list, treat it as if you didn't find it."""

    prompt = f"""You are a news researcher for a personal AI news dashboard. Today is {date_info['full']}.

Your job: Use the web_search tool to find REAL AI industry news published in the LAST 24 HOURS, then summarize the best stories into the sections below.

CRITICAL RULES:
1. ONLY use real news from real articles you find via web search. Never invent stories, quotes, numbers, companies, or actions.
2. ONLY include stories published within the last 48 hours from {date_info['full']}. Skip anything older.
3. Every source URL MUST be a real, working URL from one of the allowlisted domains below. URLs from any other domain are NOT permitted, no matter how relevant the story.
4. If you cannot find a genuine, allowlisted, <48hr story for a section, OMIT that section entirely. A shorter dashboard with real news is far better than a fuller one with stale, fabricated, or low-quality sources.
5. Summarize in your own words. Do not reproduce article wording. If you must quote, keep quotes under 15 words and clearly attributed; prefer paraphrasing.

{sources_text}

{avoid_section}
SECTIONS TO FILL (in this order, ONLY include sections where you found a real <24hr story from an allowlisted source):
1. "What's Hot" — The biggest AI story of the day
2. "What's Contentious" — AI controversies, ethics debates, lawsuits, backlash
3. "UX Challenges" — AI user experience issues, product problems, design failures
4. "The Discourse" — Notable AI debates among researchers, executives, or in major commentary
5. "Money Moves" — AI funding, acquisitions, market moves, earnings
6. "Policy Alert" — AI regulation, government actions, legal developments
7. "New Tools" — New AI products, features, model releases
8. "Research, Translated" — AI research papers/breakthroughs explained simply

For each section you include, write:
- A compelling headline (under 80 chars)
- Exactly 3 paragraphs, each starting with <strong>Label:</strong>
- 2-3 source links from the allowlist

OUTPUT FORMAT — EXTREMELY IMPORTANT:
Your final message must contain ONLY a single valid JSON object — nothing else. No preamble like "Here are today's stories." No markdown fences. No commentary after. Just the raw JSON, starting with {{ and ending with }}.

The JSON must follow this exact structure:

{{
  "sections": [
    {{
      "label": "What's Hot",
      "headline": "Real headline based on actual reporting",
      "paragraphs": [
        "<strong>What happened:</strong> First paragraph in your own words.",
        "<strong>Why it matters:</strong> Second paragraph.",
        "<strong>What's next:</strong> Third paragraph."
      ],
      "sources": [
        {{"name": "Reuters", "url": "https://www.reuters.com/technology/..."}},
        {{"name": "Bloomberg", "url": "https://www.bloomberg.com/news/articles/..."}}
      ]
    }}
  ]
}}

Remember: it is far better to return 3 real, well-sourced sections than 8 fabricated or weakly-sourced ones."""

    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=16000,
        tools=[{
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": 15,
        }],
        messages=[{"role": "user", "content": prompt}]
    )

    text_blocks = [b.text for b in response.content if b.type == "text"]
    if not text_blocks:
        raise RuntimeError("Claude returned no text content after web search.")

    # Use the LAST text block — that's the final answer after any tool use rounds.
    text = text_blocks[-1]

    # Also save full conversation in case the JSON is in an earlier text block
    full_text = "\n\n---BLOCK---\n\n".join(text_blocks)

    return text, full_text


def build_card_html(section, collapsed=False):
    collapsed_class = ' collapsed' if collapsed else ''
    paragraphs_html = "\n                    ".join(
        f"<p>{p}</p>" for p in section["paragraphs"]
    )
    sources_html = ", ".join(
        f'<a href="{s["url"]}" target="_blank" rel="noopener noreferrer">{s["name"]}</a>'
        for s in section["sources"]
    )
    return f'''            <div class="card{collapsed_class}" onclick="this.classList.toggle('collapsed')">
                <div class="card-label">{section["label"]}</div>
                <h3>{section["headline"]}</h3>
                <div class="card-content">
                    {paragraphs_html}
                </div>
                <div class="card-source">{sources_html}</div>
            </div>'''


def update_index_html(date_info, sections):
    with open("index.html", "r") as f:
        html = f.read()

    date_pattern = r'<span id="date-text">[^<]+</span>'
    new_date = f'<span id="date-text">{date_info["weekday"]}, {date_info["month"]} {date_info["day"]}, {date_info["year"]}</span>'
    html = re.sub(date_pattern, new_date, html)

    if not sections:
        raise RuntimeError("No sections survived allowlist filtering — refusing to wipe the dashboard.")

    cards_html = []
    for i, section in enumerate(sections):
        collapsed = i >= 4
        cards_html.append(build_card_html(section, collapsed))

    cards_pattern = r'(<!-- What\'s Hot -->).*?(</div>\s*</div>\s*</div>\s*</body>)'
    all_cards = "\n\n".join(cards_html)
    replacement = f'<!-- What\'s Hot -->\n{all_cards}\n        </div>\n    </div>\n</body>'
    html = re.sub(cards_pattern, replacement, html, flags=re.DOTALL)

    with open("index.html", "w") as f:
        f.write(html)

    print(f"Updated index.html for {date_info['full']} with {len(sections)} sections")


def main():
    client = anthropic.Anthropic()
    date_info = get_date_info()

    previous_headlines = load_headline_history()
    print(f"Loaded {len(previous_headlines)} previous headlines to avoid")

    print(f"Researching real AI news for {date_info['full']}...")
    final_text, full_text = generate_news_content(client, date_info, previous_headlines)

    print(f"Got response (final block: {len(final_text)} chars, total text: {len(full_text)} chars)")

    # Try to parse JSON from the final text block first, then fall back to full text
    try:
        data = extract_json(final_text)
    except (ValueError, json.JSONDecodeError) as e:
        print(f"  Couldn't parse final block: {e}")
        print("  Trying full response text...")
        try:
            data = extract_json(full_text)
        except (ValueError, json.JSONDecodeError) as e2:
            print(f"  Full text also failed: {e2}")
            save_debug_response(full_text, "parse-failure")
            print("\n--- First 500 chars of response ---")
            print(full_text[:500])
            print("--- Last 500 chars of response ---")
            print(full_text[-500:])
            sys.exit(1)

    raw_sections = data.get("sections", [])
    print(f"Claude returned {len(raw_sections)} sections; filtering against allowlist...")

    sections = filter_sections_by_allowlist(raw_sections)
    print(f"  → {len(sections)} sections passed the allowlist filter")

    print("Updating index.html...")
    update_index_html(date_info, sections)

    new_headlines = [s["headline"] for s in sections]
    save_headline_history(new_headlines)
    print(f"Saved {len(new_headlines)} new headlines to history")

    print("Done!")


if __name__ == "__main__":
    main()
