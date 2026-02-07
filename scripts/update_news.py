#!/usr/bin/env python3
"""
Daily news updater for AI News Dashboard.
Uses Claude API to research and generate fresh AI news content.
"""

import anthropic
import re
from datetime import datetime

def get_date_info():
    """Get formatted date information."""
    now = datetime.now()
    return {
        "weekday": now.strftime("%A"),
        "month": now.strftime("%B"),
        "day": now.strftime("%d"),
        "year": now.strftime("%Y"),
        "full": now.strftime("%A, %B %d, %Y")
    }

def generate_news_content(client, date_info):
    """Use Claude to generate fresh news content."""

    prompt = f"""You are writing content for a personal AI news dashboard. Today's date is {date_info['full']}.

Create engaging, realistic-sounding AI industry news summaries for 8 sections. This is creative content for a personal dashboard - write plausible scenarios about AI developments, funding, policy, and research that could realistically happen. Each section needs:
- A compelling headline (under 80 chars)
- 3 paragraphs, each starting with <strong>Label:</strong> (e.g., "The deal:", "Why it matters:", "The backlash:")
- 2-3 placeholder source links with major publication names (use # as URL)

CRITICAL: Generate completely fresh content each time. Never reuse the same storylines, companies, or scenarios. Be creative and vary the topics, players, and angles.

SECTIONS:
1. What's Hot - The biggest AI story today
2. What's Contentious - AI controversies, ethics debates, backlash
3. UX Challenges - AI user experience, design challenges, product issues
4. The Discourse - What's trending on X/Twitter about AI, hot takes, debates between AI leaders
5. Money Moves - AI funding, acquisitions, market moves, stock news
6. Policy Alert - AI regulation, government actions, legal developments
7. New Tools - New AI products, features, model releases
8. Research, Translated - AI research breakthroughs explained simply

Return ONLY valid JSON in this exact format (no markdown, no code blocks):
{{
  "sections": [
    {{
      "label": "What's Hot",
      "headline": "Headline here",
      "paragraphs": [
        "<strong>The deal:</strong> First paragraph content here.",
        "<strong>Why it matters:</strong> Second paragraph content here.",
        "<strong>The signal:</strong> Third paragraph content here."
      ],
      "sources": [
        {{"name": "Bloomberg", "url": "#"}},
        {{"name": "TechCrunch", "url": "#"}}
      ]
    }}
  ]
}}

Make content specific, varied, and engaging."""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=8000,
        messages=[{"role": "user", "content": prompt}]
    )

    text = response.content[0].text
    # Strip markdown code blocks if present
    if text.startswith("```"):
        text = re.sub(r'^```(?:json)?\n?', '', text)
        text = re.sub(r'\n?```$', '', text)
    return text.strip()

def build_card_html(section, collapsed=False):
    """Build HTML for a single card."""
    collapsed_class = ' collapsed' if collapsed else ''

    paragraphs_html = "\n                    ".join(
        f"<p>{p}</p>" for p in section["paragraphs"]
    )

    sources_html = ", ".join(
        f'<a href="{s["url"]}">{s["name"]}</a>' for s in section["sources"]
    )

    return f'''            <div class="card{collapsed_class}" onclick="this.classList.toggle('collapsed')">
                <div class="card-label">{section["label"]}</div>
                <h3>{section["headline"]}</h3>
                <div class="card-content">
                    {paragraphs_html}
                </div>
                <div class="card-source">{sources_html}</div>
            </div>'''

def update_index_html(date_info, sections_data):
    """Update the index.html file with new content."""

    with open("index.html", "r") as f:
        html = f.read()

    # Update date
    date_pattern = r'<span id="date-text">[^<]+</span>'
    new_date = f'<span id="date-text">{date_info["weekday"]}, {date_info["month"]} {date_info["day"]}, {date_info["year"]}</span>'
    html = re.sub(date_pattern, new_date, html)

    # Build all cards HTML
    import json
    data = json.loads(sections_data)

    cards_html = []
    for i, section in enumerate(data["sections"]):
        # First 4 sections expanded, last 4 collapsed
        collapsed = i >= 4
        cards_html.append(build_card_html(section, collapsed))

    # Find and replace all cards section
    cards_pattern = r'(<!-- What\'s Hot -->).*?(</div>\s*</div>\s*</div>\s*</body>)'

    all_cards = "\n\n".join(cards_html)
    replacement = f'<!-- What\'s Hot -->\n{all_cards}\n        </div>\n    </div>\n</body>'

    html = re.sub(cards_pattern, replacement, html, flags=re.DOTALL)

    with open("index.html", "w") as f:
        f.write(html)

    print(f"Updated index.html for {date_info['full']}")

def main():
    client = anthropic.Anthropic()
    date_info = get_date_info()

    print(f"Generating news for {date_info['full']}...")
    news_content = generate_news_content(client, date_info)

    print("Updating index.html...")
    update_index_html(date_info, news_content)

    print("Done!")

if __name__ == "__main__":
    main()
