# -*- coding: utf-8 -*-
"""查模之屋前端 JS 里的登录/下载接口线索"""
import re
import urllib.request

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36'


def get(url):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    return urllib.request.urlopen(req, timeout=25).read()


def main():
    html = get('https://www.aplaybox.com/').decode('utf-8', 'ignore')
    # 找 JS 入口
    js = re.findall(r'src=["\']([^"\']+\.js[^"\']*)["\']', html)
    print('js files:', js[:10])
    # 找接口前缀线索（写在 html 的 json 配置里）
    cfg = re.findall(r'window\.\w+\s*=\s*(\{.{0,800}?\})', html)
    for c in cfg[:5]:
        print('cfg:', c[:400].replace('\n', ' '))
    # 直接找 bilibili / download 等
    for kw in ['bilibili', 'BILIBILI', 'download', '/api/']:
        ms = re.findall(r'.{0,50}%s.{0,80}' % kw, html)
        if ms:
            print('[%s]' % kw, ms[:3])


if __name__ == '__main__':
    main()
