"""Check an installed compiled SDK without connecting to any device."""

import importlib
from importlib.machinery import EXTENSION_SUFFIXES
from importlib.metadata import distribution
from pathlib import Path
import subprocess
import sys

import looktech_glasses_sdk
from looktech_glasses_sdk import GlassesSession, DeviceCaptureState
from looktech_glasses_sdk.protocol import CaptureKind, CaptureSource, CaptureState


def main():
    package = Path(looktech_glasses_sdk.__file__).parent
    assert any(str(looktech_glasses_sdk.__file__).endswith(suffix) for suffix in EXTENSION_SUFFIXES)
    assert not list(package.rglob('*.py')), 'Installed SDK contains implementation source'
    assert (package / 'py.typed').is_file()
    assert looktech_glasses_sdk.__version__ == distribution('looktech-glasses-sdk').version
    for name in looktech_glasses_sdk.__all__:
        assert hasattr(looktech_glasses_sdk, name), name
    for file in distribution('looktech-glasses-sdk').files:
        if str(file).startswith('looktech_glasses_sdk/') and str(file).endswith('.pyi'):
            name = Path(str(file)).stem
            if name in ('mac_bt', 'rfcomm_transport') and sys.platform != 'darwin':
                continue
            module = importlib.import_module('looktech_glasses_sdk' if name == '__init__' else 'looktech_glasses_sdk.' + name)
            assert any(module.__file__.endswith(suffix) for suffix in EXTENSION_SUFFIXES), name
    state = DeviceCaptureState.parse(bytes((1, 1, 4, 0, 2, 4, 2, 0)))
    assert state.photo.kind == CaptureKind.PHOTO and state.photo.source == CaptureSource.LOCAL
    assert state.photo.state == CaptureState.DONE and state.video.state == CaptureState.RECORDING
    session = GlassesSession(bt='auto')
    assert not session.is_connected
    session.close()
    if sys.platform == 'darwin':
        import objc
        from looktech_glasses_sdk.mac_bt import _Delegate, _channel_worker
        from looktech_glasses_sdk.rfcomm_transport import _ChannelDelegate

        assert callable(_channel_worker)
        for delegate in (_Delegate, _ChannelDelegate):
            for method in ('initWithOwner_', 'rfcommChannelOpenComplete_status_',
                           'rfcommChannelData_data_length_', 'rfcommChannelClosed_'):
                assert isinstance(getattr(delegate, method), objc.selector), (delegate, method)
        # Imports run in a separate interpreter, as the macOS channel workers do.
        subprocess.run([sys.executable, '-I', '-c',
                        'from looktech_glasses_sdk.mac_bt import _channel_worker; assert callable(_channel_worker)'],
                       check=True, timeout=30)
    print('Installed compiled SDK verified:', looktech_glasses_sdk.__version__, looktech_glasses_sdk.__file__)


if __name__ == '__main__':
    main()
