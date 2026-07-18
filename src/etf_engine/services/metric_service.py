import numpy as np
import pandas as pd

TRADING_DAYS=252

def _series(frame:pd.DataFrame)->pd.Series:
    column='adj_close' if 'adj_close' in frame else 'close'
    return pd.to_numeric(frame[column],errors='coerce').dropna()

def calculate_metrics(etf_id:str,prices:pd.DataFrame,benchmark:pd.DataFrame,risk_free_rate:float=0.015)->list[dict]:
    p=_series(prices); b=_series(benchmark)
    if len(p)<20:return []
    one=p.iloc[-TRADING_DAYS:] if len(p)>TRADING_DAYS else p
    r=one.pct_change().dropna(); years=max(len(one)/TRADING_DAYS,1/TRADING_DAYS)
    total_return=float(one.iloc[-1]/one.iloc[0]-1)
    annual_return=float((one.iloc[-1]/one.iloc[0])**(1/years)-1) if years>=1 else total_return/years
    volatility=float(r.std()*np.sqrt(TRADING_DAYS))
    sharpe=(annual_return-risk_free_rate)/volatility if volatility else None
    drawdown=one/one.cummax()-1
    common=r.index.intersection(b.pct_change().dropna().index)
    alpha=beta=tracking_error=None
    if len(common)>=20:
        er=r.loc[common]; br=b.pct_change().dropna().loc[common]
        variance=float(br.var())
        beta=float(er.cov(br)/variance) if variance else None
        if beta is not None:
            alpha=float((er.mean()-beta*br.mean())*TRADING_DAYS)
        tracking_error=float((er-br).std()*np.sqrt(TRADING_DAYS))
    as_of=p.index[-1].date().isoformat()
    rows={
      'total_return_1y':(total_return*100,'percent'), 'annualized_return':(annual_return*100,'percent'),
      'annualized_volatility':(volatility*100,'percent'),'sharpe_ratio':(sharpe,'ratio'),
      'max_drawdown':(float(drawdown.min())*100,'percent'),'alpha':(alpha*100 if alpha is not None else None,'percent'),
      'beta':(beta,'ratio'),'tracking_error':(tracking_error*100 if tracking_error is not None else None,'percent'),
      'data_years':(len(p)/TRADING_DAYS,'years')}
    return [{'etf_id':etf_id,'metric_code':k,'value':round(v,4) if v is not None else None,'unit':u,'as_of':as_of,'period':'1y' if k!='data_years' else 'available','source':'calculated'} for k,(v,u) in rows.items()]
