import os
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import re
from notion_client import Client
import time
from typing import Dict, List, Optional, Set

class GitHubPagesNotionParser:
    def __init__(self, notion_token: str, parent_page_id: Optional[str] = None, max_pages: int = 100):
        self.notion = Client(auth=notion_token)
        self.parent_page_id = parent_page_id
        self.processed_urls: Set[str] = set()
        self.page_mapping: Dict[str, str] = {}  # URL -> Notion page ID
        self.max_pages = max_pages  # Limit crawling to avoid infinite loops
        
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
    
    def get_or_create_parent_page(self) -> str:
        """Get parent page ID or create a workspace page"""
        if self.parent_page_id:
            # Verify the page exists and is accessible
            try:
                page = self.notion.pages.retrieve(page_id=self.parent_page_id)
                return self.parent_page_id
            except Exception as e:
                print(f"Warning: Could not access parent page {self.parent_page_id}: {e}")
        
        # Search for or create a default parent page
        default_page_name = "GitHub Pages Sync"
        try:
            search_results = self.notion.search(query=default_page_name, filter={"value": "page", "property": "object"})
            for result in search_results.get('results', []):
                if result['object'] == 'page' and not result.get('archived', False):
                    print(f"Using existing parent page: {default_page_name}")
                    return result['id']
        except Exception as e:
            print(f"Search error: {e}")
        
        # If we can't find or create a parent page, we'll need to use workspace as parent
        raise ValueError(
            "No valid parent page found. Please either:\n"
            "1. Set NOTION_PARENT_PAGE_ID environment variable with a valid page ID\n"
            "2. Create a page called 'GitHub Pages Sync' in your Notion workspace\n"
            "3. Ensure your integration has access to at least one page in your workspace"
        )
    
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

        # Get parent page ID
        try:
            parent_id = self.get_or_create_parent_page()
        except ValueError as e:
            print(f"Error: {e}")
            # Try to create database at workspace level
            print("Attempting to create database at workspace level...")
            parent_id = None
        
        # Create new database
        print(f"Creating new database: {database_name}")
        
        # Determine parent based on what we have
        if parent_id:
            parent = {"type": "page_id", "page_id": parent_id}
        else:
            # Try workspace level - this requires special permissions
            parent = {"type": "workspace", "workspace": True}
        
        try:
            database = self.notion.databases.create(
                parent=parent,
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
        except Exception as e:
            print(f"Failed to create database: {e}")
            raise ValueError(
                f"Could not create database. Error: {e}\n"
                "Please ensure:\n"
                "1. Your Notion integration has the correct permissions\n"
                "2. You have shared at least one page with your integration\n"
                "3. Your NOTION_TOKEN is valid\n"
            )
    
    def crawl_gh_pages(self, base_url: str) -> Dict[str, Dict]:
        """Crawl GitHub Pages site and build page structure"""
        pages = {}
        to_visit = [base_url]
        
        # Handle redirects by following them
        try:
            initial_response = requests.get(base_url, timeout=10, allow_redirects=True)
            actual_base_url = initial_response.url
            if actual_base_url != base_url:
                print(f"Following redirect: {base_url} -> {actual_base_url}")
                base_url = actual_base_url
                to_visit = [actual_base_url]
        except Exception as e:
            print(f"Error accessing base URL: {e}")
            return pages
        
        while to_visit and len(self.processed_urls) < self.max_pages:
            current_url = to_visit.pop(0)
            if current_url in self.processed_urls:
                continue
                
            self.processed_urls.add(current_url)
            print(f"Crawling: {current_url}")
            
            try:
                # Skip non-HTML files
                if any(current_url.endswith(ext) for ext in ['.pdf', '.zip', '.tar', '.gz', '.jpg', '.png', '.gif']):
                    print(f"  Skipping non-HTML file: {current_url}")
                    continue
                
                response = requests.get(current_url, timeout=10, allow_redirects=True)
                response.raise_for_status()
                
                # Check content type
                content_type = response.headers.get('content-type', '')
                if 'text/html' not in content_type and 'application/xhtml' not in content_type:
                    print(f"  Skipping non-HTML content: {content_type}")
                    continue
                
                # Update URL if redirected
                final_url = response.url
                if final_url != current_url:
                    print(f"  Redirected to: {final_url}")
                    if final_url in self.processed_urls:
                        continue
                    self.processed_urls.add(final_url)
                    current_url = final_url
                
                # Parse HTML with better error handling
                try:
                    soup = BeautifulSoup(response.content, 'html.parser')
                except Exception as parse_error:
                    print(f"  Error parsing HTML: {parse_error}")
                    continue
                
                # Check for JavaScript redirects
                script_redirects = self.find_javascript_redirects(soup, current_url)
                if script_redirects:
                    print(f"  Found JavaScript redirects: {script_redirects}")
                    for redirect in script_redirects:
                        if redirect not in self.processed_urls:
                            to_visit.append(redirect)
                
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
        
        if len(self.processed_urls) >= self.max_pages:
            print(f"Reached maximum page limit ({self.max_pages}). Stopping crawl.")
        
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
        
        # Extract main content with URL context for images
        content_blocks = self.html_to_notion_blocks(soup, url)
        
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
        
        # Also find links in navigation, sidebar, etc.
        link_elements = soup.find_all('a', href=True)
        
        # Look for common navigation patterns
        nav_areas = soup.find_all(['nav', 'aside']) + soup.find_all(class_=re.compile(r'sidebar|menu|navigation|nav', re.I))
        for area in nav_areas:
            link_elements.extend(area.find_all('a', href=True))
        
        # Process all found links
        seen_urls = set()
        for link in link_elements:
            href = link['href']
            
            # Skip anchors, mailto, javascript links
            if href.startswith('#') or href.startswith('mailto:') or href.startswith('javascript:'):
                continue
            
            # Convert relative URLs to absolute
            full_url = urljoin(current_url, href)
            parsed = urlparse(full_url)
            
            # Only include links from same domain
            if parsed.netloc == base_domain:
                # Clean URL (remove fragments only, keep useful query params)
                clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                if parsed.query:
                    # Keep query params that might represent different pages
                    clean_url += f"?{parsed.query}"
                
                # Normalize trailing slashes
                if clean_url.endswith('/') and len(clean_url) > 1:
                    clean_url = clean_url.rstrip('/')
                
                if clean_url not in seen_urls and clean_url != current_url:
                    seen_urls.add(clean_url)
                    links.append(clean_url)
        
        print(f"  Found {len(links)} internal links")
        return links
    
    def find_javascript_redirects(self, soup: BeautifulSoup, current_url: str) -> List[str]:
        """Find JavaScript-based redirects in the page"""
        redirects = []
        
        # Look for redirect patterns in script tags
        for script in soup.find_all('script'):
            if not script.string:
                continue
                
            # Pattern 1: var redirects = {...}
            if 'var redirects' in script.string:
                # Extract redirect URLs from JavaScript object
                # Look for patterns like "pages/getting_started.html"
                url_pattern = r'["\']([^"\'\\\n]+\.html?)["\']'
                matches = re.findall(url_pattern, script.string)
                for match in matches:
                    if not match.startswith('http'):
                        full_url = urljoin(current_url, match)
                        redirects.append(full_url)
            
            # Pattern 2: window.location.replace or window.location.href
            if 'window.location' in script.string:
                # Look for direct URL assignments
                url_pattern = r'window\.location(?:\.href|\.replace)?\s*[=\(]\s*["\']([^"\'\\\n]+)["\']'
                matches = re.findall(url_pattern, script.string)
                for match in matches:
                    if not match.startswith('http') and not match == '/':
                        full_url = urljoin(current_url, match)
                        redirects.append(full_url)
        
        # Also check for meta refresh tags
        meta_refresh = soup.find('meta', attrs={'http-equiv': 'refresh'})
        if meta_refresh and meta_refresh.get('content'):
            content = meta_refresh['content']
            # Extract URL from content like "0; URL=..."
            parts = content.split('URL=', 1)
            if len(parts) == 2:
                redirect_url = parts[1].strip()
                if not redirect_url.startswith('http'):
                    redirect_url = urljoin(current_url, redirect_url)
                redirects.append(redirect_url)
        
        return list(set(redirects))  # Remove duplicates
    
    def html_to_notion_blocks(self, soup: BeautifulSoup, page_url: str) -> List[Dict]:
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
        
        # Process elements (limit to first 50 for performance)
        # Include div for math blocks
        elements = main_content.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'pre', 'img', 'div', 'table', 'ul', 'ol'])[:50]
        for element in elements:
            # Skip elements that have already been processed as children
            # Skip code elements entirely - they'll be handled within pre or p tags
            if element.name == 'code':
                continue
            # Skip divs that are inside other processed elements
            if element.name == 'div' and element.parent.name in ['pre', 'p']:
                continue
            
            block = self.element_to_notion_block(element, page_url)
            if block:
                blocks.append(block)
                if len(blocks) >= 20:  # Limit blocks per page
                    break
        
        return blocks
    
    def element_to_notion_block(self, element, page_url: str) -> Optional[Dict]:
        """Convert HTML element to Notion block"""
        tag = element.name.lower()
        
        if tag in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
            level = min(int(tag[1]), 3)  # Notion only supports h1-h3
            rich_text = self.parse_rich_text(element)
            return {
                "object": "block",
                "type": f"heading_{level}",
                f"heading_{level}": {
                    "rich_text": rich_text
                }
            }
        
        elif tag == 'p':
            rich_text = self.parse_rich_text(element)
            if rich_text:
                return {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": rich_text
                    }
                }
        
        elif tag == 'pre':
            # Code block
            code_elem = element.find('code') or element
            code_text = code_elem.get_text()
            
            # Try to detect language from class
            language = "plain text"
            classes = code_elem.get('class', []) if code_elem != element else element.get('class', [])
            for cls in classes:
                if 'language-' in cls:
                    language = cls.replace('language-', '')
                    break
            
            return {
                "object": "block",
                "type": "code",
                "code": {
                    "rich_text": [{"type": "text", "text": {"content": code_text}}],
                    "language": language
                }
            }
        
        elif tag == 'div':
            # Check if it's a math block
            classes = element.get('class', [])
            if any('math' in str(c).lower() or 'katex' in str(c).lower() or 'mathjax' in str(c).lower() for c in classes):
                # Try to extract math equation
                latex = self.extract_latex(element)
                if latex:
                    return {
                        "object": "block",
                        "type": "equation",
                        "equation": {
                            "expression": latex
                        }
                    }
            # Otherwise treat as regular paragraph
            rich_text = self.parse_rich_text(element)
            if rich_text:
                return {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": rich_text
                    }
                }
        
        elif tag == 'img':
            src = element.get('src')
            if src:
                # Convert relative URLs to absolute
                if not src.startswith('http'):
                    src = urljoin(page_url, src)
                return {
                    "object": "block",
                    "type": "image",
                    "image": {
                        "type": "external",
                        "external": {"url": src}
                    }
                }
        
        return None
    
    def parse_rich_text(self, element) -> List[Dict]:
        """Parse HTML element into Notion rich text format"""
        rich_text = []
        
        # Check if element contains math
        math_elements = element.find_all(['math', 'span'], class_=re.compile(r'math|katex|MathJax', re.I))
        if math_elements:
            for math_elem in math_elements:
                # Try to extract LaTeX from different formats
                latex = self.extract_latex(math_elem)
                if latex:
                    # Replace the math element with a placeholder
                    placeholder = f"[MATH:{latex}]"
                    math_elem.string = placeholder
        
        def process_node(node):
            if hasattr(node, 'name') and node.name:
                # It's an HTML element
                if node.name in ['strong', 'b']:
                    # Bold text
                    text_content = node.get_text()
                    if text_content:
                        rich_text.append({
                            "type": "text",
                            "text": {"content": text_content},
                            "annotations": {"bold": True}
                        })
                elif node.name in ['em', 'i']:
                    # Italic text
                    text_content = node.get_text()
                    if text_content:
                        rich_text.append({
                            "type": "text",
                            "text": {"content": text_content},
                            "annotations": {"italic": True}
                        })
                elif node.name == 'code':
                    # Inline code
                    text_content = node.get_text()
                    if text_content:
                        rich_text.append({
                            "type": "text",
                            "text": {"content": text_content},
                            "annotations": {"code": True}
                        })
                elif node.name == 'br':
                    # Line break
                    rich_text.append({
                        "type": "text",
                        "text": {"content": "\n"}
                    })
                elif node.name == 'a':
                    # Link
                    href = node.get('href', '')
                    text_content = node.get_text()
                    if text_content:
                        if href and not href.startswith('#'):
                            # Skip relative URLs that Notion can't handle
                            if href.startswith('http') or href.startswith('mailto:'):
                                rich_text.append({
                                    "type": "text",
                                    "text": {
                                        "content": text_content,
                                        "link": {"url": href}
                                    }
                                })
                            else:
                                # For relative links, just show text
                                rich_text.append({
                                    "type": "text",
                                    "text": {"content": text_content}
                                })
                        else:
                            rich_text.append({
                                "type": "text",
                                "text": {"content": text_content}
                            })
                else:
                    # Process children of other elements
                    if hasattr(node, 'children'):
                        for child in node.children:
                            process_node(child)
            else:
                # It's a text node
                text = str(node)
                if text:
                    # Preserve newlines and handle markdown-style line breaks
                    # Don't strip text to preserve formatting
                    rich_text.append({
                        "type": "text",
                        "text": {"content": text}
                    })
        
        # Process all children of the element
        for child in element.children:
            process_node(child)
        
        # If no rich text was found, fall back to plain text
        if not rich_text:
            text = element.get_text()
            if text:
                rich_text.append({
                    "type": "text",
                    "text": {"content": text}
                })
        
        # Post-process to handle math placeholders
        processed_rich_text = []
        for item in rich_text:
            if item.get('type') == 'text' and '[MATH:' in item['text']['content']:
                # Split text by math placeholders and create equation blocks
                parts = re.split(r'\[MATH:(.*?)\]', item['text']['content'])
                for i, part in enumerate(parts):
                    if i % 2 == 0:
                        # Regular text
                        if part:
                            processed_rich_text.append({
                                "type": "text",
                                "text": {"content": part}
                            })
                    else:
                        # Math equation
                        processed_rich_text.append({
                            "type": "equation",
                            "equation": {"expression": part}
                        })
            else:
                processed_rich_text.append(item)
        
        return processed_rich_text
    
    def extract_latex(self, math_elem) -> Optional[str]:
        """Extract LaTeX from various math element formats"""
        # Try data attributes first
        latex = math_elem.get('data-latex') or math_elem.get('data-formula')
        if latex:
            return latex
        
        # Check for annotation elements (MathML)
        annotation = math_elem.find('annotation', attrs={'encoding': 'application/x-tex'})
        if annotation:
            return annotation.get_text()
        
        # Check for script tags with tex
        script = math_elem.find('script', attrs={'type': re.compile(r'math/tex', re.I)})
        if script:
            return script.get_text()
        
        # Try to extract from class names or text content
        text = math_elem.get_text()
        if text and ('$' in text or '\\' in text):
            # Clean up common patterns
            text = text.strip('$').strip()
            return text
        
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
        """Create or update Notion pages with proper nesting based on URL hierarchy"""
        import time
        from urllib.parse import urlparse
        
        # Build parent-child relationships based on URL paths
        url_hierarchy = self.build_url_hierarchy(pages)
        
        # Sort pages by depth to create parents first
        sorted_pages = sorted(pages.items(), key=lambda x: x[1]['depth'])
        
        created_count = 0
        for url, page_info in sorted_pages:
            try:
                # Determine parent - either another page or the database
                parent_url = url_hierarchy.get(url)
                
                if parent_url and parent_url in self.page_mapping:
                    # Create as child of another page
                    parent_type = "page_id"
                    parent_id = self.page_mapping[parent_url]
                    print(f"Creating child page {created_count + 1}/{len(pages)}: {page_info['title'][:30]} under parent")
                else:
                    # Create in database (top-level)
                    parent_type = "database_id"
                    parent_id = database_id
                    print(f"Creating root page {created_count + 1}/{len(pages)}: {page_info['title'][:30]}")
                
                new_page = self.create_notion_page_with_parent(parent_type, parent_id, page_info)
                self.page_mapping[url] = new_page['id']
                created_count += 1
                
                # Rate limiting - Notion API has limits
                time.sleep(0.5)
                
            except Exception as e:
                print(f"Error processing {url}: {e}")
                continue
        
        print(f"Successfully created {created_count} pages")
    
    def build_url_hierarchy(self, pages: Dict[str, Dict]) -> Dict[str, str]:
        """Build parent-child relationships based on URL structure"""
        hierarchy = {}
        
        # First, identify the main/home page
        home_urls = []
        for url in pages:
            parsed = urlparse(url)
            path = parsed.path.strip('/')
            if not path or path == 'index.html' or url.endswith('/'):
                home_urls.append(url)
        
        # Build hierarchy
        for url in pages:
            parsed = urlparse(url)
            path = parsed.path.strip('/')
            
            # Skip if this is a redirect or home page
            if pages[url].get('title', '').lower() == 'redirect':
                hierarchy[url] = None
                continue
            
            if not path or path == 'index.html':
                # Root level page
                hierarchy[url] = None
                continue
            
            # Special grouping for common directories
            path_parts = path.split('/')
            
            # Group pages by their directory
            if len(path_parts) > 1:
                # For pages in subdirectories like /pages/, /api/, etc
                directory = path_parts[0]
                
                # Find or create a parent page for this directory
                if directory == 'pages':
                    # All pages in /pages/ should be under a "Documentation" parent
                    # Look for the main index/home page as parent
                    if home_urls:
                        # Use the first non-redirect home page as parent
                        for home_url in home_urls:
                            if pages[home_url].get('title', '').lower() != 'redirect':
                                hierarchy[url] = home_url
                                break
                        else:
                            hierarchy[url] = None
                    else:
                        hierarchy[url] = None
                        
                elif directory == 'api':
                    # API pages - check if there's an api index
                    api_index = f"{parsed.scheme}://{parsed.netloc}/api/"
                    if api_index in pages and api_index != url:
                        hierarchy[url] = api_index
                    else:
                        hierarchy[url] = None
                else:
                    # Other subdirectories - try to find parent
                    parent_path = '/'.join(path_parts[:-1])
                    potential_parents = [
                        f"{parsed.scheme}://{parsed.netloc}/{parent_path}/index.html",
                        f"{parsed.scheme}://{parsed.netloc}/{parent_path}/",
                        f"{parsed.scheme}://{parsed.netloc}/{parent_path}"
                    ]
                    
                    for potential_parent in potential_parents:
                        if potential_parent in pages and potential_parent != url:
                            hierarchy[url] = potential_parent
                            break
                    else:
                        hierarchy[url] = None
            else:
                # Top-level page
                hierarchy[url] = None
        
        return hierarchy
    
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
        """Create new Notion page (legacy method for backward compatibility)"""
        return self.create_notion_page_with_parent("database_id", database_id, page_info)
    
    def create_notion_page_with_parent(self, parent_type: str, parent_id: str, page_info: Dict) -> Dict:
        """Create new Notion page with specified parent"""
        properties = {
            "Name": {"title": [{"text": {"content": page_info['title']}}]},
            "URL": {"url": page_info['url']},
            "Last Updated": {"date": {"start": "2024-01-01"}},  # Replace with actual date
            "Content Type": {"select": {"name": page_info['content_type']}}
        }
        
        # Create page with appropriate parent
        if parent_type == "database_id":
            parent = {"database_id": parent_id}
        else:
            parent = {"page_id": parent_id}
            # For child pages, we don't need all database properties
            properties = {"title": [{"text": {"content": page_info['title']}}]}
        
        page = self.notion.pages.create(
            parent=parent,
            properties=properties
        )
        
        # Add content blocks
        if page_info['content_blocks']:
            try:
                self.notion.blocks.children.append(
                    block_id=page['id'],
                    children=page_info['content_blocks'][:100]  # Notion limit
                )
            except Exception as e:
                print(f"Warning: Could not add content blocks: {e}")
        
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
        print(f"Repository name: {repo_name}")
        
        database_id = self.find_or_create_database(repo_name)
        print(f"Database ID: {database_id}")
        
        # Crawl and parse pages
        print("Crawling GitHub Pages...")
        pages = self.crawl_gh_pages(gh_pages_url)
        print(f"Found {len(pages)} pages")
        
        if not pages:
            print("No pages found to sync")
            return
        
        # Create/update Notion pages
        print("Syncing to Notion...")
        self.create_or_update_notion_pages(database_id, pages)
        
        print("Sync completed!")

def notion_gh_pages(repo_name, max_pages=50):
    
    gh_pages_url = f"https://munch-group.github.io/{repo_name}/"
    notion_token = os.environ.get("NOTION_TOKEN")
    parent_page_id = os.environ.get("NOTION_PARENT_PAGE_ID")  # Optional
    
    if not notion_token:
        raise ValueError("NOTION_TOKEN environment variable is required")
    
    parser = GitHubPagesNotionParser(notion_token=notion_token, parent_page_id=parent_page_id, max_pages=max_pages)
    parser.sync_repository(gh_pages_url)


# Usage example
if __name__ == "__main__": 


    notion_gh_pages("geneinfo")  # Replace with actual repository name


# # Usage example
# if __name__ == "__main__":
#     # Configure logging
#     logging.basicConfig(
#         level=logging.INFO,
#         format='%(asctime)s - %(levelname)s - %(message)s',
#         handlers=[
#             logging.FileHandler('sync.log'),
#             logging.StreamHandler()
#         ]
#     )
    
#     # Initialize parser
#     try:
#         parser = GitHubPagesNotionParser(notion_token=os.environ.get("NOTION_TOKEN"))
#         repo_name = "example-repo"  # Replace with actual repository name
#         # Sync a repository
#         gh_pages_url = f"https://munch-group.github.io/{repo_name}/"
#         parser.sync_repository(gh_pages_url)
        
#     except Exception as e:
#         logger.error(f"Failed to initialize or run parser: {e}", exc_info=True)