import os
import json
import sys
import re
import time
import random
import logging
from datetime import datetime, timedelta
import aiohttp
import asyncio
import pandas as pd
from bs4 import BeautifulSoup
from textblob import TextBlob
from typing import Dict, Optional, List
import pickle
import ta
from aiohttp import ClientTimeout
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
import numpy as np

class MarketNewsAnalyzer:
    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Accept': 'application/json',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache'
        }
        
        # Alpha Vantage API configuration
        self.alpha_vantage_key = os.getenv('ALPHA_VANTAGE_KEY', 'demo')  # Use demo key if not set
        if self.alpha_vantage_key == 'demo':
            print("\n\033[93mWarning: Using demo Alpha Vantage API key. Features will be limited and some data may be delayed.\033[0m")
            # For demo key, we'll use longer cache duration to avoid hitting rate limits
            self.stock_cache_duration = timedelta(hours=24)  # 24 hours cache for demo key
            self.min_request_interval = 60  # 60 seconds between requests for demo key
        else:
            self.stock_cache_duration = timedelta(minutes=15)  # 15 minutes for paid key
            self.min_request_interval = 12  # 12 seconds between requests for paid key
            
        self.alpha_vantage_url = 'https://www.alphavantage.co/query'
        
        # Setup data directories
        self.data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')
        os.makedirs(self.data_dir, exist_ok=True)
        
        # Create offline data directory
        self.offline_dir = os.path.join(self.data_dir, 'offline')
        os.makedirs(self.offline_dir, exist_ok=True)
        
        # Stock data directory
        self.stock_data_dir = os.path.join(self.offline_dir, 'stocks')
        os.makedirs(self.stock_data_dir, exist_ok=True)
        
        # News data directory
        self.news_data_dir = os.path.join(self.offline_dir, 'news')
        os.makedirs(self.news_data_dir, exist_ok=True)
        
        # Cache directory
        self.cache_dir = os.path.join(self.data_dir, 'cache')
        os.makedirs(self.cache_dir, exist_ok=True)
        
        # Stock cache directory
        self.stock_cache_dir = os.path.join(self.data_dir, 'stock_cache')
        os.makedirs(self.stock_cache_dir, exist_ok=True)
        
        # Add tracked stocks with their sectors
        self.tracked_stocks = {
            'AAPL': {'name': 'Apple Inc.', 'sector': 'Technology'},
            'MSFT': {'name': 'Microsoft Corp.', 'sector': 'Technology'},
            'GOOGL': {'name': 'Alphabet Inc.', 'sector': 'Technology'},
            'AMZN': {'name': 'Amazon.com Inc.', 'sector': 'Consumer Cyclical'},
            'META': {'name': 'Meta Platforms Inc.', 'sector': 'Technology'},
            'TSLA': {'name': 'Tesla Inc.', 'sector': 'Automotive'},
            'JPM': {'name': 'JPMorgan Chase & Co.', 'sector': 'Financial Services'},
            'V': {'name': 'Visa Inc.', 'sector': 'Financial Services'},
            'JNJ': {'name': 'Johnson & Johnson', 'sector': 'Healthcare'},
            'WMT': {'name': 'Walmart Inc.', 'sector': 'Consumer Defensive'}
        }  # Reduced list for offline mode

        # Add price alert thresholds
        self.price_alerts = {
            'AAPL': {'upper': 220.0, 'lower': 200.0},
            'MSFT': {'upper': 420.0, 'lower': 380.0},
            'GOOGL': {'upper': 150.0, 'lower': 130.0},
            'AMZN': {'upper': 180.0, 'lower': 160.0},
            'META': {'upper': 500.0, 'lower': 450.0},
            'TSLA': {'upper': 200.0, 'lower': 180.0},
            'JPM': {'upper': 180.0, 'lower': 160.0},
            'V': {'upper': 280.0, 'lower': 260.0},
            'JNJ': {'upper': 160.0, 'lower': 140.0},
            'WMT': {'upper': 180.0, 'lower': 160.0}
        }  # Reduced list for offline mode
        
        # Setup logging
        self.setup_logging()
        
        # Initialize ThreadPoolExecutor with dynamic sizing
        cpu_count = os.cpu_count() or 4
        self.thread_pool = ThreadPoolExecutor(
            max_workers=min(cpu_count * 2, 8),  # Scale with CPU cores, max 8 workers
            thread_name_prefix='MarketAnalyzer'
        )
        self.thread_pool_tasks = 0
        self._thread_pool_lock = asyncio.Lock()
        
        # Cache settings
        self.max_cache_size = 1000  # Maximum number of items in cache
        self.cache_cleanup_threshold = 0.8  # Cleanup when 80% full
        self._indicator_cache = {}
        self._cache_lock = asyncio.Lock()
        self._last_cache_cleanup = datetime.now()
        
        # Generate sample data if it doesn't exist
        self._ensure_sample_data()
        
        # Initialize rate limiting
        self.last_request_time = {}
        
        # Initialize aiohttp session in the event loop
        self.session = None
        self.timeout = ClientTimeout(total=30)  # Increased timeout for demo key
        
        # Track API calls
        self.api_calls = 0
        self.last_api_reset = datetime.now()

    def setup_logging(self):
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(os.path.join(self.data_dir, 'market_analyzer.log')),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)

    async def setup_session(self):
        """Setup aiohttp session with connection pooling and recovery"""
        try:
            if self.session is None or self.session.closed:
                connector = aiohttp.TCPConnector(limit=10, ttl_dns_cache=300)
                self.session = aiohttp.ClientSession(
                    headers=self.headers,
                    timeout=self.timeout,
                    connector=connector
                )
                self.logger.info("Session initialized successfully")
            elif not self.session.closed:
                self.logger.debug("Reusing existing session")
                return
        except Exception as e:
            self.logger.error(f"Error setting up session: {str(e)}")
            # Force cleanup of any partial session
            await self.close_session()
            raise
            
    async def close_session(self):
        """Close aiohttp session with proper cleanup"""
        if self.session:
            try:
                if not self.session.closed:
                    await self.session.close()
                # Wait for all connections to close
                await asyncio.sleep(0.25)
            except Exception as e:
                self.logger.error(f"Error closing session: {str(e)}")
            finally:
                self.session = None
                self.logger.info("Session closed and cleaned up")

    def fetch_news(self, source):
        try:
            if source in self.last_request_time:
                time_since_last_request = (datetime.now() - self.last_request_time[source]).total_seconds()
                if time_since_last_request < self.min_request_interval:
                    time.sleep(self.min_request_interval - time_since_last_request)

            self.logger.info(f"Fetching news from {source}")
            response = self.session.get(
                self.news_sources[source],
                timeout=15
            )
            response.raise_for_status()
            self.last_request_time[source] = datetime.now()
            return response.text
        except Exception as e:
            self.logger.error(f"Error fetching {source}: {str(e)}")
            return None

    async def get_recent_news_batch(self, symbols: List[str], today_only=True) -> Dict[str, List]:
        """Get news for multiple symbols concurrently with batching"""
        try:
            results = {}
            batch_size = 5 if self.alpha_vantage_key == 'demo' else 20
            
            for i in range(0, len(symbols), batch_size):
                batch = symbols[i:i + batch_size]
                
                # Prepare API request for batch
                params = {
                    'function': 'NEWS_SENTIMENT',
                    'sort': 'LATEST',
                    'limit': 50,
                    'tickers': ','.join(batch)
                }
                
                # Make API request with rate limiting
                data = await self._make_alpha_vantage_request(params)
                if not data or 'feed' not in data:
                    self.logger.error(f"No news feed in Alpha Vantage response for batch {i//batch_size + 1}")
                    continue
                
                # Process articles
                for article in data['feed']:
                    try:
                        # Parse the time
                        article_time = datetime.strptime(article['time_published'], '%Y%m%dT%H%M%S')
                        
                        # Filter by date if today_only is True
                        if today_only and article_time.date() < datetime.now().date():
                            continue
                        
                        # Create result with enhanced information
                        result = {
                            'article': {
                                'title': article['title'],
                                'summary': article['summary'],
                                'source': article['source'],
                                'url': article['url'],
                                'time': article_time.strftime('%Y-%m-%d %H:%M:%S')
                            },
                            'sentiment': {
                                'polarity': float(article.get('overall_sentiment_score', 0)),
                                'subjectivity': 0.5,
                                'assessment': self._get_sentiment_assessment(float(article.get('overall_sentiment_score', 0)))
                            },
                            'timestamp': datetime.now().isoformat()
                        }
                        
                        # Add ticker-specific sentiment
                        if 'ticker_sentiment' in article:
                            for ticker_data in article['ticker_sentiment']:
                                ticker = ticker_data['ticker']
                                if ticker in batch:
                                    if ticker not in results:
                                        results[ticker] = []
                                    result['ticker_sentiment'] = {
                                        'relevance': float(ticker_data.get('relevance_score', 0)),
                                        'sentiment': float(ticker_data.get('ticker_sentiment_score', 0))
                                    }
                                    results[ticker].append(result)
                                    
                    except Exception as e:
                        self.logger.error(f"Error processing article: {str(e)}")
                        continue
                
                # Wait between batches for demo key
                if self.alpha_vantage_key == 'demo' and i + batch_size < len(symbols):
                    await asyncio.sleep(60)
            
            # Sort articles by time for each symbol
            for symbol in results:
                results[symbol] = sorted(results[symbol], key=lambda x: x['article']['time'], reverse=True)
            
            return results
            
        except Exception as e:
            self.logger.error(f"Error fetching batch news: {str(e)}")
            return {}

    async def get_recent_news(self, today_only=True):
        """Get news from Alpha Vantage API with sentiment analysis"""
        try:
            # Use batch processing for better performance
            symbols = list(self.tracked_stocks.keys())
            results_by_symbol = await self.get_recent_news_batch(symbols, today_only)
            
            # Combine and sort all results
            all_results = []
            for symbol_results in results_by_symbol.values():
                all_results.extend(symbol_results)
            
            return sorted(all_results, key=lambda x: x['article']['time'], reverse=True)
            
        except Exception as e:
            self.logger.error(f"Error fetching news: {str(e)}")
            return []

    def _get_sentiment_assessment(self, sentiment_score: float) -> str:
        """Convert Alpha Vantage sentiment score to assessment"""
        if sentiment_score >= 0.35:
            return 'positive'
        elif sentiment_score <= -0.35:
            return 'negative'
        return 'neutral'

    def parse_news(self, html_content, source):
        if not html_content:
            return []

        self.logger.info(f"Parsing {source} content")
        soup = BeautifulSoup(html_content, 'html.parser')
        articles = []

        try:
            if source == 'ft':
                articles = self._parse_ft(soup)
            elif source == 'marketwatch':
                articles = self._parse_marketwatch(soup)
            elif source == 'yahoo_finance':
                articles = self._parse_yahoo_finance(soup)
            elif source == 'cnbc':
                articles = self._parse_cnbc(soup)
        except Exception as e:
            self.logger.error(f"Error parsing {source}: {str(e)}")

        return articles

    def _parse_ft(self, soup):
        articles = []
        for article in soup.select('div.o-teaser'):
            try:
                title = article.select_one('a.js-teaser-heading-link').text.strip()
                summary = article.select_one('p.o-teaser__standfirst').text.strip()
                link = article.select_one('a.js-teaser-heading-link')['href']
                if not link.startswith('http'):
                    link = 'https://www.ft.com' + link
                
                articles.append({
                    'title': title,
                    'summary': summary,
                    'link': link,
                    'source': 'Financial Times'
                })
            except Exception as e:
                self.logger.debug(f"Error parsing FT article: {str(e)}")
                continue
        return articles

    def _parse_marketwatch(self, soup):
        articles = []
        for article in soup.select('div.article__content'):
            try:
                title = article.select_one('h3.article__headline').text.strip()
                summary = article.select_one('p.article__summary').text.strip()
                link = article.select_one('a.link')['href']
                if not link.startswith('http'):
                    link = 'https://www.marketwatch.com' + link
                
                articles.append({
                    'title': title,
                    'summary': summary,
                    'link': link,
                    'source': 'MarketWatch'
                })
            except Exception as e:
                self.logger.debug(f"Error parsing MarketWatch article: {str(e)}")
                continue
        return articles

    def _parse_yahoo_finance(self, soup):
        articles = []
        for article in soup.select('div.Cf'):
            try:
                title = article.select_one('h3 a').text.strip()
                summary = article.select_one('p').text.strip()
                link = article.select_one('a')['href']
                if not link.startswith('http'):
                    link = 'https://finance.yahoo.com' + link
                
                articles.append({
                    'title': title,
                    'summary': summary,
                    'link': link,
                    'source': 'Yahoo Finance'
                })
            except Exception as e:
                self.logger.debug(f"Error parsing Yahoo Finance article: {str(e)}")
                continue
        return articles

    def _parse_cnbc(self, soup):
        articles = []
        for article in soup.select('div.Card-standardBreakerCard'):
            try:
                title = article.select_one('a.Card-title').text.strip()
                summary = article.select_one('div.Card-description').text.strip()
                link = article.select_one('a.Card-title')['href']
                if not link.startswith('http'):
                    link = 'https://www.cnbc.com' + link
                
                articles.append({
                    'title': title,
                    'summary': summary,
                    'link': link,
                    'source': 'CNBC'
                })
            except Exception as e:
                self.logger.debug(f"Error parsing CNBC article: {str(e)}")
                continue
        return articles

    def analyze_sentiment(self, text):
        try:
            analysis = TextBlob(text)
            sentiment = {
                'polarity': analysis.sentiment.polarity,
                'subjectivity': analysis.sentiment.subjectivity,
                'assessment': 'neutral'
            }
            
            if sentiment['polarity'] > 0.2:
                sentiment['assessment'] = 'positive'
            elif sentiment['polarity'] < -0.2:
                sentiment['assessment'] = 'negative'
            
            return sentiment
        except Exception as e:
            self.logger.error(f"Error in sentiment analysis: {str(e)}")
            return {'polarity': 0, 'subjectivity': 0, 'assessment': 'neutral'}

    def display_recent_news(self, results, time_period):
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

        # Group by impact
        high_impact = []
        medium_impact = []
        low_impact = []

        for result in results:
            sentiment = abs(result['sentiment']['polarity'])
            if sentiment > 0.5:
                high_impact.append(result)
            elif sentiment > 0.2:
                medium_impact.append(result)
            else:
                low_impact.append(result)

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
        for result in articles:
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
            print(f"│ \033[38;5;246m{result['article']['source']} {sentiment_color}{sentiment_indicator}\033[0m")
            print(f"│ \033[1;37m{result['article']['title']}\033[38;5;239m")
            print(f"├──────────────────────────────────────────────────────────╯\033[0m")

            # Display summary with market indicators
            if 'summary' in result['article']:
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

    def display_technical_analysis(self, symbol: str, analysis: Dict):
        """Display technical analysis results in a formatted way"""
        if not analysis:
            print(f"\n\033[91m╔═ No technical analysis data available for {symbol} ═╗\033[0m")
            return
            
        indicators = analysis['indicators']
        signals = analysis['signals']
        
        # Color mapping for signals
        signal_colors = {
            'strong_buy': '\033[1;32m',  # Bright Green
            'buy': '\033[32m',           # Green
            'neutral': '\033[33m',       # Yellow
            'sell': '\033[31m',          # Red
            'strong_sell': '\033[1;31m'  # Bright Red
        }
        
        print(f"\n\033[1;38;5;39m╔════════ Technical Analysis: {symbol} ════════╗")
        print(f"║  Last Updated: {analysis['last_updated'][:19]}")
        print("╠══════════════════════════════════════════╣")
        
        # Display Overall Signal
        overall_signal = signals['overall']
        signal_color = signal_colors.get(overall_signal, '\033[0m')
        print(f"║  Overall Signal: {signal_color}{overall_signal.upper()}\033[0m")
        
        # Display Component Signals
        print("║")
        print("║  Component Signals:")
        for component in ['trend', 'momentum', 'volatility', 'volume']:
            signal = signals[component]
            color = signal_colors.get(signal, '\033[0m')
            print(f"║    {component.title():10}: {color}{signal.upper():10}\033[0m")
            
        # Display Key Indicators
        print("║")
        print("║  Key Indicators:")
        print(f"║    RSI       : {indicators['RSI']:.2f}")
        print(f"║    MACD      : {indicators['MACD']:.2f}")
        print(f"║    ADX       : {indicators['ADX']:.2f}")
        print(f"║    SMA (20)  : {indicators['SMA_20']:.2f}")
        print(f"║    EMA (20)  : {indicators['EMA_20']:.2f}")
        
        # Display Bollinger Bands
        print("║")
        print("║  Bollinger Bands:")
        print(f"║    Upper     : {indicators['BB_upper']:.2f}")
        print(f"║    Middle    : {indicators['BB_middle']:.2f}")
        print(f"║    Lower     : {indicators['BB_lower']:.2f}")
        
        print("╚══════════════════════════════════════════╝")

    async def fetch_stock_data_batch(self, symbols: List[str], days: int = 5) -> Dict[str, Optional[pd.DataFrame]]:
        """Fetch stock data for multiple symbols concurrently"""
        await self.setup_session()
        tasks = []
        results = {}
        
        # Group symbols into batches of 5 to respect rate limits
        batch_size = 5
        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i + batch_size]
            tasks.extend([self.fetch_stock_data(symbol, days) for symbol in batch])
            if i + batch_size < len(symbols):
                await asyncio.sleep(12)  # Wait between batches
                
        # Execute all tasks concurrently
        completed = await asyncio.gather(*tasks)
        
        # Map results to symbols
        return dict(zip(symbols, completed))

    async def _make_alpha_vantage_request(self, params: dict) -> Optional[dict]:
        """Make a rate-limited request to Alpha Vantage API"""
        try:
            # Check and reset API call counter
            now = datetime.now()
            if (now - self.last_api_reset).total_seconds() >= 60:
                self.api_calls = 0
                self.last_api_reset = now
                
            # Check rate limits
            if self.alpha_vantage_key == 'demo' and self.api_calls >= 5:
                self.logger.warning("Demo API key rate limit reached (5 calls per minute). Waiting...")
                await asyncio.sleep(60 - (now - self.last_api_reset).total_seconds())
                self.api_calls = 0
                self.last_api_reset = datetime.now()
                
            # Ensure session is setup
            await self.setup_session()
            
            # Add API key to params
            params['apikey'] = self.alpha_vantage_key
            
            # Make request with retries
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    async with self.session.get(self.alpha_vantage_url, params=params) as response:
                        self.api_calls += 1
                        
                        if response.status == 200:
                            data = await response.json()
                            
                            # Check for API error messages
                            if "Error Message" in data:
                                self.logger.error(f"Alpha Vantage API error: {data['Error Message']}")
                                return None
                            elif "Note" in data and "API call frequency" in data["Note"]:
                                self.logger.warning("Rate limit warning from Alpha Vantage")
                                if attempt < max_retries - 1:
                                    await asyncio.sleep(self.min_request_interval)
                                    continue
                            return data
                        else:
                            self.logger.error(f"Alpha Vantage API error: {response.status} - {await response.text()}")
                            return None
                            
                except Exception as e:
                    self.logger.error(f"Request error: {str(e)}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(2 ** attempt)  # Exponential backoff
                        continue
                    return None
                    
        except Exception as e:
            self.logger.error(f"Error making Alpha Vantage request: {str(e)}")
            return None

    async def fetch_stock_data(self, symbol: str, days: int = 5) -> Optional[pd.DataFrame]:
        """Fetch stock price data with enhanced error handling and caching"""
        cache_key = f"{symbol}_{days}"
        cache_file = os.path.join(self.cache_dir, f'stock_cache_{cache_key}.pkl')
        
        # Check cache first with async file operations
        try:
            if os.path.exists(cache_file):
                cache_time = os.path.getmtime(cache_file)
                if (datetime.now() - datetime.fromtimestamp(cache_time)) < self.stock_cache_duration:
                    loop = asyncio.get_event_loop()
                    df = await loop.run_in_executor(self.thread_pool, self._read_cache, cache_file)
                    if df is not None:
                        self.logger.info(f"Using cached stock data for {symbol}")
                        return df
        except Exception as e:
            self.logger.warning(f"Error reading cache for {symbol}: {str(e)}")

        # Fetch new data from Alpha Vantage
        try:
            self.logger.info(f"Fetching stock data for {symbol}")
            
            # Make API request
            params = {
                'function': 'TIME_SERIES_DAILY',
                'symbol': symbol,
                'outputsize': 'compact'  # Last 100 data points
            }
            
            data = await self._make_alpha_vantage_request(params)
            if not data or 'Time Series (Daily)' not in data:
                return None
                
            # Process data in thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            df = await loop.run_in_executor(
                self.thread_pool,
                self._process_stock_data,
                data['Time Series (Daily)'],
                days
            )
            
            # Save to cache in background
            if df is not None:
                asyncio.create_task(self._save_cache(cache_file, df))
            
            return df
            
        except Exception as e:
            self.logger.error(f"Error fetching stock data for {symbol}: {str(e)}")
            return None

    def _read_cache(self, cache_file: str) -> Optional[pd.DataFrame]:
        """Read cache file in a separate thread"""
        try:
            with open(cache_file, 'rb') as f:
                return pickle.load(f)
        except Exception:
            return None

    async def _save_cache(self, cache_file: str, df: pd.DataFrame):
        """Save cache file asynchronously"""
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                self.thread_pool,
                lambda: df.to_pickle(cache_file)
            )
        except Exception as e:
            self.logger.warning(f"Error saving cache: {str(e)}")

    async def _execute_in_thread_pool(self, func, *args):
        """Execute a function in thread pool with proper resource management"""
        try:
            async with self._thread_pool_lock:
                self.thread_pool_tasks += 1
            
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(self.thread_pool, func, *args)
            return result
        finally:
            async with self._thread_pool_lock:
                self.thread_pool_tasks -= 1

    def _process_stock_data(self, time_series_data: dict, days: int) -> Optional[pd.DataFrame]:
        """Process stock data in a separate thread"""
        try:
            # Convert to DataFrame
            df = pd.DataFrame.from_dict(time_series_data, orient='index')
            
            # Use more efficient operations
            df.index = pd.to_datetime(df.index)
            df = df.sort_index()
            
            # Optimize column operations
            column_map = {
                '1. open': 'Open',
                '2. high': 'High',
                '3. low': 'Low',
                '4. close': 'Close',
                '5. volume': 'Volume'
            }
            df = df.rename(columns=column_map)
            
            # Convert to numeric more efficiently
            for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            # Optimize date filtering
            end_date = pd.Timestamp.now()
            start_date = end_date - pd.Timedelta(days=days)
            df = df[df.index >= start_date]
            
            return df
            
        except Exception as e:
            self.logger.error(f"Error processing stock data: {str(e)}")
            return None

    async def analyze_technical_indicators_batch(self, symbols: List[str]) -> Dict[str, Dict]:
        """Analyze technical indicators for multiple stocks concurrently"""
        # Fetch all stock data concurrently
        stock_data = await self.fetch_stock_data_batch(symbols, days=30)
        
        # Process technical analysis in parallel
        tasks = []
        for symbol, data in stock_data.items():
            if data is not None and not data.empty:
                tasks.append(self.analyze_technical_indicators(symbol, data))
                
        # Execute all tasks concurrently
        results = await asyncio.gather(*tasks)
        
        # Map results to symbols
        return {symbol: result for symbol, result in zip(symbols, results) if result is not None}

    async def analyze_technical_indicators(self, symbol: str, hist: Optional[pd.DataFrame] = None) -> Optional[Dict]:
        """Calculate technical indicators for a stock"""
        try:
            # Trigger cache cleanup if needed
            if len(self._indicator_cache) > self.max_cache_size * self.cache_cleanup_threshold:
                await self._cleanup_cache()
            
            # Check cache first
            cache_key = f"{symbol}_tech_{datetime.now().strftime('%Y%m%d_%H')}"
            if cache_key in self._indicator_cache:
                return self._indicator_cache[cache_key]
            
            # Fetch data if not provided
            if hist is None:
                hist = await self.fetch_stock_data(symbol, days=30)
            
            if hist is None or hist.empty:
                return None
            
            # Calculate indicators in thread pool
            indicators = await self._execute_in_thread_pool(self._calculate_indicators, hist)
            
            # Calculate signals
            current_price = hist['Close'].iloc[-1]
            signals = await self._execute_in_thread_pool(
                self._calculate_signals,
                indicators,
                current_price,
                hist
            )
            
            result = {
                'indicators': indicators,
                'signals': signals,
                'last_updated': datetime.now().isoformat()
            }
            
            # Cache the result
            async with self._cache_lock:
                self._indicator_cache[cache_key] = result
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error calculating technical indicators for {symbol}: {str(e)}")
            return None

    def _calculate_indicators(self, hist: pd.DataFrame) -> Dict:
        """Calculate technical indicators in a separate thread"""
        indicators = {}
        
        # Moving Averages
        indicators['SMA_20'] = ta.trend.sma_indicator(hist['Close'], window=20).iloc[-1]
        indicators['EMA_20'] = ta.trend.ema_indicator(hist['Close'], window=20).iloc[-1]
        
        # Trend Indicators
        indicators['MACD'] = ta.trend.macd_diff(hist['Close']).iloc[-1]
        indicators['RSI'] = ta.momentum.rsi(hist['Close']).iloc[-1]
        
        # Volatility Indicators
        indicators['BB_upper'] = ta.volatility.bollinger_hband(hist['Close']).iloc[-1]
        indicators['BB_lower'] = ta.volatility.bollinger_lband(hist['Close']).iloc[-1]
        indicators['BB_middle'] = ta.volatility.bollinger_mavg(hist['Close']).iloc[-1]
        
        # Volume Indicators
        indicators['OBV'] = ta.volume.on_balance_volume(hist['Close'], hist['Volume']).iloc[-1]
        indicators['Volume_SMA'] = hist['Volume'].rolling(window=20).mean().iloc[-1]
        
        # Additional Trend Indicators
        indicators['ADX'] = ta.trend.adx(hist['High'], hist['Low'], hist['Close']).iloc[-1]
        indicators['CCI'] = ta.trend.cci(hist['High'], hist['Low'], hist['Close']).iloc[-1]
        
        return indicators

    def _calculate_signals(self, indicators: Dict, current_price: float, hist: pd.DataFrame) -> Dict:
        """Calculate trading signals in a separate thread"""
        signals = {
            'trend': self._analyze_trend(indicators, current_price),
            'momentum': self._analyze_momentum(indicators),
            'volatility': self._analyze_volatility(indicators, current_price),
            'volume': self._analyze_volume(indicators, hist)
        }
        
        # Calculate overall signal
        signal_scores = {
            'strong_buy': 2,
            'buy': 1,
            'neutral': 0,
            'sell': -1,
            'strong_sell': -2
        }
        
        total_score = sum(signal_scores.get(signals[k], 0) for k in signals.keys())
        
        if total_score >= 4:
            signals['overall'] = 'strong_buy'
        elif total_score >= 2:
            signals['overall'] = 'buy'
        elif total_score <= -4:
            signals['overall'] = 'strong_sell'
        elif total_score <= -2:
            signals['overall'] = 'sell'
        else:
            signals['overall'] = 'neutral'
            
        return signals

    def _analyze_trend(self, indicators: Dict, current_price: float) -> str:
        """Analyze trend indicators"""
        trend_score = 0
        
        # Check Moving Averages
        if current_price > indicators['SMA_20']:
            trend_score += 1
        if current_price > indicators['EMA_20']:
            trend_score += 1
            
        # Check MACD
        if indicators['MACD'] > 0:
            trend_score += 1
            
        # Check ADX (>25 indicates strong trend)
        if indicators['ADX'] > 25:
            if current_price > indicators['SMA_20']:
                trend_score += 1
            else:
                trend_score -= 1
                
        # Return signal based on trend score
        if trend_score >= 3:
            return 'strong_buy'
        elif trend_score >= 1:
            return 'buy'
        elif trend_score <= -3:
            return 'strong_sell'
        elif trend_score <= -1:
            return 'sell'
        return 'neutral'
        
    def _analyze_momentum(self, indicators: Dict) -> str:
        """Analyze momentum indicators"""
        # RSI Analysis
        rsi = indicators['RSI']
        
        if rsi >= 70:
            return 'strong_sell'  # Overbought
        elif rsi <= 30:
            return 'strong_buy'  # Oversold
        elif rsi >= 60:
            return 'sell'
        elif rsi <= 40:
            return 'buy'
        return 'neutral'
        
    def _analyze_volatility(self, indicators: Dict, current_price: float) -> str:
        """Analyze volatility indicators"""
        # Bollinger Bands Analysis
        bb_position = (current_price - indicators['BB_lower']) / (indicators['BB_upper'] - indicators['BB_lower'])
        
        if bb_position >= 1:
            return 'strong_sell'  # Price at or above upper band
        elif bb_position <= 0:
            return 'strong_buy'  # Price at or below lower band
        elif bb_position >= 0.8:
            return 'sell'
        elif bb_position <= 0.2:
            return 'buy'
        return 'neutral'
        
    def _analyze_volume(self, indicators: Dict, hist: pd.DataFrame) -> str:
        """Analyze volume indicators"""
        current_volume = hist['Volume'].iloc[-1]
        volume_sma = indicators['Volume_SMA']
        
        volume_score = 0
        
        # Volume trend
        if current_volume > volume_sma * 1.5:
            volume_score += 1
        elif current_volume < volume_sma * 0.5:
            volume_score -= 1
            
        # OBV trend
        obv_change = (indicators['OBV'] - hist['Volume'].iloc[-2]) / hist['Volume'].iloc[-2]
        if obv_change > 0.05:
            volume_score += 1
        elif obv_change < -0.05:
            volume_score -= 1
            
        # Return signal based on volume score
        if volume_score >= 2:
            return 'strong_buy'
        elif volume_score == 1:
            return 'buy'
        elif volume_score <= -2:
            return 'strong_sell'
        elif volume_score == -1:
            return 'sell'
        return 'neutral'

    def _ensure_sample_data(self):
        """Generate sample data for offline mode if it doesn't exist"""
        try:
            # Generate sample stock data
            for symbol in self.tracked_stocks:
                stock_file = os.path.join(self.stock_data_dir, f'{symbol}.csv')
                if not os.path.exists(stock_file):
                    self._generate_sample_stock_data(symbol)
                    
            # Generate sample news data
            news_file = os.path.join(self.news_data_dir, 'market_news.json')
            if not os.path.exists(news_file):
                self._generate_sample_news_data()
                
        except Exception as e:
            self.logger.error(f"Error generating sample data: {str(e)}")

    def _generate_sample_stock_data(self, symbol):
        """Generate realistic sample stock data"""
        try:
            # Generate 100 days of sample data
            dates = pd.date_range(end=datetime.now(), periods=100, freq='D')
            
            # Generate realistic price movements
            base_price = random.uniform(50, 500)
            volatility = random.uniform(0.01, 0.03)
            trend = random.uniform(-0.0002, 0.0002)
            
            prices = []
            current_price = base_price
            
            for _ in range(len(dates)):
                change = random.gauss(trend, volatility)
                current_price *= (1 + change)
                prices.append(current_price)
                
            # Create DataFrame
            df = pd.DataFrame({
                'Date': dates,
                'Open': prices,
                'High': [p * (1 + random.uniform(0, 0.02)) for p in prices],
                'Low': [p * (1 - random.uniform(0, 0.02)) for p in prices],
                'Close': [p * (1 + random.uniform(-0.01, 0.01)) for p in prices],
                'Volume': [int(random.uniform(1000000, 10000000)) for _ in prices]
            })
            
            df.set_index('Date', inplace=True)
            
            # Save to CSV
            stock_file = os.path.join(self.stock_data_dir, f'{symbol}.csv')
            df.to_csv(stock_file)
            
        except Exception as e:
            self.logger.error(f"Error generating sample stock data for {symbol}: {str(e)}")

    def _generate_sample_news_data(self):
        """Generate sample market news data"""
        try:
            # Sample news templates
            templates = [
                "{company} Reports Strong Q{quarter} Earnings, Beats Estimates",
                "{company} Announces New Product Launch",
                "{company} Expands Operations in {region}",
                "Market Analysis: {sector} Sector Shows Promise",
                "{company} Partners with {partner} for Innovation",
                "Industry Update: {sector} Trends and Forecasts",
                "{company} Stock {movement} After {event}",
                "Analysts {rating} {company} Stock",
                "Market Watch: {sector} Stocks in Focus",
                "{company} CEO Discusses Future Growth Plans"
            ]
            
            regions = ["Asia", "Europe", "North America", "Latin America", "Middle East"]
            movements = ["Surges", "Dips", "Rallies", "Stabilizes"]
            events = ["Earnings Report", "Product Launch", "Strategic Announcement", "Market Update"]
            ratings = ["Upgrade", "Maintain Buy Rating on", "Set New Target for", "Review"]
            
            news_data = {
                'feed': []
            }
            
            # Generate news for the last 2 days
            end_date = datetime.now()
            start_date = end_date - timedelta(days=2)
            
            for _ in range(50):  # Generate 50 news items
                company = random.choice(list(self.tracked_stocks.keys()))
                company_info = self.tracked_stocks[company]
                
                template = random.choice(templates)
                news_time = start_date + timedelta(
                    seconds=random.randint(0, int((end_date - start_date).total_seconds()))
                )
                
                title = template.format(
                    company=company_info['name'],
                    quarter=random.randint(1, 4),
                    region=random.choice(regions),
                    sector=company_info['sector'],
                    partner=random.choice([v['name'] for v in self.tracked_stocks.values()]),
                    movement=random.choice(movements),
                    event=random.choice(events),
                    rating=random.choice(ratings)
                )
                
                # Generate sentiment score
                sentiment_score = random.uniform(-1, 1)
                
                news_item = {
                    'title': title,
                    'summary': f"Sample news summary for {title}",
                    'source': random.choice(['Reuters', 'Bloomberg', 'CNBC', 'MarketWatch']),
                    'url': 'https://example.com/news',
                    'time_published': news_time.strftime('%Y%m%dT%H%M%S'),
                    'overall_sentiment_score': sentiment_score,
                    'ticker_sentiment': [{
                        'ticker': company,
                        'relevance_score': random.uniform(0.5, 1),
                        'ticker_sentiment_score': sentiment_score
                    }]
                }
                
                news_data['feed'].append(news_item)
            
            # Sort by time
            news_data['feed'].sort(key=lambda x: x['time_published'], reverse=True)
            
            # Save to JSON
            news_file = os.path.join(self.news_data_dir, 'market_news.json')
            with open(news_file, 'w') as f:
                json.dump(news_data, f, indent=2)
                
        except Exception as e:
            self.logger.error(f"Error generating sample news data: {str(e)}")

    async def _cleanup_cache(self):
        """Clean up old cache entries when cache size exceeds threshold"""
        try:
            async with self._cache_lock:
                current_size = len(self._indicator_cache)
                if current_size > self.max_cache_size * self.cache_cleanup_threshold:
                    self.logger.info(f"Cache cleanup triggered. Current size: {current_size}")
                    
                    # Sort by timestamp and keep most recent
                    sorted_cache = sorted(
                        self._indicator_cache.items(),
                        key=lambda x: datetime.fromisoformat(x[1]['last_updated']),
                        reverse=True
                    )
                    
                    # Keep only the most recent entries
                    keep_count = int(self.max_cache_size * 0.6)  # Keep 60% of max size
                    self._indicator_cache = dict(sorted_cache[:keep_count])
                    
                    self.logger.info(f"Cache cleaned up. New size: {len(self._indicator_cache)}")
                    self._last_cache_cleanup = datetime.now()
        except Exception as e:
            self.logger.error(f"Error during cache cleanup: {str(e)}")

async def main():
    """Main function with improved interface and technical analysis"""
    analyzer = None
    try:
        analyzer = MarketNewsAnalyzer()
        await analyzer.setup_session()
        
        # Show demo key limitations
        if analyzer.alpha_vantage_key == 'demo':
            print("\n\033[93mDemo Key Limitations:\033[0m")
            print("1. Maximum 5 API calls per minute")
            print("2. Some data may be delayed or limited")
            print("3. Longer cache duration (24 hours) to avoid rate limits")
            print("4. Some features may be restricted\n")
            print("To get full functionality, sign up for a free API key at:")
            print("https://www.alphavantage.co/support/#api-key\n")
            print("Then set the ALPHA_VANTAGE_KEY environment variable:\n")
            print("export ALPHA_VANTAGE_KEY=your_api_key\n")
            input("Press Enter to continue...")
        
        while True:
            print("\n\033[1;38;5;39m╔════════════════════════════════════════════╗")
            print("║           MARKET NEWS ANALYZER              ║")
            print("╚════════════════════════════════════════════╝\033[0m")
            print("1. View Today's News")
            print("2. View Yesterday's News")
            print("3. View Both Days' News")
            print("4. Technical Analysis")
            print("5. Compare Stocks")
            print("6. Check Price Alerts")
            print("7. Exit")
            
            choice = input("\nEnter your choice (1-7): ").strip()
            
            if choice == '1':
                print("\n\033[1;38;5;82m═══════════════ TODAY'S NEWS ═══════════════\033[0m")
                today_results = await analyzer.get_recent_news(today_only=True)
                analyzer.display_recent_news(today_results, "Today's")
                
            elif choice == '2':
                print("\n\033[1;38;5;214m═══════════════ YESTERDAY'S NEWS ═══════════════\033[0m")
                yesterday_results = await analyzer.get_recent_news(today_only=False)
                analyzer.display_recent_news(yesterday_results, "Yesterday's")
                
            elif choice == '3':
                print("\n\033[1;38;5;82m═══════════════ TODAY'S NEWS ═══════════════\033[0m")
                today_results = await analyzer.get_recent_news(today_only=True)
                analyzer.display_recent_news(today_results, "Today's")
                
                print("\nPress Enter to view yesterday's news...")
                input()
                
                print("\n\033[1;38;5;214m═══════════════ YESTERDAY'S NEWS ═══════════════\033[0m")
                yesterday_results = await analyzer.get_recent_news(today_only=False)
                analyzer.display_recent_news(yesterday_results, "Yesterday's")
                
            elif choice == '4':
                print("\n\033[1;38;5;39mTechnical Analysis\033[0m")
                print("\nEnter stock symbols separated by spaces (e.g., AAPL MSFT GOOGL):")
                symbols = input().strip().upper().split()
                valid_symbols = [s for s in symbols if s in analyzer.tracked_stocks]
                
                if not valid_symbols:
                    print("\n\033[91mNo valid stock symbols entered\033[0m")
                    print("\nTracked stocks:")
                    for s in sorted(analyzer.tracked_stocks.keys()):
                        print(f"  {s}: {analyzer.tracked_stocks[s]['name']}")
                    continue
                    
                if analyzer.alpha_vantage_key == 'demo' and len(valid_symbols) > 5:
                    print("\n\033[93mWarning: Demo API key is limited to 5 requests per minute.")
                    print("Processing first 5 symbols only. Please wait for rate limit reset.\033[0m")
                    valid_symbols = valid_symbols[:5]
                    
                print(f"\nAnalyzing {len(valid_symbols)} stocks...")
                analyses = await analyzer.analyze_technical_indicators_batch(valid_symbols)
                
                # Display comparisons
                print("\n\033[1;38;5;39m╔════════ Stock Comparison ════════╗\033[0m")
                for symbol in valid_symbols:
                    if symbol in analyses and analyses[symbol]:
                        print(f"\n{symbol}: {analyzer.tracked_stocks[symbol]['name']}")
                        analyzer.display_technical_analysis(symbol, analyses[symbol])
                        
            elif choice == '5':
                print("\nEnter stock symbols separated by spaces (e.g., AAPL MSFT GOOGL):")
                symbols = input().strip().upper().split()
                valid_symbols = [s for s in symbols if s in analyzer.tracked_stocks]
                
                if not valid_symbols:
                    print("\n\033[91mNo valid stock symbols entered\033[0m")
                    print("\nTracked stocks:")
                    for s in sorted(analyzer.tracked_stocks.keys()):
                        print(f"  {s}: {analyzer.tracked_stocks[s]['name']}")
                    continue
                    
                if analyzer.alpha_vantage_key == 'demo' and len(valid_symbols) > 5:
                    print("\n\033[93mWarning: Demo API key is limited to 5 requests per minute.")
                    print("Processing first 5 symbols only. Please wait for rate limit reset.\033[0m")
                    valid_symbols = valid_symbols[:5]
                    
                print(f"\nAnalyzing {len(valid_symbols)} stocks...")
                analyses = await analyzer.analyze_technical_indicators_batch(valid_symbols)
                
                # Display comparisons
                print("\n\033[1;38;5;39m╔════════ Stock Comparison ════════╗\033[0m")
                for symbol in valid_symbols:
                    if symbol in analyses and analyses[symbol]:
                        signal = analyses[symbol]['signals']['overall']
                        print(f"\n{symbol}: {analyzer.tracked_stocks[symbol]['name']}")
                        analyzer.display_technical_analysis(symbol, analyses[symbol])
                        
            elif choice == '6':
                print("\n\033[1;38;5;39m╔════════ Price Alerts ════════╗\033[0m")
                
                if analyzer.alpha_vantage_key == 'demo':
                    print("\n\033[93mWarning: Demo API key is limited to 5 requests per minute.")
                    print("Checking alerts in batches. Please wait...\033[0m")
                    
                    # Process alerts in batches of 5
                    symbols = list(analyzer.tracked_stocks.keys())
                    for i in range(0, len(symbols), 5):
                        batch = symbols[i:i+5]
                        if i > 0:
                            print("\nWaiting for rate limit reset...")
                            await asyncio.sleep(60)
                            
                        stock_data = await analyzer.fetch_stock_data_batch(batch, days=1)
                        for symbol, data in stock_data.items():
                            if data is not None and not data.empty:
                                current_price = data['Close'].iloc[-1]
                                alerts = analyzer.price_alerts.get(symbol, {})
                                
                                if alerts:
                                    print(f"\n{symbol}: {analyzer.tracked_stocks[symbol]['name']}")
                                    print(f"Current Price: ${current_price:.2f}")
                                    
                                    if current_price >= alerts.get('upper', float('inf')):
                                        print(f"\033[91m▲ Upper Alert: ${alerts['upper']:.2f}\033[0m")
                                    elif current_price <= alerts.get('lower', float('-inf')):
                                        print(f"\033[91m▼ Lower Alert: ${alerts['lower']:.2f}\033[0m")
                                    else:
                                        print(f"Upper Alert: ${alerts['upper']:.2f}")
                                        print(f"Lower Alert: ${alerts['lower']:.2f}")
                else:
                    # For paid API key, process all at once
                    stock_data = await analyzer.fetch_stock_data_batch(list(analyzer.tracked_stocks.keys()), days=1)
                    for symbol, data in stock_data.items():
                        if data is not None and not data.empty:
                            current_price = data['Close'].iloc[-1]
                            alerts = analyzer.price_alerts.get(symbol, {})
                            
                            if alerts:
                                print(f"\n{symbol}: {analyzer.tracked_stocks[symbol]['name']}")
                                print(f"Current Price: ${current_price:.2f}")
                                
                                if current_price >= alerts.get('upper', float('inf')):
                                    print(f"\033[91m▲ Upper Alert: ${alerts['upper']:.2f}\033[0m")
                                elif current_price <= alerts.get('lower', float('-inf')):
                                    print(f"\033[91m▼ Lower Alert: ${alerts['lower']:.2f}\033[0m")
                                else:
                                    print(f"Upper Alert: ${alerts['upper']:.2f}")
                                    print(f"Lower Alert: ${alerts['lower']:.2f}")
                                    
            elif choice == '7':
                print("\n\033[1;38;5;39mExiting Market News Analyzer. Goodbye!\033[0m")
                break
            else:
                print("\n\033[91mInvalid choice. Please enter a number between 1 and 7.\033[0m")
                
    except Exception as e:
        print(f"\n\033[91mError: {str(e)}\033[0m")
    finally:
        if analyzer:
            await analyzer.close_session()
            analyzer.thread_pool.shutdown()

if __name__ == '__main__':
    asyncio.run(main())