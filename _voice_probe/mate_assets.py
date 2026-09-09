# -*- coding: utf-8 -*-
"""抓 Mate-Engine X3.3.0 release assets 完整列表"""
import re
import urllib.request

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36'


def get(url):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    return urllib.request.urlopen(req, timeout=30).read().decode('utf-8', 'ignore')


def main():
    html = get('https://github.com/shinyflvre/Mate-Engine/releases/expanded_assets/Public-Release-X3.3.0')
    links = re.findall(r'href="(/shinyflvre/Mate-Engine/releases/download/[^"]+)"', html)
    seen = []
    for l in dict.fromkeys(links):
        name = l.rsplit('/', 1)[-1]
        seen.append((name, l))
        print(name)
    print('count:', len(seen))


if __name__ == '__main__':
    main()