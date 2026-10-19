"""Crimson Moon Save Editor: native portable desktop interface."""
from __future__ import annotations

import argparse
import html
import json
import os
from pathlib import Path
import re
import sys
import traceback

from PySide6.QtCore import Qt, QSize, QRectF, QTimer, QSettings, QUrl, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QBrush, QPixmap, QIcon, QFont, QFontDatabase, QLinearGradient, QRadialGradient, QDesktopServices, QShortcut, QKeySequence, QPainterPath
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton,
    QHBoxLayout, QVBoxLayout, QGridLayout, QComboBox, QLineEdit, QListWidget, QListWidgetItem,
    QStackedWidget, QScrollArea, QSpinBox, QFileDialog, QMessageBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QDialog, QDialogButtonBox, QTextBrowser)

from crimson import __version__
from crimson.catalogue import Catalogue, TYPE_SLOTS, clean_enum, format_number
from crimson.editing import ATTRIBUTES, equipment_entry, backpack
from crimson.gvas import SaveDocument, SaveError
from crimson.service import currency_status
from crimson.storage import EditorSession, TransactionStore, find_saves

from crimson.resource_paths import resource_root
ROOT = resource_root()
QUALITY = ['Common', 'Uncommon', 'Rare', 'Epic', 'Legendary']
COLORS = {'Common':'#a7a9ae', 'Uncommon':'#62af8a', 'Rare':'#638fd1', 'Epic':'#bd79df', 'Legendary':'#dfb35c'}
CARD_COLORS = {'Common':('#525252','#343434'),'Uncommon':('#285c36','#15371e'),
               'Rare':('#2654a2','#152951'),'Epic':('#6d207e','#360c40'),'Legendary':('#996816','#4c310c')}

EN = {
 'equipment':'Equipment', 'blessings':'Blessings', 'journey':'Journey', 'character':'Character', 'backups':'Backups',
 'open':'Open save', 'detect':'Find saves', 'save':'Apply to save', 'export':'Export copy', 'undo':'Undo', 'redo':'Redo',
 'money':'Coins', 'souls':'Souls', 'prepare':'Prepare changes', 'prepared':'Changes prepared in memory.',
 'empty':'Open a character save to begin', 'empty_note':'Your character, equipment and journey will appear here.',
 'gear_title':'THE NEPHILIM', 'gear_sub':'Select a slot to inspect or replace equipment.', 'catalog':'ITEM CATALOG',
 'search':'Search by name or effect…', 'compare':'COMPARISON', 'current':'Current', 'selected':'Selected', 'attribute':'Attribute',
 'delta':'Difference', 'base_note':'Base definition values. Final stats depend on quality and game scaling.',
 'replace':'Replace selected item', 'quality_only':'Change quality', 'quality':'Quality', 'description':'Description',
 'Head':'Helmet', 'Body':'Armor', 'Legs':'Legs', 'Arms':'Gauntlets', 'RightHand':'Weapon', 'LeftHand':'Shield', 'Trinket':'Ring', 'Amulet':'Medallion',
 'Common':'Common', 'Uncommon':'Uncommon', 'Rare':'Rare', 'Epic':'Epic', 'Legendary':'Legendary',
 'active_boons':'YOUR BLESSINGS', 'boon_sub':'Hover an icon to read its effect. Select a blessing to add or remove it.',
 'boon_catalog':'BLESSING CATALOG', 'add_boon':'Add blessing', 'remove_boon':'Remove selected blessing',
 'gear_effect':'Equipment effect', 'run_effect':'Journey blessing', 'all':'All', 'level':'Level', 'stacks':'Stacks',
 'journey_title':'CHOOSE YOUR PATH', 'journey_sub':'Change the saved position in the manual journey and its selected difficulty.',
 'stage':'Stage', 'section':'Section', 'difficulty':'Selected difficulty', 'missions':'Missions offered in this section',
 'journey_note':'The game uses this saved position when continuing the journey. This does not teleport a character inside an active mission.',
 'character_title':'CHARACTER', 'attributes':'ATTRIBUTES', 'currency_title':'COINS & SOULS', 'attribute_note':'Changing attributes does not recalculate XP, level or spent points.',
 'backup_title':'BACKUP HISTORY', 'backup_sub':'A verified backup is created automatically before each application or restore.',
 'restore':'Restore selected backup', 'folder':'Open backup folder', 'no_backups':'No backups for this character yet.',
 'ready':'Save loaded · no pending changes', 'pending':'pending changes', 'close_game':'Close the game before applying changes.',
 'discard':'Discard changes', 'discard_question':'Discard pending changes?', 'review':'Review changes',
 'apply_question':'Apply these changes to the character save? A backup will be created first.',
 'applied':'Save applied and verified. The original is available in Backups.', 'error':'Unable to complete the action',
 'experimental':'Experimental · save version 8', 'no_item':'No item in this slot', 'no_candidate':'Select an item in the catalog',
 'copy_saved':'Modified copy and original backups exported.', 'refresh':'Reload', 'reserved':'BACKPACK / RESERVE',
 'select_existing':'Choose an existing backpack instance to replace.', 'about':'ABOUT', 'effect':'Effect',
}
PT = {
 'equipment':'Equipamentos', 'blessings':'Bênçãos', 'journey':'Jornada', 'character':'Personagem', 'backups':'Backups',
 'open':'Abrir save', 'detect':'Detectar saves', 'save':'Aplicar no save', 'export':'Exportar cópia', 'undo':'Desfazer', 'redo':'Refazer',
 'money':'Moedas', 'souls':'Almas', 'prepare':'Preparar alterações', 'prepared':'Alterações preparadas em memória.',
 'empty':'Abra um save de personagem para começar', 'empty_note':'Seu personagem, equipamentos e jornada aparecerão aqui.',
 'gear_title':'O NEFILIM', 'gear_sub':'Selecione um espaço para inspecionar ou trocar o equipamento.', 'catalog':'CATÁLOGO DE ITENS',
 'search':'Pesquisar por nome ou efeito…', 'compare':'COMPARAÇÃO', 'current':'Atual', 'selected':'Selecionado', 'attribute':'Atributo',
 'delta':'Diferença', 'base_note':'Valores-base da definição. Os atributos finais dependem da qualidade e da escala do jogo.',
 'replace':'Substituir item selecionado', 'quality_only':'Alterar qualidade', 'quality':'Qualidade', 'description':'Descrição',
 'Head':'Elmo', 'Body':'Armadura', 'Legs':'Pernas', 'Arms':'Manoplas', 'RightHand':'Arma', 'LeftHand':'Escudo', 'Trinket':'Anel', 'Amulet':'Medalhão',
 'Common':'Comum', 'Uncommon':'Incomum', 'Rare':'Raro', 'Epic':'Épico', 'Legendary':'Lendário',
 'active_boons':'SUAS BÊNÇÃOS', 'boon_sub':'Passe o mouse sobre os ícones para ver os efeitos. Selecione uma bênção para adicionar ou remover.',
 'boon_catalog':'CATÁLOGO DE BÊNÇÃOS', 'add_boon':'Adicionar bênção', 'remove_boon':'Remover bênção selecionada',
 'gear_effect':'Efeito do equipamento', 'run_effect':'Bênção da jornada', 'all':'Todas', 'level':'Nível', 'stacks':'Acúmulos',
 'journey_title':'ESCOLHA SEU CAMINHO', 'journey_sub':'Altere a posição salva na jornada manual e a dificuldade escolhida.',
 'stage':'Etapa', 'section':'Fase', 'difficulty':'Dificuldade escolhida', 'missions':'Missões oferecidas nesta fase',
 'journey_note':'O jogo usa essa posição salva ao continuar a jornada. Isso não teletransporta o personagem dentro de uma missão em andamento.',
 'character_title':'PERSONAGEM', 'attributes':'ATRIBUTOS', 'currency_title':'MOEDAS E ALMAS', 'attribute_note':'Alterar atributos não recalcula experiência, nível ou pontos gastos.',
 'backup_title':'HISTÓRICO DE BACKUPS', 'backup_sub':'Um backup verificado é criado automaticamente antes de cada aplicação ou restauração.',
 'restore':'Restaurar backup selecionado', 'folder':'Abrir pasta de backups', 'no_backups':'Este personagem ainda não tem backups.',
 'ready':'Save carregado · nenhuma alteração pendente', 'pending':'alterações pendentes', 'close_game':'Feche o jogo antes de aplicar alterações.',
 'discard':'Descartar alterações', 'discard_question':'Descartar as alterações pendentes?', 'review':'Revisar alterações',
 'apply_question':'Aplicar estas alterações ao save do personagem? Um backup será criado antes.',
 'applied':'Save aplicado e conferido. O original está disponível em Backups.', 'error':'Não foi possível concluir a ação',
 'experimental':'Experimental · save versão 8', 'no_item':'Nenhum item neste espaço', 'no_candidate':'Selecione um item no catálogo',
 'copy_saved':'Cópia modificada e backups dos originais exportados.', 'refresh':'Recarregar', 'reserved':'MOCHILA / RESERVA',
 'select_existing':'Escolha uma instância existente da mochila para substituir.', 'about':'SOBRE', 'effect':'Efeito',
}

EXTRA = {
 'de':dict(equipment='Ausrüstung',blessings='Segnungen',journey='Reise',character='Charakter',backups='Sicherungen',open='Spielstand öffnen',save='Anwenden',money='Münzen',souls='Seelen',search='Suchen…',quality='Qualität',current='Aktuell',selected='Ausgewählt'),
 'es':dict(equipment='Equipamiento',blessings='Bendiciones',journey='Viaje',character='Personaje',backups='Copias',open='Abrir partida',save='Aplicar cambios',money='Monedas',souls='Almas',search='Buscar…',quality='Calidad',current='Actual',selected='Seleccionado'),
 'fr':dict(equipment='Équipement',blessings='Bénédictions',journey='Voyage',character='Personnage',backups='Sauvegardes',open='Ouvrir',save='Appliquer',money='Pièces',souls='Âmes',search='Rechercher…',quality='Qualité',current='Actuel',selected='Sélectionné'),
 'it':dict(equipment='Equipaggiamento',blessings='Benedizioni',journey='Viaggio',character='Personaggio',backups='Backup',open='Apri salvataggio',save='Applica',money='Monete',souls='Anime',search='Cerca…',quality='Qualità',current='Attuale',selected='Selezionato'),
 'ja':dict(equipment='装備',blessings='祝福',journey='旅',character='キャラクター',backups='バックアップ',open='セーブを開く',save='変更を適用',money='コイン',souls='ソウル',search='検索…',quality='品質',current='現在',selected='選択中'),
 'zh':dict(equipment='装备',blessings='祝福',journey='旅程',character='角色',backups='备份',open='打开存档',save='应用更改',money='金币',souls='灵魂',search='搜索…',quality='品质',current='当前',selected='已选择'),
}

STYLE = """
QWidget { background: #15171c; color: #d9d8d6; font-family: 'Segoe UI'; font-size: 13px; }
QMainWindow { background: #15171c; }
QFrame#sidebar { background: #101216; border-right: 1px solid #303036; }
QFrame#topbar { background: #191b20; border-bottom: 1px solid #303036; }
QFrame#card { background: #1c1e24; border: 1px solid #36343a; border-radius: 7px; }
QFrame#footer { background: #101216; border-top: 1px solid #36343a; }
QLabel { background: transparent; border: none; }
QLabel#title { font-family: 'Georgia'; font-size: 25px; color: #e2d5b9; letter-spacing: 2px; }
QLabel#eyebrow { color: #b79b6c; font-size: 11px; font-weight: 600; letter-spacing: 2px; }
QLabel#muted { color: #95959e; font-size: 12px; }
QPushButton { background: #25272e; border: 1px solid #414048; border-radius: 4px; padding: 8px 13px; color: #d9d8d6; }
QPushButton:hover { border-color: #b49560; background: #303038; }
QPushButton:pressed { background: #3b3430; }
QPushButton:disabled { color: #696970; border-color: #303139; background: #202127; }
QPushButton#primary { background: #a8824d; border-color: #c5a46f; color: #14151a; font-weight: 700; }
QPushButton#primary:hover { background: #c7a773; }
QPushButton#primary:disabled { background: #36312a; color: #77716a; border-color: #454036; }
QPushButton#nav { background: transparent; border: 0; border-left: 3px solid transparent; border-radius: 0; text-align: left; padding: 15px 17px; color: #93939e; }
QPushButton#nav:checked { background: #252326; color: #dec49a; border-left: 3px solid #c6a46a; }
QPushButton#nav:hover { background: #202126; color: #e0d3bd; }
QLineEdit, QSpinBox, QComboBox { background: #121419; border: 1px solid #3b3a42; border-radius: 4px; padding: 8px; selection-background-color: #685133; }
QLineEdit:focus, QSpinBox:focus, QComboBox:focus { border-color: #b99a68; }
QSpinBox { min-width: 95px; }
QComboBox::drop-down { border: 0; width: 22px; }
QComboBox QAbstractItemView { background: #202127; border: 1px solid #5c5143; selection-background-color: #41372c; }
QListWidget { background: #17191f; border: 1px solid #35343c; border-radius: 4px; outline: none; padding: 4px; }
QListWidget::item { padding: 7px; border-bottom: 1px solid #25272e; border-radius: 3px; }
QListWidget::item:selected { background: #393027; color: #e8d7b6; border: 1px solid #8b704a; }
QListWidget::item:hover { background: #26272f; }
QTableWidget { background: #17191e; border: 1px solid #36343c; gridline-color: #292a32; selection-background-color: #383128; }
QTableWidget::item { padding: 5px; }
QHeaderView::section { background: #24242b; color: #b9a583; padding: 7px; border: 0; border-bottom: 1px solid #454039; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { width: 8px; background: #17191e; margin: 0; }
QScrollBar::handle:vertical { background: #4e4944; border-radius: 4px; min-height: 28px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QToolTip { color: #e1ddda; background: #1a191c; border: 1px solid #a38960; padding: 12px; font-size: 13px; }
QTextBrowser { background: #17191f; border: 1px solid #38363d; padding: 12px; }
"""

def label(text, kind='', wrap=False):
    w=QLabel(text); w.setWordWrap(wrap)
    if kind: w.setObjectName(kind)
    return w

def button(text, callback, primary=False):
    w=QPushButton(text); w.setCursor(Qt.PointingHandCursor); w.clicked.connect(callback)
    if primary: w.setObjectName('primary')
    return w

def card():
    w=QFrame(); w.setObjectName('card'); return w

def plain(value):
    return re.sub(r'<[^>]+>', '', str(value or '')).replace('&nbsp;', ' ')


class Moon(QWidget):
    def __init__(self):
        super().__init__(); self.setFixedSize(56,56)
    def paintEvent(self,e):
        p=QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor('#bda06a'),1)); p.drawEllipse(QRectF(5,5,46,46))
        p.setBrush(QColor('#bda06a')); p.setPen(Qt.NoPen); p.drawEllipse(QRectF(15,12,27,31))
        p.setBrush(QColor('#101216')); p.drawEllipse(QRectF(23,8,25,29))
        p.setBrush(QColor('#8d373a')); p.drawEllipse(QRectF(25,41,5,5))


class SkullDifficulty(QWidget):
    valueChanged=Signal(int)
    def __init__(self,translator,modes=None):
        super().__init__(); self.t=translator; self.modes=modes or [{'skulls':i+1,'raw_value':15*i,'names':{}} for i in range(5)]; self._value=0
        v=QVBoxLayout(self); v.setContentsMargins(0,0,0,0); v.setSpacing(8); row=QHBoxLayout(); row.setSpacing(5); self.buttons=[]
        self.white=QPixmap(str(ROOT/'assets/ui/skull.png')); self.gray=QPixmap(self.white)
        if not self.gray.isNull():
            p=QPainter(self.gray); p.setCompositionMode(QPainter.CompositionMode_SourceIn); p.fillRect(self.gray.rect(),QColor('#59595b')); p.end()
        for i,mode in enumerate(self.modes):
            b=button('',lambda checked=False,value=mode['raw_value']:self.choose(value)); b.setFixedSize(43,43); b.setIconSize(QSize(33,33)); b.setAccessibleName(str(mode['skulls'])+' '+self.t('difficulty')); row.addWidget(b); self.buttons.append(b)
        row.addStretch(); v.addLayout(row); self.caption=label('','muted',True); v.addWidget(self.caption); self.sync()
    def choose(self,value): self.setValue(value); self.valueChanged.emit(value)
    def setValue(self,value): self._value=int(value); self.sync()
    def value(self):return self._value
    def setRange(self,minimum,maximum):pass  # Preserve non-preset values without rounding.
    def sync(self):
        mode=next((m for m in self.modes if m['raw_value']==self._value),None); count=mode['skulls'] if mode else 0
        for i,b in enumerate(self.buttons):
            b.setIcon(QIcon(self.white if i<count else self.gray)); b.setStyleSheet('QPushButton { background:transparent; border:1px solid '+('#9f8256' if mode and i==count-1 else 'transparent')+'; padding:3px; } QPushButton:hover { border-color:#c3a26e; }')
            lang=self.property('language') or 'pt'; names=self.modes[i].get('names',{}); desc=self.modes[i].get('descriptions',{}); name=names.get(lang) or names.get('en') or str(i+1)
            b.setToolTip('<div style="width:320px"><b>'+html.escape(name)+'</b><p>'+html.escape(desc.get(lang) or desc.get('en') or '').replace('\n','<br>')+'</p></div>')
        names=mode.get('names',{}) if mode else {}; lang=self.property('language') or 'pt'
        self.caption.setText((names.get(lang) or names.get('en') or str(count)+' / 5') if mode else self.t('custom_difficulty').format(value=self._value))


class MissionStep(QPushButton):
    def __init__(self,number,callback):
        super().__init__(); self.number=number; self.setCheckable(True); self.setFixedSize(64,78); self.setCursor(Qt.PointingHandCursor); self.clicked.connect(callback)
    def paintEvent(self,event):
        p=QPainter(self); p.setRenderHint(QPainter.Antialiasing); complete=bool(self.property('complete'))
        p.setBrush(QColor('#762e30') if self.isChecked() or complete else QColor('#232228')); p.setPen(QPen(QColor('#d0b080') if self.isChecked() else QColor('#8d7151'),2 if self.isChecked() else 1)); p.drawEllipse(QRectF(10,4,44,44))
        p.setPen(QPen(QColor('#e9e2d5') if self.isChecked() or complete else QColor('#a49e93'),3))
        if complete:
            p.drawLine(22,24,29,32); p.drawLine(29,32,44,16)
        else:
            pin=QPainterPath(); pin.moveTo(32,39); pin.cubicTo(24,29,19,22,23,16); pin.cubicTo(27,8,38,8,42,16); pin.cubicTo(47,23,40,32,32,39); p.drawPath(pin); p.drawEllipse(QRectF(28,16,9,9))
        p.setPen(QColor('#e0c697') if self.isChecked() else QColor('#9c9387')); p.setFont(QFont('Georgia',11)); p.drawText(QRectF(0,56,64,18),Qt.AlignCenter,self.number)


class GearIcon(QPushButton):
    def __init__(self, title, icon='', quality='Common', round_icon=False, count=None):
        super().__init__(); self.title=title; self.art=QPixmap(str(ROOT/icon)) if icon else QPixmap()
        self.quality=quality; self.round_icon=round_icon; self.count=count; self.setFixedSize(88,103)
        self.pattern=QPixmap(str(ROOT/'assets/ui/boon_glass.png'))
        if not self.pattern.isNull():
            tint=QPainter(self.pattern); tint.setCompositionMode(QPainter.CompositionMode_SourceIn); tint.fillRect(self.pattern.rect(),QColor('#120d16')); tint.end()
        self.setCheckable(True); self.setCursor(Qt.PointingHandCursor); self.setAccessibleName(title)
    def paintEvent(self,e):
        p=QPainter(self); p.setRenderHint(QPainter.Antialiasing); p.scale(self.width()/88,self.height()/103); color=QColor(COLORS.get(self.quality,COLORS['Common']))
        r=QRectF(3,2,82,82); grad=QLinearGradient(0,0,85,85)
        bright,dark=CARD_COLORS.get(self.quality,CARD_COLORS['Common']); grad.setColorAt(0,QColor(bright)); grad.setColorAt(1,QColor(dark))
        p.setBrush(grad); p.setPen(QPen(QColor('#e3c58b') if self.isChecked() or self.underMouse() else QColor('#927c58'),2.3 if self.isChecked() else 1.6))
        if self.round_icon: p.drawEllipse(r)
        else: p.drawRect(r)
        if not self.pattern.isNull() and not self.round_icon:
            p.save(); p.setClipRect(r.adjusted(1,1,-1,-1)); p.setOpacity(.75); p.drawPixmap(-14,-15,116,116,self.pattern); p.restore()
        p.setPen(QPen(QColor('#261c2a'),.8)); p.drawEllipse(QRectF(13,12,62,62))
        if not self.art.isNull(): p.drawPixmap(9,8,70,70,self.art)
        else:
            p.setPen(QColor('#77716b')); p.setFont(QFont('Georgia',24)); p.drawText(r,Qt.AlignCenter,'◇')
        if self.count is not None:
            p.setFont(QFont('Segoe UI',10,QFont.Bold)); p.setPen(QColor('#0e0e12')); p.drawText(QRectF(6,61,77,20),Qt.AlignRight,'×'+str(self.count)); p.setPen(QColor('#f4ead8')); p.drawText(QRectF(5,60,77,20),Qt.AlignRight,'×'+str(self.count))
        p.setPen(QColor('#e5c98d') if self.isChecked() else QColor('#b5ac9b')); p.setFont(QFont('Segoe UI',9))
        p.drawText(QRectF(0,88,88,15),Qt.AlignCenter,self.title)
    def enterEvent(self,e): self.update(); super().enterEvent(e)
    def leaveEvent(self,e): self.update(); super().leaveEvent(e)


class GearBoard(QWidget):
    def __init__(self, window):
        super().__init__(); self.window=window; self.setMinimumSize(320,420)
        self.setMinimumHeight(340); self.bg=QPixmap(str(ROOT/'assets/ui/equipment_bg.png')); self.slots=[]
    def fill(self, entries):
        for b,*_ in self.slots: b.deleteLater()
        self.slots=[]
        positions={('Head',0):(.50,0),('RightHand',0):(.17,.22),('Body',0):(.50,.22),('LeftHand',0):(.83,.22),
                   ('RightHand',1):(.17,.46),('Legs',0):(.50,.46),('Throwable',0):(.83,.46),
                   ('Arms',0):(.50,.70),('Consumable',0):(.83,.70),('Trinket',0):(.38,1),('Amulet',0):(.63,1),
                   ('HealthFlask',0):(.10,1),('ManaFlask',0):(.89,1)}
        for (slot,slot_index),(x,y) in positions.items():
            found=next(((i,v) for i,v in entries if clean_enum(v.get('EquipmentSlot'))==slot and v.get('EquipmentSlotIndex',0)==slot_index),None)
            entry=found[1] if found else {}; rich=self.window.rich_item(entry.get('Item',''))
            title=self.window.t(slot)
            if slot=='RightHand':
                title=self.window.t('two_handed') if rich.get('weapon_handedness')=='TwoHanded' else self.window.t('weapon_primary' if slot_index==0 else 'weapon_secondary')
            count=entry.get('Count') if slot in ('Throwable','Consumable','HealthFlask','ManaFlask') and found else None
            b=GearIcon(title,rich.get('icon',''),clean_enum(entry.get('ItemQuality')),count=count)
            b.setParent(self); b.setToolTip(self.window.tooltip(entry.get('Item',''),entry) if found else self.window.t('no_item'))
            b.setEnabled(bool(found)); b.setChecked(bool(found and found[0]==self.window.entry_index))
            if found: b.clicked.connect(lambda checked=False,i=found[0]:self.window.select_equipment(i))
            b.show(); self.slots.append((b,x,y))
        angel=self.window.session.edits.document.values.get('SaveGameInventory',{}).get('AngelAsset','') if self.window.session else ''
        angel_data=self.window.rich.get('angels',{}).get(angel,{}); art=angel_data.get('portrait','assets/ui/portrait.png')
        b=GearIcon(self.window.t('angel'),art,'Common',True); b.setParent(self); b.setToolTip('<div style="width:280px"><b>'+html.escape(self.window.text(angel_data) or self.window.t('angel'))+'</b><p>'+html.escape(self.window.text(angel_data,'descriptions'))+'</p></div>'); b.clicked.connect(lambda:self.window.navigate(3)); b.show(); self.slots.append((b,.17,.72))
        self.position()
    def position(self):
        size=min(88,max(52,int(self.height()/5.5*88/103)))
        for b,x,y in self.slots:
            b.setFixedSize(size,int(size*103/88)); b.move(int(self.width()*x-size/2),int((self.height()-b.height())*y))
    def resizeEvent(self,e): self.position()
    def paintEvent(self,e):
        p=QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        if not self.bg.isNull():
            p.setOpacity(.65); pix=self.bg.scaled(self.size(),Qt.KeepAspectRatioByExpanding,Qt.SmoothTransformation)
            p.drawPixmap((self.width()-pix.width())//2,(self.height()-pix.height())//2,pix); p.setOpacity(1)
        p.setPen(QPen(QColor('#4b4236'),1)); p.drawLine(16,self.height()-2,self.width()-16,self.height()-2)


class EditorWindow(QMainWindow):
    def __init__(self, source=None, data_dir=None):
        super().__init__()
        if data_dir is not None:
            settings_dir=Path(data_dir).expanduser().absolute(); settings_dir.mkdir(parents=True,exist_ok=True)
            self.settings=QSettings(str(settings_dir/'settings.ini'),QSettings.IniFormat)
        else:self.settings=QSettings('CrimsonMoonSaveEditor','Editor')
        self.lang=str(self.settings.value('language','pt')); self.page_index=0; self.session=None
        self.catalog=Catalogue.load(ROOT/'data'); self.store=TransactionStore(data_dir)
        path=ROOT/'data/game_data.json'; self.rich=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        self.progression=json.loads((ROOT/'data/progression.json').read_text(encoding='utf-8'))
        self.ui_translations=json.loads((ROOT/'data/ui_translations.json').read_text(encoding='utf-8'))
        self.entry_index=None; self.candidate_path=None; self.active_boon=None; self.selected_boon=None
        self.setWindowTitle(f'Crimson Moon · Save Editor {__version__}'); self.setMinimumSize(1120,760); self.resize(1450,960)
        self.setWindowIcon(self.icon({'icon':'assets/ui/app.ico'})); self.build()
        QShortcut(QKeySequence('Ctrl+O'),self,activated=self.open_dialog)
        QShortcut(QKeySequence('Ctrl+S'),self,activated=self.apply)
        QShortcut(QKeySequence('Ctrl+Z'),self,activated=lambda:self.history_action('undo'))
        QShortcut(QKeySequence('Ctrl+Y'),self,activated=lambda:self.history_action('redo'))
        if source: self.open_path(source)
        else:
            remembered=self.settings.value('last_save',''); paths=find_saves()
            if remembered and Path(str(remembered)).is_file(): self.open_path(remembered)
            elif len(paths)==1: self.open_path(paths[0])

    def t(self,key): return self.ui_translations.get(self.lang,{}).get(key,EN.get(key,key))
    def rich_item(self,path): return self.rich.get('items',{}).get(path,{})
    def text(self,entry,field='names'):
        v=entry.get(field,{})
        return plain(v.get(self.lang) or v.get('en') or v.get('pt') or '') if isinstance(v,dict) else plain(v)
    def name(self,path):
        rich=self.rich_item(path); name=self.text(rich)
        return name or (self.catalog.by_path.get(path,{}).get('name_pt' if self.lang=='pt' else 'name_en')) or path.rsplit('.',1)[-1]
    def icon(self,entry):
        p=entry.get('icon'); return QIcon(str(ROOT/p)) if p else QIcon()
    def boon_icon(self,b,level=1):
        canvas=QPixmap(84,84); canvas.fill(Qt.transparent); p=QPainter(canvas); p.setRenderHint(QPainter.Antialiasing)
        q=QUALITY[max(0,min(4,int(level)-1))]; gradient=QRadialGradient(42,35,45)
        gradient.setColorAt(0,QColor(COLORS[q]).darker(180)); gradient.setColorAt(1,QColor('#17161b'))
        p.setBrush(gradient if b else QBrush(QColor('#1c1e24'))); p.setPen(QPen(QColor('#a88a59'),2)); p.drawEllipse(QRectF(3,3,78,78))
        p.setPen(QPen(QColor('#554536'),1)); p.setBrush(Qt.NoBrush); p.drawEllipse(QRectF(9,9,66,66))
        art=QPixmap(str(ROOT/b['icon'])) if b.get('icon') else QPixmap()
        if not art.isNull():p.drawPixmap(12,12,60,60,art)
        p.end(); return QIcon(canvas)
    def boons(self): return self.rich.get('blessings',[])
    def boon(self,path):
        key=path.rsplit('.',1)[0]
        return next((b for b in self.boons() if b.get('effect_path','').rsplit('.',1)[0]==key),{})
    def boon_description(self,b,level=None):
        variants=b.get('descriptions_by_level',{}).get(str(int(level)),{}) if level is not None else {}
        return plain(variants.get(self.lang) or variants.get('en') or self.text(b,'descriptions'))
    def tooltip(self,path,entry=None):
        rich=self.rich_item(path); item=self.catalog.by_path.get(path,{})
        quality=clean_enum((entry or {}).get('ItemQuality','Common')); color=COLORS.get(quality,'#bda06a')
        description=self.text(rich,'descriptions') or plain(item.get('description_pt' if self.lang=='pt' else 'description_en',''))
        rows=[]; section='ItemsAttributesRow' if item.get('table_rows',{}).get('ItemsAttributesRow') else 'ItemFactorAttributesRow'
        for row in self.catalog.compare(None,item,section=section):
            if row.get('after') not in (None,0): rows.append(f"{html.escape(self.stat_label(row))}: <b>{format_number(row['after'])}</b>")
        if section=='ItemFactorAttributesRow':rows.insert(0,'<i>'+('Fatores da definição' if self.lang=='pt' else 'Definition factors')+'</i>')
        effects=[]
        for ref in item.get('additional_effects',[]):
            b=self.boon(ref.get('object_path') or ref.get('referenced_path') or (ref.get('reference') or {}).get('ObjectPath',''))
            if not b:
                name=ref.get('referenced_name',''); b=next((x for x in self.boons() if name.removesuffix('_C') in x.get('effect_path','')), {})
            if b: effects.append(f"<b>{html.escape(self.text(b))}</b><br>{html.escape(self.boon_description(b,QUALITY.index(quality)+1))}")
        description=description.split('\n\n')[0]
        if len(description)>300:description=description[:297]+'…'
        return f'<div style="width:330px"><span style="color:{color}">{html.escape(self.t(quality))}</span><h3>{html.escape(self.name(path))}</h3>'+('<br>'.join(rows[:14]))+f'<p>{html.escape(description)}</p>'+''.join('<hr>'+s for s in effects)+'</div>'
    def boon_tooltip(self,b,level=None):
        desc=self.boon_description(b,level); quality=QUALITY[max(0,min(4,int(level or b.get('level',1))-1))]
        return f'<div style="width:330px"><span style="color:{COLORS[quality]}">{html.escape(self.t(quality))}</span><h3>{html.escape(self.text(b))}</h3><p>{html.escape(desc)}</p></div>'
    def stat_label(self,row):
        key=row['key'].rsplit('/',1)[-1]; labels=self.rich.get('labels',{})
        langlabels=labels.get(self.lang,{})
        if isinstance(langlabels,dict) and key in langlabels: return langlabels[key]
        return row['label'] if self.lang=='pt' else re.sub(r'(?<!^)([A-Z])',r' \1',key)

    def build(self):
        root=QWidget(); layout=QHBoxLayout(root); layout.setContentsMargins(0,0,0,0); layout.setSpacing(0)
        sidebar=QFrame(); sidebar.setObjectName('sidebar'); sidebar.setFixedWidth(184); side=QVBoxLayout(sidebar); side.setContentsMargins(0,24,0,18)
        moon=Moon(); side.addWidget(moon,0,Qt.AlignHCenter)
        brand=label('CRIMSON\nMOON'); brand.setAlignment(Qt.AlignCenter); brand.setFont(QFont('Georgia',17)); brand.setStyleSheet('color:#dfcfaf; letter-spacing:3px;'); side.addWidget(brand)
        sub=label('SAVE EDITOR','eyebrow'); sub.setAlignment(Qt.AlignCenter); side.addWidget(sub); side.addSpacing(30)
        self.nav=[]
        for i,key in enumerate(['equipment','blessings','journey','character','backups']):
            b=button(['◇  ','✧  ','⌁  ','♙  ','↶  '][i]+self.t(key),lambda checked=False,j=i:self.navigate(j)); b.setObjectName('nav'); b.setCheckable(True); self.nav.append(b); side.addWidget(b)
        side.addStretch(); side.addWidget(button(self.t('detect'),self.detect)); side.addWidget(button(self.t('about'),self.about))
        side.addWidget(label(f'  v{__version__} · PORTABLE','muted')); layout.addWidget(sidebar)
        work=QWidget(); col=QVBoxLayout(work); col.setContentsMargins(0,0,0,0); col.setSpacing(0)
        top=QFrame(); top.setObjectName('topbar'); bar=QHBoxLayout(top); bar.setContentsMargins(24,16,24,16)
        self.source_label=label('CRIMSON MOON','eyebrow'); bar.addWidget(self.source_label); bar.addStretch()
        self.balance_labels={}
        for key,asset in [('gold','coins'),('souls','souls')]:
            mini=QHBoxLayout(); mini.setSpacing(6); art=label(''); art.setFixedSize(24,24)
            art.setPixmap(QPixmap(str(ROOT/self.rich.get('ui_assets',{}).get(asset,f'assets/ui/{asset}.png'))).scaled(24,24,Qt.KeepAspectRatio,Qt.SmoothTransformation)); art.setToolTip(self.t('money' if key=='gold' else 'souls'))
            mini.addWidget(art); value=label('—'); value.setStyleSheet('color:#dbd6ca; font-size:15px;'); mini.addWidget(value); self.balance_labels[key]=value; bar.addLayout(mini); bar.addSpacing(15)
        self.language=QComboBox(); self.language.setFixedWidth(126)
        langs=self.rich.get('languages') or [{'id':k,'label':v} for k,v in [('pt','Português'),('en','English')]]
        for lng in langs: self.language.addItem(lng['label'],lng['id'])
        self.language.setCurrentIndex(max(0,self.language.findData(self.lang))); self.language.currentIndexChanged.connect(self.change_language)
        bar.addWidget(self.language); bar.addWidget(button(self.t('open'),self.open_dialog)); col.addWidget(top)
        self.stack=QStackedWidget(); self.stack.addWidget(self.equipment_page()); self.stack.addWidget(self.blessings_page()); self.stack.addWidget(self.journey_page()); self.stack.addWidget(self.character_page()); self.stack.addWidget(self.backups_page()); col.addWidget(self.stack,1)
        footer=QFrame(); footer.setObjectName('footer'); foot=QHBoxLayout(footer); foot.setContentsMargins(24,13,24,13)
        self.status=label(self.t('empty'),'muted'); foot.addWidget(self.status,1)
        self.undo_button=button('↶',lambda:self.history_action('undo')); self.undo_button.setToolTip(self.t('undo')+' · Ctrl+Z'); foot.addWidget(self.undo_button)
        self.redo_button=button('↷',lambda:self.history_action('redo')); self.redo_button.setToolTip(self.t('redo')+' · Ctrl+Y'); foot.addWidget(self.redo_button)
        self.export_button=button(self.t('export'),self.export); foot.addWidget(self.export_button)
        self.apply_button=button(self.t('save'),self.apply,True); self.apply_button.setMinimumWidth(170); foot.addWidget(self.apply_button)
        col.addWidget(footer); layout.addWidget(work,1); self.setCentralWidget(root); self.navigate(self.page_index); self.refresh()

    def page(self,title,subtitle):
        w=QWidget(); v=QVBoxLayout(w); v.setContentsMargins(24,23,24,20); v.setSpacing(13)
        v.addWidget(label(title,'title')); v.addWidget(label(subtitle,'muted',True)); return w,v

    def equipment_page(self):
        page,v=self.page(self.t('gear_title'),self.t('gear_sub')); h=QHBoxLayout(); h.setSpacing(20); v.addLayout(h,1)
        left=card(); lv=QVBoxLayout(left); lv.setContentsMargins(12,12,12,12); self.board=GearBoard(self); lv.addWidget(self.board,1)
        lv.addWidget(label(self.t('reserved'),'eyebrow')); self.reserve_bar=QWidget(); self.reserve_row=QHBoxLayout(self.reserve_bar); self.reserve_row.setContentsMargins(0,0,0,0); self.reserve_row.setSpacing(6); lv.addWidget(self.reserve_bar)
        self.inventory=QComboBox(); self.inventory.currentIndexChanged.connect(self.choose_inventory); lv.addWidget(self.inventory); h.addWidget(left,5)
        right=QWidget(); rv=QVBoxLayout(right); rv.setContentsMargins(0,0,0,0); rv.setSpacing(10)
        rv.addWidget(label(self.t('catalog'),'eyebrow')); self.item_search=QLineEdit(); self.item_search.setPlaceholderText(self.t('search')); self.item_search.textChanged.connect(self.populate_catalog); rv.addWidget(self.item_search)
        self.item_list=QListWidget(); self.item_list.setIconSize(QSize(40,40)); self.item_list.setMinimumHeight(130); self.item_list.setMaximumHeight(220); self.item_list.currentItemChanged.connect(self.candidate_changed); rv.addWidget(self.item_list,2)
        compare_row=QHBoxLayout(); compare_row.addWidget(label(self.t('compare'),'eyebrow')); compare_row.addStretch(); self.compare_mode=QComboBox()
        self.compare_mode.addItem(self.t('base_values'),'ItemsAttributesRow'); self.compare_mode.addItem(self.t('factors'),'ItemFactorAttributesRow'); self.compare_mode.currentIndexChanged.connect(self.candidate_changed); compare_row.addWidget(self.compare_mode); rv.addLayout(compare_row)
        self.compare_names=label(self.t('no_candidate'),'muted',True); rv.addWidget(self.compare_names)
        self.comparison=QTableWidget(0,4); self.comparison.setHorizontalHeaderLabels([self.t('attribute'),self.t('current'),self.t('selected'),self.t('delta')]); self.comparison.horizontalHeader().setSectionResizeMode(0,QHeaderView.Stretch)
        for i in range(1,4): self.comparison.setColumnWidth(i,80)
        self.comparison.horizontalHeader().setMinimumSectionSize(50)
        self.comparison.verticalHeader().hide(); self.comparison.setEditTriggers(QAbstractItemView.NoEditTriggers); self.comparison.setSelectionMode(QAbstractItemView.NoSelection); rv.addWidget(self.comparison,3)
        self.item_description=label('','muted',True); self.item_description.setMaximumHeight(38); rv.addWidget(self.item_description)
        self.comparison_note=label(self.t('base_note'),'muted',True); rv.addWidget(self.comparison_note)
        row=QHBoxLayout(); self.gear_quality=QComboBox()
        for q in QUALITY:self.gear_quality.addItem(self.t(q),q)
        row.addWidget(self.gear_quality); self.quality_button=button(self.t('quality_only'),self.quality_only); row.addWidget(self.quality_button); rv.addLayout(row)
        self.stack_editor=QWidget(); count_row=QHBoxLayout(self.stack_editor); count_row.setContentsMargins(0,0,0,0); count_row.addWidget(label(self.t('quantity'))); self.stack_count=QSpinBox(); self.stack_count.setRange(1,15); count_row.addWidget(self.stack_count); self.stack_button=button(self.t('prepare'),self.prepare_stack); count_row.addWidget(self.stack_button); rv.addWidget(self.stack_editor); self.stack_editor.hide()
        self.replace_button=button(self.t('replace'),self.replace_item,True); rv.addWidget(self.replace_button); h.addWidget(right,7); return page

    def blessings_page(self):
        page,v=self.page(self.t('active_boons'),self.t('boon_sub')); h=QHBoxLayout(); h.setSpacing(20); v.addLayout(h,1)
        left=card(); lv=QVBoxLayout(left); lv.setContentsMargins(16,16,16,16); self.active_list=QListWidget(); self.active_list.setStyleSheet('QListWidget::item { padding:2px; border-bottom:0; }'); self.active_list.setViewMode(QListWidget.IconMode); self.active_list.setResizeMode(QListWidget.Adjust); self.active_list.setMovement(QListWidget.Static); self.active_list.setIconSize(QSize(76,76)); self.active_list.setGridSize(QSize(98,105)); self.active_list.setWordWrap(True); self.active_list.currentItemChanged.connect(self.active_changed); lv.addWidget(self.active_list)
        self.remove_boon_button=button(self.t('remove_boon'),self.remove_boon); lv.addWidget(self.remove_boon_button); h.addWidget(left,5)
        right=QWidget(); rv=QVBoxLayout(right); rv.setContentsMargins(0,0,0,0); rv.addWidget(label(self.t('boon_catalog'),'eyebrow'))
        self.boon_search=QLineEdit(); self.boon_search.setPlaceholderText(self.t('search')); self.boon_search.textChanged.connect(self.populate_boons); rv.addWidget(self.boon_search)
        self.boon_list=QListWidget(); self.boon_list.setIconSize(QSize(52,52)); self.boon_list.currentItemChanged.connect(self.boon_changed); rv.addWidget(self.boon_list,1)
        self.boon_detail=label('','muted',True); self.boon_detail.setMinimumHeight(90); rv.addWidget(self.boon_detail)
        row=QHBoxLayout(); row.addWidget(label(self.t('quality'))); self.boon_quality=QComboBox()
        for q in QUALITY:self.boon_quality.addItem(self.t(q),q)
        self.boon_quality.setCurrentIndex(3); self.boon_quality.currentIndexChanged.connect(self.boon_changed); row.addWidget(self.boon_quality,1); rv.addLayout(row)
        self.add_boon_button=button(self.t('add_boon'),self.add_boon,True); rv.addWidget(self.add_boon_button); h.addWidget(right,6); return page

    def journey_page(self):
        page,v=self.page(self.t('journey_title'),self.t('journey_sub')); box=card(); grid=QGridLayout(box); grid.setContentsMargins(26,26,26,26); grid.setHorizontalSpacing(25); grid.setVerticalSpacing(18)
        self.journey_pairs=[]; self.path_buttons=[]; timeline=QHBoxLayout(); numerals=['I','II','III','IV','V']
        for stage in self.progression['stages']:
            for section in stage['sections']:
                i=len(self.journey_pairs); self.journey_pairs.append((stage['index'],section['index'])); title=numerals[i] if i<len(numerals) else str(i+1)
                if i:
                    line=QFrame(); line.setFixedHeight(1); line.setStyleSheet('background:#746047;'); timeline.addWidget(line,1)
                b=MissionStep(title,lambda checked=False,index=i:self.select_journey(index)); b.setToolTip(self.text(section)); self.path_buttons.append(b); timeline.addWidget(b)
        v.insertLayout(2,timeline)
        self.stage=QComboBox(page); self.stage.hide()
        for stage in self.progression.get('stages',[]): self.stage.addItem(str(stage['index']+1)+' · '+(self.text(stage) or stage['name'].get('SourceString','')),stage['index'])
        self.stage.currentIndexChanged.connect(self.populate_sections)
        self.section=QComboBox(page); self.section.hide(); self.section.currentIndexChanged.connect(self.show_missions)
        self.journey_select=QComboBox()
        for i,(stage,section) in enumerate(self.journey_pairs):self.journey_select.addItem(numerals[i]+' · '+self.text(self.progression['stages'][stage]['sections'][section]),i)
        self.journey_select.currentIndexChanged.connect(self.select_journey)
        difficulty_path=ROOT/'data/difficulty.json'; data=json.loads(difficulty_path.read_text(encoding='utf-8')) if difficulty_path.exists() else {}; modes=data.get('modes') or data.get('visible_modes')
        self.difficulty=SkullDifficulty(self.t,modes); self.difficulty.setProperty('language',self.lang); self.difficulty.sync()
        grid.addWidget(label(self.t('mission'),'eyebrow'),0,0); grid.addWidget(label(self.t('difficulty'),'eyebrow'),0,1); grid.addWidget(self.journey_select,1,0); grid.addWidget(self.difficulty,1,1)
        self.mission_choice=QComboBox(); grid.addWidget(label(self.t('mission_choice'),'eyebrow'),2,0,1,2); grid.addWidget(self.mission_choice,3,0,1,2)
        self.missions=label('','muted',True); self.missions.setMinimumHeight(100); grid.addWidget(self.missions,4,0,1,2)
        grid.addWidget(label(self.t('journey_note'),'muted',True),5,0,1,2); self.progression_button=button(self.t('prepare'),self.prepare_progression,True); grid.addWidget(self.progression_button,6,1); v.addWidget(box); v.addStretch(); return page

    def select_journey(self,index):
        if not 0<=index<len(self.journey_pairs):return
        stage,section=self.journey_pairs[index]; self.stage.setCurrentIndex(self.stage.findData(stage)); self.populate_sections(); self.section.setCurrentIndex(self.section.findData(section)); self.show_missions()

    def character_page(self):
        page,v=self.page(self.t('character_title'),self.t('close_game')); identity=card(); row=QHBoxLayout(identity); row.setContentsMargins(25,16,25,16); row.addWidget(label(self.t('character_name'))); self.character_name=QLineEdit(); self.character_name.setMaxLength(32); row.addWidget(self.character_name,1); self.rename_button=button(self.t('prepare'),self.prepare_name); row.addWidget(self.rename_button); v.addWidget(identity)
        coins=card(); cv=QGridLayout(coins); cv.setContentsMargins(25,22,25,22); cv.addWidget(label(self.t('currency_title'),'eyebrow'),0,0,1,3); self.currencies={}
        for i,key in enumerate(['gold','souls']):
            currency_header=QWidget(); currency_row=QHBoxLayout(currency_header); currency_row.setContentsMargins(0,0,0,0)
            asset='coins' if key=='gold' else 'souls'; art=label(''); art.setFixedSize(28,28); art.setPixmap(QPixmap(str(ROOT/self.rich.get('ui_assets',{}).get(asset,f'assets/ui/{asset}.png'))).scaled(28,28,Qt.KeepAspectRatio,Qt.SmoothTransformation)); currency_row.addWidget(art); currency_row.addWidget(label(self.t('money' if key=='gold' else 'souls'))); currency_row.addStretch()
            cv.addWidget(currency_header,1,i); field=QSpinBox(); field.setRange(0,10_000_000); field.setGroupSeparatorShown(True); cv.addWidget(field,2,i); self.currencies[key]=field
        self.currency_button=button(self.t('prepare'),self.prepare_currencies,True); cv.addWidget(self.currency_button,2,2); v.addWidget(coins)
        box=card(); av=QGridLayout(box); av.setContentsMargins(25,22,25,22); av.addWidget(label(self.t('attributes'),'eyebrow'),0,0,1,3); self.attributes={}
        for i,(key,name) in enumerate(ATTRIBUTES.items()):
            av.addWidget(label(name if self.lang=='pt' else key.removeprefix('Nephilim')),1+(i//3)*2,i%3); field=QSpinBox(); field.setRange(1,999); av.addWidget(field,2+(i//3)*2,i%3); self.attributes[key]=field
        av.addWidget(label(self.t('attribute_note'),'muted',True),5,0,1,3); self.attribute_button=button(self.t('prepare'),self.prepare_attributes,True); av.addWidget(self.attribute_button,6,2); v.addWidget(box); v.addStretch(); return page

    def backups_page(self):
        page,v=self.page(self.t('backup_title'),self.t('backup_sub')); self.backup_list=QListWidget(); v.addWidget(self.backup_list,1); row=QHBoxLayout(); row.addWidget(button(self.t('folder'),self.backup_folder)); row.addStretch(); self.restore_button=button(self.t('restore'),self.restore,True); row.addWidget(self.restore_button); v.addLayout(row); return page

    def navigate(self,index):
        self.page_index=index; self.stack.setCurrentIndex(index)
        for i,b in enumerate(self.nav): b.setChecked(i==index)
        if index==4:self.populate_history()
    def change_language(self):
        self.lang=self.language.currentData(); self.settings.setValue('language',self.lang); self.build()
    def run(self,action):
        try: return action()
        except Exception as exc:
            QMessageBox.warning(self,self.t('error'),str(exc)); return None
    def can_discard(self):
        if self.session and self.session.edits.dirty:
            return QMessageBox.question(self,self.t('discard'),self.t('discard_question'))==QMessageBox.Yes
        return True
    def open_dialog(self):
        path,_=QFileDialog.getOpenFileName(self,self.t('open'),str(Path(os.environ.get('LOCALAPPDATA',''))/'CrimsonMoonNG/Saved/SaveGames'),'Character save (*.sav)')
        if path:self.open_path(path)
    def detect(self):
        paths=find_saves()
        if len(paths)==1:self.open_path(paths[0])
        elif paths:
            dialog=QDialog(self); dialog.setWindowTitle(self.t('detect')); v=QVBoxLayout(dialog); choices=QListWidget()
            for p in paths: item=QListWidgetItem(str(p)); item.setData(Qt.UserRole,str(p)); choices.addItem(item)
            v.addWidget(choices); buttons=QDialogButtonBox(QDialogButtonBox.Open|QDialogButtonBox.Cancel); buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); v.addWidget(buttons); choices.setCurrentRow(0); dialog.resize(780,300)
            if dialog.exec()==QDialog.Accepted and choices.currentItem():self.open_path(choices.currentItem().data(Qt.UserRole))
        else:self.open_dialog()
    def open_path(self,path,check=True):
        if check and not self.can_discard():return
        def action():
            session=EditorSession.open(path,self.catalog); self.session=session; self.entry_index=None; self.candidate_path=None
            self.settings.setValue('last_save',str(session.source)); self.refresh()
        self.run(action)
    def refresh(self):
        exists=bool(self.session); dirty=exists and self.session.edits.dirty
        for w in [self.export_button,self.currency_button,self.attribute_button,self.progression_button,self.rename_button]:w.setEnabled(exists)
        self.apply_button.setEnabled(dirty); self.undo_button.setEnabled(exists and bool(self.session.edits._undo)); self.redo_button.setEnabled(exists and bool(self.session.edits._redo))
        if not exists:
            self.status.setText(self.t('empty')); self.board.fill([]); self.populate_boons(); self.populate_catalog(); self.populate_history(); self.replace_button.setEnabled(False); self.quality_button.setEnabled(False); return
        d=self.session.edits.document; v=d.values
        self.source_label.setText(self.session.source.name+'  /  '+str(v.get('CharacterName',''))); self.source_label.setToolTip(str(self.session.source))
        count=len(self.session.edits.operations); self.status.setText(f'●  {count} {self.t("pending")}' if dirty else '●  '+self.t('ready')); self.status.setStyleSheet('color:#d7b97c;' if dirty else 'color:#93a991;')
        balances=currency_status(d)
        for key,value in self.balance_labels.items():value.setText(format_number(balances[key]['value']))
        name=str(v.get('CharacterName','')); self.character_name.setMaxLength(max(32,len(name.encode('utf-16-le'))//2)); self.character_name.setText(name); equipped=[]; entries=backpack(d); self.inventory.blockSignals(True); self.inventory.clear()
        for i,entry in enumerate(entries):
            slot=clean_enum(entry.get('EquipmentSlot'))
            if entry.get('Item','').rsplit('.',1)[-1] in ('IC_GoldCoins','IC_Souls'):continue
            if slot in TYPE_SLOTS.values() or slot in ('Consumable','Throwable','HealthFlask','ManaFlask','All'):
                suffix=' '+str(entry.get('EquipmentSlotIndex',0)+1) if slot in ('RightHand','LeftHand') else ''
                self.inventory.addItem(self.t(slot)+suffix +'  ·  '+self.name(entry['Item']),i); equipped.append((i,entry))
        if self.entry_index is None and equipped:self.entry_index=next((i for i,e in equipped if clean_enum(e.get('EquipmentSlot'))=='Body'),equipped[0][0])
        self.inventory.setCurrentIndex(self.inventory.findData(self.entry_index)); self.inventory.blockSignals(False); self.board.fill(equipped)
        while self.reserve_row.count():
            old=self.reserve_row.takeAt(0).widget()
            if old:old.deleteLater()
        reserved=[(i,e) for i,e in equipped if clean_enum(e.get('EquipmentSlot'))=='All']
        for n in range(6):
            found=reserved[n] if n<len(reserved) else None; entry=found[1] if found else {}; path=entry.get('Item','')
            b=GearIcon('',self.rich_item(path).get('icon',''),clean_enum(entry.get('ItemQuality')),count=entry.get('Count') if entry.get('Count',1)>1 else None); b.setFixedSize(48,56); b.setEnabled(bool(found)); b.setToolTip(self.tooltip(path,entry) if found else self.t('reserve_empty'))
            if found:b.clicked.connect(lambda checked=False,index=found[0]:self.select_equipment(index))
            self.reserve_row.addWidget(b)
        self.reserve_row.addStretch()
        if self.entry_index is not None:
            entry=entries[self.entry_index]; self.gear_quality.setCurrentIndex(max(0,self.gear_quality.findData(clean_enum(entry.get('ItemQuality')))))
            if self.candidate_path is None:self.candidate_path=entry['Item']
        for kind,status in currency_status(d).items():
            field=self.currencies[kind]; value=status['value'] or 0; field.setRange(0,max(10_000_000,value)); field.setEnabled(status['editable']); field.setValue(value); field.setToolTip(status.get('reason') or '')
        for key,field in self.attributes.items():
            value=v.get('NephilimAttributes',{}).get(key); known=type(value)is int; field.setRange(min(1,value) if known else 1,max(999,value) if known else 999); field.setEnabled(known); field.setValue(value if known else 1)
        state=v.get('WorldRunState',{}); stage=state.get('CurrentManualStage',0); section=state.get('CurrentManualSection',0)
        if self.stage.findData(stage)<0:self.stage.addItem('Original · '+str(stage+1),stage)
        self.stage.setCurrentIndex(self.stage.findData(stage)); self.populate_sections()
        if self.section.findData(section)<0:self.section.addItem('Original · '+str(section+1),section)
        self.section.setCurrentIndex(self.section.findData(section)); diff=state.get('UserChosenDifficulty',0); self.difficulty.setRange(min(0,diff),max(100,diff)); self.difficulty.setValue(diff)
        self.mission_choice.setProperty('pair',None); self.show_missions()
        saved_mission=state.get('CurrentManualMission')
        if type(saved_mission)is int:
            if self.mission_choice.findData(saved_mission)<0:self.mission_choice.addItem('Original · '+str(saved_mission+1),saved_mission)
            self.mission_choice.setCurrentIndex(self.mission_choice.findData(saved_mission))
        try:
            from crimson.extended import progression_status
            status=progression_status(d); self.stage.setEnabled(status['manual_supported']); self.section.setEnabled(status['manual_supported']); self.journey_select.setEnabled(status['manual_supported']); self.progression_button.setEnabled(True)
            for b in self.path_buttons:b.setEnabled(status['manual_supported'])
            self.mission_choice.setEnabled(bool(status.get('mission_supported')))
        except SaveError as exc:
            self.progression_button.setEnabled(False); self.progression_button.setToolTip(str(exc))
        self.populate_catalog(); self.populate_boons(); self.populate_active(); self.populate_history()
    def choose_inventory(self):
        if self.inventory.currentData() is not None:self.select_equipment(self.inventory.currentData())
    def select_equipment(self,index):
        self.entry_index=index; self.candidate_path=None
        item=self.catalog.by_path.get(backpack(self.session.edits.document)[index]['Item'],{})
        self.compare_mode.setCurrentIndex(0 if item.get('table_rows',{}).get('ItemsAttributesRow') else 1); self.refresh()
    def populate_catalog(self):
        old=self.candidate_path; self.item_list.blockSignals(True); self.item_list.clear()
        type_name=None
        if self.session and self.entry_index is not None:type_name=self.catalog.by_path.get(backpack(self.session.edits.document)[self.entry_index]['Item'],{}).get('type')
        query=self.item_search.text().casefold()
        if type_name:
            for item in self.catalog.items:
                if item['type']!=type_name or self.catalog.block_reason(item):continue
                rich=self.rich_item(item['object_path']); name=self.name(item['object_path'])
                if query and query not in (name+' '+item['name_en']+' '+item['name_pt']+' '+self.text(rich,'descriptions')).casefold():continue
                w=QListWidgetItem(self.icon(rich),name); w.setData(Qt.UserRole,item['object_path']); w.setToolTip(self.tooltip(item['object_path'])); self.item_list.addItem(w)
                if item['object_path']==old:self.item_list.setCurrentItem(w)
        self.item_list.blockSignals(False); self.candidate_changed()
    def candidate_changed(self,*args):
        current=self.item_list.currentItem(); self.candidate_path=current.data(Qt.UserRole) if current else None
        self.comparison.setRowCount(0); exists=self.session and self.entry_index is not None
        gear=bool(exists and self.catalog.by_path.get(backpack(self.session.edits.document)[self.entry_index].get('Item'),{}).get('type') in TYPE_SLOTS)
        self.gear_quality.setVisible(gear); self.quality_button.setVisible(gear); self.replace_button.setVisible(gear); self.quality_button.setEnabled(gear); self.replace_button.setEnabled(bool(gear and self.candidate_path))
        self.stack_editor.setVisible(bool(exists and not gear))
        if not exists:return
        entry=backpack(self.session.edits.document)[self.entry_index]; old=self.catalog.by_path.get(entry['Item']); selected=self.catalog.by_path.get(self.candidate_path)
        if not gear:
            self.stack_count.setRange(min(1,entry.get('Count',1)),max(15,entry.get('Count',1))); self.stack_count.setValue(entry.get('Count',1)); self.stack_button.setEnabled(False)
            try:
                from crimson.extras import stack_items
                self.stack_button.setEnabled(any(e['index']==self.entry_index and e.get('editable',True) for e in stack_items(self.session.edits.document)))
            except ImportError:pass
            self.compare_names.setText(self.name(entry['Item'])); self.item_description.setText(self.text(self.rich_item(entry['Item']),'descriptions'))
            self.comparison_note.setText(self.t('quantity_note') if self.stack_button.isEnabled() else self.t('read_only_item'))
            return
        self.compare_names.setText(self.name(entry['Item'])+'  →  '+(self.name(self.candidate_path) if self.candidate_path else '—'))
        self.item_description.setText((self.text(self.rich_item(self.candidate_path),'descriptions').split('\n\n')[0]) if self.candidate_path else '')
        section=self.compare_mode.currentData(); rows=self.catalog.compare(old,selected,section=section)
        self.comparison_note.setText(self.t('base_note') if section=='ItemsAttributesRow' else ('Fatores brutos da definição, antes do cálculo de raridade e escala.' if self.lang=='pt' else 'Raw definition factors, before quality and scaling calculations.'))
        for row in rows:
            if not row['key']:continue
            i=self.comparison.rowCount(); self.comparison.insertRow(i)
            values=[self.stat_label(row),format_number(row['before']),format_number(row['after']),('+' if row['delta'] and row['delta']>0 else '')+format_number(row['delta'])]
            for j,text in enumerate(values):
                cell=QTableWidgetItem(text)
                if j:cell.setTextAlignment(Qt.AlignRight|Qt.AlignVCenter)
                if j==3 and row['delta']:cell.setForeground(QColor('#85bd9a' if row['delta']>0 else '#d78883'))
                self.comparison.setItem(i,j,cell)
    def mutate(self,action):
        if not self.session:return
        def perform():
            edits=self.session.edits; snapshot=(edits.document,list(edits._undo),list(edits._redo))
            try:action()
            except Exception:
                edits.document,edits._undo,edits._redo=snapshot
                raise
            finally:self.refresh()
        self.run(perform)
    def quality_only(self):self.mutate(lambda:self.session.edits.set_quality(self.entry_index,self.gear_quality.currentData()))
    def replace_item(self):self.mutate(lambda:self.session.edits.replace_equipment(self.entry_index,self.candidate_path,self.gear_quality.currentData()))
    def history_action(self,kind):
        if self.session:self.mutate(getattr(self.session.edits,kind))
    def prepare_currencies(self):
        def work():
            for key,field in self.currencies.items():
                status=currency_status(self.session.edits.document)[key]
                if field.isEnabled() and field.value()!=status['value']:self.session.edits.set_currency(key,field.value())
        self.mutate(work)
    def prepare_name(self):
        def work():
            from crimson.extras import write_character_name
            name=self.character_name.text(); before=self.session.edits.document.values.get('CharacterName','')
            if name==before:return
            self.record_extended(write_character_name(self.session.edits.document,name),{'kind':'name','label':self.t('character_name'),'before':before,'after':name})
        self.mutate(work)
    def prepare_stack(self):
        def work():
            from crimson.extras import write_stack_count
            before=backpack(self.session.edits.document)[self.entry_index]['Count']; value=self.stack_count.value()
            if value==before:return
            self.record_extended(write_stack_count(self.session.edits.document,self.entry_index,value),{'kind':'stack','label':self.t('quantity'),'before':before,'after':value})
        self.mutate(work)
    def prepare_attributes(self):
        def work():
            for key,field in self.attributes.items():
                old=self.session.edits.document.values.get('NephilimAttributes',{}).get(key)
                if field.isEnabled() and field.value()!=old:self.session.edits.set_attribute(key,field.value())
        self.mutate(work)
    def record_extended(self,result,operation):
        raw,check=result; self.session.edits._record(raw,operation,check)
    def prepare_progression(self):
        def work():
            from crimson.extended import write_progression
            state=self.session.edits.document.values['WorldRunState']; updates={}
            if self.difficulty.value()!=state['UserChosenDifficulty']:updates['difficulty']=self.difficulty.value()
            if self.stage.isEnabled():
                for key,field,value in [('stage','CurrentManualStage',self.stage.currentData()),('section','CurrentManualSection',self.section.currentData())]:
                    if value!=state[field]:updates[key]=value
            if self.mission_choice.isEnabled() and self.mission_choice.currentData() is not None and self.mission_choice.currentData()!=state.get('CurrentManualMission'):
                updates['mission_index']=self.mission_choice.currentData()
            self.record_extended(write_progression(self.session.edits.document,updates),{'kind':'progression','label':self.t('journey'),'after':updates})
        self.mutate(work)
    def populate_sections(self):
        if not hasattr(self,'section'):return
        prev=self.section.currentData(); self.section.blockSignals(True); self.section.clear()
        stage=self.stage.currentData() or 0
        stages=self.progression['stages']; sections=stages[stage]['sections'] if 0<=stage<len(stages) else []
        for section in sections:self.section.addItem(str(section['index']+1)+' · '+(self.text(section) or section['name'].get('SourceString','')),section['index'])
        self.section.setCurrentIndex(max(0,self.section.findData(prev))); self.section.blockSignals(False); self.show_missions()
    def show_missions(self):
        if not hasattr(self,'missions'):return
        stage=self.stage.currentData() or 0; section=self.section.currentData() or 0
        stages=self.progression['stages']
        if not 0<=stage<len(stages) or not 0<=section<len(stages[stage]['sections']):
            self.missions.setText('Original · '+str(stage+1)+' / '+str(section+1)); return
        pair=(stage,section); index=self.journey_pairs.index(pair) if pair in self.journey_pairs else -1
        self.journey_select.blockSignals(True); self.journey_select.setCurrentIndex(index); self.journey_select.blockSignals(False)
        state=self.session.edits.document.values.get('WorldRunState',{}) if self.session else {}; saved_pair=(state.get('CurrentManualStage'),state.get('CurrentManualSection')); saved_index=self.journey_pairs.index(saved_pair) if saved_pair in self.journey_pairs else -1
        for i,b in enumerate(self.path_buttons):
            b.setChecked(i==index); b.setProperty('complete',i<saved_index); b.update()
        option=stages[stage]['sections'][section]; text=[]
        previous=self.mission_choice.currentData() if self.mission_choice.property('pair')==str(pair) else state.get('CurrentManualMission',0) if saved_pair==pair else 0
        self.mission_choice.blockSignals(True); self.mission_choice.clear()
        for i,mission in enumerate(option['missions']):
            name=mission['name']; translated=self.rich.get('labels',{}).get(self.lang,{}).get(name.get('Key',''))
            self.mission_choice.addItem(self.text(mission) or translated or name.get('SourceString',mission['id']),i)
        self.mission_choice.setProperty('pair',str(pair)); self.mission_choice.setCurrentIndex(max(0,self.mission_choice.findData(previous))); self.mission_choice.blockSignals(False)
        if state.get('bPlayerStartedMission'):text.append(self.t('mission_active'))
        text.append(self.t('missions')+': '+str(len(option['missions'])))
        self.missions.setText('\n\n'.join(text))
    def populate_boons(self):
        if not hasattr(self,'boon_list'):return
        old=self.selected_boon; self.boon_list.blockSignals(True); self.boon_list.clear(); query=self.boon_search.text().casefold()
        for b in sorted(self.boons(),key=lambda b:self.text(b)):
            if b.get('experimental'):continue
            if query and query not in (self.text(b)+' '+self.text(b,'descriptions')+' '+b.get('id','')).casefold():continue
            w=QListWidgetItem(self.boon_icon(b,self.boon_quality.currentIndex()+1),self.text(b)); w.setData(Qt.UserRole,b.get('effect_path')); w.setToolTip(self.boon_tooltip(b,self.boon_quality.currentIndex()+1)); self.boon_list.addItem(w)
            if b.get('effect_path')==old:self.boon_list.setCurrentItem(w)
        self.boon_list.blockSignals(False); self.boon_changed()
    def boon_changed(self,*args):
        current=self.boon_list.currentItem(); self.selected_boon=current.data(Qt.UserRole) if current else None; b=self.boon(self.selected_boon or '')
        self.boon_detail.setText((self.text(b)+'\n\n'+self.boon_description(b,self.boon_quality.currentIndex()+1)) if b else ''); self.add_boon_button.setEnabled(bool(self.session and b))
    def populate_active(self):
        self.active_list.clear(); self.active_boon=None; self.remove_boon_button.setEnabled(False)
        if not self.session:return
        doc=self.session.edits.document
        for e in doc.values.get('PlayerGameplayEffects',[]):
            path=e.get('GameplayEffect',''); b=self.boon(path); level=e.get('Level',1)
            name=self.text(b) or path.rsplit('.',1)[-1].removeprefix('Default__'); q=QUALITY[max(0,min(4,int(level)-1))]
            w=QListWidgetItem(self.boon_icon(b,level),name); w.setData(Qt.UserRole,path); w.setToolTip(self.boon_tooltip(b,level)); self.active_list.addItem(w)
        for entry in backpack(doc):
            if clean_enum(entry.get('EquipmentSlot')) not in TYPE_SLOTS.values():continue
            item=self.catalog.by_path.get(entry.get('Item'),{})
            for ref in item.get('additional_effects',[]):
                refname=ref.get('referenced_name','').removesuffix('_C'); b=next((x for x in self.boons() if refname and refname in x.get('effect_path','')), {})
                if not b:continue
                level=QUALITY.index(clean_enum(entry.get('ItemQuality','Common')))+1
                w=QListWidgetItem(self.boon_icon(b,level),self.text(b)); w.setToolTip(self.boon_tooltip(b,level)+'<p>'+self.t('gear_effect')+'</p>'); w.setData(Qt.UserRole,None); self.active_list.addItem(w)
        for i in range(max(0,30-self.active_list.count())):
            w=QListWidgetItem(self.boon_icon({}),''); w.setFlags(Qt.ItemIsEnabled); self.active_list.addItem(w)
    def active_changed(self,*args):
        w=self.active_list.currentItem(); self.active_boon=w.data(Qt.UserRole) if w else None; self.remove_boon_button.setEnabled(bool(self.active_boon))
    def add_boon(self):
        def work():
            from crimson.extended import write_blessing
            self.record_extended(write_blessing(self.session.edits.document,self.selected_boon,quality=self.boon_quality.currentData()),{'kind':'blessing','label':self.t('add_boon'),'after':self.text(self.boon(self.selected_boon))})
        self.mutate(work)
    def remove_boon(self):
        def work():
            from crimson.extended import write_blessing
            self.record_extended(write_blessing(self.session.edits.document,self.active_boon,remove=True),{'kind':'blessing','label':self.t('remove_boon'),'before':self.text(self.boon(self.active_boon))})
        self.mutate(work)
    def populate_history(self):
        if not hasattr(self,'backup_list'):return
        self.backup_list.clear(); self.restore_button.setEnabled(False)
        if not self.session:return
        for tx in self.store.history(self.session.source):
            from datetime import datetime
            dt=datetime.fromisoformat(tx['created_utc']).astimezone().strftime('%d/%m/%Y  %H:%M:%S')
            w=QListWidgetItem(dt+'   ·   '+str(tx['status'])+'   ·   '+str(len(tx['operations']))+' '+self.t('pending')); w.setData(Qt.UserRole,tx); self.backup_list.addItem(w)
        self.restore_button.setEnabled(self.backup_list.count()>0)
        if self.backup_list.count():self.backup_list.setCurrentRow(0)
        else:self.backup_list.addItem(self.t('no_backups'))
    def backup_folder(self):
        self.store.base.mkdir(parents=True,exist_ok=True); QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.store.base)))
    def restore(self):
        item=self.backup_list.currentItem(); tx=item.data(Qt.UserRole) if item else None
        if not tx or not self.session:return
        if not self.can_discard():return
        if QMessageBox.question(self,self.t('restore'),self.t('restore')+'?\n'+self.t('close_game'))!=QMessageBox.Yes:return
        def work():
            path=self.session.source; self.store.restore(path,tx['path'],expected_current_hash=self.session.original.document.sha256); self.open_path(path,False)
        self.run(work)
    def apply(self):
        if not self.session or not self.session.edits.dirty:return
        dialog=QDialog(self); dialog.setWindowTitle(self.t('review')); v=QVBoxLayout(dialog); v.addWidget(label(self.t('apply_question'),'',True)); v.addWidget(label(self.t('close_game'),'muted',True)); text=QTextBrowser()
        lines=[]
        for op in self.session.edits.operations:
            before=op.get('before',''); after=op.get('after',''); lines.append('<p><b>'+html.escape(str(op.get('label',op['kind'])))+'</b><br>'+html.escape(str(before))+' → '+html.escape(str(after))+'</p>')
        text.setHtml(''.join(lines)); v.addWidget(text); buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel); buttons.button(QDialogButtonBox.Save).setText(self.t('save')); buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); v.addWidget(buttons); dialog.resize(620,460)
        if dialog.exec()!=QDialog.Accepted:return
        def work():
            path=self.session.source; self.store.apply(self.session); self.open_path(path,False); QMessageBox.information(self,self.t('save'),self.t('applied'))
        self.run(work)
    def export(self):
        if not self.session:return
        dest=QFileDialog.getExistingDirectory(self,self.t('export'))
        if not dest:return
        from datetime import datetime
        folder=Path(dest)/('CrimsonMoon_Export_'+datetime.now().strftime('%Y%m%d_%H%M%S'))
        def work():self.store.export(self.session,folder); QMessageBox.information(self,self.t('export'),self.t('copy_saved')+'\n'+str(folder))
        self.run(work)
    def about(self):
        dialog=QDialog(self); dialog.setWindowTitle(self.t('about')); v=QVBoxLayout(dialog); v.setContentsMargins(28,28,28,24)
        v.addWidget(label('CRIMSON MOON','title')); v.addWidget(label(f'SAVE EDITOR · {__version__}','eyebrow')); v.addSpacing(15)
        v.addWidget(label('Criado por vinitor3' if self.lang=='pt' else 'Created by vinitor3','',True))
        v.addWidget(label('Desenvolvido com ajuda do GPT (OpenAI). Inteligência artificial foi utilizada na programação, na interface, nas traduções e nos testes.' if self.lang=='pt' else 'Developed with help from GPT (OpenAI). Artificial intelligence was used for programming, interface design, translations and testing.','muted',True))
        v.addWidget(label('Research tools: FModel (4sval/FModel) · UE4SS (UE4SS-RE/RE-UE4SS)', 'muted', True))
        v.addSpacing(12); v.addWidget(label(self.t('experimental'),'muted'))
        v.addWidget(label('Os nomes, textos e imagens do jogo pertencem aos seus respectivos autores. Projeto independente, sem vínculo com o estúdio.' if self.lang=='pt' else 'Game names, text and artwork belong to their respective owners. Independent project, not affiliated with the game studio.','muted',True))
        buttons=QDialogButtonBox(QDialogButtonBox.Close); buttons.rejected.connect(dialog.reject); v.addSpacing(16); v.addWidget(buttons); dialog.resize(520,340); dialog.exec()
    def closeEvent(self,event):
        if self.can_discard():event.accept()
        else:event.ignore()


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--save'); parser.add_argument('--data-dir'); parser.add_argument('--smoke-test',action='store_true'); parser.add_argument('--screenshot'); args=parser.parse_args()
    app=QApplication(sys.argv[:1]); app.setApplicationName('CrimsonMoonSaveEditor')
    if not QFontDatabase.families():
        for name in ['segoeui.ttf','segoeuib.ttf','georgia.ttf','msgothic.ttc','msyh.ttc']:
            font=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/name
            if font.is_file():QFontDatabase.addApplicationFont(str(font))
    app.setStyle('Fusion'); app.setStyleSheet(STYLE)
    window=EditorWindow(args.save,args.data_dir); available=app.primaryScreen().availableGeometry()
    window.resize(min(1450,available.width()-40),min(960,available.height()-55)); window.show()
    if args.smoke_test:
        def smoke():
            try:
                for i in range(5):window.navigate(i); app.processEvents()
                window.navigate(0); app.processEvents()
                if args.screenshot:window.grab().save(args.screenshot)
                print(json.dumps({'ok':True,'loaded':bool(window.session),'catalog_items':len(window.catalog.items),'blessings':len(window.boons()),'languages':len(window.rich.get('languages',[]))})); app.exit(0)
            except Exception:traceback.print_exc(); app.exit(1)
        QTimer.singleShot(1000,smoke)
    return app.exec()

if __name__=='__main__':raise SystemExit(main())
