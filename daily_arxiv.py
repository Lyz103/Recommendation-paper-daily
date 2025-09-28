import os
import re
import json
import arxiv
import yaml
import logging
import argparse
import datetime
from pathlib import Path  # Use pathlib for modern, object-oriented path handling

# --- Basic Configuration ---
logging.basicConfig(
    format='[%(asctime)s %(levelname)s] %(message)s',
    datefmt='%m/%d/%Y %H:%M:%S',
    level=logging.INFO
)
ARXIV_URL_PREFIX = "http://arxiv.org/abs/"

# --- Helper Functions ---

def get_authors(authors: list[arxiv.Result.Author], first_author: bool = False) -> str:
    """Returns a formatted string of author names."""
    if first_author:
        return str(authors[0])
    return ", ".join(str(author) for author in authors)

def sort_papers_by_id(papers: dict) -> dict:
    """Sorts a dictionary of papers by their keys (paper_id) in reverse chronological order."""
    return dict(sorted(papers.items(), reverse=True))

# --- Core Logic ---

def load_config(config_file: Path) -> dict:
    """Loads, parses, and returns the YAML configuration."""
    if not config_file.exists():
        logging.error(f"Configuration file not found at: {config_file}")
        exit() # Or raise an exception

    with open(config_file, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f) # Use safe_load for security

    # REFACTORED: Simplified query building
    # The original "pretty_filters" was complex. A simple join is often sufficient.
    # The arxiv library can handle advanced queries directly if needed.
    keyword_queries = {}
    for key, value in config.get('keywords', {}).items():
        # Join filters with " OR ", quoting multi-word phrases
        query_parts = [f'"{f}"' if ' ' in f else f for f in value['filters']]
        keyword_queries[key] = " OR ".join(query_parts)

    config['keyword_queries'] = keyword_queries
    logging.info(f"Configuration loaded: {config}")
    return config

def get_daily_papers(topic: str, query: str, max_results: int) -> dict:
    """
    Searches arXiv for papers based on a query and returns a dictionary of found papers.

    REFACTORED:
    - Fixed the critical bug where no papers were being saved.
    - Simplified the title filtering logic.
    - Now stores paper data in a structured dictionary instead of a pipe-delimited string.
    """
    papers = {}
    search = arxiv.Search(
        query=query,
        max_results=max_results,
        sort_by=arxiv.SortCriterion.SubmittedDate
    )

    for result in search.results():
        # REFACTORED: More efficient and case-insensitive filtering
        title_lower = result.title.lower()
        if "recommendation" not in title_lower:
            continue

        paper_id = result.get_short_id()
        # The arxiv library already strips the version, but this is safe
        paper_key = paper_id.split('v')[0]
        
        logging.info(f"Found Paper: title='{result.title}', author='{get_authors(result.authors, True)}'")

        # REFACTORED: Store data in a structured dictionary for robustness
        papers[paper_key] = {
            "title": result.title,
            "authors": get_authors(result.authors),
            "first_author": get_authors(result.authors, first_author=True),
            "url": result.entry_id,
            "pdf_url": f"{ARXIV_URL_PREFIX}{paper_key}",
            "publish_date": result.published.date().isoformat(),
            "abstract": result.summary.replace("\n", " "),
            "primary_category": result.primary_category,
            "code_url": "null" # Placeholder for code link
        }
        
    return {topic: papers}


def update_json_file(filename: Path, new_data: dict):
    """Loads a JSON file, updates it with new data, and saves it."""
    try:
        with open(filename, "r", encoding='utf-8') as f:
            content = f.read()
            json_data = json.loads(content) if content else {}
    except FileNotFoundError:
        json_data = {}

    for topic, papers in new_data.items():
        if topic not in json_data:
            json_data[topic] = {}
        json_data[topic].update(papers)

    with open(filename, "w", encoding='utf-8') as f:
        json.dump(json_data, f, indent=4)


def json_to_md(json_file: Path, md_file: Path, **kwargs):
    """
    Generates a Markdown file from a JSON file containing paper data.
    """
    to_web = kwargs.get('to_web', False)
    use_title = kwargs.get('use_title', True)
    use_tc = kwargs.get('use_tc', True)
    show_badge = kwargs.get('show_badge', True)
    use_b2t = kwargs.get('use_b2t', True)

    try:
        with open(json_file, "r", encoding='utf-8') as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}

    date_now = datetime.date.today().strftime("%Y-%m-%d")
    
    with open(md_file, "w", encoding='utf-8') as f:
        # --- Header and Badges ---
        if to_web and use_title:
            f.write("---\nlayout: default\n---\n\n")
        
        # ... (Badge writing logic) ...

        if use_title:
            f.write(f"## Updated on {date_now}\n")
        else:
            f.write(f"> Updated on {date_now}\n")
        
        # --- Table of Contents ---
        if use_tc and data:
            f.write("<details>\n <summary>Table of Contents</summary>\n <ol>\n")
            for topic in data:
                if data[topic]:
                    f.write(f"    <li><a href=#{topic.replace(' ', '-').lower()}>{topic}</a></li>\n")
            f.write(" </ol>\n</details>\n\n")

        # --- Paper Tables ---
        for topic, papers in data.items():
            if not papers:
                continue
            
            f.write(f"## {topic}\n\n")
            
            header = "| Publish Date | Title | Authors | PDF | Code |\n"
            separator = "|:---|:---|:---|:---|:---|\n"
            f.write(header + separator)

            sorted_papers = sort_papers_by_id(papers)
            
            for paper_id, details in sorted_papers.items():
                
                # FIX: Check if the 'details' object is a dictionary before processing.
                # This handles old, string-formatted data gracefully.
                if not isinstance(details, dict):
                    logging.warning(f"Skipping malformed (old format) entry for paper_id: {paper_id}")
                    continue

                pub_date = details.get('publish_date', 'N/A')
                title = details.get('title', 'N/A').replace("|", "\\|")
                authors = details.get('authors', 'N/A')
                pdf_url = details.get('pdf_url', '#')
                code_url = details.get('code_url', 'null')
                
                code_link = f"[{paper_id}]({code_url})" if code_url != "null" else "Not Available"
                pdf_link = f"[Link]({pdf_url})"
                
                f.write(f"| {pub_date} | **{title}** | {authors} | {pdf_link} | {code_link} |\n")

            f.write("\n")
            
            if use_b2t:
                f.write(f"<p align=right>(<a href=\"#\">back to top</a>)</p>\n\n")

    logging.info(f"Markdown file '{md_file}' updated successfully.")

# REFACTORED: New function to handle publication targets to avoid repetition.
def process_publication_target(target_name: str, config: dict, data_collector: list):
    """Helper function to process a single output target (readme, gitpage, etc.)."""
    json_path = Path(config[f'json_{target_name}_path'])
    md_path = Path(config[f'md_{target_name}_path'])
    
    # 1. Update the JSON database
    for data in data_collector:
        update_json_file(json_path, data)

    # 2. Convert JSON to Markdown with appropriate settings
    md_options = {
        'to_web': target_name == 'gitpage',
        'use_title': target_name != 'wechat',
        'use_tc': target_name == 'readme',
        'show_badge': config.get('show_badge', True),
        'use_b2t': target_name != 'gitpage'
    }
    json_to_md(json_path, md_path, **md_options)
    logging.info(f"Successfully processed target: {target_name}")


def main(**config):
    """Main execution function."""
    data_collector = []
    
    # --- Step 1: Fetch new papers ---
    logging.info("Starting daily paper fetching...")
    for topic, query in config.get('keyword_queries', {}).items():
        logging.info(f"Searching for topic: '{topic}' with query: '{query}'")
        papers_data = get_daily_papers(
            topic=topic,
            query=query,
            max_results=config.get('max_results', 2)
        )
        if papers_data.get(topic): # Only add if papers were found
            data_collector.append(papers_data)
    logging.info("Finished fetching papers.")

    # --- Step 2: Update publication targets ---
    # REFACTORED: Replaced duplicated 'if' blocks with a loop and a helper function.
    publication_targets = {
        'readme': config.get('publish_readme'),
        'gitpage': config.get('publish_gitpage'),
        'wechat': config.get('publish_wechat')
    }
    
    for target, should_publish in publication_targets.items():
        if should_publish:
            process_publication_target(target, config, data_collector)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Automated arXiv paper tracker.")
    parser.add_argument(
        '--config',
        type=Path,
        default=Path('config.yaml'),
        help='Path to the configuration YAML file.'
    )
    # The 'update_paper_links' argument seems to be for a separate maintenance task.
    # It's better handled as a distinct script or a separate command.
    # For this refactoring, its logic is removed in favor of the more robust data pipeline.
    
    args = parser.parse_args()
    config = load_config(args.config)
    main(**config)