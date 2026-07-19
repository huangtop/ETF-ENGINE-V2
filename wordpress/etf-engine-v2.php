/**
 * Plugin Name: ETF Engine v2 Ranking — General / Pro
 * Description: ETF ranking homepage with general/pro modes and multi-dimensional TW/US ETF filters.
 * Version: 2.3.0
 */

if (!defined('ABSPATH')) {
    exit;
}

function etf_v2_base_url() {
    $default_url = 'https://raw.githubusercontent.com/huangtop/ETF-ENGINE-V2/main/data/public';
    $saved_url   = get_option('etf_v2_base_url', $default_url);

    return rtrim(esc_url_raw((string) $saved_url), '/');
}

function etf_v2_fetch_json($path) {
    $force_refresh = (
        isset($_GET['refresh']) &&
        sanitize_text_field(wp_unslash($_GET['refresh'])) === '1' &&
        current_user_can('manage_options')
    );

    $path = ltrim((string) $path, '/');
    $key  = 'etf_v2_' . md5($path);

    if ($force_refresh) {
        delete_transient($key);
    } else {
        $cached = get_transient($key);
        if ($cached !== false && is_array($cached)) {
            return $cached;
        }
    }

    $url = add_query_arg(
        'v',
        $force_refresh ? time() : null,
        etf_v2_base_url() . '/' . $path
    );

    $response = wp_remote_get(
        $url,
        array(
            'timeout'     => 20,
            'redirection' => 5,
            'headers'     => array('Accept' => 'application/json'),
        )
    );

    if (is_wp_error($response)) {
        return array();
    }

    if ((int) wp_remote_retrieve_response_code($response) !== 200) {
        return array();
    }

    $data = json_decode(wp_remote_retrieve_body($response), true);
    if (!is_array($data)) {
        return array();
    }

    set_transient($key, $data, HOUR_IN_SECONDS);
    return $data;
}

function etf_v2_shortcode($atts) {
    $atts = shortcode_atts(
        array(
            'market'         => 'TW',
            'classification' => '',
            'limit'          => '100',
        ),
        $atts,
        'etf_engine_v2'
    );

    $market = strtoupper(sanitize_text_field($atts['market']));
    if (!in_array($market, array('TW', 'US'), true)) {
        $market = 'TW';
    }

    $items = etf_v2_fetch_json('markets/' . $market . '.json');
    if (!is_array($items)) {
        $items = array();
    }

    $classification = sanitize_text_field($atts['classification']);
    if ($classification !== '' && strpos($classification, ':') !== false) {
        list($dimension, $code) = array_map('trim', explode(':', $classification, 2));

        $items = array_values(array_filter($items, function ($item) use ($dimension, $code) {
            $rows = isset($item['classifications']) && is_array($item['classifications'])
                ? $item['classifications']
                : array();

            foreach ($rows as $row) {
                if (
                    isset($row['dimension'], $row['code']) &&
                    (string) $row['dimension'] === $dimension &&
                    (string) $row['code'] === $code
                ) {
                    return true;
                }
            }
            return false;
        }));
    }

    $limit = max(1, min(500, absint($atts['limit'])));
    $items = array_slice($items, 0, $limit);

    $wrapper_id = 'etf_v2_' . wp_generate_uuid4();

    ob_start();
    ?>
    <div
        id="<?php echo esc_attr($wrapper_id); ?>"
        class="etf-v2"
        data-items="<?php echo esc_attr(wp_json_encode($items)); ?>"
    >
        <div class="etf-v2-mode-switch" role="group" aria-label="顯示模式">
            <button type="button" class="etf-v2-mode-button is-active" data-mode="general">
                一般模式
            </button>
            <button type="button" class="etf-v2-mode-button" data-mode="pro">
                專業模式
            </button>
        </div>

        <div class="etf-v2-toolbar">
            <input class="etf-v2-search" type="search" placeholder="搜尋代碼或名稱">

            <select class="etf-v2-metric" aria-label="選擇排名指標">
                <option value="total_return_1y">報酬表現</option>
                <option value="sharpe_ratio">穩定度</option>
                <option value="alpha">超越大盤能力</option>
                <option value="beta">市場敏感度</option>
                <option value="max_drawdown">抗跌能力</option>
                <option value="expense_ratio">低成本</option>
            </select>
        </div>

        <div class="etf-v2-filters">
            <select class="etf-v2-filter" data-dimension="management_style" aria-label="管理方式">
                <option value="">全部管理方式</option>
            </select>

            <select class="etf-v2-filter" data-dimension="asset_class" aria-label="資產類別">
                <option value="">全部資產類別</option>
            </select>

            <select class="etf-v2-filter" data-dimension="strategy" aria-label="投資策略">
                <option value="">全部投資策略</option>
            </select>

            <select class="etf-v2-filter" data-dimension="sector" aria-label="產業類別">
                <option value="">全部產業</option>
            </select>

            <select class="etf-v2-filter" data-dimension="theme" aria-label="主題類別">
                <option value="">全部主題</option>
            </select>

            <button type="button" class="etf-v2-clear-filters">清除篩選</button>
        </div>

        <div class="etf-v2-explanation" aria-live="polite">
            <strong class="etf-v2-explanation-title">報酬表現</strong>
            <span class="etf-v2-explanation-text">比較近一年的累積報酬，數值越高排名越前。</span>
        </div>

        <?php if (empty($items)) : ?>
            <div class="etf-v2-notice">
                找不到 ETF 資料。請確認 GitHub JSON 網址及 GitHub Actions 是否已成功執行。
            </div>
        <?php else : ?>
            <div class="etf-v2-summary">
                <div>
                    <span>排名指標</span>
                    <strong class="etf-v2-summary-metric">一年報酬</strong>
                </div>
                <div>
                    <span>符合條件</span>
                    <strong class="etf-v2-summary-count">0 檔</strong>
                </div>
            </div>

            <div class="etf-v2-podium"></div>
            <div class="etf-v2-grid"></div>
        <?php endif; ?>
    </div>

    <style>
        .etf-v2,.etf-v2 *{box-sizing:border-box}
        .etf-v2{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:18px}
        .etf-v2-mode-switch{display:inline-flex;gap:4px;margin-bottom:12px;padding:4px;border:1px solid #e2e8f0;border-radius:10px;background:#f8fafc}
        .etf-v2-mode-button{appearance:none;border:0;border-radius:7px;padding:8px 14px;background:transparent;color:#64748b;font-weight:700;cursor:pointer}
        .etf-v2-mode-button.is-active{background:#fff;color:#1d4ed8;box-shadow:0 1px 3px rgba(15,23,42,.12)}
        .etf-v2-toolbar{display:grid;grid-template-columns:minmax(0,1fr) minmax(180px,260px);gap:10px;margin-bottom:10px}
        .etf-v2-filters{display:grid;grid-template-columns:repeat(5,minmax(130px,1fr)) auto;gap:8px;margin-bottom:10px}
        .etf-v2-filter,.etf-v2-clear-filters{min-height:40px;padding:8px 10px;border:1px solid #cbd5e1;border-radius:7px;background:#fff}
        .etf-v2-clear-filters{cursor:pointer;color:#334155;font-weight:700}
        .etf-v2-clear-filters:hover{background:#f8fafc}
        .etf-v2-explanation{display:flex;flex-wrap:wrap;gap:6px 10px;align-items:baseline;margin-bottom:14px;padding:10px 12px;border-left:4px solid #3b82f6;border-radius:6px;background:#f8fafc;color:#475569}
        .etf-v2-explanation-title{color:#0f172a}
        .etf-v2-explanation-text{font-size:14px}
        .etf-v2-toolbar input,.etf-v2-toolbar select{width:100%;min-height:42px;padding:9px 12px;border:1px solid #cbd5e1;border-radius:7px;background:#fff;color:#334155}
        .etf-v2-summary{display:flex;justify-content:space-between;gap:16px;margin-bottom:16px;padding:14px 16px;border:1px solid #dbeafe;border-radius:10px;background:#eff6ff}
        .etf-v2-summary>div{display:flex;flex-direction:column;gap:3px}
        .etf-v2-summary span{font-size:13px;color:#64748b}
        .etf-v2-summary strong{font-size:18px;color:#0f172a}
        .etf-v2-podium{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-bottom:18px}
        .etf-v2-top-card{border:1px solid #cbd5e1;border-radius:12px;padding:16px;background:#fff;min-width:0}
        .etf-v2-top-card[data-rank="1"]{border-color:#f59e0b;background:#fffbeb}
        .etf-v2-top-card[data-rank="2"]{border-color:#94a3b8;background:#f8fafc}
        .etf-v2-top-card[data-rank="3"]{border-color:#d97706;background:#fff7ed}
        .etf-v2-top-rank{display:inline-flex;align-items:center;min-height:28px;margin-bottom:10px;padding:4px 10px;border-radius:999px;background:#f1f5f9;color:#334155;font-size:13px;font-weight:700}
        .etf-v2-top-code{font-size:22px;font-weight:800;color:#2563eb}
        .etf-v2-top-name{margin-top:5px;min-height:42px;color:#475569;font-size:14px;overflow-wrap:anywhere}
        .etf-v2-top-value{margin-top:12px;font-size:25px;font-weight:800;color:#0f172a}
        .etf-v2-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(205px,1fr));gap:10px}
        .etf-v2-card{min-width:0;border:1px solid #e2e8f0;border-radius:9px;padding:12px;background:#fff}
        .etf-v2-card-header{display:flex;align-items:center;justify-content:space-between;gap:8px}
        .etf-v2-card-left{display:flex;align-items:center;min-width:0}
        .etf-v2-card-rank{display:inline-flex;align-items:center;justify-content:center;min-width:34px;height:24px;margin-right:7px;border-radius:999px;background:#eff6ff;color:#1d4ed8;font-size:12px;font-weight:700}
        .etf-v2-code{font-weight:700;color:#2563eb}
        .etf-v2-value{font-weight:700;text-align:right;color:#334155}
        .etf-v2-name{margin-top:6px;color:#475569;font-size:14px;overflow-wrap:anywhere}
        .etf-v2-notice{padding:16px;border:1px solid #fbbf24;border-radius:8px;background:#fffbeb;color:#92400e}
        @media(max-width:1100px){.etf-v2-filters{grid-template-columns:repeat(3,minmax(130px,1fr))}}
        @media(max-width:760px){.etf-v2-filters{grid-template-columns:1fr 1fr}.etf-v2-toolbar{grid-template-columns:1fr}.etf-v2-podium{grid-template-columns:1fr}.etf-v2-top-name{min-height:0}}
    </style>

    <?php if (!empty($items)) : ?>
        <script>
        (function () {
            const root = document.getElementById(<?php echo wp_json_encode($wrapper_id); ?>);
            if (!root) return;

            let all = [];
            try {
                all = JSON.parse(root.dataset.items || '[]');
            } catch (error) {
                console.error('ETF Engine v2 JSON parse error:', error);
                return;
            }

            const grid = root.querySelector('.etf-v2-grid');
            const podium = root.querySelector('.etf-v2-podium');
            const search = root.querySelector('.etf-v2-search');
            const select = root.querySelector('.etf-v2-metric');
            const summaryMetric = root.querySelector('.etf-v2-summary-metric');
            const summaryCount = root.querySelector('.etf-v2-summary-count');
            const modeButtons = root.querySelectorAll('.etf-v2-mode-button');
            const explanationTitle = root.querySelector('.etf-v2-explanation-title');
            const explanationText = root.querySelector('.etf-v2-explanation-text');
            const filterSelects = root.querySelectorAll('.etf-v2-filter');
            const clearFilters = root.querySelector('.etf-v2-clear-filters');

            let displayMode = 'general';

            const metricConfig = {
                total_return_1y: {
                    general: '報酬表現',
                    pro: '一年報酬',
                    description: '比較近一年的累積報酬，數值越高排名越前。',
                    proDescription: '近一年累積總報酬率。',
                    direction: 'desc'
                },
                sharpe_ratio: {
                    general: '穩定度',
                    pro: 'Sharpe Ratio',
                    description: '衡量承擔風險後得到的報酬，通常越高越好。',
                    proDescription: '每承擔一單位波動風險所取得的超額報酬。',
                    direction: 'desc'
                },
                alpha: {
                    general: '超越大盤能力',
                    pro: 'Alpha',
                    description: '觀察 ETF 是否有機會跑贏比較基準，數值越高越好。',
                    proDescription: '相對績效基準的風險調整後超額報酬。',
                    direction: 'desc'
                },
                beta: {
                    general: '市場敏感度',
                    pro: 'Beta',
                    description: '數值越接近 1，走勢通常越接近大盤；大於 1 波動可能更明顯。',
                    proDescription: 'ETF 報酬相對市場報酬的敏感程度，本項預設依數值由低到高排列。',
                    direction: 'asc'
                },
                max_drawdown: {
                    general: '抗跌能力',
                    pro: '最大回撤',
                    description: '歷史高點到低點的最大跌幅；越接近 0，抗跌能力通常越好。',
                    proDescription: '觀察期間內從波峰到波谷的最大跌幅，數值越接近 0 越好。',
                    direction: 'desc'
                },
                expense_ratio: {
                    general: '低成本',
                    pro: '費用率',
                    description: '每年由基金資產中扣除的管理成本，通常越低越好。',
                    proDescription: 'ETF 年度總費用率，本項依數值由低到高排列。',
                    direction: 'asc'
                }
            };

            function metricLabel(code) {
                const config = metricConfig[code];
                if (!config) return code;
                return displayMode === 'pro' ? config.pro : config.general;
            }

            function updateMetricOptions() {
                Array.from(select.options).forEach(function (option) {
                    option.textContent = metricLabel(option.value);
                });
            }

            const classificationLabels = {
                management_style: {
                    active: '主動式',
                    passive: '被動式'
                },
                asset_class: {
                    equity: '股票',
                    fixed_income: '債券',
                    commodity: '商品',
                    digital_asset: '數位資產',
                    real_estate: '不動產'
                },
                strategy: {
                    high_dividend: '高股息',
                    dividend_growth: '股息成長',
                    income: '收益型',
                    covered_call: '掩護性買權',
                    low_volatility: '低波動',
                    momentum: '動能',
                    value: '價值',
                    growth: '成長',
                    equal_weight: '等權重',
                    esg: 'ESG／永續',
                    smart_beta: 'Smart Beta',
                    broad_market: '大盤型',
                    aggregate_bond: '綜合債券',
                    treasury: '美國公債',
                    gold: '黃金',
                    real_estate: '不動產',
                    leveraged: '槓桿型',
                    bitcoin_futures: '比特幣期貨',
                    quality: '品質'
                },
                sector: {
                    semiconductors: '半導體',
                    technology: '科技',
                    financials: '金融',
                    health_care: '醫療保健',
                    energy: '能源',
                    automotive: '汽車／電動車',
                    real_estate: '不動產'
                },
                theme: {
                    artificial_intelligence: '人工智慧',
                    disruptive_innovation: '顛覆式創新',
                    robotics: '機器人／自動化',
                    semiconductors: '半導體',
                    cloud_computing: '雲端運算',
                    cybersecurity: '資安',
                    data_center: '資料中心',
                    electric_vehicles: '電動車',
                    nuclear_energy: '核能／鈾礦',
                    space: '太空',
                    quantum_computing: '量子運算',
                    infrastructure: '基礎建設'
                }
            };

            function classificationLabel(dimension, code) {
                const map = classificationLabels[dimension] || {};
                return map[code] || code
                    .replaceAll('_', ' ')
                    .replace(/\b\w/g, function (letter) {
                        return letter.toUpperCase();
                    });
            }

            function classificationSet(item, dimension) {
                const rows = Array.isArray(item.classifications)
                    ? item.classifications
                    : [];

                return new Set(
                    rows
                        .filter(function (row) {
                            return row.dimension === dimension;
                        })
                        .map(function (row) {
                            return row.code;
                        })
                );
            }

            function initializeFilters() {
                filterSelects.forEach(function (selectElement) {
                    const dimension = selectElement.dataset.dimension;
                    const values = new Set();

                    all.forEach(function (item) {
                        classificationSet(item, dimension).forEach(function (code) {
                            values.add(code);
                        });
                    });

                    Array.from(values)
                        .sort(function (left, right) {
                            return classificationLabel(dimension, left)
                                .localeCompare(
                                    classificationLabel(dimension, right),
                                    'zh-Hant'
                                );
                        })
                        .forEach(function (code) {
                            const option = document.createElement('option');
                            option.value = code;
                            option.textContent = classificationLabel(dimension, code);
                            selectElement.appendChild(option);
                        });
                });
            }

            function selectedFiltersMatch(item) {
                return Array.from(filterSelects).every(function (selectElement) {
                    const selected = selectElement.value;

                    if (!selected) {
                        return true;
                    }

                    return classificationSet(
                        item,
                        selectElement.dataset.dimension
                    ).has(selected);
                });
            }

            function displayName(item) {
                return item.display_name ||
                    item.name_zh ||
                    item.name ||
                    item.ticker ||
                    '';
            }

            function escapeHtml(value) {
                return String(value ?? '')
                    .replaceAll('&', '&amp;')
                    .replaceAll('<', '&lt;')
                    .replaceAll('>', '&gt;')
                    .replaceAll('"', '&quot;')
                    .replaceAll("'", '&#039;');
            }

            function metricValue(item, code) {
                const metric = item && item.metrics && item.metrics[code];
                if (!metric || metric.value === null || metric.value === undefined) return null;
                const number = Number(metric.value);
                return Number.isFinite(number) ? number : null;
            }

            function formatMetric(value, code) {
                if (value === null) return 'N/A';
                if (['total_return_1y', 'alpha', 'max_drawdown', 'expense_ratio'].includes(code)) {
                    return value.toFixed(2) + '%';
                }
                return value.toFixed(2);
            }

            function render() {
                const query = search.value.trim().toLowerCase();
                const code = select.value;

                const rows = all
                    .filter(function (item) {
                        const text = String(item.ticker || '') + ' ' + String(item.name || '');
                        return text.toLowerCase().includes(query);
                    })
                    .sort(function (a, b) {
                        const av = metricValue(a, code);
                        const bv = metricValue(b, code);
                        if (av === null && bv === null) return 0;
                        if (av === null) return 1;
                        if (bv === null) return -1;
                        const direction = metricConfig[code] && metricConfig[code].direction === 'asc'
                            ? 1
                            : -1;

                        return direction === 1 ? av - bv : bv - av;
                    });

                const rankedRows = rows.filter(function (item) {
                    return metricValue(item, code) !== null;
                });
                const topRows = rankedRows.slice(0, 3);

                const config = metricConfig[code] || {};
                summaryMetric.textContent = metricLabel(code);
                summaryCount.textContent = rows.length + ' 檔';
                explanationTitle.textContent = metricLabel(code);
                explanationText.textContent = displayMode === 'pro'
                    ? (config.proDescription || '')
                    : (config.description || '');

                podium.innerHTML = topRows.map(function (item, index) {
                    const rank = index + 1;
                    const medal = rank === 1 ? '🏆' : (rank === 2 ? '🥈' : '🥉');
                    return '<div class="etf-v2-top-card" data-rank="' + rank + '">' +
                        '<div class="etf-v2-top-rank">' + medal + ' 第 ' + rank + ' 名</div>' +
                        '<div class="etf-v2-top-code">' + escapeHtml(item.ticker || '') + '</div>' +
                        '<div class="etf-v2-top-name">' + escapeHtml(item.name || '') + '</div>' +
                        '<div class="etf-v2-top-value">' + escapeHtml(formatMetric(metricValue(item, code), code)) + '</div>' +
                    '</div>';
                }).join('');

                if (!topRows.length) {
                    podium.innerHTML = '<div class="etf-v2-notice">目前選擇的指標沒有可排名資料。</div>';
                }

                grid.innerHTML = rows.map(function (item, index) {
                    const value = metricValue(item, code);
                    const rank = value === null ? '—' : String(index + 1);
                    return '<div class="etf-v2-card">' +
                        '<div class="etf-v2-card-header">' +
                            '<span class="etf-v2-card-left">' +
                                '<span class="etf-v2-card-rank">#' + rank + '</span>' +
                                '<span class="etf-v2-code">' + escapeHtml(item.ticker || '') + '</span>' +
                            '</span>' +
                            '<span class="etf-v2-value">' + escapeHtml(formatMetric(value, code)) + '</span>' +
                        '</div>' +
                        '<div class="etf-v2-name">' + escapeHtml(item.name || '') + '</div>' +
                    '</div>';
                }).join('');
            }

            search.addEventListener('input', render);
            select.addEventListener('change', render);

            filterSelects.forEach(function (selectElement) {
                selectElement.addEventListener('change', render);
            });

            clearFilters.addEventListener('click', function () {
                filterSelects.forEach(function (selectElement) {
                    selectElement.value = '';
                });
                render();
            });

            modeButtons.forEach(function (button) {
                button.addEventListener('click', function () {
                    displayMode = button.dataset.mode === 'pro' ? 'pro' : 'general';

                    modeButtons.forEach(function (item) {
                        item.classList.toggle('is-active', item === button);
                    });

                    updateMetricOptions();
                    render();
                });
            });

            initializeFilters();
            updateMetricOptions();
            render();
        }());
        </script>
    <?php endif; ?>
    <?php

    return ob_get_clean();
}

add_shortcode('etf_engine_v2', 'etf_v2_shortcode');

function etf_v2_register_settings() {
    register_setting(
        'etf_v2_settings_group',
        'etf_v2_base_url',
        array(
            'type'              => 'string',
            'sanitize_callback' => 'esc_url_raw',
            'default'           => 'https://raw.githubusercontent.com/huangtop/ETF-ENGINE-V2/main/data/public',
        )
    );
}
add_action('admin_init', 'etf_v2_register_settings');

function etf_v2_add_settings_page() {
    add_options_page(
        'ETF Engine v2',
        'ETF Engine v2',
        'manage_options',
        'etf-v2',
        'etf_v2_render_settings_page'
    );
}
add_action('admin_menu', 'etf_v2_add_settings_page');

function etf_v2_render_settings_page() {
    if (!current_user_can('manage_options')) {
        return;
    }
    ?>
    <div class="wrap">
        <h1>ETF Engine v2</h1>
        <form method="post" action="options.php">
            <?php settings_fields('etf_v2_settings_group'); ?>
            <table class="form-table" role="presentation">
                <tr>
                    <th scope="row"><label for="etf_v2_base_url">Public JSON base URL</label></th>
                    <td>
                        <input
                            id="etf_v2_base_url"
                            class="regular-text"
                            type="url"
                            name="etf_v2_base_url"
                            value="<?php echo esc_attr(etf_v2_base_url()); ?>"
                        >
                    </td>
                </tr>
            </table>
            <?php submit_button(); ?>
        </form>
    </div>
    <?php
}