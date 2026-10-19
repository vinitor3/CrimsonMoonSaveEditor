"""Small synthetic fixtures; these are NOT playable saves and contain no user data."""
from pathlib import Path
import struct
from test_core import text, tn, prop, struct_type, integer, fixture, record
from crimson.catalogue import Catalogue, TYPE_SLOTS
from crimson.editing import ATTRIBUTES

ROOT=Path(__file__).resolve().parents[1]

def catalogue():return Catalogue.load(ROOT/'data')

def gear_record(item, *, quality='Epic', index=0, slot=None, stability='Purifiable', count=1, effect=None, runes=False):
    package,asset=item['package_name'],item['asset_name']
    ap=prop('PackageName',tn('NameProperty'),text(package))+prop('AssetName',tn('NameProperty'),text(asset))+text('None')
    if effect is None:effect={'PackageName':'None','AssetName':'None','SubPath':''}
    props=(prop('AssetPath',struct_type('TopLevelAssetPath'),ap)
        +prop('Item',tn('ObjectProperty'),text(item['object_path']))+integer('Count',count)
        +prop('EquipmentSlot',tn('EnumProperty',tn('EEquipmentSlot'),tn('ByteProperty')),text('EEquipmentSlot::'+(slot or TYPE_SLOTS[item['type']])))
        +integer('EquipmentSlotIndex',index)+integer('Context1',0)+integer('Context2',0)
        +prop('SlottedRunes',tn('ArrayProperty',tn('IntProperty')),struct.pack('<i',1 if runes else 0)+(struct.pack('<i',7) if runes else b''))
        +prop('InstanceId',tn('Int64Property'),struct.pack('<q',1234567890))
        +prop('IsDefaultItem',tn('BoolProperty'),b'',0)+prop('bAutoEquip',tn('BoolProperty'),b'',16)
        +prop('PurificationStatus',tn('EnumProperty',tn('EPurificationStatus'),tn('ByteProperty')),text('EPurificationStatus::Impure'))
        +prop('ItemStability',tn('EnumProperty',tn('EItemStability'),tn('ByteProperty')),text('EItemStability::'+stability))
        +prop('ItemQuality',tn('EnumProperty',tn('EScalingQuality'),tn('ByteProperty')),text('EScalingQuality::'+quality))
        +prop('InstanceEquippedEffect',tn('SoftObjectProperty'),b''.join(text(effect[k]) for k in ('PackageName','AssetName','SubPath')))
        +text('None'))
    return props

def sample(item=None,*,extra=b'',**kwargs):
    c=catalogue()
    item=item or c.by_asset['IIA_PhoenixPaladin_01_Head']
    attrs=prop('NephilimAttributes',struct_type('NephilimAttributes'),b''.join(integer(k,10) for k in ATTRIBUTES)+text('None'))
    opaque=prop('UninterpretedName',tn('TextProperty'),b'\x01\xff\x80OPAQUE\0\0')
    return fixture([record(),record('IC_Souls',40),gear_record(item,**kwargs)],extra=attrs+opaque+extra)
