function etf_engine_filter_shortcode($atts) {
    $a = shortcode_atts(array('type' => 'HighDividend'), $atts);
    $type_map = array('MarketCap'=> '市值型','HighDividend' => '高股息', 'Active' => '主動式', 'Industry' => '產業型');
    $type = sanitize_text_field($a['type']);
    if (!array_key_exists($type, $type_map)) $type = 'HighDividend';

    $chinese_title = $type_map[$type];
    $cid = "etf_box_" . strtolower($type);

    $csv_url = "https://raw.githubusercontent.com/huangtop/ETF_Engine/main/charts_output/" . $type . "_etf_comparison_unified.csv?v=" . time();

    ob_start(); ?>
    <style>
        /* 最外層容器 */
        .etf-main-container {
            background: #ffffff !important; 
            border-radius: 12px;
            padding: 0;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            color: #334155 !important;
            overflow: hidden;
            border: 1px solid #e2e8f0;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.03); 
            margin-bottom: 25px;
            position: relative;
            z-index: 1;
        }

        /* 監控面板標題列 */
        .etf-header {
            background: #2563eb; 
            padding: 16px 20px;
        }
        .etf-header h2 { 
            margin: 0; 
            font-size: 1.15rem; 
            font-weight: 600;
            color: #ffffff !important;
        }

        /* 內部面板主體 */
        .etf-body-section {
            background: #ffffff !important;
            padding: 20px;
        }

        /* 按鈕控制區 */
        .filter-controls {
            padding: 6px 0 16px 0;
            display: flex;
            overflow-x: auto; 
            white-space: nowrap;
            gap: 8px;
            scrollbar-width: none; 
            border-bottom: 1px solid #f1f5f9;
        }
        .filter-controls::-webkit-scrollbar { display: none; }

        .btn-etf {
            background: #ffffff !important;
            border: 1px solid #cbd5e1 !important;
            color: #64748b !important;
            padding: 8px 16px;
            border-radius: 6px;
            cursor: pointer;
            transition: all 0.2s;
            font-size: 0.85rem;
            flex: 0 0 auto;
            font-weight: 500;
        }
        .btn-etf:hover {
            background: #f8fafc !important;
            color: #1e293b !important;
            border-color: #94a3b8 !important;
        }
        .btn-etf.active {
            background: #2563eb !important;
            color: #ffffff !important;
            border-color: #2563eb !important;
            box-shadow: 0 2px 4px rgba(37, 99, 235, 0.15);
        }

        /* 圖表容器 */
        .canvas-container {
			background: #ffffff !important;
			padding: 15px 0;
			margin-bottom: 15px;
			border-bottom: 1px solid #f1f5f9;
			position: relative;
			width: 100%;
			height: 420px;
			min-height: 420px;
		}
        .canvas-container canvas {
            display: block !important;
            width: 100% !important;
            height: 100% !important; /* 修正：讓畫布填滿容器固定高度 */
            z-index: 5;
        }

        /* 下方 ETF 卡片網格 */
        .etf-card-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
            gap: 12px;
            padding-top: 15px;
            background: #ffffff !important;
        }

        .etf-card {
            background: #ffffff !important;
            border: 1px solid #e2e8f0 !important;
            border-radius: 8px;
            padding: 14px;
            transition: all 0.2s;
            box-shadow: 0 1px 3px rgba(0,0,0,0.01);
            cursor: pointer;
        }
        .etf-card:hover {
            border-color: #2563eb !important;
            background: rgba(37, 99, 235, 0.01) !important;
            transform: translateY(-2px);
        }
        .etf-card.selected {
            border-color: #2563eb !important;
            background: rgba(37, 99, 235, 0.04) !important;
            box-shadow: 0 0 0 1px #2563eb;
        }

        @media (max-width: 480px) {
            .etf-card-grid { 
                grid-template-columns: repeat(2, 1fr); 
                gap: 8px; 
            }
            .etf-body-section { padding: 12px; }
            .etf-card { padding: 10px; }
            .etf-card span { font-size: 0.85rem; }
            .etf-card div { font-size: 0.75rem !important; }
            .etf-header { padding: 14px 15px; }
            .etf-header h2 { font-size: 1rem; }
            .canvas-container { height: 340px; min-height: 340px; }
        }
    </style>

    <div id="<?php echo esc_attr($cid); ?>_wrapper" class="etf-main-container" data-type="<?php echo esc_attr($type); ?>">
        <div class="etf-header">
            <h2>📊 <?php echo esc_html($chinese_title); ?> ETF 監控面板</h2>
        </div>

        <div class="etf-body-section">
            <div class="filter-controls">
                <button class="btn-etf active" data-mode="漲幅">📈 漲幅排名</button>
                <button class="btn-etf" data-mode="Alpha">🏆 報酬王 (Alpha)</button>
                <button class="btn-etf" data-mode="夏普比率">📊 性價比 (Sharp)</button>
                <button class="btn-etf" data-mode="Beta">🛡️ 波動穩健度 (Beta)</button>
                <button class="btn-etf" data-mode="ExpenseTurnover">🏺 管理費排名 (%)</button>
                <button class="btn-etf" id="<?php echo esc_attr($cid); ?>_btn_trend" data-mode="PriceTrend">📈 走勢對比 (vs 0050)</button>
                <button class="btn-etf" data-mode="DividendCalendar">📅 配息月份表</button>
            </div>

            <div class="canvas-container">
                <canvas id="<?php echo esc_attr($cid); ?>_barCanvas"></canvas>
            </div>
            
            <div id="<?php echo esc_attr($cid); ?>" class="etf-card-grid"></div>
        </div>
    </div>

    <script src="https://cdnjs.cloudflare.com/ajax/libs/PapaParse/5.3.2/papaparse.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>

    <script>
    window.etfChartInstances = window.etfChartInstances || {};

    (function() {
        const cid = "<?php echo esc_js($cid); ?>";
        const csvUrl = "<?php echo esc_js($csv_url); ?>"; 
        const container = document.getElementById(cid);
        const wrapper = document.getElementById(cid + "_wrapper");

        if (!container) return;

        // 👑 核心修正：將初始化方法直接掛載給全域，讓主導航載入文章後呼叫得到！
        window.initETFChart = function() {
            if (typeof Papa === 'undefined' || typeof Chart === 'undefined') {
                setTimeout(window.initETFChart, 250);
                return;
            }
            runEngine();
        };

        function runEngine() {
            let rawData = [];
            let currentActiveMode = '漲幅';
            const barId = cid + "_barCanvas";

            // 👑 核心修正：啟動前先把當前 ID 的舊圖表實例徹底清空，防止 Canvas 衝突
            if (window.etfChartInstances[barId]) {
                window.etfChartInstances[barId].destroy();
                window.etfChartInstances[barId] = null;
            }

            const getVal = (item, kw) => {
                let searchKey = kw;
                if (kw === '漲幅') {
                    const keys = Object.keys(item);
                    searchKey = keys.find(k => k.includes('漲幅') || k.includes('報酬率') || k.includes('Return')) || kw;
                }
                const key = Object.keys(item).find(k => String(k).includes(searchKey));
                return key ? (parseFloat(item[key]) || 0) : 0;
            };

            const parseDividendInfo = (item) => {
                const monthsStr = item['_div_months'] || '';
                if (!monthsStr || monthsStr === '[]') {
                    return { frequency: '不定期/無', count: 0, monthsText: '無資料' };
                }
                try {
                    const months = JSON.parse(monthsStr.replace(/'/g, '"')).sort((a,b) => a-b);
                    const count = months.length;
                    let frequency = '不定期';
                    
                    if (count === 12) frequency = '月配';
                    else if (count === 4) frequency = '季配';
                    else if (count === 2) frequency = '半年配';
                    else if (count === 1) frequency = '年配';
                    else if (count > 0) frequency = `年配 ${count} 次`;

                    return {
                        frequency: frequency,
                        count: count,
                        monthsText: months.join(',') + '月'
                    };
                } catch(e) {
                    return { frequency: '不定期', count: 0, monthsText: '有資料' };
                }
            };

            function updateBarChart(data, metricLabel) {
                const barCanvas = document.getElementById(barId);
                if (!barCanvas) return;

                const barCtx = barCanvas.getContext('2d');
                if (window.etfChartInstances[barId]) window.etfChartInstances[barId].destroy();

                let sortedData, labelKey, valueKey, barColor;

                if (metricLabel === 'ExpenseTurnover') {
                    sortedData = [...data].sort((a,b) => getVal(b, '管理費') - getVal(a, '管理費'));
                    labelKey = '證券代碼';
                    valueKey = '管理費';
                    barColor = 'rgba(239, 68, 68, 0.8)';
                } else {
                    let benchmarkItem = data.find(item => String(item['證券代碼']).includes('0050')) || null;
                    let otherItems = data.filter(item => !String(item['證券代碼']).includes('0050'));
                    otherItems.sort((a, b) => getVal(b, metricLabel) - getVal(a, metricLabel));
                    sortedData = benchmarkItem ? [...otherItems, benchmarkItem] : otherItems;

                    labelKey = '證券代碼';
                    valueKey = metricLabel;
                    barColor = (item) => String(item['證券代碼']).includes('0050') 
                        ? 'rgba(249, 115, 22, 0.85)' 
                        : 'rgba(37, 99, 235, 0.75)';
                }

                const chartLabels = sortedData.map(item => String(item[labelKey] || '').split('.')[0]);

                window.etfChartInstances[barId] = new Chart(barCtx, {
                    type: 'bar',
                    data: {
                        labels: chartLabels,
                        datasets: [{
							label: metricLabel === 'ExpenseTurnover' ? '管理費 (%)' : (metricLabel === '漲幅' ? '累計漲跌 (%)' : metricLabel),
                            data: sortedData.map(item => getVal(item, valueKey)),
                            backgroundColor: sortedData.map(item => typeof barColor === 'function' ? barColor(item) : barColor),
                            borderColor: '#1e40af',
                            borderWidth: 1
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        animation: { duration: 600 },
                        scales: {
                            y: { ticks: { color: '#64748b', font: { size: 11 } }, grid: { color: '#f1f5f9' } },
                            x: {
                                ticks: {
                                    color: '#334155',
                                    font: { size: 11.5 },
                                    maxRotation: 0,
                                    minRotation: 0,
                                    autoSkip: true,
                                    autoSkipPadding: 12
                                },
                                grid: { display: false }
                            }
                        },
                        plugins: {
                            legend: { display: true, position: 'top', labels: { color: '#475569', font: { size: 13 } } },
                            tooltip: {
                                callbacks: {
                                    title: function(tooltipItems) {
                                        const idx = tooltipItems[0].dataIndex;
                                        const item = sortedData[idx];
                                        return String(item['證券代碼']).split('.')[0] + ' ' + (item['名稱'] || '');
                                    }
                                }
                            }
                        }
                    }
                });
            }

            function updateDividendCalendar(data) {
                const barCanvas = document.getElementById(barId);
                if (!barCanvas) return;
                const barCtx = barCanvas.getContext('2d');
                if (window.etfChartInstances[barId]) window.etfChartInstances[barId].destroy();

                const calendar = Array.from({ length: 12 }, () => []);
                data.forEach(item => {
                    const monthsStr = item['_div_months'] || '';
                    const code = String(item['證券代碼'] || '').split('.')[0];
                    if (monthsStr && monthsStr !== '[]') {
                        try {
                            const months = JSON.parse(monthsStr.replace(/'/g, '"'));
                            months.forEach(m => {
                                if (m >= 1 && m <= 12) calendar[m-1].push(code);
                            });
                        } catch(e) {}
                    }
                });

                window.etfChartInstances[barId] = new Chart(barCtx, {
                    type: 'bar',
                    data: { labels: [], datasets: [] },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: { legend: { display: false }, tooltip: { enabled: false } }
                    },
                    plugins: [{
                        id: 'dividendTable',
                        afterDraw: (chart) => {
                            const { ctx, width, height } = chart;
                            ctx.save();
                            const rows = 3; const cols = 4;
                            const cellWidth = width / cols; const cellHeight = height / rows;
                            ctx.strokeStyle = '#e2e8f0'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
                            
                            for (let i = 0; i < rows; i++) {
                                for (let j = 0; j < cols; j++) {
                                    const m = i * cols + j + 1;
                                    const x = j * cellWidth; const y = i * cellHeight;
                                    ctx.fillStyle = '#ffffff'; ctx.fillRect(x, y, cellWidth, cellHeight);
                                    ctx.strokeRect(x, y, cellWidth, cellHeight);
                                    ctx.font = 'bold 14px sans-serif'; ctx.fillStyle = '#2563eb';
                                    ctx.fillText(m + '月', x + cellWidth/2, y + 18);
                                    ctx.font = '11px sans-serif'; ctx.fillStyle = '#475569';
                                    const tickers = calendar[m-1];
                                    const maxVisible = window.innerWidth < 480 ? 3 : 4;
                                    tickers.slice(0, maxVisible).forEach((t, idx) => {
                                        ctx.fillText(t, x + cellWidth/2, y + 42 + (idx * 16));
                                    });
                                    if (tickers.length > maxVisible) {
                                        ctx.fillStyle = '#94a3b8';
                                        ctx.fillText(`+等${tickers.length}支`, x + cellWidth/2, y + 42 + (maxVisible * 16));
                                    }
                                }
                            }
                            ctx.restore();
                        }
                    }]
                });
            }

            function updateInteractiveTrend(data) {
                const barCanvas = document.getElementById(barId);
                if (!barCanvas) return;
                const barCtx = barCanvas.getContext('2d');
                if (window.etfChartInstances[barId]) window.etfChartInstances[barId].destroy();

                const sampleItem = data[0] || {};
                const trendKey = Object.keys(sampleItem).find(k => k.includes('趨勢')) || '趨勢數據';
                
                let targetETFs = data.slice(0, 6);
                const has0050 = data.find(item => String(item['證券代碼']).includes('0050'));
                if (has0050 && !targetETFs.some(item => String(item['證券代碼']).includes('0050'))) {
                    targetETFs.push(has0050);
                }

                const allDates = new Set(); const datasets = [];
                const colors = ['#2563eb', '#ef4444', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899'];

                targetETFs.forEach((item, idx) => {
                    const trendStr = item[trendKey] || '';
                    if (!trendStr) return;
                    const ticker = String(item['證券代碼'] || '').split('.')[0];
                    const isBenchmark = ticker.includes('0050');
                    const points = [];

                    trendStr.split('|').forEach(pair => {
                        if (!pair) return;
                        const [dateStr, valStr] = pair.split(':');
                        if (!dateStr || !valStr) return;
                        const formattedDate = dateStr.length === 8 
                            ? `${dateStr.substring(0,4)}-${dateStr.substring(4,6)}-${dateStr.substring(6,8)}` 
                            : dateStr.trim();
                        allDates.add(formattedDate);
                        points.push({ x: formattedDate, y: parseFloat(valStr) });
                    });

                    if (points.length > 0) {
                        datasets.push({
                            label: isBenchmark ? '0050 大盤' : ticker,
                            data: points,
                            borderColor: isBenchmark ? '#475569' : colors[idx % colors.length],
                            borderWidth: isBenchmark ? 3.5 : 2,
                            tension: 0.15,
                            spanGaps: true,
                            pointRadius: 0,
                            pointHoverRadius: 3.5
                        });
                    }
                });

                window.etfChartInstances[barId] = new Chart(barCtx, {
                    type: 'line',
                    data: { labels: Array.from(allDates).sort(), datasets: datasets },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        interaction: { mode: 'index', intersect: false },
                        scales: {
                            x: { type: 'category', ticks: { color: '#64748b', autoSkip: true, maxTicksLimit: 10, maxRotation: 0 }, grid: { display: false } },
                            y: { ticks: { color: '#64748b', callback: v => Number(v).toFixed(1) }, grid: { color: '#f1f5f9' } }
                        },
                        plugins: { legend: { position: 'top', align: 'start' } }
                    }
                });
            }

            function updateLineChart(ticker) {
                const barCanvas = document.getElementById(barId);
                if (!barCanvas) return;
                const barCtx = barCanvas.getContext('2d');
                if (window.etfChartInstances[barId]) window.etfChartInstances[barId].destroy();

                const selectedItem = rawData.find(item => String(item['證券代碼']).includes(ticker));
                const benchmarkItem = rawData.find(item => String(item['證券代碼']).includes('0050'));
                if (!selectedItem) return;

                const sampleItem = rawData[0] || {};
                const trendKey = Object.keys(sampleItem).find(k => k.includes('趨勢')) || '趨勢數據';
                let allLabelsSet = new Set(); let datasets = [];

                const parseTrendData = (item, label, color, width) => {
                    const trendStr = item[trendKey] || '';
                    if (!trendStr) return;
                    let points = [];
                    trendStr.split('|').forEach(pair => {
                        if (!pair) return;
                        const parts = pair.split(':');
                        if (parts.length === 2) {
                            const rawDate = parts[0].trim();
                            const formattedDate = rawDate.length === 8 ? `${rawDate.substring(0,4)}-${rawDate.substring(4,6)}-${rawDate.substring(6,8)}` : rawDate;
                            allLabelsSet.add(formattedDate);
                            points.push({ x: formattedDate, y: parseFloat(parts[1]) });
                        }
                    });
                    if (points.length > 0) {
                        datasets.push({
                            label: label, data: points, borderColor: color, borderWidth: width, pointRadius: 0, fill: false, tension: 0.1
                        });
                    }
                };

                parseTrendData(selectedItem, ticker.split('.')[0], '#2563eb', 2.5);
                if (benchmarkItem && !ticker.includes('0050')) {
                    parseTrendData(benchmarkItem, '0050 大盤', '#94a3b8', 1.5);
                }

                window.etfChartInstances[barId] = new Chart(barCtx, {
                    type: 'line',
                    data: { labels: Array.from(allLabelsSet).sort(), datasets: datasets },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        interaction: { mode: 'index', intersect: false },
                        scales: {
                            x: { type: 'category', ticks: { color: '#64748b', autoSkip: true, maxTicksLimit: 8 }, grid: { display: false } },
                            y: { ticks: { color: '#64748b' }, grid: { color: '#f1f5f9' } }
                        }
                    }
                });
            }

            function renderCards(data, mode = '漲幅') {
                const modeLabels = {
                    '漲幅': { label: '累計漲跌', unit: '%' }, 'Alpha': { label: '贏大盤', unit: '%' },
                    '夏普比率': { label: '投資CP值', unit: '' }, 'Beta': { label: '抗震度', unit: '' },
                    'ExpenseTurnover': { label: '管理費/年', unit: '%' }, 'DividendCalendar': { label: '配息月份', unit: '' }
                };
                const currentMode = modeLabels[mode] || { label: mode, unit: '' };

                container.innerHTML = data.map(item => {
                    const code = String(item['證券代碼'] || '').split('.')[0];
                    const divInfo = parseDividendInfo(item);
                    let displayVal = mode === 'ExpenseTurnover' ? getVal(item, '管理費') : getVal(item, mode);
                    let numColor = '#475569'; let formattedVal = `${displayVal}${currentMode.unit}`;

                    if (mode === 'DividendCalendar') {
                        numColor = '#2563eb'; formattedVal = `${divInfo.frequency} (${divInfo.count}次)`;
                    } else if (mode === '漲幅' || mode === 'Alpha') {
                        let val = mode === '漲幅' ? parseFloat(item['累計漲跌 (%)'] ?? item['漲幅'] ?? 0) : getVal(item, mode);
                        numColor = val >= 0 ? '#dc2626' : '#16a34a';
                        formattedVal = val >= 0 ? `+${val.toFixed(2)}%` : `${val.toFixed(2)}%`;
                        if (mode === '漲幅' && !item['累計漲跌 (%)']) formattedVal += '<span style="font-size:0.75rem;opacity:0.7;">(年)</span>';
                    } else if (mode === '夏普比率') {
                        numColor = displayVal >= 1.0 ? '#2563eb' : '#475569';
                        formattedVal = `${displayVal} (${displayVal > 1.5 ? '極高' : (displayVal > 1.0 ? '優等' : '普通')})`;
                    } else if (mode === 'Beta') {
                        numColor = displayVal < 0.8 ? '#16a34a' : (displayVal > 1.2 ? '#ea580c' : '#475569');
                        formattedVal = displayVal < 0.8 ? `抗震(${displayVal})` : (displayVal > 1.2 ? `衝鋒(${displayVal})` : `同步(${displayVal})`);
                    }

                    let cardHtml = `<div class="etf-card" data-code="${item['證券代碼']}">
                        <div style="display:flex; justify-content:space-between; margin-bottom:6px; align-items:center;">
                            <span style="color:#2563eb; font-weight:bold; font-size:1.1rem;">${code}</span>
                            <span style="color:${numColor}; font-weight:bold; font-size:0.95rem;">
                                ${formattedVal}
                                ${(parseFloat(item['資料期間 (年)'] || item['數據天數'] / 252 || 0) < 1) ? '<span style="color:#dc2626;font-size:0.75rem;font-weight:500;margin-left:4px;">(未滿一年，數據僅供參考)</span>' : ''}
                            </span>
                        </div>
                        <div style="display:flex; justify-content:space-between; font-size:0.8rem; color:#64748b; align-items:center;">
                            <span style="text-overflow:ellipsis; overflow:hidden; white-space:nowrap; max-width:90px; font-weight:500;">
                                ${item['名稱'] || item['證券名稱'] || ''}
                            </span>
                            <span style="font-size:0.75rem; color:${mode === 'DividendCalendar'?'#2563eb':'#94a3b8'}; background:${mode === 'DividendCalendar'?'rgba(37,99,235,0.1)':'#f1f5f9'}; padding:2px 6px; border-radius:4px; font-weight:bold;">
                                ${mode === 'DividendCalendar'?divInfo.monthsText:currentMode.label}
                            </span>
                        </div>
                    </div>`;

                    return cardHtml;
                }).join('');
            }

            Papa.parse(csvUrl, {
                download: true, header: true, skipEmptyLines: true,
                complete: function(results) {
                    rawData = results.data.filter(row => String(row['證券代碼'] || '').includes('.TW'));
                    rawData.sort((a,b) => getVal(b, '漲幅') - getVal(a, '漲幅'));
                    renderCards(rawData, '漲幅');
                    updateBarChart(rawData, '漲幅');
                }
            });

            wrapper.onclick = function(e) {
                const btn = e.target.closest('.btn-etf');
                const card = e.target.closest('.etf-card');
                
                if (btn) {
                    wrapper.querySelectorAll('.btn-etf').forEach(b => b.classList.remove('active'));
                    btn.classList.add('active');
                    const mode = btn.dataset.mode; currentActiveMode = mode; 
                    
                    if (mode === 'ExpenseTurnover') {
                        renderCards([...rawData].sort((a,b) => getVal(b, '管理費') - getVal(a, '管理費')), 'ExpenseTurnover');
                        updateBarChart(rawData, 'ExpenseTurnover');
                    } else if (mode === 'DividendCalendar') {
                        renderCards(rawData, 'DividendCalendar'); updateDividendCalendar(rawData);
                    } else if (mode === 'PriceTrend') {
                        renderCards(rawData, '漲幅'); updateInteractiveTrend(rawData);
                    } else {
                        rawData.sort((a,b) => getVal(b, mode) - getVal(a, mode));
                        renderCards(rawData, mode); updateBarChart(rawData, mode);
                    }
                }
                
                if (card) {
                    wrapper.querySelectorAll('.etf-card').forEach(c => c.classList.remove('selected'));
                    card.classList.add('selected');
                    wrapper.querySelectorAll('.btn-etf').forEach(b => b.classList.remove('active'));
                    const trendBtn = document.getElementById(cid + "_btn_trend");
                    if(trendBtn) trendBtn.classList.add('active');
                    updateLineChart(card.dataset.code);
                }
            };
        }

        // 👑 自動觸發一次
        window.initETFChart();
    })();
    </script>
    <?php return ob_get_clean();
}
add_shortcode('etf_filter', 'etf_engine_filter_shortcode');