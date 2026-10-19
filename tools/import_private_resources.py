"""Copy optional local assets without overwriting tracked public resources."""
import argparse
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--from-folder',type=Path,required=True)
    args=parser.parse_args();source=args.from_folder.resolve();dest=ROOT/'local_resources'
    if dest.exists(): parser.error('local_resources already exists; choose a fresh checkout or preserve it separately.')
    files=[]
    for parent in ['data','assets']:
        folder=source/parent
        if not folder.is_dir() or folder.is_symlink(): parser.error('Expected ordinary data/ and assets/ directories.')
        for path in folder.rglob('*'):
            if path.is_symlink() or not path.resolve().is_relative_to(source): parser.error('Symlinks and escaping paths are refused.')
            if path.is_file():
                if path.suffix.lower() not in {'.json','.png','.ico','.txt'}: continue
                files.append(path)
    for path in files:
        target=dest/path.relative_to(source);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
    (dest/'PRIVATE_GAME_RESOURCES').write_text('Local-only content. Not authorized for redistribution.\n',encoding='utf-8')
    print('Imported local resources. Set CM_EDITOR_RESOURCES to the local_resources directory.')

if __name__=='__main__':main()
