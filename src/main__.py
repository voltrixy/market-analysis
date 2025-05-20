#!/usr/bin/env python3
import os
import sys
from market_analyzer import MarketNewsAnalyzer

def main():
    """Main function for running the market news analyzer"""
    analyzer = MarketNewsAnalyzer()
    
    while True:
        print("\nMarket News Analyzer")
        print("1. Today's Market News")
        print("2. Yesterday's Market News")
        print("3. Exit")
        
        choice = input("\nEnter your choice (1-3): ")
        
        if choice == '1':
            print("\nFetching today's market news...")
            results = analyzer.get_recent_news(today_only=True)
            analyzer.display_recent_news(results, "Today's")
        elif choice == '2':
            print("\nFetching yesterday's market news...")
            results = analyzer.get_recent_news(today_only=False)
            analyzer.display_recent_news(results, "Yesterday's")
        elif choice == '3':
            print("\nExiting Market News Analyzer. Goodbye!")
            break
        else:
            print("\nInvalid choice. Please enter 1, 2, or 3.")

if __name__ == '__main__':
    main()
