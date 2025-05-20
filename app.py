from flask import Flask, render_template, jsonify, request, current_app
from flask_cors import CORS
from src.market_analyzer_fixed import MarketNewsAnalyzer
from functools import wraps
import json
import time
import os

app = Flask(__name__)
CORS(app)

# Security headers
@app.after_request
def add_security_headers(response):
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    return response

# Initialize the analyzer
analyzer = MarketNewsAnalyzer()

def cache_response(timeout=300):  # 5 minutes default timeout
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            cache_key = f.__name__ + str(args) + str(kwargs)
            response = getattr(current_app, 'response_cache', {}).get(cache_key)
            
            if response:
                timestamp, data = response
                if time.time() - timestamp < timeout:
                      return data
            
            response = f(*args, **kwargs)
            if not hasattr(current_app, 'response_cache'):
                setattr(current_app, 'response_cache', {})
            current_app.response_cache[cache_key] = (time.time(), response)
            return response
        return decorated_function
    return decorator

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/health')
def health_check():
    return jsonify({'status': 'healthy'}), 200

@app.route('/api/market_overview')
@cache_response(timeout=300)  # Cache for 5 minutes
def market_overview():
    try:
        sector_perf = analyzer.get_sector_performance()
        stock_movements = []
        
        for symbol in analyzer.tracked_stocks:
            data = analyzer.get_stock_data(symbol)
            if data:
                stock_movements.append(data)
        
        # Sort by absolute change percentage
        stock_movements.sort(key=lambda x: abs(x['change_percent']), reverse=True)
        top_movers = stock_movements[:5]
        
        return jsonify({
            'sector_performance': sector_perf,
            'top_movers': top_movers
        })
    except Exception as e:
        app.logger.error(f"Error in market_overview: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/news')
@cache_response(timeout=900)  # Cache for 15 minutes
def get_news():
    try:
        today_only = request.args.get('today_only', 'true').lower() == 'true'
        news = analyzer.get_recent_news(today_only=today_only)
        return jsonify(news)
    except Exception as e:
        app.logger.error(f"Error in get_news: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/technical/<symbol>')
@cache_response(timeout=300)  # Cache for 5 minutes
def technical_analysis(symbol):
    try:
        period = request.args.get('period', '1M')
        if symbol not in analyzer.tracked_stocks:
            return jsonify({'error': 'Invalid symbol'}), 400
            
        indicators = analyzer.calculate_technical_indicators(symbol, period)
        volume = analyzer.analyze_volume(symbol)
        
        return jsonify({
            'indicators': indicators,
            'volume': volume
        })
    except Exception as e:
        app.logger.error(f"Error in technical_analysis: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/chart_data/<symbol>')
@cache_response(timeout=300)  # Cache for 5 minutes
def chart_data(symbol):
    try:
        period = request.args.get('period', '1M')
        if symbol not in analyzer.tracked_stocks:
            return jsonify({'error': 'Invalid symbol'}), 400
            
        days = analyzer.time_periods.get(period, analyzer.time_periods['1M'])['days']
        stock_data = analyzer.get_stock_data(symbol, days=days)
        
        return jsonify(stock_data)
    except Exception as e:
        app.logger.error(f"Error in chart_data: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/compare')
@cache_response(timeout=300)  # Cache for 5 minutes
def compare_stocks():
    try:
        symbols = request.args.get('symbols', '').upper().split(',')
        period = request.args.get('period', '1M')
        
        valid_symbols = [s for s in symbols if s in analyzer.tracked_stocks]
        if len(valid_symbols) < 2:
            return jsonify({'error': 'Please provide at least 2 valid symbols'}), 400
            
        comparison = analyzer.compare_stocks(valid_symbols, period)
        return jsonify(comparison)
    except Exception as e:
        app.logger.error(f"Error in compare_stocks: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/symbols')
@cache_response(timeout=3600)  # Cache for 1 hour
def get_symbols():
    try:
        return jsonify(analyzer.tracked_stocks)
    except Exception as e:
        app.logger.error(f"Error in get_symbols: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/indices')
@cache_response(timeout=300)  # Cache for 5 minutes
def get_indices():
    try:
        indices = analyzer.get_market_indices()
        return jsonify(indices)
    except Exception as e:
        app.logger.error(f"Error in get_indices: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/alerts')
def check_alerts():
    alerts = analyzer.check_price_alerts()
    return jsonify(alerts)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port) 