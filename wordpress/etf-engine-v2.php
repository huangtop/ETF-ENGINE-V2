<?php
/**
 * Plugin Name: ETF Engine v2
 * Description: Read ETF Engine v2 public JSON with WordPress transient caching.
 * Version: 2.0.0
 */
if (!defined('ABSPATH')) exit;

function etf_v2_base_url() {
    return rtrim((string)get_option('etf_v2_base_url', 'https://raw.githubusercontent.com/huangtop/ETF-Engine-v2/main/data/public'), '/');
}
function etf_v2_fetch_json($path) {
    $key='etf_v2_'.md5($path); $cached=get_transient($key);
    if ($cached!==false) return $cached;
    $response=wp_remote_get(etf_v2_base_url().'/'.ltrim($path,'/'), array('timeout'=>15));
    if (is_wp_error($response) || wp_remote_retrieve_response_code($response)!==200) return array();
    $data=json_decode(wp_remote_retrieve_body($response), true);
    if (!is_array($data)) return array();
    set_transient($key,$data,HOUR_IN_SECONDS); return $data;
}
function etf_v2_shortcode($atts) {
    $a=shortcode_atts(array('market'=>'TW','classification'=>'','limit'=>'100'),$atts);
    $market=strtoupper(sanitize_text_field($a['market']));
    if (!in_array($market,array('TW','US'),true)) $market='TW';
    $items=etf_v2_fetch_json('markets/'.$market.'.json');
    $filter=sanitize_text_field($a['classification']);
    if ($filter && strpos($filter,':')!==false) {
        list($dimension,$code)=array_map('trim',explode(':',$filter,2));
        $items=array_values(array_filter($items,function($item) use($dimension,$code){
            foreach(($item['classifications']??array()) as $row) if(($row['dimension']??'')===$dimension && ($row['code']??'')===$code) return true;
            return false;
        }));
    }
    $items=array_slice($items,0,max(1,intval($a['limit'])));
    $id='etf_v2_'.wp_generate_uuid4();
    wp_enqueue_script('chart-js','https://cdn.jsdelivr.net/npm/chart.js',array(),null,true);
    ob_start(); ?>
    <div id="<?php echo esc_attr($id); ?>" class="etf-v2" data-items="<?php echo esc_attr(wp_json_encode($items)); ?>">
      <div class="etf-v2-toolbar"><input class="etf-v2-search" type="search" placeholder="搜尋代碼或名稱"><select class="etf-v2-metric"><option value="total_return_1y">一年報酬</option><option value="sharpe_ratio">Sharpe</option><option value="alpha">Alpha</option><option value="beta">Beta</option><option value="max_drawdown">最大回撤</option><option value="expense_ratio">費用率</option></select></div>
      <div style="height:420px"><canvas></canvas></div><div class="etf-v2-grid"></div>
    </div>
    <style>.etf-v2{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:18px}.etf-v2-toolbar{display:flex;gap:10px;margin-bottom:14px}.etf-v2-toolbar input,.etf-v2-toolbar select{padding:9px;border:1px solid #cbd5e1;border-radius:6px}.etf-v2-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:10px;margin-top:16px}.etf-v2-card{border:1px solid #e2e8f0;border-radius:8px;padding:12px}.etf-v2-code{font-weight:700;color:#2563eb}.etf-v2-value{float:right;font-weight:700}</style>
    <script>(function(){const root=document.getElementById(<?php echo wp_json_encode($id); ?>);if(!root)return;const all=JSON.parse(root.dataset.items||'[]'),canvas=root.querySelector('canvas'),grid=root.querySelector('.etf-v2-grid'),search=root.querySelector('.etf-v2-search'),select=root.querySelector('.etf-v2-metric');let chart=null;const value=(x,k)=>x.metrics&&x.metrics[k]&&x.metrics[k].value!=null?Number(x.metrics[k].value):null;function render(){const q=search.value.trim().toLowerCase(),k=select.value;let rows=all.filter(x=>(x.ticker+' '+x.name).toLowerCase().includes(q));rows.sort((a,b)=>(value(b,k)??-Infinity)-(value(a,k)??-Infinity));grid.innerHTML=rows.map(x=>'<div class="etf-v2-card"><span class="etf-v2-code">'+x.ticker+'</span><span class="etf-v2-value">'+(value(x,k)??'N/A')+'</span><div>'+x.name+'</div></div>').join('');if(chart)chart.destroy();chart=new Chart(canvas,{type:'bar',data:{labels:rows.map(x=>x.ticker),datasets:[{label:k,data:rows.map(x=>value(x,k)??0)}]},options:{responsive:true,maintainAspectRatio:false}})}search.addEventListener('input',render);select.addEventListener('change',render);function start(){if(typeof Chart==='undefined')return setTimeout(start,150);render()}start()})();</script>
    <?php return ob_get_clean();
}
add_shortcode('etf_engine_v2','etf_v2_shortcode');
function etf_v2_settings(){register_setting('etf_v2','etf_v2_base_url');add_options_page('ETF Engine v2','ETF Engine v2','manage_options','etf-v2',function(){?><div class="wrap"><h1>ETF Engine v2</h1><form method="post" action="options.php"><?php settings_fields('etf_v2');?><table class="form-table"><tr><th>Public JSON base URL</th><td><input class="regular-text" name="etf_v2_base_url" value="<?php echo esc_attr(etf_v2_base_url()); ?>"></td></tr></table><?php submit_button();?></form></div><?php;});}
add_action('admin_menu','etf_v2_settings'); add_action('admin_init','etf_v2_settings');
