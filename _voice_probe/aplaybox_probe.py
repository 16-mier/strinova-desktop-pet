# -*- coding: utf-8 -*-
"""探测模之屋登录方式与卡拉彼丘模型页"""
import re
import json
import urllib.request

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36'


def get(url):
    req = urllib.request.Request(url, headers={
        'User-Agent': UA,
        'Referer': 'https://www.aplaybox.com/',
    })
    return urllib.request.urlopen(req, timeout=25)


def main():
    # 1) 主页登录线索
    html = get('https://www.aplaybox.com/').read().decode('utf-8', 'ignore')
    print('home len:', len(html))
    kws = ['bilibili', 'qqLogin', 'passport', 'sso', 'loginBy', '手机号', '登录']
    for kw in kws:
        ms = re.findall(r'[^"\'<>]{0,40}%s[^"\'<>]{0,60}' % kw, html, re.I)
        if ms:
            print('[%s]' % kw, ms[:4])

    # 2) 卡拉彼丘官方账号模型列表接口（常见分页结构）
    for u in [
        'https://www.aplaybox.com/u/288404078/model',
        'https://www.aplaybox.com/api/u/288404078/model?page=1',
        'https://www.aplaybox.com/api/v1/u/288404078/models?page=1',
    ]:
        try:
            r = get(u)
            txt = r.read().decode('utf-8', 'ignore')
            print('\nURL', u, '-> status', r.status, 'len', len(txt))
            print('head:', txt[:300].replace('\n', ' '))
        except Exception as e:
            print('\nURL', u, '-> FAIL', e)


if __name__ == '__main__':
    main()
