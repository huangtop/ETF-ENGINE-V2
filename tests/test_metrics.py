import pandas as pd
from etf_engine.services.metric_service import calculate_metrics

def test_metrics_smoke():
    idx=pd.date_range('2024-01-01',periods=260,freq='B')
    etf=pd.DataFrame({'adj_close':[100+i*0.1 for i in range(260)]},index=idx)
    benchmark=pd.DataFrame({'adj_close':[100+i*0.08 for i in range(260)]},index=idx)
    rows=calculate_metrics('US-TEST',etf,benchmark)
    codes={x['metric_code'] for x in rows}
    assert {'total_return_1y','sharpe_ratio','beta','max_drawdown'} <= codes
