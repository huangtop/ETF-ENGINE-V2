#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from etf_engine.repository import SeedRepository

print('🔧 初始化...')
seed = SeedRepository()

print('\n📋 台灣 ETF:')
entities = seed.entities()
tw = [e for e in entities if e.listing_market == 'TW']
for e in tw[:5]:
    print(f'  {e.etf_id} - {e.name}')

print(f'\n✅ 總共 {len(tw)} 個台灣 ETF')
print(f'✅ 總共 {len([e for e in entities if e.listing_market == "US"])} 個美國 ETF')
