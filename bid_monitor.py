#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
东方有线网络有限公司 - 上海招投标信息每日监控程序 v2.0
=====================================================
版本: 2.0
功能：
  1. 从中国政府采购网(ccgp.gov.cn)抓取上海地区最新招标/磋商公告
  2. 从上海市政府采购网(zfcg.sh.gov.cn)抓取采购公告（6大类）
  3. 按东方有线业务关键词智能过滤（广电+通信全品类，基于OCN知识库）
  4. 自动抓取详情页提取预算金额和采购需求（ccgp源）
  5. 生成 HTML 报告，自动在浏览器中打开
  6. 支持命令行参数控制抓取天数（1-10天）和输出路径
  7. [v2.0新增] 临港新片区项目智能识别与醒目展示
     - 自动识别采购人位于临港新片区（大治河以南、金汇港以东、小洋山岛区域）
     - 关键词覆盖：环湖/申港/沪城环路/海港大道/水华路/南汇/泥城/书院/
       万祥/四团/奉城/金汇/青村/海湾等临港核心区域
     - 匹配项目在报告中以特殊高亮卡片+置顶专区展示

数据源：
  - 中国政府采购网 (ccgp.gov.cn) — 地方/中央招标公告、竞争性磋商、单一来源
  - 上海市政府采购网 (zfcg.sh.gov.cn) — 公开招标、竞争性磋商、竞争性谈判、
    单一来源、采购意向、询价公告（通过政采云 /portal/category API 抓取）

使用方法：
  python bid_monitor.py                    # 默认抓取最近2天
  python bid_monitor.py --days 1           # 抓取最近1天
  python bid_monitor.py --days 10          # 抓取最近10天
  python bid_monitor.py --output report.html
  python bid_monitor.py --no-open          # 不自动打开浏览器
  python bid_monitor.py --verbose          # 显示详细日志
  python bid_monitor.py --source zfcg      # 只抓上海政府采购网
  python bid_monitor.py --source ccgp      # 只抓中国政府采购网
  python bid_monitor.py --source all       # 抓取全部数据源(默认)

依赖安装：
  pip install requests beautifulsoup4 lxml

作者: WorkBuddy
日期: 2026-07-31
v2.0更新: 2026-08-02 — 临港新片区项目识别+醒目展示，天数范围1-10天
v1.0备份: bid_monitor_v1.py
"""

import argparse
import datetime
import html
import json
import os
import re
import sys
import time
import traceback
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Set
from urllib.parse import urljoin, quote

import requests
from bs4 import BeautifulSoup

# Windows 控制台 UTF-8 输出（避免中文乱码）
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        os.system("chcp 65001 >nul 2>&1")

# ============================================================
# 配置区
# ============================================================

# 东方有线可承接的业务关键词（覆盖广电+通信全品类）
# 东方有线 = 中国广电网络股份有限公司上海分公司
# 第四大基础电信运营商，与电信/移动/联通同级
# 关键词体系基于OCN知识库的产品体系、案例能力矩阵、2026考核品类
KEYWORDS = [
    # === 通信基础（基础电信运营商核心业务）===
    "通信", "电信", "网络", "光纤", "光缆", "宽带", "专线", "5G",
    "基站", "传输", "链路", "城域网", "接入网", "裸光纤",
    "MSTP", "SDH", "PTN", "OTN", "SPN", "波分", "WDM",
    "固话", "语音", "PSTN", "SIP", "中继",
    "BGP", "互联网接入", "互联网专线", "带宽", "出口",
    # === 广电特色（东方有线独有优势）===
    "有线电视", "广电", "广播电视", "应急广播", "电视传输",
    "数字电视", "融媒体", "广电5G", "700M", "广播",
    "频段", "无线电", "地面数字电视",
    # === 信息化/数字化/智能化 ===
    "信息化", "数字化", "智能化", "智慧城市", "智慧社区", "智慧校园",
    "智慧政务", "数字孪生", "物联网", "云计算", "大数据",
    "智慧工厂", "智慧园区", "智慧文旅", "智慧交通",
    "一网统管", "一网通办", "联勤联动", "城市运行", "城市大脑",
    "数据要素", "数据交易", "数据加工",
    # === 安防/监控 ===
    "安防", "监控", "视频监控", "雪亮", "平安城市", "技防",
    "电子围栏", "门禁", "楼宇对讲", "视频门禁",
    "人脸识别", "车牌识别", "智能分析",
    # === 弱电/机房/数据中心 ===
    "弱电", "综合布线", "机房", "数据中心", "IDC",
    "机柜", "UPS", "精密空调", "动环监控",
    "算力", "边缘计算", "智算中心", "超算",
    # === 网络服务 ===
    "政务外网", "政务网", "网络运维", "网络服务",
    "网络建设", "网络安全", "通信运维", "网络设备",
    "系统集成", "ICT",
    # === 应急/指挥/调度 ===
    "应急", "指挥", "调度", "集群", "PDT", "对讲",
    "民防", "人防", "消防通信", "应急指挥",
    # === 教育/酒店/社区（OCN案例库核心行业）===
    "AI精准教学", "AI批阅", "智慧课堂", "教育专网",
    "数字客房", "智慧酒店", "酒店信息化",
    "智能垃圾房", "垃圾分类",
    "党建", "直播", "数字党务",
    # === 信创/国产化 ===
    "信创", "国产化", "自主可控", "国产替代",
    "操作系统", "国产数据库",
    # === 视频会议/协同 ===
    "视频会议", "一卡通", "信息发布", "能耗管理",
    "停车管理", "消防", "防雷",
    # === 其他可承接 ===
    "云桌面", "虚拟化", "容灾", "备份",
    "IP广播", "公共广播", "背景音乐",
]

# 排除关键词（标题中包含这些词的项目不适合东方有线）
EXCLUDE_KEYWORDS = [
    "保洁", "绿化", "垃圾清运", "清扫", "物业", "物业管理",
    "电梯", "空调维保", "供暖", "食堂", "餐饮", "牛奶",
    "医疗设备", "药品", "医疗器械", "耗材", "体检",
    "家具", "复印", "打印", "办公设备",
    "保险", "审计", "评估", "咨询",
    "工程监理", "造价",
    "演出", "演艺", "剧场",
    "游泳", "体育设施",
    "种苗", "苗木", "农药", "肥料",
    "校服", "学生服",
    "教科书", "教材", "课本",
    "车辆", "购车", "租车", "车辆租赁",
    "救护车", "消防车",
]

# ============================================================
# 临港新片区识别关键词
# 东方有线临港新片区分公司重点关注区域
# 地理范围：大治河以南、金汇港以东以及小洋山岛
# ============================================================
LINGANG_KEYWORDS = [
    # === 用户指定关键词 ===
    "环湖", "申港", "沪城环路", "海港大道", "水华路",
    "南汇", "泥城", "书院", "万祥", "四团",
    "奉城", "金汇", "青村", "海湾",
    # === 地理范围相关 ===
    "大治河", "金汇港", "小洋山", "洋山",
    # === 临港核心区域补充 ===
    "临港", "滴水湖", "芦潮港", "临港新片区", "新片区",
    "自贸区临港", "南汇新城", "临港奉贤", "临港产业区",
    "临港重装备", "临港主城区", "临港综合区",
    # === 临港相关道路/地标补充 ===
    "环湖一路", "环湖二路", "环湖三路", "环湖四路",
    "申港大道", "申港东", "申港南",
    "沪城环", "港城路", "杞青路",
    "方竹路", "茉莉路", "紫荆",
    "云端路", "海基路", "海洋一路",
]

# 中国政府采购网公告类型及URL
CCGP_SOURCES = {
    "公开招标": "https://www.ccgp.gov.cn/cggg/dfgg/gkzb/",
    "竞争性磋商": "https://www.ccgp.gov.cn/cggg/dfgg/jzxcs/",
    "单一来源": "https://www.ccgp.gov.cn/cggg/dfgg/dylygg/",
}

# 中央政府采购公告
CCGP_CENTRAL_SOURCES = {
    "中央公开招标": "https://www.ccgp.gov.cn/cggg/zygg/gkzb/",
    "中央竞争性磋商": "https://www.ccgp.gov.cn/cggg/zygg/jzxcs/",
}

# 上海市政府采购网（政采云平台）公告类别配置
# API: POST https://www.zfcg.sh.gov.cn/portal/category
# 每个 categoryCode 对应一种公告类型
ZFCG_CATEGORIES = {
    "ZcyAnnouncement3001": "公开招标公告",
    "ZcyAnnouncement3011": "竞争性磋商公告",
    "ZcyAnnouncement3002": "竞争性谈判公告",
    "ZcyAnnouncement3012": "单一来源采购公示",
    "ZcyAnnouncement10016": "采购意向公开",
    "ZcyAnnouncement3003": "询价公告",
}

# 上海政府采购网详情页URL模板
ZFCG_DETAIL_URL = "https://www.zfcg.sh.gov.cn/site/detail?parentId=137027&articleId={article_id}"

# 上海政府采购网API端点
ZFCG_API_URL = "https://www.zfcg.sh.gov.cn/portal/category"
ZFCG_PARENT_ID = "137027"

# 请求头
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# 上海政府采购网API专用请求头
ZFCG_API_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Content-Type": "application/json",
    "Origin": "https://www.zfcg.sh.gov.cn",
    "Referer": "https://www.zfcg.sh.gov.cn/site/category?parentId=137027&childrenCode=ZcyAnnouncement",
}

REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_DELAY = 2
MAX_PAGES_PER_SOURCE = 10   # ccgp每种公告类型最多翻10页
ZFCG_PAGE_SIZE = 30          # zfcg每页条数
ZFCG_MAX_PAGES = 3           # zfcg每种类别最多翻3页（90条）


# ============================================================
# 数据结构
# ============================================================

@dataclass
class BidItem:
    """招投标信息条目"""
    title: str = ""
    url: str = ""
    date: str = ""
    region: str = ""
    purchaser: str = ""
    budget: str = ""
    notice_type: str = ""
    source: str = ""  # 数据来源: "中国政府采购网" / "上海政府采购网"
    keyword_hits: List[str] = field(default_factory=list)
    match_level: str = ""
    detail: str = ""
    project_name: str = ""
    is_lingang: bool = False           # [v2.0] 是否位于临港新片区
    lingang_reason: str = ""           # [v2.0] 命中的临港关键词

    @property
    def match_score(self) -> int:
        return len(self.keyword_hits)

    def calculate_match_level(self):
        score = self.match_score
        if score >= 5:
            self.match_level = "极高"
        elif score >= 3:
            self.match_level = "高"
        elif score >= 1:
            self.match_level = "中"
        else:
            self.match_level = "低"


# ============================================================
# 关键词匹配引擎
# ============================================================

class KeywordMatcher:
    """关键词匹配和评分引擎"""

    def __init__(self):
        self.keywords = KEYWORDS
        self.exclude_keywords = EXCLUDE_KEYWORDS

    def filter_and_score(self, item: BidItem) -> bool:
        """关键词过滤和评分，返回是否匹配"""
        combined = f"{item.title} {item.detail} {item.purchaser} {item.project_name}".lower()

        # 检查排除关键词（仅标题）
        title_lower = item.title.lower()
        for ex_kw in self.exclude_keywords:
            if ex_kw in title_lower:
                return False

        # 关键词匹配
        hits = []
        for kw in self.keywords:
            if kw.lower() in combined:
                hits.append(kw)

        item.keyword_hits = list(set(hits))  # 去重
        item.calculate_match_level()
        return len(hits) > 0


# ============================================================
# 临港新片区检测器
# ============================================================

class LingangDetector:
    """检测项目是否位于临港新片区

    识别逻辑：
    1. 检查采购人名称、标题、详情、项目名称、地区中是否包含临港区域关键词
    2. 关键词覆盖：用户指定词 + 地理范围词 + 临港核心区域补充词
    """

    def __init__(self):
        self.keywords = LINGANG_KEYWORDS

    def detect(self, item: BidItem) -> bool:
        """检测项目是否位于临港新片区，结果写入 item.is_lingang"""
        combined = f"{item.purchaser} {item.title} {item.detail} {item.project_name} {item.region}"

        hits = []
        for kw in self.keywords:
            if kw in combined:
                hits.append(kw)

        if hits:
            item.is_lingang = True
            item.lingang_reason = ", ".join(hits)
            # [v2.0] 临港项目至少为"中"匹配度
            if item.match_score == 0:
                item.match_level = "中"
            return True
        else:
            item.is_lingang = False
            item.lingang_reason = ""
            return False


# ============================================================
# 中国政府采购网抓取器
# ============================================================

class CcgpScraper:
    """中国政府采购网抓取器"""

    def __init__(self, days: int = 2, verbose: bool = False):
        self.days = days
        self.verbose = verbose
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.cutoff_date = datetime.datetime.now() - datetime.timedelta(days=days)

    def log(self, msg: str):
        if self.verbose:
            print(msg)

    def fetch_page(self, url: str) -> Optional[str]:
        """抓取页面内容，带重试"""
        for attempt in range(MAX_RETRIES):
            try:
                resp = self.session.get(url, timeout=REQUEST_TIMEOUT)
                resp.encoding = resp.apparent_encoding or "utf-8"
                if resp.status_code == 200:
                    return resp.text
                print(f"  [!] HTTP {resp.status_code}")
            except requests.RequestException as e:
                print(f"  [!] 请求失败 (尝试 {attempt+1}/{MAX_RETRIES}): {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
        return None

    def parse_list_page(self, html_text: str, source_name: str, base_url: str) -> List[BidItem]:
        """解析列表页"""
        items = []
        soup = BeautifulSoup(html_text, "lxml")

        lis = soup.select("ul.c_list_bid li")
        if not lis:
            lis = soup.select("ul.ul_compa li")
        if not lis:
            self.log("  [!] 未找到列表元素")
            return items

        for li in lis:
            item = BidItem()
            item.source = "中国政府采购网"
            item.notice_type = source_name

            a_tag = li.find("a")
            if not a_tag:
                continue
            item.title = a_tag.get_text(strip=True)
            href = a_tag.get("href", "")
            if href:
                item.url = urljoin(base_url, href)

            ems = li.find_all("em")
            em_texts = [em.get_text(strip=True) for em in ems]

            for text in em_texts:
                if re.match(r"\d{4}[-/]\d{2}[-/]\d{2}", text):
                    item.date = text
                elif text in ("上海", "北京", "天津", "重庆", "广东", "江苏",
                              "浙江", "山东", "河南", "四川", "湖北", "湖南",
                              "福建", "安徽", "辽宁", "黑龙江", "吉林", "河北",
                              "山西", "陕西", "甘肃", "青海", "云南", "贵州",
                              "广西", "海南", "内蒙古", "新疆", "西藏", "宁夏",
                              "江西", "中央"):
                    item.region = text
                else:
                    if not item.purchaser:
                        item.purchaser = text

            if item.date:
                try:
                    item_date = datetime.datetime.strptime(
                        item.date.replace("/", "-")[:10], "%Y-%m-%d"
                    )
                    if item_date < self.cutoff_date:
                        continue
                except ValueError:
                    pass

            items.append(item)

        return items

    def fetch_detail(self, item: BidItem):
        """抓取公告详情页，提取预算金额和采购需求"""
        if not item.url:
            return

        html_text = self.fetch_page(item.url)
        if not html_text:
            return

        soup = BeautifulSoup(html_text, "lxml")
        text = soup.get_text()

        # 提取预算金额
        budget_patterns = [
            r"预算金额[（(]元[)）]\s*[：:]\s*([\d,]+\.?\d*)",
            r"预算金额\s*[¥￥]?\s*([\d,.]+)\s*万元",
            r"预算金额[：:]\s*[¥￥]?\s*([\d,.]+)\s*万元",
            r"预算金额[：:]\s*[¥￥]?\s*([\d,.]+)\s*元",
        ]
        for pattern in budget_patterns:
            m = re.search(pattern, text)
            if m:
                val = m.group(1).replace(",", "")
                try:
                    num = float(val)
                    if "万" in m.group(0):
                        item.budget = f"{num:.2f}万元"
                    elif num > 10000:
                        item.budget = f"{num / 10000:.2f}万元"
                    else:
                        item.budget = f"{num:.0f}元"
                except ValueError:
                    item.budget = m.group(0).strip()
                break

        # 提取采购需求简要描述
        desc_patterns = [
            r"简要规格描述[：:](.+?)(?:说明[：:]|合同|包号|备注|包名称)",
            r"采购需求[：:](.+?)(?:说明[：:]|合同|包号|备注|包名称)",
            r"简要规则描述[：:](.+?)(?:说明[：:]|合同|包号|备注)",
        ]
        for pattern in desc_patterns:
            m = re.search(pattern, text, re.DOTALL)
            if m:
                detail = m.group(1).strip()
                detail = re.sub(r"\s+", " ", detail)[:300]
                item.detail = detail
                break

    def scrape(self) -> List[BidItem]:
        """执行抓取"""
        all_items = []
        all_sources = {**CCGP_SOURCES, **CCGP_CENTRAL_SOURCES}

        for source_name, url in all_sources.items():
            print(f"\n[*] [中国政府采购网] 抓取 {source_name} ...")
            for page in range(1, MAX_PAGES_PER_SOURCE + 1):
                if page == 1:
                    page_url = url
                else:
                    page_url = urljoin(url, f"index_{page}.htm")

                self.log(f"  -> 第 {page} 页: {page_url}")
                html_text = self.fetch_page(page_url)
                if not html_text:
                    print(f"  [!] 第 {page} 页抓取失败")
                    continue

                items = self.parse_list_page(html_text, source_name, url)
                if not items:
                    print(f"  [!] 第 {page} 页未解析到条目，停止")
                    break

                shanghai_items = [i for i in items if i.region == "上海" or "上海" in i.purchaser]
                if shanghai_items:
                    print(f"  [OK] 第 {page} 页: {len(items)} 条公告, 上海地区: {len(shanghai_items)} 条")
                    all_items.extend(shanghai_items)
                else:
                    self.log(f"  第 {page} 页: {len(items)} 条公告, 上海地区: 0 条")

                has_recent = False
                for i in items:
                    if i.date:
                        try:
                            d = datetime.datetime.strptime(i.date[:10], "%Y-%m-%d")
                            if d >= self.cutoff_date:
                                has_recent = True
                                break
                        except ValueError:
                            pass
                if not has_recent:
                    print(f"  [*] 第 {page} 页已无近期公告，停止翻页")
                    break

                time.sleep(1)

        # 去重
        seen_urls = set()
        unique_items = []
        for item in all_items:
            if item.url and item.url not in seen_urls:
                seen_urls.add(item.url)
                unique_items.append(item)

        print(f"\n[*] [中国政府采购网] 共抓取 {len(unique_items)} 条上海地区公告（去重后）")

        for i, item in enumerate(unique_items, 1):
            self.log(f"  [{i}] {item.date} | {item.title[:60]}")

        # 抓取详情页
        print(f"[*] [中国政府采购网] 抓取详情页...")
        for item in unique_items:
            self.log(f"  [>] {item.title[:50]}...")
            self.fetch_detail(item)
            time.sleep(0.5)

        return unique_items


# ============================================================
# 上海市政府采购网抓取器
# ============================================================

class ZfcgScraper:
    """上海市政府采购网抓取器（通过政采云 API）"""

    def __init__(self, days: int = 2, verbose: bool = False):
        self.days = days
        self.verbose = verbose
        self.session = requests.Session()
        self.session.headers.update(ZFCG_API_HEADERS)
        self.cutoff_date = datetime.datetime.now() - datetime.timedelta(days=days)
        self.today = datetime.datetime.now()

    def log(self, msg: str):
        if self.verbose:
            print(msg)

    def fetch_category(self, category_code: str, category_name: str) -> List[BidItem]:
        """抓取指定类别的公告列表"""
        items = []

        date_begin = self.cutoff_date.strftime("%Y-%m-%d")
        date_end = self.today.strftime("%Y-%m-%d")

        for page in range(1, ZFCG_MAX_PAGES + 1):
            payload = {
                "pageNo": page,
                "pageSize": ZFCG_PAGE_SIZE,
                "parentId": ZFCG_PARENT_ID,
                "categoryCode": category_code,
                "publishDateBegin": date_begin,
                "publishDateEnd": date_end,
                "_t": int(time.time() * 1000),
            }

            self.log(f"  -> {category_name} 第 {page} 页 (pageSize={ZFCG_PAGE_SIZE})")

            for attempt in range(MAX_RETRIES):
                try:
                    resp = self.session.post(
                        ZFCG_API_URL, json=payload, timeout=REQUEST_TIMEOUT
                    )
                    if resp.status_code == 200:
                        break
                    print(f"  [!] HTTP {resp.status_code}")
                except requests.RequestException as e:
                    print(f"  [!] 请求失败 (尝试 {attempt+1}/{MAX_RETRIES}): {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY)
            else:
                print(f"  [!] {category_name} 第 {page} 页抓取失败")
                break

            try:
                result = resp.json()
            except json.JSONDecodeError:
                print(f"  [!] {category_name} 第 {page} 页 JSON解析失败")
                break

            if not result.get("success"):
                print(f"  [!] {category_name} 第 {page} 页返回失败: {result.get('error')}")
                break

            data_obj = result.get("result", {}).get("data", {})
            total = data_obj.get("total", 0)
            page_items = data_obj.get("data", [])

            if not page_items:
                self.log(f"  第 {page} 页无数据，停止")
                break

            print(f"  [OK] {category_name} 第 {page} 页: {len(page_items)} 条 (总计 {total} 条)")

            for raw in page_items:
                item = self._parse_item(raw, category_name)
                if item:
                    items.append(item)

            # 如果当前页是最后一页或数据量不够，停止翻页
            if len(page_items) < ZFCG_PAGE_SIZE:
                break
            if page * ZFCG_PAGE_SIZE >= total:
                break

            time.sleep(0.5)  # 礼貌等待

        return items

    def _parse_item(self, raw: dict, category_name: str) -> Optional[BidItem]:
        """解析API返回的单条公告数据"""
        item = BidItem()
        item.source = "上海政府采购网"
        item.notice_type = category_name

        # 标题
        item.title = raw.get("title", "").strip()
        if not item.title:
            return None

        # articleId 构造详情页URL
        article_id = raw.get("articleId", "")
        if article_id:
            item.url = ZFCG_DETAIL_URL.format(article_id=article_id)

        # 发布日期 (Unix时间戳毫秒)
        publish_ts = raw.get("publishDate")
        if publish_ts:
            try:
                dt = datetime.datetime.fromtimestamp(publish_ts / 1000)
                item.date = dt.strftime("%Y-%m-%d %H:%M")
            except (ValueError, TypeError, OSError):
                item.date = ""

        # 采购人
        item.purchaser = raw.get("purchaseName") or raw.get("author") or ""

        # 地区
        item.region = raw.get("districtName") or "上海"

        # 预算金额 (API返回的是字符串如 "3315000元" 或 "3200000")
        budget = raw.get("budgetPrice")
        if budget:
            budget_str = str(budget).strip()
            # 去掉"元"后缀
            budget_str = re.sub(r'[元]', '', budget_str)
            # 提取数字部分
            num_match = re.search(r'([\d,]+\.?\d*)', budget_str)
            if num_match:
                try:
                    num = float(num_match.group(1).replace(',', ''))
                    if num > 10000:
                        item.budget = f"{num / 10000:.2f}万元"
                    else:
                        item.budget = f"{num:.0f}元"
                except ValueError:
                    item.budget = str(budget)
            else:
                item.budget = str(budget)

        # 项目名称
        item.project_name = raw.get("projectName") or ""

        # 采购方式
        method = raw.get("procurementMethod")
        if method:
            item.detail = f"采购方式: {method}"

        # 公告类型
        path_name = raw.get("pathName", "")
        if path_name:
            item.notice_type = path_name

        return item

    def scrape(self) -> List[BidItem]:
        """执行抓取"""
        all_items = []

        print(f"\n[*] [上海政府采购网] 开始抓取 (日期范围: {self.cutoff_date.strftime('%Y-%m-%d')} ~ {self.today.strftime('%Y-%m-%d')})")

        for code, name in ZFCG_CATEGORIES.items():
            print(f"\n[*] [上海政府采购网] 抓取 {name} ({code}) ...")
            items = self.fetch_category(code, name)
            all_items.extend(items)
            print(f"  [OK] {name}: 获取 {len(items)} 条")
            time.sleep(0.5)

        # 去重（按URL）
        seen_urls = set()
        unique_items = []
        for item in all_items:
            if item.url and item.url not in seen_urls:
                seen_urls.add(item.url)
                unique_items.append(item)
            elif not item.url:
                unique_items.append(item)

        print(f"\n[*] [上海政府采购网] 共抓取 {len(unique_items)} 条公告（去重后）")

        for i, item in enumerate(unique_items[:30], 1):
            self.log(f"  [{i}] {item.date} | {item.title[:60]}")
        if len(unique_items) > 30:
            self.log(f"  ... 还有 {len(unique_items) - 30} 条")

        return unique_items


# ============================================================
# HTML 报告生成
# ============================================================

def generate_html_report(items: List[BidItem], days: int, sources: str) -> str:
    """生成 HTML 报告"""
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    total = len(items)
    high_match = sum(1 for i in items if i.match_level == "极高")
    mid_match = sum(1 for i in items if i.match_level == "高")
    low_match = sum(1 for i in items if i.match_level == "中")

    # 按数据来源统计
    zfcg_count = sum(1 for i in items if i.source == "上海政府采购网")
    ccgp_count = sum(1 for i in items if i.source == "中国政府采购网")

    # [v2.0] 临港新片区项目统计
    lingang_items = [i for i in items if i.is_lingang]
    lingang_count = len(lingang_items)
    non_lingang_items = [i for i in items if not i.is_lingang]

    items_html = ""
    idx_counter = [0]  # mutable counter for index

    def render_item(item: BidItem) -> str:
        idx_counter[0] += 1
        idx = idx_counter[0]
        level_color = {
            "极高": "#e74c3c",
            "高": "#e67e22",
            "中": "#f39c12",
            "低": "#95a5a6",
        }.get(item.match_level, "#95a5a6")

        source_color = {
            "上海政府采购网": "#1565c0",
            "中国政府采购网": "#00897b",
        }.get(item.source, "#757575")

        keywords_html = " ".join(
            f'<span class="kw-tag">{html.escape(kw)}</span>'
            for kw in item.keyword_hits[:12]
        )

        detail_html = ""
        if item.detail:
            detail_html = f'<div class="bid-detail">{html.escape(item.detail)}</div>'

        # [v2.0] 临港新片区特殊展示
        lingang_class = " lingang" if item.is_lingang else ""
        lingang_badge = ""
        lingang_reason_html = ""
        if item.is_lingang:
            lingang_badge = '<span class="lingang-badge">★ 临港新片区</span>'
            lingang_reason_html = f'<div class="lingang-reason"><span class="lingang-label">临港命中:</span> <span class="lingang-keywords">{html.escape(item.lingang_reason)}</span></div>'

        return f"""
        <div class="bid-card{lingang_class}">
            <div class="bid-header">
                <span class="bid-num">#{idx}</span>
                <span class="bid-source" style="background:{source_color}">{html.escape(item.source)}</span>
                <span class="bid-type">{html.escape(item.notice_type or '')}</span>
                {lingang_badge}
                <span class="match-badge" style="background:{level_color}">{item.match_level}</span>
            </div>
            <h3 class="bid-title">
                <a href="{html.escape(item.url)}" target="_blank">{html.escape(item.title)}</a>
            </h3>
            <div class="bid-meta">
                <div class="meta-row">
                    <span class="meta-label">采购人</span>
                    <span class="meta-value">{html.escape(item.purchaser or '详见公告')}</span>
                </div>
                <div class="meta-row">
                    <span class="meta-label">预算金额</span>
                    <span class="meta-value budget">{html.escape(item.budget or '详见公告')}</span>
                </div>
                <div class="meta-row">
                    <span class="meta-label">发布日期</span>
                    <span class="meta-value">{html.escape(item.date or '未知')}</span>
                </div>
                <div class="meta-row">
                    <span class="meta-label">地区</span>
                    <span class="meta-value">{html.escape(item.region or '上海')}</span>
                </div>
            </div>
            {detail_html}
            {lingang_reason_html}
            <div class="bid-keywords">
                <span class="kw-label">命中关键词({item.match_score}):</span>
                {keywords_html if keywords_html else '<span class="kw-none">无</span>'}
            </div>
            <div class="bid-actions">
                <a href="{html.escape(item.url)}" target="_blank" class="btn-view">查看公告原文</a>
            </div>
        </div>"""

    # [v2.0] 临港新片区项目专区
    lingang_section_html = ""
    if lingang_items:
        lingang_section_html = f"""
        <div class="lingang-banner">
            <span class="lingang-icon">★</span>
            <span class="lingang-title-text">临港新片区重点项目</span>
            <span class="lingang-count">{lingang_count} 个项目</span>
        </div>"""
        for item in lingang_items:
            lingang_section_html += render_item(item)

    # 其余项目
    other_section_html = ""
    if non_lingang_items:
        other_section_html = '<div class="section-title">其他匹配项目</div>'
        for item in non_lingang_items:
            other_section_html += render_item(item)

    items_html = lingang_section_html + other_section_html

    if not items:
        items_html = '<div class="no-result">今日未发现匹配的招投标信息</div>'

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>东方有线投标机会监控报告 - {today}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, "Microsoft YaHei", "Segoe UI", sans-serif;
            background: #f0f2f5; color: #333; line-height: 1.6;
        }}
        .header {{
            background: linear-gradient(135deg, #1a237e 0%, #283593 50%, #3949ab 100%);
            color: white; padding: 30px 40px; box-shadow: 0 2px 8px rgba(0,0,0,0.15);
        }}
        .header h1 {{ font-size: 24px; margin-bottom: 8px; }}
        .header .subtitle {{ font-size: 14px; opacity: 0.85; }}
        .header .meta-bar {{ display: flex; gap: 30px; margin-top: 15px; font-size: 13px; opacity: 0.9; flex-wrap: wrap; }}
        .container {{ max-width: 1200px; margin: 0 auto; padding: 20px; }}
        .stats-bar {{ display: flex; gap: 20px; margin-bottom: 25px; flex-wrap: wrap; }}
        .stat-card {{
            flex: 1; min-width: 140px; background: white; border-radius: 8px; padding: 20px;
            text-align: center; box-shadow: 0 1px 4px rgba(0,0,0,0.08);
        }}
        .stat-card .num {{ font-size: 32px; font-weight: bold; color: #1a237e; }}
        .stat-card .label {{ font-size: 13px; color: #666; margin-top: 5px; }}
        .stat-card.high .num {{ color: #e74c3c; }}
        .stat-card.mid .num {{ color: #e67e22; }}
        .stat-card.source .num {{ color: #1565c0; }}
        .section-title {{
            font-size: 18px; font-weight: bold; color: #1a237e;
            margin: 25px 0 15px; padding-left: 12px; border-left: 4px solid #1a237e;
        }}
        .bid-card {{
            background: white; border-radius: 8px; padding: 20px;
            margin-bottom: 15px; box-shadow: 0 1px 4px rgba(0,0,0,0.08);
            transition: box-shadow 0.2s;
        }}
        .bid-card:hover {{ box-shadow: 0 2px 12px rgba(0,0,0,0.12); }}
        .bid-header {{ display: flex; align-items: center; gap: 8px; margin-bottom: 10px; flex-wrap: wrap; }}
        .bid-num {{
            background: #e8eaf6; color: #1a237e; font-weight: bold;
            padding: 2px 10px; border-radius: 4px; font-size: 13px;
        }}
        .bid-source {{
            color: white; padding: 2px 10px; border-radius: 4px; font-size: 11px;
        }}
        .bid-type {{
            background: #e3f2fd; color: #1565c0;
            padding: 2px 10px; border-radius: 4px; font-size: 12px;
        }}
        .match-badge {{
            color: white; padding: 2px 12px; border-radius: 12px;
            font-size: 12px; font-weight: bold; margin-left: auto;
        }}
        .bid-title {{ font-size: 16px; margin: 8px 0 12px; line-height: 1.4; }}
        .bid-title a {{ color: #1a237e; text-decoration: none; }}
        .bid-title a:hover {{ text-decoration: underline; }}
        .bid-meta {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px 20px; }}
        .meta-row {{ display: flex; font-size: 13px; }}
        .meta-label {{ color: #888; min-width: 65px; margin-right: 8px; }}
        .meta-value {{ color: #333; }}
        .meta-value.budget {{ color: #e74c3c; font-weight: bold; }}
        .bid-detail {{
            margin-top: 10px; padding: 10px; background: #f5f5f5;
            border-radius: 4px; font-size: 13px; color: #555;
            max-height: 100px; overflow: hidden; position: relative;
        }}
        .bid-detail::after {{
            content: '...'; position: absolute; bottom: 0; right: 0;
            background: #f5f5f5; padding: 0 5px;
        }}
        .bid-keywords {{ margin-top: 10px; display: flex; flex-wrap: wrap; align-items: center; gap: 5px; }}
        .kw-label {{ font-size: 12px; color: #888; }}
        .kw-tag {{
            background: #e8f5e9; color: #2e7d32;
            padding: 1px 8px; border-radius: 10px; font-size: 11px;
        }}
        .kw-none {{ font-size: 12px; color: #ccc; }}
        .bid-actions {{ margin-top: 12px; }}
        .btn-view {{
            display: inline-block; padding: 5px 20px;
            background: #1a237e; color: white; text-decoration: none;
            border-radius: 4px; font-size: 13px;
        }}
        .btn-view:hover {{ background: #283593; }}
        .no-result {{ text-align: center; padding: 60px; color: #999; font-size: 16px; }}
        /* [v2.0] 临港新片区醒目样式 */
        .lingang-banner {{
            background: linear-gradient(135deg, #b71c1c 0%, #c62828 50%, #d84315 100%);
            color: white; padding: 15px 20px; border-radius: 8px;
            margin-bottom: 15px; display: flex; align-items: center; gap: 12px;
            box-shadow: 0 2px 10px rgba(183,28,28,0.3); font-size: 16px;
        }}
        .lingang-banner .lingang-icon {{ font-size: 22px; }}
        .lingang-banner .lingang-title-text {{ font-weight: bold; font-size: 18px; }}
        .lingang-banner .lingang-count {{
            margin-left: auto; background: rgba(255,255,255,0.25);
            padding: 2px 12px; border-radius: 12px; font-size: 13px;
        }}
        .bid-card.lingang {{
            border-left: 5px solid #c62828;
            background: linear-gradient(to right, #fff8e1 0%, #ffffff 40%);
            box-shadow: 0 2px 8px rgba(198,40,40,0.12);
        }}
        .bid-card.lingang:hover {{
            box-shadow: 0 4px 16px rgba(198,40,40,0.2);
            border-left-color: #b71c1c;
        }}
        .lingang-badge {{
            background: #c62828; color: white; padding: 2px 12px;
            border-radius: 12px; font-size: 11px; font-weight: bold;
            white-space: nowrap;
        }}
        .lingang-reason {{
            margin-top: 8px; padding: 6px 10px; background: #fff3e0;
            border-radius: 4px; font-size: 12px; color: #e65100;
            border: 1px dashed #ffb74d;
        }}
        .lingang-label {{ font-weight: bold; }}
        .lingang-keywords {{ color: #bf360c; }}
        .stat-card.lingang .num {{ color: #c62828; }}
        .footer {{ text-align: center; padding: 20px; color: #999; font-size: 12px; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>东方有线网络有限公司 - 投标机会监控报告 v2.0</h1>
        <div class="subtitle">中国广电网络股份有限公司上海分公司 | 广电+通信融合运营商 | 第四大基础电信运营商</div>
        <div class="meta-bar">
            <span>报告日期: {now_str}</span>
            <span>抓取范围: 最近 {days} 天</span>
            <span>数据来源: {sources}</span>
            <span>★ 临港新片区项目: {lingang_count} 个</span>
        </div>
    </div>
    <div class="container">
        <div class="stats-bar">
            <div class="stat-card">
                <div class="num">{total}</div>
                <div class="label">匹配项目总数</div>
            </div>
            <div class="stat-card high">
                <div class="num">{high_match}</div>
                <div class="label">极高匹配度</div>
            </div>
            <div class="stat-card mid">
                <div class="num">{mid_match}</div>
                <div class="label">高匹配度</div>
            </div>
            <div class="stat-card">
                <div class="num">{low_match}</div>
                <div class="label">中等匹配度</div>
            </div>
            <div class="stat-card source">
                <div class="num">{zfcg_count}</div>
                <div class="label">上海政府采购网</div>
            </div>
            <div class="stat-card source">
                <div class="num">{ccgp_count}</div>
                <div class="label">中国政府采购网</div>
            </div>
            <div class="stat-card lingang">
                <div class="num">{lingang_count}</div>
                <div class="label">★ 临港新片区项目</div>
            </div>
        </div>
        {items_html}
    </div>
    <div class="footer">
        <p>本报告由东方有线投标监控程序 v2.0 自动生成 | 临港新片区分公司专用</p>
        <p>数据来源: 中国政府采购网(ccgp.gov.cn) + 上海市政府采购网(zfcg.sh.gov.cn) | 仅供参考，具体投标信息以官方公告为准</p>
    </div>
</body>
</html>"""


# ============================================================
# 主程序
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="东方有线网络有限公司 - 上海招投标信息每日监控"
    )
    parser.add_argument("--days", type=int, default=2, help="抓取最近N天的公告（范围1-10，默认2天）")
    parser.add_argument("--output", type=str, default="", help="输出HTML文件路径")
    parser.add_argument("--no-open", action="store_true", help="不自动在浏览器中打开报告")
    parser.add_argument("--verbose", "-v", action="store_true", help="显示详细日志")
    parser.add_argument(
        "--source", type=str, default="all", choices=["all", "ccgp", "zfcg"],
        help="数据源: all=全部(默认), ccgp=中国政府采购网, zfcg=上海政府采购网"
    )
    args = parser.parse_args()

    # [v2.0] 天数校验：1-10
    if args.days < 1:
        print("[!] 天数不能小于1，已自动调整为1")
        args.days = 1
    elif args.days > 10:
        print("[!] 天数不能超过10，已自动调整为10")
        args.days = 10

    print("=" * 60)
    print("  东方有线网络有限公司 - 投标机会每日监控 v2.0")
    print("  China Broadcasting Network Shanghai Branch")
    print("  数据源: 中国政府采购网 + 上海市政府采购网")
    print("  ★ 临港新片区分公司重点项目智能识别")
    print("=" * 60)
    print(f"\n[*] 抓取最近 {args.days} 天的公告")
    print(f"[*] 数据源: {args.source}")
    print(f"[*] 开始时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    matcher = KeywordMatcher()
    lingang_detector = LingangDetector()
    all_items = []
    all_scraped = []  # [v2.0] 保留所有抓取结果，用于临港二次扫描
    source_names = []

    # 1. 中国政府采购网
    if args.source in ("all", "ccgp"):
        source_names.append("中国政府采购网")
        try:
            ccgp_scraper = CcgpScraper(days=args.days, verbose=args.verbose)
            ccgp_items = ccgp_scraper.scrape()
            all_scraped.extend(ccgp_items)
            print(f"\n[*] [中国政府采购网] 关键词+临港检测中...")
            matched = 0
            for item in ccgp_items:
                kw_match = matcher.filter_and_score(item)
                lg_match = lingang_detector.detect(item)
                if kw_match or lg_match:
                    all_items.append(item)
                    matched += 1
            print(f"[*] [中国政府采购网] 匹配: {matched}/{len(ccgp_items)} 条")
        except Exception as e:
            print(f"\n[!] 中国政府采购网抓取出错: {e}")
            traceback.print_exc()

    # 2. 上海市政府采购网
    if args.source in ("all", "zfcg"):
        source_names.append("上海政府采购网")
        try:
            zfcg_scraper = ZfcgScraper(days=args.days, verbose=args.verbose)
            zfcg_items = zfcg_scraper.scrape()
            all_scraped.extend(zfcg_items)
            print(f"\n[*] [上海政府采购网] 关键词+临港检测中...")
            matched = 0
            for item in zfcg_items:
                kw_match = matcher.filter_and_score(item)
                lg_match = lingang_detector.detect(item)
                if kw_match or lg_match:
                    all_items.append(item)
                    matched += 1
            print(f"[*] [上海政府采购网] 匹配: {matched}/{len(zfcg_items)} 条")
        except Exception as e:
            print(f"\n[!] 上海政府采购网抓取出错: {e}")
            traceback.print_exc()

    # 去重（跨数据源，按标题去重）
    seen_titles = set()
    unique_matched = []
    for item in all_items:
        # 标准化标题用于去重
        norm_title = re.sub(r'\s+', '', item.title).lower()
        if norm_title not in seen_titles:
            seen_titles.add(norm_title)
            unique_matched.append(item)

    # 按匹配度排序
    unique_matched.sort(key=lambda x: x.match_score, reverse=True)

    # [v2.0] 临港新片区统计（检测已在匹配阶段完成）
    lingang_matched = sum(1 for i in unique_matched if i.is_lingang)

    # [v2.0] 排序：临港项目置顶，其次按匹配度
    unique_matched.sort(key=lambda x: (x.is_lingang, x.match_score), reverse=True)

    print(f"\n[*] 合并去重后匹配项目: {len(unique_matched)} 条")
    if lingang_matched > 0:
        print(f"[★] 其中临港新片区项目: {lingang_matched} 条")

    # 生成报告
    if not args.output:
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        args.output = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            f"bid_report_{today}.html"
        )

    source_str = " + ".join(source_names) if source_names else "无"
    html_content = generate_html_report(unique_matched, args.days, source_str)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"\n[OK] 报告已生成: {args.output}")
    print(f"[*] 匹配项目: {len(unique_matched)} 个")

    if unique_matched:
        print("\n[*] 匹配项目摘要:")
        for i, item in enumerate(unique_matched[:15], 1):
            lingang_mark = " ★临港" if item.is_lingang else ""
            print(f"  {i}. [{item.match_level}]{lingang_mark} [{item.source}] {item.title}")
            if item.purchaser:
                print(f"     采购人: {item.purchaser}")
            if item.budget:
                print(f"     预算: {item.budget}")
            if item.is_lingang:
                print(f"     ★ 临港命中: {item.lingang_reason}")
            print(f"     日期: {item.date} | 关键词({item.match_score}): {', '.join(item.keyword_hits[:5])}")

    if not args.no_open:
        import webbrowser
        print(f"\n[*] 正在打开浏览器...")
        webbrowser.open(f"file:///{os.path.abspath(args.output)}")

    print(f"\n[*] 完成! 时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
