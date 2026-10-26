"""Build compiled SDK wheels without shipping implementation source."""

from pathlib import Path

from Cython.Build import cythonize
from setuptools import Extension, setup
from setuptools.command.build_py import build_py
from setuptools.command.sdist import sdist


class BinaryBuild(build_py):
    def find_package_modules(self, package, package_dir):
        return []

    def run(self):
        super().run()
        from mypy.stubgen import main

        main(['--no-import', 'edu_host', '-o', self.build_lib])
        package = Path(self.build_lib) / 'edu_host'
        if not (package / '__init__.pyi').is_file():
            raise RuntimeError('SDK type declarations were not generated')
        with (package / '__init__.pyi').open('a') as declarations:
            declarations.write('\n__version__: str\n')
        (package / 'py.typed').touch()


class NoSourceDistribution(sdist):
    def run(self):
        raise RuntimeError('Source distributions are disabled; build with --wheel')


extensions = [
    Extension('edu_host.' + path.stem, [str(path)])
    for path in sorted(Path('edu_host').glob('*.py'))
]

setup(
    ext_modules=cythonize(
        extensions,
        build_dir='build/cython',
        compiler_directives={
            'language_level': 3,
            'annotation_typing': False,
            'binding': True,
            'embedsignature': True,
        },
    ),
    cmdclass={'build_py': BinaryBuild, 'sdist': NoSourceDistribution},
)
