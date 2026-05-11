import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import io
import re
import unicodedata
import traceback
from datetime import datetime

APP_VERSION = "V101 损益表精简版"
APP_UPDATED_AT = "2026-04-30 16:30"
APP_TITLE = f"酷澎财务核算 Pro ({APP_VERSION})"
APP_SUBTITLE = "第一要务：数据准确｜统一经营利润 vs 结算利润双口径，严禁混用营收与打款逻辑"

# --- 1. 页面配置与环境初始化 ---
st.set_page_config(page_title=APP_TITLE, layout="wide")
plt.rcParams['font.sans-serif'] = [
    'Noto Sans CJK SC', 'Noto Sans CJK TC', 'Noto Sans CJK JP',
    'Microsoft YaHei', 'SimHei', 'WenQuanYi Zen Hei', 'Arial Unicode MS'
]
plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['axes.unicode_minus'] = False


# --- 2. 工业级工具函数 (100% 还原自 V86，仅增强底层清洗和提速) ---
def clean_df_columns(df):
    """清理列名，确保列名绝对唯一且重置物理索引"""
    if df is None:
        return None
    df = df.copy()
    new_cols = []
    counts = {}
    for col in df.columns:
        c_str = str(col).strip().replace('\n', '').replace('\r', '')
        c_str = unicodedata.normalize('NFKC', c_str)
        if c_str in counts:
            counts[c_str] += 1
            new_cols.append(f"{c_str}_{counts[c_str]}")
        else:
            counts[c_str] = 0
            new_cols.append(c_str)
    df.columns = new_cols
    return df.reset_index(drop=True)


def force_numeric_col(series):
    """财务级数值解析器：极速向量化重写，彻底解决循环卡死"""
    if not isinstance(series, pd.Series):
        return pd.Series(0.0)
    s = series.astype(str).str.strip().str.upper()
    is_neg = (s.str.startswith('(') & s.str.endswith(')')) | s.str.startswith('-')
    s = s.str.replace(r'[^0-9.]', '', regex=True)
    num = pd.to_numeric(s, errors='coerce').fillna(0.0)
    res = np.where(is_neg, -num, num)
    return pd.Series(res, index=series.index)


def smart_format_id(series):
    """极致 ID 归一化：极速向量化重写，秒级处理万行数据"""
    if not isinstance(series, pd.Series):
        val = series
        if pd.isna(val):
            return ""
        if isinstance(val, (float, int)):
            if isinstance(val, float) and (np.isnan(val) or np.isinf(val)):
                return ""
            s_val = f"{val:.0f}"
        else:
            s_val = unicodedata.normalize('NFKC', str(val)).strip()
        if s_val.lower() in ['nan', 'none', 'null', '']:
            return ""
        if s_val.endswith('.0'):
            s_val = s_val[:-2]
        if 'e' in s_val.lower() or '+' in s_val:
            try:
                s_val = "{:.0f}".format(float(s_val))
            except Exception:
                pass
        s_val = re.sub(r'[^A-Za-z0-9]', '', s_val)
        return s_val

    s = series.astype(str).str.strip()
    s = s.str.replace(r'\.0$', '', regex=True)
    s = s.apply(lambda x: unicodedata.normalize('NFKC', x) if isinstance(x, str) else x)
    s = s.str.replace(r'[^A-Za-z0-9]', '', regex=True)
    invalid_mask = s.str.lower().isin(['nan', 'none', 'null', ''])
    return s.mask(invalid_mask, "")


def find_header_row_dynamic(file_bytes, is_csv=False, keywords=['订单ID', 'SKU ID', '选项ID', '配送ID']):
    """动态扫描定位起始点"""
    try:
        if is_csv:
            for enc in ['utf-8-sig', 'gb18030', 'gbk', 'cp949', 'utf-8']:
                try:
                    df = pd.read_csv(io.BytesIO(file_bytes), nrows=80, header=None, encoding=enc)
                    break
                except Exception:
                    continue
        else:
            df = pd.read_excel(io.BytesIO(file_bytes), nrows=80, header=None)
        for i, row in df.iterrows():
            row_str = [str(v) for v in row.values]
            if any(any(kw in s for kw in keywords) for s in row_str):
                return i
        return 0
    except Exception:
        return 0


def smart_read_with_multi_header(file, keywords=['订单ID', 'SKU ID']):
    """深度解析引擎：支持双层表头及物理偏移纠正"""
    file_bytes = file.getvalue()
    is_csv = file.name.lower().endswith('.csv')
    h_idx = find_header_row_dynamic(file_bytes, is_csv, keywords)

    try:
        if is_csv:
            for enc in ['utf-8-sig', 'gb18030', 'gbk', 'cp949', 'utf-8']:
                try:
                    df_test = pd.read_csv(io.BytesIO(file_bytes), encoding=enc, skiprows=h_idx, nrows=2, header=None)
                    h2_str = "".join([str(x) for x in df_test.iloc[1].values])
                    if any(kw in h2_str for kw in ['金额', '费用', 'A-B', 'A-B-C']):
                        col_names = []
                        for c in range(df_test.shape[1]):
                            h1, h2 = str(df_test.iloc[0, c]), str(df_test.iloc[1, c])
                            name = f"{h1}_{h2}" if h1 != h2 and "nan" not in h2.lower() else h1
                            col_names.append(name.strip())
                        df = pd.read_csv(io.BytesIO(file_bytes), encoding=enc, skiprows=h_idx + 2, header=None)
                        df.columns = col_names[:df.shape[1]]
                    else:
                        df = pd.read_csv(io.BytesIO(file_bytes), encoding=enc, skiprows=h_idx)
                    break
                except Exception:
                    continue
        else:
            df_preview = pd.read_excel(io.BytesIO(file_bytes), skiprows=h_idx, nrows=2, header=None)
            h2_str = "".join([str(x) for x in df_preview.iloc[1].values])
            if any(kw in h2_str for kw in ['金额', '费用', 'A-B', 'A-B-C']):
                df = pd.read_excel(io.BytesIO(file_bytes), header=[h_idx, h_idx + 1])
                df.columns = [
                    f"{str(a).strip()}_{str(b).strip()}" if 'Unnamed' not in str(b) and str(a).strip() != str(b).strip()
                    else str(a).strip() for a, b in df.columns
                ]
            else:
                df = pd.read_excel(io.BytesIO(file_bytes), skiprows=h_idx)

        if df.columns.str.contains('Unnamed').all() or df.shape[1] < 2:
            potential_header = df.iloc[0]
            if any(kw in str(potential_header).casefold() for kw in keywords):
                df.columns = [str(x) for x in potential_header]
                df = df.iloc[1:].reset_index(drop=True)

        return clean_df_columns(df)
    except Exception as e:
        st.error(f"解析 {file.name} 失败: {e}")
        return None


def find_col_by_keywords(columns, keywords):
    """加入NFKC无视半全角差异，彻底匹配"""
    cols_list = [unicodedata.normalize('NFKC', str(c)).strip().casefold() for c in columns]
    negative_hints = {
        '赔偿金额': ['是否适用'],
        '结算金额': ['结算周期'],
    }
    for kw in keywords:
        kw_fold = unicodedata.normalize('NFKC', str(kw)).strip().casefold()
        for i, c in enumerate(cols_list):
            if kw_fold in c:
                if kw in negative_hints and any(bad in c for bad in negative_hints[kw]):
                    continue
                return columns[i]
    return None


def find_all_cols_by_keywords(columns, keywords):
    cols_list = [unicodedata.normalize('NFKC', str(c)).strip().casefold() for c in columns]
    matches = []
    for i, c in enumerate(cols_list):
        if any(unicodedata.normalize('NFKC', str(kw)).strip().casefold() in c for kw in keywords):
            matches.append(columns[i])
    return matches


def build_health_issue(module, level, message):
    return {"模块": module, "级别": level, "问题": message}


def normalize_cost_template(df):
    """兼容 /opt 下两版成本模板的列名差异，避免导入后成本字段失效。"""
    if df is None or len(df) == 0:
        return df
    df = clean_df_columns(df)
    rename_map = {}
    for col in df.columns:
        norm = unicodedata.normalize('NFKC', str(col)).strip().replace(' ', '')
        if norm in ['SKU标识']:
            rename_map[col] = 'SKU 标识'
        elif norm in ['本月销量', '实发总量']:
            rename_map[col] = '实发总量'
        elif norm in ['单件进价(RMB)', '单件进价（RMB）', '单件进价']:
            rename_map[col] = '单件进价 (RMB)'
        elif norm in ['单件头程(RMB)', '单件头程（RMB）', '单件头程']:
            rename_map[col] = '单件头程 (RMB)'
        elif norm in ['单件体积']:
            rename_map[col] = '单件体积'
    df = df.rename(columns=rename_map)
    return df


def summarize_trade_types(series):
    vals = []
    for x in series:
        s = str(x).strip()
        if s and s.lower() not in ['nan', 'none', 'null']:
            vals.append(s)
    uniq = []
    for v in vals:
        if v not in uniq:
            uniq.append(v)
    if not uniq:
        return '未知'
    priority_keywords = ['退款', '退货', '取消', '换货', '拒收', '正常', '销售', '购买']
    for kw in priority_keywords:
        matched = [v for v in uniq if kw in v]
        if matched:
            return ' | '.join(matched)
    return ' | '.join(uniq)


def render_health_report(issues, confidence, confidence_reason, stats):
    st.divider()
    st.subheader("🩺 数据健康检查")
    c1, c2, c3 = st.columns(3)
    c1.metric("可信度", confidence)
    c2.metric("高风险问题数", sum(1 for x in issues if x['级别'] == '高'))
    c3.metric("总提示数", len(issues))
    st.caption(confidence_reason)

    if stats:
        stat_df = pd.DataFrame(stats)
        st.dataframe(stat_df, use_container_width=True, hide_index=True)

    if issues:
        issue_df = pd.DataFrame(issues)
        st.dataframe(issue_df, use_container_width=True, hide_index=True)
        high_count = sum(1 for x in issues if x['级别'] == '高')
        if high_count > 0:
            st.error("存在高风险数据问题：建议优先修正后再看最终利润。")
        else:
            st.warning("存在中低风险提示：结果可参考，但请留意缺失映射与成本覆盖情况。")
    else:
        st.success("当前上传数据未发现明显结构性异常，可以进入核算。")


# ==========================================
# UI 界面开始
# ==========================================
st.title(f"💎 {APP_TITLE}")
st.caption(APP_SUBTITLE)
st.caption(f"版本更新时间：{APP_UPDATED_AT}")

with st.sidebar:
    st.header("⚙️ 财务参数")
    ex_rate_input = st.number_input("1000 韩元 = ? 人民币", value=5.3, step=0.1)
    ex_rate = ex_rate_input / 1000

    st.divider()
    st.header("🧾 赔偿口径")
    compensation_mode = st.radio(
        "赔偿金额字段解释方式",
        ["赔偿金额为整行总额", "赔偿金额为单件金额"],
        help="如果赔偿报表里的赔偿金额已经是整行总赔偿额，就不要再乘数量；如果是单件赔偿额，再按数量放大。"
    )

    st.divider()
    st.header("📢 广告费成本")
    ads_krw = st.number_input("广告费总计 (KRW)", value=0.0)
    ads_patch_cny = ads_krw * ex_rate
    st.write(f"💵 广告费换算：¥ {ads_patch_cny:,.2f}")
    st.caption("说明：广告费不计入“自然净利润”，只计入“全口径净利润”。")

    st.markdown("---")
    st.subheader("📊 增值税核算")
    st.caption("**规则：** 增值税 = 营业额 - 营业额 / 1.1")
    vat_turnover_krw = st.number_input("增值税计费营业额 (KRW)", value=0.0)
    vat_krw = vat_turnover_krw - (vat_turnover_krw / 1.1)
    vat_patch_cny = vat_krw * ex_rate
    st.write(f"➡️ 增值税换算：¥ {vat_patch_cny:,.2f}")
    st.markdown("---")

    other_rmb = st.number_input("3. 其它杂项支出 (RMB)", value=0.0)
    natural_patch_cny = other_rmb + vat_patch_cny
    total_patch_cny = ads_patch_cny + natural_patch_cny

    st.divider()
    st.header("📏 审计分摊逻辑")
    allocation_mode = st.radio(
        "物流费分摊方式",
        ["按体积权重分摊 (V86)", "按订单项平均分摊 (V90)"],
        help="体积权重：按产品体积占比分配费用；平均分摊：按同一订单内SKU行数平均分配。"
    )

    st.divider()
    st.header("📂 报表上传")
    f_sales = st.file_uploader("1. 销售手续费报告", type=["xlsx", "xls", "csv"], key="upload_sales")
    f_logi = st.file_uploader("2. 物流总表", type=["xlsx", "xls"], key="upload_logi")
    f_stor = st.file_uploader("3. 仓储费明细表", type=["xlsx", "xls", "csv"], key="upload_stor")
    f_comp = st.file_uploader("4. 库存损失赔偿报告", type=["xlsx", "xls", "csv"], key="upload_comp")
    
    # 存储到 session_state 以保持上传状态
    if f_sales:
        st.session_state['f_sales'] = f_sales
    if f_logi:
        st.session_state['f_logi'] = f_logi
    if f_stor:
        st.session_state['f_stor'] = f_stor
    if f_comp:
        st.session_state['f_comp'] = f_comp
    
    # 从 session_state 读取，保证按钮点击后不丢失
    f_sales = st.session_state.get('f_sales', f_sales)
    f_logi = st.session_state.get('f_logi', f_logi)
    f_stor = st.session_state.get('f_stor', f_stor)
    f_comp = st.session_state.get('f_comp', f_comp)

if f_sales and f_logi and f_stor:
    try:
        health_issues = []
        health_stats = []
        with st.status("建立多维审计路由系统...", expanded=False) as status:
            df_s_raw = smart_read_with_multi_header(f_sales, keywords=['订单ID', 'SKU ID'])
            if df_s_raw is None or df_s_raw.empty:
                raise ValueError("销售手续费报告未成功解析，请检查文件格式")

            oid_s_c = find_col_by_keywords(df_s_raw.columns, ['订单ID', 'Order ID'])
            sid_s_c = find_col_by_keywords(df_s_raw.columns, ['选项 ID', '选项ID', 'SKU ID'])
            skuid_s_c = find_col_by_keywords(df_s_raw.columns, ['SKU ID'])  # BUG1修复：专门定位SKU ID列，用于仓储费关联
            did_s_c = find_col_by_keywords(df_s_raw.columns, ['配送ID', 'Delivery ID']) or oid_s_c
            date_s_c = find_col_by_keywords(df_s_raw.columns, ['费用产生日期', '日期', '付款完成日期'])

            price_c = find_col_by_keywords(df_s_raw.columns, ['售价(A)', 'Unit Price'])
            qty_sales_c = find_col_by_keywords(df_s_raw.columns, ['销售数量(B)'])
            rev_c = find_col_by_keywords(df_s_raw.columns, ['成交额(A*B-C)'])
            settlement_c = find_col_by_keywords(df_s_raw.columns, ['结算金额'])
            gross_sales_c = find_col_by_keywords(df_s_raw.columns, ['销售额(A*B)', '销售额'])
            comm_f_c = find_col_by_keywords(df_s_raw.columns, ['销售手续费'])
            comm_vat_c = find_col_by_keywords(df_s_raw.columns, ['手续费（含增值税）', '手续费增值税'])

            required_sales_cols = {
                '订单ID': oid_s_c,
                'SKU ID': sid_s_c,
                '数量': qty_sales_c,
                '成交额': rev_c,
                '结算金额': settlement_c,
                '售价': price_c,
            }
            missing_sales_cols = [k for k, v in required_sales_cols.items() if not v]
            if missing_sales_cols:
                raise ValueError(f"销售报表关键字段缺失：{', '.join(missing_sales_cols)}")
            optional_sales_missing = [k for k, v in {'配送ID': did_s_c, '销售手续费': comm_f_c, '手续费增值税': comm_vat_c, '日期': date_s_c}.items() if not v]
            for col in optional_sales_missing:
                health_issues.append(build_health_issue('销售报表', '中', f'未识别到字段：{col}'))
            health_stats.append({'模块': '销售报表', '指标': '原始记录数', '值': len(df_s_raw)})

            df_s_raw['订单ID_CLEAN'] = smart_format_id(df_s_raw[oid_s_c])
            df_s_raw['ID_CLEAN'] = smart_format_id(df_s_raw[sid_s_c])
            df_s_raw['SKUID_CLEAN'] = smart_format_id(df_s_raw[skuid_s_c]) if skuid_s_c else df_s_raw['ID_CLEAN']  # BUG1修复：保留SKU ID用于仓储关联
            df_s_raw['DID_CLEAN'] = smart_format_id(df_s_raw[did_s_c])
            df_s_raw['TEMP_QTY'] = force_numeric_col(df_s_raw[qty_sales_c])
            df_s_raw['TEMP_QTY_POS'] = df_s_raw['TEMP_QTY'].clip(lower=0)
            df_s_raw['NUM_REV'] = force_numeric_col(df_s_raw[rev_c]) if rev_c else 0.0
            df_s_raw['NUM_SETTLEMENT'] = force_numeric_col(df_s_raw[settlement_c]) if settlement_c else 0.0
            df_s_raw['NUM_GROSS_SALES'] = force_numeric_col(df_s_raw[gross_sales_c]) if gross_sales_c else 0.0
            df_s_raw['NUM_COMM_F'] = force_numeric_col(df_s_raw[comm_f_c]) if comm_f_c else 0.0
            df_s_raw['NUM_COMM_VAT'] = force_numeric_col(df_s_raw[comm_vat_c]) if comm_vat_c else 0.0

            agg_dict = {
                price_c: 'first',
                'TEMP_QTY': 'sum',
                'TEMP_QTY_POS': 'sum',
                'NUM_REV': 'sum',
                'NUM_SETTLEMENT': 'sum',
                'NUM_GROSS_SALES': 'sum',
                'NUM_COMM_F': 'sum',
                'NUM_COMM_VAT': 'sum',
                '注册商品名称': 'first',
                '选项名': 'first',
                '交易类型': summarize_trade_types,
                'SKUID_CLEAN': 'first',  # BUG1修复：带入SKU ID
            }
            df_s_agg = df_s_raw.groupby(['订单ID_CLEAN', 'ID_CLEAN']).agg(agg_dict).reset_index()
            df_s_agg.columns = [
                '订单ID_CLEAN', 'ID_CLEAN', '售价(A)', 'NET_QTY', 'GROSS_QTY',
                'NET_REV', 'NET_SETTLEMENT', 'GROSS_SALES', 'NET_COMM', 'NET_COMM_VAT', '注册商品名称', '选项名', '交易类型', 'SKUID_CLEAN'
            ]

            status_map = df_s_agg.set_index('订单ID_CLEAN')['交易类型'].to_dict()
            date_map = df_s_raw.drop_duplicates('订单ID_CLEAN').set_index('订单ID_CLEAN')[date_s_c].to_dict() if date_s_c else {}
            if '交易类型' in df_s_raw.columns:
                mixed_status_orders = df_s_raw.groupby('订单ID_CLEAN')['交易类型'].nunique()
                mixed_status_count = int((mixed_status_orders > 1).sum())
                health_stats.append({'模块': '销售报表', '指标': '多交易类型订单数', '值': mixed_status_count})
                if mixed_status_count > 0:
                    health_issues.append(build_health_issue('销售报表', '中', f'存在 {mixed_status_count} 个订单含多种交易类型，当前版本已按优先级聚合而非取最后一条'))

            df_logi_w = smart_read_with_multi_header(f_logi, keywords=['订单ID', '配送ID'])
            if df_logi_w is None or df_logi_w.empty:
                raise ValueError('物流总表未成功解析，请检查文件格式')
            rb_l = f_logi.getvalue()
            h_idx_d = find_header_row_dynamic(rb_l, keywords=['配送ID'])
            try:
                df_logi_d = pd.read_excel(io.BytesIO(rb_l), sheet_name=1, skiprows=h_idx_d)
                if any(kw in "".join([str(x) for x in df_logi_d.iloc[0].values]) for kw in ['金额', '费用']):
                    df_logi_d = pd.read_excel(io.BytesIO(rb_l), sheet_name=1, header=[h_idx_d, h_idx_d + 1])
                    df_logi_d.columns = [
                        f"{str(a).strip()}_{str(b).strip()}" if 'Unnamed' not in str(b) and str(a).strip() != str(b).strip()
                        else str(a).strip() for a, b in df_logi_d.columns
                    ]
                    df_logi_d = clean_df_columns(df_logi_d)
            except Exception:
                df_logi_d = pd.DataFrame()

            df_c_raw = smart_read_with_multi_header(f_comp, keywords=['赔偿金额', '选项ID', '订单ID']) if f_comp else pd.DataFrame()

            map_data = [pd.DataFrame({'OID': df_s_raw['订单ID_CLEAN'], 'DID': df_s_raw['DID_CLEAN']})]
            w_did_col = find_col_by_keywords(df_logi_w.columns, ['配送ID', 'Delivery ID'])
            w_oid_col = find_col_by_keywords(df_logi_w.columns, ['订单ID', 'Order ID'])
            if w_did_col and w_oid_col:
                map_data.append(pd.DataFrame({'OID': smart_format_id(df_logi_w[w_oid_col]), 'DID': smart_format_id(df_logi_w[w_did_col])}))
            else:
                health_issues.append(build_health_issue('物流报表', '高', '第一页未完整识别订单ID/配送ID，物流映射准确性会下降'))

            d_did_col = find_col_by_keywords(df_logi_d.columns, ['配送ID', 'Delivery ID']) if not df_logi_d.empty else None
            d_oid_col = find_col_by_keywords(df_logi_d.columns, ['订单ID', 'Order ID']) if not df_logi_d.empty else None
            if d_did_col and d_oid_col:
                map_data.append(pd.DataFrame({'OID': smart_format_id(df_logi_d[d_oid_col]), 'DID': smart_format_id(df_logi_d[d_did_col])}))
            elif not df_logi_d.empty:
                health_issues.append(build_health_issue('物流报表', '中', '第二页存在但未完整识别订单ID/配送ID，配送费可能漏归属'))

            df_route = pd.concat(map_data, ignore_index=True)
            df_route = df_route[(df_route['DID'] != "") & (df_route['OID'] != "")].drop_duplicates(subset=['DID'], keep='last')
            did_to_oid = df_route.set_index('DID')['OID'].to_dict()
            health_stats.append({'模块': '物流报表', '指标': 'DID→OID 映射数', '值': len(did_to_oid)})

            kw_fees_priority = ['最终费用(A-B-C)', '最终费用', '优惠后金额(A-B)', '产生的金额', '产生金额', '优惠后金额', '金额', '操作费', '配送费']
            df_logi_w['DID_C'] = smart_format_id(df_logi_w[w_did_col] if w_did_col else df_logi_w[w_oid_col])
            fallback_w = smart_format_id(df_logi_w[w_oid_col]) if w_oid_col else pd.Series("", index=df_logi_w.index)
            df_logi_w['OID_MAPPED'] = df_logi_w['DID_C'].map(did_to_oid)
            df_logi_w['OID_FINAL'] = df_logi_w['OID_MAPPED'].fillna(fallback_w).fillna("")
            w_unmapped = int(((df_logi_w['DID_C'] != "") & df_logi_w['OID_MAPPED'].isna() & (fallback_w == "")).sum())
            health_stats.append({'模块': '物流报表', '指标': '第一页未映射记录数', '值': w_unmapped})
            if w_unmapped > 0:
                health_issues.append(build_health_issue('物流报表', '高', f'第一页有 {w_unmapped} 条物流记录未能归属到订单'))
            w_f_col = find_col_by_keywords(df_logi_w.columns, kw_fees_priority)
            df_logi_w['NUM_FEE'] = force_numeric_col(df_logi_w[w_f_col]) if w_f_col else 0.0
            df_w_agg = df_logi_w[(df_logi_w['OID_FINAL'] != "") & (df_logi_w['NUM_FEE'] != 0)].groupby('OID_FINAL')['NUM_FEE'].sum().reset_index()
            df_w_agg.columns = ['订单ID_CLEAN', '操作费_KRW']

            if not df_logi_d.empty:
                df_logi_d['DID_C'] = smart_format_id(df_logi_d[d_did_col] if d_did_col else df_logi_d[d_oid_col])
                fallback_d = smart_format_id(df_logi_d[d_oid_col]) if d_oid_col else pd.Series("", index=df_logi_d.index)
                df_logi_d['OID_MAPPED'] = df_logi_d['DID_C'].map(did_to_oid)
                df_logi_d['OID_FINAL'] = df_logi_d['OID_MAPPED'].fillna(fallback_d).fillna("")
                d_unmapped = int(((df_logi_d['DID_C'] != "") & df_logi_d['OID_MAPPED'].isna() & (fallback_d == "")).sum())
                health_stats.append({'模块': '物流报表', '指标': '第二页未映射记录数', '值': d_unmapped})
                if d_unmapped > 0:
                    health_issues.append(build_health_issue('物流报表', '中', f'第二页有 {d_unmapped} 条配送记录未能归属到订单'))
                d_f_col = find_col_by_keywords(df_logi_d.columns, kw_fees_priority)
                df_logi_d['NUM_FEE'] = force_numeric_col(df_logi_d[d_f_col]) if d_f_col else 0.0
                df_d_agg = df_logi_d[(df_logi_d['OID_FINAL'] != "") & (df_logi_d['NUM_FEE'] != 0)].groupby('OID_FINAL')['NUM_FEE'].sum().reset_index()
                df_d_agg.columns = ['订单ID_CLEAN', '配送费_KRW']
            else:
                df_d_agg = pd.DataFrame(columns=['订单ID_CLEAN', '配送费_KRW'])

            df_comp_logi = pd.DataFrame(columns=['订单ID_CLEAN', '操作费_C_KRW', '配送费_C_KRW'])
            compensation_audit_preview = pd.DataFrame()
            if not df_c_raw.empty:
                c_oid_col = find_col_by_keywords(df_c_raw.columns, ['订单ID', 'Order ID'])
                c_w_fee = find_col_by_keywords(df_c_raw.columns, ['仓库操作费', '操作费'])
                c_d_fee = find_col_by_keywords(df_c_raw.columns, ['配送费'])
                if c_oid_col:
                    df_c_raw['OID_CLEAN'] = smart_format_id(df_c_raw[c_oid_col])
                    df_c_raw['NUM_W_FEE'] = force_numeric_col(df_c_raw[c_w_fee]) if c_w_fee else 0.0
                    df_c_raw['NUM_D_FEE'] = force_numeric_col(df_c_raw[c_d_fee]) if c_d_fee else 0.0
                    df_comp_logi = df_c_raw[(df_c_raw['OID_CLEAN'] != "") & ((df_c_raw['NUM_W_FEE'] != 0) | (df_c_raw['NUM_D_FEE'] != 0))].groupby('OID_CLEAN').agg({'NUM_W_FEE': 'sum', 'NUM_D_FEE': 'sum'}).reset_index()
                    df_comp_logi.columns = ['订单ID_CLEAN', '操作费_C_KRW', '配送费_C_KRW']

            df_logi_final = pd.merge(df_w_agg, df_d_agg, on='订单ID_CLEAN', how='outer').fillna(0)
            # BUG2修复：赔偿报告物流费只补充物流表中没有的订单，避免重复计入
            logi_existing_oids = set(df_logi_final['订单ID_CLEAN'].unique())
            if not df_comp_logi.empty:
                df_comp_logi_new = df_comp_logi[~df_comp_logi['订单ID_CLEAN'].isin(logi_existing_oids)]
            else:
                df_comp_logi_new = df_comp_logi
            df_logi_final = pd.merge(df_logi_final, df_comp_logi_new, on='订单ID_CLEAN', how='outer').fillna(0)
            df_logi_final['操作费_SUM'] = df_logi_final.get('操作费_KRW', 0) + df_logi_final.get('操作费_C_KRW', 0)
            df_logi_final['配送费_SUM'] = df_logi_final.get('配送费_KRW', 0) + df_logi_final.get('配送费_C_KRW', 0)
            df_logi_final = df_logi_final[['订单ID_CLEAN', '操作费_SUM', '配送费_SUM']].rename(columns={'操作费_SUM': '操作费_KRW', '配送费_SUM': '配送费_KRW'})

            df_st = smart_read_with_multi_header(f_stor, keywords=['SKU ID'])
            if df_st is None or df_st.empty:
                raise ValueError('仓储费明细表未成功解析，请检查文件格式')
            st_sku_c = find_col_by_keywords(df_st.columns, ['SKU ID'])
            if not st_sku_c:
                raise ValueError('仓储费明细表未识别到 SKU ID 字段')
            df_st['ID_CLEAN'] = smart_format_id(df_st[st_sku_c])
            st_f_col = find_col_by_keywords(df_st.columns, kw_fees_priority)
            if st_f_col:
                df_st['NUM_FEE'] = force_numeric_col(df_st[st_f_col])
                df_st_sum = df_st[(df_st['ID_CLEAN'] != "") & (df_st['NUM_FEE'] != 0)].groupby('ID_CLEAN')['NUM_FEE'].sum().reset_index()
            else:
                health_issues.append(build_health_issue('仓储报表', '高', '未识别到仓储费用列，仓储分摊将按 0 处理'))
                df_st_sum = pd.DataFrame(columns=['SKU ID', '月仓储费_KRW'])
            health_stats.append({'模块': '仓储报表', '指标': '可归属 SKU 数', '值': len(df_st_sum)})
            df_st_sum.columns = ['SKU ID', '月仓储费_KRW']

            status.update(label=f"✅ {APP_VERSION} 审计引擎已就绪", state="complete")

        render_health_report(health_issues, '待成本校验', '结构性检查已完成；最终可信度会在成本同步后更新。', health_stats)

        sku_summary_base = df_s_agg[df_s_agg['GROSS_QTY'] > 0].groupby(['ID_CLEAN']).agg({'注册商品名称': 'first', '选项名': 'first', 'GROSS_QTY': 'sum'}).reset_index()
        sku_summary_base['SKU 标识'] = sku_summary_base.apply(lambda r: f"{r['注册商品名称']} | {r['选项名']}", axis=1)
        sku_summary_base = sku_summary_base[['ID_CLEAN', 'SKU 标识', 'GROSS_QTY']]
        sku_summary_base.columns = ['SKU ID', 'SKU 标识', '实发总量']
        for col in ['单件进价 (RMB)', '单件头程 (RMB)', '单件体积']:
            sku_summary_base[col] = 1.0 if '体积' in col else 0.0

        st.subheader("📝 成本维护与同步")
        c_io1, c_io2 = st.columns(2)
        with c_io1:
            buf = io.BytesIO()
            with pd.ExcelWriter(buf) as wr:
                sku_summary_base.to_excel(wr, index=False)
            st.download_button("📥 下载成本模板", data=buf.getvalue(), file_name="酷澎成本维护模板.xlsx")
        with c_io2:
            f_c = st.file_uploader("📤 上传成本表", type=["xlsx"])
            if f_c:
                im = normalize_cost_template(pd.read_excel(f_c))
                im['SKU ID'] = smart_format_id(im.get('SKU ID', ''))
                for col in ['单件进价 (RMB)', '单件头程 (RMB)', '单件体积']:
                    if col in im.columns:
                        cost_map = im.set_index('SKU ID')[col].fillna(0).to_dict()
                        sku_summary_base[col] = sku_summary_base['SKU ID'].map(cost_map).combine_first(sku_summary_base[col])
                st.success("✅ 成本数据已同步（已兼容旧版/新版成本模板字段）")
        edited_df = st.data_editor(sku_summary_base, use_container_width=True, hide_index=True)

        cost_missing_purchase = int((edited_df['单件进价 (RMB)'].fillna(0) <= 0).sum())
        cost_missing_head = int((edited_df['单件头程 (RMB)'].fillna(0) < 0).sum())
        cost_missing_volume = int((edited_df['单件体积'].fillna(0) <= 0).sum())
        health_stats_cost = [
            {'模块': '成本表', '指标': 'SKU 总数', '值': len(edited_df)},
            {'模块': '成本表', '指标': '缺进价 SKU 数', '值': cost_missing_purchase},
            {'模块': '成本表', '指标': '缺体积 SKU 数', '值': cost_missing_volume},
        ]
        final_health_issues = list(health_issues)
        if cost_missing_purchase > 0:
            final_health_issues.append(build_health_issue('成本表', '高', f'有 {cost_missing_purchase} 个 SKU 单件进价未填写或为 0，利润会被高估'))
        if cost_missing_volume > 0 and '体积权重' in allocation_mode:
            final_health_issues.append(build_health_issue('成本表', '中', f'有 {cost_missing_volume} 个 SKU 单件体积未填写或为 0，体积分摊会退化为兜底权重'))
        if cost_missing_head > 0:
            final_health_issues.append(build_health_issue('成本表', '低', f'有 {cost_missing_head} 个 SKU 单件头程出现异常负值，请复核'))

        high_risk_count = sum(1 for x in final_health_issues if x['级别'] == '高')
        hard_block_reasons = []
        if cost_missing_purchase > 0:
            hard_block_reasons.append(f'存在 {cost_missing_purchase} 个 SKU 缺少单件进价')
        if cost_missing_volume > 0 and '体积权重' in allocation_mode:
            hard_block_reasons.append(f'当前使用体积分摊，但有 {cost_missing_volume} 个 SKU 缺少体积')
        if any(x['模块'] == '物流报表' and x['级别'] == '高' for x in final_health_issues):
            hard_block_reasons.append('物流报表存在高风险映射问题')
        if any(x['模块'] == '仓储报表' and x['级别'] == '高' for x in final_health_issues):
            hard_block_reasons.append('仓储报表缺少关键费用字段')
        if any(x['模块'] == '赔偿报表' and x['级别'] == '高' for x in final_health_issues):
            hard_block_reasons.append('赔偿报表缺少关键字段')

        if high_risk_count == 0 and not hard_block_reasons:
            confidence = '高'
            confidence_reason = '未发现高风险结构问题，结果具备较高参考价值。'
        elif len(hard_block_reasons) == 0:
            confidence = '中'
            confidence_reason = '存在风险提示，但尚未触发硬阻断；结果可参考，需谨慎采信。'
        else:
            confidence = '低'
            confidence_reason = '已触发准确性阻断条件：当前不允许输出正式利润。'

        render_health_report(final_health_issues, confidence, confidence_reason, health_stats + health_stats_cost)
        if hard_block_reasons:
            st.error('⛔ 已触发正式利润阻断：')
            for reason in hard_block_reasons:
                st.write(f'• {reason}')
            st.info('请先修正以上问题，再执行正式核算。')

        block_missing_logistics = st.checkbox('缺物流映射时阻断正式利润', value=False, help='开启后，只要存在未匹配物流费用的订单，就不允许正式核算。')

        if st.button("🚀 执行全量损益深度对账核算", type="primary", disabled=len(hard_block_reasons) > 0):
            try:
                cost_final = edited_df.drop_duplicates(subset=['SKU ID']).reset_index(drop=True)
                df_calc = pd.merge(df_s_agg, cost_final, left_on='ID_CLEAN', right_on='SKU ID', how='left', suffixes=('', '_c'))
                for col in ['NET_QTY', 'GROSS_QTY', 'NET_REV', 'NET_SETTLEMENT', 'GROSS_SALES', 'NET_COMM', 'NET_COMM_VAT', '单件进价 (RMB)', '单件头程 (RMB)', '单件体积']:
                    if col in df_calc.columns:
                        df_calc[col] = force_numeric_col(df_calc[col]).astype(float)

                df_calc['成交额_RMB'] = df_calc['NET_REV'] * ex_rate
                df_calc['结算额_RMB'] = df_calc['NET_SETTLEMENT'] * ex_rate
                df_calc['总销售额_RMB'] = df_calc['GROSS_SALES'] * ex_rate
                df_calc['佣金_RMB'] = (df_calc['NET_COMM'] + df_calc['NET_COMM_VAT']) * ex_rate
                df_calc = pd.merge(df_calc, df_logi_final, on='订单ID_CLEAN', how='left')
                df_calc['物流缺失标记'] = df_calc['操作费_KRW'].isna() & df_calc['配送费_KRW'].isna()
                df_calc[['操作费_KRW', '配送费_KRW']] = df_calc[['操作费_KRW', '配送费_KRW']].fillna(0)
                df_calc['ID_CLEAN'] = df_calc['ID_CLEAN'].fillna('EXTERNAL_HISTORY')
                df_calc['SKU 标识'] = df_calc['SKU 标识'].fillna('往期/取消单结算')
                for col in ['NET_QTY', 'GROSS_QTY', '成交额_RMB', '结算额_RMB', '总销售额_RMB', '佣金_RMB', '单件进价 (RMB)', '单件头程 (RMB)', '单件体积']:
                    df_calc[col] = df_calc[col].fillna(0)

                missing_logi_orders = int(df_calc.loc[df_calc['物流缺失标记'], '订单ID_CLEAN'].nunique())
                if missing_logi_orders > 0:
                    if block_missing_logistics:
                        st.error(f'⛔ 已阻断正式利润：存在 {missing_logi_orders} 个订单未匹配物流费用。请先修复物流映射，或取消勾选“缺物流映射时阻断正式利润”。')
                        st.dataframe(
                            df_calc.loc[df_calc['物流缺失标记'], ['订单ID_CLEAN', 'ID_CLEAN', 'SKU 标识']].drop_duplicates(),
                            use_container_width=True,
                            hide_index=True
                        )
                        st.stop()
                    st.warning(f"⚠️ 当前有 {missing_logi_orders} 个订单未匹配到物流费用，系统暂按 0 计入，请谨慎看利润。")

                if "体积权重" in allocation_mode:
                    if (df_calc['单件体积'] <= 0).any():
                        st.error('⛔ 已阻断正式利润：当前使用体积分摊，但存在 SKU 未填写有效体积。')
                        st.dataframe(
                            df_calc.loc[df_calc['单件体积'] <= 0, ['ID_CLEAN', 'SKU 标识', '单件体积']].drop_duplicates(),
                            use_container_width=True,
                            hide_index=True
                        )
                        st.stop()
                    df_calc['分摊权重'] = df_calc['单件体积'] * df_calc['GROSS_QTY']
                    t_w_global = df_calc.groupby('订单ID_CLEAN')['分摊权重'].transform('sum').replace(0, 1)
                    df_calc['分摊比例'] = df_calc['分摊权重'] / t_w_global
                else:
                    order_item_counts = df_calc.groupby('订单ID_CLEAN')['ID_CLEAN'].transform('count').replace(0, 1)
                    df_calc['分摊比例'] = 1.0 / order_item_counts

                df_calc['操作费_RMB'] = (df_calc['操作费_KRW'] * ex_rate) * df_calc['分摊比例']
                df_calc['配送费_RMB'] = (df_calc['配送费_KRW'] * ex_rate) * df_calc['分摊比例']
                df_calc['物流总计_RMB'] = df_calc['操作费_RMB'] + df_calc['配送费_RMB']

                sku_gross_sum_global = df_calc.groupby('SKUID_CLEAN')['GROSS_QTY'].transform('sum').replace(0, 1)  # BUG1修复：用SKUID分组
                if not df_st_sum.empty:
                    df_calc = pd.merge(df_calc, df_st_sum, left_on='SKUID_CLEAN', right_on='SKU ID', how='left').fillna(0)  # BUG1修复：用SKUID_CLEAN关联仓储费
                    df_calc['仓储分摊_RMB'] = (df_calc['月仓储费_KRW'] * ex_rate / sku_gross_sum_global) * df_calc['GROSS_QTY']
                else:
                    df_calc['仓储分摊_RMB'] = 0.0

                df_calc['退货数量'] = (df_calc['GROSS_QTY'] - df_calc['NET_QTY']).clip(lower=0)
                df_calc['沉没货值总计_RMB'] = df_calc['退货数量'] * (df_calc['单件进价 (RMB)'] + df_calc['单件头程 (RMB)'])

                s_loss_map = {}
                total_current_comp_loss = 0.0
                if not df_c_raw.empty:
                    sid_c = find_col_by_keywords(df_c_raw.columns, ['选项ID', 'SKU ID', '选项 ID'])
                    oid_c = find_col_by_keywords(df_c_raw.columns, ['订单ID', '订单 ID'])
                    fee_c = find_col_by_keywords(df_c_raw.columns, ['赔偿金额', '结算金额'])
                    qty_c_comp = find_col_by_keywords(df_c_raw.columns, ['数量', '赔偿数量'])

                    if not sid_c or not oid_c or not fee_c:
                        st.error('⛔ 已阻断正式利润：赔偿报表缺少 SKU / 订单ID / 赔偿金额 关键字段。')
                        st.stop()
                    else:
                        df_c_raw['ID_M'] = smart_format_id(df_c_raw[sid_c])
                        df_c_raw['OID_M'] = smart_format_id(df_c_raw[oid_c])
                        df_c_raw['赔偿数量'] = force_numeric_col(df_c_raw[qty_c_comp]).fillna(1).clip(lower=1) if qty_c_comp else 1
                        df_c_p = pd.merge(df_c_raw, cost_final[['SKU ID', '单件进价 (RMB)', '单件头程 (RMB)']], left_on='ID_M', right_on='SKU ID', how='left')
                        df_c_p['单件货值_RMB'] = df_c_p['单件进价 (RMB)'].fillna(0) + df_c_p['单件头程 (RMB)'].fillna(0)
                        df_c_p['货值_RMB'] = df_c_p['单件货值_RMB'] * df_c_p['赔偿数量']
                        df_c_p['赔偿原始金额_RMB'] = force_numeric_col(df_c_p[fee_c]).abs() * ex_rate if fee_c else 0.0
                        if compensation_mode == '赔偿金额为单件金额':
                            df_c_p['赔偿金_RMB'] = df_c_p['赔偿原始金额_RMB'] * df_c_p['赔偿数量']
                        else:
                            df_c_p['赔偿金_RMB'] = df_c_p['赔偿原始金额_RMB']
                        df_c_p['净亏损_RMB'] = (df_c_p['货值_RMB'] - df_c_p['赔偿金_RMB']).clip(lower=0)
                        comp_total_mode = df_c_p['赔偿原始金额_RMB']
                        comp_unit_mode = df_c_p['赔偿原始金额_RMB'] * df_c_p['赔偿数量']
                        compensation_audit_preview = df_c_p[[
                            'OID_M', 'ID_M', '赔偿数量', '赔偿原始金额_RMB', '货值_RMB'
                        ]].copy()
                        compensation_audit_preview['整行总额口径赔偿金_RMB'] = comp_total_mode
                        compensation_audit_preview['单件金额口径赔偿金_RMB'] = comp_unit_mode
                        compensation_audit_preview['双口径差值_RMB'] = compensation_audit_preview['单件金额口径赔偿金_RMB'] - compensation_audit_preview['整行总额口径赔偿金_RMB']
                        compensation_audit_preview['当前采用赔偿金_RMB'] = df_c_p['赔偿金_RMB']
                        compensation_audit_preview['当前净亏损_RMB'] = df_c_p['净亏损_RMB']
                        type_c = find_col_by_keywords(df_c_raw.columns, ['类型'])
                        damage_c = find_col_by_keywords(df_c_raw.columns, ['损坏/丢失'])
                        responsibility_c = find_col_by_keywords(df_c_raw.columns, ['退货责任方', '责任方'])
                        compensation_audit_preview['类型'] = df_c_raw[type_c].astype(str).values if type_c else ''
                        compensation_audit_preview['损坏/丢失'] = df_c_raw[damage_c].astype(str).values if damage_c else ''
                        compensation_audit_preview['责任方'] = df_c_raw[responsibility_c].astype(str).values if responsibility_c else ''
                        compensation_audit_preview['赔偿口径'] = compensation_mode

                        oids_set = set(df_calc['订单ID_CLEAN'].unique())
                        for _, r in df_c_p.iterrows():
                            oid, sid, net_loss = r['OID_M'], r['ID_M'], r['净亏损_RMB']
                            if oid not in oids_set and sid != "":
                                s_loss_map[sid] = s_loss_map.get(sid, 0) + net_loss

                        current_month_comp = df_c_p[df_c_p['OID_M'].isin(oids_set)]
                        total_current_comp_loss = current_month_comp['净亏损_RMB'].sum()
                        comp_loss_by_oid = current_month_comp.groupby('OID_M')['净亏损_RMB'].sum().to_dict()
                        df_calc['本月赔偿净亏损_RMB'] = df_calc['订单ID_CLEAN'].map(comp_loss_by_oid).fillna(0)
                        if qty_c_comp and compensation_mode == '赔偿金额为单件金额':
                            health_issues.append(build_health_issue('赔偿报表', '中', '当前赔偿按“单件金额 × 数量”口径计算，请确认赔偿字段不是整行总额'))
                        elif compensation_mode == '赔偿金额为整行总额':
                            health_stats.append({'模块': '赔偿报表', '指标': '赔偿口径', '值': '整行总额'})
                        else:
                            health_stats.append({'模块': '赔偿报表', '指标': '赔偿口径', '值': '单件金额'})
                else:
                    df_calc['本月赔偿净亏损_RMB'] = 0.0

                df_calc['均摊损耗_RMB'] = (df_calc['ID_CLEAN'].map(s_loss_map).fillna(0) / sku_gross_sum_global) * df_calc['GROSS_QTY']
                df_calc['货值成本_RMB'] = (df_calc['单件进价 (RMB)'] + df_calc['单件头程 (RMB)']) * df_calc['NET_QTY']
                # 经营口径：以成交额为基础，适合看产品经营表现
                df_calc['经营毛利_RMB'] = df_calc['成交额_RMB'] - df_calc['货值成本_RMB'] - df_calc['物流总计_RMB'] - df_calc['佣金_RMB']
                df_calc['经营净利_RMB'] = df_calc['经营毛利_RMB'] - df_calc['本月赔偿净亏损_RMB'] - df_calc['仓储分摊_RMB'] - df_calc['均摊损耗_RMB']
                # 结算口径：以平台结算金额为基础，避免把优惠券/平台补贴误当利润
                df_calc['结算毛利_RMB'] = df_calc['结算额_RMB'] - df_calc['货值成本_RMB'] - df_calc['物流总计_RMB']
                df_calc['结算净利_RMB'] = df_calc['结算毛利_RMB'] - df_calc['本月赔偿净亏损_RMB'] - df_calc['仓储分摊_RMB'] - df_calc['均摊损耗_RMB']

                total_settlement_rmb = df_calc['结算额_RMB'].sum()
                if total_settlement_rmb > 0:
                    df_calc['自然口径分摊成本_RMB'] = (df_calc['结算额_RMB'] / total_settlement_rmb) * natural_patch_cny
                    df_calc['广告分摊成本_RMB'] = (df_calc['结算额_RMB'] / total_settlement_rmb) * ads_patch_cny
                else:
                    df_calc['自然口径分摊成本_RMB'] = 0.0
                    df_calc['广告分摊成本_RMB'] = 0.0
                df_calc['经营自然净利_RMB'] = df_calc['经营净利_RMB'] - df_calc['自然口径分摊成本_RMB']
                df_calc['结算自然净利_RMB'] = df_calc['结算净利_RMB'] - df_calc['自然口径分摊成本_RMB']
                df_calc['经营全口径净利_RMB'] = df_calc['经营自然净利_RMB'] - df_calc['广告分摊成本_RMB']
                df_calc['结算全口径净利_RMB'] = df_calc['结算自然净利_RMB'] - df_calc['广告分摊成本_RMB']
            except Exception as e:
                st.error(f'❌ 本次核算失败：{e}')
                st.exception(e)
                st.stop()

            def generate_audit_note_v91(row):
                notes = []
                oid = row['订单ID_CLEAN']
                raw_st = status_map.get(oid, "未知")
                if "取消" in str(raw_st) or "退款" in str(raw_st):
                    if row['退货数量'] > 0:
                        notes.append(f"【{raw_st}】产生损耗")
                    else:
                        notes.append(f"【{raw_st}】已冲平")
                dt_str = str(date_map.get(oid, ""))
                if ("31" in dt_str or "30" in dt_str) and row['物流总计_RMB'] == 0:
                    notes.append("【月末单】物流滞后")
                if row['结算额_RMB'] > 0 and row['物流总计_RMB'] == 0 and not any(k in "".join(notes) for k in ["取消", "退款", "月末"]):
                    notes.append("⚠️ 漏算风险")
                return " | ".join(notes) if notes else "正常订单"

            df_calc['审计备注'] = df_calc.apply(generate_audit_note_v91, axis=1)

            st.divider()
            st.subheader("👔 老板默认视图")
            turnover_total = df_calc['成交额_RMB'].sum()
            settlement_total = df_calc['结算额_RMB'].sum()
            net_natural_settlement = df_calc['结算自然净利_RMB'].sum()
            net_final_settlement = df_calc['结算全口径净利_RMB'].sum()
            loss_total = df_calc['均摊损耗_RMB'].sum() + total_current_comp_loss
            
            # 存储到 session_state 供 PDF生成使用
            st.session_state['pdf_context'] = {
                'turnover_total': turnover_total,
                'settlement_total': settlement_total,
                'net_natural_settlement': net_natural_settlement,
                'net_final_settlement': net_final_settlement,
                'loss_total': loss_total,
                'allocation_mode': allocation_mode,
                'df_calc': df_calc,
                'total_current_comp_loss': total_current_comp_loss,
                'natural_patch_cny': natural_patch_cny,
                'ads_patch_cny': ads_patch_cny,
            }

            boss1, boss2, boss3, boss4, boss5, boss6 = st.columns(6)
            boss1.metric("老板最该看：结算自然净利润", f"¥ {net_natural_settlement:,.2f}")
            boss2.metric("结算口径收入", f"¥ {settlement_total:,.2f}")
            boss3.metric("自然结算利润率", f"{(net_natural_settlement / settlement_total * 100 if settlement_total > 0 else 0):.2f}%")
            boss4.metric("货值成本", f"¥ {df_calc['货值成本_RMB'].sum():,.2f}")
            boss5.metric("物流仓配", f"¥ {df_calc['物流总计_RMB'].sum() + df_calc['仓储分摊_RMB'].sum():,.2f}")
            boss6.metric("退货/沉没货值", f"¥ {loss_total:,.2f}")

            with st.expander("展开查看全部核算口径", expanded=False):
                st.subheader("📌 财务核算关键指标 (韩元/人民币双核校验)")
                col_check1, col_check2, col_check3, col_check4 = st.columns(4)
                with col_check1:
                    st.metric("成交额合计", f"{df_calc['NET_REV'].sum():,.0f} KRW")
                with col_check2:
                    st.metric("结算金额合计", f"{df_calc['NET_SETTLEMENT'].sum():,.0f} KRW")
                with col_check3:
                    st.metric("物流费总支出", f"{(df_calc['操作费_KRW'].sum() + df_calc['配送费_KRW'].sum()):,.0f} KRW")
                with col_check4:
                    st.metric("公共费用总支出", f"{(ads_krw + vat_krw):,.0f} KRW")

                st.divider()
                st.subheader("① 自然净利润（含税费，不含广告）")
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("营业额", f"¥ {turnover_total:,.2f}")
                m2.metric("实际收款", f"¥ {settlement_total:,.2f}")
                m3.metric("自然净利润", f"¥ {net_natural_settlement:,.2f}")
                m4.metric("自然净利率", f"{(net_natural_settlement / settlement_total * 100 if settlement_total > 0 else 0):.2f}%")

                st.divider()
                st.subheader("② 全口径净利润（含广告费 + 税费）")
                m5, m6, m7, m8 = st.columns(4)
                m5.metric("★最终利润★", f"¥ {net_final_settlement:,.2f}")
                m6.metric("★全口径净利率★", f"{(net_final_settlement / settlement_total * 100 if settlement_total > 0 else 0):.2f}%")
                m7.metric("广告费分摊", f"¥ {df_calc['广告分摊成本_RMB'].sum():,.2f}")
                m8.metric("历史损耗", f"¥ {loss_total:,.2f}")

            c_pie, c_rank = st.columns([3, 2])
            with c_pie:
                st.subheader("💰 成本分配及营收拆解")
                v_p = [
                    df_calc['货值成本_RMB'].sum(), df_calc['佣金_RMB'].sum(), df_calc['物流总计_RMB'].sum(),
                    df_calc['仓储分摊_RMB'].sum(), total_current_comp_loss, natural_patch_cny,
                    ads_patch_cny, max(0, net_final_settlement)
                ]
                l_p = ['货值成本', '佣金支出', '物流仓配', '月仓储费', '赔偿净亏损', '增值税+杂费', '广告费', '结算口径纯利']
                fv, fl = zip(*[(v_p[i], l_p[i]) for i in range(len(v_p)) if v_p[i] > 0]) if any(v > 0 for v in v_p) else ([1], ['暂无数据'])
                fig_pie, ax_pie = plt.subplots(figsize=(8, 6))
                ax_pie.pie(fv, labels=fl, autopct='%1.1f%%', startangle=140, colors=sns.color_palette('pastel'))
                st.pyplot(fig_pie)
            with c_rank:
                st.subheader("🚨 亏损单排行 (含沉没成本)")
                res_rk = df_calc.groupby(['ID_CLEAN', 'SKU 标识'])['结算全口径净利_RMB'].sum().reset_index()
                rk_display = res_rk[res_rk['结算全口径净利_RMB'] < 0].sort_values('结算全口径净利_RMB')
                st.dataframe(rk_display, use_container_width=True, hide_index=True)

            t1, t2, t3, t4, t5 = st.tabs(["📋 SKU 损益穿透表", "🔍 审计校验表", "🩺 数据健康明细", "🚨 异常订单审计", "📥 数据导出中心"])
            with t1:
                # 优化后的 SKU 损益穿透表（仅结算口径，含利润率）
                res_sku = df_calc.groupby(['ID_CLEAN', 'SKU 标识']).agg({
                    'GROSS_QTY': 'sum',
                    'NET_QTY': 'sum',
                    '退货数量': 'sum',
                    'NET_REV': 'sum',
                    'NET_SETTLEMENT': 'sum',
                    '成交额_RMB': 'sum',
                    '结算额_RMB': 'sum',
                    '货值成本_RMB': 'sum',
                    '佣金_RMB': 'sum',
                    '物流总计_RMB': 'sum',
                    '仓储分摊_RMB': 'sum',
                    '本月赔偿净亏损_RMB': 'sum',
                    '均摊损耗_RMB': 'sum',
                    '结算毛利_RMB': 'sum',
                    '结算净利_RMB': 'sum',
                    '结算自然净利_RMB': 'sum',
                    '结算全口径净利_RMB': 'sum',
                }).reset_index()
                # 重命名为老板能看懂的名字
                res_sku = res_sku.rename(columns={
                    'ID_CLEAN': '选项ID',
                    'GROSS_QTY': '发货量',
                    'NET_QTY': '实际销量',
                    '退货数量': '退货量',
                    'NET_REV': '成交额(KRW)',
                    'NET_SETTLEMENT': '结算金额(KRW)',
                    '成交额_RMB': '营业额(¥)',
                    '结算额_RMB': '实际收款(¥)',
                    '货值成本_RMB': '采购成本(¥)',
                    '佣金_RMB': '平台佣金(¥)',
                    '物流总计_RMB': '物流费(¥)',
                    '仓储分摊_RMB': '仓储费(¥)',
                    '本月赔偿净亏损_RMB': '赔偿损失(¥)',
                    '均摊损耗_RMB': '历史损耗(¥)',
                    '结算毛利_RMB': '毛利润(¥)',
                    '结算净利_RMB': '净利润(¥)',
                    '结算自然净利_RMB': '净利润_含税(¥)',
                    '结算全口径净利_RMB': '★最终利润★(¥)',
                })
                # 计算利润率（以实际收款为基准）
                base = res_sku['实际收款(¥)'].replace(0, 1)
                res_sku['毛利率'] = res_sku['毛利润(¥)'] / base
                res_sku['自然净利率'] = res_sku['净利润_含税(¥)'] / base
                res_sku['★全口径净利率★'] = res_sku['★最终利润★(¥)'] / base

                # 按重要性排序列
                col_order = [
                    '选项ID', 'SKU 标识',
                    '发货量', '实际销量', '退货量',
                    '成交额(KRW)', '结算金额(KRW)',
                    '营业额(¥)', '实际收款(¥)',
                    '采购成本(¥)',
                    '平台佣金(¥)', '物流费(¥)', '仓储费(¥)',
                    '赔偿损失(¥)', '历史损耗(¥)',
                    '毛利润(¥)', '净利润(¥)', '净利润_含税(¥)', '★最终利润★(¥)',
                    '毛利率', '自然净利率', '★全口径净利率★',
                ]
                res_sku = res_sku[col_order]
                st.dataframe(res_sku.sort_values('★最终利润★(¥)').style.format({
                    '成交额(KRW)': '{:,.0f}',
                    '结算金额(KRW)': '{:,.0f}',
                    '营业额(¥)': '{:,.2f}',
                    '实际收款(¥)': '{:,.2f}',
                    '采购成本(¥)': '{:,.2f}',
                    '平台佣金(¥)': '{:,.2f}',
                    '物流费(¥)': '{:,.2f}',
                    '仓储费(¥)': '{:,.2f}',
                    '赔偿损失(¥)': '{:,.2f}',
                    '历史损耗(¥)': '{:,.2f}',
                    '毛利润(¥)': '{:,.2f}',
                    '净利润(¥)': '{:,.2f}',
                    '净利润_含税(¥)': '{:,.2f}',
                    '★最终利润★(¥)': '{:,.2f}',
                    '毛利率': '{:.2%}',
                    '自然净利率': '{:.2%}',
                    '★全口径净利率★': '{:.2%}',
                }), use_container_width=True, hide_index=True)

            with t2:
                # 优化后的审计校验表（订单级别明细，含利润率）
                audit = df_calc.copy()
                q_safe = audit['GROSS_QTY'].replace(0, 1)
                rev_safe = audit['结算额_RMB'].replace(0, 1)
                audit['单件售价(KRW)'] = audit['售价(A)']
                audit['单件营业额(¥)'] = audit['成交额_RMB'] / q_safe
                audit['单件实际收款(¥)'] = audit['结算额_RMB'] / q_safe
                audit['单件佣金(¥)'] = audit['佣金_RMB'] / q_safe
                audit['单件物流费(¥)'] = audit['物流总计_RMB'] / q_safe
                audit['单件采购成本(¥)'] = audit['货值成本_RMB'] / q_safe
                audit['单件仓储费(¥)'] = audit['仓储分摊_RMB'] / q_safe
                audit['单件净利_含税(¥)'] = audit['结算自然净利_RMB'] / q_safe
                audit['单件最终利润(¥)'] = audit['结算全口径净利_RMB'] / q_safe
                # 订单级利润率
                audit['自然净利率'] = audit['结算自然净利_RMB'] / rev_safe
                audit['★全口径净利率★'] = audit['结算全口径净利_RMB'] / rev_safe

                res_v = audit[[
                    '订单ID_CLEAN', 'SKU 标识',
                    '发货量' if '发货量' in audit.columns else 'GROSS_QTY',
                    'NET_QTY',
                    '单件售价(KRW)',
                    '单件营业额(¥)', '单件实际收款(¥)',
                    '单件采购成本(¥)', '单件佣金(¥)',
                    '单件物流费(¥)', '单件仓储费(¥)',
                    '单件净利_含税(¥)', '单件最终利润(¥)',
                    '自然净利率', '★全口径净利率★',
                ]].rename(columns={'订单ID_CLEAN': '订单ID', 'GROSS_QTY': '发货量', 'NET_QTY': '实际销量'})
                st.dataframe(res_v.sort_values('单件最终利润(¥)').style.format({
                    '单件售价(KRW)': '{:,.0f}',
                    '单件营业额(¥)': '{:.2f}',
                    '单件实际收款(¥)': '{:.2f}',
                    '单件采购成本(¥)': '{:.2f}',
                    '单件佣金(¥)': '{:.2f}',
                    '单件物流费(¥)': '{:.2f}',
                    '单件仓储费(¥)': '{:.2f}',
                    '单件净利_含税(¥)': '{:.2f}',
                    '单件最终利润(¥)': '{:.2f}',
                    '自然净利率': '{:.2%}',
                    '★全口径净利率★': '{:.2%}',
                }), use_container_width=True, hide_index=True)
                if not compensation_audit_preview.empty:
                    st.markdown('### 🧾 赔偿口径校验预览')
                    st.dataframe(compensation_audit_preview.head(200), use_container_width=True, hide_index=True)

            with t3:
                st.subheader("🩺 数据健康明细")
                health_detail = df_calc[[
                    '订单ID_CLEAN', 'ID_CLEAN', 'SKU 标识', '物流缺失标记', '单件进价 (RMB)', '单件头程 (RMB)', '单件体积',
                    '操作费_KRW', '配送费_KRW', '成交额_RMB', '结算额_RMB', '结算自然净利_RMB', '结算全口径净利_RMB'
                ]].copy()
                health_detail['成本缺失'] = health_detail['单件进价 (RMB)'] <= 0
                health_detail['体积缺失'] = health_detail['单件体积'] <= 0
                health_detail['正式利润可放行'] = ~(health_detail['成本缺失'] | (health_detail['体积缺失'] & ('体积权重' in allocation_mode)) | health_detail['物流缺失标记'])
                st.dataframe(health_detail, use_container_width=True, hide_index=True)

            with t4:
                st.subheader("🚨 异常订单审计")
                mixed_trade_detail = df_s_raw.groupby('订单ID_CLEAN').agg({
                    '交易类型': lambda s: ' | '.join(sorted({str(x).strip() for x in s if str(x).strip() and str(x).lower() not in ['nan', 'none', 'null']})),
                    'ID_CLEAN': 'nunique',
                    'TEMP_QTY': 'sum'
                }).reset_index().rename(columns={'交易类型': '交易类型集合', 'ID_CLEAN': 'SKU数', 'TEMP_QTY': '净数量合计'})
                mixed_trade_detail = mixed_trade_detail[mixed_trade_detail['交易类型集合'].str.contains('|', regex=False, na=False)]
                if not mixed_trade_detail.empty:
                    st.dataframe(mixed_trade_detail, use_container_width=True, hide_index=True)
                else:
                    st.success('未发现多交易类型混合订单。')

                if not compensation_audit_preview.empty:
                    st.markdown('### 🧾 赔偿双口径对比')
                    st.dataframe(compensation_audit_preview.head(300), use_container_width=True, hide_index=True)
                    if '类型' in compensation_audit_preview.columns:
                        st.markdown('### 📊 赔偿类型分布')
                        comp_type_summary = compensation_audit_preview.groupby(['类型', '损坏/丢失', '责任方'], dropna=False).agg({
                            '当前净亏损_RMB': 'sum',
                            'OID_M': 'count'
                        }).reset_index().rename(columns={'OID_M': '记录数'})
                        st.dataframe(comp_type_summary, use_container_width=True, hide_index=True)

            with t5:
                st.subheader("📊 导出与快照中心")

                def generate_pdf_v101():
                    """V101 精简版 PDF 快照"""
                    # 从 session_state 获取数据
                    ctx = st.session_state.get('pdf_context', {})
                    if not ctx:
                        raise ValueError("请先执行全量损益核算，然后再生成PDF")
                    
                    turnover_total = ctx['turnover_total']
                    settlement_total = ctx['settlement_total']
                    net_natural_settlement = ctx['net_natural_settlement']
                    net_final_settlement = ctx['net_final_settlement']
                    loss_total = ctx['loss_total']
                    allocation_mode = ctx['allocation_mode']
                    df_calc = ctx['df_calc']
                    total_current_comp_loss = ctx['total_current_comp_loss']
                    natural_patch_cny = ctx['natural_patch_cny']
                    ads_patch_cny = ctx['ads_patch_cny']
                    
                    # 计算饼图数据
                    v_p = [
                        df_calc['货值成本_RMB'].sum(), df_calc['佣金_RMB'].sum(), df_calc['物流总计_RMB'].sum(),
                        df_calc['仓储分摊_RMB'].sum(), total_current_comp_loss, natural_patch_cny,
                        ads_patch_cny, max(0, net_final_settlement)
                    ]
                    l_p = ['货值成本', '佣金支出', '物流仓配', '月仓储费', '赔偿净亏损', '增值税+杂费', '广告费', '结算口径纯利']
                    fv, fl = zip(*[(v_p[i], l_p[i]) for i in range(len(v_p)) if v_p[i] > 0]) if any(v > 0 for v in v_p) else ([1], ['暂无数据'])
                    
                    fig_rep = plt.figure(figsize=(10, 14))
                    plt.text(0.5, 0.96, f"酷澎月度财务审计快照 V101 ({datetime.now().strftime('%Y-%m')})", fontsize=22, ha='center', fontweight='bold')
                    plt.axhline(0.94, 0.05, 0.95, color='gray', linewidth=0.5)
                    
                    # 汇总数据
                    sum_txt = (
                        f"核算时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                        f"分摊模式: {allocation_mode}\n\n"
                        f"● 营业额: ¥ {turnover_total:,.2f}\n"
                        f"● 实际收款: ¥ {settlement_total:,.2f}\n"
                        f"● 自然净利润: ¥ {net_natural_settlement:,.2f}\n"
                        f"● ★最终利润★: ¥ {net_final_settlement:,.2f}\n"
                        f"● ★全口径净利率★: {(net_final_settlement / settlement_total * 100 if settlement_total > 0 else 0):.2f}%\n\n"
                        f"● 采购成本: ¥ {df_calc['货值成本_RMB'].sum():,.2f}\n"
                        f"● 平台佣金: ¥ {df_calc['佣金_RMB'].sum():,.2f}\n"
                        f"● 物流费: ¥ {df_calc['物流总计_RMB'].sum():,.2f}\n"
                        f"● 仓储费: ¥ {df_calc['仓储分摊_RMB'].sum():,.2f}\n"
                        f"● 赔偿+损耗: ¥ {loss_total:,.2f}\n"
                    )
                    plt.text(0.1, 0.72, sum_txt, fontsize=13, family='monospace', va='top')
                    
                    # 成本饼图
                    ax_pie_rep = fig_rep.add_axes([0.15, 0.38, 0.7, 0.30])
                    ax_pie_rep.pie(fv, labels=fl, autopct='%1.1f%%', startangle=140, colors=sns.color_palette('pastel'))
                    ax_pie_rep.set_title("成本构成", fontsize=15, pad=20)
                    
                    # 亏损SKU表格
                    plt.text(0.1, 0.34, "⚠️ 亏损 SKU (Top 5):", fontsize=14, color='red', fontweight='bold')
                    res_rk = df_calc.groupby(['ID_CLEAN', 'SKU 标识'])['结算全口径净利_RMB'].sum().reset_index()
                    rk_display = res_rk[res_rk['结算全口径净利_RMB'] < 0].sort_values('结算全口径净利_RMB')
                    if not rk_display.empty:
                        table_vals = rk_display.head(5)[['ID_CLEAN', 'SKU 标识', '结算全口径净利_RMB']].values.tolist()
                        table_head = ["选项ID", "SKU 标识", "★最终利润★(¥)"]
                        tbl = plt.table(cellText=table_vals, colLabels=table_head, loc='center', cellLoc='center', bbox=[0.1, 0.12, 0.8, 0.20])
                        tbl.auto_set_font_size(False)
                        tbl.set_fontsize(9)
                    else:
                        plt.text(0.5, 0.20, "✅ 无亏损SKU", fontsize=16, ha='center', color='green')
                    
                    plt.axis('off')
                    pdf_buf = io.BytesIO()
                    fig_rep.savefig(pdf_buf, format='pdf', bbox_inches='tight')
                    plt.close(fig_rep)
                    return pdf_buf.getvalue()

                col_pdf, col_xlsx = st.columns(2)
                with col_pdf:
                    st.write("📄 **PDF 财务月报快照**")
                    if st.button("🖼️ 1. 生成 PDF 快照", key="btn_generate_pdf"):
                        with st.spinner("正在绘制财务审计快照...请稍候"):
                            try:
                                pdf_data = generate_pdf_v101()
                                st.session_state['pdf_v101'] = pdf_data
                                st.success("✅ 快照已生成！请点击下方按钮下载。")
                            except Exception as e:
                                st.error(f"生成失败: {e}")
                                st.exception(e)
                    st.download_button(
                        label="⬇️ 2. 立即下载 PDF 审计报告",
                        data=st.session_state.get('pdf_v101', b""),
                        file_name=f"Coupang_Audit_V101_{datetime.now().strftime('%Y%m')}.pdf",
                        mime="application/pdf",
                        disabled=st.session_state.get('pdf_v101') is None or len(st.session_state.get('pdf_v101', b"")) == 0,
                        key="btn_download_pdf"
                    )
                    if 'pdf_v101' in st.session_state:
                        st.caption("💡 状态：快照已就绪 (有效期至页面刷新)")
                    else:
                        st.caption("💡 状态：等待生成")

                with col_xlsx:
                    st.write("📁 **审计对账全量数据库 (Excel)**")
                    export_df = df_calc.copy()
                    export_df['核算日期'] = datetime.now().strftime("%Y-%m-%d")
                    output_xlsx = io.BytesIO()
                    with pd.ExcelWriter(output_xlsx) as writer:
                        export_df.to_excel(writer, index=False, sheet_name='Full_Audit_Data')
                    st.download_button(
                        label="📥 下载全量 Excel 对账单",
                        data=output_xlsx.getvalue(),
                        file_name=f"Coupang_Full_Audit_{datetime.now().strftime('%Y%m')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
    except Exception as e:
        st.error(f"核算失败：{e}")
        with st.expander("查看详细技术堆栈"):
            st.code(traceback.format_exc())
else:
    st.info(f"👋 请在侧边栏上传四份核心报表。当前版本：{APP_VERSION}，本版重点是数据准确性与健康检查。")
