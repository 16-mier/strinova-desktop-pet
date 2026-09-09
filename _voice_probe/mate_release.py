# -*- coding: utf-8 -*-
"""抓 Mate-Engine 最新 release 的 zip 下载链接"""
import re
import urllib.request

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36'


def main():
    req = urllib.request.Request(
        'https://github.com/shinyflvre/Mate-Engine/releases/latest',
        headers={'User-Agent': UA})
    r = urllib.request.urlopen(req, timeout=30)
    url = r.geturl()
    print('latest url:', url)
    html = r.read().decode('utf-8', 'ignore')
    zips = re.findall(r'href="(/shinyflvre/Mate-Engine/releases/download/[^"]+\.zip)"', html)
    for z in dict.fromkeys(zips):
        print('zip:', 'https://github.com' + z)
    if not zips:
        # 暴露 release-assets 临时链接
        arts = re.findall(r'href="(/shinyflvre/Mate-Engine/releases/expanded_assets/[^"]+)"', html)
        print('expanded:', arts[:3])


if __name__ == '__main__':
    main()