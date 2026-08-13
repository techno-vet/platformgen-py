"""
dev.to (Forem) API Publisher — Publish blog posts to dev.to.

This module provides a simple interface to publish Markdown blog posts to dev.to
using the Forem API (v1).

API Documentation: https://developers.forem.com/api/v1

Usage:
    from auger.tools.devto_publisher import DevtoPublisher
    
    publisher = DevtoPublisher(api_key="your_api_key")
    
    # Publish a new article
    article = publisher.publish(
        title="My Blog Post",
        body_markdown="# Hello World\n\nThis is my first post.",
        tags=["ai", "python", "platformgen"],
        canonical_url="https://yoursite.com/my-post",
        published=True
    )
    print(f"Published: {article['url']}")
"""

import requests
from typing import Dict, List, Optional, Any
from pathlib import Path


class DevtoPublisher:
    """Publish blog posts to dev.to via the Forem API."""
    
    DEFAULT_API_URL = "https://dev.to/api"
    
    def __init__(
        self,
        api_key: str,
        api_url: str = DEFAULT_API_URL,
        timeout: int = 30
    ):
        """
        Initialize the dev.to publisher.
        
        Args:
            api_key: dev.to API key (from dev.to/settings/account)
            api_url: Forem API URL (default: https://dev.to/api)
            timeout: Request timeout in seconds
        """
        self.api_key = api_key.strip()
        self.api_url = api_url.rstrip('/')
        self.timeout = timeout
        self.session = self._create_session()
    
    def _create_session(self) -> requests.Session:
        """Create a requests session with proper headers."""
        session = requests.Session()
        session.headers.update({
            'api-key': self.api_key,
            'Accept': 'application/vnd.forem.api-v1+json',
            'Content-Type': 'application/json'
        })
        return session
    
    def publish(
        self,
        title: str,
        body_markdown: str,
        tags: Optional[List[str]] = None,
        canonical_url: Optional[str] = None,
        published: bool = False,
        description: Optional[str] = None,
        cover_image_url: Optional[str] = None,
        series: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Publish or draft an article on dev.to.
        
        Args:
            title: Article title (required)
            body_markdown: Article body in Markdown (required)
            tags: List of tags (max 4, lowercase, no spaces)
            canonical_url: Canonical URL if published elsewhere
            published: Whether to publish immediately (False = draft)
            description: SEO description (max 160 chars)
            cover_image_url: Cover image URL
            series: Series name to group articles
        
        Returns:
            Dict containing article data from API response
            {
                'id': int,
                'url': str,
                'title': str,
                'published': bool,
                'created_at': str,
                'updated_at': str,
                ...
            }
        
        Raises:
            requests.exceptions.RequestException: API request failed
            ValueError: Invalid request parameters
        """
        if not title or not title.strip():
            raise ValueError("Title is required")
        if not body_markdown or not body_markdown.strip():
            raise ValueError("Body markdown is required")
        
        # Validate tags
        if tags:
            if len(tags) > 4:
                raise ValueError("Maximum 4 tags allowed")
            tags = [tag.strip().lower().replace(' ', '-') for tag in tags]
        else:
            tags = []
        
        # Validate description length
        if description and len(description) > 160:
            raise ValueError("Description cannot exceed 160 characters")
        
        payload = {
            'article': {
                'title': title.strip(),
                'body_markdown': body_markdown.strip(),
                'published': published,
            }
        }
        
        # Add optional fields
        if tags:
            payload['article']['tags'] = tags
        if canonical_url:
            payload['article']['canonical_url'] = canonical_url
        if description:
            payload['article']['description'] = description
        if cover_image_url:
            payload['article']['cover_image_url'] = cover_image_url
        if series:
            payload['article']['series'] = series
        
        # POST to /articles endpoint
        resp = self.session.post(
            f"{self.api_url}/articles",
            json=payload,
            timeout=self.timeout
        )
        
        if resp.status_code == 201:
            return resp.json()
        elif resp.status_code == 401:
            raise ValueError("Invalid API key")
        elif resp.status_code == 422:
            # Validation error
            errors = resp.json().get('errors', {})
            raise ValueError(f"Validation error: {errors}")
        else:
            raise requests.exceptions.HTTPError(
                f"Failed to publish article (HTTP {resp.status_code}): {resp.text}"
            )
    
    def publish_from_file(
        self,
        filepath: str,
        published: bool = False,
        tags: Optional[List[str]] = None,
        canonical_url: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Publish an article from a Markdown file.
        
        File format:
        ---
        title: My Article Title
        description: Optional SEO description
        canonical_url: https://example.com/article
        tags: python, platformgen, ai
        cover_image_url: https://example.com/cover.jpg
        series: My Series Name
        ---
        
        # Markdown content starts here...
        
        Args:
            filepath: Path to Markdown file
            published: Whether to publish immediately
            tags: Override tags from file
            canonical_url: Override canonical URL from file
            **kwargs: Additional article parameters
        
        Returns:
            Article data from API response
        """
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {filepath}")
        
        content = path.read_text(encoding='utf-8')
        
        # Parse frontmatter (simple YAML-like parsing)
        frontmatter = {}
        body_markdown = content
        
        if content.startswith('---'):
            parts = content.split('---', 2)
            if len(parts) >= 3:
                # Parse frontmatter
                fm_lines = parts[1].strip().split('\n')
                for line in fm_lines:
                    if ':' in line:
                        key, value = line.split(':', 1)
                        key = key.strip()
                        value = value.strip()
                        if key == 'tags':
                            frontmatter['tags'] = [t.strip() for t in value.split(',')]
                        else:
                            frontmatter[key] = value
                body_markdown = parts[2].strip()
        
        # Use frontmatter values or override with kwargs
        title = kwargs.pop('title', frontmatter.get('title'))
        if not title:
            raise ValueError("Title required (in frontmatter or kwargs)")
        
        article_tags = tags or frontmatter.get('tags')
        article_canonical_url = canonical_url or frontmatter.get('canonical_url')
        
        return self.publish(
            title=title,
            body_markdown=body_markdown,
            tags=article_tags,
            canonical_url=article_canonical_url,
            published=published,
            description=frontmatter.get('description'),
            cover_image_url=frontmatter.get('cover_image_url'),
            series=frontmatter.get('series'),
            **kwargs
        )
    
    def get_me(self) -> Dict[str, Any]:
        """
        Get authenticated user profile.
        
        Returns:
            User data dict with username, name, email, etc.
        """
        resp = self.session.get(
            f"{self.api_url}/users/me",
            timeout=self.timeout
        )
        
        if resp.status_code == 200:
            return resp.json()
        elif resp.status_code == 401:
            raise ValueError("Invalid API key")
        else:
            raise requests.exceptions.HTTPError(
                f"Failed to fetch user profile (HTTP {resp.status_code})"
            )
    
    def get_articles(
        self,
        page: int = 1,
        per_page: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Get authenticated user's articles.
        
        Args:
            page: Page number (1-based)
            per_page: Results per page (1-30)
        
        Returns:
            List of article dicts
        """
        resp = self.session.get(
            f"{self.api_url}/articles/me",
            params={'page': page, 'per_page': per_page},
            timeout=self.timeout
        )
        
        if resp.status_code == 200:
            return resp.json()
        elif resp.status_code == 401:
            raise ValueError("Invalid API key")
        else:
            raise requests.exceptions.HTTPError(
                f"Failed to fetch articles (HTTP {resp.status_code})"
            )
    
    def update_article(
        self,
        article_id: int,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Update an existing article (draft or published).
        
        Args:
            article_id: Article ID
            **kwargs: Fields to update (title, body_markdown, published, etc.)
        
        Returns:
            Updated article data
        """
        if not kwargs:
            raise ValueError("No fields to update")
        
        payload = {'article': kwargs}
        
        resp = self.session.put(
            f"{self.api_url}/articles/{article_id}",
            json=payload,
            timeout=self.timeout
        )
        
        if resp.status_code == 200:
            return resp.json()
        elif resp.status_code == 401:
            raise ValueError("Invalid API key")
        elif resp.status_code == 404:
            raise ValueError(f"Article {article_id} not found")
        else:
            raise requests.exceptions.HTTPError(
                f"Failed to update article (HTTP {resp.status_code})"
            )
