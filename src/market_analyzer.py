import os
import json
import sys
import re
import time
import random
import logging
import calendar
from datetime import datetime, timedelta
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import yfinance as yf
import pandas as pd
from bs4 import BeautifulSoup
from textblob import TextBlob

def debug_print(msg):
    print(f"DEBUG: {msg}", file=sys.stderr)

logger = logging.getLogger(__name__)

class MarketNewsAnalyzer:
    def __init__(self):
        # Initialize headers with more browser-like values
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'DNT': '1',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0'
        }
        
        self.news_sources = {
            'ft': 'https://www.ft.com/markets',
            'marketwatch': 'https://www.marketwatch.com/markets',
            'yahoo_finance': 'https://finance.yahoo.com/topic/stock-market-news',
            'cnbc': 'https://www.cnbc.com/world/?region=world'
        }

        self.data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')
        self.ensure_data_directory()
        self.stock_symbols = self.load_stock_symbols()
        self.setup_logging()
        self.session = self.setup_requests_session()
        self.last_request_time = {}
        self.min_request_interval = 3  # Increased delay between requests

        self.history_cache = {}  # Cache for historical analysis results

    def setup_logging(self):
        """Set up logging configuration"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(os.path.join(self.data_dir, 'market_analyzer.log')),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)

    def setup_requests_session(self):
        """Set up requests session with retry strategy"""
        session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        session.headers.update(self.headers)
        return session

    def load_stock_symbols(self):
        """Load common stock symbols and company names with more specific keywords"""
        return {
            'AAPL': {
                'primary': ['apple', 'iphone'],
                'secondary': ['mac', 'macbook', 'ios', 'app store'],
                'exact': ['AAPL', '$AAPL'],
                'logo': 'https://logo.clearbit.com/apple.com'
            },
            'GOOGL': {
                'primary': ['google', 'alphabet inc', 'alphabet'],
                'secondary': ['android', 'chrome', 'pixel'],
                'exact': ['GOOGL', '$GOOGL', 'GOOG', '$GOOG'],
                'logo': 'https://logo.clearbit.com/google.com'
            },
            'MSFT': {
                'primary': ['microsoft'],
                'secondary': ['windows', 'azure', 'xbox'],
                'exact': ['MSFT', '$MSFT'],
                'logo': 'https://logo.clearbit.com/microsoft.com'
            },
            'AMZN': {
                'primary': ['amazon'],
                'secondary': ['aws', 'prime', 'kindle'],
                'exact': ['AMZN', '$AMZN'],
                'logo': 'https://logo.clearbit.com/amazon.com'
            },
            'META': {
                'primary': ['meta', 'facebook'],
                'secondary': ['instagram', 'whatsapp', 'oculus'],
                'exact': ['META', '$META', 'FB', '$FB'],
                'logo': 'https://logo.clearbit.com/meta.com'
            },
            'NVDA': {
                'primary': ['nvidia', 'nvda'],
                'secondary': ['geforce', 'gpu'],
                'exact': ['NVDA', '$NVDA'],
                'logo': 'https://logo.clearbit.com/nvidia.com'
            },
            'TSLA': {
                'primary': ['tesla', 'elon musk'],
                'secondary': ['model 3', 'model y', 'cybertruck'],
                'exact': ['TSLA', '$TSLA'],
                'logo': 'https://logo.clearbit.com/tesla.com'
            },
            'BRK-B': {
                'primary': ['berkshire', 'berkshire hathaway', 'buffett'],
                'secondary': ['warren buffett', 'charlie munger'],
                'exact': ['BRK.B', 'BRK-B', '$BRK.B', '$BRK-B'],
                'logo': 'https://logo.clearbit.com/berkshirehathaway.com'
            },
            'VLVLY': {
                'primary': ['volvo', 'volvo group'],
                'secondary': ['volvo cars', 'volvo trucks'],
                'exact': ['VLVLY', '$VLVLY'],
                'logo': 'https://logo.clearbit.com/volvo.com'
            }
        }

    def ensure_data_directory(self):
        """Create data directory if it doesn't exist"""
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)

    def fetch_news(self, source):
        """Fetch news from specified source with enhanced error handling and rate limiting"""
        try:
            # Check if we need to wait before making another request
            if source in self.last_request_time:
                time_since_last_request = (datetime.now() - self.last_request_time[source]).total_seconds()
                if time_since_last_request < self.min_request_interval:
                    sleep_time = self.min_request_interval - time_since_last_request
                    self.logger.info(f"Rate limiting: waiting {sleep_time:.1f}s before requesting {source}")
                    time.sleep(sleep_time)

            self.logger.info(f"Fetching news from {source}")
            
            # Update headers based on source
            if source == 'marketwatch':
                self.headers.update({
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'Connection': 'keep-alive',
                    'Sec-Fetch-Site': 'same-origin',
                    'Sec-Fetch-Mode': 'navigate',
                    'Sec-Fetch-User': '?1',
                    'Sec-Fetch-Dest': 'document',
                    'Referer': 'https://www.marketwatch.com/',
                    'Cookie': 'gdprApplies=false; country_code=US'
                })
            elif source == 'yahoo_finance':
                self.headers.update({
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'Connection': 'keep-alive',
                    'Referer': 'https://finance.yahoo.com/',
                    'Cookie': 'B=dlsf0p1gg7edv&b=3&s=q4; GUC=AQEBAQFjWGNkY0IgLwR7'
                })
            else:
                # Update User-Agent randomly for each request
                chrome_version = f"91.0.{random.randint(4000, 5000)}.0"
                self.headers['User-Agent'] = f'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_version} Safari/537.36'
            
            # Make the request
            response = self.session.get(
                self.news_sources[source],
                headers=self.headers,
                timeout=15  # Increased timeout
            )
            response.raise_for_status()
            
            # Update last request time
            self.last_request_time[source] = datetime.now()
            
            return response.text
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Error fetching news from {source}: {str(e)}")
            if hasattr(e, 'response') and e.response is not None:
                self.logger.error(f"Status code: {e.response.status_code}")
            return None

    def extract_stock_symbols(self, text):
        """Extract potential stock symbols from text with enhanced accuracy"""
        symbols = set()
        text_lower = text.lower()
        
        # Common stock-related phrases
        stock_phrases = [
            r'\$([A-Z]{1,5}(?:\.[A-Z])?)\b',  # $AAPL, $BRK.A
            r'\b([A-Z]{1,5}(?:\.[A-Z])?)\s+(?:stock|shares|inc\.?|corp\.?|group)\b',  # AAPL stock, BRK.A shares
            r'(?:shares of|stock in)\s+([A-Z]{1,5}(?:\.[A-Z])?)\b',  # shares of AAPL
            r'\b([A-Z]{1,5}(?:\.[A-Z])?)\s+(?:rose|fell|jumped|plunged|gained|lost)\b',  # AAPL rose
            r'\b([A-Z]{1,5}(?:\.[A-Z])?)\s+(?:\+|\-)?[0-9]+(?:\.[0-9]+)?\%',  # AAPL +1.5%
            r'(?:buy|sell)\s+([A-Z]{1,5}(?:\.[A-Z])?)\b',  # buy AAPL
            r'ticker[:\s]+([A-Z]{1,5}(?:\.[A-Z])?)\b'  # ticker: AAPL
        ]
        
        # First pass: Look for exact matches with stock phrases
        for pattern in stock_phrases:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                match = match.upper()
                for symbol, data in self.stock_symbols.items():
                    if match in [exact.upper() for exact in data['exact']]:
                    symbols.add(symbol)
        
        # Second pass: Look for company names with context
        for symbol, keywords in self.stock_symbols.items():
            if symbol in symbols:
                continue
                
            # Check primary keywords
            for primary in keywords['primary']:
                if primary.lower() in text_lower:
                    # Look for financial context around company name
                    context_start = max(0, text_lower.find(primary.lower()) - 100)
                    context_end = min(len(text_lower), text_lower.find(primary.lower()) + len(primary) + 100)
                    context = text_lower[context_start:context_end]
                    
                    # Check for financial terms in context
                    financial_terms = {
                        'stock', 'share', 'market', 'price', 'investor', 'trading',
                        'earnings', 'revenue', 'profit', 'dividend', 'nasdaq', 'nyse',
                        'up', 'down', 'rise', 'fall', 'gain', 'loss', 'jump', 'plunge'
                    }
                    
                    if any(term in context for term in financial_terms):
                        symbols.add(symbol)
                        break
        
            # If not found by primary keywords, check secondary keywords
            if symbol not in symbols:
                secondary_matches = 0
            for secondary in keywords['secondary']:
                if secondary.lower() in text_lower:
                        secondary_matches += 1
                        if secondary_matches >= 2:  # Require at least 2 secondary keyword matches
                symbols.add(symbol)
                            break
        
        return list(symbols)

    def get_stock_data(self, symbol, days=5):
        """Fetch stock price data with caching"""
        cache_file = os.path.join(self.data_dir, f'stock_cache_{symbol}.json')
        
        # Check cache first
        if os.path.exists(cache_file):
            cache_time = os.path.getmtime(cache_file)
            if (datetime.now() - datetime.fromtimestamp(cache_time)).seconds < 3600:  # Cache for 1 hour
                try:
                    with open(cache_file, 'r') as f:
                        self.logger.info(f"Using cached data for {symbol}")
                        return pd.read_json(f)
                except Exception as e:
                    self.logger.warning(f"Error reading cache for {symbol}: {str(e)}")

        # Fetch new data
        try:
            self.logger.info(f"Fetching stock data for {symbol}")
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)
            stock = yf.Ticker(symbol)
            hist = stock.history(start=start_date, end=end_date)
            
            # Save to cache
            try:
                hist.to_json(cache_file)
            except Exception as e:
                self.logger.warning(f"Error caching stock data for {symbol}: {str(e)}")
            
            return hist
        except Exception as e:
            self.logger.error(f"Error fetching stock data for {symbol}: {str(e)}")
            return None

    def format_price(self, price):
        """Format price with appropriate decimal places"""
        return f"${price:,.2f}"

    def format_percentage(self, percentage):
        """Format percentage with sign"""
        return f"{'+' if percentage > 0 else ''}{percentage:.2f}%"

    def format_volume(self, volume):
        """Format volume with K/M/B suffixes"""
        if volume >= 1_000_000_000:
            return f"{volume/1_000_000_000:.1f}B"
        elif volume >= 1_000_000:
            return f"{volume/1_000_000:.1f}M"
        elif volume >= 1_000:
            return f"{volume/1_000:.1f}K"
        return str(volume)

    def get_stock_metrics(self, data):
        """Extract stock metrics using proper pandas indexing with yesterday's comparison"""
        if data is None or data.empty:
            return None
            
        try:
            # Get today's and yesterday's data
            today = datetime.now().date()
            yesterday = today - timedelta(days=1)
            
            # Get latest data point (today)
            latest = data.iloc[-1]
            
            # Find yesterday's closing price
            yesterday_data = data[data.index.date == yesterday]
            yesterday_close = yesterday_data['Close'].iloc[-1] if not yesterday_data.empty else data.iloc[0]['Close']
            
            # Calculate daily and overall changes
            daily_change = float(latest['Close'] - yesterday_close)
            daily_change_pct = float((daily_change / yesterday_close) * 100)
            
            # Calculate intraday high/low changes
            intraday_high_change_pct = float((latest['High'] - yesterday_close) / yesterday_close * 100)
            intraday_low_change_pct = float((latest['Low'] - yesterday_close) / yesterday_close * 100)
            
            return {
                'current_price': float(latest['Close']),
                'yesterday_close': float(yesterday_close),
                'daily_change': daily_change,
                'daily_change_pct': daily_change_pct,
                'intraday_high': float(latest['High']),
                'intraday_low': float(latest['Low']),
                'intraday_high_change_pct': intraday_high_change_pct,
                'intraday_low_change_pct': intraday_low_change_pct,
                'volume': int(latest['Volume']),
                'avg_volume': float(data['Volume'].mean()),
                'volume_change_pct': float((latest['Volume'] - data['Volume'].mean()) / data['Volume'].mean() * 100)
            }
        except Exception as e:
            self.logger.error(f"Error calculating stock metrics: {str(e)}")
            return None

    def analyze_sentiment(self, text):
        """Analyze sentiment of text using TextBlob with improved thresholds"""
        try:
            self.logger.info("Performing sentiment analysis")
            analysis = TextBlob(text)
            
            # Get polarity and subjectivity
            sentiment = {
                'polarity': analysis.sentiment.polarity,
                'subjectivity': analysis.sentiment.subjectivity,
                'assessment': 'neutral'
            }
            
            # More nuanced assessment thresholds
            if sentiment['polarity'] > 0.2:  # Lowered positive threshold
                sentiment['assessment'] = 'positive'
            elif sentiment['polarity'] < -0.2:  # Lowered negative threshold
                sentiment['assessment'] = 'negative'
            
            return sentiment
        except Exception as e:
            self.logger.error(f"Error in sentiment analysis: {str(e)}")
            return {
                'polarity': 0.0,
                'subjectivity': 0.0,
                'assessment': 'error'
            }

    def parse_news(self, html_content, source):
        """Parse HTML content with source-specific extraction"""
        if not html_content:
            return []

        self.logger.info(f"Parsing news content from {source}")
        soup = BeautifulSoup(html_content, 'html.parser')
        articles = []

        try:
            if source == 'cnbc':
                articles.extend(self._parse_cnbc(soup))
            elif source == 'marketwatch':
                articles.extend(self._parse_marketwatch(soup))
            elif source == 'yahoo_finance':
                articles.extend(self._parse_yahoo_finance(soup))
            elif source == 'ft':
                articles.extend(self._parse_ft(soup))
            elif source == 'bbc':
                articles.extend(self._parse_bbc(soup))
        except Exception as e:
            self.logger.error(f"Error parsing {source} content: {str(e)}")

        self.logger.info(f"Found {len(articles)} articles from {source}")
        return articles

    def _parse_ft(self, soup):
        """Parse Financial Times news"""
        articles = []
        
        # Try multiple selectors for articles
        article_selectors = [
            'div.o-teaser',
            'li.o-teaser-collection__item',
            'div.o-grid-row article'
        ]
        
        for selector in article_selectors:
            for article in soup.select(selector):
                try:
                    # Title selectors
                    title_elem = (
                        article.select_one('a.js-teaser-heading-link') or
                        article.select_one('h3.o-teaser__heading') or
                        article.select_one('.article-title')
                    )
                    
                    if not title_elem:
                        continue
                    
                    title = title_elem.get_text().strip()
                    
                    # Summary selectors
                    summary_elem = (
                        article.select_one('p.o-teaser__standfirst') or
                        article.select_one('div.o-teaser__standfirst') or
                        article.select_one('.article-summary')
                    )
                    summary = summary_elem.get_text().strip() if summary_elem else ""
                    
                    # Link selectors
                    link_elem = title_elem if title_elem.name == 'a' else title_elem.find_parent('a')
                    
                    if link_elem and 'href' in link_elem.attrs:
                        link = link_elem['href']
                        if not link.startswith('http'):
                            link = 'https://www.ft.com' + link
                            
                        articles.append({
                            'title': title,
                            'summary': summary,
                            'link': link,
                            'source': 'Financial Times',
                            'timestamp': datetime.now().isoformat()
                        })
                        
                except Exception as e:
                    self.logger.debug(f"Error parsing FT article: {str(e)}")
                    continue
                    
        return articles

    def _parse_cnbc(self, soup):
        """Parse CNBC news"""
        articles = []
        
        # Try multiple selectors for articles
        article_selectors = [
            'div.Card-standardBreakerCard',
            'div.Card-card',
            'div.SearchResult-searchResult'
        ]
        
        for selector in article_selectors:
            for article in soup.select(selector):
                try:
                    # Title selectors
                    title_elem = (
                        article.select_one('a.Card-title') or
                        article.select_one('div.Card-titleContainer') or
                        article.select_one('.headline')
                    )
                    
                    if not title_elem:
                        continue
                        
                    title = title_elem.get_text().strip()
                    
                    # Summary selectors
                    summary_elem = (
                        article.select_one('div.Card-description') or
                        article.select_one('.description') or
                        article.select_one('.summary')
                    )
                    summary = summary_elem.get_text().strip() if summary_elem else ""
                    
                    # Link selectors
                    link_elem = (
                        article.select_one('a.Card-title') or
                        article.select_one('a[href*="cnbc.com"]') or
                        title_elem.find_parent('a')
                    )
                    
                    if link_elem and 'href' in link_elem.attrs:
                        link = link_elem['href']
                            if not link.startswith('http'):
                            link = 'https://www.cnbc.com' + link
                                
                            articles.append({
                                'title': title,
                                'summary': summary,
                                'link': link,
                            'source': 'CNBC',
                                'timestamp': datetime.now().isoformat()
                            })
                            
                except Exception as e:
                    self.logger.debug(f"Error parsing CNBC article: {str(e)}")
                    continue
                    
        return articles

    def _parse_marketwatch(self, soup):
        """Parse MarketWatch news"""
        articles = []
        
        # Try multiple selectors for articles
        article_selectors = [
            'div.article__content',
            'div.column--primary article',
            'div.article__wrap'
        ]
        
        for selector in article_selectors:
            for article in soup.select(selector):
                try:
                    # Title selectors
                    title_elem = (
                        article.select_one('h3.article__headline') or
                        article.select_one('a.link') or
                        article.select_one('.article__headline')
                    )
                    
                    if not title_elem:
                        continue
                    
                    title = title_elem.get_text().strip()
                    
                    # Summary selectors
                    summary_elem = (
                        article.select_one('p.article__summary') or
                        article.select_one('.article__description') or
                        article.select_one('.description')
                    )
                    summary = summary_elem.get_text().strip() if summary_elem else ""
                    
                    # Link selectors
                    link_elem = title_elem.find_parent('a') or article.select_one('a[href*="/story/"]')
                    
                    if link_elem and 'href' in link_elem.attrs:
                        link = link_elem['href']
                        if not link.startswith('http'):
                            link = 'https://www.marketwatch.com' + link
                            
                            articles.append({
                                'title': title,
                                'summary': summary,
                                'link': link,
                            'source': 'MarketWatch',
                                'timestamp': datetime.now().isoformat()
                            })
                            
                except Exception as e:
                    self.logger.debug(f"Error parsing MarketWatch article: {str(e)}")
                    continue
        
        return articles

    def _parse_yahoo_finance(self, soup):
        """Parse Yahoo Finance news with updated selectors"""
        articles = []
        
        # Updated selectors for Yahoo Finance's new layout
        article_selectors = [
            'li[data-test="content-item"]',
            'div.Cf',
            'div.IbBox'
        ]
        
        for selector in article_selectors:
            for article in soup.select(selector):
                try:
                    # Updated title selectors
                    title_elem = (
                        article.select_one('h3 a') or
                        article.select_one('a[data-test="mega-headline"]') or
                        article.select_one('h3[class*="Mb(5px)"]') or
                        article.select_one('a.js-content-viewer')
                    )
                    
                    if not title_elem:
                        continue
                        
                    title = title_elem.get_text().strip()
                    
                    # Updated summary selectors
                    summary_elem = (
                        article.select_one('p[class*="Fz"]') or
                        article.select_one('div[class*="Wow"]') or
                        article.select_one('p[class*="Fz(14px)"]')
                    )
                    summary = summary_elem.get_text().strip() if summary_elem else ""
                    
                    # Get the link
                    link = title_elem.get('href', '')
                    if link and not link.startswith('http'):
                        link = 'https://finance.yahoo.com' + link
                        
                    # Get timestamp if available
                    time_elem = article.select_one('div[class*="C(#"]') or article.select_one('span[class*="Fw"]')
                    timestamp = time_elem.get_text().strip() if time_elem else datetime.now().isoformat()
                        
                articles.append({
                    'title': title,
                    'summary': summary,
                    'link': link,
                        'source': 'Yahoo Finance',
                        'timestamp': timestamp
                })
                        
            except Exception as e:
                    self.logger.debug(f"Error parsing Yahoo Finance article: {str(e)}")
                continue
                    
        return articles

    def _parse_bbc(self, soup):
        """Parse BBC news"""
        articles = []
        
        # Try multiple selectors for articles
        article_selectors = [
            'div.gs-c-promo',
            'article.media-item',
            'div.market-data-article'
        ]
        
        for selector in article_selectors:
            for article in soup.select(selector):
                try:
                    # Title selectors
                    title_elem = (
                        article.select_one('h3.gs-c-promo-heading') or
                        article.select_one('.media-title') or
                        article.select_one('.article-headline')
                    )
                    
                    if not title_elem:
                        continue
                        
                    title = title_elem.get_text().strip()
                    
                    # Summary selectors
                    summary_elem = (
                        article.select_one('p.gs-c-promo-summary') or
                        article.select_one('.media-summary') or
                        article.select_one('.article-description')
                    )
                    summary = summary_elem.get_text().strip() if summary_elem else ""
                    
                    # Link selectors
                    link_elem = title_elem.find_parent('a') or article.select_one('a[href*="/news/business"]')
                    
                    if link_elem and 'href' in link_elem.attrs:
                        link = link_elem['href']
                    if not link.startswith('http'):
                            link = 'https://www.bbc.com' + link
                    
                        articles.append({
                            'title': title,
                            'summary': summary,
                            'link': link,
                            'source': 'BBC',
                            'timestamp': datetime.now().isoformat()
                        })
                        
                except Exception as e:
                    self.logger.debug(f"Error parsing BBC article: {str(e)}")
                    continue
                    
        return articles

    def analyze_stock_impact(self, news_articles):
        """Analyze news articles for stock impact with enhanced features"""
        stock_impacts = []
        
        for article in news_articles:
            try:
                # Combine title and summary for analysis, with title weighted more heavily
                text = f"{article['title']} {article['title']} {article.get('summary', '')}"
                
                # Extract mentioned stocks
                affected_stocks = self.extract_stock_symbols(text)
                
                if not affected_stocks:
                    continue
                
                # Analyze sentiment with more weight on the title
                title_sentiment = self.analyze_sentiment(article['title'])
                full_sentiment = self.analyze_sentiment(text)
                
                # Combine sentiments with more weight on title
                combined_sentiment = {
                    'polarity': (title_sentiment['polarity'] * 0.7 + full_sentiment['polarity'] * 0.3),
                    'subjectivity': (title_sentiment['subjectivity'] * 0.7 + full_sentiment['subjectivity'] * 0.3),
                    'assessment': 'neutral'
                }
                
                # More nuanced sentiment assessment
                if combined_sentiment['polarity'] > 0.15:  # Lowered threshold
                    combined_sentiment['assessment'] = 'positive'
                elif combined_sentiment['polarity'] < -0.15:  # Lowered threshold
                    combined_sentiment['assessment'] = 'negative'
                
                # Get stock data for affected stocks
                stock_data = {}
                for symbol in affected_stocks:
                    data = self.get_stock_data(symbol)
                    metrics = self.get_stock_metrics(data)
                    if metrics:
                        stock_data[symbol] = metrics
                
                if stock_data:  # Only add if we have valid stock data
                    impact = {
                        'affected_stocks': affected_stocks,
                        'sentiment': combined_sentiment,
                        'stock_data': stock_data,
                        'timestamp': datetime.now().isoformat()
                    }
                    
                    stock_impacts.append({
                        'article': article,
                        'impact': impact
                    })
                
            except Exception as e:
                self.logger.error(f"Error analyzing article impact: {str(e)}")
                continue
        
        return stock_impacts

    def save_results(self, results):
        """Save analysis results with formatting"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'market_analysis_{timestamp}.json'
        filepath = os.path.join(self.data_dir, filename)
        
        # Format results for saving
        formatted_results = []
        for result in results:
            # Add stock logos to the results
            stock_data_with_logos = {}
            for symbol in result['impact']['stock_data']:
                stock_data_with_logos[symbol] = {
                    **result['impact']['stock_data'][symbol],
                    'logo': self.stock_symbols[symbol]['logo']
                }

            formatted_result = {
                'article_title': result['article']['title'],
                'article_timestamp': result['article'].get('timestamp'),
                'affected_stocks': result['impact']['affected_stocks'],
                'sentiment': result['impact']['sentiment'],
                'stock_data': stock_data_with_logos
            }
            formatted_results.append(formatted_result)
        
        with open(filepath, 'w') as f:
            json.dump(formatted_results, f, indent=2)
        
        print(f"Results saved to {filepath}")
        return filepath

    def run_analysis(self):
        """Run the complete market news analysis with deduplication"""
        all_results = []
        seen_titles = set()  # Track seen article titles
        
        for source in self.news_sources:
            self.logger.info(f"\nAnalyzing news from {source}...")
            
            # Fetch news
            html_content = self.fetch_news(source)
            if not html_content:
                self.logger.error(f"Failed to fetch content from {source}")
                continue
                
            # Parse articles
            articles = self.parse_news(html_content, source)
            self.logger.info(f"Found {len(articles)} articles from {source}")
            
            # Process each article
            for article in articles:
                try:
                    # Skip if we've seen this article before
                    title = ' '.join(article['title'].lower().split())
                    if title in seen_titles:
                        continue
                    seen_titles.add(title)
                    
                    self.logger.info(f"\nProcessing article: {article['title'][:100]}...")
                    
                    # Process the article
                    impacts = self.analyze_stock_impact([article])
                    if impacts:
                        self.logger.info(f"Found impacts for {len(impacts[0]['impact']['affected_stocks'])} stocks")
                        all_results.extend(impacts)
                    else:
                        self.logger.info("No stock impacts found")
                        
                except Exception as e:
                    self.logger.error(f"Error processing article: {str(e)}")
                    continue

        self.logger.info(f"\nTotal results found: {len(all_results)}")
        filepath = self.save_results(all_results)
        return all_results, filepath

    def get_recent_news(self, today_only=True):
        """Get news from today or yesterday
        
        Args:
            today_only (bool): If True, get only today's news. If False, get yesterday's news.
        """
        today = datetime.now()
        yesterday = today - timedelta(days=1)
        
        results = []
        seen_titles = set()
        
        for source in self.news_sources:
            self.logger.info(f"\nAnalyzing news from {source}...")
            
            html_content = self.fetch_news(source)
            if not html_content:
                            continue

            articles = self.parse_news(html_content, source)
            self.logger.info(f"Found {len(articles)} articles from {source}")
            
            # Process the first 10 articles from each source (these are usually the most recent)
            for article in articles[:10]:
                try:
                    title = ' '.join(article['title'].lower().split())
                    if title in seen_titles:
                        continue

                    # Add timestamp if not present
                    if 'timestamp' not in article:
                        article['timestamp'] = today.isoformat()
                    
                    # Check if article is from today or yesterday
                    article_time = datetime.fromisoformat(article['timestamp'])
                    article_date = article_time.date()
                    
                    # Skip if article doesn't match the requested day
                    if today_only and article_date != today.date():
                                continue
                    if not today_only and article_date != yesterday.date():
                                continue
                    
                    # Always check for stock mentions in title and summary
                    combined_text = f"{article['title']} {article.get('summary', '')}"
                    mentioned_stocks = self.extract_stock_symbols(combined_text)
                    
                    # Get stock data for all mentioned stocks
                    stock_data = {}
                    for symbol in mentioned_stocks:
                        data = self.get_stock_data(symbol)
                        metrics = self.get_stock_metrics(data)
                        if metrics:
                            stock_data[symbol] = metrics
                    
                    seen_titles.add(title)
                    
                    # Create result with stock data
                    result = {
                        'article': article,
                        'article_title': article['title'],
                        'article_timestamp': article['timestamp'],
                        'affected_stocks': mentioned_stocks,
                        'sentiment': self.analyze_sentiment(combined_text),
                        'stock_data': stock_data
                    }
                    
                    results.append(result)
                        
                except Exception as e:
                    self.logger.error(f"Error processing article: {str(e)}")
                    continue
                    
        return results

    def display_recent_news(self, results, time_period):
        """Display news in a modern, clean format with enhanced visual hierarchy"""
        if not results:
            print(f"\n\033[91m╔═ No {time_period.lower()} market news found ═╗\033[0m")
            return

        # Clear screen and show header
        print("\033[2J\033[H", end="")
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        print("\033[1;38;5;39m╔════════════════════════════════════════════════════════════════════╗")
        print(f"║  MARKET PULSE - {time_period:<44}║")
        print(f"║  Last Update: {now:<47}║")
        print("╚════════════════════════════════════════════════════════════════════╝\033[0m\n")

        # Group articles by impact level based on stock movements and sentiment
        high_impact = []
        medium_impact = []
        low_impact = []

        for result in results:
            impact_score = 0
            # Calculate impact based on stock movements and sentiment
            if result.get('affected_stocks'):
                max_move = 0
                for symbol, data in result.get('stock_data', {}).items():
                    max_move = max(max_move, abs(data.get('daily_change_pct', 0)))
                
                if max_move > 5:  # >5% move
                    impact_score += 3
                elif max_move > 2:  # >2% move
                    impact_score += 2
                elif max_move > 1:  # >1% move
                    impact_score += 1

            # Add sentiment impact
            sentiment = abs(result.get('sentiment', {}).get('polarity', 0))
            if sentiment > 0.6:
                impact_score += 2
            elif sentiment > 0.3:
                impact_score += 1

            # Categorize based on total impact score
            if impact_score >= 4:
                high_impact.append(result)
            elif impact_score >= 2:
                medium_impact.append(result)
            else:
                low_impact.append(result)

        # Display articles by impact category
        if high_impact:
            print("\033[1;38;5;196m▓▒░ HIGH IMPACT NEWS ░▒▓\033[0m")
            self._display_category(high_impact)

        if medium_impact:
            print("\n\033[1;38;5;214m▓▒░ SIGNIFICANT DEVELOPMENTS ░▒▓\033[0m")
            self._display_category(medium_impact)

        if low_impact:
            print("\n\033[1;38;5;109m▓▒░ MARKET UPDATES ░▒▓\033[0m")
            self._display_category(low_impact)

    def _display_category(self, articles):
        """Display articles with enhanced visual formatting"""
        for result in articles:
            # Format timestamp
            try:
                time_str = datetime.fromisoformat(result['article_timestamp']).strftime('%H:%M')
            except (ValueError, TypeError):
                time_str = "N/A"

            # Get sentiment indicators
            sentiment = result['sentiment']
            sentiment_color = "\033[38;5;82m"  # Green
            sentiment_indicator = "▲"
            if sentiment['polarity'] < -0.2:
                sentiment_color = "\033[38;5;196m"  # Red
                sentiment_indicator = "▼"
            elif -0.2 <= sentiment['polarity'] <= 0.2:
                sentiment_color = "\033[38;5;249m"  # Gray
                sentiment_indicator = "►"

            # Display article header
            print(f"\n\033[38;5;239m╭──────────────────────────────────────────────────────────╮")
            print(f"│ \033[38;5;246m{time_str} {sentiment_color}{sentiment_indicator}\033[0m")
            print(f"│ \033[1;37m{result['article_title']}\033[38;5;239m")
            print(f"├──────────────────────────────────────────────────────────╯\033[0m")

            # Display affected stocks if present
            affected_stocks = result.get('affected_stocks', [])
            if affected_stocks:
                print("\033[38;5;239m│")
                for symbol in affected_stocks:
                    stock_data = result['stock_data'].get(symbol, {})
                    if stock_data:
                        price = stock_data.get('current_price', 0)
                        daily_change = stock_data.get('daily_change', 0)
                        daily_change_pct = stock_data.get('daily_change_pct', 0)
                        volume_change = stock_data.get('volume_change_pct', 0)
                        
                        # Color and arrow based on price change
                        if daily_change_pct >= 0:
                            price_color = "\033[38;5;82m"  # Green
                            arrow = "▲"
                else:
                            price_color = "\033[38;5;196m"  # Red
                            arrow = "▼"

                        # Stock symbol and current price
                        print(f"│ \033[1;37m{symbol:<6}\033[0m ${price:<7.2f} ", end='')
                        
                        # Price change
                        print(f"{price_color}{arrow} {abs(daily_change):>6.2f} ({abs(daily_change_pct):>5.2f}%)\033[0m", end='')
                        
                        # Volume indicator
                        if abs(volume_change) > 50:
                            print(f" \033[38;5;201m⚡ VOL {volume_change:>+4.0f}%\033[0m")  # Hot pink for very high volume
                        elif abs(volume_change) > 20:
                            print(f" \033[38;5;141m○ VOL {volume_change:>+4.0f}%\033[0m")  # Purple for high volume
                        else:
                            print()  # Just a newline

            # Display summary with market indicators
            if 'article' in result and 'summary' in result['article']:
                summary = result['article']['summary']
                if len(summary) > 120:
                    summary = summary[:117] + "..."

                # Market indicators
                indicators = []
                if any(term in summary.lower() for term in ['surge', 'jump', 'soar', 'rally']):
                    indicators.append('\033[38;5;82m↗\033[0m')
                if any(term in summary.lower() for term in ['drop', 'fall', 'plunge', 'decline']):
                    indicators.append('\033[38;5;196m↘\033[0m')
                if any(term in summary.lower() for term in ['merger', 'acquisition', 'deal']):
                    indicators.append('\033[38;5;214m⚡\033[0m')
                if any(term in summary.lower() for term in ['profit', 'earnings']):
                    indicators.append('\033[38;5;82m$\033[0m')
                if any(term in summary.lower() for term in ['loss', 'debt', 'bankrupt']):
                    indicators.append('\033[38;5;196m$\033[0m')
                if any(term in summary.lower() for term in ['crypto', 'bitcoin']):
                    indicators.append('\033[38;5;226m₿\033[0m')
                
                print("\033[38;5;239m│")
                if indicators:
                    print(f"│ {' '.join(indicators)} \033[38;5;246m{summary}\033[0m")
        else:
                    print(f"│ \033[38;5;246m{summary}\033[0m")
                
            print("\033[38;5;239m╰──────────────────────────────────────────────────────────╯\033[0m")

def check_dependencies():
    """Check if all required dependencies are installed"""
    try:
        import requests
        import yfinance
        import pandas
        import bs4
        import textblob
        return True
    except ImportError as e:
        print(f"\033[91mError: Missing required dependency: {str(e)}\033[0m")
        print("\nPlease install required dependencies using:")
        print("pip install requests yfinance pandas beautifulsoup4 textblob")
        return False

    def main():
    """Main function for running the market news analyzer"""
    if not check_dependencies():
        return

    try:
        analyzer = MarketNewsAnalyzer()
        
        while True:
            print("\nMarket News Analyzer")
            print("1. Get recent news (Today and Yesterday)")
            print("2. Exit")
            
            choice = input("\nEnter your choice (1-2): ")
            
            if choice == '1':
                print("\nFetching recent market news...")
                today_results = analyzer.get_recent_news(today_only=True)
                analyzer.display_recent_news(today_results, "Today's")
                
                print("\nFetching yesterday's news...")
                yesterday_results = analyzer.get_recent_news(today_only=False)
                analyzer.display_recent_news(yesterday_results, "Yesterday's")
            elif choice == '2':
                print("\nExiting Market News Analyzer. Goodbye!")
                break
            else:
                print("\nInvalid choice. Please enter 1 or 2.")
    except Exception as e:
        print(f"\033[91mError: {str(e)}\033[0m")
        return

    if __name__ == '__main__':
        main()
