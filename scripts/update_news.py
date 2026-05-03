#!/usr/bin/env python3
"""
Daily news updater for AI News Dashboard.
Uses Claude API with web search to research and summarize REAL AI news from the last 48 hours,
with strict allowlisting of trusted sources. Also fetches NYC weather from National Weather Service.
"""

import anthropic
import re
import json
import os
import sys
import urllib.request
from datetime import datetime
from urllib.parse import urlparse

HISTORY_FILE = os.path.join(os.path.dirname(__file__), "headline_history.json")
DEBUG_DIR = os.path.join(os.path.dirname(__file__), "..", "debug")

NWS_FORECAST_URL = "https://api.weather.gov/gridpoints/OKX/33,37/forecast"
NWS_USER_AGENT = "ai-news-dashboard (steprka.github.io)"

ALLOWED_DOMAINS = {
    "reuters.com", "apnews.com", "bloomberg.com", "wsj.com", "nytimes.com",
    "ft.com", "economist.com", "washingtonpost.com",
    "theverge.com", "techcrunch.com", "wired.com", "arstechnica.com",
    "technologyreview.com", "theinformation.com", "axios.com", "404media.co",
    "bbc.com", "bbc.co.uk", "cnbc.com", "cnn.com", "theguardian.com",
    "forbes.com", "businessinsider.com", "fortune.com", "semafor.com",
    "openai.com", "anthropic.com", "deepmind.google", "deepmind.com",
    "ai.meta.com", "ai.googleblog.com", "blog.google", "research.google",
    "microsoft.com", "blogs.microsoft.com", "nvidia.com", "blogs.nvidia.com",
    "apple.com", "machinelearning.apple.com", "amazon.science", "aboutamazon.com",
    "huggingface.co", "mistral.ai", "x.ai", "perplexity.ai",
    "arxiv.org", "nature.com", "science.org",
    "whitehouse.gov", "europa.eu", "ec.europa.eu", "gov.uk", "congress.gov",
    "ftc.gov", "sec.gov", "nist.gov", "commerce.gov",
}


def fetch_nyc_temperature():
    try:
        req = urllib.request.Request(
            NWS_FORECAST_URL,
            headers={"User-Agent": NWS_USER_AGENT, "Accept": "application/geo+json"},
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
        period = data["properties"]["periods"][0]
        temp = period["temperature"]
        unit = period.get("temperatureUnit", "F")
        if unit == "C":
            temp = round(temp * 9 / 5 + 32)
        print(f"  NWS reports NYC: {temp}F ({period.get('shortForecast', '')})")
        return int(temp)
    except Exception as e:
        print(f"  Weather fetch failed: {e}")
        return None


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
            print(f"  Dropping '{section.get('headline', '?')}' - no allowlisted sources")
            continue
        section["sources"] = valid_sources
        cleaned.append(section)
    return cleaned


def extract_json(text):
    if not text:
        raise ValueError("Empty response from Claude.")
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r'^```(?:json)?\s*\n?', '', cleaned)
        cleaned = re.sub(r'\n?```\s*$', '', cleaned)
        cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    start = cleaned.find("{")
    if start == -1:
        raise ValueError("No JSON object found.")
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
                return json.loads(cleaned[start:i + 1])
    raise ValueError("Unbalanced JSON.")


def generate_news_content(client, date_info, previous_headlines):
    avoid_section = ""
    if previous_headlines:
        avoid_section = "ALREADY-COVERED HEADLINES (do not repeat):\n" + "\n".join(f"- {h}" for h in previous_headlines[-30:]) + "\n"

    sources_text = "TRUSTED SOURCE ALLOWLIST (only use these domains): " + ", ".join(sorted(ALLOWED_DOMAINS))

    prompt = f"""You are a news researcher for a personal AI news dashboard. Today is {date_info['full']}.

Use the web_search tool to find REAL AI industry news published in the LAST 48 HOURS, then summarize the best stories into the sections below.

CRITICAL RULES:
1. ONLY use real news from real articles you find via web search. Never invent.
2. ONLY include stories published within the last 48 hours.
3. Every source URL MUST be from one of the allowlisted domains below. No exceptions.
4. If you cannot find a genuine, allowlisted, <48hr story for a section, OMIT that section entirely.
5. Summarize in your own words. No long quotes.

{sources_text}

{avoid_section}
SECTIONS (only include sections where you found a real <48hr story from an allowlisted source):
1. "What's Hot" - The biggest AI story of the day
2. "What's Contentious" - AI controversies, ethics, lawsuits
3. "UX Challenges" - AI product/UX issues
4. "The Discourse" - Notable AI debates among researchers/execs
5. "Money Moves" - AI funding, M&A, market moves
6. "Policy Alert" - AI regulation, legal developments
7. "New Tools" - New AI products, model releases
8. "Research, Translated" - AI research papers explained simply

For each section: a headline (under 80 chars), exactly 3 paragraphs each starting with <strong>Label:</strong>, and 2-3 source links from the allowlist.

OUTPUT: Return ONLY a single valid JSON object - no preamble, no fences, no commentary. Just raw JSON like:

{{
  "sections": [
    {{
      "label": "What's Hot",
      "headline": "Real headline",
      "paragraphs": ["<strong>What happened:</strong> ...", "<strong>Why it matters:</strong> ...", "<strong>What's next:</strong> ..."],
      "sources": [{{"name": "Reuters", "url": "https://www.reuters.com/..."}}]
    }}
  ]
}}

Better to return 3 real well-sourced sections than 8 fabricated ones."""

    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=16000,
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 15}],
        messages=[{"role": "user", "content": prompt}]
    )
    text_blocks = [b.text for b in response.content if b.type == "text"]
    if not text_blocks:
        raise RuntimeError("Claude returned no text.")
    return text_blocks[-1], "\n\n---\n\n".join(text_blocks)


def build_card_html(section, collapsed=False):
    collapsed_class = ' collapsed' if collapsed else ''
    paragraphs_html = "\n                    ".join(f"<p>{p}</p>" for p in section["paragraphs"])
    sources_html = ", ".join(f'<a href="{s["url"]}" target="_blank" rel="noopener noreferrer">{s["name"]}</a>' for s in section["sources"])
    return f'''            <div class="card{collapsed_class}" onclick="this.classList.toggle('collapsed')">
                <div class="card-label">{section["label"]}</div>
                <h3>{section["headline"]}</h3>
                <div class="card-content">
                    {paragraphs_html}
                </div>
                <div class="card-source">{sources_html}</div>
            </div>'''


def update_index_html(date_info, sections, temperature):
    with open("index.html", "r") as f:
        html = f.read()
    date_pattern = r'<span id="date-text">[^<]+</span>'
    new_date = f'<span id="date-text">{date_info["weekday"]}, {date_info["month"]} {date_info["day"]}, {date_info["year"]}</span>'
    html = re.sub(date_pattern, new_date, html)
    if temperature is not None:
        temp_pattern = r'<span id="temperature">[^<]+</span>'
        new_temp = f'<span id="temperature">{temperature}&deg;F</span>'
        new_html, count = re.subn(temp_pattern, new_temp, html)
        if count == 0:
            print("  Could not find temperature span in index.html.")
        else:
            html = new_html
            print(f"  Temperature updated to {temperature}F")
    if not sections:
        raise RuntimeError("No sections survived filtering - refusing to wipe dashboard.")
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
    print(f"Updated index.html with {len(sections)} sections")


def main():
    client = anthropic.Anthropic()
    date_info = get_date_info()
    previous_headlines = load_headline_history()
    print(f"Loaded {len(previous_headlines)} previous headlines")
    print("Fetching NYC weather from National Weather Service...")
    temperature = fetch_nyc_temperature()
    print(f"Researching real AI news for {date_info['full']}...")
    final_text, full_text = generate_news_content(client, date_info, previous_headlines)
    print(f"Got response ({len(final_text)} chars)")
    try:
        data = extract_json(final_text)
    except (ValueError, json.JSONDecodeError) as e:
        print(f"  Final block parse failed: {e}, trying full text...")
        data = extract_json(full_text)
    raw_sections = data.get("sections", [])
    print(f"Claude returned {len(raw_sections)} sections; filtering...")
    sections = filter_sections_by_allowlist(raw_sections)
    print(f"  -> {len(sections)} passed allowlist")
    print("Updating index.html...")
    update_index_html(date_info, sections, temperature)
    new_headlines = [s["headline"] for s in sections]
    save_headline_history(new_headlines)
    print(f"Saved {len(new_headlines)} new headlines")
    print("Done!")


if __name__ == "__main__":
    main()
