# GitHub Pages to Notion Parser Setup

## Installation

```bash
pip install notion-client requests beautifulsoup4 lxml
```

## Notion Setup

1. **Create Notion Integration:**
   - Go to https://www.notion.so/my-integrations
   - Create new integration
   - Copy the "Internal Integration Token"

2. **Get Parent Page ID:**
   - Create or choose a parent page where databases will be created
   - Copy page ID from URL: `https://notion.so/workspace/Page-Title-{PAGE_ID}`

3. **Share Page with Integration:**
   - Open the parent page
   - Click "Share" → "Invite" → Select your integration

## Configuration

```python
# Replace these values in the main script
NOTION_TOKEN = "secret_xxxxxxxxxxxxxxxxx"  # Your integration token
PARENT_PAGE_ID = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"  # Parent page ID

# Update the find_or_create_database method:
database = self.notion.databases.create(
    parent={"type": "page_id", "page_id": PARENT_PAGE_ID},  # Use your parent page ID
    # ... rest of the code
)
```

## Usage Examples

### Basic Usage
```python
from gh_pages_parser import GitHubPagesNotionParser

# Initialize
parser = GitHubPagesNotionParser(notion_token="your_token_here")

# Sync a repository
parser.sync_repository("https://username.github.io/repository-name/")
```

### Batch Processing Multiple Repositories
```python
repositories = [
    "https://user1.github.io/ml-course/",
    "https://user2.github.io/data-science-notes/",
    "https://organization.github.io/documentation/"
]

for repo_url in repositories:
    try:
        parser.sync_repository(repo_url)
        print(f"✅ Successfully synced: {repo_url}")
    except Exception as e:
        print(f"❌ Failed to sync {repo_url}: {e}")
```

### Custom Domain Support
```python
# Works with custom domains too
parser.sync_repository("https://docs.mycompany.com/")
```

## Features

### Database Structure
Each repository creates a database with these properties:
- **Name** (Title): Page title
- **URL** (URL): Original GitHub Pages URL  
- **Last Updated** (Date): Sync timestamp
- **Content Type** (Select): Notebook/HTML Page/Index

### Content Mapping
- **Headings** (`h1-h6`) → Notion headings (max h3)
- **Paragraphs** (`p`) → Notion paragraphs  
- **Code blocks** (`pre`, `code`) → Notion code blocks
- **Images** (`img`) → Notion images
- **Lists** (`ul`, `ol`) → Notion lists

### Nesting Behavior
Pages are nested based on URL structure:
```
/                    → Root page (depth 0)
/chapter1/           → Child page (depth 1)  
/chapter1/section1/  → Grandchild page (depth 2)
```

## Customization Options

### 1. Enhanced Content Detection
```python
def is_notebook_page(self, soup: BeautifulSoup) -> bool:
    # Add more notebook detection patterns
    notebook_patterns = [
        'div[class*="jp-"]',           # JupyterLab
        'div[class*="jupyter"]',       # Classic Jupyter
        'div[class*="cell"]',          # General cell class
        'script[src*="jupyter"]',      # Jupyter scripts
    ]
    # ... implementation
```

### 2. Custom Block Conversion
```python
def element_to_notion_block(self, element) -> Optional[Dict]:
    # Add support for more HTML elements
    if tag == 'blockquote':
        return {
            "object": "block", 
            "type": "quote",
            "quote": {
                "rich_text": [{"type": "text", "text": {"content": element.get_text().strip()}}]
            }
        }
    # Add tables, callouts, dividers, etc.
```

### 3. Filtering and Exclusions
```python
def should_process_url(self, url: str) -> bool:
    # Skip certain file types or paths
    excluded_patterns = [
        r'\.pdf$', r'\.zip$', r'\.tar\.gz$',
        r'/assets/', r'/static/', r'/_site/'
    ]
    return not any(re.search(pattern, url) for pattern in excluded_patterns)
```

## Scheduling Automatic Syncs

### Using GitHub Actions
```yaml
name: Sync to Notion
on:
  schedule:
    - cron: '0 */6 * * *'  # Every 6 hours
  push:
    branches: [gh-pages]

jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Setup Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.9'
      - name: Install dependencies
        run: pip install notion-client requests beautifulsoup4
      - name: Run sync
        env:
          NOTION_TOKEN: ${{ secrets.NOTION_TOKEN }}
        run: python sync_script.py
```

### Using Cron (Linux/Mac)
```bash
# Edit crontab
crontab -e

# Add line to sync every 4 hours
0 */4 * * * /usr/bin/python3 /path/to/sync_script.py
```

## Error Handling and Monitoring

```python
import logging
import traceback

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('sync.log'),
        logging.StreamHandler()
    ]
)

# Enhanced error handling in sync method
def sync_repository(self, gh_pages_url: str):
    try:
        # ... existing sync logic
        logging.info(f"Successfully synced {gh_pages_url}")
    except requests.RequestException as e:
        logging.error(f"Network error syncing {gh_pages_url}: {e}")
    except Exception as e:
        logging.error(f"Unexpected error: {traceback.format_exc()}")
```

## Limitations and Considerations

1. **Rate Limits**: Notion API has rate limits (3 requests/second)
2. **Block Limits**: Max 100 blocks per request to Notion
3. **File Size**: Large HTML pages may need chunking
4. **Authentication**: Keep Notion tokens secure
5. **Nested Pages**: Notion has limits on nesting depth

## Next Steps

- Add support for more HTML elements
- Implement incremental syncing (only changed pages)
- Add webhook integration for real-time updates
- Create web UI for managing multiple repositories
- Add support for private repositories with GitHub tokens