# -*- coding: utf-8 -*-
# qt_align_check.py —— 检查 Qt 富文本渲染后消息对齐是否保留
import os
import sys
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from PyQt6.QtWidgets import QApplication, QTextBrowser
import ai_chat as ai

app = QApplication(sys.argv)
tb = QTextBrowser()
tb.setHtml(ai._msg_html([
    {'role': 'user', 'content': 'hi-user', 'ts': 't'},
    {'role': 'assistant', 'content': 'yo-ai', 'ts': 't'},
], '', None))
doc = tb.document()
from PyQt6.QtCore import Qt
ok_user = ok_ai = False
for i in range(doc.blockCount()):
    b = doc.findBlockByNumber(i)
    txt = b.text()
    al = b.blockFormat().alignment()
    if 'hi-user' in txt:
        ok_user = al == Qt.AlignmentFlag.AlignRight
        print('user block align:', al, 'isRight:', ok_user)
    if 'yo-ai' in txt:
        ok_ai = al == Qt.AlignmentFlag.AlignLeft
        print('ai block align:', al, 'isLeft(或默认):', al in (Qt.AlignmentFlag.AlignLeft, Qt.AlignmentFlag.AlignLeading))
print('user right:', ok_user, 'ai left:', ok_ai)
sys.exit(0 if (ok_user and ok_ai) else 1)
