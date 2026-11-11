"""Make the $1,000 test file and predict its effects from the RAW files (not via analytics.py)."""
import pandas as pd
from pathlib import Path

src = Path('data/Sales.txt').read_bytes()
old = b'"S0120270601",6/30/2027 0:00:00,"SH01","SH01_27","C1","P01",260.00'
new = b'"S0120270601",6/30/2027 0:00:00,"SH01","SH01_27","C1","P01",1260.00'
assert src.count(old) == 1
Path('validation/Sales_plus1000.txt').write_bytes(src.replace(old, new))

stores = pd.read_csv('data/Support_EX_B_Stores_1.csv', sep='\t', dtype=str)
def summary(path):
    s = pd.read_csv(path, dtype={'Revenue': float})
    s['Date'] = pd.to_datetime(s['Date'], format='%m/%d/%Y %H:%M:%S')
    s = s.merge(stores[['ID', 'StoreType']], left_on='Store ID', right_on='ID')
    y, m = s['Date'].dt.year, s['Date'].dt.month
    return {
        'Total revenue': s.Revenue.sum(),
        'Year 2027': s.Revenue[y == 2027].sum(),
        'Year 2026 (should not change)': s.Revenue[y == 2026].sum(),
        'Month June 2027, all channels': s.Revenue[(y == 2027) & (m == 6)].sum(),
        'Month June 2027, Brick & Mortar': s.Revenue[(y == 2027) & (m == 6) & (s.StoreType == 'Brick & Mortar')].sum(),
        'Month May 2027 (should not change)': s.Revenue[(y == 2027) & (m == 5)].sum(),
        'Channel Brick & Mortar': s.Revenue[s.StoreType == 'Brick & Mortar'].sum(),
        'Channel Website (should not change)': s.Revenue[s.StoreType == 'Website'].sum(),
        'Store SH01 Orlando': s.Revenue[s['Store ID'] == 'SH01'].sum(),
        'Store SH08 Orlando (should not change)': s.Revenue[s['Store ID'] == 'SH08'].sum(),
        'Category Beans (C1)': s.Revenue[s['Category ID'] == 'C1'].sum(),
        'Category Syrups (C2) (should not change)': s.Revenue[s['Category ID'] == 'C2'].sum(),
        'Filter 2027 + SH01 + Beans + Brick & Mortar': s.Revenue[(y == 2027) & (s['Store ID'] == 'SH01') & (s['Category ID'] == 'C1')].sum(),
        'Filter 2027 + Website': s.Revenue[(y == 2027) & (s.StoreType == 'Website')].sum(),
    }
a, b = summary('data/Sales.txt'), summary('validation/Sales_plus1000.txt')
print('| Measure | Before | Predicted after | Change |'); print('|---|---|---|---|')
for k in a: print(f'| {k} | ${a[k]:,.2f} | ${b[k]:,.2f} | {b[k]-a[k]:+,.2f} |')
