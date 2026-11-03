"""Small explicit alias registry for independent place checks, not browser steps."""
from dataclasses import dataclass
import re

CITIES = {
    '深圳': ('Shenzhen', ['SZX']), '上海': ('Shanghai', ['PVG', 'SHA']),
    '北京': ('Beijing', ['PEK', 'PKX']), '广州': ('Guangzhou', ['CAN']),
    '杭州': ('Hangzhou', ['HGH']), '厦门': ('Xiamen', ['XMN']),
    '成都': ('Chengdu', ['CTU', 'TFU']), '重庆': ('Chongqing', ['CKG']),
    '南京': ('Nanjing', ['NKG']), '武汉': ('Wuhan', ['WUH']),
    '西安': ("Xi'an", ['XIY']), '长沙': ('Changsha', ['CSX']),
    '郑州': ('Zhengzhou', ['CGO']), '昆明': ('Kunming', ['KMG']),
    '三亚': ('Sanya', ['SYX']), '海口': ('Haikou', ['HAK']),
    '青岛': ('Qingdao', ['TAO']), '天津': ('Tianjin', ['TSN']),
    '福州': ('Fuzhou', ['FOC']), '宁波': ('Ningbo', ['NGB']),
    '香港': ('Hong Kong', ['HKG']), '澳门': ('Macau', ['MFM']),
    '新加坡': ('Singapore', ['SIN', 'XSP']), '东京': ('Tokyo', ['HND', 'NRT']),
    '首尔': ('Seoul', ['ICN', 'GMP']), '曼谷': ('Bangkok', ['BKK', 'DMK']),
    '吉隆坡': ('Kuala Lumpur', ['KUL', 'SZB']), '伦敦': ('London', ['LHR', 'LGW', 'STN', 'LTN', 'LCY', 'SEN']),
}
AIRPORT_ALIASES = {
    '深圳宝安': ('SZX', 'Shenzhen'), '深圳宝安机场': ('SZX', 'Shenzhen'),
    '上海浦东': ('PVG', 'Shanghai'), '浦东机场': ('PVG', 'Shanghai'), '上海浦东机场': ('PVG', 'Shanghai'),
    '上海虹桥': ('SHA', 'Shanghai'), '虹桥机场': ('SHA', 'Shanghai'), '上海虹桥机场': ('SHA', 'Shanghai'),
    '北京首都': ('PEK', 'Beijing'), '北京首都机场': ('PEK', 'Beijing'),
    '北京大兴': ('PKX', 'Beijing'), '北京大兴机场': ('PKX', 'Beijing'),
    '成都天府': ('TFU', 'Chengdu'), '成都双流': ('CTU', 'Chengdu'),
}


def normalized(value):
    return re.sub(r'[\W_]+', '', value.casefold())


@dataclass
class Location:
    original: str
    query: str
    city: str
    airports: list[str]
    kind: str

    def matches_selected(self, display):
        if self.kind == 'airport':
            return bool(re.search(r'\b' + re.escape(self.query) + r'\b', display, re.I)) and 'All airports' not in display
        return normalized(display) == normalized(self.city + ' All airports')

    def matches_airport(self, display):
        codes = set(re.findall(r'\b[A-Z]{3}\b', display))
        if self.airports and codes:
            return bool(codes.intersection(self.airports))
        return normalized(self.city) in normalized(display)


def location(raw):
    s = raw.strip()
    if s in AIRPORT_ALIASES:
        code, city = AIRPORT_ALIASES[s]
        return Location(s, code, city, [code], 'airport')
    for chinese, (english, codes) in CITIES.items():
        if normalized(s) in [normalized(chinese), normalized(english)]:
            return Location(s, english, english, list(codes), 'city')
    if re.fullmatch(r'[A-Za-z]{3}', s):
        code = s.upper()
        city = next((city for city, codes in CITIES.values() if code in codes), code)
        return Location(s, code, city, [code], 'airport')
    if s.isascii() and len(s) >= 4:
        return Location(s, s, s, [], 'city')
    raise ValueError(f'Location "{raw}" cannot be verified; provide an English city name or three-letter airport code')
