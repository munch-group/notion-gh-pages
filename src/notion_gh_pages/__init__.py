import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import re
from notion_client import Client
import time
from typing import Dict, List, Optional, Set

class GitHubPagesNotionParser:
    def __init__(self, notion_token: str):
        self.notion = Client(auth=notion_token)
        self.processed_urls: Set[str] = set()
        self.page_mapping: Dict[str, str] = {}  # URL -> Notion page ID
        
    def parse_repository_name(self, gh_pages_url: str) -> str:
        """Extract repository name from GitHub Pages URL"""
        # Handle both username.github.io/repo and custom domains
        parsed = urlparse(gh_pages_url)
        if 'github.io' in parsed.netloc:
            # Format: username.github.io/repository-name
            path_parts = parsed.path.strip('/').split('/')
            if path_parts and path_parts[0]:
                return path_parts[0]
            else:
                # If no path, use the subdomain (username.github.io)
                return parsed.netloc.split('.')[0]
        else:
            # Custom domain - use domain name
            return parsed.netloc.replace('.', '-')
    
    def find_or_create_database(self, repo_name: str) -> str:
        """Find existing database or create new one"""
        database_name = f"{repo_name}-gh-pages"
        
        # Search for existing database
        try:
            search_results = self.notion.search(query=database_name)
            for result in search_results.get('results', []):
                if (result['object'] == 'database' and 
                    result.get('title', [{}])[0].get('plain_text', '') == database_name):
                    print(f"Found existing database: {database_name}")
                    return result['id']
        except Exception as e:
            print(f"Search error: {e}")
        
        # Create new database
        print(f"Creating new database: {database_name}")
        database = self.notion.databases.create(
            parent={"type": "page_id", "page_id": "YOUR_PARENT_PAGE_ID"},  # Replace with actual parent
            title=[{"type": "text", "text": {"content": database_name}}],
            properties={
                "Name": {"title": {}},
                "URL": {"url": {}},
                "Last Updated": {"date": {}},
                "Content Type": {
                    "select": {
                        "options": [
                            {"name": "Notebook", "color": "blue"},
                            {"name": "HTML Page", "color": "green"},
                            {"name": "Index", "color": "purple"}
                        ]
                    }
                }
            }
        )
        return database['id']
    
    def crawl_gh_pages(self, base_url: str) -> Dict[str, Dict]:
        """Crawl GitHub Pages site and build page structure"""
        pages = {}
        to_visit = [base_url]
        
        while to_visit:
            current_url = to_visit.pop(0)
            if current_url in self.processed_urls:
                continue
                
            self.processed_urls.add(current_url)
            print(f"Crawling: {current_url}")
            
            try:
                response = requests.get(current_url, timeout=10)
                response.raise_for_status()
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Extract page info
                page_info = self.extract_page_info(soup, current_url, base_url)
                pages[current_url] = page_info
                
                # Find links to other pages in the same domain
                links = self.find_internal_links(soup, current_url, base_url)
                for link in links:
                    if link not in self.processed_urls:
                        to_visit.append(link)
                        
            except Exception as e:
                print(f"Error crawling {current_url}: {e}")
                continue
        
        return pages
    
    def extract_page_info(self, soup: BeautifulSoup, url: str, base_url: str) -> Dict:
        """Extract page information and content"""
        # Get page title
        title_elem = soup.find('title')
        title = title_elem.text.strip() if title_elem else self.url_to_title(url)
        
        # Determine content type
        content_type = "HTML Page"
        if "ipynb" in url.lower() or self.is_notebook_page(soup):
            content_type = "Notebook"
        elif url == base_url or url.endswith('/'):
            content_type = "Index"
        
        # Extract main content
        content_blocks = self.html_to_notion_blocks(soup)
        
        # Calculate depth for nesting
        path = urlparse(url).path.strip('/')
        depth = len([p for p in path.split('/') if p]) if path else 0
        
        return {
            'title': title,
            'url': url,
            'content_type': content_type,
            'content_blocks': content_blocks,
            'depth': depth,
            'path': path
        }
    
    def is_notebook_page(self, soup: BeautifulSoup) -> bool:
        """Check if page appears to be a Jupyter notebook"""
        # Look for common notebook indicators
        notebook_indicators = [
            '.jp-Notebook',
            '.jupyter-notebook',
            'div[class*="cell"]',
            'div[class*="input"]',
            'div[class*="output"]'
        ]
        
        for indicator in notebook_indicators:
            if soup.select(indicator):
                return True
        return False
    
    def find_internal_links(self, soup: BeautifulSoup, current_url: str, base_url: str) -> List[str]:
        """Find internal links to crawl"""
        links = []
        base_domain = urlparse(base_url).netloc
        
        for link in soup.find_all('a', href=True):
            href = link['href']
            
            # Convert relative URLs to absolute
            full_url = urljoin(current_url, href)
            parsed = urlparse(full_url)
            
            # Only include links from same domain
            if parsed.netloc == base_domain:
                # Clean URL (remove fragments, query params)
                clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                if clean_url not in links and clean_url != current_url:
                    links.append(clean_url)
        
        return links
    
    def html_to_notion_blocks(self, soup: BeautifulSoup) -> List[Dict]:
        """Convert HTML content to Notion blocks"""
        blocks = []
        
        # Find main content area (try common containers)
        main_content = (
            soup.find('main') or 
            soup.find('div', class_=re.compile(r'content|main|body', re.I)) or
            soup.find('article') or
            soup.body
        )
        
        if not main_content:
            return blocks
        
        # Process elements
        for element in main_content.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'pre', 'code', 'img', 'table', 'ul', 'ol']):
            block = self.element_to_notion_block(element)
            if block:
                blocks.append(block)
        
        return blocks
    
    def element_to_notion_block(self, element) -> Optional[Dict]:
        """Convert HTML element to Notion block"""
        tag = element.name.lower()
        
        if tag in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
            level = min(int(tag[1]), 3)  # Notion only supports h1-h3
            return {
                "object": "block",
                "type": f"heading_{level}",
                f"heading_{level}": {
                    "rich_text": [{"type": "text", "text": {"content": element.get_text().strip()}}]
                }
            }
        
        elif tag == 'p':
            text = element.get_text().strip()
            if text:
                return {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"type": "text", "text": {"content": text}}]
                    }
                }
        
        elif tag == 'pre' or (tag == 'code' and element.parent.name != 'pre'):
            code_text = element.get_text()
            # Try to detect language
            language = "plain text"
            if 'python' in element.get('class', []) or 'language-python' in element.get('class', []):
                language = "python"
            elif 'javascript' in element.get('class', []):
                language = "javascript"
            
            return {
                "object": "block",
                "type": "code",
                "code": {
                    "rich_text": [{"type": "text", "text": {"content": code_text}}],
                    "language": language
                }
            }
        
        elif tag == 'img':
            src = element.get('src')
            if src:
                return {
                    "object": "block",
                    "type": "image",
                    "image": {
                        "type": "external",
                        "external": {"url": src}
                    }
                }
        
        return None
    
    def url_to_title(self, url: str) -> str:
        """Convert URL to readable title"""
        path = urlparse(url).path.strip('/')
        if not path:
            return "Home"
        
        # Get last part of path and clean it up
        title = path.split('/')[-1]
        title = title.replace('.html', '').replace('.ipynb', '')
        title = title.replace('-', ' ').replace('_', ' ')
        return title.title()
    
    def create_or_update_notion_pages(self, database_id: str, pages: Dict[str, Dict]):
        """Create or update Notion pages with proper nesting"""
        # Sort pages by depth to create parents first
        sorted_pages = sorted(pages.items(), key=lambda x: x[1]['depth'])
        
        for url, page_info in sorted_pages:
            try:
                # Check if page exists
                existing_page = self.find_existing_page(database_id, url)
                
                if existing_page:
                    print(f"Updating existing page: {page_info['title']}")
                    self.update_notion_page(existing_page['id'], page_info)
                else:
                    print(f"Creating new page: {page_info['title']}")
                    new_page = self.create_notion_page(database_id, page_info)
                    self.page_mapping[url] = new_page['id']
                
                # Rate limiting
                time.sleep(0.3)
                
            except Exception as e:
                print(f"Error processing {url}: {e}")
    
    def find_existing_page(self, database_id: str, url: str) -> Optional[Dict]:
        """Find existing page by URL"""
        try:
            query_result = self.notion.databases.query(
                database_id=database_id,
                filter={
                    "property": "URL",
                    "url": {"equals": url}
                }
            )
            
            if query_result['results']:
                return query_result['results'][0]
        except Exception as e:
            print(f"Error searching for existing page: {e}")
        
        return None
    
    def create_notion_page(self, database_id: str, page_info: Dict) -> Dict:
        """Create new Notion page"""
        properties = {
            "Name": {"title": [{"text": {"content": page_info['title']}}]},
            "URL": {"url": page_info['url']},
            "Last Updated": {"date": {"start": "2024-01-01"}},  # Replace with actual date
            "Content Type": {"select": {"name": page_info['content_type']}}
        }
        
        # Create page
        page = self.notion.pages.create(
            parent={"database_id": database_id},
            properties=properties
        )
        
        # Add content blocks
        if page_info['content_blocks']:
            self.notion.blocks.children.append(
                block_id=page['id'],
                children=page_info['content_blocks'][:100]  # Notion limit
            )
        
        return page
    
    def update_notion_page(self, page_id: str, page_info: Dict):
        """Update existing Notion page"""
        # Update properties
        self.notion.pages.update(
            page_id=page_id,
            properties={
                "Name": {"title": [{"text": {"content": page_info['title']}}]},
                "Last Updated": {"date": {"start": "2024-01-01"}},  # Replace with actual date
                "Content Type": {"select": {"name": page_info['content_type']}}
            }
        )
        
        # Clear existing content and add new
        existing_blocks = self.notion.blocks.children.list(block_id=page_id)
        for block in existing_blocks['results']:
            self.notion.blocks.delete(block_id=block['id'])
        
        # Add new content
        if page_info['content_blocks']:
            self.notion.blocks.children.append(
                block_id=page_id,
                children=page_info['content_blocks'][:100]  # Notion limit
            )
    
    def sync_repository(self, gh_pages_url: str):
        """Main method to sync GitHub Pages to Notion"""
        print(f"Starting sync for: {gh_pages_url}")
        
        # Extract repository name and setup database
        repo_name = self.parse_repository_name(gh_pages_url)
        database_id = self.find_or_create_database(repo_name)
        
        # Crawl and parse pages
        print("Crawling GitHub Pages...")
        pages = self.crawl_gh_pages(gh_pages_url)
        print(f"Found {len(pages)} pages")
        
        # Create/update Notion pages
        print("Syncing to Notion...")
        self.create_or_update_notion_pages(database_id, pages)
        
        print("Sync completed!")

# Usage example
if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('sync.log'),
            logging.StreamHandler()
        ]
    )
    
    # Initialize parser
    try:
        parser = GitHubPagesNotionParser(notion_token="your_notion_token_here")
        
        # Sync a repository
        gh_pages_url = "https://username.github.io/repository-name/"
        parser.sync_repository(gh_pages_url)
        
    except Exception as e:
        logger.error(f"Failed to initialize or run parser: {e}", exc_info=True)