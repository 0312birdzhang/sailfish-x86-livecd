#!/usr/bin/env python3
"""Build matching i386/amd64 Mesa bundles in the isolated Ubuntu graphics SDK."""
import collections
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def run(arguments, **kwargs):
    subprocess.run([str(arg) for arg in arguments], check=True, **kwargs)


def download(item, directory):
    directory.mkdir(parents=True, exist_ok=True)
    archive = directory / item['name']
    if not archive.exists() or sha256(archive) != item['sha256']:
        temporary = archive.with_suffix('.partial')
        with urllib.request.urlopen(item['url'], timeout=120) as response, temporary.open('wb') as target:
            shutil.copyfileobj(response, target)
        if sha256(temporary) != item['sha256']:
            raise RuntimeError('Source checksum mismatch: ' + item['name'])
        temporary.replace(archive)
    return archive


def verify(marker, fingerprint, payload):
    if not marker.exists():
        return False
    previous = json.loads(marker.read_text())
    return previous.get('fingerprint') == fingerprint and all(
        (payload / name).is_file() and not (payload / name).is_symlink()
        and sha256(payload / name) == digest for name, digest in previous['files'].items()
    ) and all(
        (payload / name).is_symlink() and str((payload / name).readlink()) == target
        for name, target in previous['links'].items()
    )


def dependency_bundle(libraries, triplet, runtime_directory):
    # Keep glibc and Wayland supplied by the target OS. Private RPATHs resolve
    # the remaining dependency closure without changing other system libraries.
    excluded = re.compile(r'^(ld-linux|lib(c|m|pthread|dl|rt|resolv|util)\.so|libwayland-)')
    system_paths = [Path('/usr/lib') / triplet, Path('/lib') / triplet]
    queue = collections.deque(libraries.rglob('*.so*'))
    for name in ['libEGL.so.1', 'libGLESv2.so.2', 'libGL.so.1', 'libGLX.so.0', 'libGLdispatch.so.0']:
        queue.append(next(directory / name for directory in system_paths if (directory / name).exists()))
    visited = set()
    while queue:
        source = queue.popleft()
        if source.name in visited or excluded.match(source.name):
            continue
        visited.add(source.name)
        if source.read_bytes()[:4] != b'\x7fELF':
            continue
        if not source.is_relative_to(libraries):
            target = libraries / source.name
            shutil.copy2(source.resolve(), target)
            source = target
        dynamic = subprocess.check_output(['readelf', '-d', source], text=True)
        for name in re.findall(r'Shared library: \[(.*?)\]', dynamic):
            if excluded.match(name):
                continue
            if (libraries / name).exists():
                queue.append(libraries / name)
            else:
                matches = [directory / name for directory in system_paths if (directory / name).exists()]
                if not matches:
                    raise FileNotFoundError(f'{triplet}: dependency {name} of {source}')
                queue.append(matches[0])
    for path in libraries.rglob('*'):
        if path.is_file() and not path.is_symlink() and path.read_bytes()[:4] == b'\x7fELF':
            # The loader cache names graphics/ SONAME links. $ORIGIN would
            # resolve relative to that link directory in early boosters.
            run(['patchelf', '--set-rpath', runtime_directory, path])


def main():
    project, base = (Path(arg).resolve() for arg in sys.argv[1:])
    manifest = project / 'config/graphics-mesa-build.json'
    config = json.loads(manifest.read_text())
    venv = base / 'venv'
    if not (venv / 'bin/python').exists():
        run(['python3', '-m', 'venv', venv])
    requirements = json.dumps(config['python_requirements'])
    requirements_marker = venv / 'requirements.json'
    if not requirements_marker.exists() or requirements_marker.read_text() != requirements:
        run([venv / 'bin/pip', 'install', *config['python_requirements']])
        requirements_marker.write_text(requirements)
    env = os.environ.copy()
    env['PATH'] = str(venv / 'bin') + ':' + env['PATH']
    source = base / 'source' / ('mesa-' + config['version'])
    archive = download(config['source'], base / 'downloads')
    if not source.exists():
        with tarfile.open(archive) as packed:
            packed.extractall(source.parent, filter='data')
    protocol_archive = download(config['wayland_protocols'], base / 'downloads')
    protocols = source / 'subprojects/wayland-protocols-1.41'
    if not protocols.exists():
        with tarfile.open(protocol_archive) as packed:
            packed.extractall(protocols.parent, filter='data')

    llvm32 = base / 'llvm-config-i386'
    llvm32.write_text('''#!/usr/bin/env python3
import subprocess, sys
text = subprocess.check_output(['/usr/bin/llvm-config-19', *sys.argv[1:]], text=True)
print(text.replace('/usr/lib/llvm-19/lib', '/usr/lib/i386-linux-gnu'), end='')
''')
    llvm32.chmod(0o755)
    llvm_library = Path('/usr/lib/i386-linux-gnu/libLLVM-19.so')
    if not llvm_library.exists():
        runtime = next(Path('/usr/lib/i386-linux-gnu').glob('libLLVM.so.19*'))
        llvm_library.symlink_to(runtime.name)
    cross = base / 'i386.ini'
    cross.write_text(f'''[binaries]
c = ['gcc', '-m32']
cpp = ['g++', '-m32']
ar = 'ar'
strip = 'strip'
pkg-config = 'pkg-config'
llvm-config = '{llvm32}'
[host_machine]
system = 'linux'
cpu_family = 'x86'
cpu = 'i686'
endian = 'little'
[properties]
pkg_config_libdir = ['/usr/lib/i386-linux-gnu/pkgconfig', '/usr/share/pkgconfig']
''')
    native = base / 'amd64.ini'
    native.write_text('''[binaries]
llvm-config = '/usr/bin/llvm-config-19'
''')
    compiler = subprocess.check_output(['gcc', '--version'])
    sdk_packages = Path('/etc/graphics-sdk-packages.tsv').read_bytes()
    fingerprint_base = (manifest.read_bytes() + Path(__file__).read_bytes() + compiler + sdk_packages
                        + (project / 'src/graphics-probe.c').read_bytes())
    for architecture, triplet, prefix, libdir, elf_class in [
        ('amd64', 'x86_64-linux-gnu', '/opt/sailfish-graphics', 'lib', 'ELF64'),
        ('i386', 'i386-linux-gnu', '/usr/lib/sailfish-live/mesa', '.', 'ELF32'),
    ]:
        destination = base / architecture
        destination.mkdir(exist_ok=True)
        build, stage, payload = (destination / name for name in ['build', 'stage', 'payload'])
        marker = destination / 'complete.json'
        fingerprint = hashlib.sha256(fingerprint_base + architecture.encode()).hexdigest()
        if verify(marker, fingerprint, payload):
            print('Verified cached Mesa', architecture, flush=True)
            continue
        arguments = [venv / 'bin/meson', 'setup', build, source, '--native-file', native,
                     '--prefix=' + prefix, '--libdir=' + libdir, '--buildtype=release',
                     '--wrap-mode=nodownload', *config['meson_options']]
        if architecture == 'i386':
            arguments += ['--cross-file', cross, '-Dmesa-clc=system']
            env['PATH'] = (str(base / 'amd64/build/src/compiler/clc') + ':'
                           + str(base / 'amd64/build/src/compiler/spirv') + ':'
                           + str(venv / 'bin') + ':' + os.environ['PATH'])
        else:
            arguments += ['-Dinstall-mesa-clc=true']
        if (build / 'meson-private/coredata.dat').exists():
            arguments.append('--reconfigure')
        run(arguments, env=env)
        run([venv / 'bin/meson', 'compile', '-C', build, '-j', os.environ.get('SFOS_JOBS', '4')], env=env)
        if stage.exists():
            shutil.rmtree(stage)
        run([venv / 'bin/meson', 'install', '-C', build, '--no-rebuild', '--skip-subprojects',
             '--destdir', stage], env=env)
        if payload.exists():
            shutil.rmtree(payload)
        libraries = payload / prefix.lstrip('/') / libdir
        shutil.copytree(stage / prefix.lstrip('/') / libdir, libraries, symlinks=True)
        shutil.rmtree(libraries / 'pkgconfig', ignore_errors=True)
        dependency_bundle(libraries, triplet, prefix + ('/lib' if architecture == 'amd64' else ''))
        probe = payload / 'usr/local/bin/sailfish-graphics-probe'
        probe.parent.mkdir(parents=True, exist_ok=True)
        run(['gcc', *(['-m32'] if architecture == 'i386' else []), '-O2', '-Wall', '-Wextra', '-Werror',
             '-I' + str(stage / prefix.lstrip('/') / 'include'), '-L' + str(libraries),
             project / 'src/graphics-probe.c', '-o', probe, '-lEGL', '-lGLESv2',
             '-lwayland-client', '-lwayland-server', '-lgbm', '-Wl,-rpath,' + prefix
             + ('/lib' if architecture == 'amd64' else '')])
        vendor = payload / ('usr/share/glvnd/egl_vendor.d' if architecture == 'i386'
                            else 'opt/sailfish-graphics/share/glvnd/egl_vendor.d')
        vendor.mkdir(parents=True, exist_ok=True)
        (vendor / '50_mesa.json').write_text(json.dumps({
            'file_format_version': '1.0.0',
            'ICD': {'library_path': prefix + ('/lib' if architecture == 'amd64' else '') + '/libEGL_mesa.so.0'}
        }, indent=2) + '\n')
        if architecture == 'i386':
            graphics = libraries / 'graphics'
            graphics.mkdir()
            # Only graphics SONAMEs get global cache precedence. Dependencies
            # stay private and use the RPATH of the library which needs them.
            for name in ['libEGL.so.1', 'libEGL_mesa.so.0', 'libGLESv2.so.2',
                         'libgbm.so.1', 'libGLdispatch.so.0', 'libgallium-' + config['version'] + '.so']:
                (graphics / name).symlink_to('../' + name)
            loader = payload / 'etc/ld.so.conf.d'
            loader.mkdir(parents=True)
            (loader / '00-000-sailfish-live-graphics.conf').write_text(prefix + '/graphics\n')
        for path in libraries.rglob('*'):
            if path.is_file() and not path.is_symlink() and path.read_bytes()[:4] == b'\x7fELF':
                header = subprocess.check_output(['readelf', '-h', path], text=True)
                if elf_class not in header:
                    raise RuntimeError('Wrong architecture: ' + str(path))
        (libraries / 'MESA-LICENSE.txt').write_text((source / 'docs/license.rst').read_text())
        (libraries / 'MESA-BUILD.json').write_text(json.dumps(config, indent=2) + '\n')
        files = {str(path.relative_to(payload)): sha256(path) for path in payload.rglob('*')
                 if path.is_file() and not path.is_symlink()}
        links = {str(path.relative_to(payload)): str(path.readlink()) for path in payload.rglob('*') if path.is_symlink()}
        marker.write_text(json.dumps({'architecture': architecture, 'fingerprint': fingerprint,
                                     'files': files, 'links': links, 'config': config}, indent=2) + '\n')
        print('Built Mesa', config['version'], architecture, 'with legacy Wayland', flush=True)
    shutil.copy2('/etc/graphics-sdk-packages.tsv', base / 'sdk-packages.tsv')


if __name__ == '__main__':
    main()
