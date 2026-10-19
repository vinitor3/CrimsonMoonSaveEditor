"""Opt-in read-only source validation; mutations use memory or temporary copies.

Usage: python tools/validate_real_saves.py --out report.json file1.sav file2.sav
No sample saves are distributed. The report includes basenames/hashes but not
save bytes. This is binary validation, never a claim of in-game compatibility.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import sys
import tempfile
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from crimson.catalogue import Catalogue, QUALITY_LABELS
from crimson.editing import EditBuffer, ATTRIBUTES, equipment_entry
from crimson.gvas import SaveDocument, SaveError
from crimson.service import currency_field, json_bytes, digest
from crimson.storage import EditorSession, TransactionStore


def check_source(path: Path,catalog: Catalogue):
    before=path.read_bytes();d=SaveDocument.from_bytes(before)
    assert d.rebuild()==before
    row={'filename':path.name,'sha256':digest(before),'bytes':len(before),
         'class':d.header.get('class'),'no_op_identical':True,'counts':{},'skips':[],
         'game_executed':False}
    counts=Counter()
    if d.header.get('class')!='/Script/CrimsonMoonNG.SaveGameCharacter':
        row['note']='Perfil não-personagem: somente leitura e reconstrução sem alterações.'
        assert path.read_bytes()==before
        return row
    e=EditBuffer(d,catalog)
    for kind in ['gold','souls']:
        try:value,_=currency_field(d,kind)
        except SaveError as exc:
            row['skips'].append({'kind':kind,'reason':str(exc)});counts['currency_missing_refused']+=1;continue
        for target in [0,1,20000,10000000]:
            e.discard();e.set_currency(kind,target)
            assert currency_field(e.document,kind)[0]==target
            counts['currency_values']+=1
            while e.undo():pass
            assert e.document.raw==before
    for key in ATTRIBUTES:
        if key not in d.values.get('NephilimAttributes',{}):
            row['skips'].append({'kind':key,'reason':'Atributo ausente.'});continue
        for target in [1,50,999]:
            e.discard();e.set_attribute(key,target)
            assert e.document.values['NephilimAttributes'][key]==target
            while e.undo():pass
            assert e.document.raw==before;counts['attribute_values']+=1
    templates={}
    for idx,entry in enumerate(d.values['SaveGameInventory']['BackpackContents']):
        try:_,item=equipment_entry(d,catalog,idx)
        except SaveError:continue
        for quality in QUALITY_LABELS:
            e.discard();e.set_quality(idx,quality)
            assert e.document.values['SaveGameInventory']['BackpackContents'][idx]['ItemQuality']=='EScalingQuality::'+quality
            while e.undo():pass
            assert e.document.raw==before;counts['quality_values']+=1
        if entry.get('SlottedRunes')==[] and entry.get('InstanceEquippedEffect')=={'PackageName':'None','AssetName':'None','SubPath':''} and entry.get('ItemStability')=='EItemStability::Purifiable':
            templates.setdefault(item['type'],idx)
    for target in catalog.items:
        if catalog.block_reason(target):continue
        idx=templates.get(target['type'])
        if idx is None:
            row['skips'].append({'kind':target['asset_name'],'reason':'Sem instância compatível neutra para testar.'});continue
        e.discard();e.replace_equipment(idx,target['object_path'],'Legendary')
        changed=e.document.values['SaveGameInventory']['BackpackContents'][idx]
        assert changed['Item']==target['object_path']
        assert changed['AssetPath']=={'PackageName':target['package_name'],'AssetName':target['asset_name']}
        assert changed['ItemQuality']=='EScalingQuality::Legendary'
        old=d.values['SaveGameInventory']['BackpackContents'][idx]
        assert all(changed[k]==v for k,v in old.items() if k not in {'Item','AssetPath','ItemQuality'})
        while e.undo():pass
        assert e.document.raw==before;counts['catalog_replacements']+=1
        if counts['catalog_replacements']%50==0:
            print(f'  {path.name}: {counts["catalog_replacements"]} trocas verificadas',flush=True)
    # An actual file transaction and restoration, but exclusively in a temp dir.
    with tempfile.TemporaryDirectory(prefix='cm_validation_') as temp:
        root=Path(temp);savefolder=root/'saves';savefolder.mkdir()
        source=savefolder/'Player_Character_0.sav';source.write_bytes(before)
        backup=savefolder/'Player_Character_0.backup.sav';backup.write_bytes(before)
        store=TransactionStore(root/'application',guard=lambda:None)
        session=EditorSession.open(source,catalog)
        v,_=currency_field(d,'gold');session.edits.set_currency('gold',v+100 if v<10000000 else v-1)
        session.edits.set_attribute('NephilimStrength',51)
        if templates:
            idx=next(iter(templates.values()));old_type=catalog.item(d.values['SaveGameInventory']['BackpackContents'][idx]['Item'])['type']
            target=next(i for i in catalog.items if i['type']==old_type and not catalog.block_reason(i))
            session.edits.replace_equipment(idx,target['object_path'],'Legendary')
        proposed=session.edits.document.raw
        report=store.apply(session)
        assert source.read_bytes()==proposed and backup.read_bytes()==before
        assert (Path(report['backup_directory'])/'originais'/source.name).read_bytes()==before
        result=store.restore(source,report['backup_directory'],expected_current_hash=digest(proposed))
        assert source.read_bytes()==before and backup.read_bytes()==before
        assert (Path(result['backup_directory'])/'originais'/source.name).read_bytes()==proposed
        counts['temporary_apply_restore_pairs']=1
    assert path.read_bytes()==before
    assert counts['catalog_replacements']>0, 'Nenhuma troca exercitada neste personagem.'
    row.update(counts=dict(counts),original_unchanged=True)
    return row


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('saves',nargs='+',type=Path);ap.add_argument('--out',required=True,type=Path)
    args=ap.parse_args();out=args.out.resolve()
    inputs=[p.resolve(strict=True) for p in args.saves]
    if out in inputs or out.suffix.lower()!='.json' or out.exists():
        raise SaveError('Escolha um relatório JSON novo, diferente dos arquivos de entrada.')
    if not __debug__:raise SaveError('Execute sem -O: as assercoes precisam estar ativas.')
    catalog=Catalogue.load(Path(__file__).resolve().parents[1]/'data')
    start=time.perf_counter();rows=[]
    for path in inputs:
        print('Validando '+path.name,flush=True);rows.append(check_source(path,catalog))
    total=Counter()
    for row in rows:total.update(row['counts'])
    result={'created_utc':datetime.now(timezone.utc).isoformat(),'elapsed_seconds':round(time.perf_counter()-start,3),
            'python':platform.python_version(),'platform':platform.platform(),'sources':rows,
            'totals':dict(total),'no_op_files':len(rows),'assertions_passed':True,'game_executed':False,
            'native_windows_tested':sys.platform=='win32',
            'note':'Fontes preservadas. Guard de processos injetado como neutro somente nas cópias temporárias deste teste.'}
    out.write_bytes(json_bytes(result));print(json.dumps(result['totals'],indent=2),flush=True)
    print('Relatório: '+str(out),flush=True)

if __name__=='__main__':main()
