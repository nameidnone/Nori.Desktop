"""Built-in Web Search Tool for Nori Agent.

Provides safe web search capabilities with result filtering and rate limiting.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

import aiohttp

from ..registry import ITool, ToolMetadata, ToolParameter, ToolCategory, ToolPermissionLevel
from ..executor import ToolExecutionContext, ToolExecutionResult


@dataclass
class SearchEngineConfig:
    """Configuration for a search engine."""
    
    name: str
    base_url: str
    query_param: str = "q"
    results_param: str = "results"
    headers: Dict[str, str] = field(default_factory=dict)
    parse_results_fn: Optional[str] = None  # Name of parsing function


@dataclass
class WebSearchConfig:
    """Configuration for web search tool."""
    
    # Default search engine to use
    default_engine: str = "google"
    
    # Maximum number of results to return
    max_results: int = 10
    
    # Rate limiting (requests per minute)
    rate_limit: int = 10
    
    # Request timeout in seconds
    timeout: int = 30
    
    # User agent string
    user_agent: str = "Nori-Agent/1.0 (Desktop Pet Assistant)"
    
    # Allowed domains (empty = all allowed)
    allowed_domains: List[str] = field(default_factory=list)
    
    # Blocked domains
    blocked_domains: List[str] = field(default_factory=lambda: [
        "pastebin.com", "gist.github.com"  # Common spam sources
    ])
    
    # Search engines configuration
    engines: Dict[str, SearchEngineConfig] = field(default_factory=lambda: {
        "google": SearchEngineConfig(
            name="Google",
            base_url="https://www.google.com/search",
            query_param="q",
            headers={"Accept": "text/html,application/xhtml+xml"}
        ),
        "bing": SearchEngineConfig(
            name="Bing",
            base_url="https://www.bing.com/search",
            query_param="q",
            headers={"Accept": "text/html,application/xhtml+xml"}
        ),
        "duckduckgo": SearchEngineConfig(
            name="DuckDuckGo",
            base_url="https://duckduckgo.com/html/",
            query_param="q",
            headers={"Accept": "text/html,application/xhtml+xml"}
        )
    })


class WebSearchTool(ITool):
    """Built-in tool for performing web searches with safety constraints."""
    
    def __init__(self, config: Optional[WebSearchConfig] = None):
        self.config = config or WebSearchConfig()
        self._request_times: List[float] = []
        self._session: Optional[aiohttp.ClientSession] = None
    
    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="web_search",
            display_name="Web Search",
            description="Search the web for information using various search engines.",
            category=ToolCategory.WEB_TOOLS,
            permission_level=ToolPermissionLevel.NONE,
            parameters=[
                ToolParameter(
                    name="query",
                    description="The search query",
                    param_type="str",
                    required=True
                ),
                ToolParameter(
                    name="engine",
                    description="Search engine to use (google, bing, duckduckgo)",
                    param_type="str",
                    required=False,
                    default="google",
                    choices=["google", "bing", "duckduckgo"]
                ),
                ToolParameter(
                    name="num_results",
                    description="Number of results to return (default: 10)",
                    param_type="int",
                    required=False,
                    default=10
                ),
                ToolParameter(
                    name="safe_search",
                    description="Enable safe search filtering (default: true)",
                    param_type="bool",
                    required=False,
                    default=True
                ),
                ToolParameter(
                    name="time_range",
                    description="Time range filter (any, day, week, month, year)",
                    param_type="str",
                    required=False,
                    default="any",
                    choices=["any", "day", "week", "month", "year"]
                )
            ],
            returns="List of search results with title, URL, and snippet",
            examples=[
                '{"query": "Python async programming"}',
                '{"query": "latest AI news", "engine": "google", "num_results": 5}'
            ]
        )
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"User-Agent": self.config.user_agent},
                timeout=aiohttp.ClientTimeout(total=self.config.timeout)
            )
        return self._session
    
    async def close(self) -> None:
        """Close HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
    
    def _check_rate_limit(self) -> bool:
        """Check if request is within rate limit."""
        now = time.time()
        window_start = now - 60.0  # 1 minute window
        
        # Remove old timestamps
        self._request_times = [t for t in self._request_times if t > window_start]
        
        if len(self._request_times) >= self.config.rate_limit:
            return False
        
        self._request_times.append(now)
        return True
    
    def _validate_domain(self, url: str) -> bool:
        """Check if URL domain is allowed."""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            
            # Check blocked domains
            for blocked in self.config.blocked_domains:
                if blocked.lower() in domain:
                    return False
            
            # Check allowed domains if specified
            if self.config.allowed_domains:
                for allowed in self.config.allowed_domains:
                    if allowed.lower() in domain:
                        return True
                return False
            
            return True
        except Exception:
            return False
    
    def _clean_snippet(self, text: str) -> str:
        """Clean HTML tags and normalize whitespace from snippet."""
        # Remove HTML tags
        clean = re.sub(r'<[^>]+>', '', text)
        # Normalize whitespace
        clean = re.sub(r'\s+', ' ', clean).strip()
        # Limit length
        if len(clean) > 500:
            clean = clean[:497] + "..."
        return clean
    
    async def _search_google(self, query: str, num_results: int, safe_search: bool) -> List[Dict[str, Any]]:
        """Perform Google search (simplified HTML parsing)."""
        session = await self._get_session()
        
        params = {
            "q": query,
            "num": num_results,
        }
        
        if safe_search:
            params["safe"] = "active"
        
        try:
            async with session.get(
                self.config.engines["google"].base_url,
                params=params,
                headers=self.config.engines["google"].headers
            ) as response:
                if response.status != 200:
                    return []
                
                html = await response.text()
                
                # Simple regex-based extraction (production would use proper HTML parser)
                results = []
                title_pattern = r'<h3[^>]*>(.*?)</h3>'
                link_pattern = r'<a[^>]*href="(http[^"]+)"[^>]*>'
                snippet_pattern = r'<div[^>]*class=["\']?[^"\']*snippet[^"\']*["\']?[^>]*>(.*?)</div>'
                
                titles = re.findall(title_pattern, html, re.DOTALL)[:num_results]
                links = re.findall(link_pattern, html)[:num_results * 2]  # Get extra to filter
                
                for i, title in enumerate(titles):
                    if i < len(links):
                        link = links[i]
                        if self._validate_domain(link):
                            results.append({
                                "title": self._clean_snippet(title),
                                "url": link,
                                "snippet": "Search result from Google",
                                "engine": "google"
                            })
                
                return results[:num_results]
                
        except Exception as e:
            return [{"error": f"Google search failed: {str(e)}"}]
    
    async def _search_bing(self, query: str, num_results: int, safe_search: bool) -> List[Dict[str, Any]]:
        """Perform Bing search."""
        session = await self._get_session()
        
        params = {
            "q": query,
            "count": num_results,
        }
        
        if safe_search:
            params["safesearch"] = "Strict"
        
        try:
            async with session.get(
                self.config.engines["bing"].base_url,
                params=params,
                headers=self.config.engines["bing"].headers
            ) as response:
                if response.status != 200:
                    return []
                
                html = await response.text()
                
                # Simplified extraction
                results = []
                title_pattern = r'<h2[^>]*><a[^>]*href="(http[^"]+)"[^>]*>(.*?)</a></h2>'
                
                matches = re.findall(title_pattern, html, re.DOTALL)[:num_results]
                for link, title in matches:
                    if self._validate_domain(link):
                        results.append({
                            "title": self._clean_snippet(title),
                            "url": link,
                            "snippet": "Search result from Bing",
                            "engine": "bing"
                        })
                
                return results
                
        except Exception as e:
            return [{"error": f"Bing search failed: {str(e)}"}]
    
    async def _search_duckduckgo(self, query: str, num_results: int, safe_search: bool) -> List[Dict[str, Any]]:
        """Perform DuckDuckGo search."""
        session = await self._get_session()
        
        try:
            async with session.post(
                self.config.engines["duckduckgo"].base_url,
                data={"q": query},
                headers=self.config.engines["duckduckgo"].headers
            ) as response:
                if response.status != 200:
                    return []
                
                html = await response.text()
                
                # Simplified extraction
                results = []
                result_pattern = r'<a[^>]*class=["\']result__a["\'][^>]*href="(http[^"]+)"[^>]*>(.*?)</a>'
                
                matches = re.findall(result_pattern, html, re.DOTALL)[:num_results]
                for link, title in matches:
                    if self._validate_domain(link):
                        results.append({
                            "title": self._clean_snippet(title),
                            "url": link,
                            "snippet": "Search result from DuckDuckGo",
                            "engine": "duckduckgo"
                        })
                
                return results
                
        except Exception as e:
            return [{"error": f"DuckDuckGo search failed: {str(e)}"}]
    
    async def execute_async(self, context: ToolExecutionContext) -> ToolExecutionResult:
        """Execute web search asynchronously."""
        try:
            # Check rate limit
            if not self._check_rate_limit():
                return ToolExecutionResult(
                    success=False,
                    error="Rate limit exceeded. Please wait before searching again."
                )
            
            query = context.arguments.get("query")
            if not query:
                return ToolExecutionResult(success=False, error="Missing 'query' argument")
            
            engine = context.arguments.get("engine", self.config.default_engine)
            num_results = min(context.arguments.get("num_results", 10), self.config.max_results)
            safe_search = context.arguments.get("safe_search", True)
            
            # Validate engine
            if engine not in self.config.engines:
                return ToolExecutionResult(
                    success=False,
                    error=f"Unknown search engine: {engine}. Available: {list(self.config.engines.keys())}"
                )
            
            # Perform search
            search_fn = getattr(self, f"_search_{engine}", None)
            if not search_fn:
                return ToolExecutionResult(success=False, error=f"Search function not found for {engine}")
            
            results = await search_fn(query, num_results, safe_search)
            
            if not results:
                return ToolExecutionResult(
                    success=True,
                    data={
                        "query": query,
                        "engine": engine,
                        "count": 0,
                        "results": [],
                        "message": "No results found"
                    }
                )
            
            # Filter out errors
            valid_results = [r for r in results if "error" not in r]
            
            return ToolExecutionResult(
                success=True,
                data={
                    "query": query,
                    "engine": engine,
                    "count": len(valid_results),
                    "results": valid_results
                }
            )
            
        except Exception as e:
            return ToolExecutionResult(success=False, error=f"Search failed: {str(e)}")


def create_tool(config: Optional[WebSearchConfig] = None) -> ITool:
    """Factory function to create WebSearchTool instance."""
    return WebSearchTool(config)
