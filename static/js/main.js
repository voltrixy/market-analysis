document.addEventListener('DOMContentLoaded', function() {
    // Initialize all charts
    initializeCharts();
    
    // Show loading states first
    showLoadingStates();
    
    // Load data in sequence with small delays to prevent overwhelming the server
    Promise.all([
        loadSymbols(),
        loadMarketIndices()
    ]).then(() => {
        // After initial critical data is loaded, load the rest with delays
        setTimeout(() => loadMarketOverview(), 500);
        setTimeout(() => loadNews(), 1000);
    });
});

function initializeCharts() {
    Chart.defaults.font.family = '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif';
    Chart.defaults.color = '#495057';
}

async function loadSymbols() {
    try {
        const response = await fetch('/api/symbols');
        const symbols = await response.json();
        
        // Populate symbol select
        const symbolSelect = document.getElementById('symbol-select');
        const compareSelect = document.getElementById('compare-symbols');
        
        symbols.forEach(symbol => {
            symbolSelect.add(new Option(symbol, symbol));
            compareSelect.add(new Option(symbol, symbol));
        });
        
        // Load initial technical analysis for first symbol
        if (symbols.length > 0) {
            loadTechnicalAnalysis(symbols[0]);
        }
    } catch (error) {
        console.error('Error loading symbols:', error);
    }
}

function setupEventListeners() {
    // Symbol select change
    document.getElementById('symbol-select').addEventListener('change', function(e) {
        loadTechnicalAnalysis(e.target.value);
    });
    
    // Period buttons
    document.querySelectorAll('[data-period]').forEach(button => {
        button.addEventListener('click', function(e) {
            // Update active state
            document.querySelectorAll('[data-period]').forEach(btn => btn.classList.remove('active'));
            e.target.classList.add('active');
            
            // Reload data with new period
            const symbol = document.getElementById('symbol-select').value;
            loadTechnicalAnalysis(symbol, e.target.dataset.period);
        });
    });
    
    // News filter
    document.getElementById('today-only').addEventListener('change', function() {
        loadNews();
    });
    
    // Compare button
    document.getElementById('compare-btn').addEventListener('click', function() {
        const select = document.getElementById('compare-symbols');
        const selectedSymbols = Array.from(select.selectedOptions).map(option => option.value);
        if (selectedSymbols.length >= 2) {
            loadComparison(selectedSymbols);
        }
    });
}

function showLoadingStates() {
    // Market indices loading state
    document.getElementById('market-indices').innerHTML = `
        <div class="text-center w-100">
            <div class="spinner-border spinner-border-sm text-primary" role="status">
                <span class="visually-hidden">Loading market data...</span>
            </div>
        </div>
    `;
    
    // Market overview loading state
    document.getElementById('market-overview').innerHTML = `
        <div class="text-center w-100">
            <div class="spinner-border spinner-border-sm text-primary" role="status">
                <span class="visually-hidden">Loading market overview...</span>
            </div>
        </div>
    `;
    
    // News loading state
    document.getElementById('news-container').innerHTML = `
        <div class="text-center w-100">
            <div class="spinner-border spinner-border-sm text-primary" role="status">
                <span class="visually-hidden">Loading news...</span>
            </div>
        </div>
    `;
}

async function loadMarketOverview() {
    const container = document.getElementById('market-overview');
    const moversContainer = document.getElementById('top-movers');
    
    try {
        // Check cache first
        const cacheKey = 'market_overview_' + new Date().toISOString().split('T')[0];
        const cachedData = sessionStorage.getItem(cacheKey);
        let data;

        if (cachedData) {
            const cached = JSON.parse(cachedData);
            const cacheAge = Date.now() - cached.timestamp;
            // Use cache if less than 5 minutes old
            if (cacheAge < 300000) {
                data = cached.data;
                renderSectorPerformance(data.sector_performance);
                renderTopMovers(data.top_movers);
                return;
            }
        }

        const response = await fetch('/api/market-overview');
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        data = await response.json();
        
        // Cache the new data
        sessionStorage.setItem(cacheKey, JSON.stringify({
            timestamp: Date.now(),
            data: data
        }));

        renderSectorPerformance(data.sector_performance);
        renderTopMovers(data.top_movers);

    } catch (error) {
        console.error('Error loading market overview:', error);
        const errorMessage = `
            <div class="alert alert-danger" role="alert">
                Error loading market data. 
                <button class="btn btn-link p-0 ms-2" onclick="loadMarketOverview()">
                    <i class="bi bi-arrow-clockwise"></i> Retry
                </button>
            </div>
        `;
        container.innerHTML = errorMessage;
        moversContainer.innerHTML = errorMessage;
    }
}

function renderSectorPerformance(sectorData) {
    const ctx = document.getElementById('sector-performance').getContext('2d');
    
    // Convert sector performance data format
    const sectors = [];
    const performances = [];
    
    for (const [sector, data] of Object.entries(sectorData)) {
        sectors.push(sector);
        performances.push(data.average_change);
    }
    
    // Destroy existing chart if it exists
    const existingChart = Chart.getChart(ctx);
    if (existingChart) {
        existingChart.destroy();
    }
    
    new Chart(ctx, {
        type: 'bar',
        data: {
            labels: sectors,
            datasets: [{
                data: performances,
                backgroundColor: performances.map(value => 
                    value >= 0 ? 'rgba(40, 167, 69, 0.5)' : 'rgba(220, 53, 69, 0.5)'
                ),
                borderColor: performances.map(value => 
                    value >= 0 ? '#28a745' : '#dc3545'
                ),
                borderWidth: 1
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: false
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            return context.raw.toFixed(2) + '%';
                        }
                    }
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: {
                        callback: function(value) {
                            return value.toFixed(1) + '%';
                        }
                    }
                }
            }
        }
    });
}

function renderTopMovers(movers) {
    const container = document.getElementById('top-movers');
    if (!movers || !Array.isArray(movers) || movers.length === 0) {
        container.innerHTML = '<div class="alert alert-info">No top movers data available.</div>';
        return;
    }

    // Create a document fragment for better performance
    const fragment = document.createDocumentFragment();
    
    movers.forEach(stock => {
        const isPositive = stock.change_percent >= 0;
        const card = document.createElement('div');
        card.className = `stock-card ${isPositive ? 'positive' : 'negative'} animate-fade-in`;
        
        card.innerHTML = `
            <div class="d-flex justify-content-between align-items-center">
                <div>
                    <span class="stock-symbol fw-bold">${stock.symbol}</span>
                    <span class="text-muted ms-2 small">${stock.name}</span>
                </div>
                <div class="text-end">
                    <div class="stock-price fw-bold">$${stock.current_price.toFixed(2)}</div>
                    <div class="stock-change ${isPositive ? 'text-success' : 'text-danger'} small">
                        ${isPositive ? '▲' : '▼'} ${Math.abs(stock.change_percent).toFixed(2)}%
                    </div>
                </div>
            </div>
            <div class="stock-details small text-muted mt-1">
                <span>Vol: ${(stock.volume / 1000000).toFixed(1)}M</span>
                <span class="ms-2">H: $${stock.high.toFixed(2)}</span>
                <span class="ms-2">L: $${stock.low.toFixed(2)}</span>
            </div>
        `;
        
        fragment.appendChild(card);
    });
    
    container.innerHTML = '';
    container.appendChild(fragment);
}

async function loadTechnicalAnalysis(symbol, period = '1M') {
    try {
        const [chartData, technical] = await Promise.all([
            fetch(`/api/chart_data/${symbol}?period=${period}`).then(r => r.json()),
            fetch(`/api/technical/${symbol}?period=${period}`).then(r => r.json())
        ]);
        
        renderTechnicalChart(chartData);
        renderIndicators(technical.indicators);
    } catch (error) {
        console.error('Error loading technical analysis:', error);
    }
}

function renderTechnicalChart(data) {
    const ctx = document.getElementById('technical-chart').getContext('2d');
    const chart = Chart.getChart(ctx);
    if (chart) {
        chart.destroy();
    }
    
    new Chart(ctx, {
        type: 'line',
        data: {
            labels: data.dates,
            datasets: [{
                label: 'Price',
                data: data.prices,
                borderColor: '#0d6efd',
                backgroundColor: 'rgba(13, 110, 253, 0.1)',
                fill: true
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                intersect: false,
                mode: 'index'
            },
            plugins: {
                tooltip: {
                    callbacks: {
                        label: context => `$${context.parsed.y.toFixed(2)}`
                    }
                }
            },
            scales: {
                y: {
                    ticks: {
                        callback: value => '$' + value.toFixed(2)
                    }
                }
            }
        }
    });
}

function renderIndicators(indicators) {
    const container = document.getElementById('indicators');
    container.innerHTML = '';
    
    Object.entries(indicators).forEach(([name, value]) => {
        const card = document.createElement('div');
        card.className = 'indicator-card';
        
        card.innerHTML = `
            <div class="indicator-title">${name}</div>
            <div class="indicator-value">${typeof value === 'number' ? value.toFixed(2) : value}</div>
        `;
        
        container.appendChild(card);
    });
}

async function loadNews() {
    const container = document.getElementById('news-container');
    
    try {
        // Show loading state
        container.innerHTML = `
            <div class="text-center w-100 py-3">
                <div class="spinner-border spinner-border-sm text-primary" role="status">
                    <span class="visually-hidden">Loading news...</span>
                </div>
            </div>
        `;

        // Check cache first
        const cacheKey = 'news_' + new Date().toISOString().split('T')[0];
        const cachedData = sessionStorage.getItem(cacheKey);
        let news;

        if (cachedData) {
            const cached = JSON.parse(cachedData);
            const cacheAge = Date.now() - cached.timestamp;
            // Use cache if less than 15 minutes old
            if (cacheAge < 900000) {
                news = cached.data;
            }
        }

        if (!news) {
            const timeoutPromise = new Promise((_, reject) => {
                setTimeout(() => reject(new Error('Request timeout')), 12000);
            });

            const fetchPromise = fetch('/api/news');
            const response = await Promise.race([fetchPromise, timeoutPromise]);
            
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            
            news = await response.json();
            
            // Cache the new data
            sessionStorage.setItem(cacheKey, JSON.stringify({
                timestamp: Date.now(),
                data: news
            }));
        }

        renderNews(news);
    } catch (error) {
        console.error('Error loading news:', error);
        container.innerHTML = `
            <div class="alert alert-danger" role="alert">
                Error loading news. 
                <button class="btn btn-link p-0 ms-2" onclick="loadNews()">
                    <i class="bi bi-arrow-clockwise"></i> Retry
                </button>
            </div>
        `;
    }
}

function renderNews(newsItems) {
    const container = document.getElementById('news-container');
    
    if (!newsItems || !Array.isArray(newsItems) || newsItems.length === 0) {
        container.innerHTML = '<div class="alert alert-info">No news available.</div>';
        return;
    }
    
    // Create a document fragment for better performance
    const fragment = document.createDocumentFragment();
    
    newsItems.forEach(item => {
        const newsCard = document.createElement('div');
        newsCard.className = 'card mb-3 animate-fade-in';
        
        const sentiment = item.sentiment.assessment;
        const sentimentClass = sentiment === 'positive' ? 'text-success' : 
                             sentiment === 'negative' ? 'text-danger' : 'text-muted';
        
        const sentimentIcon = sentiment === 'positive' ? '▲' : 
                            sentiment === 'negative' ? '▼' : '•';
        
        // Format the date
        const articleDate = item.article.date ? new Date(item.article.date) : new Date();
        const formattedDate = articleDate.toLocaleString('en-US', {
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        });
        
        // Calculate impact score indicator
        const impactScore = item.impact_score || 0;
        const impactIndicator = impactScore > 5 ? '🔥' : 
                              impactScore > 2 ? '⚡' : 
                              '•';
        
        newsCard.innerHTML = `
            <div class="card-body">
                <div class="d-flex justify-content-between align-items-start mb-2">
                    <h5 class="card-title mb-0">${item.article.title}</h5>
                    <span class="badge bg-light text-dark">${formattedDate}</span>
                </div>
                <h6 class="card-subtitle mb-2">
                    <span class="text-muted">${item.article.source}</span>
                    <span class="${sentimentClass} ms-2">${sentimentIcon}</span>
                    <span class="ms-2">${impactIndicator}</span>
                </h6>
                ${item.article.summary ? `
                    <p class="card-text">
                        ${item.article.summary.length > 200 ? 
                          item.article.summary.substring(0, 197) + '...' : 
                          item.article.summary}
                    </p>` : ''}
                ${item.mentioned_stocks.length > 0 ? `
                    <div class="mentioned-stocks mb-2">
                        ${item.mentioned_stocks.map(symbol => {
                            const stockData = item.stock_data[symbol] || {};
                            const changePercent = stockData.change_percent || 0;
                            const changeClass = changePercent >= 0 ? 'text-success' : 'text-danger';
                            const changeIcon = changePercent >= 0 ? '▲' : '▼';
                            return `
                                <span class="badge bg-light text-dark me-2">
                                    ${symbol} 
                                    <span class="${changeClass}">
                                        ${changeIcon} ${Math.abs(changePercent).toFixed(1)}%
                                    </span>
                                </span>
                            `;
                        }).join('')}
                    </div>
                ` : ''}
                <a href="${item.article.link}" target="_blank" class="card-link">
                    Read more <i class="bi bi-box-arrow-up-right"></i>
                </a>
            </div>
        `;
        
        fragment.appendChild(newsCard);
    });
    
    container.innerHTML = '';
    container.appendChild(fragment);
}

async function loadComparison(symbols) {
    try {
        const period = document.querySelector('[data-period].active').dataset.period;
        const queryString = `symbols=${symbols.join(',')}&period=${period}`;
        const response = await fetch(`/api/compare?${queryString}`);
        const data = await response.json();
        
        renderComparisonChart(data);
    } catch (error) {
        console.error('Error loading comparison:', error);
    }
}

function renderComparisonChart(data) {
    const ctx = document.getElementById('comparison-chart').getContext('2d');
    const chart = Chart.getChart(ctx);
    if (chart) {
        chart.destroy();
    }
    
    const colors = ['#0d6efd', '#dc3545', '#ffc107', '#28a745', '#6610f2'];
    
    new Chart(ctx, {
        type: 'line',
        data: {
            labels: data.dates,
            datasets: Object.entries(data.prices).map(([symbol, prices], index) => ({
                label: symbol,
                data: prices,
                borderColor: colors[index % colors.length],
                backgroundColor: 'transparent'
            }))
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                intersect: false,
                mode: 'index'
            },
            plugins: {
                tooltip: {
                    callbacks: {
                        label: context => `${context.dataset.label}: $${context.parsed.y.toFixed(2)}`
                    }
                }
            },
            scales: {
                y: {
                    ticks: {
                        callback: value => '$' + value.toFixed(2)
                    }
                }
            }
        }
    });
}

async function loadMarketIndices(retryCount = 0) {
    const maxRetries = 2;
    const container = document.getElementById('market-indices');
    
    try {
        // Show loading state
        container.innerHTML = `
            <div class="text-center w-100">
                <div class="spinner-border text-primary spinner-border-sm" role="status">
                    <span class="visually-hidden">Loading...</span>
                </div>
            </div>
        `;

        // Set up timeout
        const timeoutPromise = new Promise((_, reject) => {
            setTimeout(() => reject(new Error('Request timeout')), 5000);
        });

        // Make the fetch request
        const fetchPromise = fetch('/api/indices');
        const response = await Promise.race([fetchPromise, timeoutPromise]);

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const indices = await response.json();
        renderMarketIndices(indices);

    } catch (error) {
        console.error('Error loading market indices:', error);
        
        if (retryCount < maxRetries) {
            // Retry after a short delay
            setTimeout(() => loadMarketIndices(retryCount + 1), 1000);
        } else {
            container.innerHTML = `
                <div class="alert alert-warning m-2 d-flex align-items-center justify-content-between" role="alert">
                    <span>Unable to load market data</span>
                    <button class="btn btn-sm btn-outline-dark" onclick="loadMarketIndices()">
                        <i class="bi bi-arrow-clockwise"></i> Retry
                    </button>
                </div>
            `;
        }
    }
}

function renderMarketIndices(indices) {
    const container = document.getElementById('market-indices');
    
    if (!indices || !Array.isArray(indices) || indices.length === 0) {
        container.innerHTML = `
            <div class="alert alert-info m-2" role="alert">
                No market data available
            </div>
        `;
        return;
    }
    
    container.innerHTML = '';
    
    // Create a document fragment for better performance
    const fragment = document.createDocumentFragment();
    
    indices.forEach(index => {
        if (!index || typeof index !== 'object') return;
        
        const isPositive = (index.change || 0) >= 0;
        const indexDiv = document.createElement('div');
        indexDiv.className = 'text-center index-item';
        
        const price = typeof index.price === 'number' ? index.price.toLocaleString() : 'N/A';
        const change = typeof index.change === 'number' ? index.change.toLocaleString() : 'N/A';
        const changePercent = typeof index.change_percent === 'number' ? index.change_percent.toFixed(2) : 'N/A';
        
        indexDiv.innerHTML = `
            <div class="index-name fw-bold">${index.name || 'Unknown Index'}</div>
            <div class="index-price fs-5">${price}</div>
            <div class="index-change ${isPositive ? 'text-success' : 'text-danger'}">
                ${isPositive ? '+' : ''}${change} (${isPositive ? '+' : ''}${changePercent}%)
            </div>
        `;
        
        fragment.appendChild(indexDiv);
    });
    
    container.appendChild(fragment);
}

// Add auto-refresh functionality
let marketIndicesInterval;

function startAutoRefresh() {
    // Clear any existing interval
    if (marketIndicesInterval) {
        clearInterval(marketIndicesInterval);
    }
    
    // Refresh market indices every 30 seconds
    marketIndicesInterval = setInterval(() => {
        if (document.visibilityState === 'visible') {
            loadMarketIndices();
        }
    }, 30000);
}

// Start auto-refresh when the page loads
document.addEventListener('DOMContentLoaded', () => {
    startAutoRefresh();
    
    // Handle visibility change
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') {
            loadMarketIndices();  // Refresh immediately when tab becomes visible
        }
    });
});

// Add request queue management
const requestQueue = new Map();
const REQUEST_DELAY = 100; // ms between requests

function queueRequest(key, requestFn) {
    if (requestQueue.has(key)) {
        clearTimeout(requestQueue.get(key));
    }
    
    const timeoutId = setTimeout(async () => {
        try {
            await requestFn();
        } finally {
            requestQueue.delete(key);
        }
    }, REQUEST_DELAY * requestQueue.size);
    
    requestQueue.set(key, timeoutId);
}

// Modify the refresh function to use the queue
const debouncedRefresh = debounce(() => {
    queueRequest('indices', loadMarketIndices);
    queueRequest('overview', loadMarketOverview);
    queueRequest('news', loadNews);
}, 1000);

// Add auto-refresh every 5 minutes
setInterval(debouncedRefresh, 300000);

// Helper function for debouncing
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
};

// Utility functions
const formatNumber = (num) => {
    return new Intl.NumberFormat('en-US', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    }).format(num);
};

const formatPercentage = (num) => {
    return new Intl.NumberFormat('en-US', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
        style: 'percent'
    }).format(num / 100);
};

const formatVolume = (num) => {
    if (num >= 1e9) return (num / 1e9).toFixed(2) + 'B';
    if (num >= 1e6) return (num / 1e6).toFixed(2) + 'M';
    if (num >= 1e3) return (num / 1e3).toFixed(2) + 'K';
    return num.toString();
};

// Chart configuration
const chartConfig = {
    responsive: true,
    maintainAspectRatio: false,
    interaction: {
        intersect: false,
        mode: 'index'
    },
    plugins: {
        legend: {
            position: 'top'
        }
    }
};

// Load market indices
const loadMarketIndices = async () => {
    try {
        const response = await fetch('/api/indices');
        const data = await response.json();
        
        const container = document.getElementById('market-indices');
        container.innerHTML = data.map(index => `
            <div class="text-center">
                <h6 class="mb-1">${index.symbol}</h6>
                <div class="fs-5 fw-bold ${index.change_percent >= 0 ? 'positive' : 'negative'}">
                    ${formatNumber(index.price)}
                </div>
                <div class="${index.change_percent >= 0 ? 'positive' : 'negative'}">
                    ${index.change_percent >= 0 ? '▲' : '▼'} ${formatPercentage(Math.abs(index.change_percent))}
                </div>
            </div>
        `).join('');
    } catch (error) {
        console.error('Error loading market indices:', error);
    }
};

// Load market overview
const loadMarketOverview = async () => {
    try {
        const response = await fetch('/api/market_overview');
        const data = await response.json();
        
        // Sector Performance Chart
        const sectorCtx = document.getElementById('sector-performance').getContext('2d');
        new Chart(sectorCtx, {
            type: 'bar',
            data: {
                labels: data.sector_performance.map(s => s.sector),
                datasets: [{
                    label: 'Performance',
                    data: data.sector_performance.map(s => s.performance),
                    backgroundColor: data.sector_performance.map(s => s.performance >= 0 ? 'rgba(40, 167, 69, 0.5)' : 'rgba(220, 53, 69, 0.5)'),
                    borderColor: data.sector_performance.map(s => s.performance >= 0 ? 'rgb(40, 167, 69)' : 'rgb(220, 53, 69)'),
                    borderWidth: 1
                }]
            },
            options: {
                ...chartConfig,
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: {
                            callback: value => formatPercentage(value)
                        }
                    }
                }
            }
        });

        // Top Movers
        const topMoversContainer = document.getElementById('top-movers');
        topMoversContainer.innerHTML = data.top_movers.map(stock => `
            <div class="stock-card p-3 border-bottom">
                <div class="d-flex justify-content-between align-items-center">
                    <div>
                        <h6 class="mb-1">${stock.symbol}</h6>
                        <small class="text-muted">${stock.name}</small>
                    </div>
                    <div class="text-end">
                        <div class="fw-bold">${formatNumber(stock.price)}</div>
                        <div class="${stock.change_percent >= 0 ? 'positive' : 'negative'}">
                            ${stock.change_percent >= 0 ? '▲' : '▼'} ${formatPercentage(Math.abs(stock.change_percent))}
                        </div>
                    </div>
                </div>
            </div>
        `).join('');
    } catch (error) {
        console.error('Error loading market overview:', error);
    }
};

// Load technical analysis
const loadTechnicalAnalysis = async (symbol, period) => {
    try {
        const [technicalResponse, chartResponse] = await Promise.all([
            fetch(`/api/technical/${symbol}?period=${period}`),
            fetch(`/api/chart_data/${symbol}?period=${period}`)
        ]);
        
        const [technicalData, chartData] = await Promise.all([
            technicalResponse.json(),
            chartResponse.json()
        ]);

        // Price Chart
        const priceCtx = document.getElementById('price-chart').getContext('2d');
        new Chart(priceCtx, {
            type: 'candlestick',
            data: {
                labels: chartData.dates,
                datasets: [{
                    label: symbol,
                    data: chartData.prices.map((price, i) => ({
                        t: chartData.dates[i],
                        o: price.open,
                        h: price.high,
                        l: price.low,
                        c: price.close
                    }))
                }]
            },
            options: {
                ...chartConfig,
                scales: {
                    y: {
                        position: 'right'
                    }
                }
            }
        });

        // Volume Chart
        const volumeCtx = document.getElementById('volume-chart').getContext('2d');
        new Chart(volumeCtx, {
            type: 'bar',
            data: {
                labels: chartData.dates,
                datasets: [{
                    label: 'Volume',
                    data: chartData.volumes,
                    backgroundColor: chartData.prices.map(p => p.close >= p.open ? 'rgba(40, 167, 69, 0.5)' : 'rgba(220, 53, 69, 0.5)')
                }]
            },
            options: {
                ...chartConfig,
                scales: {
                    y: {
                        position: 'right',
                        ticks: {
                            callback: value => formatVolume(value)
                        }
                    }
                }
            }
        });

        // Technical Indicators
        const indicatorsContainer = document.getElementById('technical-indicators');
        indicatorsContainer.innerHTML = `
            <div class="mb-3">
                <h6 class="mb-2">Moving Averages</h6>
                <div class="d-flex flex-wrap gap-2">
                    ${Object.entries(technicalData.indicators.moving_averages).map(([period, value]) => `
                        <span class="indicator-badge bg-light">
                            MA${period}: ${formatNumber(value)}
                        </span>
                    `).join('')}
                </div>
            </div>
            <div class="mb-3">
                <h6 class="mb-2">RSI</h6>
                <div class="progress mb-2" style="height: 20px;">
                    <div class="progress-bar ${technicalData.indicators.rsi < 30 ? 'bg-danger' : technicalData.indicators.rsi > 70 ? 'bg-success' : 'bg-warning'}"
                         role="progressbar"
                         style="width: ${technicalData.indicators.rsi}%"
                         aria-valuenow="${technicalData.indicators.rsi}"
                         aria-valuemin="0"
                         aria-valuemax="100">
                        ${formatNumber(technicalData.indicators.rsi)}
                    </div>
                </div>
            </div>
            <div>
                <h6 class="mb-2">MACD</h6>
                <div class="d-flex flex-wrap gap-2">
                    <span class="indicator-badge bg-light">
                        MACD: ${formatNumber(technicalData.indicators.macd.value)}
                    </span>
                    <span class="indicator-badge bg-light">
                        Signal: ${formatNumber(technicalData.indicators.macd.signal)}
                    </span>
                    <span class="indicator-badge ${technicalData.indicators.macd.histogram >= 0 ? 'bg-success text-white' : 'bg-danger text-white'}">
                        Histogram: ${formatNumber(technicalData.indicators.macd.histogram)}
                    </span>
                </div>
            </div>
        `;

        // Volume Analysis
        const volumeAnalysisContainer = document.getElementById('volume-analysis');
        volumeAnalysisContainer.innerHTML = `
            <div class="mb-3">
                <h6 class="mb-2">Volume Statistics</h6>
                <div class="row">
                    <div class="col-6">
                        <small class="text-muted">Average Volume</small>
                        <div class="fw-bold">${formatVolume(technicalData.volume.average)}</div>
                    </div>
                    <div class="col-6">
                        <small class="text-muted">Relative Volume</small>
                        <div class="fw-bold">${formatNumber(technicalData.volume.relative)}x</div>
                    </div>
                </div>
            </div>
            <div>
                <h6 class="mb-2">Volume Trend</h6>
                <div class="d-flex align-items-center gap-2">
                    <i class="bi ${technicalData.volume.trend === 'increasing' ? 'bi-arrow-up-circle-fill text-success' : 
                                  technicalData.volume.trend === 'decreasing' ? 'bi-arrow-down-circle-fill text-danger' : 
                                  'bi-dash-circle-fill text-warning'}"></i>
                    <span class="text-capitalize">${technicalData.volume.trend}</span>
                </div>
            </div>
        `;
    } catch (error) {
        console.error('Error loading technical analysis:', error);
    }
};

// Load stock comparison
const loadStockComparison = async (symbols, period) => {
    try {
        const response = await fetch(`/api/compare?symbols=${symbols.join(',')}&period=${period}`);
        const data = await response.json();

        const compareCtx = document.getElementById('compare-chart').getContext('2d');
        new Chart(compareCtx, {
            type: 'line',
            data: {
                labels: data.dates,
                datasets: symbols.map(symbol => ({
                    label: symbol,
                    data: data.prices[symbol],
                    borderWidth: 2,
                    fill: false,
                    tension: 0.1
                }))
            },
            options: {
                ...chartConfig,
                scales: {
                    y: {
                        position: 'right',
                        ticks: {
                            callback: value => formatNumber(value)
                        }
                    }
                }
            }
        });
    } catch (error) {
        console.error('Error loading stock comparison:', error);
    }
};

// Load news
const loadNews = async (todayOnly = true) => {
    try {
        const response = await fetch(`/api/news?today_only=${todayOnly}`);
        const news = await response.json();

        const newsContainer = document.getElementById('news-container');
        newsContainer.innerHTML = news.map(item => `
            <div class="news-item p-3">
                <div class="d-flex justify-content-between align-items-start mb-2">
                    <h6 class="mb-0">${item.title}</h6>
                    <span class="news-time ms-2">${new Date(item.time).toLocaleTimeString()}</span>
                </div>
                <p class="mb-1">${item.summary}</p>
                <div class="d-flex gap-2">
                    ${item.symbols.map(symbol => `
                        <span class="badge bg-light text-dark">${symbol}</span>
                    `).join('')}
                </div>
            </div>
        `).join('');
    } catch (error) {
        console.error('Error loading news:', error);
    }
};

// Load available symbols
const loadSymbols = async () => {
    try {
        const response = await fetch('/api/symbols');
        const symbols = await response.json();

        // Technical Analysis symbol selector
        const technicalSymbol = document.getElementById('technical-symbol');
        technicalSymbol.innerHTML = `
            <option value="" disabled selected>Select Stock</option>
            ${symbols.map(symbol => `<option value="${symbol}">${symbol}</option>`).join('')}
        `;

        // Compare stocks selectors
        const stock1 = document.getElementById('stock1');
        const stock2 = document.getElementById('stock2');
        
        stock1.innerHTML = symbols.map(symbol => `<option value="${symbol}">${symbol}</option>`).join('');
        stock2.innerHTML = symbols.map(symbol => `<option value="${symbol}">${symbol}</option>`).join('');
    } catch (error) {
        console.error('Error loading symbols:', error);
    }
};

// Event listeners
document.addEventListener('DOMContentLoaded', () => {
    // Load initial data
    loadMarketIndices();
    loadMarketOverview();
    loadSymbols();
    loadNews();

    // Technical Analysis events
    const technicalSymbol = document.getElementById('technical-symbol');
    const technicalPeriod = document.getElementById('technical-period');

    const updateTechnical = () => {
        if (technicalSymbol.value) {
            loadTechnicalAnalysis(technicalSymbol.value, technicalPeriod.value);
        }
    };

    technicalSymbol.addEventListener('change', updateTechnical);
    technicalPeriod.addEventListener('change', updateTechnical);

    // Compare stocks events
    const stock1 = document.getElementById('stock1');
    const stock2 = document.getElementById('stock2');
    const comparePeriod = document.getElementById('compare-period');

    const updateComparison = () => {
        const selectedStocks = [...stock1.selectedOptions, ...stock2.selectedOptions].map(option => option.value);
        if (selectedStocks.length >= 2) {
            loadStockComparison(selectedStocks, comparePeriod.value);
        }
    };

    stock1.addEventListener('change', updateComparison);
    stock2.addEventListener('change', updateComparison);
    comparePeriod.addEventListener('change', updateComparison);

    // News filter event
    const todayOnly = document.getElementById('today-only');
    todayOnly.addEventListener('change', () => loadNews(todayOnly.checked));

    // Auto-refresh market data every 5 minutes
    setInterval(() => {
        loadMarketIndices();
        loadMarketOverview();
        if (technicalSymbol.value) {
            loadTechnicalAnalysis(technicalSymbol.value, technicalPeriod.value);
        }
        if (todayOnly.checked) {
            loadNews(true);
        }
    }, 300000);
}); 