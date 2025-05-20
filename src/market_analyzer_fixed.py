import os
import json
import sys
import re
import time
import random
import logging
from datetime import datetime, timedelta
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import yfinance as yf
import pandas as pd
from bs4 import BeautifulSoup
from textblob import TextBlob
import numpy as np
import ta  # Technical Analysis library
import threading
from queue import Queue
from concurrent.futures import ThreadPoolExecutor, as_completed
import pickle
from pathlib import Path
import matplotlib.pyplot as plt
from matplotlib.dates import DateFormatter

class MarketNewsAnalyzer:
    def __init__(self):
        # Basic initialization
        self.setup_cache_directories()  # This needs to come first
        self.setup_logging()
        
        # Initialize basic configuration
        self.initialize_basic_config()
        
        # Lazy loaded properties
        self._session = None
        self._stock_data_cache = {}
        self._news_cache = {}
        self._initialized = False
        
        # Configuration
        self.cache_duration = timedelta(minutes=15)
        self.stock_cache_duration = timedelta(minutes=5)
        self.min_request_interval = 3
        self.max_workers = 3  # Limit concurrent requests

    def setup_cache_directories(self):
        """Setup cache directories"""
        self.data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')
        self.cache_dir = os.path.join(self.data_dir, 'cache')
        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(self.cache_dir, exist_ok=True)

    @property
    def session(self):
        """Lazy load session"""
        if self._session is None:
            self._session = self.setup_requests_session()
        return self._session

    def initialize(self):
        """Lazy initialization of data"""
        if self._initialized:
            return
            
        # Load configuration data
        self.load_config()
        
        # Load cache
        self.load_cache()
        
        self._initialized = True

    def initialize_basic_config(self):
        """Initialize basic configuration that's needed immediately"""
        # Market indices
        self.market_indices = {
            '^GSPC': {'name': 'S&P 500', 'description': 'Standard & Poor\'s 500 Index'},
            '^IXIC': {'name': 'NASDAQ Composite', 'description': 'NASDAQ Composite Index'},
            '^DJI': {'name': 'Dow Jones', 'description': 'Dow Jones Industrial Average'}
        }
        
        # News sources
        self.news_sources = {
            'yahoo_finance': 'https://finance.yahoo.com/topic/stock-market-news',
            'marketwatch': 'https://www.marketwatch.com/markets'
        }
        
        # Load only essential stock data initially
        self.tracked_stocks = {
            'AAPL': {'name': 'Apple Inc.', 'sector': 'Technology'},
            'MSFT': {'name': 'Microsoft Corp.', 'sector': 'Technology'},
            'GOOGL': {'name': 'Alphabet Inc.', 'sector': 'Technology'},
            'AMZN': {'name': 'Amazon.com Inc.', 'sector': 'Consumer Cyclical'},
            'META': {'name': 'Meta Platforms Inc.', 'sector': 'Technology'}
        }
        
        # Time periods
        self.time_periods = {
            '1D': {'days': 1, 'name': '1 Day'},
            '1W': {'days': 7, 'name': '1 Week'},
            '1M': {'days': 30, 'name': '1 Month'}
        }

        # Headers for requests
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'DNT': '1',
            'Upgrade-Insecure-Requests': '1'
        }
        
    def load_config(self):
        """Load configuration data"""
        # Headers for requests
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'DNT': '1',
            'Upgrade-Insecure-Requests': '1'
        }
        
        # Load other configuration (news sources, stock keywords, etc.)
        self.load_sources_and_stocks()
        
    def load_sources_and_stocks(self):
        """Load news sources and stock data"""
        # News sources
        self.news_sources = {
            'yahoo_finance': 'https://finance.yahoo.com/topic/stock-market-news',
            'marketwatch': 'https://www.marketwatch.com/markets'
        }
        
        # Load only essential stock data initially
        self.tracked_stocks = {
            'AAPL': {'name': 'Apple Inc.', 'sector': 'Technology'},
            'MSFT': {'name': 'Microsoft Corp.', 'sector': 'Technology'},
            'GOOGL': {'name': 'Alphabet Inc.', 'sector': 'Technology'},
            'AMZN': {'name': 'Amazon.com Inc.', 'sector': 'Consumer Cyclical'},
            'META': {'name': 'Meta Platforms Inc.', 'sector': 'Technology'}
        }
        
        # Market indices
        self.market_indices = {
            '^GSPC': {'name': 'S&P 500', 'description': 'Standard & Poor\'s 500 Index'},
            '^IXIC': {'name': 'NASDAQ Composite', 'description': 'NASDAQ Composite Index'},
            '^DJI': {'name': 'Dow Jones', 'description': 'Dow Jones Industrial Average'}
        }
        
        # Time periods
        self.time_periods = {
            '1D': {'days': 1, 'name': '1 Day'},
            '1W': {'days': 7, 'name': '1 Week'},
            '1M': {'days': 30, 'name': '1 Month'}
        }

    def get_stock_data(self, symbol, days=5):
        """Get stock data with improved caching and rate limiting"""
        if not self._initialized:
            self.initialize()
            
        cache_key = f"{symbol}_{days}"
        now = datetime.now()
        
        # Check cache first
        if cache_key in self._stock_data_cache:
            cached_data = self._stock_data_cache[cache_key]
            if now - cached_data['timestamp'] < self.stock_cache_duration:
                return cached_data['data']
        
        try:
            # Rate limiting
            time.sleep(self.min_request_interval)
            
            stock = yf.Ticker(symbol)
            hist = stock.history(period=f"{days}d")
            
            if hist.empty:
                return None
            
            data = self._process_stock_data(symbol, hist)
            
            # Cache the data
            self._stock_data_cache[cache_key] = {
                'timestamp': now,
                'data': data
            }
            
            return data
            
        except Exception as e:
            self.logger.error(f"Error fetching stock data for {symbol}: {str(e)}")
            return None

    def _process_stock_data(self, symbol, hist):
        """Process historical stock data"""
        current_price = hist['Close'].iloc[-1]
        previous_close = hist['Close'].iloc[-2] if len(hist) > 1 else current_price
        change = current_price - previous_close
        change_percent = (change / previous_close) * 100
        
        return {
            'symbol': symbol,
            'name': self.tracked_stocks[symbol]['name'],
            'current_price': current_price,
            'change': change,
            'change_percent': change_percent,
            'volume': hist['Volume'].iloc[-1],
            'high': hist['High'].iloc[-1],
            'low': hist['Low'].iloc[-1]
        }

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

    def setup_requests_session(self):
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

    def load_cache(self):
        """Load cached news data"""
        cache_file = os.path.join(self.cache_dir, 'news_cache.pkl')
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'rb') as f:
                    cached_data = pickle.load(f)
                    if isinstance(cached_data, dict):
                        self._news_cache = cached_data
            except Exception as e:
                self.logger.error(f"Error loading cache: {str(e)}")

    def save_cache(self):
        """Save news cache to disk"""
        cache_file = os.path.join(self.cache_dir, 'news_cache.pkl')
        try:
            with open(cache_file, 'wb') as f:
                pickle.dump(self._news_cache, f)
        except Exception as e:
            self.logger.error(f"Error saving cache: {str(e)}")

    def fetch_all_news(self, sources):
        """Fetch news from multiple sources in parallel"""
        results = {}
        with ThreadPoolExecutor(max_workers=4) as executor:
            future_to_source = {
                executor.submit(self.fetch_news, source): source 
                for source in sources
            }
            for future in as_completed(future_to_source):
                source = future_to_source[future]
                try:
                    results[source] = future.result()
                except Exception as e:
                    self.logger.error(f"Error fetching from {source}: {str(e)}")
                    results[source] = None
        return results

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

    def detect_stock_mentions(self, text):
        """Detect stock mentions in text with improved accuracy"""
        mentioned_stocks = set()
        text_lower = text.lower()
        
        # Check for stock symbols
        for symbol in self.tracked_stocks.keys():
            # Direct symbol mention patterns
            symbol_patterns = [
                f"${symbol}",  # $AAPL
                f" {symbol} ",  # AAPL
                f"{symbol}:",  # AAPL:
                f"{symbol}\\.",  # AAPL.
                f"{symbol}'s",  # AAPL's
            ]
            
            if any(pattern.lower() in text_lower for pattern in symbol_patterns):
                mentioned_stocks.add(symbol)
                continue
            
            # Check company name and keywords
            keywords = self.stock_keywords.get(symbol, [])
            for keyword in keywords:
                if keyword.lower() in text_lower:
                    mentioned_stocks.add(symbol)
                    break
        
        return list(mentioned_stocks)

    def get_recent_news(self, today_only=True):
        """Get news from today or yesterday with improved caching"""
        cache_key = f"news_{datetime.now().strftime('%Y-%m-%d')}_{today_only}"
        
        # Check cache first
        if cache_key in self._news_cache:
            cache_entry = self._news_cache[cache_key]
            # Use cache if it's less than 15 minutes old
            if datetime.now() - cache_entry['timestamp'] < self.cache_duration:
                return cache_entry['data']
        
        results = []
        seen_titles = set()
        
        today = datetime.now().date()
        yesterday = today - timedelta(days=1)
        
        # Fetch news from all sources in parallel with timeout
        with ThreadPoolExecutor(max_workers=len(self.news_sources)) as executor:
            future_to_source = {
                executor.submit(self.fetch_news_with_timeout, source): source 
                for source in self.news_sources.keys()
            }
            
            for future in as_completed(future_to_source):
                source = future_to_source[future]
                try:
                    html_content = future.result()
            if html_content:
                articles = self.parse_news(html_content, source)
                for article in articles:
                    if article['title'] not in seen_titles:
                        seen_titles.add(article['title'])
                        
                        # Check if article is from today/yesterday
                        article_date = article.get('date')
                        if article_date:
                            if today_only and article_date.date() != today:
                                continue
                            if not today_only and article_date.date() not in [today, yesterday]:
                                continue
                        
                                # Get mentioned stocks and their data in parallel
                        mentioned_stocks = self.detect_stock_mentions(
                            f"{article['title']} {article.get('summary', '')}"
                        )
                        
                        if mentioned_stocks:
                                    # Fetch stock data in parallel
                                    stock_futures = {
                                        executor.submit(self.get_stock_data, symbol): symbol 
                                        for symbol in mentioned_stocks
                                    }
                                    
                            stock_data = {}
                                    for stock_future in as_completed(stock_futures):
                                        try:
                                            symbol = stock_futures[stock_future]
                                            data = stock_future.result(timeout=3)
                                if data:
                                    stock_data[symbol] = data
                                        except Exception as e:
                                            self.logger.error(f"Error fetching stock data for news: {str(e)}")
                            
                                    # Calculate sentiment and impact score
                            sentiment = self.analyze_sentiment(
                                f"{article['title']} {article.get('summary', '')}"
                            )
                            
                            max_stock_move = max(
                                [abs(data['change_percent']) for data in stock_data.values()],
                                default=0
                            )
                            
                            impact_score = max_stock_move * 0.7 + abs(sentiment['polarity']) * 0.3
                            
                            results.append({
                                'article': article,
                                'mentioned_stocks': mentioned_stocks,
                                'stock_data': stock_data,
                                'sentiment': sentiment,
                                'impact_score': impact_score
                            })
                except Exception as e:
                    self.logger.error(f"Error processing news from {source}: {str(e)}")
        
        # Sort by impact score
        results.sort(key=lambda x: x['impact_score'], reverse=True)
        
        # Cache the results
        self._news_cache[cache_key] = {
            'timestamp': datetime.now(),
            'data': results
        }
        self.save_cache()
        
        return results

    def fetch_news_with_timeout(self, source, timeout=10):
        """Fetch news from a source with timeout"""
        try:
            if source in self.last_request_time:
                time_since_last_request = (datetime.now() - self.last_request_time[source]).total_seconds()
                if time_since_last_request < self.min_request_interval:
                    time.sleep(self.min_request_interval - time_since_last_request)

            self.logger.info(f"Fetching news from {source}")
            response = self.session.get(
                self.news_sources[source],
                timeout=timeout
            )
            response.raise_for_status()
            self.last_request_time[source] = datetime.now()
            return response.text
        except Exception as e:
            self.logger.error(f"Error fetching {source}: {str(e)}")
            return None

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

    def get_sector_performance(self):
        """Calculate sector performance based on tracked stocks"""
        sector_performance = {}
        
        # Initialize sector data structure
        for stock_info in self.tracked_stocks.values():
            sector = stock_info['sector']
                if sector not in sector_performance:
                    sector_performance[sector] = {
                        'change_total': 0,
                    'count': 0,
                    'stocks': []
                }
        
        # Fetch all stock data in parallel
        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_symbol = {
                executor.submit(self.get_stock_data, symbol): symbol 
                for symbol in self.tracked_stocks
            }
            
            for future in as_completed(future_to_symbol):
                symbol = future_to_symbol[future]
                try:
                    stock_data = future.result(timeout=5)  # 5 second timeout
                    if stock_data:
                        sector = self.tracked_stocks[symbol]['sector']
                sector_performance[sector]['change_total'] += stock_data['change_percent']
                sector_performance[sector]['count'] += 1
                        sector_performance[sector]['stocks'].append(stock_data)
                except Exception as e:
                    self.logger.error(f"Error fetching data for {symbol}: {str(e)}")
        
        # Calculate averages and sort stocks by performance
        for sector_data in sector_performance.values():
            if sector_data['count'] > 0:
                sector_data['average_change'] = (
                    sector_data['change_total'] / sector_data['count']
                )
                # Sort stocks by absolute change percentage
                sector_data['stocks'].sort(key=lambda x: abs(x['change_percent']), reverse=True)
            else:
                sector_data['average_change'] = 0
                sector_data['stocks'] = []
        
        return sector_performance

    def display_market_overview(self):
        """Display market overview with sector performance"""
        print("\n\033[1;38;5;39m╔════════════════════════════════════════════════════════════════════╗")
        print("║                         MARKET OVERVIEW                              ║")
        print("╚════════════════════════════════════════════════════════════════════╝\033[0m\n")

        # Display sector performance
        sector_perf = self.get_sector_performance()
        print("\033[1;38;5;214m▓▒░ SECTOR PERFORMANCE ░▒▓\033[0m")
        
        for sector, data in sector_perf.items():
            change = data['average_change']
            color = "\033[38;5;82m" if change >= 0 else "\033[38;5;196m"
            arrow = "▲" if change >= 0 else "▼"
            print(f"{sector:<20} {color}{arrow} {abs(change):>6.2f}%\033[0m")

        # Display top movers
        print("\n\033[1;38;5;82m▓▒░ TOP MOVERS ░▒▓\033[0m")
        stock_movements = []
        
        for symbol in self.tracked_stocks:
            data = self.get_stock_data(symbol)
            if data:
                stock_movements.append(data)
        
        # Sort by absolute change percentage
        stock_movements.sort(key=lambda x: abs(x['change_percent']), reverse=True)
        
        for stock in stock_movements[:5]:  # Show top 5 movers
            color = "\033[38;5;82m" if stock['change_percent'] >= 0 else "\033[38;5;196m"
            arrow = "▲" if stock['change_percent'] >= 0 else "▼"
            print(f"{stock['symbol']:<6} {stock['name']:<30} {color}{arrow} {abs(stock['change_percent']):>6.2f}%\033[0m")

    def display_recent_news(self, results, time_period):
        """Display news with optimized format"""
        if not results:
            print(f"\n\033[91m╔═ No relevant {time_period.lower()} market news found ═╗\033[0m")
            return

        # Display market overview
        self.display_market_overview()

        # Display news header
        print("\n\033[1;38;5;39m╔════════════════════════════════════════════════════════════════════╗")
        print(f"║  STOCK NEWS - {time_period:<47}║")
        print(f"║  Last Update: {datetime.now().strftime('%Y-%m-%d %H:%M:%S'):<47}║")
        print("╚════════════════════════════════════════════════════════════════════╝\033[0m\n")

        # Display all news in a compact format
        print("\033[1;38;5;109m▓▒░ STOCK UPDATES ░▒▓\033[0m")
        
        for result in results:
            # Get sentiment indicators
            sentiment = result['sentiment']
            sentiment_color = (
                "\033[38;5;82m" if sentiment['polarity'] > 0.2 
                else "\033[38;5;196m" if sentiment['polarity'] < -0.2 
                else "\033[38;5;249m"
            )
            sentiment_indicator = (
                "▲" if sentiment['polarity'] > 0.2 
                else "▼" if sentiment['polarity'] < -0.2 
                else "►"
            )

            # Display article header with impact indicator
            impact_indicator = "🔥" if result['impact_score'] > 5 else "⚡" if result['impact_score'] > 2 else "•"
            
            print(f"\n\033[38;5;239m╭──────────────────────────────────────────────────────────╮")
            print(f"│ \033[38;5;246m{result['article']['source']} {sentiment_color}{sentiment_indicator}\033[0m {impact_indicator}")
            print(f"│ \033[1;37m{result['article']['title']}\033[38;5;239m")
            
            # Display affected stocks in a compact format
            if result['mentioned_stocks']:
                stocks_display = []
                for symbol in result['mentioned_stocks']:
                    if symbol in result['stock_data']:
                        stock = result['stock_data'][symbol]
                        color = "\033[38;5;82m" if stock['change_percent'] >= 0 else "\033[38;5;196m"
                        arrow = "▲" if stock['change_percent'] >= 0 else "▼"
                        stocks_display.append(
                            f"{symbol} {color}{arrow}{abs(stock['change_percent']):>5.1f}%\033[0m"
                        )
                
                if stocks_display:
                    print("├──────────────────────────────────────────────────────────┤")
                    print(f"│ \033[1;38;5;117m{' | '.join(stocks_display)}\033[0m")

            # Display summary if available
            if 'summary' in result['article']:
                summary = result['article']['summary']
                if len(summary) > 120:
                    summary = summary[:117] + "..."
                print("├──────────────────────────────────────────────────────────┤")
                print(f"│ \033[38;5;246m{summary}\033[0m")
            
            print("\033[38;5;239m╰──────────────────────────────────────────────────────────╯\033[0m")

    def check_price_alerts(self):
        """Check if any stocks have crossed their alert thresholds"""
        alerts = []
        for symbol in self.tracked_stocks:
            stock_data = self.get_stock_data(symbol)
            if stock_data:
                current_price = stock_data['current_price']
                thresholds = self.price_alerts[symbol]
                
                if current_price > thresholds['upper']:
                    alerts.append({
                        'symbol': symbol,
                        'name': self.tracked_stocks[symbol]['name'],
                        'type': 'upper',
                        'price': current_price,
                        'threshold': thresholds['upper']
                    })
                elif current_price < thresholds['lower']:
                    alerts.append({
                        'symbol': symbol,
                        'name': self.tracked_stocks[symbol]['name'],
                        'type': 'lower',
                        'price': current_price,
                        'threshold': thresholds['lower']
                    })
        
        return alerts

    def compare_stocks(self, symbols, period='1M'):
        """Compare performance of multiple stocks over a specified period"""
        if len(symbols) < 2:
            return None
            
        comparisons = {}
        days = self.time_periods.get(period, self.time_periods['1M'])['days']
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        for symbol in symbols:
            try:
                stock = yf.Ticker(symbol)
                data = stock.history(
                    start=start_date,
                    end=end_date,
                    interval='1d'  # Always use daily data
                )
                
                if not data.empty:
                    initial_price = data['Close'].iloc[0]
                    current_price = data['Close'].iloc[-1]
                    price_change = ((current_price - initial_price) / initial_price) * 100
                    
                    comparisons[symbol] = {
                        'initial_price': float(initial_price),
                        'current_price': float(current_price),
                        'price_change': float(price_change),
                        'sector': self.tracked_stocks[symbol]['sector'],
                        'period': period,
                        'volume': int(data['Volume'].mean()),
                        'high': float(data['High'].max()),
                        'low': float(data['Low'].min())
                    }
                    
            except Exception as e:
                self.logger.error(f"Error comparing {symbol}: {str(e)}")
                
        return comparisons

    def calculate_technical_indicators(self, symbol, period='1M'):
        """Calculate technical indicators for a stock over a specified period"""
        try:
            stock = yf.Ticker(symbol)
            days = self.time_periods.get(period, self.time_periods['1M'])['days']
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)
            
            data = stock.history(
                start=start_date,
                end=end_date,
                interval='1d'  # Always use daily data
            )
            
            if not data.empty:
                # RSI
                rsi = ta.momentum.RSIIndicator(data['Close']).rsi()
                
                # Moving Averages
                sma_20 = ta.trend.SMAIndicator(data['Close'], window=min(20, len(data))).sma_indicator()
                sma_50 = ta.trend.SMAIndicator(data['Close'], window=min(50, len(data))).sma_indicator()
                
                # MACD
                macd = ta.trend.MACD(data['Close'])
                
                # Bollinger Bands
                bollinger = ta.volatility.BollingerBands(data['Close'])
                
                latest = {
                    'rsi': float(rsi.iloc[-1]),
                    'sma_20': float(sma_20.iloc[-1]),
                    'sma_50': float(sma_50.iloc[-1]),
                    'macd_line': float(macd.macd().iloc[-1]),
                    'macd_signal': float(macd.macd_signal().iloc[-1]),
                    'bollinger_high': float(bollinger.bollinger_hband().iloc[-1]),
                    'bollinger_low': float(bollinger.bollinger_lband().iloc[-1]),
                    'last_close': float(data['Close'].iloc[-1]),
                    'period': period,
                    'period_high': float(data['High'].max()),
                    'period_low': float(data['Low'].min()),
                    'period_change': float(((data['Close'].iloc[-1] - data['Close'].iloc[0]) / data['Close'].iloc[0]) * 100),
                    'avg_volume': int(data['Volume'].mean())
                }
                
                self.technical_indicators[symbol] = latest
                return latest
                
        except Exception as e:
            self.logger.error(f"Error calculating technical indicators for {symbol}: {str(e)}")
            return None

    def analyze_volume(self, symbol, days=10):
        """Analyze trading volume for a stock"""
        try:
            stock = yf.Ticker(symbol)
            hist = stock.history(period=f"{days}d")
            avg_volume = hist['Volume'].mean()
            current_volume = hist['Volume'].iloc[-1]
            volume_ratio = current_volume / avg_volume
            
            return {
                    'average_volume': int(avg_volume),
                'current_volume': int(current_volume),
                'volume_ratio': round(volume_ratio, 2)
            }
        except Exception as e:
            self.logger.error(f"Error analyzing volume for {symbol}: {str(e)}")
            return None

    def get_market_indices(self):
        """Get market indices data with caching"""
        if not hasattr(self, 'market_indices'):
            self.initialize_basic_config()
            
        cache_key = 'market_indices'
        now = datetime.now()
        
        # Check cache first
        if cache_key in self._stock_data_cache:
            cached_data = self._stock_data_cache[cache_key]
            if now - cached_data['timestamp'] < self.stock_cache_duration:
                return cached_data['data']
        
        try:
            indices_data = []
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {
                    executor.submit(self._fetch_index_data, symbol, info): symbol 
                    for symbol, info in self.market_indices.items()
                }
                
                for future in as_completed(futures):
                    result = future.result()
                    if result:
                        indices_data.append(result)
            
            # Cache the data
            self._stock_data_cache[cache_key] = {
                'timestamp': now,
                'data': indices_data
            }
            
            return indices_data
                
        except Exception as e:
            self.logger.error(f"Error fetching market indices: {str(e)}")
            return []

    def _fetch_index_data(self, symbol, info):
        """Helper method to fetch individual index data"""
        try:
            index = yf.Ticker(symbol)
            
            # Try to get real-time data first
            current_info = index.info
            if current_info and 'regularMarketPrice' in current_info:
                current_price = current_info['regularMarketPrice']
                prev_close = current_info.get('previousClose', current_price)
                change = current_price - prev_close
                change_percent = (change / prev_close) * 100 if prev_close else 0
                
                return {
                    'symbol': symbol,
                    'name': info['name'],
                    'description': info['description'],
                    'price': round(current_price, 2),
                    'change': round(change, 2),
                    'change_percent': round(change_percent, 2)
                }
            
            # Fallback to historical data if real-time not available
            hist = index.history(period="2d")
            if len(hist) >= 2:
                current_price = hist['Close'].iloc[-1]
                prev_close = hist['Close'].iloc[-2]
                change = current_price - prev_close
                change_percent = (change / prev_close) * 100
                
                return {
                    'symbol': symbol,
                    'name': info['name'],
                    'description': info['description'],
                    'price': round(current_price, 2),
                    'change': round(change, 2),
                    'change_percent': round(change_percent, 2)
                }
            
            return None
            
        except Exception as e:
            self.logger.error(f"Error fetching individual index {symbol}: {str(e)}")
            return None

    def display_technical_analysis(self, symbol, period='1M'):
        """Display technical analysis for a stock over a specified period"""
        print(f"\n\033[1;38;5;117m▓▒░ TECHNICAL ANALYSIS: {symbol} ({self.time_periods[period]['name']}) ░▒▓\033[0m")
        
        # Get technical indicators
        indicators = self.calculate_technical_indicators(symbol, period)
        if not indicators:
            print("Unable to calculate technical indicators")
            return
            
        # Period Performance
        period_change = indicators['period_change']
        period_color = "\033[38;5;82m" if period_change >= 0 else "\033[38;5;196m"
        print(f"Period Performance: {period_color}{period_change:+.2f}%\033[0m")
        print(f"Period High: ${indicators['period_high']:.2f}")
        print(f"Period Low: ${indicators['period_low']:.2f}")
        print(f"Average Volume: {indicators['avg_volume']:,}")
        
        # RSI Analysis
        rsi = indicators['rsi']
        rsi_color = "\033[38;5;196m" if rsi > 70 else "\033[38;5;82m" if rsi < 30 else "\033[38;5;249m"
        print(f"RSI (14): {rsi_color}{rsi:.2f}\033[0m")
        
        # Moving Averages
        price = indicators['last_close']
        sma_20 = indicators['sma_20']
        sma_50 = indicators['sma_50']
        
        ma_trend = "▲ Bullish" if sma_20 > sma_50 else "▼ Bearish" if sma_20 < sma_50 else "► Neutral"
        ma_color = "\033[38;5;82m" if sma_20 > sma_50 else "\033[38;5;196m" if sma_20 < sma_50 else "\033[38;5;249m"
        print(f"MA Trend: {ma_color}{ma_trend}\033[0m")
        print(f"SMA 20: ${sma_20:.2f}")
        print(f"SMA 50: ${sma_50:.2f}")
        
        # MACD
        macd_line = indicators['macd_line']
        macd_signal = indicators['macd_signal']
        macd_color = "\033[38;5;82m" if macd_line > macd_signal else "\033[38;5;196m"
        print(f"MACD: {macd_color}{macd_line:.2f}\033[0m")
        
        # Bollinger Bands
        bb_high = indicators['bollinger_high']
        bb_low = indicators['bollinger_low']
        bb_position = ((price - bb_low) / (bb_high - bb_low)) * 100
        bb_color = "\033[38;5;196m" if bb_position > 80 else "\033[38;5;82m" if bb_position < 20 else "\033[38;5;249m"
        print(f"Bollinger Position: {bb_color}{bb_position:.1f}%\033[0m")
        print(f"BB Upper: ${bb_high:.2f}")
        print(f"BB Lower: ${bb_low:.2f}")

    def display_stock_comparison(self, symbols, period='1M'):
        """Display comparison between stocks over a specified period"""
        print(f"\n\033[1;38;5;117m▓▒░ STOCK COMPARISON ({self.time_periods[period]['name']}) ░▒▓\033[0m")
        
        comparisons = self.compare_stocks(symbols, period)
        if not comparisons:
            print("Unable to compare stocks")
            return
            
        # Sort by performance
        sorted_stocks = sorted(comparisons.items(), key=lambda x: x[1]['price_change'], reverse=True)
        
        for symbol, data in sorted_stocks:
            change = data['price_change']
            color = "\033[38;5;82m" if change >= 0 else "\033[38;5;196m"
            arrow = "▲" if change >= 0 else "▼"
            
            print(f"\n{self.tracked_stocks[symbol]['name']} ({symbol})")
            print(f"Sector: {data['sector']}")
            print(f"Performance: {color}{arrow} {abs(change):.2f}%\033[0m")
            print(f"Current Price: ${data['current_price']:.2f}")
            print(f"Period High: ${data['high']:.2f}")
            print(f"Period Low: ${data['low']:.2f}")
            print(f"Avg Volume: {data['volume']:,}")

    def create_stock_chart(self, symbols, period='1M'):
        """Create a text-based stock comparison chart"""
        try:
            # Get data for all symbols
            days = self.time_periods.get(period, self.time_periods['1M'])['days']
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)
            
            # Store data for all symbols
            symbol_data = {}
            max_change = -float('inf')
            min_change = float('inf')
            
            # Collect data for each symbol
                for symbol in symbols:
                try:
                    stock = yf.Ticker(symbol)
                    data = stock.history(
                                start=start_date,
                                end=end_date,
                                interval='1d'
                    )
                
                        if not data.empty:
                            initial_price = data['Close'].iloc[0]
                        changes = ((data['Close'] - initial_price) / initial_price) * 100
                        symbol_data[symbol] = changes
                            
                        max_change = max(max_change, changes.max())
                        min_change = min(min_change, changes.min())
                    except Exception as e:
                    self.logger.error(f"Error getting data for {symbol}: {str(e)}")
                    continue
            
            if not symbol_data:
                print("No data available for the selected symbols")
                return False
                
            # Chart settings
            chart_height = 20
            chart_width = 80
            
            # Calculate scale factors
            value_range = max_change - min_change
            if value_range == 0:
                value_range = 1  # Prevent division by zero
            scale = (chart_height - 1) / value_range
            
            # Create empty chart
            chart = [[' ' for _ in range(chart_width)] for _ in range(chart_height)]
            
            # Draw axis lines
            zero_line = int((0 - min_change) * scale)
            if 0 <= zero_line < chart_height:
                for x in range(chart_width):
                    chart[zero_line][x] = '─'
            
            # Plot each symbol
            colors = {
                0: '\033[38;5;82m',   # Green
                1: '\033[38;5;208m',  # Orange
                2: '\033[38;5;39m',   # Blue
                3: '\033[38;5;201m',  # Pink
                4: '\033[38;5;226m'   # Yellow
            }
            
            # Print title
            print(f"\n\033[1m{' ' * 20}Stock Comparison ({self.time_periods[period]['name']})\033[0m\n")
            
            # Plot data points
            for idx, (symbol, changes) in enumerate(symbol_data.items()):
                color = colors.get(idx % len(colors), '\033[0m')
                plot_char = '●'
                
                # Calculate points to plot
                step = len(changes) / chart_width
                for x in range(chart_width):
                    point_idx = int(x * step)
                    if point_idx < len(changes):
                        y = int((changes.iloc[point_idx] - min_change) * scale)
                        if 0 <= y < chart_height:
                            chart[chart_height - 1 - y][x] = color + plot_char + '\033[0m'
            
            # Print the chart
            # Y-axis labels
            y_labels = np.linspace(max_change, min_change, 5)
            label_positions = np.linspace(0, chart_height-1, 5, dtype=int)
            
            # Print chart with labels
            for i in range(chart_height):
                if i in label_positions:
                    label_idx = np.where(label_positions == i)[0][0]
                    print(f"{y_labels[label_idx]:6.1f}% ", end='')
                else:
                    print(" " * 8, end='')
                    
                print(''.join(chart[i]))
            
            # Print X-axis time labels
            dates = pd.date_range(start=start_date, end=end_date, periods=5)
            date_str = [d.strftime('%Y-%m-%d') for d in dates]
            print(" " * 8 + "├" + "─" * (chart_width-2) + "┤")
            print(" " * 8 + date_str[0] + " " * (chart_width-len(date_str[0])-len(date_str[-1])) + date_str[-1])
            
            # Print legend
            print("\nLegend:")
            for idx, symbol in enumerate(symbol_data.keys()):
                color = colors.get(idx % len(colors), '\033[0m')
                final_change = symbol_data[symbol].iloc[-1]
                print(f"{color}●\033[0m {symbol:<6} {final_change:>6.1f}%")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error creating text chart: {str(e)}")
            return False

    def create_technical_chart(self, symbol, period='1M'):
        """Create a text-based technical analysis chart with candlesticks"""
        try:
            # Get data
            days = self.time_periods.get(period, self.time_periods['1M'])['days']
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)
            
            stock = yf.Ticker(symbol)
            data = stock.history(
                start=start_date,
                end=end_date,
                interval='1d'
            )
            
            if data.empty:
                return False
            
            # Calculate indicators
            close_prices = data['Close']
            sma_20 = ta.trend.SMAIndicator(close_prices, window=20).sma_indicator()
            rsi = ta.momentum.RSIIndicator(close_prices).rsi()
            
            # Print title
            print(f"\n\033[1m{' ' * 20}{symbol} Technical Analysis ({self.time_periods[period]['name']})\033[0m\n")
            
            # Chart settings
            chart_height = 20
            chart_width = 80
            volume_height = 5
            
            # Calculate price scale
            price_range = data['High'].max() - data['Low'].min()
            price_scale = (chart_height - 1) / price_range
            
            # Calculate volume scale
            max_volume = data['Volume'].max()
            volume_scale = volume_height / max_volume if max_volume > 0 else 1
            
            # Create empty charts
            price_chart = [[' ' for _ in range(chart_width)] for _ in range(chart_height)]
            volume_chart = [[' ' for _ in range(chart_width)] for _ in range(volume_height)]
            
            # Candlestick patterns
            # ▲ = Green up day
            # ▼ = Red down day
            # │ = Price range
            # ─ = Horizontal line for unchanged price
            # ● = SMA line
            
            # Plot candlesticks and volume
            step = len(data) / chart_width
            for x in range(chart_width):
                point_idx = int(x * step)
                if point_idx < len(data):
                    # Get OHLC data
                    open_price = data['Open'].iloc[point_idx]
                    high_price = data['High'].iloc[point_idx]
                    low_price = data['Low'].iloc[point_idx]
                    close_price = data['Close'].iloc[point_idx]
                    volume = data['Volume'].iloc[point_idx]
                    
                    # Calculate y positions
                    high_y = int((high_price - data['Low'].min()) * price_scale)
                    low_y = int((low_price - data['Low'].min()) * price_scale)
                    open_y = int((open_price - data['Low'].min()) * price_scale)
                    close_y = int((close_price - data['Low'].min()) * price_scale)
                    
                    # Draw candlestick
                    is_up_day = close_price >= open_price
                    color = "\033[38;5;82m" if is_up_day else "\033[38;5;196m"  # Green for up, Red for down
                    
                    # Draw price range line
                    for y in range(low_y, high_y + 1):
                        if 0 <= y < chart_height:
                            price_chart[chart_height - 1 - y][x] = color + '│' + '\033[0m'
                    
                    # Draw open/close body
                    body_start = min(open_y, close_y)
                    body_end = max(open_y, close_y)
                    
                    if body_start == body_end:
                        # Doji pattern (open = close)
                        if 0 <= chart_height - 1 - body_start < chart_height:
                            price_chart[chart_height - 1 - body_start][x] = color + '─' + '\033[0m'
                    else:
                        # Regular candle body
                        for y in range(body_start, body_end + 1):
                            if 0 <= chart_height - 1 - y < chart_height:
                                price_chart[chart_height - 1 - y][x] = color + '┃' + '\033[0m'
                    
                    # Draw candle direction marker
                    marker = '▲' if is_up_day else '▼'
                    marker_y = chart_height - 1 - close_y
                    if 0 <= marker_y < chart_height:
                        price_chart[marker_y][x] = color + marker + '\033[0m'
                    
                    # Plot SMA-20
                    if not np.isnan(sma_20.iloc[point_idx]):
                        sma_y = int((sma_20.iloc[point_idx] - data['Low'].min()) * price_scale)
                        if 0 <= chart_height - 1 - sma_y < chart_height:
                            price_chart[chart_height - 1 - sma_y][x] = '\033[38;5;39m●\033[0m'
                    
                    # Plot volume
                    volume_y = int(volume * volume_scale)
                    for y in range(min(volume_y, volume_height)):
                        volume_chart[volume_height - 1 - y][x] = color + '█' + '\033[0m'
            
            # Print price chart
            print("Price Chart (with Candlesticks):")
            # Y-axis labels (prices)
            price_labels = np.linspace(data['High'].max(), data['Low'].min(), 5)
            label_positions = np.linspace(0, chart_height-1, 5, dtype=int)
            
            for i in range(chart_height):
                if i in label_positions:
                    label_idx = np.where(label_positions == i)[0][0]
                    print(f"${price_labels[label_idx]:8.2f} ", end='')
                else:
                    print(" " * 10, end='')
                print(''.join(price_chart[i]))
            
            # Print volume chart
            print("\nVolume:")
            volume_labels = np.linspace(max_volume, 0, 3)
            for i in range(volume_height):
                if i in [0, volume_height-1]:
                    label_idx = 0 if i == 0 else -1
                    print(f"{volume_labels[label_idx]:8.0f} ", end='')
                else:
                    print(" " * 10, end='')
                print(''.join(volume_chart[i]))
            
            # Print X-axis time labels
            print(" " * 10 + "├" + "─" * (chart_width-2) + "┤")
            dates = pd.date_range(start=start_date, end=end_date, periods=5)
            date_str = [d.strftime('%Y-%m-%d') for d in dates]
            print(" " * 10 + date_str[0] + " " * (chart_width-len(date_str[0])-len(date_str[-1])) + date_str[-1])
            
            # Print legend
            print("\nChart Legend:")
            print("\033[38;5;82m▲\033[0m Up Day   \033[38;5;196m▼\033[0m Down Day   \033[38;5;39m●\033[0m SMA-20")
            print("\033[38;5;82m│\033[0m Price Range   \033[38;5;82m┃\033[0m Candle Body   \033[38;5;82m█\033[0m Volume")
            
            # RSI Chart
            print("\nRSI Chart:")
            rsi_height = 8
            rsi_chart = [[' ' for _ in range(chart_width)] for _ in range(rsi_height)]
            
            # Draw RSI reference lines
            for x in range(chart_width):
                rsi_chart[int(rsi_height * 0.7)][x] = '\033[38;5;196m─\033[0m'  # Overbought (70)
                rsi_chart[int(rsi_height * 0.3)][x] = '\033[38;5;82m─\033[0m'   # Oversold (30)
            
            # Plot RSI line with dots and connecting lines
            last_rsi_y = None
            for x in range(chart_width):
                point_idx = int(x * step)
                if point_idx < len(rsi):
                    if not np.isnan(rsi.iloc[point_idx]):
                        rsi_y = int((rsi.iloc[point_idx] / 100) * (rsi_height - 1))
                        if 0 <= rsi_y < rsi_height:
                            rsi_chart[rsi_height - 1 - rsi_y][x] = '\033[38;5;39m●\033[0m'
                            # Draw connecting line to previous point
                            if last_rsi_y is not None and x > 0:
                                for y in range(min(last_rsi_y, rsi_y), max(last_rsi_y, rsi_y)):
                                    if 0 <= rsi_height - 1 - y < rsi_height:
                                        if rsi_chart[rsi_height - 1 - y][x-1] == ' ':
                                            rsi_chart[rsi_height - 1 - y][x-1] = '\033[38;5;39m│\033[0m'
                            last_rsi_y = rsi_y
            
            # Print RSI chart
            rsi_labels = [0, 30, 50, 70, 100]
            label_positions = np.linspace(rsi_height-1, 0, len(rsi_labels), dtype=int)
            
            for i in range(rsi_height):
                if i in label_positions:
                    label_idx = np.where(label_positions == i)[0][0]
                    print(f"RSI {rsi_labels[label_idx]:<3} ", end='')
                else:
                    print(" " * 7, end='')
                print(''.join(rsi_chart[i]))
            
            # Print X-axis time labels for RSI
            print(" " * 7 + "├" + "─" * (chart_width-2) + "┤")
            print(" " * 7 + date_str[0] + " " * (chart_width-len(date_str[0])-len(date_str[-1])) + date_str[-1])
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error creating technical chart: {str(e)}")
            return False

def main():
    try:
        analyzer = MarketNewsAnalyzer()
        
        while True:
            print("\n\033[1;38;5;39m╔════════════════════════════════════════════╗")
            print("║           MARKET NEWS ANALYZER              ║")
            print("╚════════════════════════════════════════════╝\033[0m")
            print("1. View Today's News")
            print("2. View Yesterday's News")
            print("3. View Both")
            print("4. Technical Analysis")
            print("5. Compare Stocks")
            print("6. Check Price Alerts")
            print("7. Create Charts")
            print("8. Exit")
            
            choice = input("\nEnter your choice (1-8): ")
            
            if choice == '1':
                print("\n\033[1;38;5;82m═══════════════ TODAY'S NEWS ═══════════════\033[0m")
                today_results = analyzer.get_recent_news(today_only=True)
                analyzer.display_recent_news(today_results, "Today's")
            elif choice == '2':
                print("\n\033[1;38;5;214m═══════════════ YESTERDAY'S NEWS ═══════════════\033[0m")
                yesterday_results = analyzer.get_recent_news(today_only=False)
                analyzer.display_recent_news(yesterday_results, "Yesterday's")
            elif choice == '3':
                print("\n\033[1;38;5;82m═══════════════ TODAY'S NEWS ═══════════════\033[0m")
                today_results = analyzer.get_recent_news(today_only=True)
                analyzer.display_recent_news(today_results, "Today's")
                
                print("\nPress Enter to view yesterday's news...")
                input()
                
                print("\n\033[1;38;5;214m═══════════════ YESTERDAY'S NEWS ═══════════════\033[0m")
                yesterday_results = analyzer.get_recent_news(today_only=False)
                analyzer.display_recent_news(yesterday_results, "Yesterday's")
            elif choice == '4':
                print("\nEnter stock symbol (e.g., AAPL):")
                symbol = input().strip().upper()
                if symbol in analyzer.tracked_stocks:
                    print("\nSelect time period:")
                    print("1. 1 Week (1W)")
                    print("2. 1 Month (1M)")
                    print("3. 3 Months (3M)")
                    print("4. 6 Months (6M)")
                    print("5. 1 Year (1Y)")
                    period_choice = input("\nEnter your choice (1-5): ")
                    
                    period_map = {'1': '1W', '2': '1M', '3': '3M', '4': '6M', '5': '1Y'}
                    period = period_map.get(period_choice, '1M')
                    
                    analyzer.display_technical_analysis(symbol, period)
                else:
                    print("Invalid stock symbol")
            elif choice == '5':
                print("\nEnter stock symbols separated by space (e.g., AAPL MSFT GOOGL):")
                symbols = input().strip().upper().split()
                valid_symbols = [s for s in symbols if s in analyzer.tracked_stocks]
                if len(valid_symbols) >= 2:
                    print("\nSelect time period:")
                    print("1. 1 Week (1W)")
                    print("2. 1 Month (1M)")
                    print("3. 3 Months (3M)")
                    print("4. 6 Months (6M)")
                    print("5. 1 Year (1Y)")
                    period_choice = input("\nEnter your choice (1-5): ")
                    
                    period_map = {'1': '1W', '2': '1M', '3': '3M', '4': '6M', '5': '1Y'}
                    period = period_map.get(period_choice, '1M')
                    
                    analyzer.display_stock_comparison(valid_symbols, period)
                else:
                    print("Please enter at least 2 valid stock symbols")
            elif choice == '6':
                alerts = analyzer.check_price_alerts()
                if alerts:
                    print("\n\033[1;38;5;214m▓▒░ PRICE ALERTS ░▒▓\033[0m")
                    for alert in alerts:
                        color = "\033[38;5;82m" if alert['type'] == 'upper' else "\033[38;5;196m"
                        print(f"\n{alert['symbol']} - {alert['name']}")
                        print(f"Current Price: {color}${alert['price']:.2f}\033[0m")
                        print(f"Alert Threshold: ${alert['threshold']:.2f}")
                else:
                    print("\nNo price alerts triggered")
            elif choice == '7':
                print("\nChart Options:")
                print("1. Stock Comparison Chart")
                print("2. Technical Analysis Chart")
                chart_choice = input("\nEnter your choice (1-2): ")
                
                if chart_choice == '1':
                    print("\nEnter stock symbols separated by space (e.g., AAPL MSFT GOOGL):")
                    symbols = input().strip().upper().split()
                    valid_symbols = [s for s in symbols if s in analyzer.tracked_stocks]
                    
                    if valid_symbols:
                        print("\nSelect time period:")
                        print("1. 1 Week (1W)")
                        print("2. 1 Month (1M)")
                        print("3. 3 Months (3M)")
                        print("4. 6 Months (6M)")
                        print("5. 1 Year (1Y)")
                        period_choice = input("\nEnter your choice (1-5): ")
                        
                        period_map = {'1': '1W', '2': '1M', '3': '3M', '4': '6M', '5': '1Y'}
                        period = period_map.get(period_choice, '1M')
                        
                        success = analyzer.create_stock_chart(valid_symbols, period)
                        if not success:
                            print("\nError creating chart")
                    else:
                        print("Please enter valid stock symbols")
                        
                elif chart_choice == '2':
                    print("\nEnter stock symbol (e.g., AAPL):")
                    symbol = input().strip().upper()
                    
                    if symbol in analyzer.tracked_stocks:
                        print("\nSelect time period:")
                        print("1. 1 Week (1W)")
                        print("2. 1 Month (1M)")
                        print("3. 3 Months (3M)")
                        print("4. 6 Months (6M)")
                        print("5. 1 Year (1Y)")
                        period_choice = input("\nEnter your choice (1-5): ")
                        
                        period_map = {'1': '1W', '2': '1M', '3': '3M', '4': '6M', '5': '1Y'}
                        period = period_map.get(period_choice, '1M')
                        
                        success = analyzer.create_technical_chart(symbol, period)
                        if not success:
                            print("\nError creating chart")
                    else:
                        print("Invalid stock symbol")
                else:
                    print("Invalid choice")
                    
            elif choice == '8':
                print("\nExiting Market News Analyzer. Goodbye!")
                break
            else:
                print("\nInvalid choice. Please enter 1-8.")
                
            if choice in ['1', '2', '3', '4', '5', '6', '7']:
                print("\nPress Enter to return to menu...")
                input()
                
    except Exception as e:
        print(f"\033[91mError: {str(e)}\033[0m")
        return

if __name__ == '__main__':
    main() 