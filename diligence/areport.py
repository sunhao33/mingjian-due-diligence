"""A 股年报自动获取 —— 按股票代码取最新年度报告。

数据源：东方财富公告接口（`np-anotice-stock.eastmoney.com`）+ PDF 直链
（`pdf.dfcfw.com`）。一套接口覆盖沪深两市，实测 0.2s 返回、PDF 可下载。

**为什么不用巨潮资讯网**：本机实测 `www.cninfo.com.cn` 与
`static.cninfo.com.cn` 均超时（其余站点正常），属对方对本机 IP 的限制。
数据源可替换，故此处只依赖「公告列表 + PDF 直链」这一抽象。

设计约束（与项目其他部分一致）：
- 本模块**只用标准库**，因此可零依赖测试；
- 网络失败一律抛出带可读信息的异常，由界面层降级回「手工上传 PDF」；
- 不缓存、不猜测：只做「查列表 → 选最新年报 → 下载」三件事。
"""

import json
import os
import re
import ssl
import urllib.parse
import urllib.request

API = "https://np-anotice-stock.eastmoney.com/api/security/ann"
PDF_TPL = "https://pdf.dfcfw.com/pdf/H2_{art_code}_1.pdf"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
REFERER = "https://data.eastmoney.com/"

# 「20XX年年度报告」才算年报；下列词一律排除
_ANNUAL_RE = re.compile(r"(20\d{2})\s*年年度报告")
_EXCLUDE = ("半年度", "半年报", "季度", "季报", "摘要", "英文", "更正", "补充",
            "已取消", "取消", "更新", "提示性公告", "问询", "说明")


class ReportSourceError(RuntimeError):
    """取数失败（网络、代码无效、未找到年报等），信息可直接展示给用户。"""


def normalize_code(text):
    """规范化股票代码：接受 000002 / sz000002 / 000002.SZ 等写法。

    返回 6 位代码字符串；非法输入抛 ReportSourceError。
    """
    if text is None:
        raise ReportSourceError("请填写股票代码")
    s = str(text).strip().upper()
    s = re.sub(r"\.(SZ|SH|BJ)$", "", s)          # 000002.SZ
    s = re.sub(r"^(SZ|SH|BJ)", "", s)            # SZ000002
    s = re.sub(r"\D", "", s)                     # 去掉其它非数字
    if not re.fullmatch(r"\d{6}", s):
        raise ReportSourceError(f"股票代码应为 6 位数字，收到「{text}」")
    return s


def market_of(code):
    """按代码前缀判断市场（用于展示与排序，不影响取数）。"""
    if code.startswith(("60", "68")):
        return "沪市"
    if code.startswith(("00", "30")):
        return "深市"
    if code.startswith(("83", "87", "43", "92")):
        return "北交所"
    return "其它"


def is_annual_report(title):
    """判断公告标题是否为年度报告（排除半年报/季报/摘要/英文版等）。"""
    t = title or ""
    if any(x in t for x in _EXCLUDE):
        return False
    return bool(_ANNUAL_RE.search(t))


def year_of(title):
    m = _ANNUAL_RE.search(title or "")
    return int(m.group(1)) if m else None


def _get_json(url, timeout=20):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Referer": REFERER, "Accept": "application/json, text/plain, */*"})
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE          # 部分财经站点证书链不完整
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:  # noqa: BLE001
        raise ReportSourceError(f"访问数据源失败：{type(e).__name__} {e}") from e


def list_annual_reports(code, max_pages=4, page_size=50):
    """列出该公司的年度报告（按年份倒序）。

    接口按公告日期倒序返回，因此**找到第一条年报即可停止翻页**。
    """
    found = []
    for page in range(1, max_pages + 1):
        url = (f"{API}?sr=-1&page_size={page_size}&page_index={page}&ann_type=A"
               f"&client_source=web&stock_list={code}&f_node=0&s_node=0")
        js = _get_json(url)
        items = (js.get("data") or {}).get("list") or []
        if not items:
            break
        for it in items:
            title = it.get("title") or ""
            if is_annual_report(title):
                found.append({
                    "title": title,
                    "year": year_of(title),
                    "date": (it.get("notice_date") or "")[:10],
                    "art_code": it.get("art_code"),
                    "pdf_url": PDF_TPL.format(art_code=it.get("art_code")),
                    "code": code,
                })
        if found:
            break
    if not found:
        raise ReportSourceError(
            f"未在最近 {max_pages * page_size} 条公告中找到「年度报告」（代码 {code}）")
    found.sort(key=lambda x: (x["year"] or 0, x["date"]), reverse=True)
    return found


def download_pdf(url, dest_path, timeout=90):
    """下载 PDF 到 dest_path。返回文件大小（字节）。"""
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Referer": REFERER, "Accept": "application/pdf,*/*"})
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            head = r.read(5)
            if head[:5] != b"%PDF-":
                raise ReportSourceError(
                    "下载到的不是 PDF（可能被数据源拦截或该公告无附件）")
            with open(dest_path, "wb") as f:
                f.write(head)
                while True:
                    chunk = r.read(1 << 16)
                    if not chunk:
                        break
                    f.write(chunk)
    except ReportSourceError:
        raise
    except Exception as e:  # noqa: BLE001
        raise ReportSourceError(f"下载失败：{type(e).__name__} {e}") from e
    return os.path.getsize(dest_path)


def safe_filename(text, fallback="annual_report.pdf"):
    """把公告标题转成安全文件名。"""
    s = re.sub(r"[\\/:*?\"<>|\s]+", "_", (text or "").strip())
    s = s.strip("_")[:80] or fallback
    return s if s.lower().endswith(".pdf") else s + ".pdf"


def fetch_latest_annual(code, dest_dir, year=None):
    """按代码取年报并下载。返回 (路径, 元信息)。

    year 指定年份时取该年；否则取最新一期。
    """
    code = normalize_code(code)
    reports = list_annual_reports(code)
    if year:
        cand = [r for r in reports if r["year"] == int(year)]
        if not cand:
            raise ReportSourceError(
                f"未找到 {year} 年年报（可用的年份："
                + "、".join(str(r['year']) for r in reports) + "）")
        pick = cand[0]
    else:
        pick = reports[0]
    dest = os.path.join(dest_dir, f"{code}_{safe_filename(pick['title'])}")
    size = download_pdf(pick["pdf_url"], dest)
    pick = dict(pick)
    pick.update({"path": dest, "size": size, "market": market_of(code),
                 "source": "东方财富公告接口"})
    return dest, pick


def describe(meta):
    """一句话描述数据来源，用于报告「数据来源」行与界面提示。"""
    return (f"{meta.get('code')} {meta.get('title')}"
            f"（{meta.get('date')} 公告，{meta.get('source')}）")


def company_name_of(title):
    """从公告标题里取公司简称。

    '美的集团:2025年年度报告'      -> '美的集团'
    '贵州茅台:贵州茅台2025年年度报告' -> '贵州茅台'

    注意不能简单取冒号**后半段**：那样 '美的集团:2025年年度报告' 会得到 '2025'，
    实测把「标的企业」写成了「2025」。
    """
    t = (title or "").strip()
    if ":" in t or "：" in t:
        head = re.split(r"[:：]", t)[0].strip()
        if head and not re.match(r"^20\d{2}", head):
            return head
    stripped = _ANNUAL_RE.sub("", t).strip(" :：·-")
    return stripped or t or "未知公司"
