# -*- coding: utf-8 -*-
"""
年份选中格识别。

i茅台 详情页「规格」区有 7 个年份格，页面用**红色描边 + 红字**标记当前
选中的那一格，其余是灰字 + 浅灰描边。本模块把「哪种颜色算选中」的判断
集中到一处，供校准建档与运行时共用，避免再靠 constants 猜页面默认年份。

实测（1200x2652 抓图）：
    选中格 2026：最红像素 (217, 31, 45) → R - max(G,B) = 172
                 描边像素 (179, 42, 50) → 129
    未选中格 2024：最红像素 (255,255,255) → 0
                   灰字最暗 (102,102,102) → 0

所以阈值取 config.YEAR_RED_MIN（90）：选中格远超，未选中格恒为 0。

用法：
    # 建档/武装阶段（非点击关键路径）调用一次即可
    year = detect_selected_year(controls.get(u"year_cells"), bridge.max_red_in_regions)
    if year:
        controls[u"default_year"] = year
"""

from config import YEAR_RED_MIN


def redness(rgb):
    """颜色的「红度」：R - max(G, B)；取不到返回 -1。"""
    if not rgb:
        return -1
    red, green, blue = rgb
    return int(red) - max(int(green), int(blue))


def _valid_bounds(record):
    """
    从档案记录里取可用 bounds，返回 (left, top, right, bottom) 或 None。

    档案里年份格记录形如 {"bounds": [l, t, r, b], "center": [x, y]}；
    bounds 缺失、长度不对或面积过小时一律视为不可用（不能拿坏档案去取色，
    否则会把别的格子/空白区域采进来）。
    """
    if not record:
        return None
    bounds = record.get(u"bounds")
    if not bounds or len(bounds) != 4:
        return None
    try:
        left, top, right, bottom = [int(value) for value in bounds]
    except (TypeError, ValueError):
        return None
    if right - left < 8 or bottom - top < 8:
        return None
    return (left, top, right, bottom)


def build_regions(year_cells):
    """
    把 {年份: 档案记录} 转成 (年份列表, 区域列表)，跳过无效项。

    区域内缩 1px：既保留贴边的那条描边，又避免相邻格边框串色。
    """
    years = []
    regions = []
    if not year_cells:
        return years, regions
    for year in sorted(year_cells.keys()):
        bounds = _valid_bounds(year_cells[year])
        if bounds is None:
            continue
        left, top, right, bottom = bounds
        years.append(u"%s" % year)
        regions.append((left + 1, top + 1, right - 1, bottom - 1))
    return years, regions


def detect_selected_year(year_cells, sampler, red_min=None):
    """
    识别当前选中的年份，返回 "2026" 这样的字符串；识别不出返回 None。

    sampler(regions) -> [(r, g, b) 或 None, ...]，必须**一次取完**：
    取色要截图，逐格调用会慢一个数量级，只能放在建档/武装这类
    非点击关键路径上。
    """
    threshold = YEAR_RED_MIN if red_min is None else int(red_min)
    years, regions = build_regions(year_cells)
    if not regions or not callable(sampler):
        return None
    try:
        colors = sampler(regions)
    except Exception:
        return None
    if not colors or len(colors) != len(regions):
        return None

    hits = []
    for year, rgb in zip(years, colors):
        if redness(rgb) >= threshold:
            hits.append(year)
    # 必须「有且只有一个」年份格达标：0 个说明不是这一页/取色失败，
    # 多个说明档案 bounds 串格了。两种都宁可返回 None 走兜底常量，
    # 也不能赌一个——赌错就是下错年份的货。
    if len(hits) != 1:
        return None
    return hits[0]


def detect_with_bridge(bridge, year_cells, logger=None):
    """
    用 A11yBridge 做一次检测；失败时返回 None 并可选记一行日志。

    旧 APK 没有 maxRedInRegions 时 bridge 会返回 None，这里一并降级，
    调用方退回 config.DETAIL_DEFAULT_YEAR。
    """
    sampler = getattr(bridge, "max_red_in_regions", None)
    if not callable(sampler):
        return None
    year = detect_selected_year(year_cells, sampler)
    if year is not None and logger is not None:
        try:
            logger.log(u"识别到详情页默认选中年份：%s" % year)
        except Exception:
            pass
    return year
