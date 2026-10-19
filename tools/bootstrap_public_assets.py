"""Render original geometric glyphs. No external or game artwork is read."""
from pathlib import Path
import json
import math
import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]

def render(path, kind):
    image=QImage(128,128,QImage.Format_ARGB32); image.fill(Qt.transparent)
    p=QPainter(image); p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor('#d7b97a'),4)); p.setBrush(QColor('#252830'))
    if kind in {'equipment_bg','boon_glass','item_glass','equipment_card_bg','empty_card_bg'}:
        p.fillRect(image.rect(),QColor('#1c2027'))
        p.setPen(QPen(QColor('#37313d'),1))
        for x in range(-128,256,24): p.drawLine(x,0,x+128,128)
    elif kind in {'equipment_card_frame','empty_card_frame','boon_outline'}:
        p.setBrush(Qt.NoBrush); p.drawRoundedRect(QRectF(3,3,122,122),7,7)
    elif kind=='coins':
        for x,y in [(40,72),(72,78),(62,44)]:
            p.setBrush(QColor('#ab813c'));p.drawEllipse(QRectF(x-22,y-22,44,44));p.drawLine(x,y-13,x,y+13)
    elif kind=='souls':
        p.setBrush(QColor('#e6e4d8'));p.drawEllipse(QRectF(37,18,54,78));p.drawLine(64,95,64,116)
        p.drawLine(22,63,106,63)
    elif kind=='skull':
        p.setPen(QPen(QColor('#f2ede1'),5));p.setBrush(QColor('#f2ede1'))
        p.drawEllipse(QRectF(26,17,76,68));p.drawRect(QRectF(43,69,42,37))
        p.setBrush(QColor('#252830'));p.setPen(Qt.NoPen)
        p.drawEllipse(QRectF(39,43,20,23));p.drawEllipse(QRectF(69,43,20,23))
        for x in [52,64,76]:p.drawRect(QRectF(x,88,4,18))
    elif kind in {'portrait','portrait_azrael','angel'}:
        p.drawEllipse(QRectF(16,16,96,96));p.drawEllipse(QRectF(48,32,32,32))
        p.drawPolygon(QPolygonF([QPointF(64,69),QPointF(31,99),QPointF(97,99)]))
    elif kind in {'armor_head','armor_body','armor_arms','armor_legs','shield'}:
        p.drawPolygon(QPolygonF([QPointF(64,16),QPointF(105,32),QPointF(99,83),QPointF(64,113),QPointF(29,83),QPointF(23,32)]))
        p.drawLine(64,25,64,99)
    elif 'weapon' in kind or 'twohand' in kind:
        p.drawPolygon(QPolygonF([QPointF(91,19),QPointF(89,47),QPointF(49,87),QPointF(39,77),QPointF(79,37)]))
        p.drawLine(29,99,48,80);p.drawLine(29,67,61,99)
    elif kind in {'amulet','trinket','ring'}:
        p.drawEllipse(QRectF(28,28,72,72));p.drawEllipse(QRectF(40,40,48,48))
        p.setBrush(QColor('#a44d75'));p.drawEllipse(QRectF(51,15,26,26))
    elif 'consumable' in kind or 'flask' in kind:
        p.drawRoundedRect(QRectF(37,43,54,65),12,12);p.drawRect(QRectF(49,18,30,25));p.drawLine(46,73,82,73)
    else:
        pts=[QPointF(64+45*math.cos(i*math.pi/4),64+45*math.sin(i*math.pi/4)) for i in range(8)]
        p.drawPolygon(QPolygonF(pts));p.drawLine(64,32,64,96);p.drawLine(32,64,96,64)
    p.end();path.parent.mkdir(parents=True,exist_ok=True)
    if not image.save(str(path)): raise RuntimeError('Could not save '+str(path))

def main():
    app=QApplication.instance() or QApplication([])
    data=json.loads((ROOT/'data/game_data.json').read_text('utf-8'))
    records=list(data['items'].values())+data['blessings']+list(data['angels'].values())
    paths={r['icon'] for r in records}|{v for v in data['ui_assets'].values() if v.endswith('.png')}
    for name in sorted(paths): render(ROOT/name,Path(name).stem)
    # Qt's own ICO writer is sufficient; no Pillow runtime dependency.
    appicon=QImage(str(ROOT/'assets/public/blessing.png'))
    if not appicon.save(str(ROOT/'assets/ui/app.ico')): raise RuntimeError('ICO writer unavailable')
    print('Generated',len(paths)+1,'original public icons.')

if __name__=='__main__': main()
