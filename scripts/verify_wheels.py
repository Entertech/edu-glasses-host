"""Reject source, missing modules, and incorrect versions before upload."""

import argparse
from email.parser import BytesParser
from pathlib import Path
import zipfile

from packaging.utils import parse_wheel_filename


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--version', required=True)
    args = parser.parse_args()
    files = list(args.directory.iterdir())
    if not files or any(not path.is_file() or path.suffix != '.whl' for path in files):
        raise SystemExit('Artifact directory must contain only wheels')
    modules = {path.stem for path in (Path(__file__).resolve().parents[1] / 'edu_host').glob('*.py')}
    assert modules, 'No source module inventory'
    for path in sorted(files):
        name, version, _, tags = parse_wheel_filename(path.name)
        assert name == 'edu-glasses-host' and str(version) == args.version, path
        assert all(tag.abi != 'none' and tag.platform != 'any' for tag in tags), path
        with zipfile.ZipFile(path) as wheel:
            names = wheel.namelist()
            assert not any(Path(name).suffix.lower() in
                           {'.py', '.pyx', '.pxd', '.pxi', '.c', '.cpp', '.h', '.hpp', '.pyc'}
                           for name in names), 'Implementation source found: ' + str(path)
            assert 'edu_host/py.typed' in names, path
            for module in modules:
                assert 'edu_host/' + module + '.pyi' in names, (path, module, 'stub')
                assert any(name.startswith('edu_host/' + module + '.') and
                           name.endswith(('.so', '.pyd')) for name in names), (path, module, 'extension')
            assert all(name.startswith(('edu_host/', 'edu_glasses_host-')) or
                       name.startswith('edu_glasses_host.libs/') for name in names), names
            metadata = [name for name in names if name.endswith('.dist-info/METADATA')]
            assert len(metadata) == 1, path
            info = BytesParser().parsebytes(wheel.read(metadata[0]))
            assert info['Name'] == 'edu-glasses-host' and info['Version'] == args.version, path
            assert not any(name.endswith('/entry_points.txt') for name in names), path
        print('Verified', path.name)


if __name__ == '__main__':
    main()
