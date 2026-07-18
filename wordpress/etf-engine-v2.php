/**
 * Plugin Name: ETF Engine v2
 * Description: Read ETF Engine v2 public JSON with WordPress transient caching.
 * Version: 2.0.1
 */

if (!defined('ABSPATH')) {
    exit;
}

/**
 * Public JSON base URL.
 */
function etf_v2_base_url() {
    $default_url = 'https://raw.githubusercontent.com/huangtop/ETF-ENGINE-V2/main/data/public';
    $saved_url   = get_option('etf_v2_base_url', $default_url);

    return rtrim(esc_url_raw((string) $saved_url), '/');
}

/**
 * Fetch JSON with WordPress transient caching.
 */
function etf_v2_fetch_json($path) {
    $path = ltrim((string) $path, '/');
    $key  = 'etf_v2_' . md5($path);

    $cached = get_transient($key);

    if ($cached !== false && is_array($cached)) {
        return $cached;
    }

    $url = etf_v2_base_url() . '/' . $path;

    $response = wp_remote_get(
        $url,
        array(
            'timeout'     => 20,
            'redirection' => 5,
            'headers'     => array(
                'Accept' => 'application/json',
            ),
        )
    );

    if (is_wp_error($response)) {
        return array();
    }

    $status_code = wp_remote_retrieve_response_code($response);

    if ($status_code !== 200) {
        return array();
    }

    $body = wp_remote_retrieve_body($response);
    $data = json_decode($body, true);

    if (!is_array($data)) {
        return array();
    }

    set_transient($key, $data, HOUR_IN_SECONDS);

    return $data;
}

/**
 * Get metric value safely.
 */
function etf_v2_get_metric_value($item, $metric_code) {
    if (
        !isset($item['metrics']) ||
        !is_array($item['metrics']) ||
        !isset($item['metrics'][$metric_code]) ||
        !is_array($item['metrics'][$metric_code]) ||
        !array_key_exists('value', $item['metrics'][$metric_code])
    ) {
        return null;
    }

    return $item['metrics'][$metric_code]['value'];
}

/**
 * ETF listing shortcode.
 *
 * Examples:
 * [etf_engine_v2 market="TW"]
 * [etf_engine_v2 market="US"]
 * [etf_engine_v2 market="US" classification="theme:artificial_intelligence"]
 */
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
        list($dimension, $code) = array_map(
            'trim',
            explode(':', $classification, 2)
        );

        $items = array_values(
            array_filter(
                $items,
                function ($item) use ($dimension, $code) {
                    if (
                        !isset($item['classifications']) ||
                        !is_array($item['classifications'])
                    ) {
                        return false;
                    }

                    foreach ($item['classifications'] as $row) {
                        if (
                            isset($row['dimension'], $row['code']) &&
                            (string) $row['dimension'] === $dimension &&
                            (string) $row['code'] === $code
                        ) {
                            return true;
                        }
                    }

                    return false;
                }
            )
        );
    }

    $limit = max(1, min(500, absint($atts['limit'])));
    $items = array_slice($items, 0, $limit);

    $wrapper_id = 'etf_v2_' . wp_generate_uuid4();

    wp_enqueue_script(
        'chart-js',
        'https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js',
        array(),
        '4.4.7',
        true
    );

    ob_start();
    ?>
    <div
        id="<?php echo esc_attr($wrapper_id); ?>"
        class="etf-v2"
        data-items="<?php echo esc_attr(wp_json_encode($items)); ?>"
    >
        <div class="etf-v2-toolbar">
            <input
                class="etf-v2-search"
                type="search"
                placeholder="搜尋代碼或名稱"
            >

            <select class="etf-v2-metric">
                <option value="total_return_1y">一年報酬</option>
                <option value="sharpe_ratio">Sharpe</option>
                <option value="alpha">Alpha</option>
                <option value="beta">Beta</option>
                <option value="max_drawdown">最大回撤</option>
                <option value="expense_ratio">費用率</option>
            </select>
        </div>

        <?php if (empty($items)) : ?>
            <div class="etf-v2-notice">
                找不到 ETF 資料。請確認 GitHub JSON 網址及 GitHub Actions 是否已成功執行。
            </div>
        <?php else : ?>
            <div class="etf-v2-chart">
                <canvas></canvas>
            </div>

            <div class="etf-v2-grid"></div>
        <?php endif; ?>
    </div>

    <style>
        .etf-v2 {
            box-sizing: border-box;
            background: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 12px;
            padding: 18px;
        }

        .etf-v2 * {
            box-sizing: border-box;
        }

        .etf-v2-toolbar {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            margin-bottom: 14px;
        }

        .etf-v2-toolbar input,
        .etf-v2-toolbar select {
            min-height: 42px;
            padding: 9px 12px;
            border: 1px solid #cbd5e1;
            border-radius: 6px;
            background: #ffffff;
        }

        .etf-v2-search {
            flex: 1 1 240px;
        }

        .etf-v2-chart {
            position: relative;
            width: 100%;
            height: 420px;
        }

        .etf-v2-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
            gap: 10px;
            margin-top: 16px;
        }

        .etf-v2-card {
            min-width: 0;
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            padding: 12px;
            background: #ffffff;
        }

        .etf-v2-card-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 8px;
        }

        .etf-v2-code {
            font-weight: 700;
            color: #2563eb;
        }

        .etf-v2-value {
            font-weight: 700;
            text-align: right;
        }

        .etf-v2-name {
            margin-top: 6px;
            overflow-wrap: anywhere;
            color: #475569;
            font-size: 14px;
        }

        .etf-v2-notice {
            padding: 16px;
            border: 1px solid #fbbf24;
            border-radius: 8px;
            background: #fffbeb;
            color: #92400e;
        }

        @media (max-width: 600px) {
            .etf-v2-chart {
                height: 340px;
            }
        }
    </style>

    <?php if (!empty($items)) : ?>
        <script>
        (function () {
            const root = document.getElementById(
                <?php echo wp_json_encode($wrapper_id); ?>
            );

            if (!root) {
                return;
            }

            let all = [];

            try {
                all = JSON.parse(root.dataset.items || '[]');
            } catch (error) {
                console.error('ETF Engine v2 JSON parse error:', error);
                return;
            }

            const canvas = root.querySelector('canvas');
            const grid   = root.querySelector('.etf-v2-grid');
            const search = root.querySelector('.etf-v2-search');
            const select = root.querySelector('.etf-v2-metric');

            let chart = null;

            const metricLabels = {
                total_return_1y: '一年報酬',
                sharpe_ratio: 'Sharpe',
                alpha: 'Alpha',
                beta: 'Beta',
                max_drawdown: '最大回撤',
                expense_ratio: '費用率'
            };

            function escapeHtml(value) {
                return String(value ?? '')
                    .replaceAll('&', '&amp;')
                    .replaceAll('<', '&lt;')
                    .replaceAll('>', '&gt;')
                    .replaceAll('"', '&quot;')
                    .replaceAll("'", '&#039;');
            }

            function getMetricValue(item, metricCode) {
                const metric = item &&
                    item.metrics &&
                    item.metrics[metricCode];

                if (!metric || metric.value === null || metric.value === undefined) {
                    return null;
                }

                const number = Number(metric.value);

                return Number.isFinite(number) ? number : null;
            }

            function formatMetric(value, metricCode) {
                if (value === null) {
                    return 'N/A';
                }

                if (
                    metricCode === 'total_return_1y' ||
                    metricCode === 'alpha' ||
                    metricCode === 'max_drawdown' ||
                    metricCode === 'expense_ratio'
                ) {
                    return value.toFixed(2) + '%';
                }

                return value.toFixed(2);
            }

            function render() {
                const query      = search.value.trim().toLowerCase();
                const metricCode = select.value;

                let rows = all.filter(function (item) {
                    const ticker = String(item.ticker || '');
                    const name   = String(item.name || '');

                    return (ticker + ' ' + name)
                        .toLowerCase()
                        .includes(query);
                });

                rows.sort(function (a, b) {
                    const aValue = getMetricValue(a, metricCode);
                    const bValue = getMetricValue(b, metricCode);

                    if (aValue === null && bValue === null) {
                        return 0;
                    }

                    if (aValue === null) {
                        return 1;
                    }

                    if (bValue === null) {
                        return -1;
                    }

                    return bValue - aValue;
                });

                grid.innerHTML = rows.map(function (item) {
                    const ticker = escapeHtml(item.ticker || '');
                    const name   = escapeHtml(item.name || '');
                    const value  = getMetricValue(item, metricCode);

                    return (
                        '<div class="etf-v2-card">' +
                            '<div class="etf-v2-card-header">' +
                                '<span class="etf-v2-code">' + ticker + '</span>' +
                                '<span class="etf-v2-value">' +
                                    escapeHtml(formatMetric(value, metricCode)) +
                                '</span>' +
                            '</div>' +
                            '<div class="etf-v2-name">' + name + '</div>' +
                        '</div>'
                    );
                }).join('');

                if (chart) {
                    chart.destroy();
                }

                chart = new Chart(canvas, {
                    type: 'bar',
                    data: {
                        labels: rows.map(function (item) {
                            return item.ticker || '';
                        }),
                        datasets: [
                            {
                                label: metricLabels[metricCode] || metricCode,
                                data: rows.map(function (item) {
                                    return getMetricValue(item, metricCode);
                                })
                            }
                        ]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        parsing: false,
                        scales: {
                            x: {
                                ticks: {
                                    autoSkip: false,
                                    maxRotation: 60,
                                    minRotation: 0
                                }
                            }
                        },
                        plugins: {
                            tooltip: {
                                callbacks: {
                                    label: function (context) {
                                        return formatMetric(
                                            context.raw,
                                            metricCode
                                        );
                                    }
                                }
                            }
                        }
                    }
                });
            }

            search.addEventListener('input', render);
            select.addEventListener('change', render);

            function initializeChart() {
                if (typeof Chart === 'undefined') {
                    window.setTimeout(initializeChart, 150);
                    return;
                }

                render();
            }

            initializeChart();
        }());
        </script>
    <?php endif; ?>

    <?php
    return ob_get_clean();
}

add_shortcode('etf_engine_v2', 'etf_v2_shortcode');

/**
 * Register settings.
 */
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

/**
 * Add settings page.
 */
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

/**
 * Render settings page.
 */
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
                    <th scope="row">
                        <label for="etf_v2_base_url">
                            Public JSON base URL
                        </label>
                    </th>

                    <td>
                        <input
                            id="etf_v2_base_url"
                            class="regular-text"
                            type="url"
                            name="etf_v2_base_url"
                            value="<?php echo esc_attr(etf_v2_base_url()); ?>"
                        >

                        <p class="description">
                            例如：
                            https://raw.githubusercontent.com/huangtop/ETF-ENGINE-V2/main/data/public
                        </p>
                    </td>
                </tr>
            </table>

            <?php submit_button(); ?>
        </form>
    </div>
    <?php
}