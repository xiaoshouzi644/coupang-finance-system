import io
import json
import unicodedata
from pathlib import Path

import pandas as pd

ROOT = Path('/opt/shuju')
FILES = {
    'compensation': ROOT / '库存损失赔偿报告1月.xlsx',
    'storage': ROOT / 'N-1月仓储费.xlsx',
    'cost1': ROOT / '成本模板_(1).xlsx',
    'cost2': ROOT / '酷澎成本维护模板_(1).xlsx',
}


def clean_cols(df):
    cols = []
    seen = {}
    for col in df.columns:
        c = unicodedata.normalize('NFKC', str(col)).strip().replace('\n', '').replace('\r', '')
        if c in seen:
            seen[c] += 1
            c = f'{c}_{seen[c]}'
        else:
            seen[c] = 0
        cols.append(c)
    df = df.copy()
    df.columns = cols
    return df


def find_header_row_dynamic(file_bytes, is_csv=False, keywords=None):
    keywords = keywords or ['订单ID', 'SKU ID', '选项ID', '配送ID']
    try:
        df = pd.read_csv(io.BytesIO(file_bytes), nrows=80, header=None) if is_csv else pd.read_excel(io.BytesIO(file_bytes), nrows=80, header=None)
        for i, row in df.iterrows():
            row_str = [str(v) for v in row.values]
            if any(any(kw in s for kw in keywords) for s in row_str):
                return i
        return 0
    except Exception:
        return 0


def smart_read_with_multi_header(path, keywords=None):
    keywords = keywords or ['订单ID', 'SKU ID']
    file_bytes = path.read_bytes()
    is_csv = path.suffix.lower() == '.csv'
    h_idx = find_header_row_dynamic(file_bytes, is_csv, keywords)
    if is_csv:
        df = pd.read_csv(io.BytesIO(file_bytes), skiprows=h_idx)
    else:
        df_preview = pd.read_excel(io.BytesIO(file_bytes), skiprows=h_idx, nrows=2, header=None)
        h2_str = ''.join([str(x) for x in df_preview.iloc[1].values]) if len(df_preview) > 1 else ''
        if any(kw in h2_str for kw in ['金额', '费用', 'A-B', 'A-B-C']):
            df = pd.read_excel(io.BytesIO(file_bytes), header=[h_idx, h_idx + 1])
            df.columns = [
                f"{str(a).strip()}_{str(b).strip()}" if 'Unnamed' not in str(b) and str(a).strip() != str(b).strip() else str(a).strip()
                for a, b in df.columns
            ]
        else:
            df = pd.read_excel(io.BytesIO(file_bytes), skiprows=h_idx)
    return clean_cols(df)


def find_col_by_keywords(columns, keywords):
    cols = [unicodedata.normalize('NFKC', str(c)).strip().casefold() for c in columns]
    negative_hints = {
        '赔偿金额': ['是否适用'],
        '结算金额': ['结算周期'],
    }
    for kw in keywords:
        k = unicodedata.normalize('NFKC', str(kw)).strip().casefold()
        for i, c in enumerate(cols):
            if k in c:
                if kw in negative_hints and any(bad in c for bad in negative_hints[kw]):
                    continue
                return columns[i]
    return None


def is_numeric_series(series):
    sample = pd.to_numeric(series, errors='coerce')
    return float(sample.notna().mean())


summary = {'structure': {}, 'behavior': {}}

comp = smart_read_with_multi_header(FILES['compensation'], ['赔偿金额', '选项ID', '订单ID'])
comp_order_col = find_col_by_keywords(comp.columns, ['订单ID', '订单 ID'])
comp_sku_col = find_col_by_keywords(comp.columns, ['选项ID', 'SKU ID', '选项 ID'])
comp_fee_col = find_col_by_keywords(comp.columns, ['赔偿金额', '结算金额'])
summary['structure']['compensation'] = {
    'rows': int(len(comp)),
    'order_col': comp_order_col,
    'sku_col': comp_sku_col,
    'fee_col': comp_fee_col,
    'type_col': find_col_by_keywords(comp.columns, ['类型']),
    'damage_col': find_col_by_keywords(comp.columns, ['损坏/丢失']),
    'responsibility_col': find_col_by_keywords(comp.columns, ['退货责任方', '责任方']),
}
summary['behavior']['compensation'] = {
    'fee_numeric_ratio': is_numeric_series(comp[comp_fee_col]) if comp_fee_col else 0,
    'has_required_fields': bool(comp_order_col and comp_sku_col and comp_fee_col),
}

stor = smart_read_with_multi_header(FILES['storage'], ['SKU ID'])
stor_sku_col = find_col_by_keywords(stor.columns, ['SKU ID'])
stor_fee_col = find_col_by_keywords(stor.columns, ['最终费用(A-B-C)', '最终费用', '优惠后金额(A-B)', '产生金额(A)', '产生金额'])
stor_volume_col = find_col_by_keywords(stor.columns, ['单位产品体积', '体积'])
summary['structure']['storage'] = {
    'rows': int(len(stor)),
    'sku_col': stor_sku_col,
    'fee_col': stor_fee_col,
    'volume_col': stor_volume_col,
}
summary['behavior']['storage'] = {
    'fee_numeric_ratio': is_numeric_series(stor[stor_fee_col]) if stor_fee_col else 0,
    'volume_numeric_ratio': is_numeric_series(stor[stor_volume_col]) if stor_volume_col else 0,
    'has_required_fields': bool(stor_sku_col and stor_fee_col),
}

for key in ['cost1', 'cost2']:
    df = pd.read_excel(FILES[key])
    df = clean_cols(df)
    sku_col = find_col_by_keywords(df.columns, ['SKU ID'])
    purchase_col = find_col_by_keywords(df.columns, ['单件进价'])
    head_col = find_col_by_keywords(df.columns, ['单件头程'])
    volume_col = find_col_by_keywords(df.columns, ['单件体积'])
    summary['structure'][key] = {
        'rows': int(len(df)),
        'sku_col': sku_col,
        'purchase_col': purchase_col,
        'head_col': head_col,
        'volume_col': volume_col,
    }
    summary['behavior'][key] = {
        'purchase_numeric_ratio': is_numeric_series(df[purchase_col]) if purchase_col else 0,
        'head_numeric_ratio': is_numeric_series(df[head_col]) if head_col else 0,
        'volume_numeric_ratio': is_numeric_series(df[volume_col]) if volume_col else 0,
        'has_required_fields': bool(sku_col and purchase_col and head_col and volume_col),
    }

summary['verdict'] = {
    'all_required_fields_present': all(v.get('has_required_fields', False) for v in summary['behavior'].values()),
    'numeric_checks_passed': (
        summary['behavior']['compensation']['fee_numeric_ratio'] > 0.9 and
        summary['behavior']['storage']['fee_numeric_ratio'] > 0.9 and
        summary['behavior']['cost1']['purchase_numeric_ratio'] > 0.9 and
        summary['behavior']['cost2']['purchase_numeric_ratio'] > 0.9
    )
}

print(json.dumps(summary, ensure_ascii=False, indent=2))
